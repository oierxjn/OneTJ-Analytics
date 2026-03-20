from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_text(value: object, field_name: str) -> str:
    '''
    去掉首尾空格

    :param value: 输入值
    :param field_name: 字段名称(用于错误信息)
    :return: 去掉首尾空格的字符串
    '''
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def parse_semver(value: str, field_name: str) -> tuple[int, ...]:
    '''
    解析语义化版本号

    :param value: 输入值
    :param field_name: 字段名称(用于错误信息)
    :return: 语义化版本号元组
    '''
    normalized = normalize_text(value, field_name)
    parts = normalized.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"{field_name} must be a semantic version in the format major.minor.patch")
    return tuple(int(part) for part in parts)


class UpdateCheckQuery(BaseModel):
    platform: Literal["windows", "android"]
    arch: str | None = None
    current_version: str
    current_build: str

    @field_validator("arch", mode="before")
    @classmethod
    def validate_arch(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_text(value, "arch").lower()

    @field_validator("current_version", mode="before")
    @classmethod
    def validate_current_version(cls, value: object) -> str:
        return normalize_text(value, "current_version")

    @field_validator("current_build", mode="before")
    @classmethod
    def validate_current_build(cls, value: object) -> str:
        result = normalize_text(value, "current_build")
        if not result.isdigit() or int(result) <= 0:
            raise ValueError("current_build must be a positive integer")
        return result

    @property
    def current_build_number(self) -> int:
        return int(self.current_build)

    @property
    def current_version_tuple(self) -> tuple[int, ...]:
        return parse_semver(self.current_version, "current_version")

    @property
    def manifest_key(self) -> str:
        if self.platform == "android":
            return "android:default"
        return f"{self.platform}:{self.arch or 'default'}"


class UpdateManifestEntry(BaseModel):
    latest_version: str
    latest_build: int = Field(gt=0)
    release_notes: str | None = None
    published_at: datetime | None = None
    mandatory: bool = False
    download_url: str
    sha256: str
    file_size: int | None = Field(default=None, gt=0)
    min_supported_version: str | None = None

    @field_validator("latest_version", mode="before")
    @classmethod
    def validate_latest_version(cls, value: object) -> str:
        return normalize_text(value, "latest_version")

    @field_validator("release_notes", "download_url", "sha256", "min_supported_version", mode="before")
    @classmethod
    def validate_text_fields(cls, value: object, info) -> str | None:
        if value is None:
            return None
        return normalize_text(value, info.field_name)

    @field_validator("download_url")
    @classmethod
    def validate_download_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("download_url must use https")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("sha256 must be a 64-character lowercase hex string")
        return value

    @field_validator("latest_version")
    @classmethod
    def validate_latest_version_format(cls, value: str) -> str:
        parse_semver(value, "latest_version")
        return value

    @field_validator("min_supported_version")
    @classmethod
    def validate_min_supported_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parse_semver(value, "min_supported_version")
        return value

    @property
    def latest_version_tuple(self) -> tuple[int, ...]:
        return parse_semver(self.latest_version, "latest_version")


class UpdateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: dict[str, UpdateManifestEntry]


class UpdateCheckData(BaseModel):
    has_update: bool
    latest_version: str | None = None
    latest_build: int | None = None
    release_notes: str | None = None
    published_at: str | None = None
    mandatory: bool | None = None
    download_url: str | None = None
    sha256: str | None = None
    file_size: int | None = None
    min_supported_version: str | None = None


class UpdateCheckResponse(BaseModel):
    status: Literal["ok"]
    code: Literal["SUCCESS"]
    message: str
    request_id: str
    data: UpdateCheckData
