"""Long-polling queue for firewalled Agents."""

import asyncio
from astrbot.core import logger
from .envelope import MessageEnvelope


class LongPollQueue:
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.max_size = config.get("max_queue_size", 10000)
        self.max_unacked = config.get("max_unacked", 1000)
        self.ack_timeout = config.get("ack_timeout_seconds", 60)
        self._queues: dict[str, asyncio.Queue] = {}
        self._unacked: dict[str, dict] = {}

    async def enqueue(self, envelope: MessageEnvelope):
        payload = envelope.to_dict()
        for key_id, queue in list(self._queues.items()):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(f"LongPoll queue full for {key_id}")

    def get_or_create_queue(self, key_id: str) -> asyncio.Queue:
        if key_id not in self._queues:
            self._queues[key_id] = asyncio.Queue(maxsize=self.max_size)
        return self._queues[key_id]

    async def dequeue(self, key_id: str, timeout: float) -> list[dict]:
        queue = self.get_or_create_queue(key_id)
        events = []
        try:
            while not queue.empty():
                events.append(queue.get_nowait())
            if not events:
                first = await asyncio.wait_for(queue.get(), timeout=timeout)
                events.append(first)
        except asyncio.TimeoutError:
            pass
        return events

    def ack(self, key_id: str, event_ids: list[str]):
        for eid in event_ids:
            self._unacked.pop(eid, None)
