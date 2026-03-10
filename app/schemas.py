from typing import ClassVar, Literal

from pydantic import BaseModel, field_validator


class EventIn(BaseModel):
    hashId: str
    userid: str | None = None
    username: str | None = None
    client_version: str | None = None
    device_brand: str | None = None
    device_model: str | None = None
    dept_name: str | None = None
    school_name: str | None = None
    gender: str | None = None
    platform: str | None = None

    ALLOW_EMPTY_FIELDS: ClassVar[set[str]] = {"school_name"}

    @field_validator("*", mode="before")
    @classmethod
    def ensure_string(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value.strip()

    @field_validator("*", mode="after")
    @classmethod
    def ensure_non_empty(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        if not value and info.field_name not in cls.ALLOW_EMPTY_FIELDS:
            raise ValueError("must not be empty")
        return value


class ApiResponse(BaseModel):
    status: Literal["ok", "error"]
    code: str
    message: str
    request_id: str
