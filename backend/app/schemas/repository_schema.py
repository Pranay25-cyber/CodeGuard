
from pydantic import BaseModel, Field, ConfigDict


class RepositoryCreate(BaseModel):
    github_repo_id: int
    name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    html_url: str = Field(min_length=1, max_length=500)


class RepositoryResponse(BaseModel):
    id: int
    github_repo_id: int
    name: str
    full_name: str
    html_url: str

    model_config = ConfigDict(from_attributes=True)
