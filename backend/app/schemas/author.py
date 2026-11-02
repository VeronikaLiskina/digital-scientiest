from pydantic import BaseModel, ConfigDict, computed_field

from app.services.publication_author_policy import is_required_author


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

    @computed_field
    @property
    def is_required(self) -> bool:
        return is_required_author(self.full_name)
