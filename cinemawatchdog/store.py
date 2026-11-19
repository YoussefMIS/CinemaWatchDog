"""Tiny JSON-file persistence (monitors, settings, alert history)."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

DEFAULT_SETTINGS = {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
    "smtp_user": "",
    "smtp_password": "",
    "recipients": [],
    "interval_seconds": 120,
}


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mon_path = self.dir / "monitors.json"
        self._set_path = self.dir / "settings.json"
        self._alert_path = self.dir / "alerts.json"

    # ---- io
    def _read(self, path: Path, default):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except json.JSONDecodeError:
            return default

    def _write(self, path: Path, data):
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    # ---- settings
    def settings(self) -> dict:
        with self._lock:
            s = dict(DEFAULT_SETTINGS)
            s.update(self._read(self._set_path, {}))
            # environment variables win (handy for not storing the password on disk)
            if os.environ.get("CWD_SMTP_USER"):
                s["smtp_user"] = os.environ["CWD_SMTP_USER"]
            if os.environ.get("CWD_SMTP_PASSWORD"):
                s["smtp_password"] = os.environ["CWD_SMTP_PASSWORD"]
            return s

    def save_settings(self, patch: dict) -> dict:
        with self._lock:
            cur = self._read(self._set_path, {})
            for k in DEFAULT_SETTINGS:
                if k in patch:
                    if k == "smtp_password" and not patch[k]:
                        continue  # blank = keep existing
                    cur[k] = patch[k]
            self._write(self._set_path, cur)
            return self.settings()

    # ---- monitors
    def monitors(self) -> list[dict]:
        with self._lock:
            return self._read(self._mon_path, [])

    def get_monitor(self, mid: str) -> dict | None:
        return next((m for m in self.monitors() if m["id"] == mid), None)

    def add_monitor(self, mon: dict) -> dict:
        with self._lock:
            mons = self.monitors()
            mon = dict(mon)
            mon["id"] = uuid.uuid4().hex[:10]
            mon["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mon.setdefault("active", True)
            mon["state"] = {}
            mons.append(mon)
            self._write(self._mon_path, mons)
            return mon

    def update_monitor(self, mid: str, patch: dict) -> dict | None:
        with self._lock:
            mons = self.monitors()
            for m in mons:
                if m["id"] == mid:
                    m.update({k: v for k, v in patch.items() if k not in ("id", "state")})
                    if patch.get("reset_state"):
                        m["state"] = {}
                    m.pop("reset_state", None)
                    self._write(self._mon_path, mons)
                    return m
            return None

    def update_monitor_state(self, mid: str, state: dict):
        with self._lock:
            mons = self.monitors()
            for m in mons:
                if m["id"] == mid:
                    m["state"] = state
            self._write(self._mon_path, mons)

    def delete_monitor(self, mid: str) -> bool:
        with self._lock:
            mons = self.monitors()
            keep = [m for m in mons if m["id"] != mid]
            self._write(self._mon_path, keep)
            return len(keep) != len(mons)

    # ---- alerts
    def alerts(self) -> list[dict]:
        with self._lock:
            return self._read(self._alert_path, [])

    def add_alert(self, alert: dict):
        with self._lock:
            al = self.alerts()
            al.insert(0, alert)
            self._write(self._alert_path, al[:200])
