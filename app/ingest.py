import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from redis.asyncio import Redis
from redis.typing import EncodableT, FieldT

from app.config import Settings
from app.schemas import EventIn

StreamFields = dict[FieldT, EncodableT]


@dataclass(slots=True)
class EventEnvelope:
    request_id: str
    received_at: str
    client_ip: str
    payload: dict[str, str | None]

    @classmethod
    def from_event(cls, payload: EventIn, request_id: str, client_ip: str) -> "EventEnvelope":
        return cls(
            request_id=request_id,
            received_at=datetime.now(timezone.utc).isoformat(),
            client_ip=client_ip,
            payload=payload.model_dump(by_alias=True, exclude_none=False),
        )

    def to_stream_fields(self) -> StreamFields:
        return {
            "request_id": self.request_id,
            "received_at": self.received_at,
            "client_ip": self.client_ip,
            "payload_json": json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")),
        }


class EventProducer(ABC):
    @abstractmethod
    async def enqueue(self, event: EventEnvelope) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class InMemoryEventProducer(EventProducer):
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def enqueue(self, event: EventEnvelope) -> None:
        self.events.append(event)

    async def close(self) -> None:
        return None


class RedisStreamEventProducer(EventProducer):
    def __init__(self, client: Redis, stream_key: str, maxlen: int) -> None:
        self.client = client
        self.stream_key = stream_key
        self.maxlen = maxlen

    async def enqueue(self, event: EventEnvelope) -> None:
        await self.client.xadd(
            name=self.stream_key,
            fields=event.to_stream_fields(),
            maxlen=self.maxlen,
            approximate=True,
        )

    async def close(self) -> None:
        await self.client.close()


def build_event_producer(settings: Settings) -> EventProducer:
    backend = settings.ingest_backend.lower().strip()
    if backend == "redis":
        client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        return RedisStreamEventProducer(client, settings.redis_stream_key, settings.redis_stream_maxlen)
    if backend == "memory":
        return InMemoryEventProducer()
    raise ValueError("ingest_backend must be either 'memory' or 'redis'")
