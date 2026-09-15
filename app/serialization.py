"""Convert database cells for display in scalar-valued API responses."""

import json
import math
from datetime import date, datetime

_BLOB_TYPES = (bytes, bytearray, memoryview)
_BLOB_PLACEHOLDER = "<BLOB_DATA>"


def _nested_json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, _BLOB_TYPES):
        return _BLOB_PLACEHOLDER
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    if isinstance(value, (list, tuple)):
        return [_nested_json_value(item) for item in value]
    if isinstance(value, dict):
        # DuckDB MAP keys can themselves be non-string values. JSON object
        # keys must be strings; mask binary keys just like binary values.
        normalized_items = []
        for key, item in value.items():
            normalized_key = key if isinstance(key, str) else str(_nested_json_value(key))
            normalized_items.append((normalized_key, _nested_json_value(item)))

        unique_keys = {normalized_key for normalized_key, _ in normalized_items}
        if len(unique_keys) == len(normalized_items):
            return {normalized_key: item for normalized_key, item in normalized_items}
        return [[normalized_key, item] for normalized_key, item in normalized_items]
    return value


def serialize_database_cell(value):
    """Mask binary cells and encode composite cells as JSON text.

    Dates and datetimes use ISO-like display values: date as YYYY-MM-DD and
    timestamps as YYYY-MM-DD HH:MM:SS. Decimals and other non-JSON scalars
    inside composites use their string representation. Other scalar cells are
    returned unchanged.
    """
    if isinstance(value, _BLOB_TYPES):
        return _BLOB_PLACEHOLDER
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(_nested_json_value(value), ensure_ascii=False, default=str, allow_nan=False)
    return _nested_json_value(value)
