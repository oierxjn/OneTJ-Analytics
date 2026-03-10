from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OneTJ Data Collector"
    environment: str = "test"
    require_https: bool = False
    rate_limit_per_minute: int = 16
    max_payload_bytes: int = 1_048_576
    ingest_backend: str = "memory"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_stream_key: str = "collector.events"
    redis_stream_maxlen: int = 1_000_000
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:5432/onetj_analytics"
    consumer_group: str = "collector-workers"
    consumer_name: str = "worker-1"
    batch_size: int = 500
    flush_interval_ms: int = 100
    consume_block_ms: int = 1000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
