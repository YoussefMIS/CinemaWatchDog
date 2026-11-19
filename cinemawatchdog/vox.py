"""VOX Cinemas Egypt scraper (City Centre Almaza).

VOX sits behind Akamai bot protection, which drops plain Python HTTP clients.
curl_cffi impersonates Chrome's TLS fingerprint and gets through.

How the site works (as of Nov 2026):
  * /movies/whatson and /movies/comingsoon             -> movie links /movies/<slug>
  * /movies/<slug>?d=YYYYMMDD                          -> showtimes for all cinemas on that date.
        Inside <section id="showtimes">: <h3>Cinema name</h3><ol class="showtimes"> with one <li> per
        experience (<strong>Standard</strong>, GOLD, MAX, ...). Each showtime <li data-id="0047-276882">
        holds <a class="action showtime" href="/booking/<id>"> when bookable or
        <span class="action showtime unavailable"> when sold out / closed.
  * Seat map = guest booking flow (no login, nothing is reserved):
        GET /booking/<id>            -> .../<session>_<id>/guest/processing  (poll ?json=1 until data.url)
        GET .../<session>_<id>/seats/fetch -> .../seats  (may also pass through /processing)
        The seats page has <div class="seating-plan"><table> where each <td class="seat ..."> is
        "blank" (gap/aisle) or has a status class ("normal" = free, "sold" = taken) plus an area class
        ("standard" = Regular seat, "premium" = Premium seat) and <input data-label="L-4">.
        Table order = on-screen order (screen above the table).
        GET .../abandon releases the booking session afterwards.
    (On 2026-11-19 morning this flow returned GENERAL_ERROR for every showtime; it came back later that day.)
"""
from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup
from curl_cffi import requests as creq

from .common import ProviderError, Seat, SeatMap, Showtime, parse_time_label, split_seat_label

BASE = "https://egy.voxcinemas.com"


class VoxProvider:
    supports_seats = True
    seat_types = ["Regular", "Premium"]

    def __init__(self, key: str, cinema_name: str, name: str, short: str):
        self.key = key
        self.cinema_name = cinema_name
        self.name = name
        self.short = short
        self._local = threading.local()

    @property
    def s(self):
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = creq.Session(impersonate="chrome")
            self._local.session = sess
        return sess

    def _get(self, url, **kw):
        last = None
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=45, **kw)
                if r.status_code == 200:
                    return r
                last = ProviderError(f"HTTP {r.status_code} for {url}")
            except Exception as e:  # curl_cffi raises its own error types
                last = ProviderError(f"{type(e).__name__}: {e}")
                self._local.session = None  # reset session on network errors
            time.sleep(2 * (attempt + 1))
        raise last

    # -- movies -----------------------------------------------------------
    def list_movies(self) -> list[dict]:
        movies: dict[str, str] = {}
        for path in ("/movies/whatson", "/movies/comingsoon"):
            soup = BeautifulSoup(self._get(BASE + path).text, "html.parser")
            for a in soup.select('a[href^="/movies/"], a[href^="' + BASE + '/movies/"]'):
                m = re.search(r"/movies/([a-z0-9-]+)(?:[#?].*)?$", a.get("href", ""))
                if not m or m.group(1) in ("whatson", "comingsoon"):
                    continue
                slug = m.group(1)
                name = ""
                for cand in (a.get("title"), a.get_text(" ", strip=True),
                             (a.find("img") or {}).get("alt") if a.find("img") else None):
                    if cand and not re.search(r"book|showtimes|trailer|more info", cand, re.I) \
                            and len(cand) < 90:
                        name = re.sub(r"^movie poster for\s+", "", cand.strip(), flags=re.I)
                        break
                if name and (slug not in movies or not movies[slug]):
                    movies[slug] = name
                movies.setdefault(slug, "")
        out = [{"slug": s, "name": (n or s.replace("-", " ").title()).upper()} for s, n in movies.items()]
        out.sort(key=lambda m: (0 if "avengers" in m["slug"] else 1, m["name"]))
        return out

    # -- showtimes --------------------------------------------------------
    def _page(self, slug: str, iso: str | None = None) -> BeautifulSoup:
        params = {"d": iso.replace("-", "")} if iso else None
        return BeautifulSoup(self._get(f"{BASE}/movies/{slug}", params=params).text, "html.parser")

    @staticmethod
    def _dates_from(soup: BeautifulSoup) -> list[str]:
        out = []
        nav = soup.select("#showtimes nav.date-filter li")
        known = []
        for li in nav:
            a = li.find("a")
            if a and (m := re.search(r"[?&]d=(\d{8})", a.get("href", ""))):
                known.append(datetime.strptime(m.group(1), "%Y%m%d").date())
            else:
                known.append(None)
        # fill the selected (non-link) day from its neighbours
        for i, d in enumerate(known):
            if d is None:
                if i + 1 < len(known) and known[i + 1]:
                    d = known[i + 1] - timedelta(days=1)
                elif i > 0 and known[i - 1]:
                    d = known[i - 1] + timedelta(days=1)
                else:
                    label = nav[i].get_text(" ", strip=True)
                    d = VoxProvider._guess_date(label)
            if d:
                out.append(d.isoformat())
        return out

    @staticmethod
    def _guess_date(label: str) -> date | None:
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})", label)
        if not m:
            return None
        today = date.today()
        for y in (today.year, today.year + 1):
            try:
                d = datetime.strptime(f"{m.group(1)} {m.group(2)} {y}", "%d %b %Y").date()
            except ValueError:
                return None
            if d >= today - timedelta(days=1):
                return d
        return None

    def list_dates(self, slug: str) -> list[str]:
        return self._dates_from(self._page(slug))

    def list_showtimes(self, slug: str, dates: list[str] | None = None) -> list[Showtime]:
        first = self._page(slug)
        all_dates = self._dates_from(first)
        out: list[Showtime] = []
        for i, iso in enumerate(all_dates):
            if dates and iso not in dates:
                continue
            soup = first if i == 0 else self._page(slug, iso)
            out.extend(self._parse(slug, iso, soup))
        return out

    def _parse(self, slug, iso, soup) -> list[Showtime]:
        res = []
        sec = soup.select_one("#showtimes")
        if not sec:
            return res
        for h3 in sec.select("h3"):
            if h3.get_text(strip=True).lower() != self.cinema_name.lower():
                continue
            ol = h3.find_next_sibling("ol")
            if not ol:
                continue
            for exp_li in ol.find_all("li", recursive=False):
                strong = exp_li.find("strong")
                exp = strong.get_text(strip=True) if strong else "Standard"
                for li in exp_li.select("ol > li"):
                    el = li.find(class_="showtime")
                    if not el:
                        continue
                    tl = el.get_text(strip=True)
                    try:
                        t24 = parse_time_label(tl)
                    except ValueError:
                        continue
                    sid = li.get("data-id") or el.get("data-id")
                    bookable = el.name == "a" and "unavailable" not in (el.get("class") or [])
                    res.append(Showtime(
                        cinema=self.key, movie_slug=slug, date=iso, time=t24, time_label=tl,
                        experience=exp, showtime_id=sid, bookable=bookable,
                        booking_url=f"{BASE}/booking/{sid}" if bookable and sid else
                        f"{BASE}/movies/{slug}?d={iso.replace('-', '')}#showtimes"))
        return res

    # -- seats ------------------------------------------------------------
    AREA_NAMES = {"premium": "Premium", "standard": "Regular"}

    def seat_map(self, st: Showtime) -> SeatMap | None:
        if not st.showtime_id:
            return None
        sess = creq.Session(impersonate="chrome")  # one booking session per read
        try:
            def follow(resp):
                for _ in range(40):
                    path = resp.url.split("?")[0].split("#")[0]
                    if "/error/" in path:
                        raise ProviderError("VOX booking error page (" + path.rsplit("/", 1)[-1] + ")")
                    if not path.endswith("/processing"):
                        return resp
                    data = sess.get(path + "?json=1", timeout=45).json().get("data") or {}
                    if data.get("error"):
                        raise ProviderError(f"VOX booking error: {data['error']}")
                    if data.get("url"):
                        resp = sess.get(BASE + data["url"], timeout=45)
                        continue
                    time.sleep(1.5)
                raise ProviderError("VOX booking flow timed out")

            first = follow(sess.get(f"{BASE}/booking/{st.showtime_id}", timeout=45))
            m = re.search(r"(/booking/[^/?#]+)", first.url)
            if not m:
                raise ProviderError(f"Unexpected VOX booking URL {first.url}")
            booking = m.group(1)
            page = follow(sess.get(BASE + booking + "/seats/fetch", timeout=45))
            seats = self._parse_seats(page.text)
            try:
                sess.get(BASE + booking + "/abandon", timeout=20, allow_redirects=False)
            except Exception:
                pass
            if not seats:
                raise ProviderError("VOX seat map was empty (page layout may have changed)")
            return SeatMap(seats=seats)
        finally:
            try:
                sess.close()
            except Exception:
                pass

    @classmethod
    def _parse_seats(cls, html: str) -> list[Seat]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select(".seating-plan table tbody tr")
        seats = []
        n_rows = len(rows)
        for ri, tr in enumerate(rows):
            cells = tr.find_all("td")
            n_cols = len(cells)
            for ci, td in enumerate(cells):
                cls_ = set(td.get("class") or [])
                if "seat" not in cls_ or "blank" in cls_:
                    continue
                inp = td.find("input")
                label = (inp.get("data-label") if inp else "") or td.get_text(strip=True)
                if not label:
                    continue
                row, num = split_seat_label(label)
                area = next((cls.AREA_NAMES[a] for a in cls.AREA_NAMES if a in cls_), "")
                free = "normal" in cls_ and "sold" not in cls_ and not (inp and inp.has_attr("disabled"))
                # grid indices are reversed so the UI (which draws highest first) keeps VOX's own order
                seats.append(Seat(label=f"{row}{num}", row=row, number=num, grid_row=n_rows - ri,
                                  grid_col=n_cols - ci, free=free, seat_type=area))
        return seats
