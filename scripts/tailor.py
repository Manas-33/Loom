#!/usr/bin/env python3
"""
Tailor saved jobs' resumes (the pick-resume-auto skill) and keep each job's
state in output/<slug>/tailor.json for the dashboard.

One model session per job. Claude (Opus) is the default engine; Codex can be
chosen instead, and when Claude's usage runs out on a job's first turn, the job
is retried with Codex (settings in data/tailor_settings.json).

Both engines are locked down to the same things: read, web search, edit only
that job's resume, run only scripts/tailor_build.py for that job.
  - Claude: `claude -p --restricted --permission-prompts none` with an allowlist.
  - Codex: `codex exec` in the workspace-write sandbox rooted at output/<slug>/
    (no /tmp, no network apart from its web search tool).

Owner decisions that need no model run right away: Use (apply a tweak's exact
before → after), Skip (revert it), Send as-is. The session is resumed only to
rewrite a tweak (Change…), fit an approved tweak that broke the page, or draft
an outreach note.

Kept jobs are tailored in the background by start_workers()/enqueue(), 2 at a
time, when auto-tailor is on.

Usage (from repo root):
  python scripts/tailor.py start <slug> [--engine codex]
  python scripts/tailor.py decide <slug> --approve 1 3 --reject 2
  python scripts/tailor.py decide <slug> --change 2 "keep Go in the line"
  python scripts/tailor.py decide <slug> --as-is
  python scripts/tailor.py answers <slug>       # read the form, draft its answers (app-answers)
  python scripts/tailor.py show <slug>
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tailor_build  # noqa: E402
import tailor_score  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
JOBS_DIR = REPO_ROOT / "jobs"
SETTINGS_FILE = REPO_ROOT / "data" / "tailor_settings.json"
# auto_review (the owner's choice, 2026-09-30): tweaks and drafted answers go through without a Review stop, since
# the owner checks the filled form before submitting; a job marked for review (state["review"]) still stops.
# parallel: jobs tailored (or answered) at the same time, each in its own session
MAX_PARALLEL = 10
MAX_FILL_PARALLEL = 3  # fills share the owner's one Chrome, each in its own tab
DEFAULT_SETTINGS = {"auto_tailor": True, "engine": "claude", "fallback": True, "auto_answers": True, "fill_engine": "claude",
                    "auto_review": True, "parallel": 2, "fill_parallel": 1}
ENGINES = ("claude", "codex")
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
CODEX = shutil.which("codex") or str(Path.home() / ".local" / "bin" / "codex")
CLAUDE_MODEL, CLAUDE_EFFORT = "claude-opus-5-5", "high"
CODEX_MODEL, CODEX_EFFORT = "gpt-5.6-sol", "xhigh"  # extra high: the owner's choice
TURN_TIMEOUT = 1200  # seconds; a first turn with web searches usually takes 1-3 minutes
BUCKETS = ["ai-agents", "mle", "mobile", "generalist"]
STATUSES = ["pending", "applied", "rejected", "didn't fit"]
RESUME = "Manas_Dalvi_Resume.tex"
# How Claude reports that the plan's usage is used up
USAGE_LIMIT = re.compile(r"usage limit|limit reached|rate.?limit|quota|credit balance|extra usage|out of (usage|credits)", re.I)

_KEYWORD = {"type": "object", "additionalProperties": False, "required": ["keyword", "tier", "note"],
            "properties": {"keyword": {"type": "string"}, "tier": {"type": "string", "enum": ["min", "pref"]},
                           "note": {"type": "string"}}}
# quote = the resume text that covers the keyword; tailor_score checks it's really in the file
_PRESENT = {"type": "object", "additionalProperties": False, "required": ["keyword", "tier", "quote"],
            "properties": {"keyword": {"type": "string"}, "tier": {"type": "string", "enum": ["min", "pref"]},
                           "quote": {"type": "string"}}}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["bucket", "route_reason", "domain_note", "keywords", "preferred_coverage", "recommendation", "owner_vouched",
                 "recommendation_reason", "tweaks", "build_ok", "sponsorship_blocker", "boost", "reminders", "message"],
    "properties": {
        "bucket": {"type": "string", "enum": BUCKETS},
        "route_reason": {"type": "string"},
        "domain_note": {"type": "string"},
        "keywords": {
            "type": "object", "additionalProperties": False, "required": ["present", "missing", "not_claimable"],
            "properties": {"present": {"type": "array", "items": _PRESENT},
                           "missing": {"type": "array", "items": _KEYWORD},  # note = the cv.md evidence
                           "not_claimable": {"type": "array", "items": _KEYWORD}},
        },
        "preferred_coverage": {"type": "string"},
        "recommendation": {"type": "string", "enum": ["send as-is", "apply tweaks"]},
        "recommendation_reason": {"type": "string"},
        "tweaks": {"type": "array", "maxItems": 6, "items": {  # 3 on the first turn; owner comments can add more
            "type": "object", "additionalProperties": False,
            "required": ["id", "summary", "before", "after", "why", "evidence", "covers", "status"],
            "properties": {"id": {"type": "integer"}, "summary": {"type": "string"}, "before": {"type": "string"},
                           "after": {"type": "string"}, "why": {"type": "string"}, "evidence": {"type": "string"},
                           "covers": {"type": "array", "items": {"type": "string"}},  # missing keywords it adds
                           "status": {"type": "string", "enum": STATUSES}},
        }},
        "build_ok": {"type": "boolean"},
        "sponsorship_blocker": {"type": "boolean"},
        "boost": {
            "type": "object", "additionalProperties": False,
            "required": ["sponsorship", "process", "referrals", "outreach", "timing"],
            "properties": {"sponsorship": {"type": "string"}, "process": {"type": "string"},
                           "referrals": {"type": "array", "items": {"type": "string"}},
                           "outreach": {"type": "string"}, "timing": {"type": "string"}},
        },
        "reminders": {"type": "array", "items": {"type": "string"}},
        "message": {"type": "string"},
        "owner_vouched": {"type": "array", "items": {"type": "string"}},  # skills the owner said they have
    },
}


class TailorError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Settings ─────────────────────────────────────────────────────────

def get_settings() -> dict:
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in saved.items() if k in DEFAULT_SETTINGS}}


def save_settings(changes: dict) -> dict:
    settings = get_settings()
    for key, value in changes.items():
        if key in ("engine", "fill_engine") and value not in ENGINES:
            raise TailorError(f"{key} must be one of {', '.join(ENGINES)}")
        if key in ("auto_tailor", "fallback", "auto_answers", "auto_review"):
            value = bool(value)
        if key == "parallel":
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_PARALLEL:
                raise TailorError(f"parallel must be a whole number from 1 to {MAX_PARALLEL}")
        if key == "fill_parallel":
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_FILL_PARALLEL:
                raise TailorError(f"fill_parallel must be a whole number from 1 to {MAX_FILL_PARALLEL}")
        if key in DEFAULT_SETTINGS:
            settings[key] = value
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    if settings["auto_tailor"]:
        _wake()
    return settings


# ── State ────────────────────────────────────────────────────────────

def job_dir(slug: str) -> Path:
    path = (OUTPUT_DIR / slug).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not (JOBS_DIR / f"{slug}.md").is_file():
        raise TailorError("No saved job with that name")
    return path


def _lock_path(slug: str) -> Path:
    return job_dir(slug) / ".tailor.lock"


def _lock_alive(slug: str) -> bool:
    try:
        pid = int(_lock_path(slug).read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def load_state(slug: str) -> dict | None:
    path = job_dir(slug) / "tailor.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if state.get("status") == "running" and not _lock_alive(slug):
        state.update(status="failed", error="The last run stopped before finishing (the dashboard or Mac restarted?).")
    build = job_dir(slug) / "build.json"
    if build.exists():
        try:
            state["build"] = json.loads(build.read_text(encoding="utf-8"))
        except ValueError:
            pass
    coverage = _coverage(slug, state)
    if coverage:
        state["coverage"] = coverage
    return state


def _as_is_tex(slug: str) -> str:
    """The bucket resume this job started from (base.tex), or the resume file before any tweak."""
    out = job_dir(slug)
    for name in ("base.tex", RESUME):
        try:
            return (out / name).read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def _coverage(slug: str, state: dict) -> dict | None:
    """The coverage score for the resume file as it is now (scripts/tailor_score.py)."""
    if not state.get("coverage_base"):
        return None
    try:
        tex = (job_dir(slug) / RESUME).read_text(encoding="utf-8")
    except OSError:
        return None
    return tailor_score.score(state["coverage_base"], state.get("result"), tex, _as_is_tex(slug))


def save_state(slug: str, state: dict) -> None:
    out = job_dir(slug)
    out.mkdir(parents=True, exist_ok=True)
    state["updated"] = _now()
    tmp = out / "tailor.json.tmp"
    tmp.write_text(json.dumps({k: v for k, v in state.items() if k not in ("build", "coverage")}, indent=2),
                   encoding="utf-8")
    tmp.replace(out / "tailor.json")


def begin(slug: str, action: str, engine: str | None = None) -> dict:
    """Take the job's lock and mark a turn as running; raises if one is already running."""
    out = job_dir(slug)
    out.mkdir(parents=True, exist_ok=True)
    state = load_state(slug) or {"slug": slug, "turns": []}
    if state.get("status") == "running":
        raise TailorError("Tailoring is already running for this job")
    if action != "start" and not state.get("result"):
        raise TailorError("Tailor this job first")
    try:
        fd = os.open(_lock_path(slug), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # run_turn saves the finished state just before it drops the lock, so a lock
        # left behind by a turn whose state isn't "running" is stale
        if _lock_alive(slug) and (load_state(slug) or {}).get("status") == "running":
            raise TailorError("Tailoring is already running for this job")
        _lock_path(slug).unlink(missing_ok=True)
        fd = os.open(_lock_path(slug), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    if action == "start":
        engine = engine or get_settings()["engine"]
        state = {"slug": slug, "engine": engine, "session_id": str(uuid.uuid4()) if engine == "claude" else None,
                 "turns": [], "result": None}
    state.update(status="running", action=action, error="", running_since=_now())
    state.pop("queued_at", None)
    save_state(slug, state)
    return state


def _finish(slug: str, state: dict) -> dict:
    state.pop("running_since", None)
    save_state(slug, state)
    _lock_path(slug).unlink(missing_ok=True)
    return load_state(slug) or state


# ── Prompts ──────────────────────────────────────────────────────────

def build_command(slug: str) -> str:
    return f"{sys.executable} {REPO_ROOT / 'scripts' / 'tailor_build.py'} {slug}"


# ── Skills the owner confirmed (their word counts as evidence; the owner's choice, 2026-10-01) ──

def _vouched_file() -> Path:
    return REPO_ROOT / "data" / "vouched_skills.json"


def vouched_skills() -> list[dict]:
    try:
        skills = json.loads(_vouched_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [s for s in skills if isinstance(s, dict) and str(s.get("skill") or "").strip()]


def save_vouched(skills: list, slug: str = "") -> list[dict]:
    """Remember skills the owner said they have, so every later tailoring counts them as backed."""
    current = vouched_skills()
    known = {s["skill"].casefold() for s in current}
    added = False
    for skill in skills:
        name = " ".join(str(skill or "").split())[:80]
        if name and name.casefold() not in known:
            current.append({"skill": name, "added": date.today().isoformat(), "job": slug})
            known.add(name.casefold())
            added = True
    if added:
        _vouched_file().parent.mkdir(parents=True, exist_ok=True)
        _vouched_file().write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def remove_vouched(skill: str) -> list[dict]:
    kept = [s for s in vouched_skills() if s["skill"].casefold() != str(skill).strip().casefold()]
    _vouched_file().parent.mkdir(parents=True, exist_ok=True)
    _vouched_file().write_text(json.dumps(kept, indent=2), encoding="utf-8")
    return kept


def _vouched_line() -> str:
    skills = vouched_skills()
    if not skills:
        return ""
    return ("Skills the owner confirmed (count them as backed, evidence \"your word\"; never invent anything around "
            "them): " + ", ".join(f"{s['skill']} (confirmed {s['added']})" for s in skills) + ".\n")


def first_prompt(slug: str) -> str:
    build = build_command(slug)
    return (f"Tailor {slug}.\n\n"
            f"Read {REPO_ROOT / '.claude/skills/pick-resume-auto/SKILL.md'} first and follow it. "
            f"The repo root is {REPO_ROOT}; the job is {JOBS_DIR / (slug + '.md')}; "
            f"the only file you may edit is {job_dir(slug) / RESUME}.\n"
            f"Read whatever you need (the job, cv.md, the bucket resumes, the skills). "
            f"Apart from reading files, the only commands you may run:\n  {build} start <bucket>\n  {build} build\n"
            + _vouched_line()
            + f"Today is {date.today():%B %d, %Y}.")


def later_prompt(slug: str, done: list[str], todo: list[str], tweaks: list[dict] | None = None) -> str:
    build = build_command(slug)
    lines = [f"Decisions for {slug}, from the owner. Follow the \"Later turns\" section of "
             f"{REPO_ROOT / '.claude/skills/pick-resume-auto/SKILL.md'}."]
    if tweaks:
        lines.append("Current tweak statuses (the dashboard may have changed some since your last turn; the resume "
                     "file matches these): " + ", ".join(f"{t['id']} {t['status']}" for t in tweaks) + ".")
    if done:
        lines.append("Already done by the dashboard (the resume file reflects it; don't redo it): " + "; ".join(done) + ".")
    lines.append("Still to do:")
    lines += [f"- {t}" for t in todo]
    lines.append("In the output, every `keywords.present` item needs its `tier` and a `quote` copied exactly from the "
                 "resume file, and every tweak needs `covers` (the missing keywords it puts on the page, [] if none). "
                 "Keep keyword names the same as in your earlier turns.")
    lines.append(f"Apart from reading files, the only commands you may run:\n  {build} start <bucket>\n  {build} build")
    if _vouched_line():
        lines.append(_vouched_line().strip())
    return "\n".join(lines)


# ── Engines ──────────────────────────────────────────────────────────

def _claude_env() -> dict[str, str]:
    """This process's environment minus what a parent Claude Code session sets. A nested
    `claude` that inherits those tries the parent's login instead of the saved one."""
    nested = "CLAUDECODE" in os.environ
    return {k: v for k, v in os.environ.items()
            if not (k == "CLAUDECODE" or k.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_", "CLAUDE_PREVIEW_"))
                    or k in ("CLAUDE_PID", "CLAUDE_EFFORT") or (nested and k.startswith("ANTHROPIC_")))}


def claude_args(slug: str, session_id: str, resume: bool, schema: dict | None = None) -> list[str]:
    build = build_command(slug)
    return [
        CLAUDE,
        "--restricted",                      # no code-running tools or WebFetch unless named; no settings files
        "--tools", "Read,Glob,Grep,Edit,Bash,WebSearch",
        "--allowedTools", "Read", "Glob", "Grep", "WebSearch",
        f"Edit(/{job_dir(slug) / RESUME})",  # "//abs/path": only this job's resume
        f"Bash({build} start:*)", f"Bash({build} build)",
        "--permission-prompts", "none",      # anything not allowed above is denied, nobody is asked
        "--strict-mcp-config",
        "--model", CLAUDE_MODEL, "--effort", CLAUDE_EFFORT,
        "--output-format", "json", "--json-schema", json.dumps(schema or SCHEMA),
        *(["--resume", session_id] if resume else ["--session-id", session_id]),
    ]


def codex_args(slug: str, session_id: str | None, schema: Path, out: Path) -> list[str]:
    common = ["-m", CODEX_MODEL, "-c", f"model_reasoning_effort={CODEX_EFFORT}", "-c", "notify=[]",
              "-c", 'sandbox_mode="workspace-write"',
              "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
              "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
              "--skip-git-repo-check", "--output-schema", str(schema), "-o", str(out), "--json"]
    if session_id:
        return [CODEX, "--search", "exec", "resume", session_id, *common]
    return [CODEX, "--search", "exec", "-s", "workspace-write", "-C", str(job_dir(slug)), *common]


def _denial(d) -> dict:
    """{tool, detail} for something the session tried and wasn't allowed to do."""
    if not isinstance(d, dict):
        return {"tool": str(d), "detail": ""}
    inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    detail = inp.get("command") or inp.get("file_path") or inp.get("url") or inp.get("pattern") or inp.get("query")
    return {"tool": str(d.get("tool_name") or "unknown"), "detail": str(detail or json.dumps(inp))[:200]}


def _run_claude(slug: str, state: dict, prompt: str, schema: dict | None = None) -> tuple[dict, list]:
    resume = bool(state.get("turns"))
    proc = subprocess.run([*claude_args(slug, state["session_id"], resume, schema), "-p", prompt],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=TURN_TIMEOUT,
                          stdin=subprocess.DEVNULL, env=_claude_env())
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise TailorError((proc.stderr or proc.stdout or "claude printed nothing").strip()[-400:])
    if envelope.get("is_error"):
        raise TailorError(str(envelope.get("result") or envelope.get("terminal_reason") or "claude failed")[:400])
    result = envelope.get("structured_output")
    if not isinstance(result, dict):
        raise TailorError("Claude finished without the structured result")
    return result, [_denial(d) for d in envelope.get("permission_denials") or []]


_BLOCKED = re.compile(r"operation not permitted|permission denied|read-only file system", re.I)


def _run_codex(slug: str, state: dict, prompt: str, schema_doc: dict | None = None) -> tuple[dict, list]:
    with tempfile.TemporaryDirectory(prefix="loom-tailor-") as tmp:
        schema, out = Path(tmp) / "schema.json", Path(tmp) / "answer.json"
        schema.write_text(json.dumps(schema_doc or SCHEMA), encoding="utf-8")
        proc = subprocess.run([*codex_args(slug, state.get("session_id"), schema, out), prompt],
                              capture_output=True, text=True, cwd=job_dir(slug), timeout=TURN_TIMEOUT,
                              stdin=subprocess.DEVNULL)
        denied, errors = [], []
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and event.get("thread_id"):
                state["session_id"] = event["thread_id"]
            item = event.get("item") or {}
            if (event.get("type") == "item.completed" and item.get("type") == "command_execution"
                    and item.get("exit_code") not in (0, None) and _BLOCKED.search(item.get("aggregated_output") or "")):
                denied.append({"tool": "command", "detail": str(item.get("command"))[:200]})
            if event.get("type") in ("error", "turn.failed"):
                errors.append(str(event.get("message") or (event.get("error") or {}).get("message") or event)[:300])
        if proc.returncode != 0 or not out.exists():
            detail = errors[-1] if errors else (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            raise TailorError(f"codex failed: {detail if isinstance(detail, str) else detail[0]}"[:400])
        try:
            result = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise TailorError("Codex returned something that isn't JSON")
    return result, denied


def _run_engine(engine: str, slug: str, state: dict, prompt: str, schema: dict | None = None) -> tuple[dict, list]:
    return (_run_codex if engine == "codex" else _run_claude)(slug, state, prompt, schema)


def run_turn(slug: str, prompt: str, summary: str, done: str = "", frozen: set | None = None,
             kind: str = "tailor", comment: str = "") -> dict:
    """Run one model turn of the job's session. begin() must have been called. Tweaks (or, for an answers
    turn, questions) in `frozen` weren't part of this turn's work: the dashboard's version of them wins."""
    state = load_state(slug) or {}
    if kind == "answers":
        return _run_answers_turn(slug, state, prompt, summary, frozen)
    before = {t["id"]: t for t in ((state.get("result") or {}).get("tweaks") or [])}
    old_bucket = (state.get("result") or {}).get("bucket")
    engine = state.get("engine") or "claude"
    started = time.monotonic()
    try:
        try:
            result, denied = _run_engine(engine, slug, state, prompt)
        except TailorError as exc:
            first = not state.get("turns")
            if not (engine == "claude" and USAGE_LIMIT.search(str(exc))):
                raise
            if not (first and get_settings()["fallback"]):
                raise TailorError(f"Claude's usage has run out ({exc}). Try again after it resets, or turn on "
                                  "the Codex fallback / switch to Codex and start over.")
            # First turn and Claude is out of usage: the job starts over with Codex
            engine = "codex"
            state.update(engine="codex", session_id=None, fell_back=f"Claude: {str(exc)[:160]}")
            save_state(slug, state)
            result, denied = _run_engine("codex", slug, state, first_prompt(slug))
        if frozen:
            tweaks = [before[t["id"]] if t["id"] in frozen and t["id"] in before else t for t in result.get("tweaks") or []]
            tweaks += [before[i] for i in sorted(frozen) if i in before and i not in {t["id"] for t in tweaks}]
            result["tweaks"] = sorted(tweaks, key=lambda t: t["id"])
        state.update(status="ready", result=result, error="")
        save_vouched(result.get("owner_vouched") or [], slug)
        # The keyword list is frozen once, against the as-is resume; a new bucket (an owner comment) starts it again
        if not state.get("coverage_base") or (old_bucket and result.get("bucket") != old_bucket):
            base = tailor_score.baseline(result, _as_is_tex(slug))
            if base:
                state["coverage_base"] = base
        state.setdefault("turns", []).append({
            "at": _now(), "action": summary, "engine": engine, "seconds": round(time.monotonic() - started),
            "message": (done + " " if done else "") + result.get("message", ""), "denied": denied,
            **({"comment": comment} if comment else {}),
        })
    except (TailorError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        reason = f"took longer than {TURN_TIMEOUT // 60} minutes" if isinstance(exc, subprocess.TimeoutExpired) \
            else f"the {engine} command isn't installed" if isinstance(exc, FileNotFoundError) else str(exc)
        state.update(status="failed", error=reason)
    return _finish(slug, state)


# ── Decisions: instant where possible ─────────────────────────────────

def _validate(state: dict, approve, reject, change: dict, as_is: bool, extra: str, comment: str = "") -> None:
    if not state.get("result"):
        raise TailorError("Tailor this job first")
    known = {t["id"] for t in state["result"].get("tweaks") or []}
    unknown = sorted((set(approve) | set(reject) | set(change)) - known)
    if unknown:
        raise TailorError(f"No tweak with id {', '.join(map(str, unknown))}")
    if not (approve or reject or change or as_is or extra.strip() or comment.strip()):
        raise TailorError("Nothing to do")


def prepare_decision(slug: str, approve=(), reject=(), change: dict | None = None, as_is: bool = False,
                     extra: str = "", comment: str = "") -> dict:
    """Check the decisions make sense (raises TailorError) and return them normalised."""
    change = {int(k): str(v) for k, v in (change or {}).items() if str(v).strip()}
    approve, reject = sorted(set(map(int, approve))), sorted(set(map(int, reject)))
    _validate(load_state(slug) or {}, approve, reject, change, as_is, extra, comment)
    return {"approve": approve, "reject": reject, "change": change, "as_is": as_is, "extra": extra.strip(),
            "comment": comment.strip()}


def _apply_fast(slug: str, state: dict, d: dict) -> tuple[list[str], list[str]]:
    """Do what needs no model: Send as-is, Skip, and Use when the exact text is there and the page
    still builds. Returns (what was done, what the session still has to do)."""
    result = state["result"]
    tweaks = {t["id"]: t for t in result.get("tweaks") or []}
    tex_file = job_dir(slug) / RESUME
    done, todo = [], []
    if d["as_is"]:
        tailor_build.start(slug, result["bucket"])
        for t in tweaks.values():
            t["status"] = "rejected"
        done.append("sent as-is (back to the bucket resume, every tweak rejected)")
        return done, todo
    before_all = tex_file.read_text(encoding="utf-8")
    tex = before_all
    for tid in d["reject"]:
        t = tweaks[tid]
        if t["status"] == "applied":
            if tex.count(t["after"]) == 1:
                tex = tex.replace(t["after"], t["before"])
            else:
                todo.append(f"Reject tweak {tid}: it's applied, but its text isn't in the file exactly as recorded; "
                            "revert it by hand and rebuild")
                continue
        t["status"] = "rejected"
        done.append(f"rejected tweak {tid}")
    newly = []
    for tid in d["approve"]:
        t = tweaks[tid]
        if t["status"] == "applied":
            continue
        if tex.count(t["before"]) == 1:
            tex = tex.replace(t["before"], t["after"])
            t["status"] = "applied"
            newly.append(tid)
        else:
            todo.append(f"Approve tweak {tid}: its `before` text isn't in the file exactly once, so apply it by hand")
    if tex != before_all:
        tex_file.write_text(tex, encoding="utf-8")
        build = tailor_build.build(slug)
        if not build.get("ok") and newly:
            # One of the new approvals broke the page: undo them and let the session fit them
            failed = [k for k, ok in build.get("checks", {}).items() if not ok] or ["LaTeX didn't compile"]
            for tid in newly:
                tweaks[tid]["status"] = "pending"
                tex = tex.replace(tweaks[tid]["after"], tweaks[tid]["before"], 1)
            tex_file.write_text(tex, encoding="utf-8")
            build = tailor_build.build(slug)
            todo += [f"Approve tweak {tid}: applied as written, the build failed ({', '.join(failed)}). Apply it, "
                     "shorten only that tweak and rebuild, up to 3 tries; if it still fails, revert it and mark it "
                     "didn't fit" for tid in newly]
        else:
            done += [f"applied tweak {tid}" for tid in newly]
        result["build_ok"] = bool(build.get("ok"))
    for tid, feedback in d["change"].items():
        todo.append(f"Change tweak {tid}. The owner's feedback: {feedback.strip()}")
    if d["extra"]:
        todo.append(d["extra"])
    if d.get("comment"):
        todo.append(f"The owner's comment on this resume: \"{d['comment']}\". Follow \"The owner's comment\" in the "
                    "Later turns section: answer it in `message`, and propose any change as a new pending tweak.")
    return done, todo


def decide(slug: str, approve=(), reject=(), change: dict | None = None, as_is: bool = False, extra: str = "",
           background: bool = False, comment: str = "") -> dict:
    """Apply the owner's decisions. Instant ones finish before this returns; anything that needs the
    model resumes the session (in a thread when background=True)."""
    d = prepare_decision(slug, approve, reject, change, as_is, extra, comment)
    state = begin(slug, "decide")
    started = time.monotonic()
    try:
        done, todo = _apply_fast(slug, state, d)
    except (tailor_build.BuildError, OSError, subprocess.SubprocessError) as exc:  # never leave the job locked
        state.update(status="failed", error=f"Couldn't apply that: {exc}")
        return _finish(slug, state)
    summary = ", ".join(p for p in (["send as-is"] if d["as_is"] else []) + ([f"use {d['approve']}"] if d["approve"] else [])
                        + ([f"skip {d['reject']}"] if d["reject"] else []) + ([f"change {sorted(d['change'])}"] if d["change"] else [])
                        + (["request"] if d["extra"] else []) + (["comment"] if d["comment"] else []))
    done_text = ("Done right away: " + "; ".join(done) + ".") if done else ""
    if not todo:
        state["result"]["message"] = done_text[0].upper() + done_text[1:] if done_text else "Nothing changed."
        state.update(status="ready", error="")
        state.setdefault("turns", []).append({"at": _now(), "action": summary, "engine": "dashboard",
                                              "seconds": round(time.monotonic() - started),
                                              "message": state["result"]["message"], "denied": []})
        return _finish(slug, state)
    save_state(slug, state)  # instant results show while the session works on the rest
    tweaks = state["result"].get("tweaks") or []
    prompt = later_prompt(slug, done, todo, tweaks)
    worked_on = {int(m) for line in todo for m in re.findall(r"^(?:Approve|Reject|Change) tweak (\d+)", line)}
    # A comment can touch any tweak (rework one, undo one, switch bucket), so none are frozen then
    frozen = set() if d["comment"] else {t["id"] for t in tweaks} - worked_on
    kwargs = {"comment": d["comment"]}
    if background:
        threading.Thread(target=run_turn, args=(slug, prompt, summary, done_text, frozen), kwargs=kwargs,
                         daemon=True).start()
        return load_state(slug) or state
    return run_turn(slug, prompt, summary, done_text, frozen, **kwargs)


def reviews(state: dict) -> bool:
    """Does the owner look at this job's resume and answers in Review before the fill?"""
    return bool(state.get("review")) if state.get("review") is not None else not get_settings()["auto_review"]


def set_review(slug: str, review: bool) -> dict:
    """The owner's per-job choice: look at the resume and answers in Review (True), or let them through (False)."""
    state = load_state(slug)
    if not state:
        return enqueue(slug, review=review)
    state["review"] = bool(review)
    save_state(slug, state)
    return load_state(slug) or state


def auto_review(slug: str) -> dict | None:
    """An automatic job, just tailored: use every tweak (the build checks keep the page right), mark the resume
    reviewed, and draft the answers."""
    state = load_state(slug) or {}
    if reviews(state) or state.get("reviewed") or state.get("status") != "ready" or not state.get("result"):
        return None
    pending = [t["id"] for t in state["result"].get("tweaks") or [] if t.get("status") == "pending"]
    if pending:
        state = decide(slug, approve=pending)  # may resume the session to fit a tweak; this worker waits
    if (load_state(slug) or {}).get("status") != "ready":
        return None  # it shows in Review with the reason
    state = mark_reviewed(slug)
    state["auto"] = True
    save_state(slug, state)
    if get_settings()["auto_answers"]:
        state = enqueue_answers(slug)
    return state


def mark_glanced(slug: str) -> dict:
    """The owner looked at a job that went through Skip Review ("Looks good"): it leaves Review.
    Start over makes a new state, so a re-tailored job shows up again."""
    state = load_state(slug)
    if not state or not state.get("result"):
        raise TailorError("Tailor this job first")
    state["glanced"] = True
    save_state(slug, state)
    return load_state(slug) or state


def mark_reviewed(slug: str) -> dict:
    """The owner is done with this job in the Review queue (a later Start over clears it)."""
    state = load_state(slug)
    if not state or not state.get("result"):
        raise TailorError("Tailor this job first")
    state["reviewed"] = True
    save_state(slug, state)
    return load_state(slug) or state


# ── Application answers (step 12, the app-answers skill) ──────────────

PROFILE_FILE = REPO_ROOT / "profile.local.yaml"
LIBRARY_FILE = REPO_ROOT / "data" / "answers_library.json"
ANSWER_KINDS = ["fact", "written", "you", "upload", "skip"]


def profile_facts() -> dict:
    """The `application:` section of profile.local.yaml (the only source of facts)."""
    import yaml
    try:
        data = yaml.safe_load(PROFILE_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    # YAML reads unquoted yes/no as booleans; forms need the words
    return {str(k): (None if v is None else ("Yes" if v else "No") if isinstance(v, bool) else str(v))
            for k, v in (data.get("application") or {}).items()}


def answers_schema() -> dict:
    keys = sorted(set(profile_facts()) | {"how_heard"}) + ["none"]
    return {
        "type": "object", "additionalProperties": False, "required": ["answers", "message"],
        "properties": {
            "answers": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "kind", "profile_key", "value", "reason", "general"],
                "properties": {"id": {"type": "string"}, "kind": {"type": "string", "enum": ANSWER_KINDS},
                               "profile_key": {"type": "string", "enum": keys}, "value": {"type": "string"},
                               "reason": {"type": "string"}, "general": {"type": "boolean"}},
            }},
            "message": {"type": "string"},
        },
    }


def _job_row(slug: str) -> dict:
    """The job's sheet row, or what its jobs/<slug>.md records when the sheet doesn't have it."""
    from add_job import Store, job_id_from_url, record_slug
    row = next((r for r in Store(REPO_ROOT).rows() if record_slug(r) == slug), None)
    if row:
        return row
    try:
        text = (JOBS_DIR / f"{slug}.md").read_text(encoding="utf-8")
    except OSError:
        return {}
    fields = dict(re.findall(r"^- \*\*([^*]+):\*\* (.*)$", text, flags=re.M))
    url, apply_url = fields.get("Posting URL", ""), fields.get("Apply URL", "")
    return {"company": fields.get("Company", ""), "title": fields.get("Title", ""), "url": url, "apply_url": apply_url,
            "found_via": [v.strip() for v in fields.get("Found via", "").split(",") if v.strip()],
            "job_id": job_id_from_url(apply_url or url) or ""}


def how_heard(found_via) -> str:
    """The owner's rule (2026-09-30): "Job board" or LinkedIn, whichever the form offers; Handshake finds say so."""
    sources = found_via if isinstance(found_via, list) else [s.strip() for s in str(found_via or "").split(",")]
    return "Handshake" if "handshake" in sources else "LinkedIn" if "linkedin" in sources else "Job board"


# ── Cover letters (the owner's rule, 2026-09-30: write one whenever a form has a cover letter field) ──

LETTER_ID = "cover_letter"
LETTER_FILE = "cover_letter.docx"
_LETTER_LABEL = re.compile(r"cover\s*letter", re.I)


def is_letter(q: dict) -> bool:
    """A form's cover letter field (drafted as a written answer, uploaded as a file)."""
    return q.get("id") == LETTER_ID or (q.get("type") in ("file", "textarea") and bool(_LETTER_LABEL.search(q.get("label") or "")))


def _letter_item(block: dict) -> tuple[str, dict] | None:
    questions = {q["id"]: q for q in block.get("questions") or []}
    for qid, item in (block.get("items") or {}).items():
        if qid in questions and is_letter(questions[qid]):
            return qid, item
    return None


def write_cover_letter(slug: str, text: str) -> Path:
    """The approved letter as output/<slug>/cover_letter.docx (letterhead and sign-off from the build script)."""
    import build_cover_letters
    row = _job_row(slug)
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if len(paragraphs) > 3:  # the template has three body paragraphs; keep the extra text in the middle one
        paragraphs = [paragraphs[0], " ".join(paragraphs[1:-1]), paragraphs[-1]]
    body = dict(zip(("opening", "experience", "closing"), paragraphs))
    location = row.get("location") or ""
    data = {"date": datetime.now().strftime("%B %-d, %Y"), "hiring_manager": "Hiring Manager",
            "company": row.get("company", ""), "location": "" if location == "Not specified" else location, **body}
    out = job_dir(slug)
    (out / "cover_letter.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    build_cover_letters.build_docx(data, str(out / LETTER_FILE))
    return out / LETTER_FILE


def _library(limit: int = 10) -> list[dict]:
    try:
        return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))[-limit:]
    except (OSError, ValueError):
        return []


def _save_to_library(entries: list[dict]) -> None:
    if not entries:
        return
    try:
        library = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        library = []
    known = {(e["question"], e["answer"]) for e in library}
    library += [e for e in entries if (e["question"], e["answer"]) not in known]
    LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_FILE.write_text(json.dumps(library[-200:], indent=2), encoding="utf-8")


def answers_prompt(slug: str, row: dict, change: dict | None = None, only: list[str] | None = None) -> str:
    out = job_dir(slug)
    heard = how_heard(row.get("found_via"))
    if only:  # questions the fill found on a form that couldn't be read ahead
        return (f"Answers for {slug}: filling the application found questions that need your writing. Answer exactly "
                f"the question ids {', '.join(only)} in {out / 'questions.json'}, following "
                f"{REPO_ROOT / '.claude/skills/app-answers/SKILL.md'} (a cover letter per its \"Cover letters\" "
                f"section). Return only those answers.\n"
                f"Facts: the application: section of {PROFILE_FILE}. This job's how_heard value is \"{heard}\".\n"
                f"The job: {JOBS_DIR / (slug + '.md')}. The resume being sent: {out / RESUME}. "
                f"The owner's CV: {REPO_ROOT / 'cv.md'}.\nDon't edit any file or run any command in this turn.")
    if change:
        items = "\n".join(f"- {qid}: {fb.strip()}" for qid, fb in change.items())
        return (f"Answers for {slug}: the owner wants these answers rewritten. Follow the \"Later turns\" section of "
                f"{REPO_ROOT / '.claude/skills/app-answers/SKILL.md'}.\n{items}\n"
                f"The questions are in {out / 'questions.json'}. Don't edit any file or run any command.")
    library = _library()
    return (f"Answers for {slug}.\n\n"
            f"Read {REPO_ROOT / '.claude/skills/app-answers/SKILL.md'} first and follow it.\n"
            f"The form's questions: {out / 'questions.json'}.\n"
            f"Facts: the application: section of {PROFILE_FILE}. This job's how_heard value is \"{heard}\".\n"
            f"The job: {JOBS_DIR / (slug + '.md')}. The resume being sent: {out / RESUME}. "
            f"The owner's CV: {REPO_ROOT / 'cv.md'}.\n"
            "Answers the owner approved for other jobs (reuse only if one truly fits): "
            + (json.dumps([{"question": e["question"], "answer": e["answer"]} for e in library]) if library else "none")
            + "\nDon't edit any file or run any command in this turn.")


# The owner's writing rules (cover-letter + resume-bullet-style), checked on every drafted answer
_STYLE_CHECKS = [
    (re.compile(r"—|\s--\s"), "em dash"),
    (re.compile(r"^\s*I(\s|'m\b|'ve\b|'d\b)"), "opens with I"),
    (re.compile(r"express(ing)? my interest|excited to apply|\baligns?\b|passionate about|hope to hear|"
                r"look forward to (discussing|hearing)|I am writing", re.I), "stock phrase"),
    (re.compile(r"(^|[.!?]\s+)(Furthermore|Moreover|Additionally|Consequently|Ultimately|Overall)\b"), "AI connector"),
    (re.compile(r"\b(architected|engineered|orchestrated|enhanced|streamlin\w*|ensuring|leverag\w*|"
                r"actionable insights|cross-functional teams?)\b", re.I), "banned word"),
    (re.compile(r",\s(ensuring|enabling|driving|allowing|resulting in|leading to)\b", re.I), "trailing -ing clause"),
    (re.compile(r"^\s*What (I|drew me|excites me|stands out)\b", re.I), "cleft opener"),
    (re.compile(r"\b(that'?s|this is) (exactly )?the kind of\b", re.I), "callback closer"),
    (re.compile(r"\b(delve|tapestry|testament to|fast-paced world|in today's)\b", re.I), "AI-sounding word"),
]


def style_issues(text: str) -> list[str]:
    """What in a drafted answer breaks the owner's writing rules (shown on the card; the owner decides)."""
    found = []
    for pattern, label in _STYLE_CHECKS:
        m = pattern.search(text or "")
        if m and label not in [f.split(":")[0] for f in found]:
            found.append(f"{label}: \"{m.group(0).strip()}\"")
    return found


def _store_answers(slug: str, state: dict, result: dict, keep: set | None = None) -> None:
    """Turn the session's answers into answer items. Facts are copied from the profile, never from the
    model; a choice that isn't one of the form's options goes to the owner."""
    facts = profile_facts()
    heard = how_heard(_job_row(slug).get("found_via"))
    block = state["answers"]
    questions = {q["id"]: q for q in block.get("questions") or []}
    old = block.get("items") or {}
    items = {}
    for a in result.get("answers") or []:
        q = questions.get(str(a.get("id")))
        if q is None:
            continue
        if keep and q["id"] in keep and q["id"] in old:
            items[q["id"]] = old[q["id"]]
            continue
        item = {"kind": a["kind"], "profile_key": a.get("profile_key", "none"), "value": a.get("value", "").strip(),
                "reason": a.get("reason", ""), "general": bool(a.get("general")), "status": "draft"}
        if is_letter(q):
            if item["kind"] == "written" and item["value"]:
                item.update(letter=True, general=False)
            else:
                item.update(kind="you", value="", status="needs_you", reason="No cover letter was drafted")
        if item["kind"] == "fact":
            fact = heard if item["profile_key"] == "how_heard" else facts.get(item["profile_key"])
            if not fact:
                item.update(kind="you", value="", status="needs_you",
                            reason=f"Your profile doesn't have this ({item['profile_key']})")
            elif q["type"] in ("select", "multiselect", "boolean"):
                options = q.get("options") or (["Yes", "No"] if q["type"] == "boolean" else [])
                chosen = [c.strip() for c in item["value"].split(" | ")] if q["type"] == "multiselect" else [item["value"]]
                if not all(chosen) or any(c not in options for c in chosen):
                    item.update(kind="you", value="", status="needs_you",
                                reason="None of the options clearly matches your profile")
                else:
                    item.update(value=" | ".join(chosen), status="approved")
            else:
                item.update(value=fact, status="approved")
        elif item["kind"] == "written":
            item["style"] = style_issues(item["value"])
        elif item["kind"] == "you":
            item.update(value="", status="needs_you")
        elif item["kind"] == "upload":
            item["status"] = "approved"
        elif item["kind"] == "skip":
            item["status"] = "skipped"
        items[q["id"]] = item
    for qid, q in questions.items():  # anything the session left out comes to the owner
        items.setdefault(qid, old.get(qid) or {"kind": "you", "profile_key": "none", "value": "", "general": False,
                                               "reason": "No answer was drafted", "status": "needs_you"})
    block["items"] = items
    # nothing to look at (only facts, uploads, skips): no Review card
    block["reviewed"] = not any(i["status"] in ("draft", "needs_you") for i in items.values())


def _run_answers_turn(slug: str, state: dict, prompt: str, summary: str, keep: set | None) -> dict:
    engine = state.get("engine") or "claude"
    started = time.monotonic()
    try:
        result, denied = _run_engine(engine, slug, state, prompt, answers_schema())
        _store_answers(slug, state, result, keep)
        state["answers"].update(status="ready", error="", message=result.get("message", ""), updated=_now())
        state.setdefault("turns", []).append({"at": _now(), "action": summary, "engine": engine,
                                              "seconds": round(time.monotonic() - started),
                                              "message": result.get("message", ""), "denied": denied})
        if not reviews(state):  # the owner checks these in the filled form before submitting
            _auto_approve(slug, state["answers"])
    except (TailorError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        reason = f"took longer than {TURN_TIMEOUT // 60} minutes" if isinstance(exc, subprocess.TimeoutExpired) \
            else f"the {engine} command isn't installed" if isinstance(exc, FileNotFoundError) else str(exc)
        state.setdefault("answers", {}).update(status="failed", error=reason)
    state.update(status="ready", error="")  # the resume itself is untouched either way
    state = _finish(slug, state)
    return _hand_to_fill(slug) or state


def _auto_approve(slug: str, block: dict) -> None:
    """A job the owner doesn't review ahead: drafts are approved as written and the cover letter is built.
    Questions only the owner can answer stay open; the fill lists them."""
    for item in (block.get("items") or {}).values():
        if item.get("status") == "draft" and item.get("value"):
            item.update(status="approved", auto=True)
    _build_letter(slug, block)
    block["reviewed"] = True


def _build_letter(slug: str, block: dict) -> None:
    letter = _letter_item(block)
    if letter and letter[1].get("status") == "approved" and letter[1].get("value") \
            and letter[1].get("built") != letter[1]["value"]:
        write_cover_letter(slug, letter[1]["value"])
        letter[1]["built"] = letter[1]["value"]


def _hand_to_fill(slug: str) -> dict | None:
    """A fill that stopped at questions nobody had drafted: once they're approved, carry on in the same tab."""
    state = load_state(slug) or {}
    block = state.get("answers") or {}
    ids = block.get("for_fill") or []
    if not ids or (state.get("apply") or {}).get("status") not in ("needs_you", "ready_to_submit"):
        return None
    questions = {q["id"]: q for q in block.get("questions") or []}
    items = block.get("items") or {}
    ready = [qid for qid in ids if qid in questions and items.get(qid, {}).get("status") == "approved"
             and items[qid].get("value")]
    if not ready:
        return None
    answered = {}
    for qid in ready:
        label = questions[qid].get("fill_label") or questions[qid]["label"]
        answered[label] = (f"upload the file {job_dir(slug) / LETTER_FILE}" if is_letter(questions[qid])
                           else items[qid]["value"])
    block["for_fill"] = [qid for qid in ids if qid not in ready]
    save_state(slug, state)
    try:
        return apply_continue(slug, answered, background=True)
    except TailorError:
        return None


def _fill_questions(block: dict, wanted: list[dict]) -> list[dict]:
    """Questions for what the fill found: the cover letter field, and written questions by their label on the form."""
    known = {q.get("fill_label") or q["label"] for q in block.get("questions") or []}
    taken = {q["id"] for q in block.get("questions") or []}
    has_letter = _letter_item(block) is not None or LETTER_ID in taken
    out = []
    for w in wanted:
        label = " ".join(str(w.get("label") or "").split())
        if not label or label in known:
            continue
        letter = bool(_LETTER_LABEL.search(label))
        if letter and has_letter:
            continue
        qid = LETTER_ID if letter else next(f"fill_{i}" for i in range(1, 500) if f"fill_{i}" not in taken)
        taken.add(qid)
        known.add(label)
        has_letter = has_letter or letter
        out.append({"id": qid, "label": "Cover letter" if letter else label, "fill_label": label,
                    "description": "Found on the application form while filling it.", "required": bool(w.get("required")),
                    "type": "file" if letter else "textarea", "options": [], "section": "application"})
    return out


def run_answers(slug: str) -> dict:
    """Read the job's application form and have its session draft the answers (a worker calls this)."""
    import app_questions
    state = load_state(slug) or {}
    if not state.get("result"):
        raise TailorError("Tailor this job first")
    begin(slug, "answers")
    state = load_state(slug) or state
    row = _job_row(slug)
    block = state.get("answers") or {}
    if block.get("from_fill") is not None:  # the fill found a cover letter field or questions nothing read ahead
        new = _fill_questions(block, block.pop("from_fill"))
        block.setdefault("items", {})
        if not new:
            block["status"] = "ready" if block.get("questions") else "none"
            state.update(answers=block, status="ready")
            return _finish(slug, state)
        block.update(questions=(block.get("questions") or []) + new, status="running", reviewed=False, updated=_now(),
                     for_fill=sorted(set(block.get("for_fill") or []) | {q["id"] for q in new}))
        state["answers"] = block
        (job_dir(slug) / "questions.json").write_text(json.dumps(block["questions"], indent=2), encoding="utf-8")
        save_state(slug, state)
        return run_turn(slug, answers_prompt(slug, row, only=[q["id"] for q in new]), "answers found by the fill", "",
                        set(block["items"]), "answers")
    form = app_questions.fetch(row.get("apply_url") or row.get("url") or "", row.get("job_id", ""), row.get("company", ""))
    state["answers"] = {"source": form["source"], "questions": form["questions"], "items": {}, "status": "running",
                        "error": form.get("error", ""), "reviewed": False, "updated": _now()}
    if not form["questions"]:
        state["answers"].update(status="none", reviewed=True)
        state["status"] = "ready"
        return _finish(slug, state)
    (job_dir(slug) / "questions.json").write_text(json.dumps(form["questions"], indent=2), encoding="utf-8")
    save_state(slug, state)
    return run_turn(slug, answers_prompt(slug, row), "answers", kind="answers")


def decide_answers(slug: str, approve=(), edit: dict | None = None, fill: dict | None = None, skip=(),
                   change: dict | None = None, reviewed: bool = False, background: bool = False) -> dict:
    """The owner's answer decisions. All instant except Change, which resumes the session."""
    edit, fill, change = dict(edit or {}), dict(fill or {}), {k: v for k, v in (change or {}).items() if str(v).strip()}
    state = load_state(slug) or {}
    block = state.get("answers") or {}
    items = block.get("items") or {}
    if block.get("status") != "ready":
        raise TailorError("There are no drafted answers for this job yet")
    if state.get("status") == "running":
        raise TailorError("Tailoring is already running for this job")
    unknown = sorted((set(approve) | set(edit) | set(fill) | set(skip) | set(change)) - set(items))
    if unknown:
        raise TailorError(f"No question with id {', '.join(unknown)}")
    questions = {q["id"]: q for q in block.get("questions") or []}
    for qid, value in {**edit, **fill}.items():
        q = questions.get(qid) or {}
        options = q.get("options") or (["Yes", "No"] if q.get("type") == "boolean" else [])
        if options and q.get("type") != "multiselect" and value not in options:
            raise TailorError(f"'{value}' isn't one of the options for: {q.get('label', qid)}")
        items[qid].update(value=str(value).strip(), status="approved", edited=True)
    for qid in approve:
        if items[qid]["status"] in ("draft", "approved") and items[qid].get("value"):
            items[qid]["status"] = "approved"
    for qid in skip:
        items[qid]["status"] = "skipped"
    company = _job_row(slug).get("company", "")
    _save_to_library([{"question": questions.get(qid, {}).get("label", ""), "answer": items[qid]["value"],
                       "company": company, "approved": _now()}
                      for qid in set(approve) | set(edit) if items[qid].get("general") and items[qid]["status"] == "approved"])
    if reviewed:
        block["reviewed"] = True
    _build_letter(slug, block)
    save_state(slug, state)  # instant decisions are kept even if the rewrite below fails
    if not change:  # a rewrite takes the job's lock, so a waiting fill carries on after it instead
        _hand_to_fill(slug)
        return load_state(slug) or state
    state = begin(slug, "answers")  # the lock, and the state as just saved
    state["answers"]["status"] = "running"
    save_state(slug, state)
    args = (slug, answers_prompt(slug, _job_row(slug), change), f"change answers {sorted(change)}", "",
            set(items) - set(change), "answers")
    if background:
        threading.Thread(target=run_turn, args=args, daemon=True).start()
        return load_state(slug) or state
    return run_turn(*args)


def enqueue_answers(slug: str, restart: bool = False) -> dict:
    """Queue answer drafting for a tailored job (a no-op if drafted or queued, unless restart)."""
    state = load_state(slug)
    if not state or not state.get("result"):
        raise TailorError("Tailor this job first")
    block = state.get("answers") or {}
    if block.get("status") in ("queued", "running") or (block.get("status") in ("ready", "none") and not restart):
        return state
    state["answers"] = {**block, "status": "queued", "error": ""}
    save_state(slug, state)
    _put((slug, "answers"))
    return load_state(slug) or state


def enqueue_from_fill(slug: str, wanted: list[dict]) -> dict:
    """The fill found a cover letter field or written questions: the job's session drafts them. Automatic jobs
    hand them straight back to the fill; jobs the owner reviews show them in Review first."""
    state = load_state(slug) or {}
    block = state.get("answers") or {}
    if block.get("status") in ("queued", "running"):  # picked up once the current turn ends
        block["from_fill"] = (block.get("from_fill") or []) + wanted
        state["answers"] = block
        save_state(slug, state)
        return state
    state["answers"] = {**block, "status": "queued", "error": "", "from_fill": wanted}
    save_state(slug, state)
    _put((slug, "answers"))
    return load_state(slug) or state


# ── Filling the application (step 13, the apply-form skill) ──────────

APPLY_MODEL, APPLY_EFFORT = "claude-sonnet-5-5", "high"  # the owner's choice
# Codex fills through the ChatGPT app's browser tool (cua_repl), a JavaScript console. The guard can't see inside
# it, so for Codex the site and upload limits are instructions only (the owner accepted this, 2026-09-29). An
# audit after every Codex turn flags web requests and other sites in what it ran.
CODEX_APPLY_MODEL, CODEX_APPLY_EFFORT = "gpt-5.6-sol", "high"  # the owner's choice
_AUDIT_CALLS = re.compile(r"\b(fetch|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts)\b|require\(\s*['\"](https?|net|child_process)['\"]")
APPLY_TIMEOUT = 1800
# Chrome tools the agent may use. Not: javascript_tool (arbitrary code in the page), browser_batch (would
# skip the per-call guard), gif/shortcut/network tools, closing tabs.
CHROME_TOOLS = ["tabs_context_mcp", "tabs_create_mcp", "navigate", "read_page", "find", "get_page_text",
                "form_input", "computer", "file_upload", "list_connected_browsers", "select_browser"]
APPLY_STATUSES = ["ready_to_submit", "needs_you", "blocked", "submitted", "failed"]
APPLY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", "tab_url", "filled", "unanswered", "message"],
    "properties": {
        "status": {"type": "string", "enum": APPLY_STATUSES},
        "tab_url": {"type": "string"},
        "filled": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "value", "source"],
            "properties": {"label": {"type": "string"}, "value": {"type": "string"},
                           "source": {"type": "string", "enum": ["answer", "profile", "resume", "owner"]}}}},
        "unanswered": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "required", "type", "options", "reason"],
            "properties": {"label": {"type": "string"}, "required": {"type": "boolean"}, "type": {"type": "string"},
                           "options": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}}},
        "message": {"type": "string"},
    },
}
# Sites shared by many companies: allow only the exact host, never the whole domain
_SHARED_HOSTS = ("myworkdayjobs.com", "myworkdaysite.com", "icims.com", "oraclecloud.com", "workable.com",
                 "bamboohr.com", "smartrecruiters.com", "lever.co", "ashbyhq.com", "greenhouse.io", "taleo.net",
                 "successfactors.com", "jobvite.com", "rippling.com", "paylocity.com", "ultipro.com", "adp.com")


def _shared(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in _SHARED_HOSTS)


def _embedded_ats_hosts(url: str) -> set[str]:
    """Application sites a company's career page embeds or links to, e.g. careers-garmin.icims.com behind
    careers.garmin.com. Only company-specific hosts on the shared sites count (not www.icims.com)."""
    from urllib.parse import urlparse
    try:
        import requests
        from boards import USER_AGENT
        page = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT}).text
    except Exception:
        return set()
    hosts = set()
    for link in re.findall(r"https?://[a-z0-9.-]+", page, flags=re.I):
        host = (urlparse(link).hostname or "").lower()
        if _shared(host) and not host.startswith("www.") and host not in _SHARED_HOSTS:
            hosts.add(host)
    return set(sorted(hosts)[:6])


def apply_scope(slug: str, row: dict) -> dict:
    """Where the agent's browser may go and what it may upload for this job."""
    from urllib.parse import urlparse
    hosts = set()
    for url in dict.fromkeys(u for u in (row.get("apply_url"), row.get("url")) if u):
        host = (urlparse(url or "").hostname or "").lower()
        if not host:
            continue
        if host in ("localhost", "127.0.0.1") or _shared(host):
            hosts.add(host)
        else:  # a company's own site: the whole domain (careers.example.com), plus the application site it embeds
            hosts.add(".".join(host.split(".")[-2:]))
            hosts |= _embedded_ats_hosts(url)
        if "gh_jid=" in (url or "") or "greenhouse" in str(row.get("apply_via", "")):
            hosts |= {"boards.greenhouse.io", "job-boards.greenhouse.io"}  # the embedded Greenhouse form
    uploads = [str(job_dir(slug) / "Manas_Dalvi_Resume.pdf")]
    if (job_dir(slug) / LETTER_FILE).exists():
        uploads.append(str(job_dir(slug) / LETTER_FILE))
    # The owner's choice (2026-09-30): the fill Chrome has no personal accounts, so any web page may be opened.
    # `hosts` stays as the job's own sites, for the prompt and for the audit's notes.
    return {"hosts": sorted(hosts), "any_site": True, "uploads": uploads}


def _apply_answers(state: dict) -> list[dict]:
    """The owner's approved answers for this form, for the agent to copy."""
    block = state.get("answers") or {}
    questions = {q["id"]: q for q in block.get("questions") or []}
    return [{"label": questions[qid]["label"], "value": it["value"], "type": questions[qid]["type"]}
            for qid, it in (block.get("items") or {}).items()
            if qid in questions and it.get("status") == "approved" and it.get("kind") in ("fact", "written", "you")
            and it.get("value") and not is_letter(questions[qid])]


def apply_hooks(slug: str) -> dict:
    guard = f"{sys.executable} {REPO_ROOT / 'scripts' / 'apply_guard.py'} {slug}"
    chrome = "mcp__claude-in-chrome__"
    return {"hooks": {
        "PreToolUse": [{"matcher": f"{chrome}(navigate|tabs_create_mcp|file_upload)",
                        "hooks": [{"type": "command", "command": f"{guard} pre"}]}],
        "PostToolUse": [{"matcher": f"{chrome}.*", "hooks": [{"type": "command", "command": f"{guard} post"}]}],
    }}


def claude_apply_args(slug: str, session_id: str, resume: bool) -> list[str]:
    return [
        CLAUDE, "--chrome",
        "--tools", "Read",
                "--allowedTools", "Read",
        "--permission-mode", "auto",
        "--disallowedTools", *[f"mcp__claude-in-chrome__{t}" for t in ("javascript_tool", "browser_batch", "gif_creator", "shortcuts_execute", "shortcuts_list", "upload_image", "read_network_requests", "read_console_messages", "resize_window", "switch_browser", "tabs_close_mcp")],
        "--settings", json.dumps(apply_hooks(slug)),  # the guard: allowed sites and uploads only
        "--permission-prompts", "none",
        "--model", APPLY_MODEL, "--effort", APPLY_EFFORT,
        "--output-format", "json", "--json-schema", json.dumps(APPLY_SCHEMA),
        *(["--resume", session_id] if resume else ["--session-id", session_id]),
    ]


def codex_apply_args(slug: str, session_id: str | None, schema: Path, out: Path) -> list[str]:
    common = ["-m", CODEX_APPLY_MODEL, "-c", f"model_reasoning_effort={CODEX_APPLY_EFFORT}", "-c", "notify=[]",
              "-c", 'sandbox_mode="read-only"', "--skip-git-repo-check", "--output-schema", str(schema), "-o", str(out),
              "--json"]
    if session_id:
        return [CODEX, "exec", "resume", session_id, *common]
    return [CODEX, "exec", "-s", "read-only", "-C", str(job_dir(slug)), *common]


def _codex_scope_note(slug: str) -> str:
    scope = json.loads((job_dir(slug) / "apply_scope.json").read_text(encoding="utf-8"))
    return (f"\nHard limits (nothing enforces them for you, so follow them exactly; everything you run is audited): "
            + (f"open whatever web pages this application needs (it starts on {', '.join(scope['hosts'])}); "
               if scope.get("any_site") else f"only open pages on {', '.join(scope['hosts'])}; ")
            + f"only upload {', '.join(scope['uploads'])}; never make web "
            "requests from the console yourself (no fetch, XMLHttpRequest, sendBeacon, WebSocket); use the browser only "
            "to fill this one form.")


def audit_codex_events(stdout: str, scope: dict) -> list[dict]:
    """What a Codex fill ran that breaks the limits: web requests from the console, other sites' addresses, or
    local files other than the job's uploads."""
    from urllib.parse import urlparse
    import apply_guard
    flagged = []
    for line in stdout.splitlines():
        try:
            item = (json.loads(line).get("item") or {})
        except (json.JSONDecodeError, AttributeError):
            continue
        if item.get("type") not in ("mcp_tool_call", "command_execution", "function_call"):
            continue
        code = json.dumps(item.get("arguments") or item.get("command") or item.get("input") or "")
        for m in _AUDIT_CALLS.finditer(code):
            flagged.append({"tool": "web request", "detail": code[max(0, m.start() - 80):m.end() + 80]})
        for url in re.findall(r"https?://[^\s\"'\\<>)]+", code):
            if not scope.get("any_site") and not apply_guard.host_allowed(url, scope["hosts"]):
                flagged.append({"tool": "other site", "detail": url[:200]})
        # With Chrome's "Allow access to file URLs" on, the browser can open local files: only the job's uploads may
        # appear in browser code. (Codex's own shell reading the skill or the profile isn't the browser.)
        if item.get("type") != "command_execution":
            for path in re.findall(r"(?:file://)?(/(?:Users|private|tmp|etc|var|Volumes)/[^\s\"'\\<>)]+)", code):
                if path not in scope["uploads"]:
                    flagged.append({"tool": "local file", "detail": path[:200]})
    unique = {(f["tool"], f["detail"]): f for f in flagged}
    return list(unique.values())[:20]


def apply_prompt(slug: str, row: dict, answered: dict | None = None, submit: bool = False,
                 earlier_tab: str = "", comment: str = "") -> str:
    out = job_dir(slug)
    skill = REPO_ROOT / ".claude/skills/apply-form/SKILL.md"
    if comment:
        ashby = "ashbyhq.com" in (row.get("apply_url") or row.get("url") or "")
        return (f"The owner checked the filled form and left this comment:\n\"\"\"\n{comment}\n\"\"\"\n"
                f"Follow \"The owner left a comment\" under \"Later turns\" in {skill}: make exactly the change it asks for "
                "in this tab, keep every other field as it is, re-check the form, and stop before Submit."
                + (" On this Ashby form, give each field you change the space-and-Backspace pass from "
                   "\"Fields that don't register\"." if ashby else ""))
    if submit:
        return (f"The owner asked you to submit this application now. Follow the \"Later turns\" section of {skill}: "
                "check every required field is filled and there are no errors, then click the final submit button once. "
                "If the form flags filled fields as empty, fix them as in \"Fields that don't register\" and submit "
                "once more.")
    if answered:
        return (f"The owner answered these fields. Fill exactly these values, re-check the form, and stop before Submit "
                f"(\"Later turns\" in {skill}; on an Ashby form, give each one the space-and-Backspace pass from "
                f"\"Fields that don't register\"):\n" + "\n".join(f"- {k}: {v}" for k, v in answered.items()))
    letter = out / LETTER_FILE
    ashby = "ashbyhq.com" in (row.get("apply_url") or row.get("url") or "")
    return (f"Fill the application for {row.get('title', '')} at {row.get('company', '')}.\n\n"
            f"Read {skill} first and follow it.\n"
            + ("This is an Ashby form: after filling, give every text field the space-and-Backspace pass from "
               "\"Fields that don't register\", or Ashby treats them as empty.\n" if ashby else "")
            + f"Application URL: {row.get('apply_url') or row.get('url')}\n"
            f"Approved answers: {out / 'apply_answers.json'}\n"
            f"Profile facts: the application: section of {PROFILE_FILE}\n"
            f"Education and work history: {REPO_ROOT / 'cv.md'}\n"
            f"How did you hear about us, for this job: {how_heard(row.get('found_via'))}\n"
            f"Resume to upload: {out / 'Manas_Dalvi_Resume.pdf'}\n"
            + (f"Cover letter to upload: {letter}\n" if letter.exists() else
               "Cover letter: none yet. If the form has a cover letter field (required or optional), leave it and list "
               "it in unanswered with a label starting \"Cover letter\"; one gets written for the owner to approve.\n")
            + (f"An earlier fill of this job left a tab at {earlier_tab}. If that tab, or any tab on this application's "
               "site that is past sign-in, is still open, continue in it instead of starting over: starting over can "
               "send another sign-in email.\n" if earlier_tab else "")
            + "Stop before Submit.")


def _write_application_md(slug: str, row: dict, block: dict) -> None:
    status = {"ready_to_submit": "Filled; waiting for you to submit", "needs_you": "Waiting for your answers",
              "blocked": "Blocked", "submitted": "Submitted", "failed": "Failed"}.get(block.get("status"), block.get("status"))
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
    lines = [f"# Application: {row.get('title', '')} at {row.get('company', '')}", "",
             f"- **Status:** {status}", f"- **Form:** {block.get('tab_url') or row.get('apply_url') or row.get('url')}",
             f"- **Last run:** {block.get('updated', '')} ("
             + (f"{CODEX_APPLY_MODEL}, Codex browser; limits not enforced, audited" if block.get("engine") == "codex"
                else f"{APPLY_MODEL}, Claude in Chrome")
             + ")", "",
             block.get("message", ""), "", "## Filled", "", "| Field | Value | From |", "|---|---|---|"]
    lines += [f"| {cell(f['label'])} | {cell(f['value'])} | {f['source']} |" for f in block.get("filled") or []]
    flagged = [d for t in block.get("turns") or [] if t.get("engine") == "codex" for d in t.get("denied") or []]
    if flagged:
        lines += ["", "## Flagged by the audit (Codex ran these)", ""]
        lines += [f"- {f['tool']}: `{cell(f['detail'])}`" for f in flagged]
    if block.get("unanswered"):
        lines += ["", "## Still needs you", ""]
        lines += [f"- {u['label']}{' (required)' if u['required'] else ''}: {u['reason']}" for u in block["unanswered"]]
    (job_dir(slug) / "application.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_apply_codex(slug: str, block: dict, prompt: str) -> tuple[dict, list]:
    with tempfile.TemporaryDirectory(prefix="loom-apply-") as tmp:
        schema, out = Path(tmp) / "schema.json", Path(tmp) / "answer.json"
        schema.write_text(json.dumps(APPLY_SCHEMA), encoding="utf-8")
        resume = block.get("session_id") if block.get("turns") else None
        proc = subprocess.run([*codex_apply_args(slug, resume, schema, out), prompt + _codex_scope_note(slug)],
                              capture_output=True, text=True, cwd=job_dir(slug), timeout=APPLY_TIMEOUT,
                              stdin=subprocess.DEVNULL)
        errors = []
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and event.get("thread_id"):
                block["session_id"] = event["thread_id"]
            if event.get("type") in ("error", "turn.failed"):
                errors.append(str(event.get("message") or (event.get("error") or {}).get("message") or event)[:300])
        flagged = audit_codex_events(proc.stdout, json.loads((job_dir(slug) / "apply_scope.json").read_text(encoding="utf-8")))
        if proc.returncode != 0 or not out.exists():
            detail = errors[-1] if errors else ((proc.stderr or proc.stdout).strip().splitlines() or ["no output"])[-1]
            block["flagged"] = flagged
            raise TailorError(f"codex failed: {detail}"[:400])
        try:
            return json.loads(out.read_text(encoding="utf-8")), flagged
        except json.JSONDecodeError:
            raise TailorError("Codex returned something that isn't JSON")


def _run_apply_claude(slug: str, block: dict, prompt: str) -> tuple[dict, list]:
    resume = bool(block.get("turns"))
    block.setdefault("session_id", str(uuid.uuid4()))
    proc = subprocess.run([*claude_apply_args(slug, block["session_id"], resume), "-p", prompt],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=APPLY_TIMEOUT,
                          stdin=subprocess.DEVNULL, env=_claude_env())
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise TailorError((proc.stderr or proc.stdout or "claude printed nothing").strip()[-400:])
    result = envelope.get("structured_output") or {}
    if envelope.get("is_error") and not result:
        raise TailorError(str(envelope.get("result") or envelope.get("terminal_reason") or "claude failed")[:400])
    denied = [_denial(d) for d in envelope.get("permission_denials") or []]
    # Claude in Chrome's own per-site permission: the owner allows the site in the extension's settings
    allowed_chrome = {f"mcp__claude-in-chrome__{t}" for t in CHROME_TOOLS}
    if any(d["tool"] in allowed_chrome for d in denied) and not result.get("filled"):  # not our own bans
        from urllib.parse import urlparse
        host = urlparse(_job_row(slug).get("apply_url") or _job_row(slug).get("url") or "").hostname or "this site"
        result = {**result, "status": "blocked", "filled": [],
                  "message": f"Claude in Chrome isn't allowed on {host} yet. Allow it in the Claude in Chrome extension's "
                             "site settings, then press Fill again."}
    if not result:  # the guard stops the session without a final answer when the tab leaves the site
        raise TailorError(str(envelope.get("result") or "The session stopped before reporting")[:400])
    return result, denied


def _keep_owner_values(state: dict, filled: list[dict]) -> None:
    """What the owner gave in a later turn replaces the saved answer to that question, so Fill again keeps it."""
    answers = state.get("answers") or {}
    norm = lambda label: " ".join(str(label or "").split()).lower()
    by_label = {norm(q.get("fill_label") or q["label"]): q for q in answers.get("questions") or []}
    for f in filled:
        q = by_label.get(norm(f.get("label")))
        item = (answers.get("items") or {}).get(q["id"]) if q else None
        if (f.get("source") == "owner" and f.get("value") and item is not None
                and item.get("kind") in ("fact", "written", "you") and not is_letter(q)):
            item.update(value=f["value"], status="approved")


def _run_apply_turn(slug: str, prompt: str, summary: str, comment: str = "") -> dict:
    """One turn of the job's apply session. begin(slug, "apply") must have been called."""
    state = load_state(slug) or {}
    block = state.setdefault("apply", {})
    engine = block.get("engine") or "claude"
    started = time.monotonic()
    row = _job_row(slug)
    try:
        result, denied = (_run_apply_codex if engine == "codex" else _run_apply_claude)(slug, block, prompt)
        block.update(status=result["status"], tab_url=result.get("tab_url", ""), filled=result.get("filled", []),
                     unanswered=result.get("unanswered", []), message=result.get("message", ""), error="")
        block.setdefault("turns", []).append({"at": _now(), "action": summary, "engine": engine,
                                              "seconds": round(time.monotonic() - started), "denied": denied,
                                              **({"comment": comment} if comment else {})})
        if summary in ("comment", "fill answers"):
            _keep_owner_values(state, block["filled"])
        if result["status"] == "submitted":
            block["submitted_by"] = "agent"
            try:
                from add_job import Store
                Store(REPO_ROOT).set_status(slug, "Applied")
            except (KeyError, OSError) as exc:  # the form is submitted either way; say what didn't save
                block["error"] = f"Submitted, but the job couldn't be marked Applied ({exc}). Set it by hand."
    except (TailorError, subprocess.TimeoutExpired, FileNotFoundError, KeyError) as exc:
        reason = f"took longer than {APPLY_TIMEOUT // 60} minutes" if isinstance(exc, subprocess.TimeoutExpired) \
            else f"the {engine} command isn't installed" if isinstance(exc, FileNotFoundError) else str(exc)
        if engine == "claude" and USAGE_LIMIT.search(reason):
            reason = f"Claude's usage has run out ({reason}). Try again after it resets, or fill with Codex."
        block.update(status="failed", error=reason)
        if block.get("flagged"):
            block.setdefault("turns", []).append({"at": _now(), "action": summary, "engine": engine,
                                                  "seconds": round(time.monotonic() - started),
                                                  "denied": block.pop("flagged")})
    block["updated"] = _now()
    wanted = []
    if block.get("status") in ("needs_you", "ready_to_submit"):
        answers = state.get("answers") or {}
        drafted = {q.get("fill_label") or q["label"] for q in answers.get("questions") or []}
        for u in block.get("unanswered") or []:
            label = " ".join(str(u.get("label") or "").split())
            letter = bool(_LETTER_LABEL.search(label))
            if label in drafted or (letter and (job_dir(slug) / LETTER_FILE).exists()):
                continue
            if letter or u.get("type") == "textarea":
                wanted.append(u)
                u["reason"] = ("Being written for you; " + ("approve it in Review and it's" if reviews(state)
                                                            else "it's") + " filled in automatically.")
    _write_application_md(slug, row, block)
    state.update(status="ready", error="")  # the resume is untouched
    state = _finish(slug, state)
    if wanted:
        state = enqueue_from_fill(slug, wanted)
    # Tell the owner, unless the only open fields are being written and filled for them right now
    owner_fields = [u for u in block.get("unanswered") or [] if u not in wanted]
    if not (block.get("status") == "needs_you" and wanted and not owner_fields):
        try:
            import notify
            notify.fill_notice(slug, row, block, owner_fields)
        except Exception:  # noqa: BLE001 - a notification never breaks a fill
            pass
    return state


def run_apply(slug: str) -> dict:
    """Fill the job's application in Chrome (the apply worker calls this)."""
    state = load_state(slug) or {}
    if not state.get("result"):
        raise TailorError("Tailor this job first")
    begin(slug, "apply")
    state = load_state(slug) or state
    row = _job_row(slug)
    out = job_dir(slug)
    (out / "apply_scope.json").write_text(json.dumps(apply_scope(slug, row), indent=2), encoding="utf-8")
    (out / "apply_answers.json").write_text(json.dumps(_apply_answers(state), indent=2), encoding="utf-8")
    engine = (state.get("apply") or {}).get("engine") or get_settings()["fill_engine"]
    earlier_tab = (state.get("apply") or {}).get("tab_url") or ""
    state["apply"] = {"status": "running", "engine": engine, "session_id": str(uuid.uuid4()) if engine == "claude" else None,
                      "turns": [], "started": _now()}
    save_state(slug, state)
    return _run_apply_turn(slug, apply_prompt(slug, row, earlier_tab=earlier_tab), "fill")


def _apply_followup(slug: str, prompt: str, summary: str, background: bool, comment: str = "") -> dict:
    state = load_state(slug) or {}
    if not (state.get("apply") or {}).get("turns"):
        raise TailorError("Fill the application first")
    state = begin(slug, "apply")
    state["apply"]["status"] = "running"
    save_state(slug, state)
    (job_dir(slug) / "apply_scope.json").write_text(json.dumps(apply_scope(slug, _job_row(slug)), indent=2),
                                                    encoding="utf-8")
    if background:
        threading.Thread(target=_run_apply_turn, args=(slug, prompt, summary, comment), daemon=True).start()
        return load_state(slug) or state
    return _run_apply_turn(slug, prompt, summary, comment)


SIGNED_IN_PROMPT = ("The owner says they have signed in to this application site in Chrome. A sign-in applies to "
                    "every tab, including yours. In your tab, open the application again (reload it, or the job's "
                    "application link on the same site); don't enter an email or start a new sign-in. If you're past "
                    "sign-in, fill the form as {skill} says and stop before Submit. If it still asks you to sign in, "
                    "stop with blocked and say exactly what the page shows.")


def apply_continue(slug: str, answered: dict, background: bool = False, signed_in: bool = False) -> dict:
    """The owner answered fields the agent couldn't, or signed in where it stopped: carry on (same session, same tab)."""
    if signed_in:
        prompt = SIGNED_IN_PROMPT.format(skill=REPO_ROOT / ".claude/skills/apply-form/SKILL.md")
        return _apply_followup(slug, prompt, "continue after sign-in", background)
    answered = {str(k).strip(): str(v).strip() for k, v in answered.items() if str(v).strip()}
    if not answered:
        raise TailorError("Nothing to fill")
    return _apply_followup(slug, apply_prompt(slug, _job_row(slug), answered=answered), "fill answers", background)


def apply_comment(slug: str, comment: str, background: bool = False) -> dict:
    """The owner checked the filled form and wants something changed: the same session changes it, in the same tab."""
    comment = str(comment or "").strip()
    if not comment:
        raise TailorError("Write what to change")
    if len(comment) > 4000:
        raise TailorError("Keep the comment under 4,000 characters")
    status = ((load_state(slug) or {}).get("apply") or {}).get("status")
    if status in ("queued", "running"):
        raise TailorError("The form is still being filled. Comment when it's done.")
    if status == "submitted":
        raise TailorError("This application is already submitted")
    return _apply_followup(slug, apply_prompt(slug, _job_row(slug), comment=comment), "comment", background, comment)


def apply_submit(slug: str, background: bool = False) -> dict:
    """The owner pressed Submit for me (after confirming): the agent clicks the final submit button."""
    state = load_state(slug) or {}
    if (state.get("apply") or {}).get("status") != "ready_to_submit":
        raise TailorError("The form isn't filled and ready yet")
    return _apply_followup(slug, apply_prompt(slug, _job_row(slug), submit=True), "submit", background)


def mark_submitted(slug: str) -> dict:
    """The owner submitted the form themselves: mark the job Applied and record it (no model run)."""
    from add_job import Store
    Store(REPO_ROOT).set_status(slug, "Applied")  # KeyError when the job isn't in the sheet
    state = load_state(slug) or {}
    block = state.get("apply")
    # A turn that's running saves its own copy of the state when it ends, so leave the record to it
    if block and state.get("status") != "running" and block.get("status") not in ("queued", "running"):
        block.update(status="submitted", submitted_by="owner", error="", unanswered=[], updated=_now(),
                     message="You submitted it yourself. The job is marked Applied.")
        block.setdefault("turns", []).append({"at": _now(), "action": "submitted by the owner", "engine": "dashboard",
                                              "seconds": 0, "denied": []})
        _write_application_md(slug, _job_row(slug), block)
        save_state(slug, state)
    return load_state(slug) or state


def enqueue_apply(slug: str, engine: str | None = None) -> dict:
    state = load_state(slug)
    if not state or not state.get("result"):
        raise TailorError("Tailor this job first")
    if not (job_dir(slug) / "Manas_Dalvi_Resume.pdf").exists():
        raise TailorError("This job has no resume PDF yet")
    block = state.get("apply") or {}
    if block.get("status") in ("queued", "running"):
        return state
    if engine and engine not in ENGINES:
        raise TailorError(f"engine must be one of {', '.join(ENGINES)}")
    state["apply"] = {**block, "status": "queued", "error": "", "turns": [], "engine": engine or get_settings()["fill_engine"]}
    save_state(slug, state)
    _apply_put(slug)
    return load_state(slug) or state


# Queued fills: as many at once as the fill_parallel setting allows (each in its own Chrome tab).
# Follow-ups the owner starts (answers, sign-in, submit) run right away and don't take a slot.
_apply_queue: "queue.Queue[str]" = queue.Queue()
_fill_slots = threading.Condition()
_fill_busy = 0


def _take_fill_slot() -> None:
    global _fill_busy
    with _fill_slots:
        while _fill_busy >= get_settings()["fill_parallel"]:
            _fill_slots.wait(timeout=5)  # also picks up a changed setting
        _fill_busy += 1


def _free_fill_slot() -> None:
    global _fill_busy
    with _fill_slots:
        _fill_busy -= 1
        _fill_slots.notify_all()


def _apply_put(slug: str) -> None:
    _apply_queue.put(slug)


def _apply_worker() -> None:
    while True:
        slug = _apply_queue.get()
        try:
            state = load_state(slug) or {}
            if (state.get("apply") or {}).get("status") == "queued":
                if state.get("status") == "running":  # a tailoring turn on this job: come back to it
                    time.sleep(3)
                    _apply_put(slug)
                else:
                    _take_fill_slot()
                    try:
                        run_apply(slug)
                    finally:
                        _free_fill_slot()
        except Exception as exc:
            try:
                state = load_state(slug) or {"slug": slug}
                state.setdefault("apply", {}).update(status="failed", error=f"Couldn't start: {exc}")
                if state.get("status") == "running":
                    state["status"] = "ready"
                save_state(slug, state)
                _lock_path(slug).unlink(missing_ok=True)
            except Exception:
                pass
        finally:
            _apply_queue.task_done()


# ── Background queue ─────────────────────────────────────────────────

_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()  # (slug, "tailor" | "answers")
_queued: set[tuple[str, str]] = set()
_queue_lock = threading.Lock()
_started = False
_slots = threading.Condition()  # how many workers may run at once: the `parallel` setting
_busy = 0


def _take_slot() -> None:
    global _busy
    with _slots:
        while _busy >= get_settings()["parallel"]:
            _slots.wait(timeout=5)  # also picks up a changed setting
        _busy += 1


def _free_slot() -> None:
    global _busy
    with _slots:
        _busy -= 1
        _slots.notify_all()


def _wake() -> None:
    """Hand every job marked queued (e.g. before a restart) to the workers."""
    if not _started:
        return
    for path in OUTPUT_DIR.glob("*/tailor.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if state.get("status") == "queued":
            _put((path.parent.name, "tailor"))
        if (state.get("answers") or {}).get("status") == "queued":
            _put((path.parent.name, "answers"))
        if (state.get("apply") or {}).get("status") == "queued":
            _apply_put(path.parent.name)


def _put(item) -> None:
    item = (item, "tailor") if isinstance(item, str) else tuple(item)
    with _queue_lock:
        if item not in _queued:
            _queued.add(item)
            _queue.put(item)


def _worker() -> None:
    while True:
        slug, kind = _queue.get()
        with _queue_lock:
            _queued.discard((slug, kind))
        _take_slot()
        try:
            state = load_state(slug) or {}
            if kind == "tailor" and state.get("status") == "queued":
                begin(slug, "start", state.get("engine"))
                review = state.get("review")
                run_turn(slug, first_prompt(slug), "tailor")
                if review is not None:  # begin() starts the state over; the owner's choice carries across
                    set_review(slug, review)
                auto_review(slug)
            elif kind == "answers" and (state.get("answers") or {}).get("status") == "queued":
                if state.get("status") == "running":  # a resume decision is still running: come back to it
                    time.sleep(3)
                    _put((slug, kind))
                else:
                    run_answers(slug)
        except Exception as exc:  # keep the worker alive whatever one job does
            try:
                state = load_state(slug) or {"slug": slug}
                if kind == "tailor" and state.get("status") in ("queued", "running"):
                    state.update(status="failed", error=f"Couldn't start: {exc}")
                elif kind == "answers":
                    state.setdefault("answers", {}).update(status="failed", error=f"Couldn't draft answers: {exc}")
                    if state.get("status") == "running":
                        state["status"] = "ready"
                save_state(slug, state)
                _lock_path(slug).unlink(missing_ok=True)
            except Exception:
                pass
        finally:
            _free_slot()
            _queue.task_done()


def start_workers(n: int = MAX_PARALLEL) -> None:
    """Start the background tailoring workers (the dashboard calls this once)."""
    global _started
    if _started:
        return
    _started = True
    for _ in range(n):
        threading.Thread(target=_worker, daemon=True).start()
    for _ in range(MAX_FILL_PARALLEL):
        threading.Thread(target=_apply_worker, daemon=True).start()
    _wake()


def enqueue(slug: str, restart: bool = False, engine: str | None = None, review: bool | None = None) -> dict:
    """Queue a job for tailoring. A job that's queued, running or (unless restart) already tailored is left as is.
    review: the owner looks at this job's resume and answers in Review; otherwise it's automatic."""
    state = load_state(slug)
    if state and (state.get("status") in ("queued", "running") or (state.get("result") and not restart)):
        if review is not None and state.get("review") != review:
            state["review"] = review
            save_state(slug, state)
        return state
    state = {**(state or {}), "slug": slug, "status": "queued", "queued_at": _now(), "error": "",
             "engine": engine or get_settings()["engine"]}
    if review is not None:
        state["review"] = review
    save_state(slug, state)
    _put(slug)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Tailor a saved job's resume (pick-resume-auto).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("slug")
    s.add_argument("--engine", choices=ENGINES)
    sub.add_parser("show").add_argument("slug")
    sub.add_parser("answers").add_argument("slug")
    d = sub.add_parser("decide")
    d.add_argument("slug")
    d.add_argument("--approve", type=int, nargs="*", default=[])
    d.add_argument("--reject", type=int, nargs="*", default=[])
    d.add_argument("--change", nargs=2, action="append", metavar=("ID", "FEEDBACK"), default=[])
    d.add_argument("--as-is", action="store_true")
    d.add_argument("--comment", default="", help="a comment on the resume for the job's session")
    args = parser.parse_args()
    try:
        if args.cmd == "start":
            begin(args.slug, "start", args.engine)
            state = run_turn(args.slug, first_prompt(args.slug), "tailor")
        elif args.cmd == "answers":
            state = run_answers(args.slug)
        elif args.cmd == "decide":
            state = decide(args.slug, args.approve, args.reject, {int(i): f for i, f in args.change}, args.as_is,
                           comment=args.comment)
        else:
            state = load_state(args.slug) or {}
    except TailorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(state, indent=2))
    return 0 if state.get("status") != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
