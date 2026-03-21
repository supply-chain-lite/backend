from pydantic import BaseModel


class ModelCreateRequest(BaseModel):
    name: str
    description: str | None = None


class ModelCreateResponse(BaseModel):
    id: int
    name: str
    message: str = "Model created successfully"
