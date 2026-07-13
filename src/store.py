"""In-memory task store for solve jobs."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.models import TaskStatus


@dataclass
class Task:
    task_id: str
    site_key: str
    page_url: str
    proxy: Optional[str] = None  # normalized proxy URL, if any
    status: TaskStatus = TaskStatus.PENDING
    token: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    @property
    def elapsed_ms(self) -> Optional[int]:
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return int((end - self.started_at) * 1000)


class TaskStore:
    """Thread-safe (async) in-memory task registry."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._ttl_seconds = ttl_seconds

    async def create(
        self,
        site_key: str,
        page_url: str,
        proxy: Optional[str] = None,
    ) -> Task:
        task = Task(
            task_id=str(uuid.uuid4()),
            site_key=site_key,
            page_url=page_url,
            proxy=proxy,
        )
        async with self._lock:
            await self._purge_expired_unlocked()
            self._tasks[task.task_id] = task
        return task

    async def get(self, task_id: str) -> Optional[Task]:
        async with self._lock:
            await self._purge_expired_unlocked()
            return self._tasks.get(task_id)

    async def mark_processing(self, task_id: str) -> Optional[Task]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = TaskStatus.PROCESSING
            task.started_at = time.monotonic()
            return task

    async def mark_ready(self, task_id: str, token: str) -> Optional[Task]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = TaskStatus.READY
            task.token = token
            task.finished_at = time.monotonic()
            return task

    async def mark_failed(self, task_id: str, error: str) -> Optional[Task]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = TaskStatus.FAILED
            task.error = error
            task.finished_at = time.monotonic()
            return task

    async def _purge_expired_unlocked(self) -> None:
        """Drop finished tasks older than TTL. Caller must hold the lock."""
        now = time.monotonic()
        expired = [
            task_id
            for task_id, task in self._tasks.items()
            if task.finished_at is not None
            and (now - task.finished_at) > self._ttl_seconds
        ]
        for task_id in expired:
            del self._tasks[task_id]
