"""Pooled, always-writable SQLite connections and the APSW cursor interface."""

import os
import threading

import apsw
import apsw.ext

from ..logging_config import get_logger

logger = get_logger(__name__)
connection_pool = {}
_pool_lock = threading.Lock()


def authorizer(action, arg1, arg2, dbname, source):
    if action in (apsw.SQLITE_ATTACH, apsw.SQLITE_DETACH):
        return apsw.SQLITE_DENY
    return apsw.SQLITE_OK


def init_db(db_path):
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"DBFile Doesn't exists in system, {db_path}")
    conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READWRITE)
    try:
        conn.setbusytimeout(30000)
        conn.setauthorizer(authorizer)
        conn.enable_load_extension(False)
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
        finally:
            cursor.close()
    except BaseException:
        conn.close()
        raise
    return conn


def get_cursor(db_id, db_path):
    thread_id = threading.get_ident()
    if db_id == "master":
        thread_id = f"master-{thread_id}"
    with _pool_lock:
        thread_pool = connection_pool.setdefault(db_path, {})
        if thread_id not in thread_pool:
            thread_pool[thread_id] = init_db(db_path)
        connection = thread_pool[thread_id]
        return connection, connection.cursor()


class sqlite_connection:
    def __init__(self, db_id, db_path):
        self.db_id = db_id
        self.connection, self.cursor = get_cursor(db_id, db_path)

    def __enter__(self):
        try:
            self.cursor.execute("BEGIN")
        except BaseException:
            self.cursor.close()
            raise
        return this_cursor(self.connection, self.cursor, self.db_id)

    def __exit__(self, exception_type, exception_value, traceback_val):
        try:
            if exception_type is not None:
                self._rollback()
                logger.error(
                    "Database transaction failed on connection %s",
                    self.db_id,
                    exc_info=(exception_type, exception_value, traceback_val),
                )
            else:
                try:
                    self.cursor.execute("COMMIT")
                except BaseException:
                    self._rollback()
                    raise
        finally:
            self.cursor.close()
        return False

    def _rollback(self):
        try:
            self.cursor.execute("ROLLBACK")
        except Exception:
            logger.warning("Rollback failed for connection %s", self.db_id, exc_info=True)


class this_cursor:
    def __init__(self, conn, cursor, id):
        self.conn = conn
        self.cursor = cursor
        self.id = id

    def rowcount(self):
        count_query = "SELECT CHANGES()"
        self.cursor.execute(count_query)
        return self.cursor.fetchone()[0]

    def execute(self, query, args=tuple(), silent=False):
        if ";" in query.strip().rstrip(";"):
            raise ValueError("; is not allowed in query to prevent SQL injection.")
        try:
            self.cursor.execute(query, args)
        except Exception:
            if not silent:
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

    def get_table_columns(self, table_name):
        """Return column names and types"""
        return self.execute(
            "select name, type, dflt_value, hidden from pragma_table_xinfo(?) ", (table_name,)
        ).fetchall()

    def get_object_ddl(self, object_name):
        query = """select sql from sqlite_master
                    where name = ? COLLATE NOCASE"""
        row = self.execute(query, (object_name,)).fetchone()
        return row[0] if row else None

    def get_all_objects(self):
        query = """select type, name from sqlite_master
                    where type in ('table', 'view') COLLATE NOCASE
                      and substr(lower(name), 1, 7) <> 'sqlite_'
                      ORDER BY 1, 2"""
        return self.execute(query).fetchall()

    def check_if_table_exists(self, table_name):
        query = (
            "select type from sqlite_master where type in ('table', 'view') collate nocase and name=? collate nocase"
        )
        return self.execute(query, (table_name,)).fetchone()


def close_all_conn():
    with _pool_lock:
        conns = [conn for by_thread in connection_pool.values() for conn in by_thread.values()]
        connection_pool.clear()
    for conn in conns:
        conn.close()


def remove_connection_object(db_path):
    with _pool_lock:
        by_thread = connection_pool.pop(db_path, {})
        for conn in by_thread.values():
            conn.close()
