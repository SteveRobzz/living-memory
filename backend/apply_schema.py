"""Apply schema.sql without needing psql on PATH.

    python apply_schema.py

Reads DATABASE_URL from .env (or the environment) and executes schema.sql
against it. Safe to run more than once -- every statement is IF NOT EXISTS
or ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import pathlib
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from app.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    sql_path = pathlib.Path(__file__).parent / "schema.sql"
    if not sql_path.exists():
        print(f"ERROR: {sql_path} not found")
        return 1

    url = settings.database_url
    safe = url.split("@")[-1] if "@" in url else url
    print(f"Connecting to {safe} ...")

    engine = create_engine(url)
    sql = sql_path.read_text(encoding="utf-8")

    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception as exc:
        print("\nFAILED to apply schema:\n")
        print(f"  {type(exc).__name__}: {exc}\n")
        print("Common causes:")
        print("  - database not running or wrong port in DATABASE_URL")
        print("  - pgvector not installed (the CREATE EXTENSION line fails)")
        print("  - wrong username/password/database name")
        return 1

    with engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )).scalars().all()
        users = conn.execute(text("SELECT handle FROM users ORDER BY id")).scalars().all()

    print(f"\nOK. {len(tables)} tables: {', '.join(tables)}")
    print(f"Demo users: {', '.join(users) if users else '(none)'}")
    print("\nExpected 8 tables and users maya, dev.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
