"""Camoufox-based Cloudflare Turnstile solver."""

from __future__ import annotations

import asyncio
import html
import time
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from camoufox.async_api import AsyncCamoufox
from loguru import logger

from src.config import settings
from src.proxy import redact_proxy, to_playwright_proxy

# Soft-fail codes that often clear after a reload / re-click.
_RETRYABLE_TURNSTILE_CODES = {"600010", "600007", "300030"}


class SolveError(Exception):
    """Raised when a Turnstile challenge cannot be solved."""


def _normalize_url(url: str) -> str:
    """Ensure a stable absolute URL for routing (preserve query/fragment)."""
    parts = urlsplit(url.strip())
    path = parts.path or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _widget_html(site_key: str) -> str:
    """Minimal page with an *implicit* Turnstile widget (data-sitekey div)."""
    safe_key = html.escape(site_key, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Just a moment...</title>
  <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
  <style>
    html, body {{ margin: 0; padding: 0; background: #fff; }}
    .center {{
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
  </style>
</head>
<body>
  <div class="center">
    <div class="cf-turnstile"
         data-sitekey="{safe_key}"
         data-theme="light"
         data-size="normal"
         data-callback="onTsSuccess"
         data-error-callback="onTsError"
         data-expired-callback="onTsExpired"></div>
  </div>
  <script>
    window.__tsToken = null;
    window.__tsError = null;
    window.onTsSuccess = function (token) {{ window.__tsToken = token; window.__tsError = null; }};
    window.onTsError = function (code) {{
      window.__tsError = code ? String(code) : "turnstile_error";
    }};
    window.onTsExpired = function () {{ window.__tsToken = null; }};
  </script>
</body>
</html>
"""


def _same_document_url(request_url: str, page_url: str) -> bool:
    """True if request_url is a top-level navigation to page_url (query-aware)."""
    req = urlsplit(request_url)
    target = urlsplit(page_url)
    return (
        req.scheme == target.scheme
        and req.netloc.lower() == target.netloc.lower()
        and req.path.rstrip("/") == target.path.rstrip("/")
        and req.query == target.query
    )


def _coerce_headless(value: bool | str) -> bool | str:
    """Normalize env HEADLESS into Camoufox's accepted types."""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized == "virtual":
        return "virtual"
    return value


class TurnstileSolver:
    """One Camoufox browser instance that can solve Turnstile widgets."""

    def __init__(self, worker_id: int = 0) -> None:
        self.worker_id = worker_id
        self._camoufox: Optional[AsyncCamoufox] = None
        self._browser: Any = None

    @property
    def ready(self) -> bool:
        return self._browser is not None

    async def start(self) -> None:
        if self._browser is not None:
            return

        headless = _coerce_headless(settings.headless)
        logger.info(
            "Worker {} starting Camoufox (headless={}, os={})",
            self.worker_id,
            headless,
            settings.browser_os,
        )

        self._camoufox = AsyncCamoufox(
            headless=headless,
            os=settings.browser_os,
            humanize=True,
        )
        self._browser = await self._camoufox.__aenter__()
        logger.info("Worker {} Camoufox ready", self.worker_id)

    async def stop(self) -> None:
        if self._camoufox is not None:
            try:
                await self._camoufox.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Worker {} error while stopping Camoufox: {}",
                    self.worker_id,
                    exc,
                )
            self._camoufox = None
            self._browser = None
        logger.info("Worker {} Camoufox stopped", self.worker_id)

    async def solve(
        self,
        site_key: str,
        page_url: str,
        proxy: Optional[str] = None,
    ) -> str:
        """Solve Turnstile for site_key as if rendered on page_url. Returns token."""
        if self._browser is None:
            raise SolveError("browser is not started")

        page_url = _normalize_url(page_url)

        context_kwargs: dict[str, Any] = {"no_viewport": True}
        if proxy:
            context_kwargs["proxy"] = to_playwright_proxy(proxy)
            logger.debug(
                "Worker {} using proxy {}",
                self.worker_id,
                redact_proxy(proxy),
            )

        # IMPORTANT: browser.new_page() fails with Camoufox + recent Playwright
        # ("isMobile" not in Browser.setDefaultViewport scheme). Create a
        # context with no_viewport instead, then open a page on it.
        context = await self._browser.new_context(**context_kwargs)
        page = await context.new_page()
        page.set_default_timeout(settings.navigation_timeout_ms)

        async def fulfill_document(route) -> None:
            request = route.request
            if request.resource_type == "document" and _same_document_url(
                request.url, page_url
            ):
                await route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=_widget_html(site_key),
                )
                return
            await route.continue_()

        try:
            await page.route("**/*", fulfill_document)

            logger.debug(
                "Worker {} navigating to {} for site_key={}…",
                self.worker_id,
                page_url,
                site_key[:12],
            )
            await page.goto(page_url, wait_until="domcontentloaded")

            token = await self._wait_for_token(page, settings.solve_timeout_seconds)
            if not token:
                raise SolveError("timeout waiting for turnstile token")
            logger.info(
                "Worker {} token obtained ({} chars) for {}",
                self.worker_id,
                len(token),
                page_url,
            )
            return token
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass

    async def _read_state(self, page) -> dict:
        return await page.evaluate(
            """() => {
                if (window.__tsToken) return { token: window.__tsToken };
                const el = document.querySelector(
                  'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
                );
                if (el && el.value) return { token: el.value };
                if (window.__tsError) return { error: window.__tsError };
                return {};
            }"""
        )

    async def _try_click_widget(self, page) -> None:
        """Click the Turnstile host / checkbox iframe when interaction is needed."""
        try:
            host = page.locator("div.cf-turnstile").first
            if await host.count() > 0:
                await host.click(timeout=1500, force=True)
                return
        except Exception:  # noqa: BLE001
            pass

        for frame in page.frames:
            if "challenges.cloudflare.com" not in (frame.url or ""):
                continue
            for selector in (
                "input[type='checkbox']",
                "label",
                "body",
            ):
                try:
                    loc = frame.locator(selector).first
                    if await loc.count() > 0:
                        await loc.click(timeout=1500, force=True)
                        return
                except Exception:  # noqa: BLE001
                    continue

    async def _wait_for_token(self, page, timeout: float) -> Optional[str]:
        deadline = time.monotonic() + timeout
        poll_interval = 0.5
        last_error: Optional[str] = None
        reloads = 0
        max_reloads = 2

        while time.monotonic() < deadline:
            state = await self._read_state(page)
            token = state.get("token")
            if token:
                return token

            error = state.get("error")
            if error and error != last_error:
                last_error = str(error)
                logger.warning(
                    "Worker {} Turnstile error {}",
                    self.worker_id,
                    last_error,
                )
                await page.evaluate("() => { window.__tsError = null; }")
                if last_error in _RETRYABLE_TURNSTILE_CODES and reloads < max_reloads:
                    reloads += 1
                    logger.info(
                        "Worker {} retryable error {} — reloading ({}/{})",
                        self.worker_id,
                        last_error,
                        reloads,
                        max_reloads,
                    )
                    await page.reload(wait_until="domcontentloaded")
                    await asyncio.sleep(1.0)
                    continue

            await self._try_click_widget(page)
            await asyncio.sleep(poll_interval)

        state = await self._read_state(page)
        if state.get("token"):
            return state["token"]
        if last_error:
            raise SolveError(f"turnstile widget error: {last_error}")
        if state.get("error"):
            raise SolveError(f"turnstile widget error: {state['error']}")
        return None


class BrowserPool:
    """Pool of ready TurnstileSolver browsers (one Camoufox each)."""

    def __init__(self, worker_count: int) -> None:
        self.worker_count = max(1, worker_count)
        self._solvers: list[TurnstileSolver] = [
            TurnstileSolver(worker_id=i) for i in range(self.worker_count)
        ]
        self._available: asyncio.Queue[TurnstileSolver] = asyncio.Queue()

    @property
    def ready_count(self) -> int:
        return sum(1 for s in self._solvers if s.ready)

    async def start(self) -> None:
        # Start browsers concurrently for faster boot.
        await asyncio.gather(*(solver.start() for solver in self._solvers))
        for solver in self._solvers:
            await self._available.put(solver)
        logger.info("Browser pool ready ({} workers)", self.worker_count)

    async def stop(self) -> None:
        await asyncio.gather(
            *(solver.stop() for solver in self._solvers),
            return_exceptions=True,
        )
        # Drain queue
        while not self._available.empty():
            try:
                self._available.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info("Browser pool stopped")

    async def acquire(self) -> TurnstileSolver:
        return await self._available.get()

    async def release(self, solver: TurnstileSolver) -> None:
        await self._available.put(solver)
