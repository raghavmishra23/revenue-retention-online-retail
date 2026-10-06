import sqlite3
from pathlib import Path

from src.config import get, load_settings, resolve_path

MIN_SQLITE_VERSION: str = get(load_settings(), "warehouse.min_sqlite_version")


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def assert_sqlite_version(installed: str | None = None, minimum: str = MIN_SQLITE_VERSION) -> None:
    """Compare as integer tuples; as strings "3.9" would sort above "3.25"."""
    installed = installed or sqlite3.sqlite_version
    if _version_tuple(installed) < _version_tuple(minimum):
        raise RuntimeError(f"sqlite {installed} is older than the required {minimum}")


def connect(path: Path | None = None) -> sqlite3.Connection:
    assert_sqlite_version()
    conn = sqlite3.connect(path or resolve_path("warehouse"))
    # off by default in SQLite and per-connection, so the integrity gate needs it set every time
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def run_script(conn: sqlite3.Connection, path: Path) -> None:
    conn.executescript(path.read_text(encoding="utf-8"))


def apply_schema(conn: sqlite3.Connection, directory: Path) -> None:
    # filenames are numbered so sorted order is dependency order
    for script in sorted(directory.glob("*.sql")):
        run_script(conn, script)


def foreign_key_violations(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("PRAGMA foreign_key_check").fetchall()
