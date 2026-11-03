"""Shared, bounded, change-only queue snapshots for browser subscribers."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

from fastapi.sse import ServerSentEvent

logger = logging.getLogger(__name__)


class QueuePublisher:
    def __init__(
        self,
        snapshot: Callable[[], dict],
        interval: float = 0.25,
        heartbeat: float = 15.0,
    ):
        self.snapshot = snapshot
        self.interval = interval
        self.heartbeat = heartbeat
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._last: dict | None = None

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        async with self._lock:
            # Serialize fresh subscription snapshots against ongoing publication.
            snapshot = await asyncio.to_thread(self.snapshot)
            queue.put_nowait(snapshot)
            self._subscribers.add(queue)
            if self._task is None:
                self._last = snapshot
                self._task = asyncio.create_task(self._publish())
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        task = None
        async with self._lock:
            self._subscribers.discard(queue)
            if not self._subscribers and self._task:
                task = self._task
                task.cancel()
                self._task = None
                self._last = None
        if task:
            with suppress(asyncio.CancelledError):
                await task

    async def _publish(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            async with self._lock:
                try:
                    current = await asyncio.to_thread(self.snapshot)
                except Exception:
                    logger.exception("Queue snapshot failed; retrying")
                    continue
                if current == self._last:
                    continue
                self._last = current
                for queue in self._subscribers:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(current)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._subscribers.clear()

    async def stream(self):
        queue = await self.subscribe()
        try:
            while True:
                try:
                    snapshot = await asyncio.wait_for(
                        queue.get(), timeout=self.heartbeat
                    )
                    yield ServerSentEvent(event="queue", data=snapshot, retry=3000)
                except TimeoutError:
                    yield ServerSentEvent(comment="heartbeat")
        finally:
            await self.unsubscribe(queue)
