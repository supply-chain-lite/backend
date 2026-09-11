"""Database entry points, file detection, pooling, and transaction lifecycle."""

import os
import threading

from . import connection_duckdb, connection_sqlite
from .config import master_db
from .logging_config import get_logger

_BACKENDS = {"sqlite": connection_sqlite, "duckdb": connection_duckdb}
connection_pool = {}
_pool_lock = threading.Lock()
logger = get_logger(__name__)


def _backend_for_connection(connection):
    for backend in _BACKENDS.values():
        if backend.owns_connection(connection):
            return backend
    raise TypeError(f"Unsupported database connection: {type(connection).__name__}")


class sql_connection:
    def __init__(self, db_id, db_path, db_access=1):
        self.connection, self.cursor = get_cursor(db_id, db_path, db_access)
        self._backend = _backend_for_connection(self.connection)
        self.dbType = self._backend.dbType
        self.db_id = db_id

    def __enter__(self):
        try:
            self.cursor.execute("BEGIN")
        except Exception:
            self.cursor.close()
            raise
        return self._backend.Cursor(self.connection, self.cursor, self.db_id)

    def __exit__(self, exception_type, exception_value, traceback_val):
        if exception_type:
            try:
                self.cursor.execute("ROLLBACK")
            except Exception as _e:
                logger.warning("Rollback failed for connection %s", self.db_id, exc_info=_e)
            finally:
                self.cursor.close()

            self._backend.handle_transaction_error(exception_type, exception_value, self.db_id)

            logger.error(
                "Database transaction failed on connection %s",
                self.db_id,
                exc_info=(exception_type, exception_value, traceback_val),
            )
            return False
        else:
            try:
                self.cursor.execute("COMMIT")
            except Exception:
                self.cursor.close()
                logger.exception("Commit failed on connection %s", self.db_id)
                raise
            finally:
                self.cursor.close()


def get_cursor(db_id, db_path, db_access=1):
    db_path = os.path.abspath(db_path)
    thread_id = (db_id == "master", threading.get_ident(), db_access)
    with _pool_lock:
        if db_path in connection_pool and thread_id in connection_pool[db_path]:
            connection = connection_pool[db_path][thread_id]
            return connection, _backend_for_connection(connection).get_cursor(connection)

        # DuckDB locks its file on Windows. Reuse the open database handle
        # and create a separate cursor/transaction for each caller/thread.
        by_thread = connection_pool.get(db_path, {})
        connection = None
        for key, existing in by_thread.items():
            backend = _backend_for_connection(existing)
            if backend.share_connection_across_threads:
                if key[2] != db_access:
                    raise ValueError(f"Close existing {backend.dbType} connections before changing read-only mode.")
                connection = existing
                break
        if connection is None:
            connection = init_db(db_path, db_access)
        if db_path in connection_pool:
            connection_pool[db_path][thread_id] = connection
        else:
            connection_pool[db_path] = {thread_id: connection}

        return connection, _backend_for_connection(connection).get_cursor(connection)


def detect_db_type(db_path):
    """Identify an existing database by its file signature, never its extension."""
    with open(db_path, "rb") as database_file:
        header = database_file.read(16)
    if header == b"SQLite format 3\x00":
        return "sqlite"
    if header[8:12] == b"DUCK":
        return "duckdb"
    raise ValueError(f"Unrecognized database file format: {db_path}")


def init_db(db_path, db_access=1):
    """Open an existing file with the engine selected from its header."""
    return _BACKENDS[detect_db_type(db_path)].init_db(os.fspath(db_path), db_access)


def this_cursor(conn, cursor, id):
    """Compatibility factory for callers wrapping an existing driver cursor."""
    return _backend_for_connection(conn).Cursor(conn, cursor, id)


def close_all_conn():
    with _pool_lock:
        conns = {id(conn): conn for by_thread in connection_pool.values() for conn in by_thread.values()}.values()

        connection_pool.clear()
    for conn in conns:
        conn.close()


def remove_connection_object(id):
    with _pool_lock:
        if id in connection_pool:
            for thread_id in connection_pool[id]:
                conn = connection_pool[id][thread_id]
                conn.close()
            del connection_pool[id]


def master_connection():
    return sql_connection("master", master_db)
