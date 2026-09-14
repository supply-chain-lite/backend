"""DuckDB connections owned by one context, with no application connection pool."""

import os
import re

import duckdb

from ..logging_config import get_logger

logger = get_logger(__name__)


def _allowed_directories_sql():
    """Render the configured remote prefixes as a DuckDB list literal."""
    raw_value = os.getenv("DUCKDB_ALLOWED_DIRECTORIES", "")
    directories = [part.strip() for part in raw_value.split(",") if part.strip()]
    quoted = ("'" + directory.replace("'", "''") + "'" for directory in directories)
    return "[" + ", ".join(quoted) + "]"


class duckdb_connection:
    def __init__(self, db_id, db_path, db_access=0):
        self.db_id = db_id
        self.db_path = db_path
        self.db_access = db_access
        self.connection = None
        self.cursor = None

    def __enter__(self):
        if self.connection is not None:
            raise RuntimeError("This DuckDB connection context is already open")
        if not os.path.isfile(self.db_path):
            raise FileNotFoundError(f"DBFile Doesn't exists in system, {self.db_path}")
        self.connection = duckdb.connect(database=self.db_path, read_only=self.db_access == 0)
        lock_result = self.connection.execute("SELECT current_setting('lock_configuration')")
        configuration_locked = bool(lock_result.fetchone()[0]) if lock_result is not None else False
        if not configuration_locked:
            self.connection.execute("LOAD httpfs;")
            self.connection.execute(f"SET allowed_directories = {_allowed_directories_sql()};")
            self.connection.execute("SET autoinstall_known_extensions = false;")
            self.connection.execute("SET autoload_known_extensions = false;")
            self.connection.execute("SET allow_persistent_secrets = false;")
            self.connection.execute("SET enable_external_access = false;")
            self.connection.execute("SET lock_configuration = true;")
        elif self.db_access == 0:
            # Another reader may have initialized and locked the shared
            # database configuration while this connection was opening.
            self.connection.execute("LOAD httpfs;")

        # DuckDB's cursor() creates another connection. Use this connection itself
        # for both execution and transactions so they always share one session.
        self.cursor = self.connection
        try:
            self.cursor.execute("BEGIN")
            return this_cursor(self.connection, self.cursor, self.db_id)
        except BaseException:
            self._close()
            raise

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
            self._close()
        return False

    def _rollback(self):
        try:
            self.cursor.execute("ROLLBACK")
        except Exception:
            logger.warning("Rollback failed for connection %s", self.db_id, exc_info=True)

    def _close(self):
        try:
            self.connection.close()
        finally:
            self.connection = None
            self.cursor = None


class this_cursor:
    def __init__(self, conn, cursor, id):
        self.conn = conn
        self.cursor = cursor
        self.id = id
        self._rowcount = 0
        self._description = []
        self._pending_description = None
        self._count_returning = False

    def _statement(self, query):
        statements = self.conn.extract_statements(query)
        if len(statements) != 1:
            raise ValueError("Exactly one SQL statement is required.")
        statement = statements[0]
        if statement.type in (duckdb.StatementType.ATTACH, duckdb.StatementType.DETACH):
            raise ValueError("ATTACH and DETACH are not allowed.")
        return statement

    @staticmethod
    def _has_returning(query):
        tokens = duckdb.tokenize(query)
        for index, (start, token_type) in enumerate(tokens):
            end = tokens[index + 1][0] if index + 1 < len(tokens) else len(query)
            if token_type == duckdb.token_type.keyword and re.match(r"RETURNING\b", query[start:end], re.IGNORECASE):
                return True
        return False

    def execute(self, query, args=tuple(), silent=False):
        try:
            statement = self._statement(query)
            self.cursor.execute(statement, args)
            self._description = [(col[0], str(col[1]), *col[2:]) for col in (self.cursor.description or [])]
            self._rowcount = 0
            self._count_returning = (
                duckdb.ExpectedResultType.CHANGED_ROWS in statement.expected_result_type and self._has_returning(query)
            )
            if (
                duckdb.ExpectedResultType.CHANGED_ROWS in statement.expected_result_type
                and not self._count_returning
                and self._description
                and self._description[0][:2] == ("Count", "BIGINT")
            ):
                row = self.cursor.fetchone()
                self._rowcount = row[0] if row else 0
                self._description = []
            if self._pending_description is not None:
                pending_query, description = self._pending_description
                if pending_query == query:
                    description[:] = self._description
                self._pending_description = None
        except Exception:
            if not silent:
                logger.exception("Query execution failed: %s", query)
            raise
        return self

    def executemany(self, query, seq_of_args):
        self._statement(query)
        total = 0
        for args in seq_of_args:
            self.execute(query, args)
            total += self._rowcount
        self._rowcount = total
        return self

    def executescript(self, query, args=tuple()):
        statements = self.conn.extract_statements(query)
        # Validate the entire script before executing any of its statements.
        for statement in statements:
            self._statement(statement.query)
        offset = 0
        if not isinstance(args, dict) and sum(len(s.named_parameters) for s in statements) != len(args):
            raise ValueError("The number of script parameters does not match the supplied arguments.")
        for statement in statements:
            count = len(statement.named_parameters)
            parameters = (
                {name: args[name] for name in statement.named_parameters}
                if isinstance(args, dict)
                else args[offset : offset + count]
            )
            self.execute(statement.query, parameters)
            offset += count
        return self

    def get_description(self, query):
        """Validate without executing writes; complete write-result columns on execute.

        The SQL client retains this list before execute() and reads it afterwards.
        DuckDB exposes RETURNING column names only when executing the statement,
        so execute() fills the same list in place without executing the write twice.
        """
        statement = self._statement(query)
        if statement.type == duckdb.StatementType.SELECT:
            relation = self.conn.sql(statement.query)
            description = [(col[0], str(col[1]), *col[2:]) for col in relation.description]
        else:
            if statement.type != duckdb.StatementType.EXPLAIN:
                self.conn.execute("EXPLAIN " + statement.query)
            description = []
        self._pending_description = (query, description)
        return description

    def rowcount(self):
        return self._rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        if self._count_returning and row is not None:
            self._rowcount += 1
        return row

    def fetchall(self):
        rows = self.cursor.fetchall()
        if self._count_returning:
            self._rowcount += len(rows)
        return rows

    def fetchmany(self, size):
        rows = self.cursor.fetchmany(size)
        if self._count_returning:
            self._rowcount += len(rows)
        return rows

    def description(self):
        return self._description

    def intermediate_commit(self):
        self.cursor.execute("COMMIT")
        self.cursor.execute("BEGIN")

    def rollback_changes(self):
        self.cursor.execute("ROLLBACK")
        self.cursor.execute("BEGIN")

    def get_table_columns(self, table_name):
        generated = self._generated_columns(self.get_object_ddl(table_name) or "")
        rows = self.execute("SELECT name, type, dflt_value FROM pragma_table_info(?)", (table_name,)).fetchall()
        return [(name, dtype, default, 2 if name.lower() in generated else 0) for name, dtype, default in rows]

    @staticmethod
    def _generated_columns(ddl):
        # DuckDB currently exposes generated expressions as defaults in column
        # metadata. Its canonical CREATE TABLE SQL retains GENERATED ALWAYS AS.
        tokens = duckdb.tokenize(ddl)
        depth = 0
        column = None
        generated = set()
        for index, (start, token_type) in enumerate(tokens):
            end = tokens[index + 1][0] if index + 1 < len(tokens) else len(ddl)
            token = ddl[start:end].strip()
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
            elif depth == 1:
                if token == ",":
                    column = None
                elif column is None:
                    column = token.removeprefix('"').removesuffix('"').replace('""', '"').lower()
                elif token_type == duckdb.token_type.keyword and token.upper() == "GENERATED":
                    generated.add(column)
        return generated

    def get_object_ddl(self, object_name):
        row = self.execute(
            """SELECT sql FROM duckdb_tables()
               WHERE database_name = current_database() AND schema_name = current_schema()
                 AND lower(table_name) = lower(?)
               UNION ALL
               SELECT sql FROM duckdb_views()
               WHERE database_name = current_database() AND schema_name = current_schema()
                 AND lower(view_name) = lower(?) AND NOT internal""",
            (object_name, object_name),
        ).fetchone()
        return row[0] if row else None

    def get_all_objects(self):
        return self.execute(
            """SELECT 'table' AS type, table_name AS name FROM duckdb_tables()
               WHERE database_name = current_database() AND schema_name = current_schema() AND NOT internal
               UNION ALL
               SELECT 'view', view_name FROM duckdb_views()
               WHERE database_name = current_database() AND schema_name = current_schema() AND NOT internal
               ORDER BY 1, 2"""
        ).fetchall()

    def check_if_table_exists(self, table_name):
        for object_type, name in self.get_all_objects():
            if name.lower() == table_name.lower():
                return (object_type,)
        return None
