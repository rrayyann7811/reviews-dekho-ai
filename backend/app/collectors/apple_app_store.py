"""Apple App Store: app details and customer reviews from Apple's public feeds.

Sources (both public, published by Apple, no account or key needed):
* iTunes Lookup API  https://itunes.apple.com/lookup?id=<app id>&country=<cc>
  -> app name, developer, category, overall store rating.
* Customer reviews feed
  https://itunes.apple.com/<cc>/rss/customerreviews/page=<n>/id=<app id>/sortby=mostrecent/json
  -> the most recent written reviews: star rating (1-5), title, text, author, date.

Limits of the source, shown to the user:
* At most 10 pages x 50 = 500 of the most recent reviews per app and country.
* Reviews are per country storefront: the India store (in) and the US store (us)
  have different reviews.
"""
import re
import time
from urllib.parse import ParseResult

from .. import config
from .base import (CollectedProduct, NoReviewsFound, ProductNotFound, ProductRef, SourceAdapter,
                   SourceUnavailable, UnsupportedLink)
from .http import get_json

LOOKUP_URL = "https://itunes.apple.com/lookup"
REVIEWS_URL = "https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"

# /in/app/whatsapp-messenger/id310633997, /app/id310633997, /us/app/some-name/id123?platform=iphone
_APP_PATH = re.compile(r"^/(?:(?P<country>[a-z]{2})/)?app/(?:[^/]+/)?id(?P<app_id>\d{5,12})/?$", re.IGNORECASE)


# Data from another website is never trusted to have the expected shape: anything unexpected is
# treated as missing, never as a crash.

def _label(node, key: str) -> str | None:
    value = node.get(key) if isinstance(node, dict) else None
    if isinstance(value, list):  # some feeds send both a text and an HTML "content"
        dicts = [v for v in value if isinstance(v, dict)]
        value = next((v for v in dicts if (v.get("attributes") or {}).get("type") == "text"),
                     dicts[0] if dicts else None)
    if isinstance(value, dict):
        value = value.get("label")
    return value if isinstance(value, str) else None


def parse_review_entry(entry) -> dict | None:
    """Turn one feed entry into a raw review record, or None if it isn't a review."""
    if not isinstance(entry, dict) or "im:rating" not in entry:  # older feeds start with an entry about the app
        return None
    return {
        "id": _label(entry, "id"),
        "text": _label(entry, "content"),
        "title": _label(entry, "title"),
        "rating": _label(entry, "im:rating"),
        "date": _label(entry, "updated"),
        "reviewer": _label(entry.get("author"), "name"),
    }


def _entries(feed) -> list:
    """The review entries of a feed page. Raises SourceUnavailable if the page isn't a feed at all."""
    body = feed.get("feed") if isinstance(feed, dict) else None
    if not isinstance(body, dict):
        raise SourceUnavailable("Apple App Store sent a review page in an unexpected format. Please try again later.")
    entries = body.get("entry") or []
    if isinstance(entries, dict):  # one review is sent as an object, not a list
        return [entries]
    return entries if isinstance(entries, list) else []


def _apple_link(value, fallback: str) -> str:
    """Use Apple's own app link only if it really is an Apple https link (it's shown as a clickable link)."""
    if isinstance(value, str):
        link = value.split("?")[0]
        if any(link.startswith(f"https://{host}/") for host in AppleAppStoreAdapter.hosts):
            return link
    return fallback


class AppleAppStoreAdapter(SourceAdapter):
    id = "apple_app_store"
    name = "Apple App Store"
    hosts = ("apps.apple.com", "itunes.apple.com")
    status = "supported"
    note = ("Apps on the App Store. Up to the 500 most recent written reviews from the country store in the link, "
            "through Apple’s public review feed.")
    example = "https://apps.apple.com/in/app/whatsapp-messenger/id310633997"

    def parse(self, url: ParseResult) -> ProductRef:
        match = _APP_PATH.match(url.path)
        if not match:
            raise UnsupportedLink("This App Store link isn’t an app page. Open the app on apps.apple.com and copy "
                                  "the link from the address bar (it contains “/app/” and “id” followed by numbers).")
        country = (match["country"] or config.APPLE_DEFAULT_COUNTRY).lower()
        app_id = match["app_id"]
        return ProductRef(site=self.id, product_id=app_id, region=country,
                          url=f"https://apps.apple.com/{country}/app/id{app_id}")

    def _fetch_page(self, http, ref: ProductRef, page: int) -> list[dict] | None:
        """Reviews on one feed page; [] for an empty page; None when Apple says the page doesn't exist."""
        if config.APPLE_PAGE_DELAY_SECONDS:
            time.sleep(config.APPLE_PAGE_DELAY_SECONDS)  # be polite to Apple's servers
        url = REVIEWS_URL.format(country=ref.region, page=page, app_id=ref.product_id)
        feed = get_json(http, url, self.name, not_found_ok=True)
        if feed is None:
            return None
        return [r for r in map(parse_review_entry, _entries(feed)) if r]

    def collect(self, ref: ProductRef, http) -> CollectedProduct:
        lookup = get_json(http, LOOKUP_URL, self.name, params={"id": ref.product_id, "country": ref.region},
                          not_found_ok=True)
        results = lookup.get("results") if isinstance(lookup, dict) else None
        app = next((r for r in (results if isinstance(results, list) else [])
                    if isinstance(r, dict) and str(r.get("trackId")) == ref.product_id), None)
        if app is None:
            raise ProductNotFound(f"No app with ID {ref.product_id} was found in the App Store for country "
                                  f"“{ref.region.upper()}”. It may have been removed or may not be available there.")

        def text(key):
            value = app.get(key)
            return value.strip() if isinstance(value, str) and value.strip() else None

        def number(key):
            value = app.get(key)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        reviews, pages_with_reviews, empty_in_a_row, stopped_early = [], 0, 0, None
        for page in range(1, config.APPLE_MAX_PAGES + 1):
            try:
                page_reviews = self._fetch_page(http, ref, page)
                if page_reviews == []:
                    # Apple's feed sometimes returns an empty page in the middle (verified: page 2 empty,
                    # pages 3-10 full). Ask once more before treating it as empty.
                    page_reviews = self._fetch_page(http, ref, page)
            except SourceUnavailable as exc:
                if page == 1:
                    raise
                stopped_early = exc.message  # keep what was collected; tell the user why it's incomplete
                break
            if page_reviews is None:
                break  # Apple answers 400 past the last page
            if not page_reviews:
                empty_in_a_row += 1
                if empty_in_a_row == 2:
                    break  # two empty pages in a row: there are no more reviews
                continue
            empty_in_a_row = 0
            pages_with_reviews += 1
            reviews.extend(page_reviews)

        if not reviews:
            raise NoReviewsFound(f"“{text('trackName') or 'This app'}” has no written reviews in the "
                                 f"{ref.region.upper()} App Store yet, so there is nothing to analyse. "
                                 "Try the link for another country’s store.")

        return CollectedProduct(
            name=text("trackName") or f"App {ref.product_id}",
            brand=text("sellerName") or text("artistName"),
            category=text("primaryGenreName"),
            url=_apple_link(app.get("trackViewUrl"), ref.url),
            reviews=reviews,
            details={
                "storeRating": number("averageUserRating"),
                "storeRatingCount": number("userRatingCount"),
                "pagesRead": pages_with_reviews,
                "sourceLimit": "Apple’s public feed lists at most the 500 most recent written reviews "
                               "for each country store.",
                **({"stoppedEarly": stopped_early} if stopped_early else {}),
            },
        )
