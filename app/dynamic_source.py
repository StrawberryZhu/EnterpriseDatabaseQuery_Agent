from __future__ import annotations

import time

import sqlglot
from sqlglot import exp
from sqlalchemy import select

from app.credentials import CredentialCipher
from app.data_source_connector import PostgreSQLConnectionConfig, PostgreSQLConnector
from app.db import DataSource, DataSourceCredential, DataSourceSchemaSnapshot, Run, SessionLocal
from app.northwind import NorthwindSource, json_value


class DynamicDataSource:
    """Resolve schema and read-only query execution from the Run-bound source."""

    def __init__(self, northwind: NorthwindSource | None = None, cipher: CredentialCipher | None = None) -> None:
        self.northwind = northwind or NorthwindSource()
        self.cipher = cipher or CredentialCipher.from_settings()

    def schema(self, run_id: str) -> dict:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if not run or not run.data_source_id:
                raise KeyError("运行记录未绑定数据源")
            snapshot = db.scalar(select(DataSourceSchemaSnapshot).where(
                DataSourceSchemaSnapshot.data_source_id == run.data_source_id,
                DataSourceSchemaSnapshot.status == "success",
            ).order_by(DataSourceSchemaSnapshot.version.desc()).limit(1))
            if snapshot:
                return snapshot.schema_payload
            source = db.get(DataSource, run.data_source_id)
            if source and source.is_system:
                return {"schemas": [{"name": "northwind", "tables": self.northwind.schema(compact=False)}]}
            raise RuntimeError("数据源尚未同步 Schema")

    def is_system(self, run_id: str) -> bool:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            source = db.get(DataSource, run.data_source_id) if run else None
            return bool(source and source.is_system)

    def schema_text(self, run_id: str) -> str:
        lines = []
        for schema in self.schema(run_id)["schemas"]:
            for table in schema["tables"]:
                columns = ", ".join(f"{column['name']}({column['type']})" for column in table["columns"])
                lines.append(f"- {schema['name']}.{table['name']}: {columns}")
        return "\n".join(lines)

    def query(self, run_id: str, sql: str) -> dict:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            source = db.get(DataSource, run.data_source_id) if run else None
            if source is None or source.deleted_at is not None:
                raise KeyError("数据源不存在")
            if source.is_system:
                return self.northwind.query(sql)
            credential = db.get(DataSourceCredential, source.id)
            if credential is None:
                raise RuntimeError("数据源凭据不存在")
            password = self.cipher.decrypt(credential.encrypted_password, credential.key_version)
            config = PostgreSQLConnectionConfig(source.host, source.port, source.database_name, source.username,
                password, source.ssl_mode, tuple(source.allowed_schemas))
        safe_sql = self._validate_sql(sql, self.schema(run_id), set(config.allowed_schemas))
        started = time.perf_counter()
        connector = PostgreSQLConnector(config)
        with connector.connect() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT set_config('search_path', %s, true)", (", ".join(config.allowed_schemas),))
            cursor.execute(safe_sql)
            rows = [{key: json_value(value) for key, value in row.items()} for row in cursor.fetchall()]
            columns = [item.name for item in cursor.description or []]
        return {"sql": safe_sql, "columns": columns, "rows": rows, "row_count": len(rows),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2)}

    @staticmethod
    def _validate_sql(sql: str, payload: dict, allowed_schemas: set[str]) -> str:
        sql = sql.strip().rstrip(";")
        if not sql:
            raise ValueError("只允许执行只读 SELECT 查询")
        tree = sqlglot.parse_one(sql, read="postgres")
        forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Merge)
        if isinstance(tree, forbidden) or any(tree.find(item) for item in forbidden) or tree.find(exp.Select) is None:
            raise ValueError("只允许执行只读 SELECT 查询")
        allowed_tables = {table["name"].lower() for schema in payload["schemas"] for table in schema["tables"]}
        for table in tree.find_all(exp.Table):
            if table.name.lower() not in allowed_tables or (table.db and table.db.lower() not in allowed_schemas):
                raise ValueError(f"SQL 包含未授权对象：{table.sql()}")
        if not tree.args.get("limit"):
            sql += "\nLIMIT 200"
        return sql
