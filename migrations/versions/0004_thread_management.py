"""Add thread pinning support."""
from alembic import op
import sqlalchemy as sa

revision = "0004_thread_management"
down_revision = "0003_register_northwind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("threads", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_threads_pinned_at", "threads", ["pinned_at"])


def downgrade() -> None:
    op.drop_index("ix_threads_pinned_at", table_name="threads")
    op.drop_column("threads", "pinned_at")
