"""Run with python -m unittest discover -s tests -v; uses only temporary databases."""

import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import duckdb


def setUpModule():
    global root, api
    root = Path(__file__).resolve().parents[1] / (".connection-tests-" + uuid4().hex)
    root.mkdir()
    master = root / "master.db"
    conn = sqlite3.connect(master)
    conn.execute("CREATE TABLE marker (value INTEGER)")
    conn.close()
    with patch.dict(
        os.environ,
        {"SECRET_KEY": "connection-tests", "SQLITE_DB_PATH": str(master), "DATA_FOLDER": str(root)},
    ):
        from app import connection
    api = connection


def tearDownModule():
    api.close_all_conn()
    shutil.rmtree(root)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.files = root / uuid4().hex
        self.files.mkdir()
        self.addCleanup(shutil.rmtree, self.files)
        self.addCleanup(api.close_all_conn)
        self.path = self.files / "model.db"
        conn = duckdb.connect(str(self.path))
        conn.execute("CREATE TABLE marker (value INTEGER)")
        conn.close()

    def assert_closed(self, transaction):
        for handle in (transaction.cursor, transaction.connection):
            with self.assertRaises(duckdb.ConnectionException):
                handle.execute("SELECT 1")

    def test_fresh_connections_commit_and_release_file_to_another_process(self):
        first = api.sql_connection("model", self.path)
        with first as cursor:
            cursor.execute("INSERT INTO marker VALUES (1)")
        self.assert_closed(first)
        second = api.sql_connection("model", self.path)
        with second as cursor:
            self.assertIsNot(first.connection, second.connection)
            self.assertEqual(cursor.execute("SELECT * FROM marker").fetchall(), [(1,)])
        self.assert_closed(second)
        self.assertNotIn(os.path.abspath(self.path), api.connection_pool)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import duckdb,sys; c=duckdb.connect(sys.argv[1]); "
                "assert c.execute('SELECT * FROM marker').fetchall()==[(1,)]; c.close()",
                str(self.path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rollback_discards_changes_and_closes_connection(self):
        transaction = api.sql_connection("model", self.path)
        with patch.object(api, "logger"), self.assertRaisesRegex(ValueError, "cancel"):
            with transaction as cursor:
                cursor.execute("INSERT INTO marker VALUES (2)")
                raise ValueError("cancel")
        self.assert_closed(transaction)
        with api.sql_connection("model", self.path) as cursor:
            self.assertEqual(cursor.execute("SELECT * FROM marker").fetchall(), [])

    def test_read_only_transaction_can_be_followed_by_write(self):
        with api.sql_connection("model", self.path, db_access=0) as cursor:
            self.assertEqual(cursor.execute("SELECT * FROM marker").fetchall(), [])
        with api.sql_connection("model", self.path) as cursor:
            cursor.execute("INSERT INTO marker VALUES (3)")

    def test_connection_opens_only_when_entering_transaction(self):
        with patch.object(api, "get_cursor", wraps=api.get_cursor) as get_cursor:
            transaction = api.sql_connection("model", self.path)
            get_cursor.assert_not_called()
            with transaction:
                self.assertEqual(get_cursor.call_count, 1)
            self.assert_closed(transaction)

    def test_transaction_failures_close_both_handles(self):
        for failing_statement in ("BEGIN", "COMMIT", "ROLLBACK"):
            with self.subTest(statement=failing_statement):
                get_cursor = api.connection_duckdb.get_cursor
                handles = []

                def failing_cursor(connection):
                    real_cursor = get_cursor(connection)
                    handles.extend((connection, real_cursor))
                    proxy = Mock(wraps=real_cursor)

                    def execute(statement, *args):
                        if statement == failing_statement:
                            raise RuntimeError("injected failure")
                        return real_cursor.execute(statement, *args)

                    proxy.execute.side_effect = execute
                    return proxy

                with patch.object(api.connection_duckdb, "get_cursor", side_effect=failing_cursor):
                    with patch.object(api, "logger"), self.assertRaises(RuntimeError):
                        with api.sql_connection("model", self.path):
                            if failing_statement == "ROLLBACK":
                                raise RuntimeError("cancel")
                for handle in handles:
                    with self.assertRaises(duckdb.ConnectionException):
                        handle.execute("SELECT 1")

    def test_cursor_creation_failure_closes_parent(self):
        handles = []

        def fail(connection):
            handles.append(connection)
            raise RuntimeError("cursor creation failed")

        with patch.object(api.connection_duckdb, "get_cursor", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "cursor creation failed"):
                with api.sql_connection("model", self.path):
                    self.fail("Transaction must not start")
        with self.assertRaises(duckdb.ConnectionException):
            handles[0].execute("SELECT 1")

    def test_sqlite_still_reuses_connection_and_rolls_back(self):
        path = self.files / "sqlite.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE marker (value INTEGER)")
        conn.close()
        first = api.sql_connection("sqlite", path)
        with first as cursor:
            cursor.execute("INSERT INTO marker VALUES (1)")
        second = api.sql_connection("sqlite", path)
        with patch.object(api, "logger"), self.assertRaises(ValueError):
            with second as cursor:
                self.assertIs(first.connection, second.connection)
                cursor.execute("INSERT INTO marker VALUES (2)")
                raise ValueError("cancel")
        with api.sql_connection("sqlite", path) as cursor:
            self.assertEqual(cursor.execute("SELECT * FROM marker").fetchall(), [(1,)])
