from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OneTJ Data Collector"
    environment: str = "test"
    require_https: bool = False
    rate_limit_per_minute: int = 16
    max_payload_bytes: int = 1_048_576

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

