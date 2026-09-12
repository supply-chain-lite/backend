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
    def __init__(self, db_id, db_path, db_access=None):
        self.db_id = db_id
        self.db_path = db_path
        self.db_access = db_access

    def __enter__(self):
        self.connection, self.cursor = get_cursor(self.db_id, self.db_path, self.db_access)
        self._backend = _backend_for_connection(self.connection)
        self.dbType = self._backend.dbType
        try:
            self.cursor.execute("BEGIN")
            return self._backend.Cursor(self.connection, self.cursor, self.db_id)
        except Exception:
            self._close()
            raise

    def _close(self):
        try:
            self.cursor.close()
        finally:
            if not self._backend.pool_connections:
                self.connection.close()

    def __exit__(self, exception_type, exception_value, traceback_val):
        if exception_type:
            try:
                self.cursor.execute("ROLLBACK")
            except Exception as _e:
                logger.warning("Rollback failed for connection %s", self.db_id, exc_info=_e)
            finally:
                self._close()

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
                logger.exception("Commit failed on connection %s", self.db_id)
                raise
            finally:
                self._close()


def get_cursor(db_id, db_path, db_access=None):
    db_path = os.path.abspath(db_path)
    # Only SQLite is pooled; its default access is read/write (1).
    pool_access = 1 if db_access is None else db_access
    thread_id = (db_id == "master", threading.get_ident(), pool_access)
    with _pool_lock:
        if db_path in connection_pool and thread_id in connection_pool[db_path]:
            connection = connection_pool[db_path][thread_id]
            return connection, _backend_for_connection(connection).get_cursor(connection)

        connection = init_db(db_path, db_access)
        backend = _backend_for_connection(connection)
        try:
            cursor = backend.get_cursor(connection)
        except Exception:
            connection.close()
            raise
        # SQLite retains per-thread connections. DuckDB is owned by the
        # transaction and must close both its cursor and parent connection.
        if backend.pool_connections:
            connection_pool.setdefault(db_path, {})[thread_id] = connection
        return connection, cursor


def detect_db_type(db_path):
    """Identify an existing database by its file signature, never its extension."""
    with open(db_path, "rb") as database_file:
        header = database_file.read(16)
    if header == b"SQLite format 3\x00":
        return "sqlite"
    if header[8:12] == b"DUCK":
        return "duckdb"
    raise ValueError(f"Unrecognized database file format: {db_path}")


def init_db(db_path, db_access=None):
    """Open an existing file; default to read-only for DuckDB, read/write for SQLite."""
    backend = _BACKENDS[detect_db_type(db_path)]
    if db_access is None:
        return backend.init_db(os.fspath(db_path))
    return backend.init_db(os.fspath(db_path), db_access)


def this_cursor(conn, cursor, id):
    """Compatibility factory for callers wrapping an existing driver cursor."""
    return _backend_for_connection(conn).Cursor(conn, cursor, id)


def close_all_conn():
    with _pool_lock:
        conns = {id(conn): conn for by_thread in connection_pool.values() for conn in by_thread.values()}.values()

        connection_pool.clear()
    for conn in conns:
        conn.close()


def remove_connection_object(db_path):
    db_path = os.path.abspath(db_path)
    with _pool_lock:
        if db_path in connection_pool:
            for thread_id in connection_pool[db_path]:
                conn = connection_pool[db_path][thread_id]
                conn.close()
            del connection_pool[db_path]


def master_connection():
    return sql_connection("master", master_db)


def create_database(db_path, db_type, db_sql):
    db_path = os.path.abspath(db_path)
    backend = _BACKENDS[db_type]
    connection = backend.init_db(os.fspath(db_path))
    cursor = backend.get_cursor(connection)
    try:
        cursor.execute(db_sql)
        connection.commit()
    finally:
        cursor.close()
        connection.close()