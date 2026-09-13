"""Entry point for master SQLite and database-specific model connections."""

import re

from ..config import master_db
from .connection_sqlite import close_all_conn as close_all_conn
from .connection_sqlite import connection_pool as connection_pool
from .connection_sqlite import remove_connection_object as remove_connection_object
from .connection_sqlite import sqlite_connection

_SQLITE_WRITE_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "REPLACE",
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "VACUUM",
    "REINDEX",
    "ATTACH",
    "DETACH",
)


def _remove_sql_comments_and_literals(query):
    """Replace comments and quoted literals with spaces before keyword checks."""
    output = []
    index = 0
    while index < len(query):
        if query.startswith("--", index):
            newline = query.find("\n", index + 2)
            index = len(query) if newline == -1 else newline
            output.append(" ")
            continue
        if query.startswith("/*", index):
            end = query.find("*/", index + 2)
            index = len(query) if end == -1 else end + 2
            output.append(" ")
            continue
        if query[index] in "'\"`":
            quote = query[index]
            output.append(" ")
            index += 1
            while index < len(query):
                if query[index] == quote:
                    if index + 1 < len(query) and query[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        output.append(query[index])
        index += 1
    return "".join(output)


def query_requires_write_access(query, db_type="SQLITE"):
    """Return whether executing *query* requires a writable model connection.

    DuckDB's parser handles CTE-prefixed writes and engine-specific statements.
    SQLite connections are always opened writable, so the fallback only needs to
    identify writes for task-running guards and remains conservative for PRAGMA.
    """
    normalized = _remove_sql_comments_and_literals(query).strip()
    if not normalized:
        return False

    if db_type.upper() == "DUCKDB":
        try:
            import duckdb

            statements = duckdb.extract_statements(query)
            if not statements:
                return False
            for statement in statements:
                statement_type = statement.type.name
                if statement_type == "COPY":
                    return bool(re.search(r"\bFROM\b", statement.query, re.IGNORECASE))
                if statement_type in {
                    "ALTER",
                    "CREATE",
                    "DELETE",
                    "DROP",
                    "INSERT",
                    "MERGE_INTO",
                    "UPDATE",
                    "VACUUM",
                }:
                    return True
                if statement_type == "PRAGMA" and "=" in statement.query:
                    return True
            return False
        except Exception:
            # Let the database produce the definitive syntax error later; use a
            # conservative lexical result for access selection in the meantime.
            pass

    first_keyword = re.match(r"([A-Z]+)", normalized.upper())
    if first_keyword and first_keyword.group(1) in _SQLITE_WRITE_KEYWORDS:
        return True
    if first_keyword and first_keyword.group(1) == "PRAGMA":
        return True
    if re.match(r"WITH\b", normalized, re.IGNORECASE):
        return bool(re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE)\b", normalized, re.IGNORECASE))
    return False


class sql_connection:
    def __init__(self, db_id, db_path, db_type="SQLITE", db_access=None):
        # Master data always belongs to SQLite, regardless of model metadata.
        self.db_type = "SQLITE" if db_id == "master" else db_type.upper()
        if self.db_type not in ("SQLITE", "DUCKDB"):
            raise ValueError(f"Unsupported database type: {db_type}")
        self.db_id = db_id

        if self.db_type == "SQLITE":
            self.db_access = 1
            self._context = sqlite_connection(db_id, db_path)
        else:
            if db_access is None:
                db_access = 0
            if db_access not in (0, 1):
                raise ValueError("db_access must be 0 (read-only) or 1 (read-write)")
            self.db_access = db_access
            # SQLite installations do not need to import the optional DuckDB driver.
            from .connection_duckdb import duckdb_connection

            self._context = duckdb_connection(db_id, db_path, db_access)

    @property
    def connection(self):
        return self._context.connection

    @property
    def cursor(self):
        return self._context.cursor

    def __enter__(self):
        return self._context.__enter__()

    def __exit__(self, exception_type, exception_value, traceback_val):
        return self._context.__exit__(exception_type, exception_value, traceback_val)


def master_connection():
    return sql_connection("master", master_db, db_type="SQLITE", db_access=1)
