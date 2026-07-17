"""Alembic migration tests: the chain applies, reverses and stamps cleanly.

These run against a throwaway SQLite file (migrations use ``render_as_batch`` so
they are dialect-portable). They guard that:

* ``upgrade head`` builds the expected schema from an empty database,
* ``downgrade base`` reverses it completely,
* ``stamp head`` marks an existing database without running the migrations, and
* the migration graph has exactly one head (no accidental divergent branches).
"""
import os

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.config import Config

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations"
)

# A representative slice of tables the full chain must create.
_EXPECTED_TABLES = {"traces", "users", "organizations", "refresh_tokens", "prompt_versions"}


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", _MIGRATIONS_DIR)
    # env.py resolves the URL from app config, but set this too for completeness.
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture()
def migration_db(tmp_path, monkeypatch):
    """Point both Alembic and the app config at a fresh SQLite file."""
    db_url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_url)
    return db_url, _alembic_config(db_url)


def _table_names(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_graph_has_single_head(migration_db):
    _, cfg = migration_db
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"expected one head, found {heads}"


def test_upgrade_head_builds_schema(migration_db):
    db_url, cfg = migration_db
    command.upgrade(cfg, "head")

    tables = _table_names(db_url)
    assert _EXPECTED_TABLES <= tables
    assert "alembic_version" in tables


def test_downgrade_base_reverses_schema(migration_db):
    db_url, cfg = migration_db
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    tables = _table_names(db_url)
    # Every application table is gone after a full downgrade.
    assert not (_EXPECTED_TABLES & tables), f"tables survived downgrade: {tables}"


def test_stamp_head_marks_without_creating_tables(migration_db):
    db_url, cfg = migration_db
    command.stamp(cfg, "head")

    head = ScriptDirectory.from_config(cfg).get_current_head()
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            stamped = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert stamped == head
        # Stamping records the version but must not run the migrations.
        assert "traces" not in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_is_idempotent_at_head(migration_db):
    _, cfg = migration_db
    command.upgrade(cfg, "head")
    # Running upgrade again is a no-op (already at head), not an error.
    command.upgrade(cfg, "head")
