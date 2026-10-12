#!/usr/bin/env python3
"""
The daily email: today's new inbox jobs, grouped by source, sent once the morning run has finished.

This script only builds the email. Claude's scheduled task sends it through
the Gmail connector to the owner's own address, which is fixed in that task and
never read from here. --send is the fallback: smtplib with a Gmail app password
from .env (LOOM_EMAIL_USER, LOOM_EMAIL_APP_PASSWORD), sent to that same account.

A job found by a sweep or SimplifyJobs is listed under that source even if a
board check found it too, like the inbox order. Rejected jobs are left out.
Links open the job in the dashboard (the phone link when phone access is on)
and never trigger an action.

Usage (from repo root):
  python scripts/daily_email.py                     # print today's email
  python scripts/daily_email.py --date 2026-09-29
  python scripts/daily_email.py --json              # {"subject", "body", "html"} for the scheduled task
  python scripts/daily_email.py --send              # fallback: send it with smtplib
"""

from __future__ import annotations

import argparse
import html
import json
import re
import smtplib
import sqlite3
import sys
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phone  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_URL = "http://127.0.0.1:8000"
GROUPS = (("linkedin", "LinkedIn"), ("handshake", "Handshake"), ("simplify", "SimplifyJobs"),
          ("boards", "Company job boards"))
MAX_LISTED = 20   # per source; the rest are a count, so a backlog day stays a short email
MAX_FIELD = 90    # characters of a company, title or location

# The dashboard's light theme and tag labels. Styles are inline because mail clients drop stylesheets.
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
INK, MUTED, LINE, ACCENT, PAGE = "#232538", "#74798c", "#e7e8f0", "#6456d9", "#f5f6fa"
TONES = {  # tag background, text
    "neutral": ("#f5f6fa", "#74798c"), "soft": ("#efedfd", "#6251b9"), "warning": ("#fff5e6", "#98651c"),
    "good": ("#e8f4ec", "#2f7a4b"), "ai-agents": ("#f0edf7", "#78608f"), "mle": ("#eaf0f8", "#52739d"),
    "mobile": ("#f9ede6", "#9a6c4a"),
}
BUCKETS = {"generalist": "Software engineering", "ai-agents": "AI & agents", "mle": "Machine learning", "mobile": "Mobile"}
FLAGS = {"no-sponsorship": "No visa sponsorship", "location-unclear": "Location unclear",
         "no-description": "No description", "amazon-check": "Amazon: check account & referral"}
APPLY_VIA = {"easy-apply": "LinkedIn Easy Apply", "handshake": "Apply on Handshake"}


def clean(text, limit: int = MAX_FIELD) -> str:
    """Job text is untrusted: one line, no control characters, capped."""
    text = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f\u2028\u2029]", " ", str(text or ""))).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def group_of(found_via) -> str:
    return next((key for key, _ in GROUPS[:-1] if key in (found_via or [])), "boards")


def tags_of(record: dict, kept: bool) -> list[tuple[str, str]]:
    """(label, tone) pairs, the same tags the dashboard's cards show."""
    bucket = record.get("suggested_bucket")
    tags = [("Kept", "good")] if kept else []
    if record.get("title_match") == "new-grad":
        tags.append(("New-grad title", "soft"))
    if bucket in BUCKETS:
        tags.append((BUCKETS[bucket], bucket if bucket in TONES else "neutral"))
    if record.get("apply_via") in APPLY_VIA:
        tags.append((APPLY_VIA[record["apply_via"]], "neutral"))
    for flag in record.get("flags") or []:
        tags.append((FLAGS.get(flag) or clean(flag, 30), "warning" if flag in ("no-sponsorship", "amazon-check") else "neutral"))
    return tags


def days_jobs(root: Path, day: str) -> list[dict]:
    db_file = Path(root) / "data" / "loom.db"
    if not db_file.exists():
        return []
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='inbox'").fetchone():
            return []
        rows = db.execute("SELECT job_id, status, slug, record FROM inbox WHERE added_on = ? AND status != 'rejected' "
                          "ORDER BY rowid", (day,)).fetchall()
    finally:
        db.close()
    jobs = []
    for job_id, status, slug, record in rows:
        record = json.loads(record)
        kept = status == "kept"
        jobs.append({"job_id": job_id, "kept": kept, "slug": slug, "group": group_of(record.get("found_via")),
                     "company": clean(record.get("company")), "title": clean(record.get("title")),
                     "location": clean(record.get("location")), "new_grad": record.get("title_match") == "new-grad",
                     "tags": tags_of(record, kept)})
    # New-grad titles first, then by company (the sort is stable)
    jobs.sort(key=lambda j: j["company"].casefold())
    jobs.sort(key=lambda j: not j["new_grad"])
    return jobs


def run_status(root: Path, day: str) -> tuple[str, bool]:
    """How the day's scheduled check ended, from its log (scripts/daily_run.sh), and whether that's good."""
    try:
        log = (Path(root) / "data" / "logs" / f"{day}.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "Daily check: no run logged.", False
    done = re.findall(r"^\[(\d\d:\d\d):\d\d\] === done( with failures)? ===", log, flags=re.M)
    if not done:
        return "Daily check: started, not finished.", False
    return f"Daily check: finished {done[-1][0]}{', with failures' if done[-1][1] else ''}.", not done[-1][1]


LAST_SLOT = 21  # the routine tries hourly until 21:00; from then on it sends whatever the day has


def ready(root: Path, day: str, hour: int) -> tuple[bool, str]:
    """Send once a day, as soon as the morning run has finished (the owner's choice, 2026-09-30)."""
    try:
        if (Path(root) / "data" / ".last-email").read_text(encoding="utf-8").strip() == day:
            return False, "Already sent today."
    except OSError:
        pass
    if not run_status(root, day)[0].startswith("Daily check: finished") and hour < LAST_SLOT:
        return False, "The morning run hasn't finished yet."
    return True, ""


def job_link(job: dict, base: str) -> str:
    if job["kept"] and job["slug"]:
        return f"{base}/#job/{quote(job['slug'], safe='')}"
    return f"{base}/#inbox/{quote(job['job_id'], safe='')}"


def _tag(label: str, tone: str) -> str:
    background, color = TONES[tone]
    return (f'<span style="display:inline-block;margin:7px 6px 0 0;padding:2px 8px;border-radius:5px;font-size:11px;'
            f'line-height:16px;background:{background};color:{color}">{html.escape(label)}</span>')


def _heading(label: str, count: int) -> str:
    background, color = TONES["soft" if count else "neutral"]
    return (f'<span style="display:inline-block;margin-right:18px;font-size:11px;line-height:20px;font-weight:700;'
            f'letter-spacing:.08em;text-transform:uppercase;color:{MUTED}">{label}<span style="margin-left:8px;'
            f'padding:2px 8px;border-radius:9px;letter-spacing:0;background:{background};color:{color}">{count}</span></span>')


def _section(label: str, group: list[dict], base: str) -> str:
    rows = [f'<tr><td style="padding:24px 0 9px">{_heading(label, len(group))}</td></tr>']
    for job in group[:MAX_LISTED]:
        place = " · ".join(html.escape(part) for part in (job["location"],) if part)
        rows.append(
            f'<tr><td style="padding:12px 0 13px;border-top:1px solid {LINE}">'
            f'<a href="{html.escape(job_link(job, base))}" style="font-size:15px;line-height:21px;font-weight:600;'
            f'color:{INK};text-decoration:none">{html.escape(job["title"])}</a>'
            f'<div style="font-size:13px;line-height:19px;color:{MUTED}"><span style="color:{INK}">'
            f'{html.escape(job["company"])}</span>{" · " + place if place else ""}</div>'
            f'{"".join(_tag(*tag) for tag in job["tags"])}</td></tr>')
    if len(group) > MAX_LISTED:
        rows.append(f'<tr><td style="padding:12px 0;border-top:1px solid {LINE};font-size:13px;color:{MUTED}">'
                    f'and {len(group) - MAX_LISTED} more in the dashboard</td></tr>')
    return "".join(rows)


def build_html(jobs: list[dict], when: str, base: str, status: tuple[str, bool]) -> str:
    headline = f"{len(jobs)} new job{'' if len(jobs) == 1 else 's'}" if jobs else "No new jobs"
    note, good = status
    groups = [(label, [j for j in jobs if j["group"] == key]) for key, label in GROUPS]
    return (
        f'<div style="background:{PAGE};padding:24px 12px;font-family:{FONT};color:{INK}">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" align="center" width="100%" style="max-width:600px;'
        f'margin:0 auto;background:#ffffff;border:1px solid {LINE};border-radius:14px"><tr><td style="padding:26px 28px">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>'
        f'<td style="font-size:19px;font-weight:700;letter-spacing:-.4px">loom<span style="color:{ACCENT}">.</span></td>'
        f'<td align="right" style="font-size:12px;color:{MUTED}">{when}</td></tr></table>'
        f'<div style="margin-top:20px;font-size:27px;line-height:33px;font-weight:600;letter-spacing:-.5px">{headline}</div>'
        f'<div style="font-size:14px;line-height:21px;color:{MUTED}">'
        f'{"added to your inbox today" if jobs else "Nothing reached your inbox today."}</div>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">'
        + "".join(_section(label, group, base) for label, group in groups if group)
        # Sources with nothing new share one line, so the jobs come first
        + f'<tr><td style="padding:24px 0 0">{"".join(_heading(label, 0) for label, group in groups if not group)}</td></tr>'
        + f'</table><div style="margin-top:26px;padding-top:22px;border-top:1px solid {LINE}">'
        f'<a href="{html.escape(base)}/#inbox" style="display:inline-block;padding:10px 18px;border-radius:9px;'
        f'background:{ACCENT};color:#ffffff;font-size:14px;font-weight:600;text-decoration:none">Open the inbox</a>'
        f'<div style="margin-top:14px;font-size:12px;line-height:18px;color:{MUTED}">'
        f'<span style="color:{"#2f7a4b" if good else "#c4872f"}">&#9679;</span> {html.escape(note)}</div>'
        f'</div></td></tr></table></div>')


def build(root: Path = REPO_ROOT, day: str | None = None) -> dict:
    day = day or date.today().isoformat()
    base = phone.load(root).get("url") or LOCAL_URL
    jobs = days_jobs(root, day)
    when = date.fromisoformat(day).strftime("%a, %b %-d")
    count = f"{len(jobs)} new job{'' if len(jobs) == 1 else 's'}"
    status = run_status(root, day)
    text = [f"{count} in your inbox, {when}.", ""]
    for key, label in GROUPS:
        group = [j for j in jobs if j["group"] == key]
        text.append(f"{label} ({len(group)})")
        for job in group[:MAX_LISTED]:
            tail = "".join(f" · {part}" for part in (job["location"], "kept" if job["kept"] else "") if part)
            text += [f"- {job['company']}: {job['title']}{tail}", f"  {job_link(job, base)}"]
        if len(group) > MAX_LISTED:
            text.append(f"- and {len(group) - MAX_LISTED} more in the dashboard")
        text.append("")
    text += [f"Inbox: {base}/#inbox", status[0]]
    return {"date": day, "count": len(jobs), "subject": f"Loom: {count}, {when}",
            "body": "\n".join(text) + "\n", "html": build_html(jobs, when, base, status)}


def read_env(root: Path) -> dict:
    values = {}
    try:
        lines = (Path(root) / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            values[key.strip()] = value.strip().strip("'\"")
    return values


def send(mail: dict, root: Path = REPO_ROOT) -> str:
    """The fallback sender. The only recipient is the sending account itself."""
    env = read_env(root)
    user, password = env.get("LOOM_EMAIL_USER"), env.get("LOOM_EMAIL_APP_PASSWORD")
    if not user or not password:
        raise SystemExit("Set LOOM_EMAIL_USER and LOOM_EMAIL_APP_PASSWORD (a Gmail app password) in .env first.")
    message = EmailMessage()
    message["From"] = message["To"] = user
    message["Subject"] = mail["subject"]
    message.set_content(mail["body"])
    message.add_alternative(mail["html"], subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(message)
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the daily email of today's new inbox jobs.")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--json", action="store_true",
                        help="for the routine: the email as JSON once today's run has finished, else {send: false}")
    parser.add_argument("--send", action="store_true", help="send with smtplib and the app password in .env")
    args = parser.parse_args()
    mail = build(day=args.date)
    if args.send:
        print(f"Sent to {send(mail)}: {mail['subject']}")
    elif args.json:
        go, why = (True, "") if args.date else ready(REPO_ROOT, mail["date"], datetime.now().hour)
        if not go:
            print(json.dumps({"send": False, "why": why}))
            return 0
        if not args.date:
            (REPO_ROOT / "data" / ".last-email").write_text(mail["date"] + "\n", encoding="utf-8")
        print(json.dumps({"send": True, **{k: mail[k] for k in ("subject", "body", "html")}}, ensure_ascii=False))
    else:
        print(f"Subject: {mail['subject']}\n\n{mail['body']}", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
