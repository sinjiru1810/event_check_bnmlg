"""
web/app.py

Web UI lokal buat login + monitoring session BINUS Maya.

Jalankan:
    python web/app.py
    # atau
    uvicorn web.app:app --port 8000

Endpoint:
    GET  /                      dashboard (status session)
    GET  /login                 halaman login
    GET  /api/status            status session (cepat, baca file)
    POST /api/login/start       jalankan auth/login.py di background
    GET  /api/login/log         tail log proses login (buat live progress)
    POST /api/session/refresh   verifikasi + refresh cookie via headless
    POST /api/logout            hapus session tersimpan

Catatan keamanan:
    UI ini TIDAK menerima password. Password cuma diketik di halaman resmi
    Microsoft, di jendela browser yang dibuka oleh auth/login.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import date as _date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent
AUTH_DIR = ROOT / ".auth"
STATE_PATH = AUTH_DIR / "state.json"
COOKIES_PATH = AUTH_DIR / "cookies.json"
LOGIN_LOG = AUTH_DIR / "login.log"

app = FastAPI(title="BINUS Maya - Login")
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

_proc: subprocess.Popen | None = None
_lock = threading.Lock()

ROOMS_CACHE_TTL = 300  # detik; jangan hammer server kampus
_rooms_cache: dict[tuple[str, str], tuple[float, dict]] = {}


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def _state_summary() -> dict:
    summary = {
        "has_state": STATE_PATH.exists(),
        "cookie_count": 0,
        "expires_at": None,
        "updated_at": None,
    }
    if not summary["has_state"]:
        return summary

    summary["updated_at"] = STATE_PATH.stat().st_mtime
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        summary["cookie_count"] = len(cookies)
        expiries = [
            c["expires"]
            for c in cookies
            if "binus" in c.get("domain", "")
            and isinstance(c.get("expires"), (int, float))
            and c["expires"] > 0
        ]
        if expiries:
            summary["expires_at"] = min(expiries)
    except Exception:
        pass
    return summary


def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _status() -> dict:
    payload = _state_summary()
    payload["running"] = _is_running()
    payload["now"] = time.time()
    return payload


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
@app.get("/")
def dashboard_page() -> FileResponse:
    return FileResponse(WEB / "pages" / "dashboard.html")


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(WEB / "pages" / "login.html")


@app.get("/rooms")
def rooms_page() -> FileResponse:
    return FileResponse(WEB / "pages" / "rooms.html")


# --------------------------------------------------------------------------- #
# api
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    email: str | None = None


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/status")
def api_status() -> dict:
    return _status()


@app.get("/api/rooms")
def api_rooms(
    day: str | None = None,
    location: str = "MALANG",
    lab_only: bool = False,
):
    """Ambil data peminjaman ruangan/lab (cache 5 menit per tanggal+lokasi)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from scraper.room_booking import SessionExpired, scrape

    selected_day = (day or _date.today().isoformat()).strip()
    try:
        _date.fromisoformat(selected_day)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"error": "Format tanggal harus YYYY-MM-DD."}
        )

    cache_key = (selected_day, location.upper())
    cached = _rooms_cache.get(cache_key)
    fresh = True

    if cached and time.time() - cached[0] < ROOMS_CACHE_TTL:
        result = cached[1]
        fresh = False
    else:
        try:
            result = scrape(selected_day, location.upper())
        except SessionExpired as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(
                status_code=502, content={"error": f"Gagal scraping: {exc}"}
            )
        _rooms_cache[cache_key] = (time.time(), result)

    rows = result["lab_peminjaman"] if lab_only else result["peminjaman"]

    return {
        "date": result["date"],
        "location": result["location"],
        "scraped_at": result["scraped_at"],
        "fresh": fresh,
        "counts": {
            "rooms": len(result["rooms"]),
            "lab_rooms": len(result["lab_rooms"]),
            "shifts": len(result["shifts"]),
            "detail": len(result["detail"]),
            "peminjaman": len(result["peminjaman"]),
            "lab_peminjaman": len(result["lab_peminjaman"]),
            "shown": len(rows),
        },
        "locations": result["locations"],
        "lab_rooms": result["lab_rooms"],
        "rows": rows,
    }


@app.post("/api/login/start")
def api_login_start(payload: LoginRequest | None = None) -> dict:
    global _proc

    with _lock:
        if _is_running():
            return {"started": False, "reason": "Login sedang berjalan."}

        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        email = (payload.email or "").strip() if payload else ""
        if email:
            env["BINUS_EMAIL"] = email

        handle = open(LOGIN_LOG, "w", encoding="utf-8")
        _proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "auth" / "login.py"), "--timeout", "600"],
            cwd=str(ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        handle.close()

    return {"started": True}


@app.get("/api/login/log")
def api_login_log() -> dict:
    text = ""
    if LOGIN_LOG.exists():
        text = LOGIN_LOG.read_text(encoding="utf-8", errors="replace")
    return {
        "log": text[-6000:],
        "running": _is_running(),
        "log_updated_at": LOGIN_LOG.stat().st_mtime if LOGIN_LOG.exists() else None,
        "status": _status(),
    }


@app.post("/api/login/cancel")
def api_login_cancel() -> dict:
    """Hentikan proses login + browser child-nya (Windows: taskkill /T)."""
    global _proc

    with _lock:
        if not _is_running():
            _proc = None
            return {"ok": True, "cancelled": False}

        pid = _proc.pid
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
            )
        else:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()

        _proc = None

    return {"ok": True, "cancelled": True, "status": _status()}


@app.post("/api/session/refresh")
def api_session_refresh() -> dict:
    """Jalankan refresh headless. Blocking ~10-20 detik (threadpool FastAPI)."""
    try:
        result = subprocess.run(
            [sys.executable, "-u", str(ROOT / "auth" / "session.py"), "--cookies"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "Timeout: refresh lebih dari 180 detik."}

    return {
        "ok": result.returncode == 0,
        "output": (result.stdout + result.stderr).strip(),
        "status": _status(),
    }


@app.post("/api/logout")
def api_logout() -> dict:
    for path in (STATE_PATH, COOKIES_PATH):
        path.unlink(missing_ok=True)
    return {"ok": True, "status": _status()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
