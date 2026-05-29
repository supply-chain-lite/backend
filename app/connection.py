import os
import threading

import apsw
import apsw.ext

from .config import master_db
from .logging_config import get_logger

connection_pool = {}
_pool_lock = threading.Lock()
logger = get_logger(__name__)


class sql_connection:
    def __init__(self, db_id, db_path):
        self.connection, self.cursor = get_cursor(db_id, db_path)
        self.db_id = db_id

    def __enter__(self):
        self.cursor.execute("BEGIN")
        return this_cursor(self.connection, self.cursor, self.db_id)

    def __exit__(self, exception_type, exception_value, traceback_val):
        if exception_type:
            try:
                self.cursor.execute("ROLLBACK")
            except Exception as _e:
                logger.warning("Rollback failed for connection %s", self.db_id, exc_info=_e)
            finally:
                self.cursor.close()

            if issubclass(exception_type, apsw.ReadOnlyError):
                logger.warning("Read-only access denied on connection %s", self.db_id)
                raise apsw.ReadOnlyError("Sorry!, You have Read Only access.") from exception_value

            logger.error(
                "Database transaction failed on connection %s",
                self.db_id,
                exc_info=(exception_type, exception_value, traceback_val),
            )
            raise
        else:
            try:
                self.cursor.execute("COMMIT")
            except Exception:
                self.cursor.close()
                logger.exception("Commit failed on connection %s", self.db_id)
                raise
            finally:
                self.cursor.close()


def authorizer(action, arg1, arg2, dbname, source):
    if action in (apsw.SQLITE_ATTACH, apsw.SQLITE_DETACH):
        return apsw.SQLITE_DENY
    return apsw.SQLITE_OK


def get_cursor(db_id, db_path):
    thread_id = threading.get_ident()
    if db_id == "master":
        thread_id = f"master-{thread_id}"
    with _pool_lock:
        if db_path in connection_pool and thread_id in connection_pool[db_path]:
            connection = connection_pool[db_path][thread_id]
            return connection, connection.cursor()

        connection = init_db(db_path)
        if db_path in connection_pool:
            connection_pool[db_path][thread_id] = connection
        else:
            connection_pool[db_path] = {thread_id: connection}

        return connection, connection.cursor()


def init_db(db_path, db_access=1):
    if not os.path.isfile(db_path):
        raise Exception(f"DBFile Doesn't exists in system, {db_path}")
    if db_access == 0:
        conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READONLY)
    else:
        conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READWRITE)
    conn.setbusytimeout(30000)
    conn.setauthorizer(authorizer)
    conn.enable_load_extension(False)
    conn.cursor().execute("PRAGMA journal_mode=WAL;")
    conn.cursor().execute("PRAGMA synchronous=NORMAL;")
    conn.cursor().execute("PRAGMA temp_store =  MEMORY")
    return conn


class this_cursor:
    def __init__(self, conn, cursor, id):
        self.conn = conn
        self.cursor = cursor
        self.id = id

    def rowcount(self):
        count_query = "SELECT CHANGES()"
        self.cursor.execute(count_query)
        return self.cursor.fetchone()[0]

    def execute(self, query, args=tuple()):
        if ";" in query.strip().rstrip(";"):
            raise ValueError("; is not allowed in query to prevent SQL injection.")
        try:
            self.cursor.execute(query, args)
        except Exception:
            logger.exception("Query execution failed: %s", query)
            raise
        return self.cursor

    def executemany(self, query, seq_of_args):
        if ";" in query.strip().rstrip(";"):
            raise ValueError("; is not allowed in query to prevent SQL injection.")
        try:
            self.cursor.executemany(query, seq_of_args)
        except Exception:
            logger.exception("Batch query execution failed: %s", query)
            raise
        return self.cursor

    def executescript(self, query, args=tuple()):
        try:
            self.cursor.execute(query, args)
        except Exception:
            logger.exception("Query execution failed: %s", query)
            raise
        return self.cursor

    def get_description(self, query):
        try:
            qd = apsw.ext.query_info(
                self.conn,
                query,
                actions=False,
                explain=False,
                explain_query_plan=False,
            )
            return qd.description
        except Exception:
            logger.exception("Query execution failed: %s", query)
            raise

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchmany(self, size):
        rows = []
        for _ in range(size):
            row = self.cursor.fetchone()
            if row is None:
                break
            rows.append(row)
        return rows

    def description(self):
        return self.cursor.description

    def intermediate_commit(self):
        try:
            self.cursor.execute("COMMIT")
            self.cursor.execute("BEGIN")
        except Exception:
            raise

    def rollback_changes(self):
        try:
            self.cursor.execute("ROLLBACK")
            self.cursor.execute("BEGIN")
        except Exception:
            raise


def close_all_conn():
    with _pool_lock:
        conns = list(conn for by_thread in connection_pool.values() for conn in by_thread.values())

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
