"""Database tables.

    Product 1 ──< Review           the reviews belonging to a product (input data)
    Product 1 ──< AnalysisResult   one row per analysis run (the history)

Each AnalysisResult is a complete, unchanging snapshot of one run: the
product-level results (stats, aspects, keywords, summary) AND the per-review
results (`review_results`: every review as it was analysed). Adding or
deleting reviews later never changes an earlier run.

Changing these tables? Add append-only SQLite and PostgreSQL/Alembic migrations as well.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .db_types import UTCDateTime

SOURCES = ("upload", "url", "manual")  # url = collected from a product link


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    # A collected product (e.g. one App Store app in one country) is stored once and refreshed, not duplicated.
    __table_args__ = (Index("uq_collected_product", "owner_id", "source_site", "external_product_id", "source_region",
                            unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Derived exclusively from a verified (issuer, subject), or the reserved local workspace.
    owner_id: Mapped[str] = mapped_column(String(64), default="local", server_default="local", index=True)
    # Fixed product lifetime: refreshing/re-analysing never extends retention. Local data is not expired.
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # one of SOURCES
    # What was reviewed: "product" (physical product) or "app". Chooses the feature list used in analysis.
    domain: Mapped[str] = mapped_column(String(20), default="product", server_default="product")
    source_url: Mapped[str | None] = mapped_column(String(2000))
    file_name: Mapped[str | None] = mapped_column(String(255))
    # Only for products collected from a link (source == "url"):
    source_site: Mapped[str | None] = mapped_column(String(40))           # adapter id, e.g. "apple_app_store"
    external_product_id: Mapped[str | None] = mapped_column(String(100))  # the site's own product ID
    source_region: Mapped[str | None] = mapped_column(String(10))         # storefront / country code
    collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True, order_by="Review.id")
    analyses: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True,
        order_by="AnalysisResult.id.desc()")
    jobs: Mapped[list["ProcessingJob"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)

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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

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
    # Which sentiment engine and NLP pipeline version produced this run (see app/nlp/engines.py).
    engine: Mapped[dict | None] = mapped_column(JSON)

    product: Mapped[Product] = relationship(back_populates="analyses")
    ai_summaries: Mapped[list["AiSummary"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True, order_by="AiSummary.id.desc()")


class AiSummary(Base):
    """One attempt at an optional AI-written overview of an analysis run (see services/ai_summary.py).

    Stored separately so the run and its evidence-backed summary are never changed. Every attempt is
    kept, including rejected ones, together with the checker's findings.
    """
    __tablename__ = "ai_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_results.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))      # accepted | rejected
    attempts: Mapped[int] = mapped_column(Integer)
    sentences: Mapped[list] = mapped_column(JSON)        # [{text, claims, excerpts}] — accepted output, else []
    problems: Mapped[list] = mapped_column(JSON)         # checker findings of the last attempt

    analysis: Mapped[AnalysisResult] = relationship(back_populates="ai_summaries")


class ProcessingJob(Base):
    """Durable analysis work; ownership and expiry always come from the product root."""
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("uq_job_request", "product_id", "request_key", unique=True),
        Index("ix_job_queue", "status", "available_at", "id"),
        Index("ix_job_lease", "status", "lease_until", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[dict | None] = mapped_column(JSON)
    result_analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_results.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), default="analysis", server_default="analysis")
    request_key: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    claim_token: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(String(160))


class ImportReceipt(Base):
    """A committed import result or a tombstone until its original expiry."""

    __tablename__ = "import_receipts"
    __table_args__ = (UniqueConstraint("owner_id", "request_key", name="uq_import_receipt_owner_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    result: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
