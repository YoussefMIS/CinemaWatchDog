"""Email alerts over SMTP (Gmail by default, using an App Password)."""
from __future__ import annotations

import html
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage


def _fmt_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%a %d %b %Y")


def _criteria(mon: dict, seat_level: bool = True) -> str:
    parts = []
    if seat_level:
        parts.append(f"{mon.get('seats_needed', 1)} seat(s)" + (" together" if mon.get("together") else ""))
        if mon.get("together") and int(mon.get("max_groups") or 1) > 1:
            parts.append(f"may split into up to {mon['max_groups']} groups of at least "
                         f"{mon.get('min_group') or 1}")
    if mon.get("experiences"):
        parts.append("experience: " + ", ".join(mon["experiences"]))
    if mon.get("rows"):
        parts.append("rows: " + ", ".join(mon["rows"]))
    if mon.get("specific_seats"):
        parts.append("seats: " + ", ".join(mon["specific_seats"]))
    if mon.get("seat_types"):
        parts.append("seat type: " + ", ".join(mon["seat_types"]))
    frm, to = mon.get("time_from"), mon.get("time_to")
    if frm and to:
        parts.append(f"shows between {frm} and {to}")
    elif frm:
        parts.append(f"shows from {frm}")
    elif to:
        parts.append(f"shows until {to}")
    elif mon.get("times"):
        parts.append("times: " + ", ".join(mon["times"]))
    return " · ".join(parts) or "any bookable showtime"


def send_email(settings: dict, subject: str, text: str, html_body: str) -> list[str]:
    user = settings.get("smtp_user")
    pwd = settings.get("smtp_password")
    rcpts = [r.strip() for r in settings.get("recipients") or [] if r.strip()]
    if not user or not pwd:
        raise RuntimeError("SMTP sender email / app password not configured (Settings)")
    if not rcpts:
        raise RuntimeError("No recipients configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Cinema WatchDog <{user}>"
    msg["To"] = ", ".join(rcpts)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    host = settings.get("smtp_host") or "smtp.gmail.com"
    port = int(settings.get("smtp_port") or 465)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, pwd.replace(" ", ""))
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pwd.replace(" ", ""))
            s.send_message(msg)
    return rcpts


def send_alert_email(settings: dict, prov, mon: dict, showtimes: list[dict]) -> list[str]:
    first = showtimes[0]
    subject = (f"🎬 Seats available: {mon['movie_name']} – {prov.short} – "
               f"{_fmt_date(first['date'])} {first['time_label']}"
               + (f" (+{len(showtimes) - 1} more)" if len(showtimes) > 1 else ""))
    lines = [f"Seats just became available at {prov.name}", f"Movie: {mon['movie_name']}",
             f"Your criteria: {_criteria(mon, prov.supports_seats)}", ""]
    rows_html = []
    for st in showtimes:
        seats = ""
        if st.get("seat_level") and st.get("seats"):
            seats = ("Split across these blocks: " if st.get("split") else "Seats: ") + " | ".join(st["seats"])
        elif not st.get("seat_level"):
            seats = "Showtime is bookable again (seat map couldn't be read right now, so check the seats yourself)"
        lines += [f"• {_fmt_date(st['date'])} {st['time_label']} — {st['experience']}",
                  f"  {seats}", f"  Book: {st['url']}", ""]
        rows_html.append(f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #eee"><b>{html.escape(_fmt_date(st['date']))}</b><br>
              {html.escape(st['time_label'])}</td>
          <td style="padding:10px;border-bottom:1px solid #eee">{html.escape(st['experience'])}</td>
          <td style="padding:10px;border-bottom:1px solid #eee;font-size:13px">{html.escape(seats)}</td>
          <td style="padding:10px;border-bottom:1px solid #eee">
              <a href="{html.escape(st['url'])}" style="background:#e50914;color:#fff;padding:8px 14px;
                 border-radius:6px;text-decoration:none;font-weight:bold">Book now</a></td>
        </tr>""")
    lines.append("Hurry — seats go fast. (Sent by Cinema WatchDog running on your PC.)")
    body = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:720px">
      <h2 style="margin:0 0 4px">🎬 Seats available!</h2>
      <p style="margin:0 0 12px;color:#444"><b>{html.escape(mon['movie_name'])}</b> at
         <b>{html.escape(prov.name)}</b><br><span style="color:#777;font-size:13px">Your criteria:
         {html.escape(_criteria(mon, prov.supports_seats))}</span></p>
      <table style="border-collapse:collapse;width:100%">
        <tr style="background:#f5f5f5;text-align:left"><th style="padding:8px">When</th>
          <th style="padding:8px">Experience</th><th style="padding:8px">Seats</th><th></th></tr>
        {''.join(rows_html)}
      </table>
      <p style="color:#999;font-size:12px">Hurry — seats go fast. Sent by Cinema WatchDog running on your PC.</p>
    </div>"""
    return send_email(settings, subject, "\n".join(lines), body)


def send_test_email(settings: dict) -> list[str]:
    return send_email(settings, "✅ Cinema WatchDog test email",
                      "Email alerts are working. You'll get a message like this when seats open up.",
                      "<p>✅ Email alerts are working. You'll get a message like this when seats open up.</p>")
