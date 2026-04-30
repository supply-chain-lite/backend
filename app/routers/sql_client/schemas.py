from pydantic import BaseModel


class SQLObjectRequest(BaseModel):
    model_name: str
    project_name: str


class SQLObjectResponse(BaseModel):
    tables: list[str]
    views: list[str]


class SQLQueryRequest(SQLObjectRequest):
    sql: str


class SQLQueryResponse(BaseModel):
    type: str
    columns: list[str] | None = None
    rows: list[tuple] | None = None
    changes: int | None = None


class SQLObjectDDLRequest(SQLObjectRequest):
    object_name: str


class SQLObjectDDLResponse(BaseModel):
    ddl: str


class SQLHistoryRequest(SQLObjectRequest):
    pass


class SQLHistoryResponse(BaseModel):
    history: list[dict[str, str | int | bool | None]]


class SQLHistoryAddRequest(SQLObjectRequest):
    sql: str
    is_error: bool
    status: str


class SQLHistoryAddResponse(BaseModel):
    message: str
