"""The list of website adapters, and URL validation."""
from urllib.parse import ParseResult, urlparse

from .apple_app_store import AppleAppStoreAdapter
from .base import SourceAdapter, UnsupportedLink
from .restricted import AmazonAdapter, DemoStoreAdapter, FlipkartAdapter

# To support a new website: write an adapter class and add it here.
ADAPTERS: list[SourceAdapter] = [DemoStoreAdapter(), AppleAppStoreAdapter(), AmazonAdapter(), FlipkartAdapter()]

INVALID = "This doesn’t look like a web address. Copy the link from your browser’s address bar."


def validate_url(raw: str) -> ParseResult:
    """Check a user-supplied link and return it parsed. Adds https:// if the scheme is missing."""
    text = (raw or "").strip()
    if not text or any(c.isspace() for c in text) or len(text) > 2000:
        raise UnsupportedLink(INVALID)
    if "://" not in text:
        text = f"https://{text}"
    try:
        url = urlparse(text)
        host = (url.hostname or "").lower()
    except ValueError as exc:
        raise UnsupportedLink(INVALID) from exc
    if url.scheme not in ("http", "https") or "." not in host or url.username or url.password:
        raise UnsupportedLink(INVALID)
    return url


def host_of(url: ParseResult) -> str:
    return (url.hostname or "").lower().removeprefix("www.")


def find_adapter(url: ParseResult) -> SourceAdapter | None:
    host = host_of(url)
    return next((a for a in ADAPTERS if a.matches(host)), None)


def site_name(site_id: str | None) -> str | None:
    return next((a.name for a in ADAPTERS if a.id == site_id), None) if site_id else None
