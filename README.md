# Turnstile Solver

Cloudflare Turnstile challenge solver berbasis **Camoufox** browser dengan API server **FastAPI**.

> Saat ini mendukung **non-interactive** Turnstile (token auto-generated). Interactive/managed mode (checkbox) terdeteksi sebagai bot oleh Cloudflare.

## Cara Kerja

1. Menjalankan browser sungguhan via [Camoufox](https://github.com/daijro/camoufox) (Playwright-compatible dengan fingerprint camouflage, uBlock Origin excluded)
2. Menginjeksi widget Turnstile ke halaman target menggunakan `page.route()`
3. Polling hidden input `[name=cf-turnstile-response]` sampai token tersedia
4. Mengembalikan token sebagai response

Tidak ada reverse-engineering atau bypass kriptografi — browser asli yang menyelesaikan challenge secara natural.

## Instalasi

### Prasyarat

- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended)
- `xvfb` (untuk server tanpa display)

```bash
sudo apt install xvfb
```

### 1. Clone repository

```bash
git clone <repo-url>
cd turnstile-solver
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Install browser Camoufox

```bash
uv run python -m camoufox fetch
```

## Penggunaan

### API Server

```bash
xvfb-run --auto-servernum uv run main.py
```

Server berjalan di `http://0.0.0.0:5000`.

### Endpoint

#### `GET /solve`

Memecahkan Turnstile challenge dan mengembalikan token.

| Parameter  | Tipe    | Wajib | Deskripsi                                  |
|------------|---------|:-----:|--------------------------------------------|
| `url`      | string  |  Ya   | URL target yang memiliki widget Turnstile  |
| `sitekey`  | string  |  Ya   | Cloudflare Turnstile sitekey               |
| `action`   | string  | Tidak | Action parameter Turnstile (opsional)      |
| `cdata`    | string  | Tidak | Custom data parameter Turnstile (opsional) |
| `headless` | boolean | Tidak | Jalankan browser dalam mode headless       |
| `timeout`  | integer | Tidak | Timeout dalam detik (default: 30)          |

Contoh request (Crunchbase — non-interactive, bekerja):

```bash
curl "http://localhost:5000/solve?url=https://www.crunchbase.com/login&sitekey=0x4AAAAAAAyJK2FfyvayqHnv"
```

Response sukses:

```json
{
    "token": "0.hN7SfvLcNZR9iSwY7lY8YWE...",
    "elapsed": 8.369,
    "status": "success",
    "error": null
}
```

Response gagal:

```json
{
    "token": null,
    "elapsed": 30.0,
    "status": "failure",
    "error": "timeout"
}
```

#### `GET /health`

```bash
curl http://localhost:5000/health
```

```json
{"status": "ok"}
```

### Library Usage

```python
from main import TurnstileSolver

solver = TurnstileSolver(headless=False)
result = solver.solve(
    url="https://www.crunchbase.com/login",
    sitekey="0x4AAAAAAAyJK2FfyvayqHnv",
)

if result.status == "success":
    print(f"Token: {result.token}")
    print(f"Elapsed: {result.elapsed}s")
```

## Struktur Project

```
turnstile-solver/
├── main.py           # Solver + FastAPI server
├── pyproject.toml    # Project config & dependencies
├── README.md
└── .gitignore
```

## Dependencies

| Package            | Kegunaan                        |
|--------------------|---------------------------------|
| `camoufox[geoip]`  | Browser automation + camouflage |
| `fastapi[standard]`| API server                      |
| `loguru`           | Logging (format warna)          |

## Catatan

- Gunakan `xvfb-run` jika berjalan di server tanpa display
- Server menggunakan `ProcessPoolExecutor` agar setiap request terisolasi dari event loop FastAPI
- Non-interactive Turnstile bekerja baik (~5-9 detik per solve)
- Interactive/managed mode tidak didukung (iframe challenge tidak dirender)

## License

MIT