"""Recursively discover DuckDB files and plan an offline upgrade to 2.0 storage.

Default root: DATA_FOLDER from the environment, backend/.env, then backend/data.
Relative configured paths resolve from backend. Explicit paths override this root.
Preview first, then stop all services before running with --apply --offline.
Replaced originals are retained alongside each database as .pre-duckdb-2.bak.
"""

import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import duckdb
from dotenv import dotenv_values

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class NotDuckDB(ValueError):
    """Candidate does not have the native DuckDB signature."""


def data_directory():
    """Read configuration without app.config's startup side effects."""
    configured = os.getenv("DATA_FOLDER") or dotenv_values(BACKEND_ROOT / ".env").get("DATA_FOLDER")
    path = Path(configured) if configured else Path("data")
    return path if path.is_absolute() else BACKEND_ROOT / path


def discover(paths):
    """Collect unique candidates without following symlinks or junctions."""
    seen = set()
    candidates = []

    def scan_error(error):
        raise error

    for path in paths:
        path = Path(path).absolute()
        if path.is_symlink() or path.is_junction() or not path.is_dir():
            candidates.append(path)
            continue
        for root, directories, files in os.walk(path, followlinks=False, onerror=scan_error):
            directories[:] = sorted(
                name
                for name in directories
                if not name.startswith(".duckdb-migrate-")
                and not (Path(root) / name).is_symlink()
                and not (Path(root) / name).is_junction()
            )
            candidates.extend(
                Path(root) / name for name in sorted(files) if Path(name).suffix.lower() in {".db", ".duckdb"}
            )
    for path in candidates:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            yield path


def verify_duckdb(path):
    """Check native magic before connecting (DuckDB can auto-attach SQLite)."""
    with path.open("rb") as stream:
        header = stream.read(16)
    if header[8:12] != b"DUCK":
        raise NotDuckDB("not a native DuckDB database; left unchanged")
    # A matching header alone does not establish that the database is readable.
    with duckdb.connect(str(path), read_only=True) as connection:
        connection.execute("SELECT count(*) FROM duckdb_tables()").fetchone()
        if connection.execute("SELECT count(*) FROM duckdb_triggers()").fetchone()[0]:
            raise RuntimeError("Database has triggers, which EXPORT omits; manual migration required")
        if connection.execute(
            "SELECT encrypted FROM duckdb_databases() WHERE database_name = current_database()"
        ).fetchone()[0]:
            raise RuntimeError("Encrypted databases require manual migration preserving encryption")


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(source, target):
    """Check table structure and exact row multisets, plus stored catalog definitions."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"ATTACH {literal(source)} AS old (READ_ONLY)")
        connection.execute(f"ATTACH {literal(target)} AS new (READ_ONLY)")
        for function, columns in (
            ("duckdb_tables", "schema_name, table_name, sql"),
            ("duckdb_views", "schema_name, view_name, sql"),
            ("duckdb_indexes", "schema_name, index_name, sql"),
            ("duckdb_sequences", "schema_name, sequence_name, sql"),
            ("duckdb_types", "schema_name, type_name, logical_type, labels"),
            ("duckdb_functions", "schema_name, function_name, function_type, parameters, macro_definition"),
        ):
            internal_filter = "" if function in ("duckdb_indexes", "duckdb_sequences") else " AND NOT internal"
            query = f"SELECT {columns} FROM {function}() WHERE database_name = ?{internal_filter} ORDER BY 1, 2"
            if connection.execute(query, ["old"]).fetchall() != connection.execute(query, ["new"]).fetchall():
                raise ValueError(f"Catalog validation failed: {function}")
        tables = connection.execute(
            "SELECT schema_name, table_name FROM duckdb_tables() WHERE database_name = 'old' AND NOT internal"
        ).fetchall()
        for schema, table in tables:
            name = f"{identifier(schema)}.{identifier(table)}"
            for left, right in (("old", "new"), ("new", "old")):
                if connection.execute(
                    f"SELECT EXISTS (SELECT * FROM {left}.{name} EXCEPT ALL SELECT * FROM {right}.{name})"
                ).fetchone()[0]:
                    raise ValueError(f"Data validation failed: {name}")


def migrate(path, *, apply=False):
    if duckdb.__version__ != "2.0.0":
        raise RuntimeError("Run this script with the project's pinned DuckDB 2.0.0")
    path = Path(path).absolute()
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError(f"Expected a regular database file: {path}")
    backup = path.with_name(path.name + ".pre-duckdb-2.bak")
    if backup.exists() or backup.is_symlink():
        raise FileExistsError(f"Backup already exists; refusing to overwrite: {backup}")
    # Read-only planning never opens a writable connection or replays a WAL.
    if Path(str(path) + ".wal").exists():
        raise RuntimeError(f"WAL exists for {path}; stop writers and checkpoint with the current engine first")
    verify_duckdb(path)
    if not apply:
        return f"Would convert {path}; backup: {backup}"
    original = digest(path)
    # Same filesystem permits atomic replacement. Keep the original untouched until validated.
    with tempfile.TemporaryDirectory(prefix=".duckdb-migrate-", dir=path.parent) as temporary:
        folder = Path(temporary)
        snapshot = folder / "source.duckdb"
        converted = folder / "converted.duckdb"
        shutil.copy2(path, snapshot)
        if digest(snapshot) != original:
            raise RuntimeError("Source changed while copying; source was not replaced")
        with duckdb.connect(str(snapshot), read_only=True) as connection:
            connection.execute(f"EXPORT DATABASE {literal(folder / 'export')} (FORMAT PARQUET)")
        with duckdb.connect(str(converted), config={"storage_compatibility_version": "v2.0.0"}) as connection:
            connection.execute(f"IMPORT DATABASE {literal(folder / 'export')}")
            connection.execute("CHECKPOINT")
        validate(snapshot, converted)
        if digest(path) != original or Path(str(path) + ".wal").exists():
            raise RuntimeError("Source changed during migration; stop every reader/writer and retry")
        # Exclusive creation prevents accidental backup replacement.
        with backup.open("xb") as destination, path.open("rb") as source:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        if digest(backup) != original:
            raise RuntimeError(f"Backup validation failed; source unchanged, inspect {backup}")
        if digest(path) != original or Path(str(path) + ".wal").exists():
            raise RuntimeError("Source changed while backing up; source was not replaced")
        shutil.copystat(path, converted)
        with converted.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(converted, path)
    return f"Converted {path}; rollback backup: {backup}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "databases", type=Path, nargs="*", help="Files or directories instead of configured DATA_FOLDER"
    )
    parser.add_argument("--data-dir", type=Path, help="Root directory to scan recursively")
    parser.add_argument("--apply", action="store_true", help="Convert files; default is a read-only plan")
    parser.add_argument(
        "--offline", action="store_true", help="Confirm all services and external task programs are stopped"
    )
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("--apply requires --offline: stop API, scheduler, workers and external task programs first")
    if args.data_dir and args.databases:
        parser.error("Use either --data-dir or positional paths")
    if duckdb.__version__ != "2.0.0":
        parser.error("Run this script with the project's pinned DuckDB 2.0.0")
    roots = args.databases or [args.data_dir or data_directory()]
    for root in roots:
        print(f"Scanning: {root}")
    try:
        candidates = list(discover(roots))
    except OSError as exc:
        parser.exit(1, f"Discovery failed; no files migrated: {exc}\n")
    counts = {"planned": 0, "converted": 0, "skipped": 0, "failed": 0}
    for path in candidates:
        try:
            print(migrate(path, apply=args.apply))
            counts["converted" if args.apply else "planned"] += 1
        except NotDuckDB as exc:
            counts["skipped"] += 1
            print(f"Skipped {path}: {exc}")
        except Exception as exc:
            counts["failed"] += 1
            print(f"Failed {path}: {exc}")
    print("Summary: " + ", ".join(f"{count} {status}" for status, count in counts.items()))
    if not candidates:
        print("No .db or .duckdb candidates found.")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
