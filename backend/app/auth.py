"""Verified access-token boundary. No account creation, passwords or token minting here.

JWT mode trusts only operator-configured asymmetric keys, issuer and audience. Local mode uses
one reserved workspace and cannot claim JWT-owned data. Test signing keys live only in tests.
"""
import hashlib
import ipaddress
import json
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from . import config

LOCAL_OWNER = "local"
PUBLIC_PATHS = frozenset(("/api/health", "/api/sites"))


@dataclass(frozen=True)
class Principal:
    owner_id: str
    local: bool = False


class TokenVerifier:
    def __init__(self):
        self.issuer, self.audience, self.algorithm = config.AUTH_ISSUER, config.AUTH_AUDIENCE, config.AUTH_ALGORITHM
        if not self.issuer or not self.audience or self.algorithm not in {"RS256", "ES256", "EdDSA"}:
            raise ValueError("JWT mode requires a trusted issuer, audience and supported asymmetric algorithm")
        if bool(config.AUTH_JWKS_FILE) == bool(config.AUTH_JWKS_URL):
            raise ValueError("JWT mode requires exactly one trusted public-key file or HTTPS JWKS URL")
        self.keys = None
        self.client = None
        if config.AUTH_JWKS_FILE:
            data = json.loads(Path(config.AUTH_JWKS_FILE).read_text())
            keys = data.get("keys", [])
            if not keys or any(k.get("kty") not in {"RSA", "EC", "OKP"} or "d" in k or "k" in k for k in keys):
                raise ValueError("JWKS must contain asymmetric public keys only")
            self.keys = {k.key_id: k for k in jwt.PyJWKSet.from_dict(data).keys}
            if None in self.keys or len(self.keys) != len(keys):
                raise ValueError("JWKS keys require unique key IDs")
        else:
            url = urlsplit(config.AUTH_JWKS_URL)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("JWKS URL must be a trusted HTTPS endpoint without credentials or fragment")
            self.client = jwt.PyJWKClient(config.AUTH_JWKS_URL, timeout=3, lifespan=300, cache_keys=False)

    def verify(self, token: str) -> Principal:
        if len(token) > 8192:
            raise jwt.InvalidTokenError("Token too long")
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if (header.get("alg") != self.algorithm or not isinstance(kid, str) or not 1 <= len(kid) <= 128
                or any(k in header for k in ("jku", "jwk", "x5u", "crit"))):
            raise jwt.InvalidTokenError("Unsupported token header")
        if self.keys is not None:
            key = self.keys.get(kid)
            if key is None:
                raise jwt.InvalidTokenError("Unknown signing key")
        else:
            key = self.client.get_signing_key(kid)
        if key.algorithm_name != self.algorithm or key.public_key_use not in (None, "sig"):
            raise jwt.InvalidTokenError("Unexpected signing key")
        claims = jwt.decode(token, key.key, algorithms=[self.algorithm], issuer=self.issuer,
                            audience=self.audience, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        # Explicit user-access-token profile: anon/service-role tokens are never user identities.
        if (claims.get("role") != "authenticated" or claims.get("is_anonymous") is True
                or not isinstance(claims["sub"], str) or not claims["sub"].strip()):
            raise jwt.InvalidTokenError("A user access token is required")
        for name in ("iat", "exp", "nbf"):
            value = claims.get(name)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise jwt.InvalidTokenError("Invalid timestamp")
        if claims["exp"] <= claims["iat"] or len(claims["sub"]) > 256:
            raise jwt.InvalidTokenError("Invalid user token")
        # This application's hosted data API supports password-authenticated sessions only.
        # Supabase's signed AMR distinguishes password and recovery (role/aal do not).
        # Missing evidence fails closed; metadata and browser recovery flags are never evidence.
        amr = claims.get("amr")
        if not isinstance(amr, list) or not 1 <= len(amr) <= 32:
            raise jwt.InvalidTokenError("Password authentication evidence is required")
        methods = set()
        for entry in amr:
            if (not isinstance(entry, dict) or not isinstance(entry.get("method"), str)
                    or not 1 <= len(entry["method"]) <= 64
                    or type(entry.get("timestamp")) not in (int, float)
                    or not math.isfinite(entry["timestamp"])
                    or not 0 <= entry["timestamp"] <= claims["iat"]):
                raise jwt.InvalidTokenError("Invalid authentication evidence")
            methods.add(entry["method"])
        if "password" not in methods or methods.intersection({"recovery", "anonymous"}):
            raise jwt.InvalidTokenError("A non-recovery password session is required")
        owner = hashlib.sha256((self.issuer + "\0" + claims["sub"]).encode()).hexdigest()
        return Principal(owner)


class AuthMiddleware:
    """ASGI middleware authenticates before FastAPI reads multipart bodies or opens DB sessions."""
    def __init__(self, app, mode, verifier=None):
        self.app, self.mode, self.verifier = app, mode, verifier

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        if scope["method"] == "GET" and scope["path"].rstrip("/") in PUBLIC_PATHS:
            return await self.app(scope, receive, send)
        if self.mode == "local":
            host = (scope.get("client") or ("",))[0]
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = host == "testclient"  # in-process TestClient; never a network peer address
            if not loopback:
                return await JSONResponse({"detail": "Local mode only accepts loopback clients. Configure JWT mode for hosted use."},
                                          status_code=403)(scope, receive, send)
            principal = Principal(LOCAL_OWNER, local=True)
        else:
            headers = Headers(scope=scope).getlist("authorization")
            parts = headers[0].split() if len(headers) == 1 else []
            if len(parts) != 2 or parts[0].lower() != "bearer":
                principal = None
            else:
                try:
                    principal = await run_in_threadpool(self.verifier.verify, parts[1])
                except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
                    principal = None
            if principal is None:
                return await JSONResponse({"detail": "A valid user access token is required."}, status_code=401,
                                          headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)
