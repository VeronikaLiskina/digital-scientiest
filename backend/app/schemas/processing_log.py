from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProcessingLogBase(BaseModel):
    source_file_id: int
    step_name: str
    status: str
    error_message: str | None = None


class ProcessingLogCreate(ProcessingLogBase):
    pass


class ProcessingLogUpdate(BaseModel):
    step_name: str | None = None
    status: str | None = None
    error_message: str | None = None


class ProcessingLogRead(ProcessingLogBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)