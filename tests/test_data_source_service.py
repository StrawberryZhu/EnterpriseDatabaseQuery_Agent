from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.config import get_settings
from app.credentials import CredentialCipher
from app.data_source_service import DataSourceInput, DataSourceService
from app.dynamic_source import DynamicDataSource
from app.db import DataSource, DataSourceCredential, Run, SessionLocal, Thread
from app.main import app
from app.repository import Repository


def test_data_source_api_never_returns_credentials():
    response = TestClient(app).get("/api/v1/data-sources")
    assert response.status_code == 200
    body = response.text.lower()
    assert "encrypted_password" not in body
    assert "northwind_reader_password" not in body
    assert response.json()[0]["has_password"] is True


def test_external_source_lifecycle_encrypts_password_and_restores_northwind():
    settings = get_settings()
    key = Fernet.generate_key().decode()
    service = DataSourceService(CredentialCipher({1: key}, active_key_version=1))
    source = service.create(DataSourceInput(
        name="Connector integration test", host="postgres", port=5432,
        database_name="querymind", username="northwind_reader",
        password=settings.northwind_reader_password, ssl_mode="prefer",
        allowed_schemas=("northwind",),
    ))
    try:
        with SessionLocal() as db:
            credential = db.get(DataSourceCredential, source.id)
            assert credential is not None
            assert settings.northwind_reader_password not in credential.encrypted_password
        assert service.test_connection(source.id).ok is True
        snapshot = service.sync_schema(source.id)
        assert snapshot.table_count >= 11
        assert service.activate(source.id).is_active is True
        repo = Repository()
        thread = repo.create_thread(title="dynamic source test")
        run = repo.create_run(thread.id, "guest", "count orders", 2000)
        result = DynamicDataSource(cipher=service.cipher).query(run.id, "SELECT count(*) AS total FROM northwind.orders")
        assert result["rows"][0]["total"] == 830
        repo.delete_thread(thread.id)
        service.delete(source.id)
        with SessionLocal() as db:
            northwind = db.scalar(select(DataSource).where(DataSource.is_system.is_(True)))
            deleted = db.get(DataSource, source.id)
            assert northwind.is_active is True
            assert deleted.deleted_at is not None
    finally:
        with SessionLocal() as db:
            item = db.get(DataSource, source.id)
            if item:
                thread_ids = list(db.scalars(select(Run.thread_id).where(Run.data_source_id == source.id)))
                if thread_ids:
                    db.execute(delete(Thread).where(Thread.id.in_(thread_ids)))
                    db.flush()
                db.delete(item)
            db.execute(update(DataSource).where(DataSource.is_active.is_(True)).values(is_active=False))
            db.flush()
            northwind = db.scalar(select(DataSource).where(DataSource.is_system.is_(True)))
            northwind.is_active = True
            db.commit()
