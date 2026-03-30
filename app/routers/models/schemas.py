from enum import Enum

from pydantic import BaseModel


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


class saveAsModelRequest(BaseModel):
    model_name: str
    project_name: str
    new_model_name: str


class addExistingModelRequest(BaseModel):
    model_project_pairs: list[tuple[str, str]]
    project_name: str


class renameModelRequest(BaseModel):
    model_name: str
    project_name: str
    new_model_name: str


class modelRequest(BaseModel):
    model_name: str
    project_name: str


class moveModelRequest(BaseModel):
    model_name: str
    project_name: str
    new_project_name: str


class backupModelRequest(BaseModel):
    model_name: str
    project_name: str
    backup_comment: str


class getBackupsResponse(BaseModel):
    model_backups: list[tuple[int, str, str]]


class restoreModelRequest(BaseModel):
    model_name: str
    project_name: str
    backup_id: int


class accessLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class shareModelRequest(BaseModel):
    model_name: str
    project_name: str
    target_user_email: str
    access_level: accessLevel


class notificationBaseModel(BaseModel):
    notification_id: int
    from_user_email: str
    title: str
    message: str
    notification_type: str
    project_name: str | None
    model_name: str | None
    is_read: int
    is_accepted: int


class getNotificationsResponse(BaseModel):
    notifications: list[notificationBaseModel]


class acceptModelRequest(BaseModel):
    notification_id: int
    accept: bool
    model_name: str
    project_name: str
    create_new_copy: bool
