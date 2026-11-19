"""Shared data structures and helpers for cinema providers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Showtime:
    cinema: str            # provider key, e.g. "scene_cfc" / "vox_almaza"
    movie_slug: str
    date: str              # business date, ISO "YYYY-MM-DD"
    time: str              # 24h "HH:MM"
    time_label: str        # as shown on the site, e.g. "08:00 PM"
    experience: str        # e.g. "ScreenX", "Premiere", "Standard", "GOLD", "MAX"
    showtime_id: str | None  # None when the site hides the id (e.g. Scene sold-out)
    bookable: bool         # False when the site marks it sold out / unavailable
    booking_url: str | None

    @property
    def key(self) -> str:
        return f"{self.cinema}|{self.movie_slug}|{self.date}|{self.experience}|{self.time}"

    def to_dict(self):
        d = asdict(self)
        d["key"] = self.key
        return d


@dataclass
class Seat:
    label: str        # e.g. "F12"
    row: str          # e.g. "F"
    number: str       # e.g. "12"
    grid_row: int     # physical row index in the hall grid
    grid_col: int     # physical column index (gaps = aisles)
    free: bool
    seat_type: str = ""   # e.g. "ScreenX", "Standard", "Premium"


@dataclass
class SeatMap:
    seats: list[Seat] = field(default_factory=list)

    @property
    def free_seats(self) -> list[Seat]:
        return [s for s in self.seats if s.free]

    @property
    def total(self) -> int:
        return len(self.seats)


def parse_time_label(label: str) -> str:
    """'08:00 PM' / '8:00pm' / '12:00 AM' -> 'HH:MM' (24h)."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap])\.?m", label.strip(), re.I)
    if not m:
        raise ValueError(f"Unrecognised time: {label!r}")
    h, mnt, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ap == "a" and h == 12:
        h = 0
    elif ap == "p" and h != 12:
        h += 12
    return f"{h:02d}:{mnt:02d}"


def split_seat_label(label: str) -> tuple[str, str]:
    m = re.match(r"^\s*([A-Za-z]+)\s*-?\s*(\d+)\s*$", label or "")
    if not m:
        return (label or "").strip().upper(), ""
    return m.group(1).upper(), m.group(2)


def iso_from_dmy(s: str) -> str:
    return datetime.strptime(s, "%d-%m-%Y").strftime("%Y-%m-%d")


def dmy_from_iso(s: str) -> str:
    return datetime.strptime(s, "%Y-%m-%d").strftime("%d-%m-%Y")


def ymd_compact(s: str) -> str:
    return s.replace("-", "")


class ProviderError(Exception):
    pass
