from pydantic import BaseModel, Field


class TableHeaderRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str


class TableHeaderResponse(BaseModel):
    headers: list[tuple[str, str]]


class TableAllHeadersResponse(BaseModel):
    headers: list[str]


class AddColumnRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_name: str
    column_type: str


class SetColumnOrderRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_names: list[str]


class MessageResponse(BaseModel):
    message: str


class TableDataRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    page_number: int
    page_size: int
    column_names: list[str]
    sort_columns: list[list[str, str]]
    select_filters: dict[str, list[str | int | float | bool | None]]
    text_filters: dict[str, str]
    date_columns: list[str]
    numeric_filters: list[tuple[str, str, str | int | float]]


class TableDataResponse(BaseModel):
    data: list[tuple[str | int | float | bool | None, ...]]


class DistinctColumnValuesRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_name: str
    page_size: int
    select_filters: dict[str, list[str | int | float | bool | None]]
    text_filters: dict[str, str]
    date_columns: list[str]
    numeric_filters: list[tuple[str, str, str | int | float]]


class DistinctColumnValuesResponse(BaseModel):
    values: list[str | int | float | bool | None]


class RowCountRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    select_filters: dict[str, list[str | int | float | bool | None]] = Field(default_factory=dict)
    text_filters: dict[str, str] = Field(default_factory=dict)
    date_columns: list[str]
    numeric_filters: list[tuple[str, str, str | int | float]]


class RowCountResponse(BaseModel):
    row_count: int


class SetColumnFormattingRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_name: str
    column_type: str
    format: dict[str, str | int | float | bool | None | list | dict]


class GetColumnFormattingResponse(BaseModel):
    column_formatting: dict[str, dict[str, str | int | float | bool | None | list | dict]]


class updateRowRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    row_id: int
    updates: dict[str, str | int | float | bool | None]


class updateRowValuesRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_name: str
    column_value: str | int | float | bool | None
    select_filters: dict[str, list[str | int | float | bool | None]]
    text_filters: dict[str, str]
    date_columns: list[str]
    numeric_filters: list[tuple[str, str, str | int | float]]
    row_ids: list[int]


class updateRowValuesResponse(BaseModel):
    rows_updated: int


class DeleteRowsRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    row_ids: list[int]
    select_filters: dict[str, list[str | int | float | bool | None]]
    text_filters: dict[str, str]
    date_columns: list[str]
    numeric_filters: list[tuple[str, str, str | int | float]]


class DeleteRowsResponse(BaseModel):
    rows_deleted: int


class getSummaryStatsRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_names: dict[str, str]
    select_filters: dict[str, list[str | int | float | bool | None]]
    text_filters: dict[str, str]
    date_columns: list[str]
    numeric_filters: list[tuple[str, str, str | int | float]]


class getSummaryStatsResponse(BaseModel):
    summary: dict[str, str | float | int | None]


class AddRowRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    values: dict[str, str | int | float | bool | None]


class ExportTablesToExcelRequest(BaseModel):
    model_name: str
    project_name: str
    table_names: list[str]


class UploadExcelToTableResponse(BaseModel):
    response: dict[str, dict[str, str | int | float | bool | None]]


class checkExcelSheetRequest(BaseModel):
    model_name: str
    project_name: str
    sheet_names: list[str]


class checkExcelSheetResponse(BaseModel):
    sheet_types: dict[str, str]
