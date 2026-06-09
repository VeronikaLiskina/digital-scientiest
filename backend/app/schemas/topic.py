from pydantic import BaseModel, ConfigDict


class TopicBase(BaseModel):
    name: str
    description: str | None = None


class TopicCreate(TopicBase):
    pass


class TopicUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class TopicRead(TopicBase):
    id: int

    model_config = ConfigDict(from_attributes=True)