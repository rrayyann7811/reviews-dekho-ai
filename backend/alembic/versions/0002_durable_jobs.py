"""Durable analysis jobs; append-only extension of the existing retention foundation."""
from alembic import op
import sqlalchemy as sa

revision = "0002_jobs"
down_revision = "0001_postgres"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE processing_jobs ADD COLUMN result_analysis_id INTEGER REFERENCES analysis_results(id) ON DELETE SET NULL")
    for column in (
        sa.Column("kind", sa.String(20), nullable=False, server_default="analysis"),
        sa.Column("request_key", sa.String(64)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("claim_token", sa.String(64)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(160)),
    ):
        op.add_column("processing_jobs", column)
    op.execute("UPDATE processing_jobs SET status='cancelled', error='Legacy job was not executable.' WHERE status IN ('pending','queued','running')")
    op.create_index("uq_job_request", "processing_jobs", ["product_id", "request_key"], unique=True)
    op.create_index("ix_job_queue", "processing_jobs", ["status", "available_at", "id"])
    op.create_index("ix_job_lease", "processing_jobs", ["status", "lease_until", "id"])


def downgrade():
    raise RuntimeError("Destructive job downgrade is disabled; restore an operator-verified backup.")
