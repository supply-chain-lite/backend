"""Run with python -m unittest discover -s tests -p test_connections.py."""

import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import apsw
import duckdb

# Import only the connection layer, without reading .env or creating app folders.
config = types.ModuleType("app.config")
config.master_db = "unused"
config.LOG_FOLDER = "."
config.LOG_LEVEL = "INFO"
previous_config = sys.modules.get("app.config")
sys.modules["app.config"] = config
try:
    from app.connections import connection, connection_duckdb, connection_sqlite
finally:
    if previous_config is None:
        del sys.modules["app.config"]
    else:
        sys.modules["app.config"] = previous_config


class DuckDBS3SetupTests(unittest.TestCase):
    def open_connection(self, env):
        native = MagicMock()
        with (
            patch.dict(connection_duckdb.os.environ, env, clear=True),
            patch.object(connection_duckdb.os.path, "isfile", return_value=True),
            patch.object(connection_duckdb.duckdb, "connect", return_value=native),
        ):
            with connection_duckdb.duckdb_connection("model", "unused.db") as cursor:
                self.assertIs(cursor.conn, native)
        return [call.args[0] for call in native.execute.call_args_list if isinstance(call.args[0], str)]

    def test_unconfigured_connections_skip_s3_setup_every_time(self):
        for env in (
            {},
            {"S3_ACCESS_KEY": "partial"},
            {"S3_REGION": "us-east-1"},
            {"DUCKDB_S3_CREDENTIAL_CHAIN": "false"},
        ):
            with self.subTest(env=env):
                for _ in range(2):
                    statements = self.open_connection(env)
                    self.assertNotIn("LOAD aws;", statements)
                    self.assertFalse(any(sql.startswith("CREATE OR REPLACE SECRET") for sql in statements))
                    self.assertIn("BEGIN", statements)
                    self.assertIn("COMMIT", statements)

    def test_explicit_keys_create_secret_without_aws_discovery(self):
        statements = self.open_connection(
            {
                "S3_ACCESS_KEY": "test-key",
                "S3_SECRET_KEY": "test-secret",
                "DUCKDB_S3_CREDENTIAL_CHAIN": "true",
            }
        )
        self.assertNotIn("LOAD aws;", statements)
        secret = next(sql for sql in statements if sql.startswith("CREATE OR REPLACE SECRET"))
        self.assertIn("KEY_ID 'test-key'", secret)
        self.assertIn("SECRET 'test-secret'", secret)
        self.assertNotIn("credential_chain", secret)
        self.assertLess(statements.index(secret), statements.index("SET enable_external_access = false;"))

    def test_credential_discovery_requires_opt_in(self):
        statements = self.open_connection({"DUCKDB_S3_CREDENTIAL_CHAIN": "true"})
        secret = next(sql for sql in statements if sql.startswith("CREATE OR REPLACE SECRET"))
        self.assertIn("PROVIDER credential_chain", secret)
        self.assertIn("REFRESH auto", secret)
        self.assertLess(statements.index("LOAD aws;"), statements.index(secret))
        self.assertLess(statements.index(secret), statements.index("SET enable_external_access = false;"))

    def test_configured_extensions_are_loaded_once_in_order(self):
        statements = self.open_connection({"DUCKDB_EXTENSIONS": "json, httpfs, json, excel"})
        loads = [statement for statement in statements if statement.startswith("LOAD ")]
        self.assertEqual(loads, ["LOAD json;", "LOAD httpfs;", "LOAD excel;"])

    def test_resource_limits_are_supplied_at_connection_start(self):
        native = MagicMock()
        with (
            patch.dict(
                connection_duckdb.os.environ,
                {
                    "DUCKDB_MEMORY_LIMIT": "256MB",
                    "DUCKDB_THREADS": "3",
                    "DUCKDB_MAX_TEMP_DIRECTORY_SIZE": "512MB",
                },
                clear=True,
            ),
            patch.object(connection_duckdb.os.path, "isfile", return_value=True),
            patch.object(connection_duckdb.duckdb, "connect", return_value=native) as connect,
        ):
            with connection_duckdb.duckdb_connection("model", "unused.db"):
                pass
        self.assertEqual(
            connect.call_args.kwargs["config"],
            {"memory_limit": "256MB", "threads": 3, "max_temp_directory_size": "512MB"},
        )


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parent
        self.folder = (self.test_root / f"connections-{uuid.uuid4().hex}").resolve()
        assert self.folder.is_relative_to(self.test_root)
        self.folder.mkdir()
        self.sqlite_path = str(self.folder / "sqlite.db")
        self.duckdb_path = str(self.folder / "duckdb.db")
        apsw.Connection(self.sqlite_path).close()
        duckdb.connect(self.duckdb_path).close()
        self.log_patches = [
            patch.object(module, "logger", MagicMock()) for module in (connection_sqlite, connection_duckdb)
        ]
        for log_patch in self.log_patches:
            log_patch.start()

    def tearDown(self):
        connection.close_all_conn()
        for log_patch in self.log_patches:
            log_patch.stop()
        for path in self.folder.iterdir():
            path.unlink()
        self.folder.rmdir()

    def connect(self, engine="SQLITE", access=None):
        path = self.sqlite_path if engine.upper() == "SQLITE" else self.duckdb_path
        return connection.sql_connection("model", path, db_type=engine, db_access=access)

    def test_sqlite_pool_and_existing_cursor(self):
        with self.connect() as cursor:
            first = cursor.conn
            cursor.execute("CREATE TABLE items (id INTEGER, name TEXT)")
            cursor.executemany("INSERT INTO items VALUES (?, ?)", [(1, "one"), (2, "two")])
            self.assertEqual(cursor.rowcount(), 1)
            self.assertEqual(cursor.get_description("SELECT name FROM items")[0][0], "name")
            self.assertEqual(cursor.get_table_columns("items")[0], ("id", "INTEGER", None, 0))
        with self.connect() as cursor:
            self.assertIs(first, cursor.conn)
            self.assertEqual(cursor.execute("SELECT name FROM items ORDER BY id").fetchall(), [("one",), ("two",)])

    def test_sqlite_ignores_access_mode_and_reuses_writable_connection(self):
        with self.connect() as cursor:
            writable = cursor.conn
            cursor.execute("CREATE TABLE items (id INTEGER)")
        context = self.connect(access=0)
        self.assertEqual(context.db_access, 1)
        with context as cursor:
            self.assertIs(writable, cursor.conn)
            self.assertEqual(cursor.execute("SELECT * FROM items").fetchall(), [])
            cursor.execute("INSERT INTO items VALUES (1)")
        with self.connect(access=1) as cursor:
            self.assertIs(writable, cursor.conn)
            self.assertEqual(cursor.execute("SELECT * FROM items").fetchall(), [(1,)])

    def test_sqlite_pool_cleanup_closes_model_and_master_connections(self):
        with self.connect() as cursor:
            model_connection = cursor.conn
        with connection.sql_connection("master", self.sqlite_path) as cursor:
            master_connection = cursor.conn
            self.assertIsNot(model_connection, master_connection)
        connection.remove_connection_object(self.sqlite_path)
        self.assertNotIn(self.sqlite_path, connection.connection_pool)
        for native in (model_connection, master_connection):
            with self.assertRaises(apsw.ConnectionClosedError):
                native.execute("SELECT 1")
        with self.connect() as cursor:
            reopened = cursor.conn
            self.assertIsNot(model_connection, reopened)
        connection.close_all_conn()
        self.assertEqual(connection.connection_pool, {})
        with self.assertRaises(apsw.ConnectionClosedError):
            reopened.execute("SELECT 1")

    def test_master_stays_sqlite_and_writable(self):
        with patch.object(connection, "master_db", self.sqlite_path):
            with connection.master_connection() as cursor:
                cursor.execute("CREATE TABLE master_data (id INTEGER)")
            with connection.sql_connection("master", self.sqlite_path, db_type="DUCKDB") as cursor:
                self.assertIsInstance(cursor, connection_sqlite.this_cursor)
                cursor.execute("INSERT INTO master_data VALUES (1)")

    def test_both_engines_rollback_and_partial_commits(self):
        for engine in ("SQLITE", "DUCKDB"):
            with self.subTest(engine=engine):
                with self.connect(engine, 1) as cursor:
                    cursor.execute("CREATE TABLE items (id INTEGER)")
                with self.assertRaisesRegex(RuntimeError, "stop"):
                    with self.connect(engine, 1) as cursor:
                        cursor.execute("INSERT INTO items VALUES (1)")
                        cursor.intermediate_commit()
                        cursor.execute("INSERT INTO items VALUES (2)")
                        cursor.rollback_changes()
                        cursor.execute("INSERT INTO items VALUES (3)")
                        raise RuntimeError("stop")
                with self.connect(engine) as cursor:
                    self.assertEqual(cursor.execute("SELECT * FROM items").fetchall(), [(1,)])

    def test_sqlite_failed_commit_rolls_back_before_pool_reuse(self):
        context = self.connect()
        context.connection.execute("PRAGMA foreign_keys=ON")
        with context as cursor:
            cursor.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            cursor.execute("CREATE TABLE child (id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)")
        with self.assertRaises(apsw.ConstraintError):
            with self.connect() as cursor:
                cursor.execute("INSERT INTO child VALUES (1)")
        with self.connect() as cursor:
            self.assertEqual(cursor.execute("SELECT * FROM child").fetchall(), [])

    def test_duckdb_opens_fresh_and_closes_on_success(self):
        context = self.connect("duckdb", 1)
        self.assertIsNone(context.connection)
        with context as cursor:
            first = cursor.conn
            cursor.execute("CREATE TABLE items (id INTEGER)")
            cursor.execute("INSERT INTO items VALUES (1)")
        with self.assertRaises(duckdb.ConnectionException):
            first.execute("SELECT 1")
        with self.connect("DUCKDB") as cursor:
            self.assertIsNot(first, cursor.conn)
            self.assertEqual(cursor.execute("SELECT * FROM items").fetchall(), [(1,)])
        self.assertEqual(connection.connection_pool, {})

    def test_duckdb_default_read_only_and_exception_cleanup(self):
        with self.connect("DUCKDB", 1) as cursor:
            cursor.execute("CREATE TABLE items (id INTEGER)")
        with self.assertRaises(duckdb.InvalidInputException):
            with self.connect("DUCKDB") as cursor:
                native = cursor.conn
                cursor.execute("INSERT INTO items VALUES (1)")
        with self.assertRaises(duckdb.ConnectionException):
            native.execute("SELECT 1")
        with self.connect("DUCKDB", 1) as cursor:
            self.assertEqual(cursor.execute("SELECT * FROM items").fetchall(), [])

    def test_duckdb_overlapping_readers_use_different_connections(self):
        with self.connect("DUCKDB") as first, self.connect("DUCKDB") as second:
            self.assertIsNot(first.conn, second.conn)
            self.assertEqual(first.execute("SELECT 1").fetchall(), [(1,)])
            self.assertEqual(second.execute("SELECT 2").fetchall(), [(2,)])

    def test_duckdb_local_csv_access_is_disabled(self):
        csv_path = self.folder / "population.csv"
        csv_path.write_text("city,population\nExample,42\n", encoding="utf-8")
        query = f"SELECT * FROM '{csv_path.as_posix()}';;"
        try:
            with self.connect("DUCKDB") as cursor:
                self.assertFalse(cursor.execute("SELECT current_setting('enable_external_access')").fetchone()[0])
                self.assertFalse(cursor.execute("SELECT current_setting('autoinstall_known_extensions')").fetchone()[0])
                self.assertFalse(cursor.execute("SELECT current_setting('autoload_known_extensions')").fetchone()[0])
                with self.assertRaises(duckdb.PermissionException):
                    cursor.get_description(query)
        finally:
            csv_path.unlink()

    def test_duckdb_query_timeout_interrupts_long_operation(self):
        with patch.dict(connection_duckdb.os.environ, {"DUCKDB_QUERY_TIMEOUT_SECONDS": "0.05"}, clear=False):
            with self.assertRaisesRegex(TimeoutError, "0.05-second time limit"):
                with self.connect("DUCKDB") as cursor:
                    cursor.execute("SELECT sum(i) FROM range(1000000000) AS values(i)")

    def test_duckdb_closes_when_begin_or_commit_fails(self):
        for failing_statement in ("BEGIN", "COMMIT"):
            with self.subTest(statement=failing_statement):
                native = MagicMock()

                def execute(query):
                    if query == failing_statement:
                        raise RuntimeError("transaction failure")

                native.execute.side_effect = execute
                with patch.object(connection_duckdb.duckdb, "connect", return_value=native):
                    with self.assertRaisesRegex(RuntimeError, "transaction failure"):
                        with self.connect("DUCKDB"):
                            pass
                native.close.assert_called_once()

    def test_duckdb_metadata_including_generated_columns_and_views(self):
        with self.connect("DUCKDB", 1) as cursor:
            cursor.execute('CREATE TABLE items (id INTEGER DEFAULT 1, "twice id" INTEGER GENERATED ALWAYS AS (id * 2))')
            cursor.execute("CREATE VIEW item_view AS SELECT * FROM items")
            self.assertEqual(
                cursor.get_table_columns("ITEMS"),
                [
                    ("id", "INTEGER", "1", 0),
                    ("twice id", "INTEGER", "CAST((id * 2) AS INTEGER)", 2),
                ],
            )
            self.assertEqual(cursor.check_if_table_exists("ITEM_VIEW"), ("view",))
            self.assertIsNone(cursor.check_if_table_exists("missing"))
            self.assertEqual(cursor.get_all_objects(), [("table", "items"), ("view", "item_view")])
            self.assertIn("CREATE TABLE items", cursor.get_object_ddl("ITEMS"))
            self.assertIn("CREATE VIEW item_view", cursor.get_object_ddl("item_view"))
            self.assertIsNone(cursor.get_object_ddl("missing"))

    def test_duckdb_description_does_not_execute_writes(self):
        with self.connect("DUCKDB", 1) as cursor:
            ddl = "CREATE TABLE items (id BIGINT)"
            description = cursor.get_description(ddl)
            self.assertIsNone(cursor.check_if_table_exists("items"))
            cursor.execute(ddl)
            query = "INSERT INTO items VALUES (7) RETURNING /* result */ id AS Count"
            description = cursor.get_description(query)
            self.assertEqual(cursor.conn.execute("SELECT count(*) FROM items").fetchone(), (0,))
            cursor.execute(query)
            self.assertEqual(description[0][:2], ("Count", "BIGINT"))
            self.assertEqual(cursor.fetchall(), [(7,)])
            self.assertEqual(cursor.rowcount(), 1)
            self.assertEqual(cursor.execute("SELECT * FROM items").fetchall(), [(7,)])

    def test_duckdb_counts_and_select_count_are_distinct(self):
        with self.connect("DUCKDB", 1) as cursor:
            cursor.execute("CREATE TABLE items (id BIGINT)")
            cursor.executemany("INSERT INTO items VALUES (?)", [(1,), (2,), (3,)])
            self.assertEqual(cursor.rowcount(), 3)
            query = "UPDATE items SET id = 4 WHERE id < 3"
            description = cursor.get_description(query)
            cursor.execute(query)
            self.assertEqual(description, [])
            self.assertEqual(cursor.rowcount(), 2)
            query = 'SELECT count(*) AS "Count" FROM items'
            description = cursor.get_description(query)
            cursor.execute(query)
            self.assertEqual(description[0][:2], ("Count", "BIGINT"))
            self.assertEqual(cursor.fetchmany(10), [(3,)])
            cursor.execute("DELETE FROM items WHERE id = 100")
            self.assertEqual(cursor.rowcount(), 0)

    def test_duckdb_explain_is_supported_by_description_then_execute(self):
        with self.connect("DUCKDB") as cursor:
            query = "EXPLAIN SELECT 1"
            description = cursor.get_description(query)
            cursor.execute(query)
            self.assertEqual([column[0] for column in description], ["explain_key", "explain_value"])
            self.assertTrue(cursor.fetchall())

    def test_duckdb_explain_analyze_uses_wrapped_statement_access(self):
        with self.connect("DUCKDB", 1) as cursor:
            cursor.execute("CREATE TABLE items (id INTEGER)")
            cursor.execute("INSERT INTO items VALUES (1)")

        cases = (
            ("EXPLAIN UPDATE items SET id = id + 1", True, 1),
            ("EXPLAIN (FORMAT JSON) UPDATE items SET id = id + 1", True, 1),
            ("EXPLAIN ANALYZE UPDATE items SET id = id + 1", True, 2),
            ("EXPLAIN (ANALYZE, FORMAT JSON) UPDATE items SET id = id + 1", True, 3),
            ("EXPLAIN (ANALYZE FALSE) UPDATE items SET id = id + 1", True, 4),
            ("EXPLAIN ANALYZE SELECT * FROM items", False, 4),
            ("EXPLAIN SELECT * FROM items", False, 4),
        )
        for query, expected_access, expected_id in cases:
            with self.subTest(query=query):
                access = connection.query_requires_write_access(query, "DUCKDB")
                self.assertEqual(access, expected_access)
                with self.connect("DUCKDB", int(access)) as cursor:
                    description = cursor.get_description(query)
                    cursor.execute(query)
                    self.assertEqual([column[0] for column in description], ["explain_key", "explain_value"])
                    self.assertTrue(cursor.fetchall())
                with self.connect("DUCKDB") as cursor:
                    self.assertEqual(cursor.execute("SELECT id FROM items").fetchall(), [(expected_id,)])

    def test_scripts_and_statement_restrictions(self):
        for engine in ("SQLITE", "DUCKDB"):
            with self.subTest(engine=engine):
                with self.connect(engine, 1) as cursor:
                    cursor.execute("CREATE TABLE items (id INTEGER)")
                    cursor.executescript("INSERT INTO items VALUES (?); INSERT INTO items VALUES (?)", (1, 2))
                    self.assertEqual(cursor.execute("SELECT * FROM items ORDER BY id").fetchall(), [(1,), (2,)])
                    with self.assertRaises((ValueError, apsw.AuthError)):
                        cursor.execute("ATTACH ':memory:' AS other")
                    with self.assertRaises(ValueError):
                        cursor.execute("SELECT 1; SELECT 2")

    def test_missing_files_and_invalid_engine_fail_without_creating_files(self):
        missing = str(self.folder / "missing.db")
        for engine in ("SQLITE", "DUCKDB"):
            with self.assertRaises(FileNotFoundError):
                with connection.sql_connection("model", missing, db_type=engine, db_access=1):
                    pass
        self.assertFalse(Path(missing).exists())
        with self.assertRaises(ValueError):
            connection.sql_connection("model", missing, db_type="unknown")

    def test_query_write_access_detection(self):
        cases = (
            ("SELECT 1", "DUCKDB", False),
            ("-- UPDATE\nSELECT 'DELETE'", "DUCKDB", False),
            ("WITH x AS (SELECT 1) UPDATE items SET id = 1", "DUCKDB", True),
            ("WITH x AS (SELECT 1) INSERT INTO items SELECT * FROM x", "DUCKDB", True),
            ("COPY items TO 'out.csv'", "DUCKDB", False),
            ("COPY items FROM 'in.csv'", "DUCKDB", True),
            ("VACUUM", "DUCKDB", True),
            ("EXPLAIN INSERT INTO items VALUES (1)", "DUCKDB", True),
            ("EXPLAIN ANALYZE UPDATE items SET id = 1", "DUCKDB", True),
            ("EXPLAIN ANALYZE INSERT INTO items VALUES (1)", "DUCKDB", True),
            ("EXPLAIN ANALYZE DELETE FROM items", "DUCKDB", True),
            ("EXPLAIN ANALYZE WITH x AS (SELECT 1) UPDATE items SET id = 1", "DUCKDB", True),
            ("/* \u00e9 */ EXPLAIN /* comment */ ANALYZE -- comment\nUPDATE items SET id = 1", "DUCKDB", True),
            ("EXPLAIN (FORMAT JSON, ANALYZE) UPDATE items SET id = 1", "DUCKDB", True),
            ("EXPLAIN (FORMAT JSON) UPDATE items SET id = 1", "DUCKDB", True),
            ("EXPLAIN ANALYZE SELECT 'UPDATE'", "DUCKDB", False),
            ("EXPLAIN SELECT 'ANALYZE UPDATE'", "DUCKDB", False),
            ("/* DROP */ SELECT 1", "SQLITE", False),
            ("-- DELETE\nUPDATE items SET id = 1", "SQLITE", True),
            ("WITH x AS (SELECT 1) DELETE FROM items", "SQLITE", True),
        )
        for query, db_type, expected in cases:
            with self.subTest(query=query, db_type=db_type):
                self.assertEqual(connection.query_requires_write_access(query, db_type), expected)


if __name__ == "__main__":
    unittest.main()
