"""
Company job boards on Greenhouse, Ashby, Lever and Workday.

board_from_url() turns a posting or board link into a board key, and probe()
checks whether a board is live through the site's public API. The company
list builder (build_boards.py) and the job-board checks both use these.

Board keys:
  greenhouse, ashby          the board name, lowercased ("airbnb"); these APIs ignore case
  lever                      the board name as written ("AIFund"); Lever's API is case-sensitive
  workday                    "tenant|wdN|site", lowercased ("adobe|wd5|external_university")
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

ATS = ("greenhouse", "ashby", "lever", "workday")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 20

_NOT_BOARDS = {"", "embed", "api", "v1", "jobs", "job", "careers", "favicon.ico", "robots.txt", "sitemap.xml", "static", "assets", "_next"}
_SLUG_OK = re.compile(r"[a-z0-9][a-z0-9 ._-]{0,80}", re.I)
_LOCALE = re.compile(r"^[a-z]{2}-[a-z]{2}$", re.I)


def _slug(raw: str, keep_case: bool = False) -> str | None:
    slug = unquote(raw).strip()
    if not keep_case:
        slug = slug.lower()
    if slug.lower() in _NOT_BOARDS or not _SLUG_OK.fullmatch(slug):
        return None
    return slug


def board_from_url(url: str) -> tuple[str, str] | None:
    """(ats, key) for a Greenhouse/Ashby/Lever/Workday link, else None."""
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    path = [p for p in parts.path.split("/") if p]

    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        if path and path[0] == "embed":
            for_ = parse_qs(parts.query).get("for", [""])[0]
            slug = _slug(for_)
        else:
            slug = _slug(path[0]) if path else None
        return ("greenhouse", slug) if slug else None
    if host == "jobs.ashbyhq.com":
        slug = _slug(path[0]) if path else None
        return ("ashby", slug) if slug else None
    if host == "jobs.lever.co":
        slug = _slug(path[0], keep_case=True) if path else None
        return ("lever", slug) if slug else None

    m = re.fullmatch(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", host)
    if m:
        if path and _LOCALE.match(path[0]):
            path = path[1:]
        if not path or path[0] in ("wday", "job"):
            return None
        site = unquote(path[0]).lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,80}", site):
            return None
        return "workday", f"{m.group(1)}|{m.group(2)}|{site}"
    return None


# ── Checking a board ─────────────────────────────────────────────────

@dataclass
class Probe:
    status: str          # ok | dead | closed | error
    jobs: int | None     # open postings, when the API says (Ashby's check doesn't)
    detail: str = ""


_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        _local.session = s
    return _local.session


def _request(method: str, url: str, retry_on: tuple[int, ...] = (429,), **kwargs) -> requests.Response:
    """One request with two retries on rate limits, server errors and timeouts."""
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = _session().request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            last = exc
        else:
            if resp.status_code not in retry_on and resp.status_code < 500:
                return resp
            last = RuntimeError(f"HTTP {resp.status_code}")
        time.sleep(2 * (attempt + 1) ** 2)
    raise RuntimeError(str(last))


def workday_api(key: str) -> tuple[str, str]:
    tenant, wd, site = key.split("|")
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    return f"{base}/wday/cxs/{tenant}/{site}/jobs", f"{base}/{site}"


def probe(ats: str, key: str) -> Probe:
    """Is this board live? Uses the lightest request each site allows."""
    try:
        if ats == "greenhouse":
            # Greenhouse answers 403 when it's throttling, so wait and retry those too
            resp = _request("GET", f"https://boards-api.greenhouse.io/v1/boards/{quote(key)}/jobs", retry_on=(403, 429))
            if resp.status_code == 200:
                return Probe("ok", len(resp.json().get("jobs", [])))
        elif ats == "ashby":
            resp = _request("HEAD", f"https://api.ashbyhq.com/posting-api/job-board/{quote(key)}")
            if resp.status_code == 200:
                return Probe("ok", None)
        elif ats == "lever":
            resp = _request("GET", f"https://api.lever.co/v0/postings/{quote(key)}?mode=json&limit=1")
            if resp.status_code == 200:
                return Probe("ok", None)
        elif ats == "workday":
            api, referer = workday_api(key)
            resp = _request(
                "POST", api,
                json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                headers={"Content-Type": "application/json", "Referer": referer},
            )
            if resp.status_code == 200:
                return Probe("ok", resp.json().get("total"))
            if resp.status_code == 403:
                # Site exists but isn't taking applicants now (seasonal university sites do this)
                return Probe("closed", None, "403 permission denied")
        else:
            return Probe("error", None, f"unknown site {ats}")
    except (RuntimeError, ValueError) as exc:
        return Probe("error", None, str(exc)[:200])

    if resp.status_code in (404, 410, 422):
        return Probe("dead", None, f"HTTP {resp.status_code}")
    return Probe("error", None, f"HTTP {resp.status_code}")


# ── Fetching job lists ───────────────────────────────────────────────

@dataclass
class Posting:
    ats: str
    board: str
    job_id: str              # "greenhouse:123", "ashby:<uuid>", "lever:<uuid>", "workday:<tenant>:<req>"
    title: str
    locations: list[str]
    countries: list[str]
    url: str
    apply_url: str
    posted: str              # ISO date, or "" when unknown
    posted_days: int | None  # days since posted
    company: str = ""        # when the site says (Greenhouse does)
    employment: str = ""     # Ashby employmentType / Lever commitment / Workday timeType
    description: str = ""    # filled in for Ashby and Lever; fetched later for the others
    ref: str = ""            # what fetch_description needs (Greenhouse id, Workday path)
    note: str = ""           # e.g. why a description couldn't be fetched


@dataclass
class BoardFetch:
    status: str              # changed | unchanged | dead | closed | error
    etag: str | None = None
    postings: list[Posting] | None = None
    detail: str = ""
    sorted_by_date: bool | None = None


def html_to_text(markup: str) -> str:
    import html as _html
    text = _html.unescape(markup or "")
    if "&lt;" in text:  # Greenhouse escapes its HTML twice
        text = _html.unescape(text)
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|li|ul|ol|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _days_since(iso: str) -> int | None:
    from datetime import datetime, timezone
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - dt).days)


def _workday_days(posted_on: str) -> int | None:
    text = (posted_on or "").lower()
    if "today" in text:
        return 0
    if "yesterday" in text:
        return 1
    m = re.search(r"(\d+)\+?\s*days?", text)
    return int(m.group(1)) if m else None


def _conditional_get(url: str, etag: str | None) -> requests.Response:
    headers = {"If-None-Match": etag} if etag else {}
    return _request("GET", url, headers=headers, retry_on=(403, 429))


def fetch_board(ats: str, key: str, etag: str | None = None, window_days: int = 2, full: bool = False) -> BoardFetch:
    """Download a board's open postings. Greenhouse/Ashby/Lever send nothing when unchanged."""
    try:
        if ats == "greenhouse":
            return _fetch_greenhouse(key, etag)
        if ats == "ashby":
            return _fetch_ashby(key, etag)
        if ats == "lever":
            return _fetch_lever(key, etag)
        if ats == "workday":
            return _fetch_workday(key, window_days, full)
        return BoardFetch("error", detail=f"unknown site {ats}")
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        return BoardFetch("error", detail=str(exc)[:200])


def _status_of(resp: requests.Response) -> BoardFetch | None:
    if resp.status_code == 304:
        return BoardFetch("unchanged", resp.headers.get("ETag"))
    if resp.status_code in (404, 410, 422):
        return BoardFetch("dead", detail=f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        return BoardFetch("error", detail=f"HTTP {resp.status_code}")
    return None


def _fetch_greenhouse(key: str, etag: str | None) -> BoardFetch:
    resp = _conditional_get(f"https://boards-api.greenhouse.io/v1/boards/{quote(key)}/jobs", etag)
    early = _status_of(resp)
    if early:
        return early
    out = []
    for j in resp.json().get("jobs", []):
        posted = (j.get("first_published") or j.get("updated_at") or "")[:10]
        out.append(Posting(
            ats="greenhouse", board=key, job_id=f"greenhouse:{j['id']}", title=j.get("title", ""),
            locations=[(j.get("location") or {}).get("name", "")], countries=[],
            url=j.get("absolute_url", ""), apply_url=j.get("absolute_url", ""),
            posted=posted, posted_days=_days_since(j.get("first_published") or j.get("updated_at") or ""),
            company=(j.get("company_name") or "").strip(), ref=str(j["id"]),
        ))
    return BoardFetch("changed", resp.headers.get("ETag"), out)


def _fetch_ashby(key: str, etag: str | None) -> BoardFetch:
    resp = _conditional_get(f"https://api.ashbyhq.com/posting-api/job-board/{quote(key)}", etag)
    early = _status_of(resp)
    if early:
        return early
    out = []
    for j in resp.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        locations = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        addresses = [j.get("address")] + [s.get("address") for s in j.get("secondaryLocations") or []]
        countries = [((a or {}).get("postalAddress") or {}).get("addressCountry", "") for a in addresses]
        out.append(Posting(
            ats="ashby", board=key, job_id=f"ashby:{j['id'].lower()}", title=j.get("title", "").strip(),
            locations=locations, countries=[c for c in countries if c],
            url=j.get("jobUrl", ""), apply_url=j.get("applyUrl") or j.get("jobUrl", ""),
            posted=(j.get("publishedAt") or "")[:10], posted_days=_days_since(j.get("publishedAt") or ""),
            employment=j.get("employmentType") or "", description=(j.get("descriptionPlain") or "").strip(),
        ))
    return BoardFetch("changed", resp.headers.get("ETag"), out)


def _fetch_lever(key: str, etag: str | None) -> BoardFetch:
    from datetime import datetime, timezone
    resp = _conditional_get(f"https://api.lever.co/v0/postings/{quote(key)}?mode=json", etag)
    early = _status_of(resp)
    if early:
        return early
    out = []
    for j in resp.json():
        cats = j.get("categories") or {}
        created = j.get("createdAt")
        posted_iso = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if created else ""
        out.append(Posting(
            ats="lever", board=key, job_id=f"lever:{j['id'].lower()}", title=(j.get("text") or "").strip(),
            locations=[cats.get("location") or ""] + list(cats.get("allLocations") or []),
            countries=[j["country"]] if j.get("country") else [],
            url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl") or j.get("hostedUrl", ""),
            posted=posted_iso[:10], posted_days=_days_since(posted_iso),
            employment=cats.get("commitment") or "", description=lever_description(j),
        ))
    return BoardFetch("changed", resp.headers.get("ETag"), out)


def lever_description(j: dict) -> str:
    """One Lever posting's full text: description, its lists, and the closing section."""
    parts = [j.get("descriptionPlain") or ""]
    for block in j.get("lists") or []:
        parts.append(f"{block.get('text', '')}\n{html_to_text(block.get('content', ''))}")
    parts.append(j.get("additionalPlain") or "")
    return "\n\n".join(p.strip() for p in parts if p.strip())


WORKDAY_PAGE = 20
WORKDAY_MAX_PAGES = 100  # Workday stops listing at 2,000 jobs


def _fetch_workday(key: str, window_days: int, full: bool) -> BoardFetch:
    """Newest first: stop at the first page with nothing inside the window.

    Some sites (Adobe) don't sort by date. Those are read in full, capped at 2,000 jobs.
    """
    api, referer = workday_api(key)
    tenant, _, site = key.split("|")
    base = referer.rsplit("/", 1)[0]
    out: list[Posting] = []
    sorted_by_date: bool | None = None
    for page in range(WORKDAY_MAX_PAGES):
        resp = _request(
            "POST", api,
            json={"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": page * WORKDAY_PAGE, "searchText": ""},
            headers={"Content-Type": "application/json", "Referer": referer},
        )
        if resp.status_code == 403:
            return BoardFetch("closed", detail="403 permission denied")
        early = _status_of(resp)
        if early:
            return early
        data = resp.json()
        items = data.get("jobPostings") or []
        days = [_workday_days(p.get("postedOn", "")) for p in items]
        if page == 0:
            known = [d for d in days if d is not None]
            sorted_by_date = known == sorted(known)
        in_window = False
        for p, d in zip(items, days):
            if not full and d is not None and d > window_days:
                continue
            in_window = True
            path = p.get("externalPath", "")
            url = f"{base}/{site}{path}"
            req = path.rsplit("_", 1)[-1].lower() if "_" in path else (p.get("bulletFields") or [""])[0].lower()
            hint = path.split("/")[2].replace("-", " ") if path.count("/") >= 2 else ""
            out.append(Posting(
                ats="workday", board=key, job_id=f"workday:{tenant}:{req}", title=(p.get("title") or "").strip(),
                locations=[p.get("locationsText") or "", hint], countries=[],
                url=url, apply_url=url, posted="", posted_days=d, ref=path,
            ))
        total = data.get("total") or 0
        if (page + 1) * WORKDAY_PAGE >= total or not items:
            break
        if not full and sorted_by_date and not in_window:
            break
    return BoardFetch("changed", None, out, sorted_by_date=sorted_by_date)


def fetch_description(p: Posting) -> Posting:
    """Fill in the description (and better location data) for Greenhouse and Workday postings."""
    try:
        if p.ats == "greenhouse" and not p.description:
            resp = _request("GET", f"https://boards-api.greenhouse.io/v1/boards/{quote(p.board)}/jobs/{p.ref}", retry_on=(403, 429))
            if resp.status_code == 200:
                data = resp.json()
                p.description = html_to_text(data.get("content", ""))
                p.locations += [o.get("location") or o.get("name", "") for o in data.get("offices") or []]
        elif p.ats == "workday" and not p.description:
            _, referer = workday_api(p.board)
            tenant, _, site = p.board.split("|")
            api = f"{referer.rsplit('/', 1)[0]}/wday/cxs/{tenant}/{site}{p.ref}"
            resp = _request("GET", api, headers={"Referer": referer})
            if resp.status_code == 200:
                info = resp.json().get("jobPostingInfo") or {}
                p.description = html_to_text(info.get("jobDescription", ""))
                p.locations = [info.get("location") or ""] + list(info.get("additionalLocations") or []) + p.locations
                country = (info.get("country") or {}).get("descriptor")
                if country:
                    p.countries = [country]
                p.url = p.apply_url = info.get("externalUrl") or p.url
                p.employment = info.get("timeType") or p.employment
                if info.get("startDate"):
                    p.posted = str(info["startDate"])[:10]
    except (RuntimeError, ValueError) as exc:
        p.note = f"description not fetched: {str(exc)[:80]}"
    return p
