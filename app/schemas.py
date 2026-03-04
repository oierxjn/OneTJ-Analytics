from typing import Literal

from pydantic import BaseModel, field_validator


class EventIn(BaseModel):
    userid: str
    username: str
    client_version: str
    device_brand: str
    device_model: str
    dept_name: str
    school_name: str
    gender: str
    platform: str

    @field_validator("*", mode="before")
    @classmethod
    def ensure_string(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value.strip()

    @field_validator("*", mode="after")
    @classmethod
    def ensure_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value


class ApiResponse(BaseModel):
    status: Literal["ok", "error"]
    code: str
    message: str
    request_id: str

