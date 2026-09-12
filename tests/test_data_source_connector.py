from app.config import get_settings
import pytest

from app.data_source_connector import PostgreSQLConnectionConfig, PostgreSQLConnector
from app.dynamic_source import DynamicDataSource


def northwind_config() -> PostgreSQLConnectionConfig:
    settings = get_settings()
    return PostgreSQLConnectionConfig.from_url(
        settings.business_database_url,
        allowed_schemas=["northwind"],
    )


def test_northwind_connection_is_read_only():
    result = PostgreSQLConnector(northwind_config()).test_connection()

    assert result.ok is True
    assert result.read_only is True
    assert result.error_code is None
    assert "PostgreSQL" in result.server_version


def test_northwind_schema_discovery_is_scoped_and_deterministic():
    connector = PostgreSQLConnector(northwind_config())
    first = connector.discover_schema()
    second = connector.discover_schema()

    assert first.schema_hash == second.schema_hash
    assert first.table_count >= 11
    assert {schema["name"] for schema in first.payload["schemas"]} == {"northwind"}
    tables = {table["name"]: table for table in first.payload["schemas"][0]["tables"]}
    assert "orders" in tables
    assert "order_id" in tables["orders"]["primary_key"]
    assert tables["orders"]["columns"]
    assert "sample_values" not in str(first.payload)


def test_dynamic_sql_policy_blocks_writes_and_unknown_objects():
    payload = {"schemas": [{"name": "analytics", "tables": [{"name": "orders", "columns": []}]}]}
    assert DynamicDataSource._validate_sql("SELECT * FROM analytics.orders", payload, {"analytics"}).endswith("LIMIT 200")
    with pytest.raises(ValueError, match="只允许"):
        DynamicDataSource._validate_sql("DELETE FROM analytics.orders", payload, {"analytics"})
    with pytest.raises(ValueError, match="未授权"):
        DynamicDataSource._validate_sql("SELECT * FROM private.users", payload, {"analytics"})
