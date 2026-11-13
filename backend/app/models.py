"""Database tables.

    Product 1 ──< Review           the reviews belonging to a product
    Product 1 ──< AnalysisResult   one row per analysis run (the history)

Per-review results (sentiment, score, aspects) are stored on the Review row
and reflect the latest analysis. Product-level results (stats, aspects,
keywords, summary) are stored on each AnalysisResult, so earlier runs remain
viewable in the history.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

SOURCES = ("upload", "url", "manual")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # one of SOURCES
    source_url: Mapped[str | None] = mapped_column(String(2000))
    file_name: Mapped[str | None] = mapped_column(String(255))
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

    # Filled in by the analysis (None until the product has been analysed).
    sentiment: Mapped[str | None] = mapped_column(String(10))
    score: Mapped[float | None] = mapped_column(Float)
    mixed: Mapped[bool] = mapped_column(Boolean, default=False)
    aspects: Mapped[list] = mapped_column(JSON, default=list)

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
    ingestion: Mapped[dict | None] = mapped_column(JSON)  # cleaning report from the upload, if any

    product: Mapped[Product] = relationship(back_populates="analyses")
