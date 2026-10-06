"""Pydantic request/response models for the Turnstile solver API."""

from enum import Enum
from typing import Optional

from pydantic import AnyHttpUrl, BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class CreateTaskRequest(BaseModel):
    site_key: str = Field(..., min_length=1, description="Turnstile sitekey")
    page_url: AnyHttpUrl = Field(..., description="Page URL where the widget appears")
    action: Optional[str] = Field(
        None,
        pattern=r"^[A-Za-z0-9_-]{0,32}$",
        description="Optional Turnstile widget action (mirrors Cloudflare's `action` "
        'parameter, e.g. "password_signup"). Rendered as data-action on the widget; '
        "some sites reject tokens minted without the expected action.",
    )
    proxy: Optional[str] = Field(
        None,
        description="Optional proxy URL to solve through. If set, overrides the "
        "server-side proxy pool for this task.",
    )


class CreateTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING


class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    token: Optional[str] = None
    elapsed_ms: Optional[int] = None
    error: Optional[str] = None
    action: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    workers: int = 0
    browsers_ready: int = 0
    proxies: int = 0
    max_concurrent: int = 0
