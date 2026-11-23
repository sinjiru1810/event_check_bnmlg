"""
api/client.py

Session `requests` yang sudah terautentikasi, dibangun dari cookie hasil login
Playwright (.auth/cookies.json).

Pakai:

    from api.client import session

    s = session()
    r = s.get("https://acadservices.apps.binus.ac.id/...")

Kalau cookie belum ada, otomatis refresh headless lewat auth/session.py
(nggak perlu login manual selama session Microsoft masih hidup).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
COOKIES_PATH = ROOT / ".auth" / "cookies.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/159.0.0.0 Safari/537.36"
)


def _read_cookies() -> list[dict]:
    if not COOKIES_PATH.exists():
        return []
    return json.loads(COOKIES_PATH.read_text(encoding="utf-8"))


def session(refresh_if_missing: bool = True) -> requests.Session:
    cookies = _read_cookies()

    if not cookies and refresh_if_missing:
        from auth.session import dump_cookies, refresh

        ok, fresh = asyncio.run(refresh())
        if ok:
            dump_cookies(fresh)
            cookies = _read_cookies()

    http = requests.Session()
    http.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        }
    )
    for cookie in cookies:
        http.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie["domain"],
            path=cookie["path"],
        )
    return http


if __name__ == "__main__":
    probe = session().get("https://acadservices.apps.binus.ac.id/newstaff/", timeout=30)
    is_login_page = "login.html" in probe.text.lower()
    print(f"status={probe.status_code} len={len(probe.text)} login_page={is_login_page}")
    print(f"final={probe.url}")
