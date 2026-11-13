"""Recognise product links. Mirrors frontend/src/lib/sites.js.

No website is scraped. Collecting reviews from a link needs a permitted
source (an official API or licensed data provider) — see docs/PLAN.md.
"""
from urllib.parse import urlparse

from ..errors import AppError

SITES = {
    "amazon": ("Amazon", ["amazon.in", "amazon.com", "amzn.in", "amzn.to"]),
    "flipkart": ("Flipkart", ["flipkart.com", "dl.flipkart.com"]),
    "demo": ("Demo store", ["demo.reviewsdekho.test"]),
}


def detect_site(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for site_id, (_, hosts) in SITES.items():
        if any(host == h or host.endswith(f".{h}") for h in hosts):
            return site_id
    return None


def collect_from_url(url: str):
    site = detect_site(url)
    if site == "demo":
        raise AppError("The demo product is built into the app and opens without the server. "
                       "Use the demo link on the Analyze page.", 422)
    if site in ("amazon", "flipkart"):
        name = SITES[site][0]
        raise AppError(f"{name} doesn’t provide public access to its reviews, so they can’t be collected "
                       "automatically. Export the reviews to CSV or Excel and upload the file instead.", 422)
    host = urlparse(url).hostname or url
    raise AppError(f"{host} isn’t a supported website. Upload the reviews as a CSV or Excel file instead.", 422)
