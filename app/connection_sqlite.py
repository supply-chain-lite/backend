"""SQLite connection setup and cursor operations using APSW."""

import apsw
import apsw.ext

from .logging_config import get_logger

logger = get_logger(__name__)
dbType = "sqlite"
pool_connections = True


def owns_connection(connection):
    return isinstance(connection, apsw.Connection)


def get_cursor(connection):
    return connection.cursor()


def handle_transaction_error(exception_type, exception_value, db_id):
    if issubclass(exception_type, apsw.ReadOnlyError):
        logger.warning("Read-only access denied on connection %s", db_id)
        raise apsw.ReadOnlyError("Sorry!, You have Read Only access.") from exception_value


def authorizer(action, arg1, arg2, dbname, source):
    if action in (apsw.SQLITE_ATTACH, apsw.SQLITE_DETACH):
        return apsw.SQLITE_DENY
    return apsw.SQLITE_OK


def init_db(db_path, db_access=1):
    flags = apsw.SQLITE_OPEN_READONLY if db_access == 0 else apsw.SQLITE_OPEN_READWRITE
    conn = apsw.Connection(db_path, flags=flags)
    try:
        conn.setbusytimeout(30000)
        conn.setauthorizer(authorizer)
        conn.enable_load_extension(False)
        if db_access != 0:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn
    except Exception:
        conn.close()
        raise


class Cursor:
    dbType = "sqlite"

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
            "SELECT 1 FROM pragma_table_xinfo(?) WHERE name = ? COLLATE NOCASE", (table_name, column_name)
        ).fetchone()

    def get_column_defaults(self, table_name):
        """Return column names and their SQL default expressions."""
        return self.execute(
            'select name, "dflt_value" from pragma_table_xinfo(?) WHERE "dflt_value" is not null;', (table_name,)
        ).fetchall()

    def get_generated_columns(self, table_name):
        """Return name rows for virtual and stored generated columns."""
        return self.execute("select name from pragma_table_xinfo(?) WHERE hidden in (2, 3);", (table_name,)).fetchall()

    def get_object_types(self, table_names):
        """Return matching input names and catalog types, preserving duplicates."""
        if not table_names:
            return []
        placeholders = ",".join(("(?)" for _ in table_names))
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
            qd = apsw.ext.query_info(self.conn, query, actions=False, explain=False, explain_query_plan=False)
            return qd.description
        except Exception:
            logger.exception("Query execution failed: %s", query)
            raise

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchmany(self, size):
        rows = []
        for _ in range(size):
            row = self.fetchone()
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
