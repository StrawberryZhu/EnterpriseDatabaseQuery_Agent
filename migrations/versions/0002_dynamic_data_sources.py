"""Add dynamic data source configuration and schema snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0002_dynamic_data_sources"
down_revision = "0001_existing_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(120), nullable=False),
        sa.Column("username", sa.String(120), nullable=False),
        sa.Column("credential_mode", sa.String(30), nullable=False),
        sa.Column("ssl_mode", sa.String(20), nullable=False),
        sa.Column("allowed_schemas", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(60)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("schema_synced_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name="ck_data_sources_port"),
        sa.CheckConstraint("source_type IN ('postgresql')", name="ck_data_sources_type"),
        sa.CheckConstraint("credential_mode IN ('encrypted', 'environment')", name="ck_data_sources_credential_mode"),
        sa.CheckConstraint("ssl_mode IN ('disable', 'prefer', 'require', 'verify-ca', 'verify-full')", name="ck_data_sources_ssl_mode"),
        sa.CheckConstraint("status IN ('untested', 'online', 'offline', 'disabled')", name="ck_data_sources_status"),
        sa.CheckConstraint("NOT is_system OR credential_mode = 'environment'", name="ck_data_sources_system_credentials"),
    )
    op.create_index("ix_data_sources_status", "data_sources", ["status"])
    op.create_index("ix_data_sources_deleted_at", "data_sources", ["deleted_at"])
    op.create_index("uq_data_sources_active", "data_sources", ["is_active"], unique=True, postgresql_where=sa.text("is_active AND deleted_at IS NULL"))
    op.create_index("uq_data_sources_name", "data_sources", [sa.text("lower(name)")], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_table("data_source_credentials", sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True), sa.Column("encrypted_password", sa.Text(), nullable=False), sa.Column("key_version", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("data_source_schema_snapshots", sa.Column("id", sa.String(36), primary_key=True), sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("schema_hash", sa.String(64)), sa.Column("schema_payload", sa.JSON(), nullable=False), sa.Column("table_count", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("sanitized_error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("status IN ('success', 'failed')", name="ck_data_source_schema_snapshots_status"))
    op.create_index("ix_data_source_schema_snapshots_data_source_id", "data_source_schema_snapshots", ["data_source_id"])
    op.create_index("uq_data_source_schema_snapshot_version", "data_source_schema_snapshots", ["data_source_id", "version"], unique=True)
    op.add_column("runs", sa.Column("data_source_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_runs_data_source_id", "runs", "data_sources", ["data_source_id"], ["id"])
    op.create_index("ix_runs_data_source_id", "runs", ["data_source_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_data_source_id", table_name="runs")
    op.drop_constraint("fk_runs_data_source_id", "runs", type_="foreignkey")
    op.drop_column("runs", "data_source_id")
    op.drop_table("data_source_schema_snapshots")
    op.drop_table("data_source_credentials")
    op.drop_table("data_sources")
