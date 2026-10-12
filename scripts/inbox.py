#!/usr/bin/env python3
"""
The inbox: jobs the automation found, waiting for you to keep or reject.

Nothing here touches jobs.xlsx until you keep a job. Keeping one adds it
through add_job with status "Not Applied"; rejecting just marks it. The inbox
lives in data/loom.db (table `inbox`) and checks for duplicates against both
your sheet and itself, so the same job found twice shows up once.

Usage (from repo root):
  python scripts/inbox.py list                  # jobs waiting for you
  python scripts/inbox.py keep ashby:1234 …     # add to jobs.xlsx
  python scripts/inbox.py reject ashby:1234 …
  python scripts/inbox.py page                  # write data/inbox.html to browse
  python scripts/inbox.py dedupe [--dry-run]    # reject pending jobs already in the sheet or inbox
  python scripts/inbox.py stats
"""

from __future__ import annotations

import argparse
import contextlib
import html
import json
import sqlite3
import sys
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_job import InvalidJob, Store, find_duplicate, normalize, record_slug  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = REPO_ROOT / "data" / "loom.db"
PAGE_FILE = REPO_ROOT / "data" / "inbox.html"
KEPT_STATUS = "Not Applied"


class Inbox:
    def __init__(self, root: Path = REPO_ROOT):
        self.root = Path(root)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "data" / "loom.db", timeout=30)
        self.db.execute("""CREATE TABLE IF NOT EXISTS inbox (
            job_id TEXT PRIMARY KEY, added_on TEXT, status TEXT, decided_on TEXT,
            record TEXT, reason TEXT, slug TEXT)""")
        self.db.execute("CREATE TABLE IF NOT EXISTS inbox_undo (job_id TEXT PRIMARY KEY, token TEXT, snapshot TEXT)")
        self.db.commit()
        self.store = Store(self.root)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _rows(self, status: str | None = None) -> list[dict]:
        q = "SELECT job_id, added_on, status, decided_on, record, reason, slug FROM inbox"
        rows = self.db.execute(q + (" WHERE status = ?" if status else "") + " ORDER BY added_on, rowid",
                               (status,) if status else ()).fetchall()
        return [dict(job_id=r[0], added_on=r[1], status=r[2], decided_on=r[3], record=json.loads(r[4]),
                     reason=r[5], slug=r[6]) for r in rows]

    def add(self, record: dict, reason: str = "") -> str:
        """added | duplicate | in sheet | invalid"""
        try:
            job = normalize(record)
        except InvalidJob:
            return "invalid"
        if find_duplicate(job, self.store.rows()):
            return "in sheet"
        existing = self._rows()
        dup = find_duplicate(job, [normalize(e["record"]) for e in existing])
        if dup:
            entry = existing[dup[0]]
            merged = entry["record"]
            new_sources = [s for s in job["found_via"] if s not in merged.get("found_via", [])]
            if new_sources:
                merged["found_via"] = list(merged.get("found_via", [])) + new_sources
                self.db.execute("UPDATE inbox SET record = ? WHERE job_id = ?", (json.dumps(merged), entry["job_id"]))
                self.db.commit()
            return "duplicate"
        key = job["job_id"].split(",")[0].strip() or f"{job['company']}|{job['title']}".lower()
        self.db.execute("INSERT OR IGNORE INTO inbox VALUES (?,?,?,?,?,?,?)",
                        (key, date.today().isoformat(), "pending", None, json.dumps(record), reason, None))
        self.db.commit()
        return "added"

    def dedupe(self, dry_run: bool = False) -> list[dict]:
        """Reject pending jobs that are already in the sheet or earlier in the inbox: ones that got in
        before the matcher knew them, or whose twin reached the sheet another way (Quick add, a paste)."""
        today = date.today().isoformat()
        try:
            statuses = json.loads(self.store.statuses.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            statuses = {}
        removed = []
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            sheet = self.store.rows()
            entries = []
            for entry in self._rows():
                with contextlib.suppress(InvalidJob):
                    entries.append((entry, normalize(entry["record"])))
            # Copies rejected for being a copy: never the reason to drop the job they copied
            copies = {m for m, (e, _) in enumerate(entries) if e["status"] == "rejected" and "(duplicate:" in (e["reason"] or "")}
            for n, (entry, job) in enumerate(entries):
                if entry["status"] != "pending":
                    continue
                dup = find_duplicate(job, sheet)
                if dup:
                    row = sheet[dup[0]]
                    status = statuses.get(record_slug(row)) or row.get("status") or KEPT_STATUS
                    why = f"already in your sheet: {row['title']} at {row['company']} ({status})"
                else:
                    # A twin you already decided on wins; between two pending twins the first one found stays
                    others = [e for m, e in enumerate(entries) if m not in copies and
                              (m < n or (m > n and e[0]["status"] != "pending"))]
                    dup = find_duplicate(job, [j for _, j in others])
                    if not dup:
                        continue
                    first = others[dup[0]][0]
                    why = (f"same job as \"{first['record']['title']}\" at {first['record']['company']}"
                           f" in the inbox ({first['status']})")
                    new_sources = [s for s in job["found_via"] if s not in first["record"].get("found_via", [])]
                    if first["status"] == "pending" and new_sources and not dry_run:
                        first["record"]["found_via"] = list(first["record"].get("found_via", [])) + new_sources
                        self.db.execute("UPDATE inbox SET record = ? WHERE job_id = ?",
                                        (json.dumps(first["record"]), first["job_id"]))
                removed.append({"job_id": entry["job_id"], "company": job["company"], "title": job["title"], "why": why})
                copies.add(n)
                if dry_run:
                    continue
                self.db.execute("UPDATE inbox SET status='rejected', decided_on=?, reason=? WHERE job_id=?",
                                (datetime.now().isoformat(timespec="seconds"),
                                 f"Auto-rejected {today} (duplicate: {why})", entry["job_id"]))
                self._remember(entry["job_id"], {"kind": "rejected", "reason": entry["reason"]})
        return removed

    def _remember(self, job_id: str, snapshot: dict) -> str:
        token = uuid.uuid4().hex
        self.db.execute("INSERT OR REPLACE INTO inbox_undo VALUES (?,?,?)",
                        (job_id, token, json.dumps(snapshot)))
        return token

    def keep(self, job_id: str) -> dict:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            entry = next((e for e in self._rows() if e["job_id"] == job_id), None)
            if entry is None:
                return {"result": "not found"}
            if entry["status"] != "pending":
                return {"result": "already kept" if entry["status"] == "kept" else "not pending", "slug": entry["slug"]}
            outcome = self.store.add({**entry["record"], "status": KEPT_STATUS}, capture_undo=True)
            if outcome["result"] in ("added", "merged", "duplicate"):
                token = self._remember(job_id, outcome.pop("_undo"))
                self.db.execute("UPDATE inbox SET status='kept', decided_on=?, slug=? WHERE job_id=?",
                                (datetime.now().isoformat(timespec="seconds"), outcome.get("slug"), job_id))
                outcome["undo_token"] = token
            return outcome

    def reject(self, job_id: str) -> str:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            cur = self.db.execute("UPDATE inbox SET status='rejected', decided_on=? WHERE job_id=? AND status='pending'",
                                  (datetime.now().isoformat(timespec="seconds"), job_id))
            if cur.rowcount:
                self._remember(job_id, {"kind": "rejected"})
            return "rejected" if cur.rowcount else "not pending"

    def undo_token(self, job_id: str) -> str | None:
        row = self.db.execute("SELECT token FROM inbox_undo WHERE job_id=?", (job_id,)).fetchone()
        return row[0] if row else None

    def undo(self, job_id: str, token: str | None = None) -> dict:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT token, snapshot FROM inbox_undo WHERE job_id=?", (job_id,)).fetchone()
            if row is None or (token is not None and row[0] != token):
                raise ValueError("This action can no longer be undone.")
            snapshot = json.loads(row[1])
            if snapshot["kind"] == "added" and self.db.execute(
                "SELECT 1 FROM inbox WHERE status='kept' AND slug=? AND job_id!=?",
                (snapshot["slug"], job_id),
            ).fetchone():
                raise ValueError("Another kept inbox job uses this tracker entry. Undo that Keep first.")
            if snapshot["kind"] != "rejected":
                self.store.undo_keep(snapshot)
            self.db.execute("UPDATE inbox SET status='pending', decided_on=NULL, slug=NULL WHERE job_id=?", (job_id,))
            if "reason" in snapshot:  # an automatic reject replaced why the job passed
                self.db.execute("UPDATE inbox SET reason=? WHERE job_id=?", (snapshot["reason"], job_id))
            self.db.execute("DELETE FROM inbox_undo WHERE job_id=?", (job_id,))
            return {"result": "undone", "job_id": job_id}

    def pending(self) -> list[dict]:
        return self._rows("pending")

    def stats(self) -> dict:
        return dict(Counter(e["status"] for e in self._rows()))


def write_page(inbox: Inbox) -> Path:
    """A plain HTML list of pending jobs (no scripts, so it opens anywhere)."""
    e = lambda s: html.escape(str(s or ""))
    items = inbox.pending()
    rows = []
    for it in items:
        r = it["record"]
        flags = " ".join(f"<span class=tag>{e(f)}</span>" for f in r.get("flags") or [])
        rows.append(
            f"<tr><td>{e(it['added_on'])}</td><td>{e(r['company'])}</td>"
            f"<td><a href='{e(r.get('url'))}'>{e(r['title'])}</a><br><code>{e(it['job_id'])}</code></td>"
            f"<td>{e(r.get('location'))}</td><td>{e(r.get('suggested_bucket'))}</td>"
            f"<td>{e(r.get('years_required') or '')}</td><td>{e(r.get('grad_year') or '')}</td>"
            f"<td>{flags}</td><td class=why>{e(it['reason'])}</td></tr>")
    page = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Job Inbox</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e6e6e6;--chip:#f2f2f2;--acc:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161616;--fg:#eee;--mut:#9a9a9a;--line:#2c2c2c;--chip:#242424;--acc:#7aa2ff}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,sans-serif;margin:0;padding:16px;max-width:1300px}}
h1{{font-size:20px;margin:0 0 4px}} p{{color:var(--mut);margin:4px 0 12px}} table{{border-collapse:collapse;width:100%}}
td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{font-size:12px;color:var(--mut)}}
a{{color:var(--acc);text-decoration:none}} code{{font-size:11px;color:var(--mut)}} .tag{{font-size:11px;background:var(--chip);border-radius:4px;padding:1px 6px;color:var(--mut)}}
.why{{color:var(--mut);font-size:12px;max-width:320px}} .wrap{{overflow-x:auto}}
</style></head><body><h1>Job inbox</h1>
<p>{len(items)} jobs waiting. Keep or reject with <code>python scripts/inbox.py keep|reject &lt;id&gt;</code> (the id is under each title).</p>
<div class=wrap><table><thead><tr><th>Found</th><th>Company</th><th>Role</th><th>Location</th><th>Resume</th><th>Years</th><th>Grad</th><th>Flags</th><th>Why it passed</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></body></html>"""
    PAGE_FILE.write_text(page, encoding="utf-8")
    return PAGE_FILE


def main() -> int:
    parser = argparse.ArgumentParser(description="Review jobs the automation found.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("stats")
    sub.add_parser("page")
    sub.add_parser("dedupe").add_argument("--dry-run", action="store_true", help="list them without rejecting")
    for name in ("keep", "reject"):
        p = sub.add_parser(name)
        p.add_argument("ids", nargs="+")
    args = parser.parse_args()

    inbox = Inbox()
    if args.cmd == "list":
        for it in inbox.pending():
            r = it["record"]
            print(f"{it['job_id']:52} {r['company'][:22]:22} {r['title'][:55]:55} {r.get('suggested_bucket') or ''}")
    elif args.cmd == "stats":
        print(inbox.stats())
    elif args.cmd == "page":
        print(write_page(inbox))
    elif args.cmd == "dedupe":
        removed = inbox.dedupe(dry_run=args.dry_run)
        for r in removed:
            print(f"{r['job_id']:52} {r['company'][:22]:22} {r['title'][:45]:45} {r['why']}")
        print(f"{len(removed)} duplicate(s) {'found' if args.dry_run else 'rejected'}")
    elif args.cmd == "keep":
        for i in args.ids:
            print(i, inbox.keep(i).get("result"))
    elif args.cmd == "reject":
        for i in args.ids:
            print(i, inbox.reject(i))
    return 0


if __name__ == "__main__":
    sys.exit(main())
