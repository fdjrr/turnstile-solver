# turnstile-solver

Self-hosted Cloudflare Turnstile solver HTTP API.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Camoufox browser binary (downloaded via CLI below)

## Install

```bash
uv sync
uv run camoufox fetch
cp .env.example .env   # optional
cp proxies.txt.example proxies.txt   # optional proxy list
```

> Prefer `HEADLESS=true` (default) for production sitekeys.

## Run

```bash
uv run python main.py api
# or with auto-reload:
uv run python main.py dev
```

Server listens on `http://127.0.0.1:8000` by default. OpenAPI docs: `/docs`.

## Docker

```bash
# required before first compose up (bind mount target must be a file)
cp proxies.txt.example proxies.txt

docker compose up -d --build
curl -s http://127.0.0.1:8000/health
```

Notes:

- Container forces `API_HOST=0.0.0.0` and defaults `HEADLESS=true`, `BROWSER_OS=linux`.
- `shm_size: 2gb` is set — browsers often crash with the default 64MB `/dev/shm`.
- `./proxies.txt` is mounted read-only into the container — create the file first.
- First build runs `camoufox fetch` (large download). Later rebuilds reuse the
  Docker layer unless `pyproject.toml` / `uv.lock` change — code edits alone
  do **not** re-download the browser.

## API

### Health

```bash
curl -s http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "service": "turnstile-solver",
  "workers": 2,
  "browsers_ready": 2,
  "proxies": 0,
  "max_concurrent": 2
}
```

### Create task

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/task \
  -H 'content-type: application/json' \
  -d '{
    "site_key": "0x4AAAA...",
    "page_url": "https://example.com/login"
  }'
```

Request body is only `site_key` + `page_url`. Proxy comes from `proxies.txt` (round-robin). If the file is empty/missing, the solve runs direct (no proxy).

```json
{"task_id":"…","status":"pending"}
```

HTTP status: **202 Accepted**.

### Poll task

```bash
curl -s http://127.0.0.1:8000/api/v1/task/<task_id>
```

Ready:

```json
{
  "task_id": "…",
  "status": "ready",
  "token": "0.xxxx…",
  "elapsed_ms": 18240,
  "error": null
}
```

### Poll loop example

```bash
TASK_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/task \
  -H 'content-type: application/json' \
  -d '{"site_key":"SITE_KEY","page_url":"https://example.com"}' \
  | python -c 'import sys,json; print(json.load(sys.stdin)["task_id"])')

while true; do
  RESP=$(curl -s "http://127.0.0.1:8000/api/v1/task/$TASK_ID")
  STATUS=$(echo "$RESP" | python -c 'import sys,json; print(json.load(sys.stdin)["status"])')
  echo "$RESP"
  case "$STATUS" in
    ready|failed) break ;;
  esac
  sleep 2
done
```

## Proxy formats (`proxies.txt` only)

```
host:port
host:port:user:pass
user:pass@host:port
http://host:port
http://user:pass@host:port
socks5://user:pass@host:port
```

## Config

| Env | Default | Description |
|-----|---------|-------------|
| `API_HOST` | `127.0.0.1` | Bind host |
| `API_PORT` | `8000` | Bind port |
| `WORKER_COUNT` | `2` | Number of Camoufox browser processes |
| `MAX_CONCURRENT` | `2` | Max in-flight solves |
| `SOLVE_TIMEOUT_SECONDS` | `60` | Per-task solve deadline |
| `NAVIGATION_TIMEOUT_MS` | `30000` | `page.goto` timeout |
| `TASK_TTL_SECONDS` | `600` | Drop finished tasks after TTL |
| `MAX_SOLVES_PER_BROWSER` | `100` | Restart browser after N solves (RAM cleanup; 0 = disable) |
| `HEADLESS` | `true` | `false` / `true` / `virtual` (Xvfb) |
| `BROWSER_OS` | `windows` | Camoufox fingerprint OS |
| `PROXY_FILE` | `proxies.txt` | Optional proxy list path |

## How it works

1. On startup, load `proxies.txt` and launch `WORKER_COUNT` Camoufox browsers into a pool.
2. `POST /api/v1/task` stores a job, assigns the next pool proxy (if any), and enqueues it.
3. Dispatcher pulls jobs; each job acquires one free browser (semaphore-limited by `MAX_CONCURRENT`).
4. Browser opens a fresh context (with assigned proxy), fulfills `page_url` with a Turnstile widget page, waits for token.
5. Browser returns to the pool; poll endpoint returns `ready` / `failed`.

## Notes / limits

- Single process, in-memory task store (not multi-process / multi-machine).
- Multi-worker here means **multiple Camoufox browsers inside one API process**.
- No API auth, `action` / `cdata` / `pagedata` yet.
- Tokens expire quickly (~5 minutes) and are single-use — consume them promptly.
