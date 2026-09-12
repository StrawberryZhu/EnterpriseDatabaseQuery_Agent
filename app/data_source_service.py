from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.credentials import CredentialCipher
from app.data_source_connector import PostgreSQLConnectionConfig, PostgreSQLConnector
from app.db import DataSource, DataSourceCredential, DataSourceSchemaSnapshot, SessionLocal, utcnow


class DataSourceServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DataSourceInput:
    name: str
    host: str
    port: int
    database_name: str
    username: str
    password: str | None
    ssl_mode: str = "prefer"
    allowed_schemas: tuple[str, ...] = ("public",)


class DataSourceService:
    def __init__(self, cipher: CredentialCipher | None = None) -> None:
        self.cipher = cipher or CredentialCipher.from_settings()

    def list(self) -> list[DataSource]:
        with SessionLocal() as db:
            return list(db.scalars(select(DataSource).where(DataSource.deleted_at.is_(None)).order_by(DataSource.created_at)))

    def get(self, source_id: str) -> DataSource:
        with SessionLocal() as db:
            source = db.get(DataSource, source_id)
            if source is None or source.deleted_at is not None:
                raise KeyError("数据源不存在")
            return source

    def create(self, body: DataSourceInput) -> DataSource:
        if not body.password:
            raise DataSourceServiceError("外部数据源密码不能为空")
        encrypted = self.cipher.encrypt(body.password)
        source = DataSource(
            name=body.name.strip(), source_type="postgresql", host=body.host.strip(), port=body.port,
            database_name=body.database_name.strip(), username=body.username.strip(),
            credential_mode="encrypted", ssl_mode=body.ssl_mode,
            allowed_schemas=list(body.allowed_schemas), status="untested", is_active=False, is_system=False,
        )
        with SessionLocal() as db:
            db.add(source)
            db.flush()
            db.add(DataSourceCredential(data_source_id=source.id, encrypted_password=encrypted.ciphertext, key_version=encrypted.key_version))
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DataSourceServiceError("数据源名称已存在或配置无效") from exc
            db.refresh(source)
            return source

    def update(self, source_id: str, body: DataSourceInput) -> DataSource:
        with SessionLocal() as db:
            source = self._get(db, source_id)
            if source.is_system:
                raise DataSourceServiceError("系统数据源不能修改连接配置")
            was_active = source.is_active
            for field in ("name", "host", "port", "database_name", "username", "ssl_mode"):
                setattr(source, field, getattr(body, field))
            source.allowed_schemas = list(body.allowed_schemas)
            source.status = "untested"
            source.is_active = False
            source.updated_at = utcnow()
            if body.password:
                encrypted = self.cipher.encrypt(body.password)
                credential = db.get(DataSourceCredential, source.id) or DataSourceCredential(data_source_id=source.id, encrypted_password="")
                credential.encrypted_password = encrypted.ciphertext
                credential.key_version = encrypted.key_version
                credential.updated_at = utcnow()
                db.add(credential)
            if was_active:
                self._activate_fallback(db)
            db.commit(); db.refresh(source)
            return source

    def test_connection(self, source_id: str):
        with SessionLocal() as db:
            source = self._get(db, source_id)
            connector = self._connector(db, source)
            result = connector.test_connection()
            source.last_tested_at = utcnow()
            source.status = "online" if result.ok and result.read_only else "offline"
            source.last_error_code = None if result.ok else result.error_code
            source.last_error_message = None if result.ok else result.message
            source.updated_at = utcnow()
            if not result.ok and source.is_active and not source.is_system:
                source.is_active = False
                self._activate_fallback(db)
            db.commit()
            return result

    def sync_schema(self, source_id: str) -> DataSourceSchemaSnapshot:
        with SessionLocal() as db:
            source = self._get(db, source_id)
            if source.status != "online":
                raise DataSourceServiceError("请先通过连接测试")
            discovered = self._connector(db, source).discover_schema()
            version = (db.scalar(select(func.max(DataSourceSchemaSnapshot.version)).where(DataSourceSchemaSnapshot.data_source_id == source.id)) or 0) + 1
            snapshot = DataSourceSchemaSnapshot(
                data_source_id=source.id, version=version, schema_hash=discovered.schema_hash,
                schema_payload=discovered.payload, table_count=discovered.table_count, status="success",
            )
            db.add(snapshot); source.schema_synced_at = utcnow(); source.updated_at = utcnow()
            db.commit(); db.refresh(snapshot)
            return snapshot

    def activate(self, source_id: str) -> DataSource:
        with SessionLocal() as db:
            source = self._get(db, source_id)
            has_snapshot = db.scalar(select(DataSourceSchemaSnapshot.id).where(
                DataSourceSchemaSnapshot.data_source_id == source.id,
                DataSourceSchemaSnapshot.status == "success",
            ).limit(1))
            if source.status != "online" or not has_snapshot:
                raise DataSourceServiceError("只有在线且已同步 Schema 的数据源才能启用")
            db.execute(update(DataSource).where(DataSource.is_active.is_(True)).values(is_active=False))
            db.flush()
            source.is_active = True; source.updated_at = utcnow()
            db.commit(); db.refresh(source)
            return source

    def delete(self, source_id: str) -> None:
        with SessionLocal() as db:
            source = self._get(db, source_id)
            if source.is_system:
                raise DataSourceServiceError("系统数据源不能删除")
            was_active = source.is_active
            source.deleted_at = utcnow(); source.is_active = False; source.status = "disabled"
            if was_active:
                self._activate_fallback(db)
            db.commit()

    @staticmethod
    def _get(db, source_id: str) -> DataSource:
        source = db.get(DataSource, source_id)
        if source is None or source.deleted_at is not None:
            raise KeyError("数据源不存在")
        return source

    def _connector(self, db, source: DataSource) -> PostgreSQLConnector:
        settings = get_settings()
        if source.credential_mode == "environment":
            config = PostgreSQLConnectionConfig.from_url(settings.business_database_url, allowed_schemas=source.allowed_schemas)
        else:
            credential = db.get(DataSourceCredential, source.id)
            if credential is None:
                raise DataSourceServiceError("数据源凭据不存在")
            password = self.cipher.decrypt(credential.encrypted_password, credential.key_version)
            config = PostgreSQLConnectionConfig(
                source.host, source.port, source.database_name, source.username, password,
                source.ssl_mode, tuple(source.allowed_schemas),
            )
        return PostgreSQLConnector(config)

    @staticmethod
    def _activate_fallback(db) -> None:
        db.execute(update(DataSource).where(DataSource.is_active.is_(True)).values(is_active=False))
        db.flush()
        fallback = db.scalar(select(DataSource).where(DataSource.is_system.is_(True), DataSource.deleted_at.is_(None)))
        if fallback:
            fallback.is_active = True


def serialize_data_source(source: DataSource) -> dict:
    return {
        "id": source.id, "name": source.name, "source_type": source.source_type,
        "host": source.host, "port": source.port, "database_name": source.database_name,
        "username": source.username, "ssl_mode": source.ssl_mode,
        "allowed_schemas": source.allowed_schemas, "status": source.status,
        "is_active": source.is_active, "is_system": source.is_system,
        "has_password": source.credential_mode in {"encrypted", "environment"},
        "last_tested_at": source.last_tested_at.isoformat() if source.last_tested_at else None,
        "schema_synced_at": source.schema_synced_at.isoformat() if source.schema_synced_at else None,
        "last_error_code": source.last_error_code, "last_error_message": source.last_error_message,
    }
