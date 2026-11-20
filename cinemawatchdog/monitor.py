"""Monitor engine: evaluates monitors against live showtimes/seat maps and fires alerts."""
from __future__ import annotations

import logging
import random
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .common import Seat, SeatMap, Showtime
from .notifier import send_alert_email
from .providers import PROVIDERS
from .store import Store

log = logging.getLogger("watchdog")


# --------------------------------------------------------------------------- matching
def showtime_start(st: Showtime) -> datetime:
    d = datetime.strptime(f"{st.date} {st.time}", "%Y-%m-%d %H:%M")
    if d.hour < 6:  # after-midnight shows belong to the previous business day
        d += timedelta(days=1)
    return d


def night_minutes(hhmm: str) -> int:
    """Minutes since 06:00-based "cinema night": 01:30 counts as after 23:00 of the same night."""
    h, m = map(int, hhmm.split(":"))
    return (h + 24 if h < 6 else h) * 60 + m


def in_time_range(t: str, frm: str | None, to: str | None) -> bool:
    """Is show time t inside [frm, to]? Either end may be empty. A window that crosses
    midnight (e.g. 21:00 to 01:00) works because times are compared on the cinema night."""
    if not frm and not to:
        return True
    k = night_minutes(t)
    lo = night_minutes(frm) if frm else night_minutes("06:00")
    hi = night_minutes(to) if to else night_minutes("05:59")
    return lo <= k <= hi if lo <= hi else (k >= lo or k <= hi)


def passes_showtime_filters(mon: dict, st: Showtime) -> bool:
    if mon.get("dates") and st.date not in mon["dates"]:
        return False
    if mon.get("time_from") or mon.get("time_to"):
        if not in_time_range(st.time, mon.get("time_from"), mon.get("time_to")):
            return False
    elif mon.get("times") and st.time not in mon["times"]:
        return False
    if mon.get("experiences") and st.experience not in mon["experiences"]:
        return False
    if showtime_start(st) < datetime.now() - timedelta(minutes=5):
        return False
    return True


def candidate_seats(mon: dict, sm: SeatMap) -> list[Seat]:
    rows = {r.upper() for r in mon.get("rows") or []}
    specific = {s.upper().replace(" ", "") for s in mon.get("specific_seats") or []}
    types = set(mon.get("seat_types") or [])
    out = []
    for s in sm.free_seats:
        if rows and s.row.upper() not in rows:
            continue
        if specific and s.label.upper() not in specific:
            continue
        if types and s.seat_type not in types:
            continue
        out.append(s)
    return out


def find_seat_groups(seats: list[Seat], n: int, together: bool,
                     max_groups: int = 1, min_group: int = 1) -> list[list[Seat]]:
    """Return seat groups satisfying the request (best first). Empty list = no match.

    together=True, max_groups=1: one unbroken run of >= n seats (returns every such run).
    together=True, max_groups=k>1: if no single run fits, the party may be split over up to k runs,
        each with at least `min_group` free seats, whose sizes add up to >= n (fewest groups wins).
    """
    n = max(1, int(n or 1))
    max_groups = max(1, int(max_groups or 1))
    min_group = max(1, min(int(min_group or 1), n))
    if not together or n == 1:
        if len(seats) >= n:
            return [sorted(seats, key=lambda s: (s.grid_row, s.grid_col))]
        return []
    runs = seat_runs(seats)
    whole = [r for r in runs if len(r) >= n]
    if whole:
        return whole
    if max_groups == 1:
        return []
    picked, total = [], 0
    for r in runs:  # largest first
        if len(r) < min_group:
            break
        picked.append(r)
        total += len(r)
        if total >= n:
            return picked
        if len(picked) == max_groups:
            break
    return []


def seat_runs(seats: list[Seat]) -> list[list[Seat]]:
    """Unbroken runs of seats in the same physical row (aisles/gaps break a run), largest first."""
    by_row: dict[int, list[Seat]] = {}
    for s in seats:
        by_row.setdefault(s.grid_row, []).append(s)
    runs = []
    for lst in by_row.values():
        lst.sort(key=lambda s: s.grid_col)
        run = [lst[0]]
        for s in lst[1:]:
            if s.grid_col == run[-1].grid_col + 1:
                run.append(s)
            else:
                runs.append(run)
                run = [s]
        runs.append(run)
    runs.sort(key=lambda g: (-len(g), g[0].grid_row, g[0].grid_col))
    return runs


def describe_groups(groups: list[list[Seat]], together: bool, limit=24) -> list[str]:
    labels = []
    if together:
        for g in groups:
            labels.append(", ".join(s.label for s in sorted(g, key=lambda s: int(s.number or 0))))
    else:
        for g in groups:
            labels.extend(s.label for s in g)
    return labels[:limit]


# --------------------------------------------------------------------------- engine
class Engine:
    def __init__(self, store: Store):
        self.store = store
        self.events = deque(maxlen=300)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.cycle_running = False
        self.last_cycle_at: str | None = None
        self.next_cycle_at: str | None = None
        self._thread: threading.Thread | None = None
        self._seat_outage: set[str] = set()  # providers whose seat maps are currently unreadable

    # ---- logging
    def event(self, level: str, msg: str):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.events.appendleft({"at": stamp, "level": level, "msg": msg})
        getattr(log, "warning" if level == "warn" else level if level in ("info", "error") else "info")(msg)

    # ---- lifecycle
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="watchdog-loop", daemon=True)
        self._thread.start()
        self.event("info", "Monitor loop started")

    def trigger(self):
        self._wake.set()

    def _loop(self):
        time.sleep(2)
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception as e:  # never die
                self.event("error", f"Cycle crashed: {e}")
                traceback.print_exc()
            interval = max(30, int(self.store.settings().get("interval_seconds", 120)))
            wait = interval * random.uniform(0.85, 1.15)
            self.next_cycle_at = (datetime.now() + timedelta(seconds=wait)).strftime("%H:%M:%S")
            self._wake.wait(wait)
            self._wake.clear()

    # ---- one pass over all active monitors
    def run_cycle(self, only_id: str | None = None):
        with self._lock:
            self.cycle_running = True
            try:
                monitors = [m for m in self.store.monitors()
                            if m.get("active", True) and (only_id is None or m["id"] == only_id)]
                if not monitors:
                    return
                # group by (cinema, movie) so each movie page is fetched once per cycle
                groups: dict[tuple, list[dict]] = {}
                for m in monitors:
                    groups.setdefault((m["cinema"], m["movie_slug"]), []).append(m)
                seat_cache: dict[str, SeatMap | Exception | None] = {}
                for (cinema, slug), mons in groups.items():
                    self._run_group(cinema, slug, mons, seat_cache)
                self.last_cycle_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            finally:
                self.cycle_running = False

    def _run_group(self, cinema, slug, mons, seat_cache):
        prov = PROVIDERS.get(cinema)
        if not prov:
            return
        dates = None
        if all(m.get("dates") for m in mons):
            dates = sorted({d for m in mons for d in m["dates"]})
        try:
            showtimes = prov.list_showtimes(slug, dates)
        except Exception as e:
            for m in mons:
                self._save_state(m, error=f"Could not load showtimes: {e}")
            self.event("error", f"{prov.short}: failed to load showtimes for {slug}: {e}")
            return

        # seat maps needed (bookable + filtered) – fetch in parallel, politely
        need: dict[str, Showtime] = {}
        if prov.supports_seats:
            for m in mons:
                for st in showtimes:
                    if st.bookable and st.showtime_id and passes_showtime_filters(m, st):
                        need.setdefault(st.showtime_id, st)
        todo = [st for sid, st in need.items() if sid not in seat_cache]
        if todo:
            def fetch(st):
                try:
                    time.sleep(random.uniform(0, 0.6))
                    return st.showtime_id, prov.seat_map(st)
                except Exception as e:
                    return st.showtime_id, e
            with ThreadPoolExecutor(max_workers=4) as ex:
                for sid, res in ex.map(fetch, todo):
                    seat_cache[sid] = res

        # If every seat map failed, the site's booking flow is probably down. Alerts are only ever
        # sent for real free seats, so nothing is emailed until seat maps can be read again.
        results = [seat_cache.get(sid) for sid in need]
        outage = len(results) >= 3 and all(isinstance(r, Exception) for r in results)
        if outage != (prov.key in self._seat_outage):
            if outage:
                self._seat_outage.add(prov.key)
                self.event("warn", f"{prov.short}: seat maps can't be read right now ({results[0]}). "
                                   "No alerts until they work again; checking continues.")
            else:
                self._seat_outage.discard(prov.key)
                self.event("info", f"{prov.short}: seat maps are readable again")

        for m in mons:
            self._evaluate(prov, m, showtimes, seat_cache)

    def _evaluate(self, prov, mon, showtimes, seat_cache):
        n = int(mon.get("seats_needed") or 1)
        together = bool(mon.get("together"))
        matches: dict[str, dict] = {}
        considered = 0
        soldout = 0
        errors = []
        state = mon.get("state") or {}
        prev = set(state.get("matching_keys") or [])
        prev_info = {m.get("key"): m for m in state.get("matches") or []}
        for st in showtimes:
            if not passes_showtime_filters(mon, st):
                continue
            considered += 1
            if not st.bookable:
                soldout += 1
                continue
            info = {"date": st.date, "time": st.time, "time_label": st.time_label,
                    "experience": st.experience, "url": st.booking_url, "seats": [],
                    "free_total": None, "seat_level": prov.supports_seats}
            if prov.supports_seats:
                sm = seat_cache.get(st.showtime_id)
                if isinstance(sm, Exception):
                    errors.append(f"{st.date} {st.time_label}: {sm}")
                    if st.key in prev and prev_info.get(st.key, {}).get("seat_level"):
                        # transient error: keep the previous seat match so we don't re-alert later
                        matches[st.key] = {k: v for k, v in prev_info[st.key].items() if k != "key"}
                    continue
                if sm is None:
                    continue
                cands = candidate_seats(mon, sm)
                grps = find_seat_groups(cands, n, together, mon.get("max_groups", 1),
                                        mon.get("min_group", 1))
                if not grps:
                    continue
                info["seats"] = describe_groups(grps, together)
                info["split"] = together and n > 1 and all(len(g) < n for g in grps)
                info["free_total"] = len(sm.free_seats)
                info["matching_total"] = len(cands)
            matches[st.key] = info

        def order(k):
            v = matches[k]
            h, mi = map(int, v["time"].split(":"))
            return (v["date"], (h + 24 if h < 6 else h) * 60 + mi, v["experience"])
        matches = {k: matches[k] for k in sorted(matches, key=order)}
        new_keys = [k for k in matches if k not in prev]
        summary = (f"{len(matches)} matching / {considered} showtimes checked"
                   + (f" ({soldout} sold out)" if soldout else ""))
        error = None
        if errors:
            error = (f"Couldn't read the seat map for {len(errors)} of {considered - soldout} bookable "
                     f"showtime(s), so their seats aren't being checked right now. First error: {errors[0]}")
        self._save_state(mon, error=error, summary=summary,
                         matching_keys=list(matches.keys()),
                         matches=[{**v, "key": k} for k, v in matches.items()])

        if new_keys:
            new = [{**matches[k], "key": k} for k in new_keys]
            self.event("info", f"ALERT {prov.short} · {mon['movie_name']}: "
                               f"{len(new)} showtime(s) now available")
            try:
                sent_to = send_alert_email(self.store.settings(), prov, mon, new)
                self.event("info", f"Email sent to {', '.join(sent_to)}")
                emailed = True
            except Exception as e:
                self.event("error", f"Email failed (will retry next check): {e}")
                # forget these keys so the alert is retried on the next cycle
                st = dict((self.store.get_monitor(mon["id"]) or {}).get("state") or {})
                st["matching_keys"] = [k for k in st.get("matching_keys", []) if k not in new_keys]
                self.store.update_monitor_state(mon["id"], st)
                return
            self.store.add_alert({
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "monitor_id": mon["id"], "cinema": prov.name, "movie": mon["movie_name"],
                "showtimes": new, "emailed": emailed})
        elif prev and not matches:
            self.event("info", f"{prov.short} · {mon['movie_name']}: previously available seats are gone")

    def _save_state(self, mon, **kw):
        st = dict(mon.get("state") or {})
        st["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for k, v in kw.items():
            st[k] = v
        self.store.update_monitor_state(mon["id"], st)
