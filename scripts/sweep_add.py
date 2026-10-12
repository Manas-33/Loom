#!/usr/bin/env python3
"""
Add what a LinkedIn or Handshake sweep found as candidates for the description check.

The sweep (the `sweep` skill: Codex or Claude in the owner's own Chrome, only
when the owner starts it) writes one JSON object per posting to a .jsonl file:

  source        linkedin | handshake
  url           the posting's page on that site
  company, title, location
  description   the description text, copied word for word
  apply_url     the real application link on the company's site ("" if none)
  easy_apply    true when LinkedIn only offers Easy Apply
  posted        "2026-09-29" or "3 days ago" ("" if not shown)

Nothing in that file is trusted. For each row:
  1. It must name its site and link to it. Then the board check's rules:
     location (US or remote-US; unclear is kept), title (clear titles up to 45
     days old, plain ones 14), TikTok and ByteDance skipped.
  2. A job already in the inbox just gains "linkedin" or "handshake" in
     found_via, which moves it to the top. Jobs already decided, or already in
     your sheet, are skipped.
  3. When the apply link is a Greenhouse, Ashby, Lever or Workday posting, the
     description comes from that board instead of the copied text, and a board
     missing from data/boards.json is checked and added to it.
  4. apply_via says how to apply: the board, easy-apply (LinkedIn only),
     handshake (no outside link) or other.
  5. Candidates go to data/candidates/<date>-sweep.jsonl. check_descriptions.py
     reads that with the other candidate files and sends what passes to the inbox.

Usage (from repo root):
  python scripts/sweep_add.py data/sweeps/2026-09-30-linkedin.jsonl
  python scripts/sweep_add.py FILE --dry-run   # print what would happen, save nothing
  python scripts/sweep_add.py FILE --check     # then run the description check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_job import InvalidJob, Store, apply_via_from_url, find_duplicate, job_id_from_url, normalize  # noqa: E402
from boards import board_from_url, probe  # noqa: E402
from build_boards import load_boards, merge, save_boards  # noqa: E402
from check_boards import MAX_AGE_DAYS, open_db  # noqa: E402
from check_simplify import fetch_details  # noqa: E402
from inbox import Inbox  # noqa: E402
from job_filters import SKIP_COMPANIES, location_class, title_class  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = REPO_ROOT / "data" / "candidates"
SITES = {"linkedin": "linkedin.com", "handshake": "joinhandshake.com"}
_AGO = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s+ago", re.I)
_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def on_site(url: str, domain: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == domain or host.endswith("." + domain)


def outside_link(url: str) -> str:
    """The application link if it leaves LinkedIn and Handshake, else "". Their redirect links are unwrapped."""
    for _ in range(2):
        if not re.match(r"https?://", url) or not any(on_site(url, domain) for domain in SITES.values()):
            break
        url = (parse_qs(urlparse(url).query).get("url") or [""])[0].strip()
    return url if re.match(r"https?://", url) else ""


def posted_days(posted: str, today: date) -> int | None:
    posted = str(posted or "").strip().lower()
    try:
        return max(0, (today - date.fromisoformat(posted[:10])).days)
    except ValueError:
        pass
    if re.search(r"just now|today", posted):
        return 0
    if "yesterday" in posted:
        return 1
    m = _AGO.search(posted)
    return int(m[1]) * _DAYS[m[2]] if m else None


def to_record(row, today: date) -> dict:
    """One sweep row as a candidate record, or InvalidJob."""
    if not isinstance(row, dict):
        raise InvalidJob("row isn't a JSON object")
    text = lambda key: str(row.get(key) or "").strip()  # noqa: E731
    source, url = text("source").lower(), text("url")
    if source not in SITES:
        raise InvalidJob("source must be linkedin or handshake")
    if not on_site(url, SITES[source]):
        raise InvalidJob(f"url isn't a {source} link")
    apply_url = outside_link(text("apply_url"))
    if apply_url:
        apply_via = apply_via_from_url(apply_url)
    else:
        apply_via = "handshake" if source == "handshake" else "easy-apply" if row.get("easy_apply") is True else ""
    days = posted_days(text("posted"), today)
    job_id = job_id_from_url(apply_url) or job_id_from_url(url) \
        or f"{source}:{hashlib.sha1(url.encode()).hexdigest()[:12]}"
    board = board_from_url(apply_url)
    return {
        "company": text("company"),
        "title": text("title"),
        "location": text("location")[:300] or "Not specified",
        "url": url,
        "apply_url": apply_url,
        "description": text("description"),
        "found_via": [source],
        "apply_via": apply_via,
        "job_id": job_id,
        "posted_time": (today - timedelta(days=days)).isoformat() if days is not None else "",
        "flags": [],
        # Fields starting with "_" are pipeline notes; add_job ignores them
        "_board": f"{board[0]}:{board[1]}" if board else source,
        "_title_class": "",
        "_location_class": "",
        "_posted_days": days,
        "_note": "",
    }


def read_rows(path: Path) -> list:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return json.loads(text)
    rows = []
    for line in text.splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append(None)  # counted as invalid
    return rows


def add_boards(records: list[dict], dry_run: bool) -> list[str]:
    """Boards behind the apply links that the company list doesn't have yet: checked once and added."""
    found: dict[str, set[str]] = {}
    for rec in records:
        board = board_from_url(rec["apply_url"])
        if board:
            found.setdefault(board[0], set()).add(board[1])
    data = load_boards()
    new = [(ats, key) for ats, keys in found.items() for key in sorted(keys) if key not in data["boards"].get(ats, {})]
    if not new or dry_run:
        return [f"{ats}:{key}" for ats, key in new]
    merge(data, "sweep", {ats: {key for a, key in new if a == ats} for ats in found})
    for ats, key in new:
        result = probe(ats, key)
        entry = data["boards"][ats][key]
        entry.update(status=result.status, checked=date.today().isoformat())
        if result.jobs is not None:
            entry["jobs"] = result.jobs
        if result.detail:
            entry["detail"] = result.detail
    save_boards(data)
    return [f"{ats}:{key}" for ats, key in new]


def main() -> int:
    parser = argparse.ArgumentParser(description="Add a LinkedIn/Handshake sweep's postings as description-check candidates.")
    parser.add_argument("file", type=Path, help="the sweep's .jsonl file")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen; save nothing")
    parser.add_argument("--check", action="store_true", help="run check_descriptions.py afterwards")
    args = parser.parse_args()

    rows = read_rows(args.file)
    today = date.today()
    db = open_db()
    checked = dict(db.execute("SELECT job_id, decision FROM checked")) if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='checked'").fetchone() else {}
    db.close()
    inbox = Inbox(REPO_ROOT)
    inbox_rows = []
    for entry in inbox._rows():
        try:
            inbox_rows.append(normalize(entry["record"]))
        except InvalidJob:
            continue
    sheet = Store(REPO_ROOT).rows()

    stats: Counter = Counter()
    todo: list[dict] = []
    picked: set[str] = set()
    for row in rows:
        try:
            record = to_record(row, today)
            job = normalize(record)
        except InvalidJob as exc:
            stats[f"invalid: {exc}"] += 1
            continue
        if SKIP_COMPANIES.search(record["company"]):
            stats["TikTok/ByteDance (applications used up)"] += 1
            continue
        lclass = location_class([record["location"]], [], record["title"])
        if lclass == "non-us":
            stats["not in the US"] += 1
            continue
        tclass, why = title_class(record["title"])
        if tclass == "drop":
            stats[f"title: {why}"] += 1
            continue
        if record["_posted_days"] is not None and record["_posted_days"] > MAX_AGE_DAYS[tclass]:
            stats["too old"] += 1
            continue
        record.update(_title_class=tclass, _location_class=lclass)
        if record["job_id"] in picked:
            stats["twice in this sweep"] += 1
            continue
        picked.add(record["job_id"])
        if find_duplicate(job, inbox_rows):  # found before: it gains this source and moves to the top
            if not args.dry_run:
                inbox.add({k: v for k, v in record.items() if not k.startswith("_")})
            stats["already in the inbox"] += 1
            continue
        if record["job_id"] in checked:
            stats[f"already checked ({'passed' if checked[record['job_id']] == 'pass' else 'dropped'})"] += 1
            continue
        if find_duplicate(job, sheet):
            stats["already in your sheet"] += 1
            continue
        todo.append(record)
    inbox.close()

    candidates = []
    for record in todo:
        if record["_board"] not in SITES:  # the board's own text beats what was copied off the listing
            info = fetch_details(record["apply_url"], job_id_from_url(record["apply_url"]) or "")
            if info["locations"] and location_class(info["locations"], info["countries"], record["title"]) == "non-us":
                stats["not in the US (from the posting)"] += 1
                continue
            if info["description"]:
                record.update(description=info["description"], _note=info["note"])
        if not record["description"]:
            record["flags"].append("no-description")
        stats["candidate" + ("" if record["description"] else " (no description)")] += 1
        candidates.append(record)
        if args.dry_run:
            print(f"  {record['_title_class']:9} | {record['company'][:20]:20} | {record['title'][:48]:48} | "
                  f"{record['apply_via'] or '?':10} | {len(record['description']):6} chars")

    boards = add_boards(candidates, args.dry_run)
    out = CANDIDATES_DIR / f"{today.isoformat()}-sweep.jsonl"
    if candidates and not args.dry_run:
        CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
        with open(out, "a", encoding="utf-8") as fh:
            for rec in candidates:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print()
    for key, value in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"  {value:5}  {key}")
    if boards:
        print(f"  {len(boards):5}  new company boards: {', '.join(boards)}")
    via = Counter(rec["apply_via"] for rec in candidates)
    log(f"{len(rows)} postings read, {len(candidates)} candidates"
        + (f" ({via['easy-apply']} Easy Apply, {via['handshake']} Handshake only)" if candidates else "")
        + (" (dry run: nothing saved)" if args.dry_run else f" written to data/candidates/{out.name}" if candidates else ""))
    if args.check and candidates and not args.dry_run:
        return subprocess.call([sys.executable, str(Path(__file__).resolve().parent / "check_descriptions.py")])
    if candidates and not args.dry_run:
        print("Next: python scripts/check_descriptions.py   (or wait for the 8:00 run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
