from pydantic import BaseModel


class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None


class ProjectCreateResponse(BaseModel):
    id: int
    name: str
    message: str = "Project created successfully"
