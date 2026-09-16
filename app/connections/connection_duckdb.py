"""DuckDB connections owned by one context, with no application connection pool."""

import math
import os
import re
import threading

import duckdb

from ..logging_config import get_logger

logger = get_logger(__name__)


def _duckdb_extensions():
    """Return unique, normalized DuckDB extensions configured for loading."""
    configured = os.getenv("DUCKDB_EXTENSIONS", "httpfs")
    extensions = tuple(
        dict.fromkeys(extension.strip().lower() for extension in configured.split(",") if extension.strip())
    )
    if not extensions:
        raise ValueError("DUCKDB_EXTENSIONS must contain at least one extension")
    return extensions


def _quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


def _allowed_directories_sql():
    """Render the configured remote prefixes as a DuckDB list literal."""
    raw_value = os.getenv("DUCKDB_ALLOWED_DIRECTORIES", "")
    directories = [part.strip() for part in raw_value.split(",") if part.strip()]
    return "[" + ", ".join(_quoted(directory) for directory in directories) + "]"


def _positive_int_env(name, default):
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _positive_float_env(name, default):
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive number")
    return parsed


def _duckdb_resource_config():
    """Return startup resource limits for every DuckDB model connection."""
    memory_limit = os.getenv("DUCKDB_MEMORY_LIMIT", "1GB").strip()
    max_temp_directory_size = os.getenv("DUCKDB_MAX_TEMP_DIRECTORY_SIZE", "2GB").strip()
    if not memory_limit:
        raise ValueError("DUCKDB_MEMORY_LIMIT must not be empty")
    if not max_temp_directory_size:
        raise ValueError("DUCKDB_MAX_TEMP_DIRECTORY_SIZE must not be empty")
    return {
        "memory_limit": memory_limit,
        "threads": _positive_int_env("DUCKDB_THREADS", 2),
        "max_temp_directory_size": max_temp_directory_size,
    }


def _duckdb_query_timeout_seconds():
    return _positive_float_env("DUCKDB_QUERY_TIMEOUT_SECONDS", 60)


def duckdb_resource_config():
    """Return startup resource limits for direct DuckDB maintenance operations."""
    return _duckdb_resource_config()


def run_duckdb_operation(connection, operation, timeout_seconds=None):
    """Run a native DuckDB operation with the configured interrupt timeout."""
    if timeout_seconds is None:
        timeout_seconds = _duckdb_query_timeout_seconds()
    timed_out = threading.Event()

    def interrupt():
        timed_out.set()
        try:
            connection.interrupt()
        except Exception:
            logger.warning("Failed to interrupt timed-out DuckDB operation", exc_info=True)

    timer = threading.Timer(timeout_seconds, interrupt)
    timer.daemon = True
    timer.start()
    try:
        return operation()
    except duckdb.InterruptException as exc:
        if timed_out.is_set():
            raise TimeoutError(f"DuckDB operation exceeded the {timeout_seconds:g}-second time limit") from exc
        raise
    finally:
        timer.cancel()
        timer.join()


def _s3_secret_sql():
    """Build the session-scoped S3 secret that lets httpfs sign its requests.

    Configured keys win. Ambient credential discovery (environment, profile,
    instance role) requires an explicit opt-in so local connections do not pay
    for unsuccessful credential lookups. Return None when S3 is unconfigured.
    """
    fields = ["TYPE s3"]
    key_id = os.getenv("S3_ACCESS_KEY")
    secret = os.getenv("S3_SECRET_KEY")
    if key_id and secret:
        fields += [f"KEY_ID {_quoted(key_id)}", f"SECRET {_quoted(secret)}"]
    elif os.getenv("DUCKDB_S3_CREDENTIAL_CHAIN", "false").strip().lower() in ("1", "true", "yes", "on"):
        fields += ["PROVIDER credential_chain", "REFRESH auto"]
    else:
        return None
    region = os.getenv("S3_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        fields.append(f"REGION {_quoted(region)}")
    endpoint = os.getenv("S3_URL")
    if endpoint:
        scheme, _, host = endpoint.rpartition("://")
        fields += [f"ENDPOINT {_quoted(host)}", f"USE_SSL {_quoted(scheme != 'http')}", "URL_STYLE 'path'"]
    return "CREATE OR REPLACE SECRET model_s3 (" + ", ".join(fields) + ");"


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
        self.connection = duckdb.connect(
            database=self.db_path,
            read_only=self.db_access == 0,
            config=_duckdb_resource_config(),
        )

        try:
            self._loaded_extensions = set()
            # Secret-manager settings must precede any secret use (including shared
            # instance state from another connection). Extensions load next, then
            # the remaining sandbox settings, then the optional S3 secret, then
            # external access is disabled.
            self._apply_settings("SET allow_persistent_secrets = false;")
            for extension in _duckdb_extensions():
                self.connection.execute(f"LOAD {extension};")
                self._loaded_extensions.add(extension)
            self._apply_settings(
                f"SET allowed_directories = {_allowed_directories_sql()};",
                "SET autoinstall_known_extensions = false;",
                "SET autoload_known_extensions = false;",
            )
            self._create_s3_secret()
            self._apply_settings("SET enable_external_access = false;")
            # DuckDB's cursor() creates another connection. Use this connection itself
            # for both execution and transactions so they always share one session.
            self.cursor = self.connection
            self.cursor.execute("BEGIN")
            return this_cursor(
                self.connection,
                self.cursor,
                self.db_id,
                query_timeout_seconds=_duckdb_query_timeout_seconds(),
            )
        except BaseException:
            self._close()
            raise

    def _create_s3_secret(self):
        """Leave remote reads unsigned unless S3 credentials are configured."""
        secret_sql = _s3_secret_sql()
        if secret_sql is None:
            return
        if not (os.getenv("S3_ACCESS_KEY") and os.getenv("S3_SECRET_KEY")):
            if "aws" not in self._loaded_extensions:
                try:
                    # credential_chain lives in the aws extension; explicit keys do not need it.
                    self.connection.execute("LOAD aws;")
                    self._loaded_extensions.add("aws")
                except duckdb.Error:
                    logger.warning("DuckDB 'aws' extension is unavailable; S3 access needs configured keys")
        try:
            self.connection.execute(secret_sql)
        except duckdb.Error:
            logger.warning("Could not configure DuckDB S3 credentials; remote reads stay unsigned", exc_info=True)

    def _apply_settings(self, *statements):
        for statement in statements:
            try:
                self.connection.execute(statement)
            except duckdb.InvalidInputException:
                # These settings belong to the database instance, which DuckDB shares
                # between connections to the same file. Another connection may already
                # have applied this policy (and may have initialized the secret manager
                # before disabling external access). Tolerate only that shared state.
                if self._setting_already_enforced(statement):
                    continue
                raise

    def _setting_already_enforced(self, statement):
        if not self.connection.execute("SELECT current_setting('enable_external_access')").fetchone()[0]:
            return True
        if "allow_persistent_secrets" in statement:
            return not self.connection.execute("SELECT current_setting('allow_persistent_secrets')").fetchone()[0]
        return False

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
    def __init__(self, conn, cursor, id, query_timeout_seconds=60):
        self.conn = conn
        self.cursor = cursor
        self.id = id
        self.query_timeout_seconds = query_timeout_seconds
        self._rowcount = 0
        self._description = []
        self._pending_description = None
        self._count_returning = False

    def _run_with_timeout(self, operation):
        return run_duckdb_operation(self.conn, operation, self.query_timeout_seconds)

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
            self._run_with_timeout(lambda: self.cursor.execute(statement, args))
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
                row = self._run_with_timeout(self.cursor.fetchone)
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
            relation = self._run_with_timeout(lambda: self.conn.sql(statement.query))
            description = [(col[0], str(col[1]), *col[2:]) for col in relation.description]
        else:
            if statement.type != duckdb.StatementType.EXPLAIN:
                self._run_with_timeout(lambda: self.conn.execute("EXPLAIN " + statement.query))
            description = []
        self._pending_description = (query, description)
        return description

    def rowcount(self):
        return self._rowcount

    def fetchone(self):
        row = self._run_with_timeout(self.cursor.fetchone)
        if self._count_returning and row is not None:
            self._rowcount += 1
        return row

    def fetchall(self):
        rows = self._run_with_timeout(self.cursor.fetchall)
        if self._count_returning:
            self._rowcount += len(rows)
        return rows

    def fetchmany(self, size):
        rows = self._run_with_timeout(lambda: self.cursor.fetchmany(size))
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
