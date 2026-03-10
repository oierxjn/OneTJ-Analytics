import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
from redis.typing import EncodableT, FieldT


@dataclass(slots=True)
class PersistedEvent:
    request_id: str
    received_at: datetime
    client_ip: str
    hash_id: str
    userid: str | None
    username: str | None
    client_version: str | None
    device_brand: str | None
    device_model: str | None
    dept_name: str | None
    school_name: str | None
    gender: str | None
    platform: str | None
    payload_json: str

    @classmethod
    def from_stream_fields(cls, fields: Mapping[FieldT, EncodableT]) -> "PersistedEvent":
        normalized = normalize_stream_fields(fields)
        payload_raw = normalized.get("payload_json", "{}")
        payload = json.loads(payload_raw)
        hash_id_raw = payload.get("hashId")
        return cls(
            request_id=normalized["request_id"],
            received_at=datetime.fromisoformat(normalized["received_at"]),
            client_ip=normalized.get("client_ip", "unknown"),
            hash_id=_required_non_empty_str(hash_id_raw, "hashId"),
            userid=_as_nullable_str(payload.get("userid")),
            username=_as_nullable_str(payload.get("username")),
            client_version=_as_nullable_str(payload.get("client_version")),
            device_brand=_as_nullable_str(payload.get("device_brand")),
            device_model=_as_nullable_str(payload.get("device_model")),
            dept_name=_as_nullable_str(payload.get("dept_name")),
            school_name=_as_nullable_str(payload.get("school_name")),
            gender=_as_nullable_str(payload.get("gender")),
            platform=_as_nullable_str(payload.get("platform")),
            payload_json=payload_raw,
        )


def normalize_stream_fields(fields: Mapping[FieldT, EncodableT]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in fields.items():
        key = _to_text(raw_key)
        value = _to_text(raw_value)
        normalized[key] = value
    return normalized


def _to_text(value: FieldT | EncodableT) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8")
    if isinstance(value, memoryview):
        return value.tobytes().decode("utf-8")
    return str(value)


def _as_nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _required_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


class PostgresEventWriter:
    def __init__(self, database_url: str, pool_min_size: int = 1, pool_max_size: int = 10) -> None:
        self.database_url = database_url
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            dsn=self.database_url,
            min_size=self.pool_min_size,
            max_size=self.pool_max_size,
        )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def insert_events(self, events: list[PersistedEvent]) -> None:
        '''
        row列和query参数的顺序要一致，否则会串列
        '''
        if not events:
            return
        if self.pool is None:
            raise RuntimeError("PostgresEventWriter is not connected")

        rows = [
            (
                e.request_id,
                e.received_at,
                e.client_ip,
                e.hash_id,
                e.userid,
                e.username,
                e.client_version,
                e.device_brand,
                e.device_model,
                e.dept_name,
                e.school_name,
                e.gender,
                e.platform,
                e.payload_json,
            )
            for e in events
        ]

        query = """
            INSERT INTO events_raw (
                request_id,
                received_at,
                client_ip,
                hash_id,
                userid,
                username,
                client_version,
                device_brand,
                device_model,
                dept_name,
                school_name,
                gender,
                platform,
                payload_json
            )
            VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb
            )
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, rows)
