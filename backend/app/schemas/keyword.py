from pydantic import BaseModel, ConfigDict


class KeywordBase(BaseModel):
    name: str


class KeywordCreate(KeywordBase):
    pass


class KeywordUpdate(BaseModel):
    name: str | None = None


class KeywordRead(KeywordBase):
    id: int

    model_config = ConfigDict(from_attributes=True)