import time
import asyncio
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import Optional
from dataclasses import dataclass, asdict

from loguru import logger
from camoufox.sync_api import Camoufox
from camoufox import DefaultAddons
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import uvicorn

# ── Browser Config ───────────────────────────────────────────────────
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
]

# ── Logging ──────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
)
logger.add(
    LOG_DIR / "turnstile-solver_{time:YYYY-MM-DD}.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
)


# ── Models ───────────────────────────────────────────────────────────
@dataclass
class SolveResult:
    token: Optional[str] = None
    elapsed: float = 0.0
    status: str = "failure"
    error: Optional[str] = None


# ── HTML Template ────────────────────────────────────────────────────
TURNSTILE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Turnstile Solver</title>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async></script>
    <script>
        async function fetchIP() {
            try {
                const response = await fetch('https://api64.ipify.org?format=json');
                const data = await response.json();
                document.getElementById('ip-display').innerText = 'Your IP: ' + data.ip;
            }} catch (error) {{
                document.getElementById('ip-display').innerText = 'Failed to fetch IP';
            }}
        }}
        window.onload = fetchIP;
    </script>
</head>
<body>
    <!-- cf turnstile -->
    <p id="ip-display">Fetching your IP...</p>
</body>
</html>"""


# ── Solver (Sync) ────────────────────────────────────────────────────
class TurnstileSolver:
    """Solve Cloudflare Turnstile challenges using Camoufox browser."""

    def __init__(self, headless: bool = False):
        self.headless = headless

    def _build_html(
        self,
        sitekey: str,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
    ) -> str:
        action_attr = f' data-action="{action}"' if action else ""
        cdata_attr = f' data-cdata="{cdata}"' if cdata else ""
        turnstile_div = (
            f'<div class="cf-turnstile" data-sitekey="{sitekey}"'
            f'{action_attr}{cdata_attr}></div>'
        )
        return TURNSTILE_HTML.replace("<!-- cf turnstile -->", turnstile_div)

    def solve(
        self,
        url: str,
        sitekey: str,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        timeout: int = 30,
    ) -> SolveResult:
        """Navigate to url, inject Turnstile widget, poll for token."""
        start = time.time()
        browser = None

        try:
            browser = Camoufox(
                headless=self.headless,
                exclude_addons=[DefaultAddons.UBO],
                args=BROWSER_ARGS,
            ).start()
            page = browser.new_page()

            # Ensure URL ends with / for proper route matching
            url = url + "/" if not url.endswith("/") else url

            # Intercept and inject Turnstile page
            html = self._build_html(sitekey, action, cdata)
            page.route(url, lambda route: route.fulfill(body=html, status=200))
            page.goto(url)

            logger.info(f"Solving Turnstile for sitekey={sitekey[:20]}...")

            # Poll for token
            deadline = start + timeout
            while time.time() < deadline:
                try:
                    token = page.input_value("[name=cf-turnstile-response]")
                    if token:
                        elapsed = round(time.time() - start, 3)
                        logger.info(
                            f"Solved! token={token[:45]}... elapsed={elapsed}s"
                        )
                        return SolveResult(
                            token=token, elapsed=elapsed, status="success"
                        )

                    # Click widget to trigger interactive challenge
                    page.click("//div[@class='cf-turnstile']", timeout=2000)
                    time.sleep(0.5)
                except Exception:
                    pass

                time.sleep(1)

            elapsed = round(time.time() - start, 3)
            logger.warning(f"Timeout after {elapsed}s")
            return SolveResult(elapsed=elapsed, status="failure", error="timeout")

        except Exception as exc:
            elapsed = round(time.time() - start, 3)
            logger.error(f"Solver error: {exc}")
            return SolveResult(elapsed=elapsed, status="failure", error=str(exc))

        finally:
            if browser:
                browser.close()


# ── FastAPI Server ───────────────────────────────────────────────────
app = FastAPI(
    title="Turnstile Solver",
    description="Solve Cloudflare Turnstile challenges via API",
    version="0.1.0",
)

executor = ProcessPoolExecutor(max_workers=4)


def _run_solve(
    url: str,
    sitekey: str,
    action: Optional[str],
    cdata: Optional[str],
    headless: bool,
    timeout: int,
) -> dict:
    """Run solver in a dedicated process (fully isolated from FastAPI event loop)."""
    solver = TurnstileSolver(headless=headless)
    result = solver.solve(
        url=url, sitekey=sitekey, action=action, cdata=cdata, timeout=timeout
    )
    return asdict(result)


@app.get("/solve")
async def solve_endpoint(
    url: str = Query(..., description="Target URL containing the Turnstile widget"),
    sitekey: str = Query(..., description="Cloudflare Turnstile sitekey"),
    action: Optional[str] = Query(None, description="Optional Turnstile action"),
    cdata: Optional[str] = Query(None, description="Optional Turnstile cdata"),
    headless: bool = Query(False, description="Run browser in headless mode"),
    timeout: int = Query(30, description="Timeout in seconds"),
):
    """Solve a Turnstile challenge and return the token."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        _run_solve,
        url,
        sitekey,
        action,
        cdata,
        headless,
        timeout,
    )
    return JSONResponse(content=result)


@app.get("/")
def root():
    return {
        "name": "Turnstile Solver",
        "version": "0.1.0",
        "endpoints": {
            "/solve": "GET - Solve a Turnstile challenge",
            "/health": "GET - Health check",
        },
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Entry Point ──────────────────────────────────────────────────────
def main():
    logger.info("Starting Turnstile Solver API on http://0.0.0.0:5000")
    uvicorn.run(app, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()