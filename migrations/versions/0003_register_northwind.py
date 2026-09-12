"""Register Northwind and bind historical runs to it."""
from alembic import op
import sqlalchemy as sa

revision = "0003_register_northwind"
down_revision = "0002_dynamic_data_sources"
branch_labels = None
depends_on = None

NORTHWIND_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO data_sources (
            id, name, source_type, host, port, database_name, username,
            credential_mode, ssl_mode, allowed_schemas, status,
            is_active, is_system, created_at, updated_at
        ) VALUES (
            :id, 'Northwind 贸易数据', 'postgresql', 'postgres', 5432,
            'querymind', 'northwind_reader', 'environment', 'prefer',
            '[\"northwind\"]'::json, 'online', true, true, now(), now()
        ) ON CONFLICT (id) DO NOTHING
    """), {"id": NORTHWIND_ID})
    connection.execute(sa.text("UPDATE runs SET data_source_id = :id WHERE data_source_id IS NULL"), {"id": NORTHWIND_ID})


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE runs SET data_source_id = NULL WHERE data_source_id = :id"), {"id": NORTHWIND_ID})
    connection.execute(sa.text("DELETE FROM data_sources WHERE id = :id"), {"id": NORTHWIND_ID})
