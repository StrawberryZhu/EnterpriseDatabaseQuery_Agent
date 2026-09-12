from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
EXTERNALLY_MANAGED_TABLES = {
    "checkpoint_blobs",
    "checkpoint_migrations",
    "checkpoint_writes",
    "checkpoints",
    "rag_knowledge",
}


def include_object(object_, name, type_, reflected, compare_to):
    """Keep Alembic away from tables owned by LangGraph and the RAG indexer."""
    if type_ == "table" and reflected and name in EXTERNALLY_MANAGED_TABLES:
        return False
    table = getattr(object_, "table", None)
    if reflected and table is not None and table.name in EXTERNALLY_MANAGED_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from app.db import engine

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
