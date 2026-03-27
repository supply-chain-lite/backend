from pydantic import BaseModel


class ProjectCreateRequest(BaseModel):
    name: str
    create_and_open: bool = True


class CurrentProjectResponse(BaseModel):
    project_name: str


class OpenProjectRequest(BaseModel):
    project_name: str


class MessageResponse(BaseModel):
    message: str


class RenameProjectRequest(BaseModel):
    old_project_name: str
    new_project_name: str
