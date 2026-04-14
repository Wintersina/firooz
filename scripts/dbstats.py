#!/usr/bin/env python3
"""Show SQLite database size and row counts per table."""
from __future__ import annotations

import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH", "firooz.db")


def format_size(bytes_: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024  # type: ignore[assignment]
    return f"{bytes_:.1f} TB"


def main() -> None:
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    file_size = os.path.getsize(DB_PATH)
    conn = sqlite3.connect(DB_PATH)

    # Get all tables
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    # Get page stats
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0]

    print("=" * 50)
    print("  Firooz — Database Stats")
    print("=" * 50)
    print()
    print(f"  File:        {DB_PATH}")
    print(f"  File size:   {format_size(file_size)}")
    print(f"  Pages:       {page_count} used, {freelist_count} free ({page_size} bytes/page)")
    print()
    print("  Table breakdown:")
    print("  " + "-" * 40)

    total_rows = 0
    for (table_name,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
        total_rows += count
        print(f"    {table_name:<20} {count:>8} rows")

    print("  " + "-" * 40)
    print(f"    {'TOTAL':<20} {total_rows:>8} rows")
    print()

    # Warn if getting large
    if file_size > 500 * 1024 * 1024:
        print("  ⚠️  WARNING: Database is over 500 MB!")
        print("  Consider running: make db-vacuum")
    elif file_size > 100 * 1024 * 1024:
        print("  ⚠️  Database is over 100 MB. Keep an eye on it.")
    else:
        print("  ✅ Database size looks healthy.")

    print()
    conn.close()


if __name__ == "__main__":
    main()
