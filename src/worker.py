"""Background worker that drains the solve queue using a browser pool."""

from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from src.proxy import redact_proxy
from src.solver import BrowserPool, SolveError
from src.store import TaskStore


class SolveWorker:
    """Consumes task IDs from a queue and runs them on pooled Camoufox workers."""

    def __init__(
        self,
        store: TaskStore,
        pool: BrowserPool,
        max_concurrent: int,
    ) -> None:
        self.store = store
        self.pool = pool
        self.max_concurrent = max(1, max_concurrent)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._dispatcher: Optional[asyncio.Task] = None
        self._inflight: set[asyncio.Task] = set()
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._dispatcher is not None:
            return
        self._stopped.clear()
        self._dispatcher = asyncio.create_task(self._run(), name="solve-dispatcher")
        logger.info(
            "Solve worker started (max_concurrent={}, browsers={})",
            self.max_concurrent,
            self.pool.worker_count,
        )

    async def stop(self) -> None:
        self._stopped.set()
        if self._dispatcher is not None:
            await self.queue.put("")  # unblock
            try:
                await asyncio.wait_for(self._dispatcher, timeout=5.0)
            except asyncio.TimeoutError:
                self._dispatcher.cancel()
            self._dispatcher = None

        # Wait briefly for in-flight solves
        if self._inflight:
            await asyncio.wait(self._inflight, timeout=10.0)
            for task in list(self._inflight):
                if not task.done():
                    task.cancel()
            self._inflight.clear()

        logger.info("Solve worker stopped")

    async def enqueue(self, task_id: str) -> None:
        await self.queue.put(task_id)

    async def _run(self) -> None:
        while not self._stopped.is_set():
            task_id = await self.queue.get()
            if self._stopped.is_set() or not task_id:
                self.queue.task_done()
                break
            handle = asyncio.create_task(
                self._handle(task_id),
                name=f"solve-{task_id[:8]}",
            )
            self._inflight.add(handle)
            handle.add_done_callback(self._inflight.discard)
            self.queue.task_done()

    async def _handle(self, task_id: str) -> None:
        async with self._semaphore:
            task = await self.store.mark_processing(task_id)
            if task is None:
                logger.warning("Task {} disappeared before processing", task_id)
                return

            proxy_label = redact_proxy(task.proxy) if task.proxy else "direct"
            logger.info(
                "Solving task {} site_key={}… url={} proxy={}",
                task_id,
                task.site_key[:12],
                task.page_url,
                proxy_label,
            )

            solver = await self.pool.acquire()
            try:
                token = await solver.solve(
                    task.site_key,
                    task.page_url,
                    proxy=task.proxy,
                )
                await self.store.mark_ready(task_id, token)
                finished = await self.store.get(task_id)
                logger.success(
                    "Task {} ready ({} chars, {} ms, worker={})",
                    task_id,
                    len(token),
                    finished.elapsed_ms if finished else "?",
                    solver.worker_id,
                )
            except SolveError as exc:
                await self.store.mark_failed(task_id, str(exc))
                logger.error("Task {} failed: {}", task_id, exc)
            except Exception as exc:  # noqa: BLE001
                await self.store.mark_failed(task_id, f"unexpected error: {exc}")
                logger.exception("Task {} crashed: {}", task_id, exc)
            finally:
                await self.pool.release(solver)
