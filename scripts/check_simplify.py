#!/usr/bin/env python3
"""
Add new roles from the SimplifyJobs New-Grad-Positions list as candidates for
the description check.

Source: .github/scripts/listings.json on the repo's dev branch, the data its
README is built from. The README only shows rows whose title says new grad; the
file also has roles Simplify tagged new-grad with plain titles. Both are taken,
and every row gets found_via ["simplify"], so it sorts to the top of the inbox
(the owner's choices, 2026-09-29). Sections: Software, AI/ML/Data, Quant.

For each active row not handled before:
  1. Location (US or remote-US; unclear is kept) and the same title rules as the
     board check: clear titles are kept up to 45 days old, plain ones 14 days.
  2. Simplify's own flags: US citizenship required and PhD-only are dropped, and
     so is "does not offer sponsorship" when profile.local.yaml says
     needs_sponsorship (otherwise it becomes the no-sponsorship flag). TikTok and
     ByteDance are skipped (the owner's applications there are used up).
  3. Jobs already decided are skipped. If one is already in the inbox, it just
     gains "simplify" in found_via.
  4. The description comes from the job's board API (Greenhouse, Ashby, Lever,
     Workday), a career-site API (Oracle, Workable, BambooHR, SmartRecruiters)
     or the page's JobPosting data. Plain page text counts only if it reads like
     a job posting; otherwise the job gets the no-description flag. Pages that need a real browser get the
     no-description flag, and Codex judges them on the title.
  5. Candidates go to data/candidates/<date>-simplify.jsonl, which
     check_descriptions.py reads with the board check's files.

State lives in data/loom.db: simplify_seen (rows already handled) and a
board_state row holding the file's ETag, so an unchanged list costs one request.

Usage (from repo root):
  python scripts/check_simplify.py
  python scripts/check_simplify.py --dry-run --limit 20   # fetch and print, save nothing
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_job import InvalidJob, Store, apply_via_from_url, find_duplicate, job_id_from_url, normalize  # noqa: E402
from boards import Posting, _request, board_from_url, fetch_description, html_to_text, lever_description  # noqa: E402
from check_boards import MAX_AGE_DAYS, open_db  # noqa: E402
from check_descriptions import load_profile  # noqa: E402
from inbox import Inbox  # noqa: E402
from job_filters import SKIP_COMPANIES, location_class, title_class  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = REPO_ROOT / "data" / "candidates"
LISTINGS_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"
# Section names in the file (older rows use the long ones)
CATEGORIES = {"Software", "Software Engineering", "AI/ML/Data", "Data Science, AI & Machine Learning",
              "Quant", "Quantitative Finance"}
MIN_PAGE_TEXT = 500  # less than this from a plain page means it needs a real browser
MAX_PAGE_TEXT = 20000  # a whole page without JobPosting data includes menus and footers


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_listings(db: sqlite3.Connection, use_cache: bool) -> tuple[list[dict] | None, str | None]:
    """(listings, etag), or (None, etag) when the file hasn't changed since the last run."""
    row = db.execute("SELECT etag FROM board_state WHERE ats='simplify' AND board='listings.json'").fetchone()
    etag = row[0] if row and use_cache else None
    resp = _request("GET", LISTINGS_URL, headers={"If-None-Match": etag} if etag else {})
    if resp.status_code == 304:
        return None, etag
    resp.raise_for_status()
    return resp.json(), resp.headers.get("ETag")


# ── Descriptions ─────────────────────────────────────────────────────

_LD_JSON = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.I | re.S)
# iCIMS shows the job in a frame; the outer page is the career site's menus and FAQ
_ICIMS = re.compile(r"https?://[^/]+\.icims\.com/jobs/\d+", re.I)
# Plain page text only counts as a description when it reads like one
_JOB_WORDS = re.compile(r"responsibilit|qualification|requirement|what you.ll do|you will|about the role|about you|"
                        r"job description|bachelor|degree|skills|years of experience", re.I)


def _job_posting_ld(page: str) -> str:
    """The description in the page's schema.org JobPosting data, if it has one."""
    for block in _LD_JSON.findall(page):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            kind = item.get("@type") if isinstance(item, dict) else None
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                return html_to_text(str(item.get("description") or ""))
    return ""


def _from_page(url: str) -> tuple[str, str]:
    if _ICIMS.match(url) and "in_iframe=1" not in url:
        url += ("&" if "?" in url else "?") + "in_iframe=1"
    resp = _request("GET", url, headers={"Accept": "text/html,application/xhtml+xml"})
    if resp.status_code != 200:
        return "", f"page answered {resp.status_code}"
    text = _job_posting_ld(resp.text)
    if text:
        return text, ""
    body = re.search(r"(?is)<body\b.*", resp.text)
    text = html_to_text(body.group(0) if body else resp.text)
    if len(text) >= MIN_PAGE_TEXT and len(set(m.lower() for m in _JOB_WORDS.findall(text))) >= 3:
        return text[:MAX_PAGE_TEXT], "page text, not the site's job data"
    return "", "page needs a browser"


# Career-site software with a public JSON endpoint for one posting: (link pattern, API URL, parser)
_ORACLE = re.compile(r"https://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/([^/?#]+)/job/(\d+)", re.I)
_WORKABLE = re.compile(r"https://apply\.workable\.com/([^/?#]+)/j/([0-9A-Za-z]+)", re.I)
_BAMBOOHR = re.compile(r"https://([a-z0-9-]+)\.bamboohr\.com/careers/(\d+)", re.I)
_SMARTRECRUITERS = re.compile(r"https://jobs\.smartrecruiters\.com/([^/?#]+)/(\d+)", re.I)


def _from_career_site(url: str) -> dict | None:
    """{description, locations, countries} from Oracle, Workable, BambooHR or SmartRecruiters, or None."""
    if m := _ORACLE.match(url):
        host, site, req = m.groups()
        api = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
               f"?expand=all&onlyData=true&finder=ById;Id=%22{req}%22,siteNumber={site}")
        items = _request("GET", api).json().get("items") or [{}]
        j = items[0]
        text = "\n\n".join(html_to_text(j.get(k) or "") for k in
                            ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
        places = [j.get("PrimaryLocation") or ""] + [s.get("Name", "") for s in j.get("secondaryLocations") or []]
        return {"description": text.strip(), "locations": places,
                "countries": [j["PrimaryLocationCountry"]] if j.get("PrimaryLocationCountry") else []}
    if m := _WORKABLE.match(url):
        j = _request("GET", f"https://apply.workable.com/api/v2/accounts/{m[1]}/jobs/{m[2]}").json()
        text = "\n\n".join(html_to_text(j.get(k) or "") for k in ("description", "requirements", "benefits"))
        places = [", ".join(x for x in (p.get("city"), p.get("region"), p.get("country")) if x)
                  for p in j.get("locations") or [j.get("location") or {}]]
        return {"description": text.strip(), "locations": places,
                "countries": [p.get("countryCode") for p in j.get("locations") or [] if p.get("countryCode")]}
    if m := _SMARTRECRUITERS.match(url):
        j = _request("GET", f"https://api.smartrecruiters.com/v1/companies/{m[1]}/postings/{m[2]}").json()
        sections = (j.get("jobAd") or {}).get("sections") or {}
        text = "\n\n".join(html_to_text((sections.get(k) or {}).get("text") or "") for k in
                            ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
        loc = j.get("location") or {}
        return {"description": text.strip(),
                "locations": [", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x)],
                "countries": [loc["country"].upper()] if loc.get("country") else []}
    if m := _BAMBOOHR.match(url):
        j = (_request("GET", f"https://{m[1]}.bamboohr.com/careers/{m[2]}/detail").json().get("result") or {}).get("jobOpening") or {}
        loc = j.get("location") or {}
        return {"description": html_to_text(j.get("description") or ""),
                "locations": [", ".join(x for x in (loc.get("city"), loc.get("state"), loc.get("addressCountry")) if x)],
                "countries": []}
    return None


def fetch_details(url: str, job_id: str) -> dict:
    """{description, locations, countries, url, note} for one posting link."""
    out = {"description": "", "locations": [], "countries": [], "url": url, "note": ""}
    board = board_from_url(url)
    ref = job_id.split(":")[-1]
    try:
        if board and board[0] in ("greenhouse", "workday"):
            ats, key = board
            if ats == "workday":  # the API wants the path from /job/ on
                path = urlparse(url).path
                ref = path[path.find("/job/"):] if "/job/" in path else ""
            p = Posting(ats=ats, board=key, job_id=job_id, title="", locations=[], countries=[], url=url,
                        apply_url=url, posted="", posted_days=None, ref=ref)
            if ref:
                p = fetch_description(p)
            out.update(description=p.description, locations=p.locations, countries=p.countries, url=p.url,
                       note=p.note)
        elif board and board[0] == "lever":
            resp = _request("GET", f"https://api.lever.co/v0/postings/{quote(board[1])}/{ref}")
            if resp.status_code == 200:
                j = resp.json()
                cats = j.get("categories") or {}
                out.update(description=lever_description(j),
                           locations=[cats.get("location") or ""] + list(cats.get("allLocations") or []),
                           countries=[j["country"]] if j.get("country") else [])
        elif board and board[0] == "ashby":
            resp = _request("GET", f"https://api.ashbyhq.com/posting-api/job-board/{quote(board[1])}")
            if resp.status_code == 200:
                for j in resp.json().get("jobs", []):
                    if j.get("id", "").lower() == ref:
                        out.update(description=(j.get("descriptionPlain") or "").strip(),
                                   locations=[j.get("location") or ""])
                        break
        elif site := _from_career_site(url):
            out.update(site)
        if not out["description"]:  # an unknown site, or the API had nothing
            out["description"], note = _from_page(url)
            out["note"] = out["note"] or note
    except (RuntimeError, ValueError) as exc:
        out["note"] = f"description not fetched: {str(exc)[:80]}"
    return out


# ── Main ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Add new SimplifyJobs roles as description-check candidates.")
    parser.add_argument("--dry-run", action="store_true", help="fetch and print; save nothing")
    parser.add_argument("--limit", type=int, default=None, help="fetch at most this many descriptions")
    parser.add_argument("--no-cache", action="store_true", help="download the list even if unchanged")
    args = parser.parse_args()

    db = open_db()
    db.execute("""CREATE TABLE IF NOT EXISTS simplify_seen (
        id TEXT PRIMARY KEY, first_seen TEXT, job_id TEXT, outcome TEXT)""")
    listings, etag = load_listings(db, use_cache=not args.no_cache)
    if listings is None:
        log("SimplifyJobs list unchanged since the last run.")
        return 0
    seen = {row[0] for row in db.execute("SELECT id FROM simplify_seen")}
    checked = {row[0] for row in db.execute("SELECT job_id FROM checked")} if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='checked'").fetchone() else set()
    today = date.today()
    now = datetime.now().timestamp()
    needs_sponsorship = bool(load_profile().get("needs_sponsorship"))
    inbox = Inbox(REPO_ROOT)
    inbox_rows = []
    for entry in inbox._rows():
        try:
            inbox_rows.append(normalize(entry["record"]))
        except InvalidJob:
            continue
    sheet = Store(REPO_ROOT).rows()

    stats: Counter = Counter()
    seen_rows: list[tuple] = []
    todo: list[dict] = []
    for item in listings:
        if not (item.get("active") and item.get("is_visible")) or item.get("category") not in CATEGORIES:
            continue
        if item["id"] in seen:
            stats["handled before"] += 1
            continue

        def done(outcome: str, job_id: str = ""):
            stats[outcome] += 1
            seen_rows.append((item["id"], today.isoformat(), job_id, outcome))

        if SKIP_COMPANIES.search(item["company_name"]):
            done("TikTok/ByteDance (applications used up)")
            continue
        title, locations = item["title"].strip(), [loc for loc in item.get("locations") or [] if loc]
        days = max(0, int((now - item["date_posted"]) / 86400)) if item.get("date_posted") else None
        lclass = location_class(locations, [], title)
        if lclass == "non-us":
            done("not in the US")
            continue
        tclass, why = title_class(title)
        if tclass == "drop":
            done(f"title: {why}")
            continue
        if days is not None and days > MAX_AGE_DAYS[tclass]:
            done("too old")
            continue
        if item.get("sponsorship") == "U.S. Citizenship is Required":
            done("needs US citizenship")
            continue
        if [d.lower() for d in item.get("degrees") or []] == ["phd"]:
            done("PhD required")
            continue
        if item.get("sponsorship") == "Does Not Offer Sponsorship" and needs_sponsorship:
            done("no visa sponsorship")
            continue

        url = item["url"]
        job_id = job_id_from_url(url) or f"simplify:{item['id']}"
        board = board_from_url(url)
        record = {
            "company": item["company_name"].strip(),
            "title": title,
            "location": "; ".join(dict.fromkeys(locations))[:300] or "Not specified",
            "url": url,
            "apply_url": url,
            "description": "",
            "found_via": ["simplify"],
            "apply_via": apply_via_from_url(url),
            "job_id": job_id,
            "posted_time": date.fromtimestamp(item["date_posted"]).isoformat() if item.get("date_posted") else "",
            "flags": ["no-sponsorship"] if item.get("sponsorship") == "Does Not Offer Sponsorship" else [],
            # Fields starting with "_" are pipeline notes; add_job ignores them
            "_board": f"{board[0]}:{board[1]}" if board else "simplify",
            "_title_class": tclass,
            "_location_class": lclass,
            "_posted_days": days,
            "_simplify_id": item["id"],
            "_note": "",
        }
        try:
            job = normalize(record)
        except InvalidJob as exc:
            done(f"can't be stored: {exc}")
            continue
        if find_duplicate(job, inbox_rows):  # found by the board check too: it just gains "simplify"
            if not args.dry_run:
                inbox.add(record)
            done("already in the inbox", job_id)
            continue
        if job_id in checked:
            done("already checked", job_id)
            continue
        if find_duplicate(job, sheet):
            done("already in your sheet", job_id)
            continue
        todo.append(record)

    log(f"{len(todo)} new SimplifyJobs roles" + (f"; fetching {args.limit} descriptions" if args.limit is not None else ""))
    if args.limit is not None:
        todo = todo[: args.limit]
    with ThreadPoolExecutor(max_workers=8) as ex:
        details = list(ex.map(lambda r: fetch_details(r["url"], r["job_id"]), todo))

    candidates = []
    for record, info in zip(todo, details):
        if info["locations"] and location_class(info["locations"], info["countries"], record["title"]) == "non-us":
            stats["not in the US (from the posting)"] += 1
            seen_rows.append((record["_simplify_id"], today.isoformat(), record["job_id"], "not in the US"))
            continue
        record.update(description=info["description"], _note=info["note"])
        record["url"] = record["apply_url"] = info["url"] or record["url"]
        if not info["description"]:
            record["flags"].append("no-description")
        stats["candidate" + ("" if info["description"] else " (no description)")] += 1
        seen_rows.append((record["_simplify_id"], today.isoformat(), record["job_id"], "candidate"))
        candidates.append(record)
        if args.dry_run:
            print(f"  {record['_title_class']:9} | {record['company'][:20]:20} | {record['title'][:48]:48} | "
                  f"{len(info['description']):6} chars | {info['note'][:40]}")

    if not args.dry_run:
        if candidates:
            CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
            with open(CANDIDATES_DIR / f"{today.isoformat()}-simplify.jsonl", "a", encoding="utf-8") as fh:
                for rec in candidates:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        db.executemany("INSERT OR IGNORE INTO simplify_seen VALUES (?,?,?,?)", seen_rows)
        if args.limit is None:  # a limited run leaves the rest for next time
            db.execute("INSERT OR REPLACE INTO board_state VALUES (?,?,?,?,?,?)",
                       ("simplify", "listings.json", etag, today.isoformat(), "changed", None))
        db.commit()
    inbox.close()
    db.close()

    print()
    for key, value in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"  {value:5}  {key}")
    log(f"{len(candidates)} candidates" + (" (dry run: nothing saved)" if args.dry_run else
                                          f" written to data/candidates/{today.isoformat()}-simplify.jsonl"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
