"""Baseline the application schema that existed in v0.1.0."""
from alembic import op
import sqlalchemy as sa

revision = "0001_existing_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("threads", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(100), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("summary", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_threads_user_id", "threads", ["user_id"])
    op.create_table("messages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("thread_id", sa.String(36), sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("run_id", sa.String(36)), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])
    op.create_index("ix_messages_run_id", "messages", ["run_id"])
    op.create_table("runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("thread_id", sa.String(36), sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(100), nullable=False), sa.Column("question", sa.Text(), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("answer", sa.JSON(), nullable=False), sa.Column("state", sa.JSON(), nullable=False), sa.Column("error", sa.Text(), nullable=False), sa.Column("verification_passed", sa.Boolean(), nullable=False), sa.Column("first_sql_success", sa.Boolean()), sa.Column("loop_count", sa.Integer(), nullable=False), sa.Column("tool_call_count", sa.Integer(), nullable=False), sa.Column("token_budget", sa.Integer(), nullable=False), sa.Column("input_tokens", sa.Integer(), nullable=False), sa.Column("output_tokens", sa.Integer(), nullable=False), sa.Column("embedding_tokens", sa.Integer(), nullable=False), sa.Column("estimated_cost", sa.Float(), nullable=False), sa.Column("latency_ms", sa.Float(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("thread_id", "user_id", "status"):
        op.create_index(f"ix_runs_{column}", "runs", [column])
    op.create_table("run_events", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False), sa.Column("event_type", sa.String(60), nullable=False), sa.Column("data", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_table("tool_calls", sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False), sa.Column("tool_name", sa.String(100), nullable=False), sa.Column("arguments", sa.JSON(), nullable=False), sa.Column("result", sa.JSON(), nullable=False), sa.Column("success", sa.Boolean(), nullable=False), sa.Column("latency_ms", sa.Float(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_tool_calls_run_id", "tool_calls", ["run_id"])
    op.create_table("user_memories", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(100), nullable=False), sa.Column("key", sa.String(100), nullable=False), sa.Column("value", sa.Text(), nullable=False), sa.Column("memory_type", sa.String(40), nullable=False), sa.Column("confidence", sa.Float(), nullable=False), sa.Column("source_message_id", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"])
    op.create_index("ix_user_memories_key", "user_memories", ["key"])
    op.create_table("prompt_snapshots", sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False), sa.Column("prompt_name", sa.String(100), nullable=False), sa.Column("prompt_version", sa.String(30), nullable=False), sa.Column("prompt_hash", sa.String(64), nullable=False), sa.Column("rendered", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_prompt_snapshots_run_id", "prompt_snapshots", ["run_id"])
    op.create_table("context_snapshots", sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False), sa.Column("context", sa.JSON(), nullable=False), sa.Column("estimated_tokens", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_context_snapshots_run_id", "context_snapshots", ["run_id"])
    op.create_table("user_feedback", sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("helpful", sa.Boolean(), nullable=False), sa.Column("comment", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("eval_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("dataset_name", sa.String(120), nullable=False), sa.Column("model_name", sa.String(120), nullable=False), sa.Column("metrics", sa.JSON(), nullable=False), sa.Column("case_count", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade() -> None:
    for table in ("eval_runs", "user_feedback", "context_snapshots", "prompt_snapshots", "user_memories", "tool_calls", "run_events", "runs", "messages", "threads"):
        op.drop_table(table)
