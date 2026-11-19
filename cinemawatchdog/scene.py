"""Scene Cinemas (Cairo Festival City) scraper.

How the site works (as of Nov 2026):
  * https://cfc.scenecinemas.com/                       -> movie links  /movie-details/<slug>.html
  * /movie-details/<slug>.html                          -> list of business days (dd-mm-yyyy)
  * /movie-details/<slug>.html?business_day=D&ajax=1    -> showtimes for that day, grouped by experience.
        Sold-out showtimes are rendered as <a class="... showtime_soldout" href="javascript:void(0);">.
  * /booking-<showtime_id>                              -> seat-map bootstrap (CSRF token, order id, hall id)
  * POST /seat-plan {showtime_id, order_id, hall_id}    -> JSON list of grid cells with status.
"""
from __future__ import annotations

import re
import threading
import time

import requests
from bs4 import BeautifulSoup

from .common import (ProviderError, Seat, SeatMap, Showtime, iso_from_dmy,
                     parse_time_label, split_seat_label)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


class SceneProvider:
    key = "scene_cfc"
    name = "Scene Cinemas – Cairo Festival City"
    short = "Scene CFC"
    base = "https://cfc.scenecinemas.com"
    supports_seats = True
    seat_types: list[str] = []  # Scene seat types come from the hall (e.g. ScreenX)

    def __init__(self):
        self._local = threading.local()

    # -- http -------------------------------------------------------------
    @property
    def s(self) -> requests.Session:
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            self._local.session = sess
        return sess

    def _get(self, url, **kw) -> requests.Response:
        last = None
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=30, **kw)
                if r.status_code == 200:
                    return r
                last = ProviderError(f"HTTP {r.status_code} for {url}")
            except requests.RequestException as e:
                last = ProviderError(f"{type(e).__name__}: {e}")
            time.sleep(1.5 * (attempt + 1))
        raise last

    # -- movies -----------------------------------------------------------
    def list_movies(self) -> list[dict]:
        html = self._get(self.base + "/").text
        soup = BeautifulSoup(html, "html.parser")
        movies: dict[str, str] = {}
        for a in soup.select('a[href*="/movie-details/"]'):
            m = re.search(r"/movie-details/([^/?#]+)\.html", a.get("href", ""))
            if not m:
                continue
            slug = m.group(1)
            name = self._name_near(a)
            if name and (slug not in movies or len(name) > len(movies[slug])):
                movies[slug] = name
            movies.setdefault(slug, "")
        out = []
        for slug, name in movies.items():
            out.append({"slug": slug, "name": name or slug.replace("-", " ").title()})
        out.sort(key=lambda m: (0 if "avengers" in m["slug"] else 1, m["name"]))
        return out

    @staticmethod
    def _name_near(a) -> str:
        if a.get("title"):
            return a["title"].strip().upper()
        txt = a.get_text(" ", strip=True)
        if txt and not re.search(r"book|trailer|booking|details", txt, re.I) and len(txt) < 80:
            txt = re.sub(r"^(PG|NR|\d+\+)\s+", "", txt)
            return txt.strip().upper()
        img = a.find("img")
        if img and img.get("alt"):
            return img["alt"].strip().upper()
        return ""

    # -- showtimes --------------------------------------------------------
    def list_dates(self, slug: str) -> list[str]:
        html = self._get(f"{self.base}/movie-details/{slug}.html").text
        days = re.findall(r"LoadShowtimes\('(\d{2}-\d{2}-\d{4})'\)", html)
        seen, out = set(), []
        for d in days:
            if d not in seen:
                seen.add(d)
                out.append(d)
        return [iso_from_dmy(d) for d in out]

    def list_showtimes(self, slug: str, dates: list[str] | None = None) -> list[Showtime]:
        all_dates = self.list_dates(slug)
        wanted = [d for d in all_dates if not dates or d in dates]
        out: list[Showtime] = []
        for iso in wanted:
            dmy = "-".join(reversed(iso.split("-")))
            html = self._get(f"{self.base}/movie-details/{slug}.html",
                             params={"business_day": dmy, "ajax": "1"}).text
            out.extend(self._parse_day(slug, iso, html))
        return out

    def _parse_day(self, slug, iso, html) -> list[Showtime]:
        soup = BeautifulSoup(html, "html.parser")
        res = []
        for block in soup.select("div[class*='_content']"):
            label = block.find("span")
            if not label:
                continue
            exp = label.get_text(strip=True)
            for a in block.select("ul li a"):
                tl = a.get_text(strip=True)
                try:
                    t24 = parse_time_label(tl)
                except ValueError:
                    continue
                href = a.get("href", "")
                m = re.search(r"showtime-([0-9a-f]+)", href)
                sold = "showtime_soldout" in (a.get("class") or []) or not m
                res.append(Showtime(
                    cinema=self.key, movie_slug=slug, date=iso, time=t24, time_label=tl,
                    experience=exp, showtime_id=m.group(1) if m else None,
                    bookable=not sold,
                    booking_url=f"{self.base}/showtime-{m.group(1)}" if m else
                    f"{self.base}/movie-details/{slug}.html"))
        return res

    # -- seats ------------------------------------------------------------
    def seat_map(self, st: Showtime) -> SeatMap | None:
        if not st.showtime_id:
            return None
        sid = st.showtime_id
        sess = requests.Session()  # fresh session per seat-map: avoids piling up carts
        sess.headers.update({"User-Agent": UA})
        sess.get(f"{self.base}/showtime-{sid}", timeout=30)
        h = sess.get(f"{self.base}/booking-{sid}", timeout=30).text
        tok = re.search(r"X-CSRF-TOKEN'\s*:\s*'([^']+)'", h)
        oid = re.search(r'var order_id\s*=\s*"([^"]+)"', h)
        hall = re.search(r'var hall_id\s*=\s*"([^"]+)"', h)
        if not (tok and oid and hall):
            raise ProviderError("Scene booking page format changed (no token/order/hall)")
        r = sess.post(f"{self.base}/seat-plan",
                      data={"showtime_id": sid, "order_id": oid.group(1), "hall_id": hall.group(1)},
                      headers={"X-CSRF-TOKEN": tok.group(1), "X-Requested-With": "XMLHttpRequest",
                               "Referer": f"{self.base}/showtime-{sid}"},
                      timeout=30)
        if r.status_code != 200:
            raise ProviderError(f"seat-plan HTTP {r.status_code}")
        data = r.json().get("data") or []
        seats = []
        for cell in data:
            st_type = cell.get("st") or ""
            if st_type in ("Blank", "SeatRowTitle", ""):
                continue
            m = re.match(r"grid-(\d+)-(\d+)", cell.get("app_id") or "")
            if not m:
                continue
            label = (cell.get("st_txt") or "").strip()
            row, num = split_seat_label(label)
            free = (cell.get("st_name") == "Free" and st_type not in ("Occupied", "Hold")
                    and bool(cell.get("app_category_id")))
            seats.append(Seat(label=label, row=row, number=num, grid_row=int(m.group(1)),
                              grid_col=int(m.group(2)), free=free,
                              seat_type="" if st_type in ("Occupied", "Hold") else st_type))
        return SeatMap(seats=seats)
