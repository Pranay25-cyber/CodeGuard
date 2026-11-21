
from pydantic import BaseModel, Field, ConfigDict


# Data received from the frontend
class RepositoryCreate(BaseModel):
    github_repo_id: int
    name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    html_url: str = Field(min_length=1, max_length=500)


# Data returned by the backend
class RepositoryResponse(BaseModel):
    id: int
    github_repo_id: int
    name: str
    full_name: str
    html_url: str

    model_config = ConfigDict(from_attributes=True)
