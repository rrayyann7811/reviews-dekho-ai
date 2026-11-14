"""Websites we recognise but cannot collect reviews from.

Checked in Phase 3 (see docs/PLAN.md, "Review sources investigated"):
* Amazon — the Product Advertising API and Selling Partner API don't return review text,
  and Amazon's Conditions of Use prohibit automated collection (scraping).
* Flipkart — the Affiliate API offers product, offer and report data but no reviews,
  and the site's terms prohibit scraping.
Recognising the link still helps: the user gets a specific explanation and is pointed to
the CSV/Excel upload instead.
"""
import re
from urllib.parse import ParseResult

from ..errors import AppError
from .base import CollectionNotPermitted, ProductRef, SourceAdapter

_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d|product-reviews)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)
_FLIPKART_ITEM = re.compile(r"/p/(itm[0-9a-z]+)", re.IGNORECASE)


class _NotPermittedAdapter(SourceAdapter):
    status = "unavailable"
    reason = ""

    def product_hint(self, url: ParseResult) -> str:
        return ""

    def parse(self, url: ParseResult) -> ProductRef:
        raise CollectionNotPermitted(f"{self.product_hint(url)}{self.reason} If you have the reviews as a CSV or "
                                     "Excel file (for example, exported by the seller), upload them instead.")


class AmazonAdapter(_NotPermittedAdapter):
    id = "amazon"
    name = "Amazon"
    hosts = ("amazon.in", "amazon.com", "amazon.co.uk", "amzn.in", "amzn.to", "amzn.eu")
    note = "Link recognised. Amazon does not provide public access to reviews, so they cannot be collected automatically."
    reason = ("Amazon’s official APIs don’t provide review text, and its terms don’t allow reviews to be "
              "collected automatically, so this app can’t analyse Amazon links.")

    def product_hint(self, url: ParseResult) -> str:
        match = _ASIN.search(url.path)
        return f"This is Amazon product {match[1].upper()}. " if match else ""


class FlipkartAdapter(_NotPermittedAdapter):
    id = "flipkart"
    name = "Flipkart"
    hosts = ("flipkart.com", "dl.flipkart.com")
    note = "Link recognised. Flipkart does not provide public access to reviews, so they cannot be collected automatically."
    reason = ("Flipkart’s official API doesn’t provide reviews, and its terms don’t allow reviews to be "
              "collected automatically, so this app can’t analyse Flipkart links.")

    def product_hint(self, url: ParseResult) -> str:
        match = _FLIPKART_ITEM.search(url.path)
        return f"This is Flipkart item {match[1]}. " if match else ""


class DemoStoreAdapter(SourceAdapter):
    """The fictional demo store. Its one product is built into the frontend and works offline."""
    id = "demo"
    name = "Demo store"
    hosts = ("demo.reviewsdekho.test",)
    status = "supported"
    note = "Sample products with synthetic reviews, for trying every feature."
    example = "https://demo.reviewsdekho.test/product/kestrel-orbit-5g"

    def parse(self, url: ParseResult) -> ProductRef:
        raise AppError("The demo product is built into the app and opens without the server. "
                       "Use the demo link on the Analyze page.", 422)
