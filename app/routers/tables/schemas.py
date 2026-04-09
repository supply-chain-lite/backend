from pydantic import BaseModel


class TableHeaderRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str


class TableHeaderResponse(BaseModel):
    headers: list[tuple[str, str]]


class TableDataRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    page_number: int
    page_size: int
    column_names: list[str]
    select_filters: dict[str, list[str]]
    text_filters: dict[str, str]


class TableDataResponse(BaseModel):
    data: list[tuple[str | int | float | bool | None, ...]]


class DistinctColumnValuesRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    column_name: str
    page_size: int
    select_filters: dict[str, list[str]]
    text_filters: dict[str, str]


class DistinctColumnValuesResponse(BaseModel):
    values: list[str | int | float | bool | None]


class RowCountRequest(BaseModel):
    model_name: str
    project_name: str
    table_name: str
    select_filters: dict[str, list[str]]
    text_filters: dict[str, str]


class RowCountResponse(BaseModel):
    row_count: int
