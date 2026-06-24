import os
import tempfile
from app.database.connection import get_engine, get_session
from app.database.models import Base, Staff


def _cleanup(engine, path):
    """WALモードのSQLiteファイルをWindows上で安全に削除する。"""
    engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def test_wal_mode_enabled():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    engine = get_engine(path)
    try:
        with engine.connect() as conn:
            result = conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode")).scalar()
        assert result == "wal"
    finally:
        _cleanup(engine, path)


def test_session_creates_tables():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    engine = get_engine(path)
    try:
        with get_session(engine) as session:
            s = Staff(name="山田")
            session.add(s)
        with get_session(engine) as session:
            assert session.query(Staff).count() == 1
    finally:
        _cleanup(engine, path)
