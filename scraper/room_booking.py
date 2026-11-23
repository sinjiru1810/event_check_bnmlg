"""
scraper/room_booking.py

Scraper Room Booking & Transaction BINUS Maya (halaman staff /newstaff).

Endpoint ditemukan dari network saat membuka:
    https://acadservices.apps.binus.ac.id/newstaff/#/room/roomBookingTransaction

Semua request butuh cookie session (diambil otomatis dari .auth oleh api.client),
plus header X-Requested-With + Content-Type JSON seperti yang dikirim JS aslinya.

Pemakaian:
    python scraper/room_booking.py --date 2026-11-23
    python scraper/room_booking.py --date 2026-11-23 --location MALANG --out output

Atau dari Python:
    from scraper.room_booking import scrape
    data = scrape("2026-11-23", location="MALANG")
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.client import session as make_http_session

BASE_URL = "https://acadservices.apps.binus.ac.id/services/ci/index.php/"
REFERER = "https://acadservices.apps.binus.ac.id/newstaff/"
DEFAULT_LOCATION = "MALANG"

# Tipe ruangan yang dianggap "lab". Bisa ditambah sesuai kebutuhan kampus.
LAB_FACILITY_TYPES = {
    "Lab Mac",
    "Lab PR",
    "Lab Gambar DKV",
    "Computer Lab",
    "Multimedia Room",
    "Photography Room",
    "Pre Press Room",
    "Drawing Room",
    "Bengkel Furniture",
}
LAB_KEYWORDS = ("lab", "multimedia", "photography", "pre press", "drawing", "bengkel")


class SessionExpired(RuntimeError):
    """Session akademik sudah mati -> perlu refresh/login ulang."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _parse_json(text: str) -> Any:
    """
    Beberapa endpoint menyisipkan <div>PHP Notice</div> sebelum JSON.
    Cari awal array/object pertama yang benar-benar bisa di-parse.
    """
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"[\[{]", stripped):
        try:
            return json.loads(stripped[match.start() :])
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Respons bukan JSON: {stripped[:200]!r}")


def http_session():
    """Session requests yang sudah login + header ala AJAX CodeIgniter."""
    http = make_http_session()
    http.headers.update(
        {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": REFERER,
        }
    )
    return http


def fetch(http, endpoint: str, payload: dict) -> Any:
    response = http.post(
        BASE_URL + endpoint,
        data=json.dumps(payload),
        timeout=45,
    )
    if response.status_code != 200:
        raise RuntimeError(f"{endpoint}: HTTP {response.status_code}")

    text = response.text
    lowered = text.lower()
    if "newdefault/login.html" in lowered or "<title>business server error" in lowered:
        raise SessionExpired(
            "Session BINUS Maya sudah mati. Jalankan: python auth/session.py "
            "(atau python auth/login.py kalau diminta MFA)."
        )

    try:
        return _parse_json(text)
    except ValueError as exc:
        raise RuntimeError(f"{endpoint}: {exc}") from exc


# --------------------------------------------------------------------------- #
# endpoint wrappers
# --------------------------------------------------------------------------- #
def get_locations(http) -> list[dict]:
    return fetch(
        http,
        "general/getFilterData",
        {"listField": ["DistinctPrevilegeLocation"]},
    ).get("DistinctPrevilegeLocation", [])


def get_shifts(http, location: str) -> list[dict]:
    return fetch(http, "room/room/getBookingShift", {"Location": location})


def get_rooms(http, location: str) -> list[dict]:
    return fetch(http, "room/room/getListRoom", {"Location": location})


def get_detail(http, location: str, day: str) -> list[dict]:
    return fetch(
        http,
        "room/room/getDetailRoom",
        {"Location": location, "Date": day},
    )


def get_booked(http, location: str, day: str) -> list[dict]:
    return fetch(
        http,
        "room/room/getBookedRoom",
        {"Date": day, "Location": location},
    )


def get_approved(http, location: str, day: str) -> list[dict]:
    return fetch(
        http,
        "room/room/getApprovedRoom",
        {"Date": day, "Location": location},
    )


def get_blackout(http, location: str, day: str) -> list[dict]:
    return fetch(
        http,
        "room/room/getBlackoutRoom",
        {"Location": location, "Tgl": day},
    )


def get_exam(http, location: str, day: str) -> list[dict]:
    return fetch(
        http,
        "room/room/getExamRoom",
        {"Location": location, "Date": day},
    )


def get_cancel_rejected(http, location: str, day: str) -> list[dict]:
    return fetch(
        http,
        "room/room/getCancelRejectedRoom",
        {"Location": location, "Date": day},
    )


# --------------------------------------------------------------------------- #
# high level
# --------------------------------------------------------------------------- #
def _normalize_booking(item: dict, status: str) -> dict:
    """Samakan bentuk data booked & approved supaya gampang ditampilkan."""
    return {
        "Status": status,
        "Facility_ID": item.get("Facility_ID") or item.get("FACILITY_ID"),
        "Room": item.get("ROOM") or item.get("Room"),
        "BinusianID": item.get("BinusianID"),
        "Name": item.get("NAME") or item.get("Name"),
        "Description": item.get("Description"),
        "Notes": item.get("Notes"),
        "Telephone": item.get("Telephone") or item.get("SPONSOR_PHONE"),
        "Attendee": item.get("Attendee"),
        "StartTime": item.get("Meeting_Time_Start") or item.get("MEETING_TIME_START"),
        "EndTime": item.get("Meeting_Time_End") or item.get("MEETING_TIME_END"),
        "ShiftStart": item.get("SHIFT_START"),
        "ShiftEnd": item.get("SHIFT_END"),
        "MeetingType": item.get("CAMPUS_MTG_TYPE_DESCR"),
    }


def is_lab(room: dict) -> bool:
    """Klasifikasi ruangan lab berdasarkan FACILITY_TYPE."""
    facility_type = str(room.get("FACILITY_TYPE") or "").strip()
    lowered = facility_type.lower()
    return (
        facility_type in LAB_FACILITY_TYPES
        or any(keyword in lowered for keyword in LAB_KEYWORDS)
    )


def filter_lab_rooms(rooms: list[dict]) -> list[dict]:
    return [room for room in rooms if is_lab(room)]


def filter_lab_bookings(bookings: list[dict], lab_rooms: list[dict]) -> list[dict]:
    """
    ID booking pakai prefix (MLG0104C), sedangkan getListRoom pakai 0104C.
    Cocokkan dengan suffix + nomor ruang.
    """
    lab_ids = [str(room.get("FACILITY_ID") or "").upper() for room in lab_rooms]
    lab_names = {
        str(room.get("ROOM") or "").upper()
        for room in lab_rooms
        if room.get("ROOM")
    }

    def matches(booking: dict) -> bool:
        facility_id = str(booking.get("Facility_ID") or "").upper()
        room_name = str(booking.get("Room") or "").upper()
        return (
            room_name in lab_names
            or any(facility_id.endswith(lab_id) for lab_id in lab_ids if lab_id)
        )

    return [booking for booking in bookings if matches(booking)]


def _dedupe(items: list[dict]) -> list[dict]:
    """API kadang mengembalikan baris identik dua kali; buang duplikatnya."""
    seen: set[str] = set()
    result = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def scrape(day: str, location: str = DEFAULT_LOCATION) -> dict:
    """
    Ambil semua data room booking untuk satu tanggal + lokasi.

    `day` format YYYY-MM-DD.
    """
    http = http_session()

    rooms = get_rooms(http, location)
    lab_rooms = filter_lab_rooms(rooms)

    booked = get_booked(http, location, day)
    approved = get_approved(http, location, day)
    peminjaman = _dedupe(
        [_normalize_booking(item, "Requested") for item in booked]
        + [_normalize_booking(item, "Approved") for item in approved]
    )

    return {
        "date": day,
        "location": location,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
        "locations": get_locations(http),
        "shifts": get_shifts(http, location),
        "rooms": rooms,
        "lab_rooms": lab_rooms,
        "detail": get_detail(http, location, day),
        "booked": booked,
        "approved": approved,
        "blackout": get_blackout(http, location, day),
        "exam": get_exam(http, location, day),
        "cancel_rejected": get_cancel_rejected(http, location, day),
        "peminjaman": peminjaman,
        "lab_peminjaman": filter_lab_bookings(peminjaman, lab_rooms),
    }


def save(result: dict, out_dir: Path) -> list[Path]:
    """Simpan per-endpoint + ringkasan peminjaman, mirip format dump mentor."""
    out_dir.mkdir(parents=True, exist_ok=True)
    day = result["date"]
    mapping = {
        "getBookingShift": result["shifts"],
        "getListRoom": result["rooms"],
        "getDetailRoom": result["detail"],
        "getBookedRoom": result["booked"],
        "getApprovedRoom": result["approved"],
        "getBlackoutRoom": result["blackout"],
        "getExamRoom": result["exam"],
        "getCancelRejectedRoom": result["cancel_rejected"],
    }
    written = []
    for name, payload in mapping.items():
        path = out_dir / f"{name}_{day}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written.append(path)

    summary = out_dir / f"peminjaman_{day}.json"
    summary.write_text(
        json.dumps(
            {
                "date": day,
                "location": result["location"],
                "scraped_at": result["scraped_at"],
                "total": len(result["peminjaman"]),
                "data": result["peminjaman"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    written.append(summary)

    lab_summary = out_dir / f"peminjaman_lab_{day}.json"
    lab_summary.write_text(
        json.dumps(
            {
                "date": day,
                "location": result["location"],
                "lab_rooms": [
                    {
                        "Facility_ID": room.get("FACILITY_ID"),
                        "ROOM": room.get("ROOM"),
                        "FACILITY_TYPE": room.get("FACILITY_TYPE"),
                        "ROOM_CAPACITY": room.get("ROOM_CAPACITY"),
                    }
                    for room in result["lab_rooms"]
                ],
                "total": len(result["lab_peminjaman"]),
                "data": result["lab_peminjaman"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    written.append(lab_summary)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Scraper room booking BINUS Maya")
    parser.add_argument(
        "--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: hari ini)"
    )
    parser.add_argument(
        "--location", default=DEFAULT_LOCATION, help="MALANG / MLGB / ML001"
    )
    parser.add_argument("--out", default="output", help="folder output JSON")
    parser.add_argument("--print", action="store_true", help="tampilkan ringkasan")
    parser.add_argument(
        "--lab-only",
        action="store_true",
        help="ringkasan & output hanya ruangan/peminjaman lab",
    )
    args = parser.parse_args()

    try:
        result = scrape(args.date, args.location)
    except SessionExpired as exc:
        print(f"[EXPIRED] {exc}")
        return 2

    files = save(result, Path(args.out))
    print(
        f"[OK] {args.date} / {args.location}: "
        f"{len(result['rooms'])} ruangan ({len(result['lab_rooms'])} lab), "
        f"{len(result['detail'])} jadwal, "
        f"{len(result['peminjaman'])} peminjaman "
        f"({len(result['lab_peminjaman'])} lab)"
    )
    for path in files:
        if args.lab_only and "peminjaman_" in path.name and "peminjaman_lab_" not in path.name:
            continue
        print(f"     -> {path}")

    rows = result["lab_peminjaman"] if args.lab_only else result["peminjaman"]
    if args.print:
        for item in rows[:20]:
            print(
                f"     {item['Facility_ID']:>8} | {item['Status']:<9} | "
                f"{str(item['StartTime'])[:5]}-{str(item['EndTime'])[:5]} | "
                f"{item['Name']} | {item['Description']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
