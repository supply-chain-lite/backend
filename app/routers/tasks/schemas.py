from pydantic import BaseModel


class TaskBaseModel(BaseModel):
    model_name: str
    project_name: str


class ListTasksRequest(TaskBaseModel):
    pass


class TaskParams(BaseModel):
    ParameterName: str
    ParameterValue: str | int | float | bool | None | list
    ParameterType: str
    ParameterValues: list | None


class TaskDetails(BaseModel):
    task_id: int
    task_name: str
    task_params: list[TaskParams]


class ListTasksResponse(BaseModel):
    tasks: list[TaskDetails]


class TaskParamValues(BaseModel):
    ParameterName: str
    ParameterValue: str | int | float | bool | None | list


class runTaskRequest(TaskBaseModel):
    task_id: int
    task_params: list[TaskParamValues]


class MessageResponse(BaseModel):
    message: str
