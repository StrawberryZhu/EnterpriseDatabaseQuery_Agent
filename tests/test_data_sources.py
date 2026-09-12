from sqlalchemy import inspect, select

from app.db import DataSource, Run, SessionLocal, engine


def test_dynamic_data_source_schema_is_migrated():
    inspector = inspect(engine)
    assert {
        "data_sources",
        "data_source_credentials",
        "data_source_schema_snapshots",
    }.issubset(inspector.get_table_names())
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    assert "data_source_id" in run_columns


def test_northwind_is_registered_and_existing_runs_are_backfilled():
    with SessionLocal() as db:
        source = db.scalar(select(DataSource).where(DataSource.is_system.is_(True)))
        assert source is not None
        assert source.name == "Northwind 贸易数据"
        assert source.source_type == "postgresql"
        assert source.credential_mode == "environment"
        assert source.allowed_schemas == ["northwind"]
        assert source.is_active is True
        assert source.deleted_at is None

        unbound_runs = db.scalars(select(Run).where(Run.data_source_id.is_(None))).all()
        assert unbound_runs == []
