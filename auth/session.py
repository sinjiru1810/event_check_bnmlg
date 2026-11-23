"""
auth/session.py

Refresh + verifikasi session BINUS Maya tanpa login manual.

Cara kerja:
    buka LoginAD.php dengan state tersimpan -> Microsoft lihat session-nya masih
    hidup -> balik ke acadservices -> cookie session baru -> simpan ulang.

Kalau tenant minta re-auth (MFA / sign-in frequency), script melapor EXPIRED
dan kak tinggal jalanin `python auth/login.py` sekali lagi.

Pemakaian:
    python auth/session.py            # cek + refresh, exit code 0 = OK
    python auth/session.py --cookies  # sekalian dump cookie buat requests/httpx
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / ".auth" / "state.json"
COOKIES_PATH = ROOT / ".auth" / "cookies.json"

ACAD_HOST = "acadservices.apps.binus.ac.id"
START_URL = f"https://{ACAD_HOST}/LoginAD.php"
REFRESH_TIMEOUT_S = 90


def _is_dashboard(url: str) -> bool:
    if ACAD_HOST not in url:
        return False
    lowered = url.lower()
    return "login.html" not in lowered and "loginad.php" not in lowered


async def refresh(verbose: bool = True) -> tuple[bool, list[dict]]:
    """Return (session_valid, cookies)."""
    if not STATE_PATH.exists():
        if verbose:
            print("[!] Belum ada .auth/state.json. Jalankan dulu: python auth/login.py")
        return False, []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(STATE_PATH), locale="id-ID")
        page = await context.new_page()

        try:
            await page.goto(START_URL, wait_until="domcontentloaded")
        except Exception as exc:
            if verbose:
                print(f"[!] Gagal buka {START_URL}: {exc}")
            await context.close()
            await browser.close()
            return False, []

        deadline = time.time() + REFRESH_TIMEOUT_S
        ok = False
        while time.time() < deadline:
            for candidate in context.pages:
                if _is_dashboard(candidate.url):
                    ok = True
                    break
            if ok:
                break
            await asyncio.sleep(1.0)

        cookies = await context.cookies()

        if ok:
            await context.storage_state(path=str(STATE_PATH))
            if verbose:
                print(f"[OK] Session hidup. {len(cookies)} cookie di-refresh.")
        elif verbose:
            print("[EXPIRED] Microsoft minta login ulang. Jalankan: python auth/login.py")
            for candidate in context.pages:
                print(f"          url terakhir: {candidate.url}")

        await context.close()
        await browser.close()

    return ok, cookies


def dump_cookies(cookies: list[dict]) -> Path:
    """Simpan cookie dalam format yang gampang dipakai requests/httpx."""
    simple = [
        {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c["path"],
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
            "expires": c.get("expires"),
        }
        for c in cookies
        if ACAD_HOST in c.get("domain", "")
    ]
    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIES_PATH.write_text(json.dumps(simple, indent=2), encoding="utf-8")
    return COOKIES_PATH


async def main() -> int:
    ok, cookies = await refresh()
    if ok and "--cookies" in sys.argv:
        path = dump_cookies(cookies)
        print(f"     cookie untuk requests disimpan -> {path}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
