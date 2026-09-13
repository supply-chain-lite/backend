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
            ("EXPLAIN INSERT INTO items VALUES (1)", "DUCKDB", False),
            ("/* DROP */ SELECT 1", "SQLITE", False),
            ("-- DELETE\nUPDATE items SET id = 1", "SQLITE", True),
            ("WITH x AS (SELECT 1) DELETE FROM items", "SQLITE", True),
        )
        for query, db_type, expected in cases:
            with self.subTest(query=query, db_type=db_type):
                self.assertEqual(connection.query_requires_write_access(query, db_type), expected)


if __name__ == "__main__":
    unittest.main()
