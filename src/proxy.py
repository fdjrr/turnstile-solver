"""Proxy parsing and optional round-robin pool."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse

from loguru import logger

# host:port:user:pass  (password may contain ':')
_COLON4_RE = re.compile(
    r"^(?P<host>[^:]+):(?P<port>\d+):(?P<user>[^:]+):(?P<password>.+)$"
)
# host:port
_COLON2_RE = re.compile(r"^(?P<host>[^:]+):(?P<port>\d+)$")
# user:pass@host:port
_AT_RE = re.compile(
    r"^(?P<user>[^:@]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)$"
)


class ProxyError(ValueError):
    """Raised when a proxy line cannot be parsed."""


def parse_proxy(raw: str, *, default_scheme: str = "http") -> str:
    """Normalize a proxy line to a Playwright/Camoufox-compatible URL.

    Supported formats:
      - host:port
      - host:port:user:pass
      - user:pass@host:port
      - http://host:port
      - http://user:pass@host:port
      - socks5://user:pass@host:port
    """
    line = raw.strip()
    if not line or line.startswith("#"):
        raise ProxyError("empty or comment line")

    if "://" in line:
        parsed = urlparse(line)
        if not parsed.hostname or not parsed.port:
            raise ProxyError(f"invalid proxy URL (need host+port): {raw!r}")
        scheme = parsed.scheme or default_scheme
        return _build_url(
            scheme,
            parsed.hostname,
            parsed.port,
            unquote(parsed.username or ""),
            unquote(parsed.password or ""),
        )

    m = _AT_RE.match(line)
    if m:
        return _build_url(
            default_scheme,
            m.group("host"),
            int(m.group("port")),
            m.group("user"),
            m.group("password"),
        )

    m = _COLON4_RE.match(line)
    if m:
        return _build_url(
            default_scheme,
            m.group("host"),
            int(m.group("port")),
            m.group("user"),
            m.group("password"),
        )

    m = _COLON2_RE.match(line)
    if m:
        return _build_url(
            default_scheme,
            m.group("host"),
            int(m.group("port")),
            "",
            "",
        )

    raise ProxyError(f"unrecognised proxy format: {raw!r}")


def _build_url(
    scheme: str,
    host: str,
    port: int,
    user: str,
    password: str,
) -> str:
    if user:
        auth = f"{quote(user, safe='')}:{quote(password, safe='')}@"
    else:
        auth = ""
    return f"{scheme}://{auth}{host}:{port}"


def redact_proxy(proxy_url: str) -> str:
    """Return a log-safe form of *proxy_url* (password masked)."""
    try:
        parsed = urlparse(proxy_url)
        if parsed.password is None:
            return proxy_url
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        user = parsed.username or ""
        auth = f"{user}:***@" if user else "***@"
        return f"{parsed.scheme}://{auth}{host}{port}"
    except Exception:  # noqa: BLE001
        return "<proxy>"


def to_playwright_proxy(proxy_url: str) -> dict[str, str]:
    """Convert a proxy URL to Playwright ``browser.new_context(proxy=...)`` shape."""
    parsed = urlparse(proxy_url)
    if not parsed.hostname or not parsed.port:
        raise ProxyError(f"invalid proxy URL: {proxy_url!r}")

    scheme = parsed.scheme or "http"
    server = f"{scheme}://{parsed.hostname}:{parsed.port}"
    result: dict[str, str] = {"server": server}
    if parsed.username:
        result["username"] = unquote(parsed.username)
    if parsed.password:
        result["password"] = unquote(parsed.password)
    return result


class ProxyPool:
    """Async-safe round-robin pool loaded from a text file."""

    def __init__(self) -> None:
        self._proxies: list[str] = []
        self._index = 0
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._proxies)

    def load_file(self, path: str | Path) -> int:
        """Load proxies from *path*. Returns number of proxies loaded."""
        file_path = Path(path)
        if not file_path.is_file():
            logger.warning("Proxy file not found: {}", file_path)
            self._proxies = []
            return 0

        loaded: list[str] = []
        for lineno, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                loaded.append(parse_proxy(line))
            except ProxyError as exc:
                logger.warning("Skipping proxy line {}: {}", lineno, exc)

        self._proxies = loaded
        self._index = 0
        logger.info("Loaded {} proxies from {}", len(loaded), file_path)
        return len(loaded)

    async def next(self) -> Optional[str]:
        """Return the next proxy URL, or None if the pool is empty."""
        async with self._lock:
            if not self._proxies:
                return None
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
            return proxy
