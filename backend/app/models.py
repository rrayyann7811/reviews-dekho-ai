"""Database tables.

    Product 1 ──< Review           the reviews belonging to a product (input data)
    Product 1 ──< AnalysisResult   one row per analysis run (the history)

Each AnalysisResult is a complete, unchanging snapshot of one run: the
product-level results (stats, aspects, keywords, summary) AND the per-review
results (`review_results`: every review as it was analysed). Adding or
deleting reviews later never changes an earlier run.

Changing these tables? Add a migration in app/migrations.py as well.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

SOURCES = ("upload", "url", "manual")  # url = collected from a product link


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    # A collected product (e.g. one App Store app in one country) is stored once and refreshed, not duplicated.
    __table_args__ = (Index("uq_collected_product", "source_site", "external_product_id", "source_region",
                            unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # one of SOURCES
    source_url: Mapped[str | None] = mapped_column(String(2000))
    file_name: Mapped[str | None] = mapped_column(String(255))
    # Only for products collected from a link (source == "url"):
    source_site: Mapped[str | None] = mapped_column(String(40))           # adapter id, e.g. "apple_app_store"
    external_product_id: Mapped[str | None] = mapped_column(String(100))  # the site's own product ID
    source_region: Mapped[str | None] = mapped_column(String(10))         # storefront / country code
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True, order_by="Review.id")
    analyses: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True,
        order_by="AnalysisResult.id.desc()")

    @property
    def latest_analysis(self) -> "AnalysisResult | None":
        return self.analyses[0] if self.analyses else None


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("product_id", "external_id", name="uq_review_per_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    # The review's ID as shown to users: taken from the file, or generated (R-1, R-2…).
    external_id: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)
    review_date: Mapped[datetime | None] = mapped_column(Date)
    title: Mapped[str | None] = mapped_column(String(300))
    reviewer: Mapped[str | None] = mapped_column(String(120))

    product: Mapped[Product] = relationship(back_populates="reviews")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Headline numbers as columns, so lists and history don't need to load the JSON.
    total_reviews: Mapped[int] = mapped_column(Integer)
    average_rating: Mapped[float | None] = mapped_column(Float)
    positive_percent: Mapped[float] = mapped_column(Float)
    negative_percent: Mapped[float] = mapped_column(Float)

    stats: Mapped[dict] = mapped_column(JSON)
    aspects: Mapped[list] = mapped_column(JSON)
    keywords: Mapped[list] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    ingestion: Mapped[dict | None] = mapped_column(JSON)  # cleaning / collection report, if any
    # Every review as analysed in this run: id, text, rating, date, title, reviewer, sentiment, score, mixed,
    # aspects. None only for runs made before this was stored (databases upgraded from Phase 2).
    review_results: Mapped[list | None] = mapped_column(JSON)

    product: Mapped[Product] = relationship(back_populates="analyses")
