#!/usr/bin/env python3
"""
Daily check of every company job board for new early-career US jobs.

For each live or closed board in data/boards.json:
  1. Download its job list. Greenhouse/Ashby/Lever send nothing if unchanged
     since the last run; Workday is read newest-first and stops at older jobs.
  2. Filter: location (US or remote-US; unclear is kept) → title (engineering,
     not senior, not intern). Clear new-grad titles and ambiguous ones both pass;
     the description check (a later step) decides the ambiguous ones.
  3. Anything not seen before becomes a candidate. Descriptions are fetched for
     those only, and they're written to data/candidates/<date>.jsonl.

The seen list only grows: a board that fails to load never makes old jobs look
new. Jobs older than 45 days (clear titles) or 14 days (ambiguous) are marked
seen but not written, so the first run doesn't flood you with a backlog.

State lives in data/loom.db (SQLite): board versions, the seen list, and runs.

Usage (from repo root):
  python scripts/check_boards.py                      # the daily run
  python scripts/check_boards.py --ats ashby --limit 50
  python scripts/check_boards.py --workday-full       # weekly: read Workday sites in full
  python scripts/check_boards.py --dry-run            # don't write state or candidates
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import ATS, Posting, fetch_board, fetch_description  # noqa: E402
from build_boards import DATA_DIR, export_csv, load_boards, readable_name, save_boards  # noqa: E402
from job_filters import SKIP_BOARDS, location_class, title_class  # noqa: E402

DB_FILE = DATA_DIR / "loom.db"
CANDIDATES_DIR = DATA_DIR / "candidates"
WORKERS = {"greenhouse": 6, "lever": 8, "ashby": 4, "workday": 8}
DESCRIPTION_WORKERS = 4
MAX_AGE_DAYS = {"clear": 45, "ambiguous": 14}
DEFAULT_BACKLOG_DAYS = 14   # Workday window the first time a site is read


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def open_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS board_state (
            ats TEXT, board TEXT, etag TEXT, last_ok TEXT, last_status TEXT, sorted INTEGER,
            PRIMARY KEY (ats, board));
        CREATE TABLE IF NOT EXISTS seen (
            job_id TEXT PRIMARY KEY, ats TEXT, board TEXT, title TEXT, title_class TEXT,
            location_class TEXT, first_seen TEXT, written INTEGER);
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT, stats TEXT);
    """)
    return db


def is_internship(p: Posting) -> bool:
    return bool(re.search(r"intern|co-?op", p.employment or "", re.I))


def location_text(p: Posting) -> str:
    seen: list[str] = []
    for loc in p.locations:
        loc = " ".join((loc or "").split())
        if loc and not re.fullmatch(r"\d+ Locations", loc, re.I) and loc not in seen:
            seen.append(loc)
    if p.ats == "workday" and len(seen) > 1:
        seen = seen[:-1]  # the last one is the hint taken from the link
    return "; ".join(seen)[:300]


def to_record(p: Posting, tclass: str, lclass: str) -> dict:
    return {
        "company": p.company or readable_name(p.ats, p.board),
        "title": p.title,
        "location": location_text(p) or "Not specified",
        "url": p.url,
        "apply_url": p.apply_url,
        "description": p.description,
        "found_via": [p.ats],
        "apply_via": p.ats,
        "job_id": p.job_id,
        "posted_time": p.posted or (f"{p.posted_days} days ago" if p.posted_days is not None else ""),
        # Fields starting with "_" are pipeline notes; add_job ignores them
        "_board": f"{p.ats}:{p.board}",
        "_title_class": tclass,
        "_location_class": lclass,
        "_employment": p.employment,
        "_posted_days": p.posted_days,
        "_note": p.note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check every job board for new jobs.")
    parser.add_argument("--ats", default=",".join(ATS), help="comma list of sites to check")
    parser.add_argument("--limit", type=int, default=None, help="check at most N boards per site (testing)")
    parser.add_argument("--workday-full", action="store_true", help="read Workday sites in full (weekly)")
    parser.add_argument("--backlog-days", type=int, default=DEFAULT_BACKLOG_DAYS)
    parser.add_argument("--no-cache", action="store_true", help="ignore saved board versions and download everything")
    parser.add_argument("--dry-run", action="store_true", help="don't write state, boards.json or candidates")
    args = parser.parse_args()

    sites = [a.strip() for a in args.ats.split(",") if a.strip() in ATS]
    boards = load_boards()
    db = open_db()
    state = {(a, b): (etag, last_ok, sorted_) for a, b, etag, last_ok, sorted_ in
             db.execute("SELECT ats, board, etag, last_ok, sorted FROM board_state")}
    seen = {row[0] for row in db.execute("SELECT job_id FROM seen")}
    today = date.today()
    started = datetime.now().isoformat(timespec="seconds")

    todo: list[tuple[str, str]] = []
    for ats in sites:
        keys = [k for k, e in boards["boards"].get(ats, {}).items()
                if e["status"] in ("ok", "closed", "error") and f"{ats}:{k}" not in SKIP_BOARDS]
        todo += [(ats, k) for k in sorted(keys)[: args.limit or None]]
    log(f"Checking {len(todo)} boards: " + ", ".join(f"{a} {sum(1 for t in todo if t[0] == a)}" for a in sites))

    def work(ats: str, key: str):
        etag, last_ok, _ = state.get((ats, key), (None, None, None))
        if last_ok:
            window = min(30, max(1, (today - date.fromisoformat(last_ok)).days + 1))
        else:
            window = args.backlog_days
        return fetch_board(ats, key, None if args.no_cache else etag, window, args.workday_full)

    stats: dict[str, Counter] = {ats: Counter() for ats in sites}
    fresh: list[tuple[Posting, str, str]] = []
    seen_rows: list[tuple] = []
    state_rows: list[tuple] = []
    board_changes: dict[tuple[str, str], str] = {}

    pools = {ats: ThreadPoolExecutor(max_workers=WORKERS[ats]) for ats in sites}
    futures = {pools[ats].submit(work, ats, key): (ats, key) for ats, key in todo}
    t0 = time.monotonic()
    try:
        for done, fut in enumerate(as_completed(futures), start=1):
            ats, key = futures[fut]
            result = fut.result()
            s = stats[ats]
            s[result.status] += 1
            entry = boards["boards"][ats][key]
            new_status = {"dead": "dead", "closed": "closed", "error": "error"}.get(result.status, "ok")
            if entry["status"] != new_status:
                board_changes[(ats, key)] = new_status
            if result.status in ("changed", "unchanged"):
                etag, _, sorted_ = state.get((ats, key), (None, None, None))
                state_rows.append((ats, key, result.etag or etag, today.isoformat(), result.status,
                                   None if result.sorted_by_date is None else int(result.sorted_by_date)))
            for p in result.postings or []:
                s["postings"] += 1
                if is_internship(p):
                    continue
                lclass = location_class(p.locations, p.countries, p.title)
                if lclass == "non-us":
                    continue
                s["us or unclear"] += 1
                tclass, _ = title_class(p.title)
                if tclass == "drop":
                    continue
                s["title ok"] += 1
                if p.job_id in seen:
                    continue
                seen.add(p.job_id)
                too_old = p.posted_days is not None and p.posted_days > MAX_AGE_DAYS[tclass]
                s["too old" if too_old else f"new {tclass}"] += 1
                seen_rows.append((p.job_id, ats, key, p.title, tclass, lclass, today.isoformat(), int(not too_old)))
                if not too_old:
                    fresh.append((p, tclass, lclass))
            if done % 2000 == 0:
                log(f"  {done}/{len(todo)} boards, {len(fresh)} new candidates so far")
    finally:
        for pool in pools.values():
            pool.shutdown(wait=True, cancel_futures=True)
    log(f"Boards done in {time.monotonic() - t0:.0f}s. Fetching descriptions for {len(fresh)} candidates…")

    with ThreadPoolExecutor(max_workers=DESCRIPTION_WORKERS) as ex:
        filled = list(ex.map(lambda item: (fetch_description(item[0]), item[1], item[2]), fresh))

    records = []
    for p, tclass, lclass in filled:
        if p.ats == "workday":  # the detail page names the real locations and country
            lclass = location_class(p.locations, p.countries, p.title)
            if lclass == "non-us":
                stats[p.ats]["non-us after detail"] += 1
                continue
        records.append(to_record(p, tclass, lclass))

    finished = datetime.now().isoformat(timespec="seconds")
    summary = {ats: dict(c) for ats, c in stats.items()}
    if not args.dry_run:
        db.executemany("INSERT OR REPLACE INTO board_state VALUES (?,?,?,?,?,?)", state_rows)
        db.executemany("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?,?,?,?)", seen_rows)
        db.execute("INSERT INTO runs (started, finished, stats) VALUES (?,?,?)",
                   (started, finished, json.dumps({"sites": summary, "written": len(records)})))
        db.commit()
        if records:
            CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
            with open(CANDIDATES_DIR / f"{today.isoformat()}.jsonl", "a", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if board_changes:
            for (ats, key), status in board_changes.items():
                boards["boards"][ats][key].update(status=status, checked=today.isoformat())
            save_boards(boards)
            export_csv(boards)
    db.close()

    log("Done." + (" (dry run: nothing saved)" if args.dry_run else ""))
    cols = ["changed", "unchanged", "dead", "closed", "error", "postings", "us or unclear", "title ok",
            "new clear", "new ambiguous", "too old"]
    print(f"{'site':11}" + "".join(f"{c:>15}" for c in cols))
    for ats in sites:
        print(f"{ats:11}" + "".join(f"{stats[ats].get(c, 0):>15}" for c in cols))
    by_class = Counter(r["_title_class"] for r in records)
    print(f"\n{len(records)} candidates written"
          + (f" to data/candidates/{today.isoformat()}.jsonl" if records and not args.dry_run else "")
          + f" ({by_class.get('clear', 0)} clear new-grad titles, {by_class.get('ambiguous', 0)} to check by description)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
