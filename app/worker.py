import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from redis.asyncio import Redis
from redis.typing import EncodableT, FieldT, ResponseT

from app.config import Settings
from app.storage import PersistedEvent, PostgresEventWriter

logger = logging.getLogger("collector.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class EventIngestWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        self.writer = PostgresEventWriter(settings.database_url)
        self.stream_key = settings.redis_stream_key
        self.group = settings.consumer_group
        self.consumer_name = settings.consumer_name
        self.batch_size = settings.batch_size
        self.block_ms = settings.consume_block_ms
        self.flush_interval_ms = settings.flush_interval_ms
        self.dlq_stream = f"{self.stream_key}.dlq"

    async def start(self) -> None:
        await self.writer.connect()
        await self._ensure_group()
        logger.info("worker started stream=%s group=%s consumer=%s", self.stream_key, self.group, self.consumer_name)
        await self._consume_forever()

    async def close(self) -> None:
        await self.redis.close()
        await self.writer.close()

    async def _ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(name=self.stream_key, groupname=self.group, id="0", mkstream=True)
        except Exception as exc:
            # BUSYGROUP means the consumer group already exists.
            if "BUSYGROUP" not in str(exc):
                raise

    async def _consume_forever(self) -> None:
        while True:
            try:
                response: ResponseT = await self.redis.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer_name,
                    streams={self.stream_key: ">"},
                    count=self.batch_size,
                    block=self.block_ms,
                )
                if not response:
                    await asyncio.sleep(self.flush_interval_ms / 1000)
                    continue

                message_ids: list[str] = []
                events: list[PersistedEvent] = []

                self._parse_stream_entries(response, message_ids, events)
                
                await self._handle_persist(message_ids, events)

            except Exception as exc:
                logger.exception("worker consume loop failed: %s", exc)
                await asyncio.sleep(1.0)

    def _parse_stream_entries(
        self, response: ResponseT, message_ids: list[str], events: list[PersistedEvent]
    ) -> None :
        '''
        解析xreadgroup返回的stream entries，返回message ids和events。
        如果前四层解析失败，抛出错误。message_id解析失败也抛出错误。
        只要message_id解析成功，就添加到message_ids中，用于后续的ack（认为是可ack的）
        event解析失败则跳过

        参考Response格式：
  [
      (
          "collector.events",
          [
              (
                  "1710000000000-0",
                  {
                      "request_id": "abc",
                      "received_at": "2026-03-10T12:00:00+00:00",
                      "client_ip": "1.2.3.4",
                      "payload_json": "{\"userid\":\"2333333\"}"
                  }
              ),
              (
                  "1710000000001-0",
                  {
                      "request_id": "def",
                      "received_at": "2026-03-10T12:00:01+00:00",
                      "client_ip": "5.6.7.8",
                      "payload_json": "{\"userid\":\"2333334\"}"
                  }
              ),
          ],
      )
  ]
        '''
        if not isinstance(response, Sequence):
            raise RuntimeError(f"xreadgroup returned unexpected response type {type(response)}")

        stream = response[0]

        if not isinstance(stream, Sequence):
            logger.error("xreadgroup returned unexpected stream type %s; dropping this poll", type(stream))
            raise RuntimeError("unexpected stream type")
        
        if len(stream) != 2:
            logger.error("xreadgroup returned unexpected stream entry count %s; dropping this poll", len(stream))
            raise RuntimeError("unexpected stream entry count")

        stream_entries = stream[1]
        if not isinstance(stream_entries, Sequence):
            logger.error("xreadgroup returned unexpected stream entries type %s; dropping this poll", type(stream_entries))
            raise RuntimeError("unexpected stream entries type")

        for entry in stream_entries:
            if not isinstance(entry, Sequence):
                logger.error("xreadgroup returned unexpected stream entry type %s; dropping this poll", type(entry))
                raise RuntimeError("unexpected stream entry type")
            if len(entry) != 2:
                logger.error("xreadgroup returned unexpected stream entry count %s; dropping this poll", len(entry))
                raise RuntimeError("unexpected stream entry count")
            message_id_raw = entry[0]
            if not isinstance(message_id_raw, str):
                logger.error("xreadgroup returned unexpected stream entry message id type %s; dropping this poll", type(message_id_raw))
                raise RuntimeError("unexpected stream entry message id type")
            message_ids.append(message_id_raw)
            
            fields = entry[1]
            if not isinstance(fields, Mapping):
                logger.error("xreadgroup returned unexpected stream entry fields type %s; dropping this poll", type(fields))
                continue
            
            try:
                events.append(PersistedEvent.from_stream_fields(fields))
            except Exception:
                logger.exception("failed to parse event from stream fields, skip this event")
                continue

    async def _handle_persist(self, message_ids: list[str], events: list[PersistedEvent]) -> None:
        try:
            await self.writer.insert_events(events)
            await self.redis.xack(self.stream_key, self.group, *message_ids)
        except Exception:
            logger.exception("batch insert failed, leave pending for retry")


async def main() -> None:
    settings = Settings()
    worker = EventIngestWorker(settings)
    try:
        await worker.start()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
