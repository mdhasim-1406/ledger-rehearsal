#!/usr/bin/env python3
"""Create a consistent SQLite online backup of the operational database."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def backup(source: str | Path, destination: str | Path) -> Path:
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if source == destination:
        raise ValueError("backup destination must differ from source")
    if not source.is_file():
        raise FileNotFoundError(f"source database does not exist: {source}")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # SQLite's backup API captures a transactionally consistent snapshot, including
    # committed WAL content; it does not copy live database files or credentials.
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30) as src:
            with sqlite3.connect(destination, timeout=30) as dst:
                src.backup(dst)
                check = dst.execute("PRAGMA quick_check").fetchone()
                if not check or check[0] != "ok":
                    raise sqlite3.DatabaseError(f"backup integrity check failed: {check}")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="path to the live operational SQLite database")
    parser.add_argument("destination", help="new backup file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        result = backup(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print(f"SQLite backup created: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
