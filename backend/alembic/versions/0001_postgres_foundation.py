"""Empty PostgreSQL database baseline; independent of the legacy SQLite version numbers."""
from alembic import op
import sqlalchemy as sa

revision = "0001_postgres"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False, server_default="local"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(120)), sa.Column("category", sa.String(120)),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False, server_default="product"),
        sa.Column("source_url", sa.String(2000)), sa.Column("file_name", sa.String(255)),
        sa.Column("source_site", sa.String(40)), sa.Column("external_product_id", sa.String(100)),
        sa.Column("source_region", sa.String(10)), sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_products_owner_id", "products", ["owner_id"])
    op.create_index("ix_products_expires_at", "products", ["expires_at"])
    op.create_index("uq_collected_product", "products", ["owner_id", "source_site", "external_product_id", "source_region"], unique=True)
    op.create_table("reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer()), sa.Column("review_date", sa.Date()),
        sa.Column("title", sa.String(300)), sa.Column("reviewer", sa.String(120)),
        sa.UniqueConstraint("product_id", "external_id", name="uq_review_per_product"))
    op.create_index("ix_reviews_product_id", "reviews", ["product_id"])
    op.create_table("analysis_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_reviews", sa.Integer(), nullable=False), sa.Column("average_rating", sa.Float()),
        sa.Column("positive_percent", sa.Float(), nullable=False), sa.Column("negative_percent", sa.Float(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False), sa.Column("aspects", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False), sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("ingestion", sa.JSON()), sa.Column("review_results", sa.JSON()), sa.Column("engine", sa.JSON()))
    op.create_index("ix_analysis_results_product_id", "analysis_results", ["product_id"])
    op.create_table("ai_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("analysis_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(100), nullable=False), sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sentences", sa.JSON(), nullable=False), sa.Column("problems", sa.JSON(), nullable=False))
    op.create_index("ix_ai_summaries_analysis_id", "ai_summaries", ["analysis_id"])
    op.create_table("processing_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("result", sa.JSON()))
    op.create_index("ix_processing_jobs_product_id", "processing_jobs", ["product_id"])


def downgrade():
    # Deliberately irreversible: even an explicit command must not silently delete user data.
    raise RuntimeError("Destructive baseline downgrade is disabled. Restore an operator-verified backup instead.")
