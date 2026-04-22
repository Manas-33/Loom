from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = REPO_ROOT / "jobs"
OUTPUT_DIR = REPO_ROOT / "output"
STATIC_DIR = REPO_ROOT / "dashboard" / "static"
INDEX_FILE = STATIC_DIR / "index.html"
STATUS_FILE = REPO_ROOT / "dashboard_statuses.json"
JOB_STATUSES = ("Not Applied", "Applied", "Ignore")

RESUME_PROMPT = (
    "Read prompts/TASK.md, cv.md, and templates/template.tex. "
    "Then process only this one job file: {job_file}. "
    "Write the tailored resume to the output path listed inside it."
)
COVER_PROMPT = (
    "Read prompts/cover_letter_task.md, cv.md, and templates/cover_letter_template.md. "
    "Then process only this one job file: {job_file}. "
    "Write the cover letter data to output/{slug}/cover_letter.json "
    "(valid JSON only, schema in templates/cover_letter_template.md)."
)


class PrepareRequest(BaseModel):
    limit: int | None = None
    filter_company: str | None = None
    filter_category: str | None = None
    skip_existing: bool = True


class JobRunRequest(BaseModel):
    slug: str | None = None
    slugs: list[str] = Field(default_factory=list)
    all_missing: bool = False


class ScriptRunRequest(BaseModel):
    skip_existing: bool = True


class StatusUpdateRequest(BaseModel):
    status: str


@dataclass
class RunState:
    run_id: str
    title: str
    queue: queue.Queue[str | None] = field(default_factory=queue.Queue)
    status: str = "running"
    process: subprocess.Popen[str] | None = None
    created_at: float = field(default_factory=time.time)
    error: str | None = None
    cancel_requested: bool = False


class RunManager:
    def __init__(self) -> None:
        self.runs: dict[str, RunState] = {}
        self._lock = threading.Lock()

    def create(self, title: str) -> RunState:
        run_id = uuid.uuid4().hex
        state = RunState(run_id=run_id, title=title)
        with self._lock:
            self.runs[run_id] = state
        return state

    def get(self, run_id: str) -> RunState:
        state = self.runs.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return state

    async def emit(self, state: RunState, event: str, data: Any) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        state.queue.put(payload)

    async def finish(self, state: RunState, status: str, error: str | None = None) -> None:
        state.status = status
        state.error = error
        await self.emit(state, "status", {"status": status, "error": error})
        state.queue.put(None)


manager = RunManager()

app = FastAPI(title="Loom Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _load_statuses() -> dict[str, str]:
    if not STATUS_FILE.exists():
        return {}
    try:
        raw = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(slug): status
        for slug, status in raw.items()
        if isinstance(status, str) and status in JOB_STATUSES
    }


def _save_statuses(statuses: dict[str, str]) -> None:
    STATUS_FILE.write_text(json.dumps(statuses, indent=2, sort_keys=True), encoding="utf-8")


def _get_status_for_slug(slug: str) -> str:
    return _load_statuses().get(slug, "Not Applied")


def _read_job_markdown(path: Path) -> dict[str, str]:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    title_line = next((line for line in lines if line.startswith("# Job: ")), "")
    title = ""
    company = ""
    if title_line:
        title_bits = title_line.removeprefix("# Job: ").split(" at ", maxsplit=1)
        title = title_bits[0].strip()
        if len(title_bits) == 2:
            company = title_bits[1].strip()

    detail_map = {
        "Company": company,
        "Title": title,
        "Location": "",
        "Category": "",
        "Salary": "",
    }
    for line in lines:
        if not line.startswith("- **"):
            continue
        try:
            label, value = line.removeprefix("- **").split(":** ", maxsplit=1)
        except ValueError:
            continue
        detail_map[label.strip()] = value.strip()

    return {
        "company": detail_map["Company"],
        "title": detail_map["Title"],
        "location": detail_map["Location"],
        "category": detail_map["Category"],
        "salary": detail_map["Salary"],
    }


def _job_payload(job_file: Path) -> dict[str, Any]:
    slug = job_file.stem
    details = (
        _read_job_markdown(job_file)
        if job_file.exists()
        else {
            "company": "",
            "title": "",
            "location": "",
            "category": "",
            "salary": "",
        }
    )
    output_dir = OUTPUT_DIR / slug
    files = {
        "job_md": job_file.exists(),
        "resume_tex": (output_dir / "resume.tex").exists(),
        "resume_pdf": (output_dir / "resume.pdf").exists(),
        "cover_letter_json": (output_dir / "cover_letter.json").exists(),
        "cover_letter_docx": (output_dir / "cover_letter.docx").exists(),
    }
    return {
        "slug": slug,
        **details,
        "status": _get_status_for_slug(slug),
        "available_statuses": list(JOB_STATUSES),
        "job_file": str(job_file.relative_to(REPO_ROOT)),
        "output_dir": str(output_dir.relative_to(REPO_ROOT)),
        "artifacts": files,
    }


def list_jobs() -> list[dict[str, Any]]:
    job_slugs = {path.stem for path in JOBS_DIR.glob("*.md")} if JOBS_DIR.exists() else set()
    output_slugs = {path.name for path in OUTPUT_DIR.iterdir() if path.is_dir()} if OUTPUT_DIR.exists() else set()
    all_slugs = sorted(job_slugs | output_slugs)
    return [_job_payload(JOBS_DIR / f"{slug}.md") for slug in all_slugs]


def diagnostics() -> dict[str, Any]:
    python_exe = shutil.which("python") or shutil.which("python3")
    packages = {}
    for module in ("fastapi", "uvicorn", "pandas", "openpyxl", "docx"):
        try:
            __import__(module)
            packages[module] = True
        except ImportError:
            packages[module] = False

    return {
        "commands": {
            "python": python_exe,
            "opencode": shutil.which("opencode"),
            "pdflatex": shutil.which("pdflatex"),
        },
        "packages": packages,
        "files": {
            "jobs_xlsx": (REPO_ROOT / "jobs.xlsx").exists(),
            "cv_md": (REPO_ROOT / "cv.md").exists(),
            "jobs_dir": JOBS_DIR.exists(),
            "output_dir": OUTPUT_DIR.exists(),
        },
    }


def _resolve_output_file(slug: str, filename: str) -> Path:
    safe_name = Path(filename).name
    path = OUTPUT_DIR / slug / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return path


def _text_preview_html(path: Path) -> str:
    content = html.escape(path.read_text(encoding="utf-8"))
    title = html.escape(path.name)
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        padding: 24px;
        background: #191614;
        color: #f5efe8;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      }}
      main {{
        max-width: 1100px;
        margin: 0 auto;
      }}
      h1 {{
        margin: 0 0 16px;
        font: 600 1.1rem system-ui, sans-serif;
      }}
      pre {{
        margin: 0;
        padding: 20px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
        border-radius: 18px;
        background: #231d19;
        border: 1px solid rgba(255,255,255,0.08);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <pre>{content}</pre>
    </main>
  </body>
</html>"""


def _inline_file_response(path: Path) -> Response:
    suffix = path.suffix.lower()
    if suffix in {".json", ".tex", ".md", ".txt"}:
        return HTMLResponse(_text_preview_html(path))

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Content-Disposition": f'inline; filename="{path.name}"'}
    return FileResponse(path, media_type=media_type, headers=headers)


def _resolve_targets(request: JobRunRequest, artifact_name: str) -> list[Path]:
    if request.slug:
        candidates = [JOBS_DIR / f"{request.slug}.md"]
    elif request.slugs:
        candidates = [JOBS_DIR / f"{slug}.md" for slug in request.slugs]
    else:
        candidates = list(JOBS_DIR.glob("*.md"))

    targets = [path for path in candidates if path.exists()]
    if request.all_missing:
        filtered: list[Path] = []
        for path in targets:
            slug = path.stem
            artifact_path = OUTPUT_DIR / slug / artifact_name
            if not artifact_path.exists():
                filtered.append(path)
        targets = filtered
    return sorted(targets)


def _prepare_command(request: PrepareRequest) -> list[str]:
    cmd = ["python", "scripts/prepare_jobs.py"]
    if request.skip_existing:
        cmd.append("--skip-existing")
    if request.limit is not None:
        cmd.extend(["--limit", str(request.limit)])
    if request.filter_company:
        cmd.extend(["--filter-company", request.filter_company])
    if request.filter_category:
        cmd.extend(["--filter-category", request.filter_category])
    return cmd


async def _stream_process(state: RunState, cmd: list[str], label: str) -> int:
    await manager.emit(state, "log", {"line": f"$ {' '.join(cmd)}", "label": label})
    process = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    state.process = process
    assert process.stdout is not None
    loop = asyncio.get_running_loop()

    while True:
        line = await loop.run_in_executor(None, process.stdout.readline)
        if not line:
            break
        await manager.emit(state, "log", {"line": line.rstrip("\n"), "label": label})

    return_code = await loop.run_in_executor(None, process.wait)
    state.process = None
    return return_code


async def _run_prepare(state: RunState, request: PrepareRequest) -> None:
    code = await _stream_process(state, _prepare_command(request), "prepare")
    if code != 0:
        raise RuntimeError(f"prepare_jobs.py exited with code {code}")


async def _run_opencode(state: RunState, request: JobRunRequest, mode: str) -> None:
    artifact = "resume.tex" if mode == "resume" else "cover_letter.json"
    targets = _resolve_targets(request, artifact)
    if not targets:
        await manager.emit(state, "log", {"line": "No matching jobs found.", "label": mode})
        return

    for path in targets:
        slug = path.stem
        prompt = RESUME_PROMPT.format(job_file=path.relative_to(REPO_ROOT).as_posix())
        label = f"{mode}:{slug}"
        if mode == "cover":
            prompt = COVER_PROMPT.format(
                job_file=path.relative_to(REPO_ROOT).as_posix(),
                slug=slug,
            )

        await manager.emit(state, "log", {"line": f"Processing {slug}", "label": label})
        code = await _stream_process(state, ["opencode", "run", prompt], label)
        if code != 0:
            raise RuntimeError(f"opencode {mode} exited with code {code} for {slug}")


async def _run_script(state: RunState, script_name: str, skip_existing: bool) -> None:
    cmd = ["python", f"scripts/{script_name}"]
    if skip_existing:
        cmd.append("--skip-existing")
    code = await _stream_process(state, cmd, script_name)
    if code != 0:
        raise RuntimeError(f"{script_name} exited with code {code}")


async def _pipeline(state: RunState) -> None:
    await _run_prepare(state, PrepareRequest(skip_existing=True))
    await _run_opencode(state, JobRunRequest(all_missing=True), "resume")
    await _run_opencode(state, JobRunRequest(all_missing=True), "cover")
    await _run_script(state, "compile_pdfs.py", skip_existing=True)
    await _run_script(state, "build_cover_letters.py", skip_existing=True)


def _launch(title: str, runner) -> dict[str, str]:
    state = manager.create(title)

    async def task_wrapper() -> None:
        try:
            await runner(state)
            if state.status != "cancelled":
                await manager.finish(state, "completed")
        except Exception as exc:  # noqa: BLE001
            if state.status == "cancelled" or state.cancel_requested:
                await manager.finish(state, "cancelled")
                return
            await manager.emit(state, "log", {"line": f"ERROR: {exc}", "label": "system"})
            await manager.finish(state, "failed", str(exc))

    threading.Thread(target=lambda: asyncio.run(task_wrapper()), daemon=True).start()
    return {"run_id": state.run_id, "stream_url": f"/api/runs/{state.run_id}/stream"}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/api/jobs")
async def api_jobs() -> JSONResponse:
    return JSONResponse({"jobs": list_jobs()})


@app.post("/api/jobs/{slug}/status")
async def update_job_status(slug: str, request: StatusUpdateRequest) -> JSONResponse:
    if request.status not in JOB_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    statuses = _load_statuses()
    statuses[slug] = request.status
    _save_statuses(statuses)
    return JSONResponse({"slug": slug, "status": request.status})


@app.get("/api/diagnostics")
async def api_diagnostics() -> JSONResponse:
    return JSONResponse(diagnostics())


@app.get("/api/files/{slug}/{filename}")
async def api_file(slug: str, filename: str) -> FileResponse:
    path = _resolve_output_file(slug, filename)
    return FileResponse(path)


@app.get("/view/{slug}/{filename}")
async def view_file(slug: str, filename: str) -> Response:
    path = _resolve_output_file(slug, filename)
    return _inline_file_response(path)


@app.post("/api/run/prepare")
async def run_prepare(request: PrepareRequest) -> JSONResponse:
    return JSONResponse(_launch("Prepare jobs", lambda state: _run_prepare(state, request)))


@app.post("/api/run/opencode-resume")
async def run_opencode_resume(request: JobRunRequest) -> JSONResponse:
    return JSONResponse(_launch("Tailor resumes", lambda state: _run_opencode(state, request, "resume")))


@app.post("/api/run/opencode-cover")
async def run_opencode_cover(request: JobRunRequest) -> JSONResponse:
    return JSONResponse(_launch("Write cover letters", lambda state: _run_opencode(state, request, "cover")))


@app.post("/api/run/compile-pdfs")
async def run_compile_pdfs(request: ScriptRunRequest) -> JSONResponse:
    return JSONResponse(
        _launch(
            "Compile PDFs",
            lambda state: _run_script(state, "compile_pdfs.py", request.skip_existing),
        )
    )


@app.post("/api/run/build-cover-docx")
async def run_build_cover_docx(request: ScriptRunRequest) -> JSONResponse:
    return JSONResponse(
        _launch(
            "Build cover letters",
            lambda state: _run_script(state, "build_cover_letters.py", request.skip_existing),
        )
    )


@app.post("/api/run/pipeline")
async def run_pipeline() -> JSONResponse:
    return JSONResponse(_launch("Full pipeline", _pipeline))


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    state = manager.get(run_id)

    async def event_stream():
        await manager.emit(state, "status", {"status": state.status, "title": state.title})
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, state.queue.get)
            if item is None:
                break
            yield item

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> JSONResponse:
    state = manager.get(run_id)
    process = state.process
    if process and process.poll() is None:
        state.cancel_requested = True
        os.killpg(process.pid, signal.SIGTERM)
        state.status = "cancelled"
        await manager.emit(state, "log", {"line": "Cancellation requested.", "label": "system"})
    return JSONResponse({"run_id": run_id, "status": state.status})
