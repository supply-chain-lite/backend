from pydantic import BaseModel


class ModelCreateRequest(BaseModel):
    name: str
    description: str | None = None


class ModelCreateResponse(BaseModel):
    id: int
    name: str
    message: str = "Model created successfully"


class ModelListResponse(BaseModel):
    project_models: dict[str, dict[str, str]]


class ModelTemplatesResponse(BaseModel):
    model_templates: list[str]


class MessageResponse(BaseModel):
    message: str


class createModelRequest(BaseModel):
    model_template: str
    model_name: str
    project_name: str
    with_sample_data: bool = False
