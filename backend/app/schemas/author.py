from pydantic import BaseModel, ConfigDict


class AuthorBase(BaseModel):
    full_name: str
    organization: str | None = None


class AuthorCreate(AuthorBase):
    pass


class AuthorUpdate(BaseModel):
    full_name: str | None = None
    organization: str | None = None


class AuthorRead(AuthorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)