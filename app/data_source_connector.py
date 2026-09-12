from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import socket
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg.rows import dict_row

from app.credentials import sanitize_secret_text


SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}


@dataclass(frozen=True)
class PostgreSQLConnectionConfig:
    host: str
    port: int
    database: str
    username: str
    password: str
    ssl_mode: str = "prefer"
    allowed_schemas: tuple[str, ...] = ("public",)

    @classmethod
    def from_url(cls, url: str, *, allowed_schemas: list[str]) -> "PostgreSQLConnectionConfig":
        parsed = urlsplit(url)
        return cls(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            database=parsed.path.lstrip("/"),
            username=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            allowed_schemas=tuple(allowed_schemas),
        )


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    read_only: bool = False
    server_version: str = ""
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class SchemaDiscoveryResult:
    payload: dict
    schema_hash: str
    table_count: int


class PostgreSQLConnector:
    def __init__(self, config: PostgreSQLConnectionConfig) -> None:
        schemas = tuple(s for s in config.allowed_schemas if s and s not in SYSTEM_SCHEMAS and not s.startswith("pg_"))
        if not schemas:
            raise ValueError("至少需要一个允许访问的业务 Schema")
        self.config = PostgreSQLConnectionConfig(**{**config.__dict__, "allowed_schemas": schemas})

    def connect(self):
        return psycopg.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.username,
            password=self.config.password,
            sslmode=self.config.ssl_mode,
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=2000",
            row_factory=dict_row,
        )

    def test_connection(self) -> ConnectionTestResult:
        try:
            with self.connect() as conn, conn.cursor() as cursor:
                cursor.execute("SELECT version() AS version, current_setting('transaction_read_only') AS read_only")
                row = cursor.fetchone()
                return ConnectionTestResult(True, row["read_only"] == "on", row["version"])
        except Exception as exc:
            code = self._error_code(exc)
            return ConnectionTestResult(False, error_code=code, message=self._safe_message(code, exc))

    def discover_schema(self) -> SchemaDiscoveryResult:
        with self.connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.table_schema, c.table_name, c.column_name, c.data_type,
                       c.is_nullable = 'YES' AS nullable, c.ordinal_position,
                       COALESCE(cls.reltuples::bigint, 0) AS estimated_rows
                FROM information_schema.columns c
                JOIN pg_namespace ns ON ns.nspname = c.table_schema
                JOIN pg_class cls ON cls.relnamespace = ns.oid AND cls.relname = c.table_name
                WHERE c.table_schema = ANY(%s) AND cls.relkind IN ('r', 'p', 'v', 'm')
                ORDER BY c.table_schema, c.table_name, c.ordinal_position
                """,
                (list(self.config.allowed_schemas),),
            )
            columns = cursor.fetchall()
            cursor.execute(
                """
                SELECT ns.nspname AS table_schema, tbl.relname AS table_name, col.attname AS column_name
                FROM pg_constraint con
                JOIN pg_class tbl ON tbl.oid = con.conrelid
                JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
                JOIN unnest(con.conkey) WITH ORDINALITY AS key(attnum, position) ON true
                JOIN pg_attribute col ON col.attrelid = tbl.oid AND col.attnum = key.attnum
                WHERE con.contype = 'p' AND ns.nspname = ANY(%s)
                ORDER BY ns.nspname, tbl.relname, key.position
                """,
                (list(self.config.allowed_schemas),),
            )
            primary_keys = cursor.fetchall()
            cursor.execute(
                """
                SELECT src_ns.nspname AS table_schema, src.relname AS table_name,
                       src_col.attname AS column_name, ref_ns.nspname AS referenced_schema,
                       ref.relname AS referenced_table, ref_col.attname AS referenced_column
                FROM pg_constraint con
                JOIN pg_class src ON src.oid = con.conrelid
                JOIN pg_namespace src_ns ON src_ns.oid = src.relnamespace
                JOIN pg_class ref ON ref.oid = con.confrelid
                JOIN pg_namespace ref_ns ON ref_ns.oid = ref.relnamespace
                JOIN unnest(con.conkey, con.confkey) WITH ORDINALITY AS keys(src_num, ref_num, position) ON true
                JOIN pg_attribute src_col ON src_col.attrelid = src.oid AND src_col.attnum = keys.src_num
                JOIN pg_attribute ref_col ON ref_col.attrelid = ref.oid AND ref_col.attnum = keys.ref_num
                WHERE con.contype = 'f' AND src_ns.nspname = ANY(%s)
                ORDER BY src_ns.nspname, src.relname, keys.position
                """,
                (list(self.config.allowed_schemas),),
            )
            foreign_keys = cursor.fetchall()

        table_map: dict[tuple[str, str], dict] = {}
        for row in columns:
            key = (row["table_schema"], row["table_name"])
            table = table_map.setdefault(key, {
                "name": row["table_name"], "kind": "table", "estimated_rows": row["estimated_rows"],
                "columns": [], "primary_key": [], "foreign_keys": [],
            })
            table["columns"].append({"name": row["column_name"], "type": row["data_type"], "nullable": row["nullable"]})
        for row in primary_keys:
            table_map[(row["table_schema"], row["table_name"])]["primary_key"].append(row["column_name"])
        for row in foreign_keys:
            table_map[(row["table_schema"], row["table_name"])]["foreign_keys"].append({
                "column": row["column_name"], "referenced_schema": row["referenced_schema"],
                "referenced_table": row["referenced_table"], "referenced_column": row["referenced_column"],
            })
        payload = {"schemas": [
            {"name": schema, "tables": [table_map[key] for key in sorted(table_map) if key[0] == schema]}
            for schema in self.config.allowed_schemas
        ]}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return SchemaDiscoveryResult(payload, hashlib.sha256(canonical.encode()).hexdigest(), len(table_map))

    @staticmethod
    def _error_code(exc: Exception) -> str:
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate == "28P01":
            return "AUTH_FAILED"
        if isinstance(exc, (socket.gaierror, TimeoutError)):
            return "HOST_UNREACHABLE"
        text = str(exc).lower()
        if "ssl" in text or "tls" in text or "certificate" in text:
            return "TLS_FAILED"
        if "timeout" in text or "connection refused" in text or "could not translate host" in text:
            return "HOST_UNREACHABLE"
        return "CONNECTION_FAILED"

    @staticmethod
    def _safe_message(code: str, exc: Exception) -> str:
        labels = {
            "AUTH_FAILED": "数据库身份验证失败",
            "HOST_UNREACHABLE": "无法连接数据库主机",
            "TLS_FAILED": "数据库 TLS 连接失败",
            "CONNECTION_FAILED": "数据库连接失败",
        }
        sanitize_secret_text(exc)
        return labels[code]
