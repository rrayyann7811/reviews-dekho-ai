"""Collect reviews from a product link, store them and analyse them.

Flow:  link -> validate -> pick the website's adapter -> product ID
            -> download product + reviews (adapter) -> clean (same rules as uploads)
            -> store (new product, or new reviews for a product collected before)
            -> analyse with the NLP pipeline -> new history entry
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..collectors.base import NoReviewsFound, ProductRef, SourceAdapter, UnsupportedLink
from ..collectors.http import make_client
from ..collectors.registry import ADAPTERS, find_adapter, host_of, validate_url
from ..errors import AppError
from ..models import Product
from .analysis import run_analysis
from .ingestion import clean_records
from .products import add_reviews


def supported_sites_text() -> str:
    return ", ".join(a.name for a in ADAPTERS if a.status == "supported" and a.id != "demo")


def collect_from_url(db: Session, raw_url: str, http=None) -> tuple[Product, bool]:
    """Returns (product, created). A product collected before is refreshed instead of duplicated."""
    url = validate_url(raw_url)
    adapter = find_adapter(url)
    if adapter is None:
        raise UnsupportedLink(f"{host_of(url)} isn’t a supported website. Reviews can be collected from: "
                              f"{supported_sites_text()}. For any other website, upload the reviews as a CSV or "
                              "Excel file.")
    ref = adapter.parse(url)  # raises a clear error for websites that can't be collected
    existing = db.scalar(select(Product).where(
        Product.source_site == ref.site, Product.external_product_id == ref.product_id,
        Product.source_region == ref.region))
    product = _collect(db, adapter, ref, existing, http)
    return product, existing is None


def refresh_product(db: Session, product: Product, http=None) -> Product:
    """Fetch the latest reviews again for a product that was collected from a link."""
    adapter = next((a for a in ADAPTERS if a.id == product.source_site and a.status == "supported"), None)
    if product.source != "url" or adapter is None:
        raise AppError("Only products collected from a supported link can be refreshed.", 422)
    ref = ProductRef(site=product.source_site, product_id=product.external_product_id,
                     region=product.source_region or "", url=product.source_url or "")
    return _collect(db, adapter, ref, product, http)


def _collect(db: Session, adapter: SourceAdapter, ref: ProductRef, product: Product | None, http) -> Product:
    # 1. Download (no database changes yet, so a network failure leaves nothing half-saved).
    # End the read transaction first: SQLite keeps a lock for as long as a transaction is open, which would
    # block every other write (uploads, other collections) while we wait seconds for the website.
    db.commit()
    if http is None:
        with make_client() as client:
            collected = adapter.collect(ref, client)
    else:
        collected = adapter.collect(ref, http)

    # 2. Clean with the same rules as uploaded files.
    reviews, report = clean_records(collected.reviews)
    if not reviews:
        raise NoReviewsFound(f"{adapter.name} returned {len(collected.reviews)} review(s) for “{collected.name}”, "
                             "but none had any written text to analyse.")

    # 3. Store.
    now = datetime.now(timezone.utc)
    if product is None:
        product = Product(name=collected.name[:200], brand=(collected.brand or "")[:120] or None,
                          category=(collected.category or "")[:120] or None, source="url", domain=adapter.domain,
                          source_url=collected.url, source_site=ref.site, external_product_id=ref.product_id,
                          source_region=ref.region)
        db.add(product)
    added, already_stored = add_reviews(db, product, reviews, skip_existing=True)
    product.collected_at = now

    # 4. Analyse every stored review (earlier collections + new ones) and record how they were collected.
    report["received"] = report.pop("rowsInFile")
    report |= {
        "source": adapter.name,
        "region": ref.region.upper() or None,
        "url": collected.url,
        "newReviews": added,
        "alreadyStored": already_stored,
        "collectedAt": now.isoformat(timespec="seconds"),
        **collected.details,
    }
    run_analysis(db, product, ingestion=report)
    try:
        db.commit()
    except IntegrityError as exc:  # the same product was collected at the same moment by another request
        db.rollback()
        raise AppError("This product is already being collected. Please try again in a moment.", 409) from exc
    return product
