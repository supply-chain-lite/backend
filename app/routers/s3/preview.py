from os.path import splitext

import duckdb
from fastapi import HTTPException

from app.serialization import serialize_database_cell

_PREVIEW_LIMIT = 500
_PREVIEW_READERS = {
    ".csv": "read_csv_auto",
    ".txt": "read_csv_auto",
    ".json": "read_json_auto",
    ".parquet": "read_parquet",
    ".xlsx": "read_xlsx",
}


def preview_reader(key: str) -> str:
    reader = _PREVIEW_READERS.get(splitext(key)[1].lower())
    if reader is None:
        raise HTTPException(status_code=415, detail="Preview supports only csv, txt, json, parquet, and xlsx files")
    return reader


def read_preview(connection, reader: str, object_url: str) -> dict:
    if reader == "read_xlsx":
        try:
            connection.execute("LOAD excel")
        except duckdb.Error as exc:
            raise HTTPException(status_code=502, detail="DuckDB could not load the Excel reader") from exc
    result = connection.execute(f"SELECT * FROM {reader}(?) LIMIT {_PREVIEW_LIMIT + 1}", [object_url])
    rows = result.fetchall()
    columns = [column[0] for column in result.description]
    return {
        "columns": columns,
        "rows": [
            {column: serialize_database_cell(value) for column, value in zip(columns, row)}
            for row in rows[:_PREVIEW_LIMIT]
        ],
        "truncated": len(rows) > _PREVIEW_LIMIT,
    }
