from pydantic import BaseModel, Field


class UserModel(BaseModel):
    ModelId: int
    AccessLevel: str


class UserDetail(BaseModel):
    UserEmail: str = Field(..., min_length=1)
    DisplayName: str = Field(..., min_length=1)
    IsActive: int = Field(..., ge=0, le=1)
    Templates: list[str] = Field(default_factory=list)
    RoleName: str = Field(..., min_length=1)
    EndDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    MaxConcurrentRuns: int = Field(..., gt=0)
    CreatedAt: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    userModels: list[UserModel] = Field(default_factory=list)


class UserDetailResponse(BaseModel):
    userDetails: list[UserDetail]


class GetUserModelsRequest(BaseModel):
    UserEmail: str = Field(..., min_length=1)


class TemplateResponse(BaseModel):
    templates: list[str]


class ModulesResponse(BaseModel):
    modules: list[str]
    HomePages: list[str]


class RoleDetail(BaseModel):
    RoleId: int = Field(..., gt=0)
    RoleName: str = Field(..., min_length=1)
    RoleDescription: str = Field(..., min_length=1)
    Modules: list[str] = Field(default_factory=list)
    HomePage: str = Field(..., min_length=1)
    CanAddNewModel: int = Field(..., ge=0, le=1)
    CreatedAt: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class RoleResponse(BaseModel):
    roles: list[RoleDetail]


class AddNewUserRequest(BaseModel):
    UserEmail: str = Field(..., min_length=1)
    DisplayName: str = Field(..., min_length=1)
    Templates: list[str] = Field(default_factory=list)
    RoleName: str = Field(..., min_length=1)
    EndDate: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    MaxConcurrentRuns: int = Field(..., gt=0)
    userModels: list[UserModel] | None = None


class MessageResponse(BaseModel):
    message: str = Field(..., min_length=1)


class AddNewRoleRequest(BaseModel):
    RoleName: str = Field(..., min_length=1)
    RoleDescription: str = Field(..., min_length=1)
    Modules: list[str] = Field(default_factory=list)
    HomePage: str = Field(..., min_length=1)
    CanAddNewModel: int = Field(..., ge=0, le=1)


class UpdateUserRequest(BaseModel):
    UserEmail: str = Field(..., min_length=1)
    DisplayName: str | None = Field(None, min_length=1)
    IsActive: int | None = Field(None, ge=0, le=1)
    Templates: list[str] = Field(default_factory=list)
    RoleName: str | None = Field(None, min_length=1)
    EndDate: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    MaxConcurrentRuns: int | None = Field(None, gt=0)
    userModels: list[UserModel] | None = None


class UpdateRoleRequest(BaseModel):
    RoleId: int = Field(..., gt=0)
    RoleName: str | None = Field(None, min_length=1)
    RoleDescription: str | None = Field(None, min_length=1)
    Modules: list[str] = Field(default_factory=list)
    HomePage: str | None = Field(None, min_length=1)
    CanAddNewModel: int | None = Field(None, ge=0, le=1)
