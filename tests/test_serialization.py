"""Verify DuckDB composite cells fit the table API without exposing BLOBs."""

import datetime
import json
import unittest
from decimal import Decimal

import duckdb

from app.routers.tables.schemas import TableDataResponse
from app.serialization import serialize_database_cell


class DatabaseSerializationTests(unittest.TestCase):
    def test_duckdb_nested_results_fit_table_response(self):
        with duckdb.connect(":memory:") as connection:
            row = connection.execute(
                """SELECT [1, 2, NULL],
                          {'name': 'example', 'payload': [from_hex('FF00')]},
                          row(42, 'value'),
                          map([1, 2], ['a', 'b'])"""
            ).fetchone()
        data = [tuple(serialize_database_cell(value) for value in row)]
        response = json.loads(TableDataResponse(data=data).model_dump_json())
        self.assertEqual(
            [json.loads(cell) for cell in response["data"][0]],
            [[1, 2, None], {"name": "example", "payload": ["<BLOB_DATA>"]}, [42, "value"], {"1": "a", "2": "b"}],
        )

    def test_nested_binary_and_dates_are_serialized_without_mutation(self):
        value = {
            "nested": (bytearray(b"secret"), memoryview(b"secret")),
            "date": datetime.date(2026, 9, 14),
            "datetime": datetime.datetime(2026, 9, 14, 15, 30, 45),
        }
        result = json.loads(serialize_database_cell(value))
        self.assertEqual(
            result,
            {
                "nested": ["<BLOB_DATA>", "<BLOB_DATA>"],
                "date": "2026-09-14",
                "datetime": "2026-09-14 15:30:45",
            },
        )
        self.assertIsInstance(value["nested"], tuple)
        self.assertEqual(value["nested"][0], bytearray(b"secret"))
        self.assertEqual(json.loads(serialize_database_cell([Decimal("1.23")])), ["1.23"])

    def test_duckdb_dates_and_timestamps_use_display_format(self):
        with duckdb.connect(":memory:") as connection:
            row = connection.execute(
                """SELECT DATE '2026-09-14', TIMESTAMP '2024-02-09 15:30:45',
                          [TIMESTAMP '2005-01-02 23:59:59']"""
            ).fetchone()
        data = [tuple(serialize_database_cell(value) for value in row)]
        response = json.loads(TableDataResponse(data=data).model_dump_json())
        self.assertEqual(response["data"][0][:2], ["2026-09-14", "2024-02-09 15:30:45"])
        self.assertEqual(json.loads(response["data"][0][2]), ["2005-01-02 23:59:59"])

    def test_scalar_cells_and_empty_composites(self):
        for value in (None, True, 42, 1.25, "text"):
            self.assertIs(serialize_database_cell(value), value)
        for value in (b"secret", bytearray(b"secret"), memoryview(b"secret")):
            self.assertEqual(serialize_database_cell(value), "<BLOB_DATA>")
        for value in ([], (), {}):
            self.assertEqual(json.loads(serialize_database_cell(value)), {} if isinstance(value, dict) else [])


if __name__ == "__main__":
    unittest.main()
