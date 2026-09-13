"""Entry point for master SQLite and database-specific model connections."""

from ..config import master_db
from .connection_sqlite import close_all_conn as close_all_conn
from .connection_sqlite import connection_pool as connection_pool
from .connection_sqlite import remove_connection_object as remove_connection_object
from .connection_sqlite import sqlite_connection


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
