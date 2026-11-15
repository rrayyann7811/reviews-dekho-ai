"""Bounded, process-local fixed windows. No database, network or request body access."""
import hashlib
import ipaddress
import logging
import math
from threading import Lock
from time import monotonic

from starlette.responses import JSONResponse

from . import config

log = logging.getLogger("reviews_dekho")


def operation_groups(scope):
    """ASGI path is already URL-decoded. IDs/query strings never become bucket keys."""
    path = scope["path"].rstrip("/")
    method = scope["method"]
    parts = path.split("/")
    groups = []
    if method == "POST" and path in {"/api/uploads/preview", "/api/uploads/import"}:
        groups.append("ingestion")
        if path.endswith("/import"):
            groups.append("analysis")
    product = len(parts) >= 4 and parts[1:3] == ["api", "products"]
    if method == "POST" and (path == "/api/products/from-url" or
                              (product and len(parts) == 5 and parts[4] == "refresh")):
        groups.extend(("collection", "analysis"))
    if product:
        if (method == "POST" and len(parts) == 5 and parts[4] in {"analyze", "reviews", "jobs"}) or (
                method == "DELETE" and len(parts) == 6 and parts[4] == "reviews"):
            groups.append("analysis")
        if method == "GET" and len(parts) == 5 and parts[4] in {"report.pdf", "report.csv"}:
            groups.append("export")
        if method == "POST" and len(parts) == 5 and parts[4] == "ai-summary":
            groups.append("ai")
    if method == "GET" and path == "/api/ai/status":
        groups.append("ai")
    return tuple(groups)


def peer_key(scope):
    # No Forwarded/X-Forwarded-For parsing here. The ASGI server must preserve the socket peer.
    host = (scope.get("client") or ("",))[0]
    try:
        address = ipaddress.ip_address(host)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        host = str(address)
    except ValueError:
        host = "unknown-peer"  # shared fallback, never an arbitrary client-controlled key
    return hashlib.sha256(host.encode()).digest()


class WindowLimiter:
    """One shared window per identity; atomic all-or-nothing multi-budget consumption.

    Active identities are never evicted to make room. Entries have fixed-size counters and expire
    even while rejected. The lock also supports concurrent threads/event loops in one process.
    """
    def __init__(self, limits, window, capacity, clock=None):
        self.limits = dict(limits)
        if not self.limits or min(self.limits.values()) < 1 or window < 1 or capacity < 1:
            raise ValueError("Rate limits, window and capacity must be positive")
        self.window, self.capacity = window, capacity
        self.clock = clock or monotonic
        self.entries = {}
        self.lock = Lock()
        self.next_sweep = 0

    def check(self, key, groups):
        with self.lock:
            now = self.clock()
            if not math.isfinite(now):
                raise ValueError("Invalid limiter clock")
            if now >= self.next_sweep or len(self.entries) >= self.capacity:
                self.entries = {k: v for k, v in self.entries.items() if v[0] > now}
                self.next_sweep = now + self.window
            record = self.entries.get(key)
            if record is not None and record[0] <= now:
                del self.entries[key]
                record = None
            if record is None:
                if len(self.entries) >= self.capacity:
                    return max(1, math.ceil(min(v[0] for v in self.entries.values()) - now))
                record = (now + self.window, {})
            deadline, counts = record
            groups = set(groups)
            if any(counts.get(group, 0) >= self.limits[group] for group in groups):
                return max(1, math.ceil(deadline - now))
            for group in groups:
                counts[group] = counts.get(group, 0) + 1
            self.entries[key] = record
            return 0


class RateLimitsMiddleware:
    """Outer peer gate protects JWT verification; inner owner gate protects API work."""
    def __init__(self, app, phase):
        self.app, self.phase = app, phase
        self.enabled = config.RATE_LIMIT_ENABLED
        window, capacity = config.RATE_LIMIT_WINDOW_SECONDS, config.RATE_LIMIT_MAX_IDENTITIES
        if phase == "peer":
            self.limiter = WindowLimiter({"peer": config.RATE_LIMIT_PEER_REQUESTS}, window, capacity)
            self.global_limiter = WindowLimiter({"global": config.RATE_LIMIT_GLOBAL_REQUESTS}, window, 1)
        elif phase == "owner":
            self.limiter = WindowLimiter({
                "general": config.RATE_LIMIT_GENERAL_REQUESTS,
                "ingestion": config.RATE_LIMIT_INGESTION_REQUESTS,
                "analysis": config.RATE_LIMIT_ANALYSIS_REQUESTS,
                "collection": config.RATE_LIMIT_COLLECTION_REQUESTS,
                "export": config.RATE_LIMIT_EXPORT_REQUESTS,
                "ai": config.RATE_LIMIT_AI_REQUESTS,
            }, window, capacity)
        else:
            raise ValueError("Unknown rate limiter phase")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.enabled:
            return await self.app(scope, receive, send)
        try:
            if self.phase == "peer":
                # Global attempts count even when the peer table is full. No identity allocation needed.
                retry = self.global_limiter.check(b"global", ("global",))
                if not retry:
                    retry = self.limiter.check(peer_key(scope), ("peer",))
            else:
                principal = scope.get("state", {}).get("principal")
                if principal is None:
                    retry = 0  # public/failed-auth attempts are covered by the outer gate
                else:
                    key = hashlib.sha256(principal.owner_id.encode()).digest()
                    retry = self.limiter.check(key, ("general", *operation_groups(scope)))
        except Exception:
            # Do not log exception text, headers, paths, peer addresses or owner identifiers.
            log.error("API rate limiter unavailable")
            return await JSONResponse({"detail": "Request protection is temporarily unavailable. Please retry shortly."},
                                      status_code=503, headers={"Retry-After": "5"})(scope, receive, send)
        if retry:
            # Fixed log vocabulary; never an attacker-selected label or private data.
            log.info("API rate limit rejected request (%s)", self.phase)
            return await JSONResponse({"detail": "Too many requests. Please retry shortly."},
                                      status_code=429, headers={"Retry-After": str(retry)})(scope, receive, send)
        await self.app(scope, receive, send)
