"""Application settings loaded from environment / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Turnstile solver API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_title: str = "Turnstile Solver API"
    api_version: str = "0.1.0"

    # Parallelism
    # worker_count = number of Camoufox browser processes
    # max_concurrent = max in-flight solves (capped by free browsers in the pool)
    worker_count: int = 2
    max_concurrent: int = 2

    solve_timeout_seconds: float = 60.0
    navigation_timeout_ms: int = 30_000
    task_ttl_seconds: int = 600

    # Camoufox headless mode:
    # - false: headed
    # - true: headless
    # - virtual: headless via Xvfb on Linux
    headless: bool | str = True

    # Fingerprint OS passed to Camoufox: windows | macos | linux
    browser_os: str = "windows"

    # Optional proxy list (one per line). Used when request omits proxy.
    proxy_file: str = "proxies.txt"


settings = Settings()
