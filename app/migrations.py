from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import ROOT
from app.db import engine

BASELINE_REVISION = "0001_existing_schema"


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def upgrade_database() -> None:
    """Upgrade fresh databases and safely adopt pre-Alembic installations."""
    tables = set(inspect(engine).get_table_names())
    config = alembic_config()
    if "runs" in tables and "alembic_version" not in tables:
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")
