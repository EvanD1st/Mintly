"""Verify the production schema upgrade, including private mint plans."""

import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from app.config import settings
from app.database import Base
import app.models
from app.models import MintPermission


def test_fresh_database_migrates_to_head(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="mintly-migration-") as directory:
        path = Path(directory) / "migration.db"
        monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
        command.upgrade(Config("alembic.ini"), "head")
        assert path.is_file()
        engine = create_engine(f'sqlite:///{path.as_posix()}')
        try:
            schema = inspect(engine)
            for table in Base.metadata.sorted_tables:
                actual = {column['name'] for column in schema.get_columns(table.name)}
                assert set(table.columns.keys()) <= actual, f'{table.name} is missing ORM columns'
            with engine.connect() as conn:
                assert conn.execute(select(MintPermission)).all() == []
        finally:
            engine.dispose()


def test_existing_permission_history_survives_timestamp_upgrade(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='mintly-upgrade-') as directory:
        path = Path(directory) / 'existing.db'
        monkeypatch.setattr(settings, 'DATABASE_URL', f'sqlite+aiosqlite:///{path.as_posix()}')
        command.upgrade(Config('alembic.ini'), '005_mint_permissions')
        engine = create_engine(f'sqlite:///{path.as_posix()}')
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("""
                    INSERT INTO mint_permissions (
                        id,user_id,plan_id,code_hash,typed_data,execution,status,
                        expires_at,execute_after,signature_deadline,note,created_at
                    ) VALUES (
                        'history','owner','plan','code','{}','{}','cancelled',
                        '2026-10-01 19:00:00','2026-10-01 18:00:00',
                        '2026-10-01 17:00:00','Preserve history','2026-09-30 12:00:00'
                    )
                """)
            command.upgrade(Config('alembic.ini'), 'head')
            with engine.connect() as conn:
                row = conn.exec_driver_sql(
                    'SELECT id,status,note,created_at,updated_at FROM mint_permissions'
                ).one()
                assert row[0:3] == ('history','cancelled','Preserve history')
                assert row[3] == row[4]
        finally:
            engine.dispose()
