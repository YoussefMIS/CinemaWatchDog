"""Cinema WatchDog – local web app that watches Scene CFC & VOX Almaza for seats."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from cinemawatchdog.common import Showtime
from cinemawatchdog.monitor import Engine
from cinemawatchdog.notifier import send_test_email
from cinemawatchdog.providers import PROVIDERS
from cinemawatchdog.store import Store

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments. Real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip().removeprefix("export ").strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if key and val:
            os.environ.setdefault(key, val)


load_dotenv(ROOT / ".env")
DATA = Path(os.environ.get("CWD_DATA_DIR", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=([logging.StreamHandler(sys.stdout)] if sys.stdout else [])  # pythonw has no console
             + [logging.FileHandler(DATA / "watchdog.log", encoding="utf-8")])
logging.getLogger("werkzeug").setLevel(logging.WARNING)

store = Store(DATA)
engine = Engine(store)
app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")

# small TTL cache so the form stays snappy
_cache: dict = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def err(msg, code=400):
    return jsonify({"error": msg}), code


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/cinemas")
def cinemas():
    return jsonify([{"key": p.key, "name": p.name, "short": p.short,
                     "supports_seats": p.supports_seats,
                     "seat_types": getattr(p, "seat_types", [])} for p in PROVIDERS.values()])


@app.get("/api/movies")
def movies():
    prov = PROVIDERS.get(request.args.get("cinema", ""))
    if not prov:
        return err("unknown cinema")
    try:
        return jsonify(cached(("movies", prov.key), 600, prov.list_movies))
    except Exception as e:
        return err(f"Could not load movies from {prov.short}: {e}", 502)


@app.get("/api/showtimes")
def showtimes():
    prov = PROVIDERS.get(request.args.get("cinema", ""))
    slug = request.args.get("movie", "")
    if not prov or not slug:
        return err("cinema and movie required")
    try:
        sts = cached(("st", prov.key, slug), 60, lambda: prov.list_showtimes(slug))
    except Exception as e:
        return err(f"Could not load showtimes: {e}", 502)
    return jsonify([s.to_dict() for s in sts])


@app.get("/api/hall")
def hall():
    """Seat map of one showtime, used by the seat/row picker."""
    prov = PROVIDERS.get(request.args.get("cinema", ""))
    sid = request.args.get("showtime_id", "")
    if not prov or not sid:
        return err("cinema and showtime_id required")
    if not prov.supports_seats:
        return err(f"{prov.short} does not expose seat maps", 404)
    st = Showtime(cinema=prov.key, movie_slug="", date="", time="", time_label="", experience="",
                  showtime_id=sid, bookable=True, booking_url=None)
    try:
        sm = cached(("hall", prov.key, sid), 60, lambda: prov.seat_map(st))
    except Exception as e:
        return err(f"Could not load seat map: {e}", 502)
    seats = [{"label": s.label, "row": s.row, "number": s.number, "r": s.grid_row,
              "c": s.grid_col, "free": s.free, "type": s.seat_type} for s in sm.seats]
    return jsonify({"seats": seats, "free": len(sm.free_seats), "total": sm.total})


# ---- monitors
FIELDS = ["cinema", "movie_slug", "movie_name", "dates", "times", "experiences", "seats_needed",
          "together", "max_groups", "min_group", "rows", "specific_seats", "seat_types", "active", "label"]


def clean_monitor(body: dict) -> dict:
    m = {k: body.get(k) for k in FIELDS if k in body}
    for k in ("dates", "times", "experiences", "rows", "specific_seats", "seat_types"):
        v = m.get(k) or []
        if isinstance(v, str):
            v = [x for x in v.replace(";", ",").split(",")]
        m[k] = [str(x).strip() for x in v if str(x).strip()]
    m["rows"] = [r.upper() for r in m["rows"]]
    m["specific_seats"] = [s.upper().replace(" ", "") for s in m["specific_seats"]]
    m["seats_needed"] = max(1, min(50, int(m.get("seats_needed") or 1)))
    m["together"] = bool(m.get("together"))
    m["max_groups"] = max(1, min(6, int(m.get("max_groups") or 1))) if m["together"] else 1
    m["min_group"] = max(1, min(m["seats_needed"], int(m.get("min_group") or 1)))
    return m


@app.get("/api/monitors")
def list_monitors():
    return jsonify(store.monitors())


@app.post("/api/monitors")
def create_monitor():
    body = request.get_json(force=True) or {}
    if body.get("cinema") not in PROVIDERS or not body.get("movie_slug"):
        return err("cinema and movie are required")
    mon = store.add_monitor(clean_monitor(body))
    engine.event("info", f"Monitor created: {mon['movie_name']} @ {PROVIDERS[mon['cinema']].short}")
    threading.Thread(target=engine.run_cycle, kwargs={"only_id": mon["id"]}, daemon=True).start()
    return jsonify(mon), 201


@app.put("/api/monitors/<mid>")
def update_monitor(mid):
    body = request.get_json(force=True) or {}
    patch = clean_monitor(body) if "cinema" in body else {k: body[k] for k in ("active", "label") if k in body}
    if "cinema" in body:
        patch["reset_state"] = True
    m = store.update_monitor(mid, patch)
    if not m:
        return err("not found", 404)
    if "cinema" in body:
        engine.event("info", f"Monitor edited: {m['movie_name']} @ {PROVIDERS[m['cinema']].short}")
        if m.get("active", True):
            threading.Thread(target=engine.run_cycle, kwargs={"only_id": mid}, daemon=True).start()
    return jsonify(m)


@app.delete("/api/monitors/<mid>")
def delete_monitor(mid):
    return jsonify({"ok": store.delete_monitor(mid)})


@app.post("/api/monitors/<mid>/check")
def check_now(mid):
    if not store.get_monitor(mid):
        return err("not found", 404)
    engine.run_cycle(only_id=mid)
    return jsonify(store.get_monitor(mid))


# ---- status / settings
@app.get("/api/status")
def status():
    return jsonify({"events": list(engine.events)[:120], "alerts": store.alerts()[:50],
                    "last_cycle_at": engine.last_cycle_at, "next_cycle_at": engine.next_cycle_at,
                    "cycle_running": engine.cycle_running,
                    "interval_seconds": store.settings().get("interval_seconds")})


def public_settings(s):
    s = dict(s)
    s["smtp_password_set"] = bool(s.pop("smtp_password", ""))
    return s


@app.get("/api/settings")
def get_settings():
    return jsonify(public_settings(store.settings()))


@app.post("/api/settings")
def save_settings():
    body = request.get_json(force=True) or {}
    if "recipients" in body and isinstance(body["recipients"], str):
        body["recipients"] = [r.strip() for r in body["recipients"].replace(";", ",").split(",") if r.strip()]
    if "interval_seconds" in body:
        body["interval_seconds"] = max(30, int(body["interval_seconds"] or 120))
    if "smtp_port" in body:
        body["smtp_port"] = int(body["smtp_port"] or 465)
    s = store.save_settings(body)
    engine.event("info", "Settings saved")
    return jsonify(public_settings(s))


@app.post("/api/test-email")
def test_email():
    try:
        to = send_test_email(store.settings())
        engine.event("info", f"Test email sent to {', '.join(to)}")
        return jsonify({"ok": True, "to": to})
    except Exception as e:
        engine.event("error", f"Test email failed: {e}")
        return err(str(e), 500)


def main():
    host = os.environ.get("CWD_HOST", "127.0.0.1")
    port = int(os.environ.get("CWD_PORT", "5000"))
    engine.start()
    print(f"\n  Cinema WatchDog running at http://{'localhost' if host == '127.0.0.1' else host}:{port}\n"
          "  Keep this window open (and the PC awake) for monitoring to continue.\n")
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
