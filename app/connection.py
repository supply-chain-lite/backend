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

    def get_table_columns(self, table_name):
        """Return column names and types, excluding BLOB columns."""
        return self.execute(
            "select name, type from pragma_table_xinfo(?) where UPPER(type) != 'BLOB'", (table_name,)
        ).fetchall()

    def get_table_object(self, table_name):
        """Return the table or view type row, or None if missing."""
        return self.execute(
            "select type from sqlite_master where type in ('table', 'view') collate nocase and name=? collate nocase",
            (table_name,),
        ).fetchone()

    def get_table_column(self, table_name, column_name):
        """Return an existence row for a column, including generated columns."""
        return self.execute(
            "SELECT 1 FROM pragma_table_xinfo(?) WHERE name = ? COLLATE NOCASE",
            (
                table_name,
                column_name,
            ),
        ).fetchone()

    def get_column_defaults(self, table_name):
        """Return column names and their SQL default expressions."""
        return self.execute(
            "select name, [dflt_value] from pragma_table_xinfo(?) WHERE [dflt_value] is not null;", (table_name,)
        ).fetchall()

    def get_generated_columns(self, table_name):
        """Return name rows for virtual and stored generated columns."""
        return self.execute("select name from pragma_table_xinfo(?) WHERE hidden in (2, 3);", (table_name,)).fetchall()

    def get_object_types(self, table_names):
        """Return matching input names and catalog types, preserving duplicates."""
        if not table_names:
            return []
        placeholders = ",".join("(?)" for _ in table_names)
        query = "SELECT t1.table_name, sqlite_master.type FROM ( SELECT column1 AS table_name FROM (VALUES {placeholders} ) ) as t1, sqlite_master WHERE T1.table_name = sqlite_master.name COLLATE NOCASE".format(
            placeholders=placeholders
        )
        return self.execute(query, table_names).fetchall()

    def get_default_table_groups(self):
        """Return fallback table and view groups, excluding SQLite internal objects."""
        return self.execute(
            "select CASE WHEN type = 'table' THEN 'All Tables' WHEN type = 'view' THEN 'All Views' END as TableGroup, name as TableName, name as TableDisplayName, 1 as rowid from sqlite_master WHERE type in ('view', 'table') AND name NOT LIKE 'sqlite_%' COLLATE NOCASE ORDER BY 1, 2;"
        ).fetchall()

    def get_sql_objects(self):
        """Return table and view type/name rows in catalog order."""
        return self.execute(
            "select type, name from sqlite_master where type in ('table', 'view') COLLATE NOCASE ORDER BY 1, 2"
        ).fetchall()

    def get_object_ddl(self, object_name):
        """Return the object DDL row, or None if missing."""
        return self.execute("select sql from sqlite_master where name = ? COLLATE NOCASE", (object_name,)).fetchone()

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
