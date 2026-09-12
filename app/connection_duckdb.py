"""DuckDB connection setup and cursor operations."""

import os
from collections import deque

import duckdb

from .logging_config import get_logger

logger = get_logger(__name__)
dbType = "duckdb"
pool_connections = False


def owns_connection(connection):
    return isinstance(connection, duckdb.DuckDBPyConnection)


def get_cursor(connection):
    return connection.cursor()


def handle_transaction_error(exception_type, exception_value, db_id):
    # Propagate the original DuckDB exception, including read-only errors.
    return None


def init_db(db_path, db_access=0):
    return duckdb.connect(
        os.fspath(db_path),
        read_only=(db_access == 0),
        config={
            "enable_external_access": "false",
            "autoload_known_extensions": "false",
            "autoinstall_known_extensions": "false",
        },
    )


# Catalog functions include system objects; restrict them to the model schema.
_DUCKDB_OBJECTS = """
    SELECT 'table' AS type, table_name AS name, sql
    FROM duckdb_tables()
    WHERE database_name = current_database() AND schema_name = current_schema() AND NOT internal
    UNION ALL
    SELECT 'view' AS type, view_name AS name, sql
    FROM duckdb_views()
    WHERE database_name = current_database() AND schema_name = current_schema() AND NOT internal
    UNION ALL
    SELECT 'index' AS type, index_name AS name, sql
    FROM duckdb_indexes()
    WHERE database_name = current_database() AND schema_name = current_schema()
"""


def _duckdb_tokens(query):
    """Return lexical tokens without treating quoted strings as SQL keywords."""
    tokens = duckdb.tokenize(query)
    return [
        (query[start : tokens[i + 1][0] if i + 1 < len(tokens) else len(query)].strip(), kind)
        for i, (start, kind) in enumerate(tokens)
    ]


class Cursor:
    dbType = "duckdb"

    def __init__(self, conn, cursor, id):
        self.conn = conn
        self.cursor = cursor
        self.id = id
        self._affected_rows = 0
        self._description = ()
        self._result_rows = None

    def get_table_columns(self, table_name):
        """Return column names and types, excluding BLOB columns."""
        return self.execute(
            "SELECT column_name, data_type FROM duckdb_columns()\n                   WHERE database_name = current_database() AND schema_name = current_schema()\n                     AND lower(table_name) = lower(?) AND upper(data_type) != 'BLOB'\n                   ORDER BY column_index",
            (table_name,),
        ).fetchall()

    def get_table_object(self, table_name):
        """Return the table or view type row, or None if missing."""
        return self.execute(
            f"SELECT type FROM ({_DUCKDB_OBJECTS}) WHERE type IN ('table', 'view') AND lower(name) = lower(?)",
            (table_name,),
        ).fetchone()

    def get_table_column(self, table_name, column_name):
        """Return an existence row for a column, including generated columns."""
        return self.execute(
            "SELECT 1 FROM duckdb_columns()\n                   WHERE database_name = current_database() AND schema_name = current_schema()\n                     AND lower(table_name) = lower(?) AND lower(column_name) = lower(?)",
            (table_name, column_name),
        ).fetchone()

    def get_column_defaults(self, table_name):
        """Return column names and their SQL default expressions."""
        generated = {row[0] for row in self.get_generated_columns(table_name)}
        rows = self.execute(
            "SELECT column_name, column_default FROM duckdb_columns()\n                   WHERE database_name = current_database() AND schema_name = current_schema()\n                     AND lower(table_name) = lower(?) AND column_default IS NOT NULL\n                   ORDER BY column_index",
            (table_name,),
        ).fetchall()
        return [row for row in rows if row[0] not in generated]

    def get_generated_columns(self, table_name):
        """Return name rows for virtual and stored generated columns."""
        # DuckDB reports generated expressions as defaults and leaves
        # information_schema.is_generated NULL; inspect catalog DDL tokens.
        row = self.get_object_ddl(table_name)
        if row is None or self.get_table_object(table_name) != ("table",):
            return []
        columns = []
        depth = 0
        column_name = None
        for token, kind in _duckdb_tokens(row[0]):
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
            elif depth == 1 and token == ",":
                column_name = None
            elif depth == 1 and column_name is None:
                column_name = token[1:-1].replace('""', '"') if token.startswith('"') else token
            elif depth == 1 and kind == duckdb.token_type.keyword and (token.upper() == "GENERATED"):
                columns.append((column_name,))
        return columns

    def get_object_types(self, table_names):
        """Return matching input names and catalog types, preserving duplicates."""
        if not table_names:
            return []
        placeholders = ",".join(("(?)" for _ in table_names))
        return self.execute(
            f"SELECT requested.name, objects.type\n                    FROM (VALUES {placeholders}) AS requested(name)\n                    JOIN ({_DUCKDB_OBJECTS}) AS objects ON lower(requested.name) = lower(objects.name)",
            table_names,
        ).fetchall()

    def get_default_table_groups(self):
        """Return fallback table and view groups, excluding SQLite internal objects."""
        return self.execute(
            f"SELECT CASE WHEN type = 'table' THEN 'All Tables' ELSE 'All Views' END,\n                           name, name, 1\n                    FROM ({_DUCKDB_OBJECTS}) WHERE type IN ('table', 'view') ORDER BY 1, 2"
        ).fetchall()

    def get_sql_objects(self):
        """Return table and view type/name rows in catalog order."""
        return self.execute(
            f"SELECT type, name FROM ({_DUCKDB_OBJECTS}) WHERE type IN ('table', 'view') ORDER BY 1, 2"
        ).fetchall()

    def get_object_ddl(self, object_name):
        """Return the object DDL row, or None if missing."""
        return self.execute(
            f"SELECT sql FROM ({_DUCKDB_OBJECTS}) WHERE lower(name) = lower(?)", (object_name,)
        ).fetchone()

    def rowcount(self):
        return self._affected_rows

    def execute(self, query, args=tuple(), silent=False):
        if ";" in query.strip().rstrip(";"):
            raise ValueError("; is not allowed in query to prevent SQL injection.")
        try:
            return self._execute_duckdb(query, args)
        except Exception:
            if not silent:
                logger.exception("Query execution failed: %s", query)
            raise

    def executemany(self, query, seq_of_args):
        if ";" in query.strip().rstrip(";"):
            raise ValueError("; is not allowed in query to prevent SQL injection.")
        try:
            total = 0
            rows = deque()
            self._description = ()
            for args in seq_of_args:
                self._execute_duckdb(query, args)
                total += self._affected_rows
                rows.extend(self.fetchall())
            self._affected_rows = total
            self._result_rows = rows
            return self
        except Exception:
            logger.exception("Batch query execution failed: %s", query)
            raise

    def executescript(self, query, args=tuple()):
        try:
            statements = self.cursor.extract_statements(query)
            if len(statements) == 1:
                return self._execute_duckdb(query, args)
            if args:
                raise ValueError("Parameters require a single DuckDB statement.")
            self._result_rows = deque()
            self._description = ()
            self._affected_rows = 0
            for statement in statements:
                self._execute_duckdb(statement.query, ())
            return self
        except Exception:
            logger.exception("Query execution failed: %s", query)
            raise

    def get_description(self, query):
        try:
            statements = self.cursor.extract_statements(query)
            if len(statements) != 1:
                raise ValueError("Exactly one SQL statement is required.")
            # Bind on the current transaction without executing modifying SQL.
            if statements[0].type == duckdb.StatementType.SELECT:
                rows = self.cursor.execute("DESCRIBE " + query).fetchall()
                return tuple((row[0], row[1]) for row in rows)
            self.cursor.execute("EXPLAIN " + query)
            return ()
        except Exception:
            logger.exception("Query execution failed: %s", query)
            raise

    def _execute_duckdb(self, query, args):
        statements = self.cursor.extract_statements(query)
        if len(statements) != 1:
            raise ValueError("Exactly one SQL statement is required.")
        if statements[0].type in (duckdb.StatementType.ATTACH, duckdb.StatementType.DETACH):
            raise PermissionError("Attaching or detaching databases is not allowed.")
        tokens = _duckdb_tokens(query)
        returning = any(kind == duckdb.token_type.keyword and token.upper() == "RETURNING" for token, kind in tokens)
        self._affected_rows = 0
        self._result_rows = None
        self.cursor.execute(query, args)
        self._description = tuple((col[0], str(col[1])) for col in self.cursor.description or ())
        if returning and statements[0].type in (
            duckdb.StatementType.INSERT,
            duckdb.StatementType.UPDATE,
            duckdb.StatementType.DELETE,
            duckdb.StatementType.MERGE_INTO,
        ):
            self._result_rows = deque(self.cursor.fetchall())
            self._affected_rows = len(self._result_rows)
        # Hide synthetic Count/Success results for non-returning DML and DDL.
        result_types = statements[0].expected_result_type
        if not returning and duckdb.ExpectedResultType.QUERY_RESULT not in result_types[:1]:
            row = self.cursor.fetchone()
            if self._description and self._description[0][0] == "Count" and row:
                self._affected_rows = row[0]
            self._description = ()
        return self

    def fetchone(self):
        if self._result_rows is not None:
            return self._result_rows.popleft() if self._result_rows else None
        return self.cursor.fetchone()

    def fetchall(self):
        if self._result_rows is not None:
            rows = list(self._result_rows)
            self._result_rows.clear()
            return rows
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
        return self._description

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
