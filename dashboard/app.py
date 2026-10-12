from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from add_job import Store, columns_from_record, company_key, record_from_columns, record_slug
from extract_job import ExtractionError, extract
import phone
import tailor
from inbox import Inbox
from llm import codex_limits
from job_filters import title_class

JOBS_XLSX = REPO_ROOT / "jobs.xlsx"
JOBS_DIR = REPO_ROOT / "jobs"
OUTPUT_DIR = REPO_ROOT / "output"
STATUS_FILE = REPO_ROOT / "dashboard_statuses.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
JOB_STATUSES = ("Not Applied", "Applied", "OA", "Interview", "Offer", "Reject", "Ignore")
PRIORITY_SOURCES = {"linkedin", "handshake", "simplify"}  # these sort to the top of the inbox
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
FORWARDED_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "tailscale-user-login")

@asynccontextmanager
async def _lifespan(_app):
    tailor.start_workers()  # background tailoring for kept jobs
    awake = None
    if phone.load(REPO_ROOT) and shutil.which("caffeinate"):
        # Phone access is on: no sleep on AC power while the dashboard runs (a closed lid still sleeps)
        awake = subprocess.Popen(["caffeinate", "-s", "-w", str(os.getpid())])
    yield
    if awake:
        awake.terminate()


app = FastAPI(title="Loom Dashboard", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _caller_allowed(headers) -> bool:
    """A browser on this Mac, or the owner's phone through `tailscale serve` (scripts/phone.py)."""
    host = re.sub(r":\d+$", "", headers.get("host", "")).lower()
    if host in LOCAL_HOSTS and not any(name in headers for name in FORWARDED_HEADERS):
        return True
    # Anything forwarded, or asked for under another name (a tunnel, DNS rebinding), needs the owner's
    # Tailscale login. `tailscale serve` sets that header itself and drops a caller's own copy.
    saved = phone.load(REPO_ROOT)
    return bool(saved) and host in LOCAL_HOSTS | {saved["host"].lower()} \
        and headers.get("tailscale-user-login", "").casefold() == saved["login"].casefold()


@app.middleware("http")
async def _only_the_owner(request: Request, call_next):
    if not _caller_allowed(request.headers):
        return PlainTextResponse("Loom answers only this Mac, and the owner's phone over Tailscale.", status_code=403)
    return await call_next(request)


class StatusUpdateRequest(BaseModel):
    status: str


class TailorDecision(BaseModel):
    approve: list[int] = Field(default_factory=list)
    reject: list[int] = Field(default_factory=list)
    change: dict[int, str] = Field(default_factory=dict)  # tweak id -> the owner's feedback
    as_is: bool = False
    request: str = Field("", max_length=2000)  # e.g. "draft the outreach note"
    comment: str = Field("", max_length=2000)  # the owner's comment on the resume (Review / job page)
    reviewed: bool = False  # the owner is done with this job in the Review queue
    glanced: bool = False  # the owner looked at a job that skipped Review ("Looks good")


class TailorStart(BaseModel):
    restart: bool = False
    engine: str | None = None
    review: bool | None = None  # the owner looks at this job in Review before the fill


class ReviewMode(BaseModel):
    review: bool


class ApplyQueue(BaseModel):
    slugs: list[str] = Field(min_length=1, max_length=200)


class TailorSettings(BaseModel):
    auto_tailor: bool | None = None
    engine: str | None = None
    fallback: bool | None = None
    auto_answers: bool | None = None
    fill_engine: str | None = None
    auto_review: bool | None = None
    parallel: int | None = None
    fill_parallel: int | None = None


class NotifySettings(BaseModel):
    phone: bool | None = None  # ntfy push to the owner's phone
    mac: bool | None = None    # macOS banner


class VouchedRemove(BaseModel):
    skill: str = Field(..., max_length=80)


class AnswerDecision(BaseModel):
    approve: list[str] = Field(default_factory=list)
    edit: dict[str, str] = Field(default_factory=dict)    # question id -> the owner's own wording
    fill: dict[str, str] = Field(default_factory=dict)    # question id -> the owner's answer to a "you" question
    skip: list[str] = Field(default_factory=list)
    change: dict[str, str] = Field(default_factory=dict)  # question id -> feedback for a rewrite
    reviewed: bool = False


class ApplyAnswers(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)  # field label -> the owner's answer
    signed_in: bool = False  # the owner signed in where the fill stopped


class ApplyComment(BaseModel):
    comment: str = Field(min_length=1, max_length=4000)  # a change the owner wants on the filled form


class TailorQueue(BaseModel):
    slugs: list[str] = Field(default_factory=list)
    all_waiting: bool = False


class InboxActionRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    review: bool | None = None  # Keep: the owner wants to look at these in Review


class UndoRequest(BaseModel):
    id: str
    token: str


def _store() -> Store:
    store = Store(REPO_ROOT)
    store.xlsx, store.jobs_dir, store.statuses = JOBS_XLSX, JOBS_DIR, STATUS_FILE
    return store


def _safe_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise HTTPException(400, "Invalid file path")
    return path


def _load_statuses() -> dict:
    try:
        result = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _job_payload(row: dict, statuses: dict) -> dict:
    slug = record_slug(row)
    job_file = _safe_path(JOBS_DIR, f"{slug}.md")
    out = _safe_path(OUTPUT_DIR, slug)
    artifacts = {"resume_pdf": (out / "Manas_Dalvi_Resume.pdf").is_file(),
                 "cover_letter_docx": (out / "cover_letter.docx").is_file(),
                 "tailor": _tailor_summary(slug)}
    status = statuses.get(slug) or row.get("status") or "Not Applied"
    if status not in JOB_STATUSES:
        status = "Not Applied"
    try:
        timestamp = datetime.fromisoformat(row.get("date") or "").timestamp()
    except ValueError:
        timestamp = 0
    if job_file.exists():
        timestamp = max(timestamp, job_file.stat().st_mtime)
    return {**{k: v for k, v in row.items() if k not in ("description", "company_intro")},
            "slug": slug, "status": status, "available_statuses": list(JOB_STATUSES),
            "artifacts": artifacts, "sort_timestamp": timestamp}


def _tailor_summary(slug: str) -> dict | None:
    """Tailoring status for the job lists: status and how many tweaks wait for a decision."""
    try:
        state = tailor.load_state(slug)
    except tailor.TailorError:
        return None
    if not state:
        return None
    result = state.get("result") or {}
    tweaks = result.get("tweaks") or []
    answers = state.get("answers") or {}
    items = (answers.get("items") or {}).values()
    return {"status": state.get("status"), "pending": sum(t.get("status") == "pending" for t in tweaks),
            "reviewed": bool(state.get("reviewed")), "blocker": bool(result.get("sponsorship_blocker")),
            "answers": {"status": answers.get("status"), "reviewed": bool(answers.get("reviewed")),
                        "needs_you": sum(i.get("status") == "needs_you" for i in items),
                        "drafts": sum(i.get("status") == "draft" for i in items)} if answers else None,
            "apply": (state.get("apply") or {}).get("status"), "review": tailor.reviews(state),
            "coverage": {k: state["coverage"][k] for k in ("as_is", "now", "max")} if state.get("coverage") else None}


def list_jobs() -> list[dict]:
    statuses = _load_statuses()
    jobs = [_job_payload(row, statuses) for row in _store().rows()]
    return sorted(jobs, key=lambda j: (-j["sort_timestamp"], j["slug"]))


def job_detail(slug: str) -> dict:
    row = next((r for r in _store().rows() if record_slug(r) == slug), None)
    if row is None:
        raise HTTPException(404, "Job not found")
    result = _job_payload(row, _load_statuses())
    description = row.get("description") or ""
    md = _safe_path(JOBS_DIR, f"{slug}.md")
    if md.exists():
        text = md.read_text(encoding="utf-8")
        match = re.search(r"^## Job Description\s*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
        if match:
            description = match.group(1).strip()
    return {**result, "description": description, "company_intro": row.get("company_intro") or ""}


def diagnostics() -> dict:
    import importlib.util
    return {
        "commands": {name: shutil.which(name) for name in ("python", "codex", "claude", "pdflatex")},
        "packages": {name: importlib.util.find_spec(name) is not None for name in ("fastapi", "uvicorn", "openpyxl", "yaml", "docx")},
        "files": {"jobs_xlsx": JOBS_XLSX.exists(), "cv_md": (REPO_ROOT / "cv.md").exists(),
                  "jobs_dir": JOBS_DIR.exists(), "output_dir": OUTPUT_DIR.exists()},
    }


def _read_inbox(status: str) -> list[dict]:
    db_file = REPO_ROOT / "data" / "loom.db"
    if not db_file.exists():
        return []
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='inbox'").fetchone():
            return []
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM inbox WHERE status=? ORDER BY added_on DESC, rowid DESC", (status,)).fetchall()
        items = [{**dict(row), "record": json.loads(row["record"])} for row in rows]
        # Jobs already in the sheet at the same company, so a near-duplicate posting is easy to spot
        statuses, at_company = _load_statuses(), {}
        for sheet_row in _store().rows():
            at_company.setdefault(company_key(sheet_row.get("company", "")), []).append(
                {"title": sheet_row.get("title", ""),
                 "status": statuses.get(record_slug(sheet_row)) or sheet_row.get("status") or "Not Applied"})
        for entry in items:
            entry["in_sheet"] = at_company.get(company_key(entry["record"].get("company", "")), [])[:5]
        def posted_timestamp(entry):
            posted = str(entry["record"].get("posted_time") or "")
            try:
                return datetime.fromisoformat(posted.replace("Z", "+00:00")).timestamp()
            except ValueError:
                age = re.fullmatch(r"(\d+) days? ago", posted, re.I)
                if age:
                    try:
                        return (datetime.fromisoformat(entry["added_on"]) - timedelta(days=int(age[1]))).timestamp()
                    except (ValueError, TypeError):
                        pass
                return 0
        # Newest: newest inbox days first, then early-career titles, then newest postings.
        items.sort(key=lambda e: (e["added_on"] or "", title_class(e["record"].get("title", ""))[0] == "clear", posted_timestamp(e)), reverse=True)
        for rank, entry in enumerate(items):
            entry["newest_rank"] = rank
            entry["priority"] = bool(PRIORITY_SOURCES & set(entry["record"].get("found_via") or []))
        # Default order: SimplifyJobs and sweep finds first, newest within each group (the sort is stable)
        items.sort(key=lambda e: not e["priority"])
        return items
    finally:
        db.close()


def system_data() -> dict:
    result = {"last_run": None, "checked": [], "inbox": {"pending": 0, "kept": 0, "rejected": 0},
              "boards": {}, "limits": {}, "diagnostics": diagnostics(), "warnings": [],
              "phone": {k: v for k, v in phone.load(REPO_ROOT).items() if k in ("url", "since")}}
    db_file = REPO_ROOT / "data" / "loom.db"
    if db_file.exists():
        db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "runs" in tables:
                row = db.execute("SELECT id, started, finished, stats FROM runs ORDER BY id DESC LIMIT 1").fetchone()
                if row:
                    result["last_run"] = dict(zip(("id", "started", "finished", "stats"), row))
                    result["last_run"]["stats"] = json.loads(row[3] or "{}")
            if "checked" in tables:
                result["checked"] = [dict(stage=r[0], decision=r[1], count=r[2]) for r in db.execute("SELECT stage, decision, COUNT(*) FROM checked GROUP BY stage, decision")]
            if "inbox" in tables:
                result["inbox"].update(dict(db.execute("SELECT status, COUNT(*) FROM inbox GROUP BY status")))
        except (sqlite3.Error, ValueError) as exc:
            result["warnings"].append(f"Check history unavailable: {exc}")
        finally:
            db.close()
    boards_file = REPO_ROOT / "data" / "boards.json"
    if boards_file.exists():
        try:
            boards = json.loads(boards_file.read_text()).get("boards", {})
            result["boards"] = {site: sum(1 for b in entries.values() if b.get("status") == "ok") for site, entries in boards.items()}
        except (OSError, ValueError, AttributeError):
            result["warnings"].append("Board list unavailable.")
    try:
        result["limits"] = codex_limits()
    except OSError:
        result["warnings"].append("Usage readings unavailable.")
    return result


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs")
async def api_jobs():
    return {"jobs": await asyncio.to_thread(list_jobs), "statuses": list(JOB_STATUSES)}


@app.get("/api/jobs/{slug}")
async def api_job(slug: str):
    return await asyncio.to_thread(job_detail, slug)


@app.post("/api/jobs/{slug}/status")
async def update_job_status(slug: str, request: StatusUpdateRequest):
    if request.status not in JOB_STATUSES:
        raise HTTPException(400, "Invalid status")
    try:
        await asyncio.to_thread(_store().set_status, slug, request.status)
    except KeyError:
        raise HTTPException(404, "Job not found")
    return {"slug": slug, "status": request.status}


def _tailor_state(slug: str) -> dict:
    _safe_path(JOBS_DIR, f"{slug}.md")
    try:
        return tailor.load_state(slug) or {"slug": slug, "status": "none"}
    except tailor.TailorError as exc:
        raise HTTPException(404, str(exc))


def _tailor_error(exc: Exception) -> HTTPException:
    return HTTPException(409 if "already running" in str(exc) else 400, str(exc))


@app.get("/api/jobs/{slug}/tailor")
async def api_tailor(slug: str):
    return await asyncio.to_thread(_tailor_state, slug)


@app.post("/api/jobs/{slug}/tailor")
async def api_tailor_start(slug: str, request: TailorStart | None = None):
    request = request or TailorStart()
    await asyncio.to_thread(_tailor_state, slug)
    if request.engine and request.engine not in tailor.ENGINES:
        raise HTTPException(400, "Unknown engine")
    return await asyncio.to_thread(tailor.enqueue, slug, request.restart, request.engine, request.review)


@app.post("/api/jobs/{slug}/review-mode")
async def api_review_mode(slug: str, request: ReviewMode):
    await asyncio.to_thread(_tailor_state, slug)
    return await asyncio.to_thread(tailor.set_review, slug, request.review)


@app.post("/api/apply/queue")
async def api_apply_queue(request: ApplyQueue):
    """Fill several applications, one after another (one Chrome)."""
    queued, skipped = [], []
    for slug in dict.fromkeys(request.slugs):
        _safe_path(JOBS_DIR, f"{slug}.md")
        try:
            state = await asyncio.to_thread(tailor.enqueue_apply, slug)
        except tailor.TailorError as exc:
            skipped.append({"slug": slug, "reason": str(exc)})
            continue
        queued.append(slug)
    return {"queued": queued, "skipped": skipped}


@app.post("/api/jobs/{slug}/tailor/decide")
async def api_tailor_decide(slug: str, request: TailorDecision):
    await asyncio.to_thread(_tailor_state, slug)
    has_decision = (request.approve or request.reject or request.change or request.as_is or request.request.strip()
                    or request.comment.strip())
    try:
        if has_decision:
            state = await asyncio.to_thread(tailor.decide, slug, request.approve, request.reject, request.change,
                                            request.as_is, request.request, True, request.comment)
        else:
            state = tailor.load_state(slug) or {}
        # A decision the session is still working on (a rewrite, a tweak to fit) comes back for a last look
        if request.reviewed and state.get("status") != "running":
            state = await asyncio.to_thread(tailor.mark_reviewed, slug)
            if tailor.get_settings()["auto_answers"]:
                state = await asyncio.to_thread(tailor.enqueue_answers, slug)
        if request.glanced and state.get("status") != "running":  # a comment's reply brings it back first
            state = await asyncio.to_thread(tailor.mark_glanced, slug)
    except tailor.TailorError as exc:
        raise _tailor_error(exc)
    return state


@app.post("/api/jobs/{slug}/answers")
async def api_answers_start(slug: str, request: TailorStart | None = None):
    await asyncio.to_thread(_tailor_state, slug)
    try:
        return await asyncio.to_thread(tailor.enqueue_answers, slug, bool(request and request.restart))
    except tailor.TailorError as exc:
        raise _tailor_error(exc)


@app.post("/api/jobs/{slug}/answers/decide")
async def api_answers_decide(slug: str, request: AnswerDecision):
    await asyncio.to_thread(_tailor_state, slug)
    try:
        return await asyncio.to_thread(tailor.decide_answers, slug, request.approve, request.edit, request.fill,
                                       request.skip, request.change, request.reviewed, True)
    except tailor.TailorError as exc:
        raise _tailor_error(exc)


@app.post("/api/jobs/{slug}/apply")
async def api_apply(slug: str, request: TailorStart | None = None):
    await asyncio.to_thread(_tailor_state, slug)
    try:
        return await asyncio.to_thread(tailor.enqueue_apply, slug, request.engine if request else None)
    except tailor.TailorError as exc:
        raise _tailor_error(exc)


@app.post("/api/jobs/{slug}/apply/continue")
async def api_apply_continue(slug: str, request: ApplyAnswers):
    await asyncio.to_thread(_tailor_state, slug)
    try:
        return await asyncio.to_thread(tailor.apply_continue, slug, request.answers, True, request.signed_in)
    except tailor.TailorError as exc:
        raise _tailor_error(exc)


@app.post("/api/jobs/{slug}/apply/comment")
async def api_apply_comment(slug: str, request: ApplyComment):
    await asyncio.to_thread(_tailor_state, slug)
    try:
        return await asyncio.to_thread(tailor.apply_comment, slug, request.comment, True)
    except tailor.TailorError as exc:
        raise _tailor_error(exc)


@app.post("/api/jobs/{slug}/apply/submit")
async def api_apply_submit(slug: str):
    """Only from the owner's Submit for me button, after they confirmed it."""
    await asyncio.to_thread(_tailor_state, slug)
    try:
        return await asyncio.to_thread(tailor.apply_submit, slug, True)
    except tailor.TailorError as exc:
        raise _tailor_error(exc)


@app.post("/api/jobs/{slug}/apply/submitted")
async def api_apply_submitted(slug: str):
    """The owner's "I submitted it" button: mark the job Applied and close its fill."""
    await asyncio.to_thread(_tailor_state, slug)
    try:
        return await asyncio.to_thread(tailor.mark_submitted, slug)
    except KeyError:
        raise HTTPException(404, "Job not found")


@app.get("/api/tailor/settings")
async def api_tailor_settings():
    return tailor.get_settings()


def _notify_view() -> dict:
    import notify
    cfg = notify.config()
    return {"phone": cfg["phone"], "mac": cfg["mac"], "topic": cfg["ntfy_topic"],
            "server": cfg["ntfy_server"], "web": f"{cfg['ntfy_server'].rstrip('/')}/{cfg['ntfy_topic']}"}


@app.get("/api/vouched")
async def api_vouched():
    """Skills the owner confirmed in comments; tailoring counts them as backed."""
    return {"skills": await asyncio.to_thread(tailor.vouched_skills)}


@app.post("/api/vouched/remove")
async def api_vouched_remove(request: VouchedRemove):
    return {"skills": await asyncio.to_thread(tailor.remove_vouched, request.skill)}


@app.get("/api/notify")
async def api_notify():
    """Notification settings, with the private ntfy topic the owner's phone subscribes to."""
    return await asyncio.to_thread(_notify_view)


@app.post("/api/notify")
async def api_notify_save(request: NotifySettings):
    import notify
    await asyncio.to_thread(notify.update, {k: v for k, v in request.model_dump().items() if v is not None})
    return await asyncio.to_thread(_notify_view)


@app.post("/api/notify/test")
async def api_notify_test():
    import notify
    errors = await asyncio.to_thread(notify.send, "Test", "Notifications from Loom are working.", notify.job_link(""),
                                     3, ["bell"])
    return {"ok": not errors, "errors": errors}


@app.post("/api/tailor/settings")
async def api_tailor_settings_save(request: TailorSettings):
    try:
        return tailor.save_settings({k: v for k, v in request.model_dump().items() if v is not None})
    except tailor.TailorError as exc:
        raise HTTPException(400, str(exc))


def _waiting_slugs() -> list[str]:
    """Saved jobs still to apply to that have no resume and haven't been tailored."""
    statuses, out = _load_statuses(), []
    for row in _store().rows():
        slug = record_slug(row)
        if (statuses.get(slug) or row.get("status") or "Not Applied") != "Not Applied":
            continue
        try:
            if tailor.load_state(slug) is None and not (OUTPUT_DIR / slug / "Manas_Dalvi_Resume.pdf").exists():
                out.append(slug)
        except tailor.TailorError:
            continue
    return out


@app.post("/api/tailor/queue")
async def api_tailor_queue(request: TailorQueue):
    slugs = await asyncio.to_thread(_waiting_slugs) if request.all_waiting else request.slugs
    queued = []
    for slug in dict.fromkeys(slugs):
        _safe_path(JOBS_DIR, f"{slug}.md")
        try:
            state = await asyncio.to_thread(tailor.enqueue, slug)
        except tailor.TailorError:
            continue
        if state.get("status") == "queued":
            queued.append(slug)
    return {"queued": queued}


def review_data() -> dict:
    """The Review queue: tailored jobs waiting for the owner, plus what's still being tailored."""
    statuses, counts, items = _load_statuses(), Counter(), []
    rows = _store().rows()
    for row in rows:
        slug = record_slug(row)
        try:
            state = tailor.load_state(slug)
        except tailor.TailorError:
            continue
        if not state:
            continue
        status = state.get("status")
        answers = state.get("answers") or {}
        if answers.get("status") in ("queued", "running"):
            counts["answering"] += 1
        if (state.get("apply") or {}).get("status") in ("queued", "running"):
            counts["filling"] += 1
        working = False
        if status in ("queued", "running"):
            counts[status] += 1
            # The session working on the owner's change to a job in Review: keep it on screen, marked working
            if state.get("action") != "decide" or not state.get("result"):
                continue
            working = True
        base = {"slug": slug, "company": row.get("company"), "title": row.get("title"),
                "location": row.get("location"), "url": row.get("url"), "apply_url": row.get("apply_url"),
                "found_via": row.get("found_via") or [],
                "job_status": statuses.get(slug) or row.get("status") or "Not Applied", "tailor": state,
                "working": working}
        # Applied (or further along, rejected, ignored) or submitted: nothing left to review
        if base["job_status"] not in ("Not Applied", "New") or (state.get("apply") or {}).get("status") == "submitted":
            counts["done"] += 1
            continue
        if not state.get("reviewed"):
            counts["to_review"] += 1
            items.append({**base, "type": "resume"})
        elif answers.get("status") in ("ready", "failed") and not answers.get("reviewed"):
            counts["to_review"] += 1
            items.append({**base, "type": "answers"})
        elif state.get("auto") and not state.get("glanced"):  # went through Skip Review: shown for a quick look
            counts["to_glance"] += 1
            items.append({**base, "type": "auto"})
        else:
            counts["reviewed"] += 1
    # What needs you first; then a fixed order: when the job first got its resume (later saves don't move it),
    # with a job's resume card before its answers card
    items.sort(key=lambda i: (i["type"] == "auto", ((i["tailor"].get("turns") or [{}])[0].get("at")
                                                    or i["tailor"].get("updated") or ""), i["slug"], i["type"] == "answers"))
    counts["waiting"] = len(_waiting_slugs())
    return {"items": items, "counts": {k: counts.get(k, 0) for k in ("to_review", "to_glance", "done", "running", "queued", "answering",
                                                                         "filling", "waiting", "reviewed")},
            "settings": tailor.get_settings()}


@app.get("/api/review")
async def api_review():
    return await asyncio.to_thread(review_data)


@app.delete("/api/jobs/{slug}")
async def delete_job(slug: str):
    _safe_path(JOBS_DIR, f"{slug}.md")
    _safe_path(OUTPUT_DIR, slug)
    try:
        removed = await asyncio.to_thread(_store().delete, slug)
    except KeyError:
        raise HTTPException(404, "Job not found")
    return {"slug": slug, "removed": removed}


@app.get("/api/inbox")
async def api_inbox(status: str = Query("pending", pattern="^(pending|kept|rejected)$"),
                    bucket: str = "", source: str = "", flag: str = "", q: str = ""):
    items = await asyncio.to_thread(_read_inbox, status)
    return {"items": [e for e in items if
                     (not bucket or e["record"].get("suggested_bucket") == bucket) and
                     (not source or source in e["record"].get("found_via", [])) and
                     (not flag or flag in e["record"].get("flags", [])) and
                     (not q or q.casefold() in " ".join(str(e["record"].get(k, "")) for k in ("company", "title", "location")).casefold())]}


def _inbox_action(action: str, ids: list[str], review: bool | None = None) -> list[dict]:
    results = []
    with Inbox(REPO_ROOT) as ib:
        ib.store = _store()
        for job_id in dict.fromkeys(ids):
            try:
                if action == "keep":
                    result = ib.keep(job_id)
                    if result.get("result") == "added" and result.get("slug") and tailor.get_settings()["auto_tailor"]:
                        try:
                            tailor.enqueue(result["slug"], review=review)
                        except tailor.TailorError:
                            pass
                else:
                    result = {"result": ib.reject(job_id)}
                    if result["result"] == "rejected":
                        result["undo_token"] = ib.undo_token(job_id)
                results.append({"id": job_id, **result})
            except (OSError, ValueError, sqlite3.Error) as exc:
                results.append({"id": job_id, "result": "error", "reason": str(exc)})
    return results


@app.post("/api/inbox/keep")
async def keep_inbox(request: InboxActionRequest):
    return {"results": await asyncio.to_thread(_inbox_action, "keep", request.ids, request.review)}


@app.post("/api/inbox/reject")
async def reject_inbox(request: InboxActionRequest):
    return {"results": await asyncio.to_thread(_inbox_action, "reject", request.ids)}


def _undo(request):
    with Inbox(REPO_ROOT) as ib:
        ib.store = _store()
        return ib.undo(request.id, request.token)


@app.post("/api/inbox/undo")
async def undo_inbox(request: UndoRequest):
    try:
        return await asyncio.to_thread(_undo, request)
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/system")
async def api_system():
    return await asyncio.to_thread(system_data)


@app.get("/api/diagnostics")
async def api_diagnostics():
    return await asyncio.to_thread(diagnostics)


def _resolve_output_file(slug: str, filename: str) -> Path:
    directory = _safe_path(OUTPUT_DIR, slug)
    path = _safe_path(directory, filename)
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return path


@app.get("/api/files/{slug}/{filename}")
async def api_file(slug: str, filename: str):
    return FileResponse(_resolve_output_file(slug, filename))


@app.get("/view/{slug}/{filename}")
async def view_file(slug: str, filename: str):
    path = _resolve_output_file(slug, filename)
    if path.suffix.lower() in (".tex", ".json", ".md", ".txt"):
        content = html.escape(path.read_text(encoding="utf-8"))
        return HTMLResponse(f'<meta name="viewport" content="width=device-width"><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{content}</pre>')
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0], content_disposition_type="inline", filename=path.name)


# ── Quick-Add feature ──────────────────────────────────────────────


class ParseJobRequest(BaseModel):
    raw_text: str


class CheckDuplicateRequest(BaseModel):
    fields: dict[str, str]


class AddJobRequest(BaseModel):
    fields: dict[str, str]
    force: bool = False


# Columns shown in the Quick Add form, in order. Found_via, Apply_via and
# Job_ID are filled in by add_job, not typed.
QUICK_ADD_COLUMNS = [
    "Company", "Title", "Location", "Category", "Title_URL", "Apply_URL", "Salary",
    "Posted_time", "People_applied", "Company_URL", "Company_size", "Company_follower",
    "Is this an internship", "Company_Intro", "About_the_job",
]


def _quick_add_record(fields: dict[str, str]) -> dict[str, Any]:
    record = record_from_columns({k: v for k, v in fields.items() if k in QUICK_ADD_COLUMNS})
    record["found_via"] = ["paste"]
    return record


@app.get("/api/quick-add/headers")
async def quick_add_headers() -> JSONResponse:
    """Return the ordered list of fields shown in the Quick Add form."""
    return JSONResponse({"headers": QUICK_ADD_COLUMNS})


@app.post("/api/quick-add/check-duplicate")
async def quick_add_check_duplicate(request: CheckDuplicateRequest) -> JSONResponse:
    """Validate the form and check whether the job is already in the sheet."""
    result = await asyncio.to_thread(_store().add, _quick_add_record(request.fields), dry_run=True)
    if result["result"] == "rejected":
        raise HTTPException(status_code=400, detail=result["reason"])
    if result["result"] in ("merged", "duplicate"):
        return JSONResponse({"duplicate": True, "match_reason": result["reason"], "existing": result["existing"]})
    return JSONResponse({"duplicate": False})


@app.post("/api/quick-add/parse")
async def quick_add_parse(request: ParseJobRequest) -> JSONResponse:
    """Extract job fields from pasted posting text with a model (see scripts/extract_job.py)."""
    try:
        result = await asyncio.to_thread(extract, request.raw_text)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return JSONResponse({
        "fields": columns_from_record(result["record"]),
        "warnings": result["warnings"],
        "engine": result["engine"],
        "model": result["model"],
    })


@app.post("/api/quick-add/save")
async def quick_add_save(request: AddJobRequest) -> JSONResponse:
    """Add the job through add_job: sheet row, jobs/<slug>.md and status Not Applied."""
    result = await asyncio.to_thread(_store().add, _quick_add_record(request.fields), force=request.force)
    if result["result"] == "rejected":
        raise HTTPException(status_code=400, detail=result["reason"])
    if result["result"] in ("merged", "duplicate"):
        raise HTTPException(status_code=409, detail=f"Already in the sheet ({result['reason'].lower()}): {result['slug']}")
    await asyncio.to_thread(_dedupe_inbox)  # the same job waiting in the inbox leaves it
    return JSONResponse({"ok": True, "slug": result["slug"]})


def _dedupe_inbox() -> None:
    try:
        with Inbox(REPO_ROOT) as ib:
            ib.store = _store()
            ib.dedupe()
    except (OSError, sqlite3.Error):
        pass  # the daily run dedupes too

