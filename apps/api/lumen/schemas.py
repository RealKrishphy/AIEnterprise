import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

Password = Annotated[str, StringConstraints(min_length=12, max_length=256)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    display_name: str = Field(min_length=1, max_length=160)
    tenant_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    tenant_id: uuid.UUID
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str


class QueryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    history: list[QueryTurn] = Field(default_factory=list, max_length=20)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query must not be blank")
        return value


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    status: str
    created_at: str
