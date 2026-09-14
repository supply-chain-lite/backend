"""Exercise generated date-filter SQL against both database engines in memory."""

import datetime
import unittest

import apsw
import duckdb

from app.routers.tables import queries


class TableDateFilterTests(unittest.TestCase):
    def setUp(self):
        self.databases = {"SQLITE": apsw.Connection(":memory:"), "DUCKDB": duckdb.connect(":memory:")}
        epoch = datetime.date(1899, 12, 30)
        leap_day = (datetime.date(2024, 2, 29) - epoch).days
        rows = [
            (1, leap_day, "alpha", "keep", 10),
            (2, leap_day + 0.75, "beta", "keep", 20),
            (3, leap_day + 1, "gamma", "keep", 30),
            (4, None, "null_date", "keep", 40),
            (5, -0.25, "negative", "keep", 50),
            (6, 0.75, "epoch", "keep", 60),
            (7, leap_day + 0.5, "other", "skip", 70),
        ]
        for database in self.databases.values():
            database.execute(
                "CREATE TABLE events (id INTEGER, serial DOUBLE, label VARCHAR, category VARCHAR, amount INTEGER)"
            )
            database.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?)", rows)

    def tearDown(self):
        for database in self.databases.values():
            database.close()

    def test_date_boundaries_and_partial_matches(self):
        for engine, database in self.databases.items():
            for date_text, expected in (
                ("2024-02-29", [(1,), (2,), (7,)]),
                ("2024-03", [(3,)]),
                ("2024", [(1,), (2,), (3,), (7,)]),
                ("1899-12-29", [(5,)]),
                ("1899-12-30", [(6,)]),
                ("2030", []),
            ):
                with self.subTest(engine=engine, date_text=date_text):
                    query, parameters = queries.get_table_query(
                        "events",
                        ["id"],
                        {},
                        {"serial": date_text},
                        ["serial"],
                        [],
                        [["id", "ASC"]],
                        1,
                        100,
                        db_type=engine.lower(),
                    )
                    self.assertEqual(database.execute(query, parameters).fetchall(), expected)

    def test_combined_filters_count_distinct_summary_and_pagination(self):
        for engine, database in self.databases.items():
            with self.subTest(engine=engine):
                filters = dict(
                    select_filters={"category": ["keep", None]},
                    text_filters={"serial": "2024-02", "label": "a"},
                    date_columns=["serial"],
                    numeric_filters=[("amount", "gte", 10)],
                    db_type=engine,
                )
                query, parameters = queries.get_row_count_query("events", **filters)
                self.assertEqual(database.execute(query, parameters).fetchone(), (2,))
                query, parameters = queries.get_distinct_column_values_query(
                    "events", "label", page_size=100, **filters
                )
                self.assertEqual(database.execute(query, parameters).fetchall(), [("alpha",), ("beta",)])
                query, parameters = queries.get_summary_stats_query("events", {"amount": "SUM"}, **filters)
                self.assertEqual(database.execute(query, parameters).fetchone(), (30,))
                query, parameters = queries.get_table_query(
                    "events", ["id"], sort_columns=[["id", "ASC"]], page_number=2, page_size=1, **filters
                )
                self.assertEqual(database.execute(query, parameters).fetchall(), [(2,)])

    def test_updates_and_deletes_only_affect_matching_dates_and_rowids(self):
        for engine, database in self.databases.items():
            with self.subTest(engine=engine):
                row_id = database.execute("SELECT rowid FROM events WHERE id = 2").fetchone()[0]
                query, parameters = queries.update_rows(
                    "events",
                    [row_id],
                    "label",
                    "changed",
                    {"category": ["keep"]},
                    {"serial": "2024-02-29"},
                    ["serial"],
                    [("amount", "gte", 10)],
                    db_type=engine,
                )
                database.execute(query, parameters)
                self.assertEqual(database.execute("SELECT id FROM events WHERE label = 'changed'").fetchall(), [(2,)])
                query, parameters = queries.delete_rows(
                    "events",
                    [],
                    {"category": ["keep"]},
                    {"serial": "2024-02-29"},
                    ["serial"],
                    [("amount", "gte", 10)],
                    db_type=engine,
                )
                database.execute(query, parameters)
                self.assertEqual(
                    database.execute("SELECT id FROM events ORDER BY id").fetchall(), [(3,), (4,), (5,), (6,), (7,)]
                )

    def test_empty_date_filter_and_bound_search_text(self):
        for engine, database in self.databases.items():
            with self.subTest(engine=engine):
                query, parameters = queries.get_row_count_query(
                    "events", {}, {"serial": ""}, ["serial"], [], db_type=engine
                )
                self.assertEqual(database.execute(query, parameters).fetchone(), (7,))
                search = "2024' OR 1=1 --"
                query, parameters = queries.get_row_count_query(
                    "events", {}, {"serial": search}, ["serial"], [], db_type=engine
                )
                self.assertNotIn(search, query)
                self.assertEqual(database.execute(query, parameters).fetchone(), (0,))

    def test_quoted_date_identifier(self):
        for engine, database in self.databases.items():
            with self.subTest(engine=engine):
                database.execute('CREATE TABLE unusual ("serial"" date" DOUBLE)')
                database.execute("INSERT INTO unusual VALUES (0.75), (1), (NULL)")
                query, parameters = queries.get_row_count_query(
                    "unusual",
                    {},
                    {'serial" date': "1899-12-30"},
                    ['serial" date'],
                    [],
                    db_type=engine,
                )
                self.assertEqual(database.execute(query, parameters).fetchone(), (1,))

    def test_legacy_default_preserves_sqlite_expression(self):
        query, parameters = queries.get_row_count_query("events", {}, {"serial": "2024-02-29"}, ["serial"], [])
        self.assertIn("DATE(\"serial\" + julianday('1899-12-30'))", query)
        self.assertEqual(self.databases["SQLITE"].execute(query, parameters).fetchone(), (3,))


if __name__ == "__main__":
    unittest.main()
