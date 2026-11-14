"""A small HTTP helper for adapters: timeouts, a clear User-Agent and friendly errors."""
import httpx

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
        response = client.get(url, params=params)
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
        return response.json()
    except ValueError as exc:
        raise SourceUnavailable(f"{site_name} sent a response that couldn’t be read. "
                                "Please try again later.") from exc
