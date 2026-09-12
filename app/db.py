from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Thread(Base):
    __tablename__ = "threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(100), default="guest", index=True)
    title: Mapped[str] = mapped_column(String(200), default="新分析")
    summary: Mapped[str] = mapped_column(Text, default="")
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    messages: Mapped[list["Message"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    thread: Mapped[Thread] = relationship(back_populates="messages")


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint("port BETWEEN 1 AND 65535", name="ck_data_sources_port"),
        CheckConstraint("source_type IN ('postgresql')", name="ck_data_sources_type"),
        CheckConstraint("credential_mode IN ('encrypted', 'environment')", name="ck_data_sources_credential_mode"),
        CheckConstraint("ssl_mode IN ('disable', 'prefer', 'require', 'verify-ca', 'verify-full')", name="ck_data_sources_ssl_mode"),
        CheckConstraint("status IN ('untested', 'online', 'offline', 'disabled')", name="ck_data_sources_status"),
        CheckConstraint("NOT is_system OR credential_mode = 'environment'", name="ck_data_sources_system_credentials"),
        Index("uq_data_sources_active", "is_active", unique=True, postgresql_where=text("is_active AND deleted_at IS NULL")),
        Index("uq_data_sources_name", text("lower(name)"), unique=True, postgresql_where=text("deleted_at IS NULL")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(30), default="postgresql")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database_name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(120))
    credential_mode: Mapped[str] = mapped_column(String(30), default="encrypted")
    ssl_mode: Mapped[str] = mapped_column(String(20), default="prefer")
    allowed_schemas: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["public"])
    status: Mapped[str] = mapped_column(String(30), default="untested", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSourceCredential(Base):
    __tablename__ = "data_source_credentials"
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True)
    encrypted_password: Mapped[str] = mapped_column(Text)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSourceSchemaSnapshot(Base):
    __tablename__ = "data_source_schema_snapshots"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'failed')", name="ck_data_source_schema_snapshots_status"),
        Index("uq_data_source_schema_snapshot_version", "data_source_id", "version", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="success")
    sanitized_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    data_source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id"), nullable=True, index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(100), default="guest", index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    answer: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    verification_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_sql_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    loop_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    token_budget: Mapped[int] = mapped_column(Integer, default=20_000)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserMemory(Base):
    __tablename__ = "user_memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(100), default="guest", index=True)
    key: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String(40), default="preference")
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptSnapshot(Base):
    __tablename__ = "prompt_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    prompt_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(30))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    rendered: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContextSnapshot(Base):
    __tablename__ = "context_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    context: Mapped[dict] = mapped_column(JSON)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), unique=True)
    helpful: Mapped[bool] = mapped_column(Boolean)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_name: Mapped[str] = mapped_column(String(120))
    model_name: Mapped[str] = mapped_column(String(120))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


settings = get_settings()
engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Apply versioned application migrations after enabling extensions."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    from app.migrations import upgrade_database

    upgrade_database()


def database_health() -> dict[str, object]:
    with engine.connect() as conn:
        database = conn.execute(text("SELECT current_database()" )).scalar_one()
        vector = conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')")).scalar_one()
    return {"ok": True, "database": database, "pgvector": bool(vector)}
