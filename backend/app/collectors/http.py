"""A small HTTP helper for adapters: timeouts, a clear User-Agent and friendly errors."""
import httpx
import json

from .. import config
from ..version import VERSION
from .base import SourceUnavailable

# Identifies the app without any personal details.
USER_AGENT = f"ReviewsDekhoAI/{VERSION} (student project; review analysis)"


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(config.COLLECT_TIMEOUT_SECONDS),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def get_json(client: httpx.Client, url: str, site_name: str, params: dict | None = None,
             not_found_ok: bool = False):
    """GET a JSON document. Returns None for 404 (or 400) when not_found_ok, else raises SourceUnavailable."""
    try:
        with client.stream("GET", url, params=params, headers={"Accept-Encoding": "identity"}) as response:
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise SourceUnavailable("The review source returned unsupported compressed content.")
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                if len(content) + len(chunk) > config.MAX_COLLECTION_BYTES:
                    raise SourceUnavailable("The review source response exceeds the configured size limit.")
                content.extend(chunk)
    except httpx.TimeoutException as exc:
        raise SourceUnavailable(f"{site_name} took too long to respond. Please try again in a minute.", 504) from exc
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"Couldn’t connect to {site_name}. Check your internet connection and "
                                "try again.") from exc

    if response.status_code in (400, 404) and not_found_ok:
        return None
    if response.status_code == 429:
        raise SourceUnavailable(f"{site_name} is limiting how often reviews can be requested. "
                                "Please wait a minute and try again.", 503)
    if response.status_code >= 400:
        raise SourceUnavailable(f"{site_name} returned an error (HTTP {response.status_code}). "
                                "Please try again later.")
    try:
        return json.loads(content)
    except ValueError as exc:
        raise SourceUnavailable(f"{site_name} sent a response that couldn’t be read. "
                                "Please try again later.") from exc
