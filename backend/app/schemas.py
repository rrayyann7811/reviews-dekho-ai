"""Request and response shapes. JSON uses camelCase to match the frontend."""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


Domain = Literal["product", "app"]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


def _strip_or_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# ---------- Products ----------

class ProductCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200, examples=["Kestrel Orbit 5G"])
    brand: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    domain: Domain = Field(default="product", description="What is reviewed: a physical product or an app")

    _clean = field_validator("name", "brand", "category", mode="before")(_strip_or_none)


class ProductUpdate(ApiModel):
    """Only the fields sent are changed. A new domain applies from the next analysis run."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    domain: Domain | None = None

    _clean = field_validator("name", "brand", "category", mode="before")(_strip_or_none)


class SourceDetails(ApiModel):
    """Where the reviews came from. Link fields are only set for products collected from a link."""
    source_url: str | None = None
    source_site: str | None = Field(default=None, examples=["apple_app_store"])
    source_site_name: str | None = Field(default=None, examples=["Apple App Store"])
    source_region: str | None = Field(default=None, examples=["in"])
    collected_at: dt.datetime | None = None


class ProductSummary(SourceDetails):
    """One row in the product list / history table."""
    id: int
    name: str
    brand: str | None
    category: str | None
    source: str = Field(description="upload | url | manual")
    domain: str = "product"
    file_name: str | None = None
    created_at: dt.datetime
    total_reviews: int
    average_rating: float | None
    positive_percent: float | None
    analyzed_at: dt.datetime | None


class UrlRequest(ApiModel):
    url: str = Field(min_length=1, max_length=2000,
                     examples=["https://apps.apple.com/in/app/whatsapp-messenger/id310633997"])


class SupportedSite(ApiModel):
    id: str
    name: str
    status: Literal["supported", "unavailable"]
    hosts: list[str]
    note: str
    example: str | None


# ---------- Reviews ----------

class ReviewIn(ApiModel):
    text: str = Field(min_length=1, max_length=5000)
    rating: int | None = Field(default=None, ge=1, le=5)
    date: dt.date | None = None
    title: str | None = Field(default=None, max_length=300)
    reviewer: str | None = Field(default=None, max_length=120)
    id: str | None = Field(default=None, max_length=100, description="Your own review ID; generated if omitted.")

    _clean = field_validator("text", "title", "reviewer", "id", mode="before")(_strip_or_none)


class ReviewsCreate(ApiModel):
    reviews: list[ReviewIn] = Field(min_length=1, max_length=1000)


class AspectMention(ApiModel):
    aspect: str
    sentiment: str
    score: float
    snippet: str


class ReviewOut(ApiModel):
    id: str = Field(description="The review ID shown to users")
    text: str
    rating: int | None
    date: dt.date | None
    title: str | None
    reviewer: str | None
    sentiment: str | None = Field(description="Null when the review couldn’t be analysed (see status)")
    score: float | None
    mixed: bool
    aspects: list[AspectMention]
    # Defaults describe runs made before Phase 4, whose snapshots don't have these fields.
    status: str = Field(default="analysed", description="analysed | language_not_supported | not_analysed_yet")
    language: str | None = None
    used_title: bool = Field(default=False, description="The title was analysed with a very short review text")


class ReviewPage(ApiModel):
    analysis_id: int | None = None
    total: int
    offset: int = 0
    limit: int = 20
    items: list[ReviewOut]


# ---------- Analysis ----------

class AnalysisProduct(SourceDetails):
    id: int
    name: str
    brand: str | None
    category: str | None
    source: str
    domain: str = "product"


class Analysis(ApiModel):
    """Full analysis of a product, in the same shape as the frontend's demo data."""
    analysis_id: int
    product: AnalysisProduct
    stats: dict
    aspects: list[dict]
    keywords: list[dict]
    summary: dict
    reviews: list[ReviewOut]
    ingestion: dict | None
    analyzed_at: dt.datetime
    engine: dict | None = Field(default=None, description="Sentiment engine and pipeline version used for this run")
    tone_by_rating: list[dict] = Field(default_factory=list,
                                       description="Per star rating: reviews reading positive / neutral / negative")
    reviews_included: bool = Field(default=True, description="False when requested with include_reviews=false")


class HistoryEntry(ApiModel):
    id: int
    product_id: int
    product_name: str
    source: str
    created_at: dt.datetime
    total_reviews: int
    average_rating: float | None
    positive_percent: float | None
    negative_percent: float | None
    engine: dict | None = None


class HistoryDetail(HistoryEntry):
    stats: dict
    aspects: list[dict]
    keywords: list[dict]
    summary: dict
    ingestion: dict | None
    reviews: list[ReviewOut] | None = Field(
        description="Every review exactly as analysed in this run. Null for runs made before Phase 3.")


# ---------- Uploads ----------

class ColumnMap(ApiModel):
    """Which file column holds each field. Only `text` is required."""
    text: str
    rating: str | None = None
    date: str | None = None
    title: str | None = None
    reviewer: str | None = None
    product_name: str | None = None
    id: str | None = None


class UploadPreview(ApiModel):
    file_name: str
    row_count: int
    columns: list[str]
    sample_rows: list[dict]
    detected: dict[str, str | None]
    product_name: str | None
    warnings: list[str]


class Health(ApiModel):
    status: Literal["ok"]
    database: Literal["ok"]
    version: str


class ErrorResponse(BaseModel):
    detail: str
    errors: list[dict] | None = None


# ---------- Comparison (Phase 7) ----------

class ComparisonCaveat(ApiModel):
    code: str = Field(examples=["small-sample"])
    severity: Literal["warning", "info"]
    message: str


class ComparisonSide(ApiModel):
    """One side of a comparison, read from its stored analysis run."""
    product: dict
    run: dict = Field(description="id, createdAt, isLatest, latestRunId, summaryVersion")
    engine: dict = Field(description="Sentiment method of this run (runs before Phase 4: VADER, pipeline 1)")
    counts: dict = Field(description="total, analysed, notAnalysed, notAnalysedReasons, rated")
    date_range: dict | None
    sentiment: dict | None = Field(description="Per tone {count, n, percent, interval}; null when not measurable "
                                               "(nothing analysed, or an old run without counts) — never 0%")
    ratings: dict = Field(description="rated, average, distribution, and the store's own rating for context")


class Comparison(ApiModel):
    """Two stored analysis runs side by side. Computed on request; nothing is stored or re-analysed."""
    a: ComparisonSide
    b: ComparisonSide
    same_product: bool
    same_run: bool
    sentiment: dict | None = Field(description="Per tone: {a, b, difference (points), separation: clear | "
                                               "overlapping | too-few | not-measurable}")
    features: list[dict] = Field(description="Every feature mentioned on at least one side, with per-side status: "
                                             "compared | few-mentions | not-mentioned | not-looked-for | unknown")
    caveats: list[ComparisonCaveat]
    statements: list[str] = Field(description="Deterministic sentences built only from the figures above")
    notes: list[str]
    thresholds: dict
