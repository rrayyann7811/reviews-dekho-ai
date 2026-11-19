"""Owner-scoped import receipts with a surviving deletion tombstone."""

from alembic import op
import sqlalchemy as sa

revision = "0003_import_receipts"
down_revision = "0002_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "import_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("result", sa.JSON()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_import_receipt_owner_key"),
    )
    op.create_index("ix_import_receipts_expires_at", "import_receipts", ["expires_at"])
    op.create_index("ix_import_receipts_product_id", "import_receipts", ["product_id"])


def downgrade():
    raise RuntimeError("Destructive import receipt downgrade is disabled; restore an operator-verified backup.")
