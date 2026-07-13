"""FastAPI application for the Turnstile solver."""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Response, status
from loguru import logger

from src.config import settings
from src.models import (
    CreateTaskRequest,
    CreateTaskResponse,
    HealthResponse,
    TaskResponse,
    TaskStatus,
)
from src.proxy import ProxyPool, redact_proxy
from src.solver import BrowserPool
from src.store import TaskStore
from src.worker import SolveWorker

store = TaskStore(ttl_seconds=settings.task_ttl_seconds)
proxy_pool = ProxyPool()
browser_pool = BrowserPool(worker_count=settings.worker_count)
worker = SolveWorker(
    store=store,
    pool=browser_pool,
    max_concurrent=settings.max_concurrent,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start browser pool + worker on boot; tear down cleanly on shutdown."""
    proxy_pool.load_file(settings.proxy_file)
    await browser_pool.start()
    await worker.start()
    logger.info(
        "API ready on {}:{} (workers={}, max_concurrent={}, proxies={})",
        settings.api_host,
        settings.api_port,
        settings.worker_count,
        settings.max_concurrent,
        proxy_pool.size,
    )
    try:
        yield
    finally:
        await worker.stop()
        await browser_pool.stop()


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
)


@app.get("/", tags=["root"])
async def root() -> dict[str, str | int]:
    return {
        "message": settings.api_title,
        "version": settings.api_version,
        "docs": "/docs",
        "workers": settings.worker_count,
        "proxies": proxy_pool.size,
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok" if browser_pool.ready_count > 0 else "degraded",
        service="turnstile-solver",
        workers=settings.worker_count,
        browsers_ready=browser_pool.ready_count,
        proxies=proxy_pool.size,
        max_concurrent=settings.max_concurrent,
    )


@app.post(
    "/api/v1/task",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["tasks"],
)
async def create_task(body: CreateTaskRequest) -> CreateTaskResponse:
    """Enqueue a Turnstile solve job and return a task id for polling."""
    if browser_pool.ready_count == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="browser pool is not ready",
        )

    # Proxy is server-side only (proxies.txt round-robin), never from the client.
    proxy_url = await proxy_pool.next()

    task = await store.create(
        site_key=body.site_key,
        page_url=str(body.page_url),
        proxy=proxy_url,
    )
    await worker.enqueue(task.task_id)
    logger.info(
        "Created task {} for {} proxy={}",
        task.task_id,
        body.page_url,
        redact_proxy(proxy_url) if proxy_url else "direct",
    )
    return CreateTaskResponse(task_id=task.task_id, status=TaskStatus.PENDING)


@app.get(
    "/api/v1/task/{task_id}",
    response_model=TaskResponse,
    tags=["tasks"],
)
async def get_task(task_id: str, response: Response) -> TaskResponse:
    """Poll solve status. Returns pending/processing/ready/failed."""
    task = await store.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    response.headers["Cache-Control"] = "no-store"

    return TaskResponse(
        task_id=task.task_id,
        status=task.status,
        token=task.token,
        elapsed_ms=(
            task.elapsed_ms
            if task.status in (TaskStatus.READY, TaskStatus.FAILED)
            else None
        ),
        error=task.error,
    )


def run_api() -> None:
    """Production-style entry (no reload)."""
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


def run_dev() -> None:
    """Dev entry with auto-reload."""
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run_api()
