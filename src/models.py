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
    proxy: Optional[str] = Field(
        default=None,
        description=(
            "Optional proxy for this solve. Formats: host:port, "
            "user:pass@host:port, host:port:user:pass, http://..., socks5://..."
        ),
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
    proxy: Optional[str] = Field(
        default=None,
        description="Redacted proxy used for the solve (if any)",
    )


class HealthResponse(BaseModel):
    status: str
    service: str
    workers: int = 0
    browsers_ready: int = 0
    proxies: int = 0
    max_concurrent: int = 0
