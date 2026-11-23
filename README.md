# event_check_bnmlg

Scraper data room booking / jadwal ruangan BINUS Maya (kampus Malang).

## Status

- [x] Login BINUS Maya via Microsoft (OAuth2 authorization code flow)
- [x] Refresh session headless + session `requests` siap pakai
- [ ] Scraper endpoint room booking (`getListRoom`, `getBookedRoom`, `getBookingShift`, `getDetailRoom`)

## Cara login

Login-nya **nggak** scraping form. `acadservices` pakai Microsoft SSO, jadi yang
dilakukan script adalah menjalankan flow OAuth yang asli di browser yang kita
kendalikan, lalu memanen cookie session-nya.

```
LoginAD.php
  -> login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize
  -> LoginAD.php?code=...
  -> (server BINUS tukar code -> token -> set cookie PHPSESSID)
  -> dashboard
```

Parameter yang dipakai (terbaca dari `LoginAD.php`):

| Parameter     | Nilai                                              |
| ------------- | -------------------------------------------------- |
| tenant        | `3485b963-82ba-4a6f-810f-b5cc226ff898`             |
| client_id     | `6435970a-4248-4e70-95f4-e44325f6467e`             |
| scope         | `User.Read`                                        |
| response_type | `code`                                             |
| redirect_uri  | `https://acadservices.apps.binus.ac.id/LoginAD.php` |

Konsekuensinya: **session nggak bisa dibikin sendiri** dari luar. `code` cuma
bisa ditukar pakai client secret yang ada di server BINUS, dan `redirect_uri`-nya
sudah dikunci ke domain mereka. Jadi pendekatannya: jalankan flow asli di
browser otomatis, ambil cookie-nya.

### Instalasi

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### Login pertama

```powershell
python auth/login.py
```

Jendela Chromium kebuka. Ketik email + password di situ, selesaikan MFA.
Setelah sampai dashboard, browser otomatis diarahkan ke
`https://acadservices.apps.binus.ac.id/newstaff/#/index`, lalu cookie disimpan
ke `.auth/state.json`. Tujuan ini bisa diganti lewat `BINUS_LANDING_URL` di `.env`.

Kalau mau email/password di-prefill otomatis, isi `.env` (lihat `.env.example`).
Kosongkan saja kalau lebih nyaman ngetik manual.

### Refresh session (tanpa login manual)

```powershell
python auth/session.py
python auth/session.py --cookies   # sekalian dump cookie buat requests
```

Exit code `0` = session hidup, `2` = perlu login manual lagi.

Cara kerjanya: buka `LoginAD.php` pakai state tersimpan, Microsoft lihat session
MS-nya masih hidup, balik ke `acadservices`, cookie baru tersimpan. Jadi yang
perlu login manual cuma kalau tenant minta re-auth (sign-in frequency / MFA).

## Web UI

Ada halaman login + dashboard lokal:

```powershell
python web/app.py
# buka http://127.0.0.1:8000/login
```

- `/login` — form email (opsional) + tombol **Masuk dengan Microsoft**.
  Tombol ini menjalankan `auth/login.py`, dan lognya ditampilkan live.
- `/` — status session: jumlah cookie, masa berlaku, tombol refresh & logout.

**UI ini sengaja nggak punya kolom password.** Password tetap diketik di
domain resmi Microsoft. Kalau UI kita yang menerima password, itu pola
credential harvesting dan MFA tetap nggak bisa dilewati.

Session juga **terikat ke browser Playwright**, bukan ke Chrome/Edge harian.
Maka tombol **Buka Dashboard BIMAY** menjalankan browser ber-session itu,
bukan membuka link di browser biasa (yang nggak punya cookie dan bakal minta
login lagi).

Struktur web:

```
web/app.py               FastAPI + endpoint
web/pages/login.html     halaman login
web/pages/dashboard.html halaman status
web/static/style.css     styling
web/static/app.js        logic frontend (polling log live)
```

## Struktur

```
auth/login.py      # login interaktif sekali, simpan .auth/state.json
auth/session.py    # refresh headless + dump cookie
api/client.py      # requests.Session yang sudah terautentikasi
```

## Cek cepat

```powershell
python api/client.py
# status=200 len=23754 login_page=False
# final=https://acadservices.apps.binus.ac.id/newstaff/
```

Kalau `login_page=True`, artinya cookie sudah mati -> jalankan
`python auth/session.py` (atau `python auth/login.py` kalau sampai minta MFA).

## Catatan

- `.env` dan `.auth/` sudah di-gitignore. `state.json` setara token akses —
  jangan di-commit, jangan dishare.
- Dump API di root repo ini berisi data pribadi (nama, nomor HP, BinusianID).
  Jangan di-commit ulang; kalau perlu, bersihkan dari history.
- Kasih delay antar request. Ini server kampus, jangan di-hammer.
