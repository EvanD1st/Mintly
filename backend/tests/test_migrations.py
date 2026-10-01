"""Verify the production schema upgrade, including private mint plans."""

import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import settings


def test_fresh_database_migrates_to_head(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="mintly-migration-") as directory:
        path = Path(directory) / "migration.db"
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
        command.upgrade(Config("alembic.ini"), "head")
        assert path.is_file()
