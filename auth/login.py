"""
auth/login.py

Login ke BINUS Maya lewat Microsoft (OAuth2 authorization code flow).

Alurnya sama persis dengan yang terjadi di browser biasa:
    LoginAD.php -> login.microsoftonline.com/authorize -> LoginAD.php?code=...
    -> server BINUS tukar code jadi token -> set cookie session -> dashboard

Script ini cuma "menemani" flow itu di browser yang kita kendalikan, lalu
menyimpan cookie session-nya ke .auth/state.json supaya run berikutnya
nggak perlu login lagi.

Pemakaian:
    python auth/login.py

Kredensial (opsional semua):
    BINUS_EMAIL     -> kalau diisi, form email Microsoft di-prefill otomatis
    BINUS_PASSWORD  -> kalau diisi, form password diisi otomatis
    Kalau kosong, kak ketik sendiri di jendela browser (cara paling aman).

CATATAN KEAMANAN:
    - Script ini TIDAK PERNAH menulis password ke disk.
    - .auth/state.json itu setara token akses: jangan di-commit, jangan dishare.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / ".auth" / "state.json"

ACAD_HOST = "acadservices.apps.binus.ac.id"
START_URL = f"https://{ACAD_HOST}/LoginAD.php"
LANDING_URL = f"https://{ACAD_HOST}/newstaff/#/index"
LOGIN_TIMEOUT_S = 600  # 10 menit: cukup buat MFA + consent + "Stay signed in?"

EMAIL_SELECTORS = "input[name='loginfmt'], input[type='email'], #i0116"
PASSWORD_SELECTORS = "input[name='passwd'], input[type='password'], #i0118"
SUBMIT_SELECTORS = "#idSIButton9, input[type='submit']"


def _load_dotenv(path: Path) -> None:
    """Loader .env minimalis, biar nggak perlu dependency tambahan."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def _click_if_present(page: Page, selector: str, timeout_ms: int = 3000) -> bool:
    try:
        element = page.locator(selector).first
        await element.wait_for(state="visible", timeout=timeout_ms)
        await element.click()
        return True
    except Exception:
        return False


async def _fill_if_present(page: Page, selector: str, value: str, timeout_ms: int = 8000) -> bool:
    if not value:
        return False
    try:
        element = page.locator(selector).first
        await element.wait_for(state="visible", timeout=timeout_ms)
        await element.fill(value)
        return True
    except Exception:
        return False


def _is_dashboard(url: str) -> bool:
    if ACAD_HOST not in url:
        return False
    lowered = url.lower()
    return "login.html" not in lowered and "loginad.php" not in lowered


async def _answer_kmsi(page: Page, handled: set[int]) -> None:
    """Klik 'Stay signed in? / Tetap masuk?' biar session Microsoft awet."""
    if id(page) in handled or "login.microsoftonline.com" not in page.url:
        return
    try:
        if await page.locator("#KmsiCheckboxField").count():
            await _click_if_present(page, "#idSIButton9", timeout_ms=1500)
            handled.add(id(page))
            print("      'Stay signed in' dijawab otomatis")
    except Exception:
        pass


async def _wait_for_dashboard(context: BrowserContext, timeout_s: int) -> Page | None:
    deadline = time.time() + timeout_s
    handled: set[int] = set()
    last_report = 0.0
    while time.time() < deadline:
        for page in context.pages:
            if _is_dashboard(page.url):
                return page
            await _answer_kmsi(page, handled)

        if time.time() - last_report >= 15:
            last_report = time.time()
            remaining = int(deadline - time.time())
            if context.pages:
                current = context.pages[-1].url
                print(f"      [{remaining:4d}s] {current[:110]}", flush=True)
            else:
                print(f"      [{remaining:4d}s] (semua tab ditutup?)", flush=True)

        await asyncio.sleep(1.0)
    return None


async def _dump_debug(context: BrowserContext) -> None:
    """Screenshot + teks halaman terakhir, buat diagnosa kalau gagal."""
    debug_dir = ROOT / ".auth" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for index, page in enumerate(context.pages):
        try:
            shot = debug_dir / f"{stamp}-tab{index}.png"
            await page.screenshot(path=str(shot), full_page=False)
            print(f"        screenshot -> {shot}")
            body = (await page.inner_text("body"))[:1200]
            print(f"        --- teks halaman tab{index} ---")
            for line in body.splitlines():
                if line.strip():
                    print(f"        | {line.strip()[:100]}")
        except Exception as exc:
            print(f"        gagal ambil debug tab{index}: {exc}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Login BINUS Maya via Microsoft SSO")
    parser.add_argument(
        "--timeout",
        type=int,
        default=LOGIN_TIMEOUT_S,
        help=f"batas waktu tunggu login dalam detik (default {LOGIN_TIMEOUT_S})",
    )
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    _load_dotenv(ROOT / ".env")

    email = os.environ.get("BINUS_EMAIL", "").strip()
    password = os.environ.get("BINUS_PASSWORD", "")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        context_options = {"viewport": None, "locale": "id-ID"}
        if STATE_PATH.exists():
            # Bawa cookie lama: kalau session Microsoft masih hidup, redirect
            # LoginAD.php -> Microsoft -> balik lagi terjadi tanpa MFA/password.
            context_options["storage_state"] = str(STATE_PATH)
            print("[0/4] Session tersimpan dimuat (coba login otomatis)")
        context = await browser.new_context(**context_options)
        page = await context.new_page()

        print(f"[1/4] Buka {START_URL}")
        await page.goto(START_URL, wait_until="domcontentloaded")

        if email:
            print("[2/4] Prefill email...")
            if await _fill_if_present(page, EMAIL_SELECTORS, email):
                await _click_if_present(page, SUBMIT_SELECTORS)
                print("      email diisi otomatis")
        else:
            print("[2/4] Email kosong di .env -> ketik sendiri di browser")

        if password:
            print("[3/4] Prefill password...")
            if await _fill_if_present(page, PASSWORD_SELECTORS, password, timeout_ms=20000):
                await _click_if_present(page, SUBMIT_SELECTORS)
                print("      password diisi otomatis")
            else:
                print("      form password belum muncul")
        else:
            print("[3/4] Password kosong di .env -> ketik sendiri di browser")

        print("[4/4] Selesaikan login + MFA di jendela browser.")
        print(f"      Menunggu sampai masuk dashboard (maks {args.timeout // 60} menit)...")

        dashboard = await _wait_for_dashboard(context, args.timeout)
        if dashboard is None:
            print("\n[GAGAL] Nggak sampai dashboard.")
            await _dump_debug(context)
            await context.close()
            await browser.close()
            return 1

        print(f"\n[OK] Masuk: {dashboard.url}")

        landing = os.environ.get("BINUS_LANDING_URL", "").strip() or LANDING_URL
        try:
            await dashboard.goto(landing, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            print(f"     Diarahkan ke: {dashboard.url}")
        except Exception as exc:
            print(f"     [!] Gagal buka landing page: {exc}")

        await context.storage_state(path=str(STATE_PATH))
        cookies = await context.cookies()
        print(f"     {len(cookies)} cookie disimpan -> {STATE_PATH}")

        await context.close()
        await browser.close()

    print("\nSelesai. Cek session kapan saja dengan: python auth/session.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
