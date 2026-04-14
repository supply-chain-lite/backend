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


class DistinctColumnValuesResponse(BaseModel):
    values: list[str | int | float | bool | None]


class RowCountRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    select_filters: dict[str, list[str | int | float | bool | None]] = Field(default_factory=dict)
    text_filters: dict[str, str] = Field(default_factory=dict)


class RowCountResponse(BaseModel):
    row_count: int


class SetColumnFormattingRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_name: str
    column_type: str
    format: dict[str, str | int | float | bool | None]


class GetColumnFormattingResponse(BaseModel):
    column_formatting: dict[str, dict[str, str | int | float | bool | None]]
