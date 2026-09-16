"""Entry point for master SQLite and database-specific model connections."""

import os
import re
import shutil
import sqlite3

import apsw
import duckdb
from fastapi import HTTPException

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


def _duckdb_explained_query(query):
    """Unwrap EXPLAIN, including ANALYZE and parenthesized options."""
    import duckdb

    # DuckDB token offsets are UTF-8 byte offsets; comments are omitted.
    encoded = query.encode("utf-8")
    offsets = [offset for offset, _ in duckdb.tokenize(query)]
    tokens = [re.match(rb"[A-Za-z_]+|.", encoded[offset:]).group().upper() for offset in offsets]
    index = 1  # Skip EXPLAIN.
    if tokens[index] == b"ANALYZE":
        index += 1
    elif tokens[index] == b"(":
        index += 1
        while tokens[index] != b")":
            index += 1
        index += 1
    return encoded[offsets[index] :].decode("utf-8")


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
                if statement_type == "EXPLAIN":
                    # DuckDB requires write access for explained writes even
                    # without ANALYZE; ANALYZE additionally executes the write.
                    if query_requires_write_access(_duckdb_explained_query(statement.query), db_type):
                        return True
                if statement_type == "COPY":
                    if re.search(r"\bFROM\b", statement.query, re.IGNORECASE):
                        return True
                    continue
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


def create_database(db_path, db_type, db_file):
    if db_type.upper() == "SQLITE":
        with sqlite3.connect(db_path) as model_db:
            with open(db_file, "r") as f:
                model_db.executescript(f.read())
    elif db_type.upper() == "DUCKDB":
        from .connection_duckdb import duckdb_resource_config, run_duckdb_operation

        con = duckdb.connect(db_path, config=duckdb_resource_config())
        try:
            with open(db_file, "r") as f:
                script = f.read()
            run_duckdb_operation(con, lambda: con.execute(script))
        finally:
            con.close()
    else:
        raise ValueError(f"Unsupported database type: {db_type}")


def vacuum_model(db_path, db_type):
    if db_type.upper() == "SQLITE":
        connection = apsw.Connection(db_path)
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.close()
    elif db_type.upper() == "DUCKDB":
        from .connection_duckdb import duckdb_resource_config, run_duckdb_operation

        con = duckdb.connect(db_path, config=duckdb_resource_config())
        try:
            run_duckdb_operation(con, lambda: con.execute("CHECKPOINT"))
        finally:
            con.close()
    else:
        raise ValueError(f"Unsupported database type: {db_type}")


def copy_database(src_db_path, dest_db_path, db_type, restore=False):
    if not os.path.exists(src_db_path):
        raise FileNotFoundError(f"Source database does not exist: {src_db_path}")
    if db_type.upper() == "SQLITE":
        if restore:
            backup_connection = apsw.Connection(src_db_path)
            this_connection = apsw.Connection(dest_db_path)
            try:
                with this_connection.backup("main", backup_connection, "main") as backup:
                    backup.step()  # copy entire database in one step
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to restore backup: {str(e)}")
            finally:
                this_connection.close()
                backup_connection.close()
        else:
            connection = apsw.Connection(src_db_path)
            connection.execute("VACUUM INTO ?", (dest_db_path,))
            connection.close()
    elif db_type.upper() == "DUCKDB":
        from .connection_duckdb import duckdb_resource_config, run_duckdb_operation

        conn = duckdb.connect(src_db_path, config=duckdb_resource_config())
        try:
            run_duckdb_operation(conn, lambda: conn.execute("CHECKPOINT"))
        finally:
            conn.close()
        dest_wal = f"{dest_db_path}.wal"
        shutil.copy(src_db_path, dest_db_path)
        if os.path.exists(dest_wal):
            os.remove(dest_wal)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")
