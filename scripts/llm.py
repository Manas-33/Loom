"""
Run a model with no tools and get JSON back that matches a schema.

  run_codex()   `codex exec` in a read-only sandbox (uses Codex credits)
  run_claude()  `claude -p` with every tool disabled (uses the Max plan)

Both run in an empty temp folder, so the model can't see or change the repo.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


class ModelError(RuntimeError):
    pass


def run_codex(prompt: str, schema: dict, model: str, effort: str = "low", timeout: int = 300,
              usage: dict | None = None, limits: dict | None = None) -> Any:
    """Pass a dict as `usage` to get the run's token counts back in it.

    Pass a dict as `limits` to also get your plan-limit meter after the run
    ({"five_hour_used": 24.0, "weekly_used": 4.0, ...}). That needs a normal
    (non-ephemeral) run, which leaves one entry in your Codex session history.
    """
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="loom-codex-") as tmp:
        workdir = Path(tmp)
        schema_path, out_path = workdir / "schema.json", workdir / "answer.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        cmd = [
            "codex", "exec", "-",
            "-m", model,
            "-c", f"model_reasoning_effort={effort}",
            "-c", "notify=[]",  # don't fire the desktop app's turn-ended hook for background runs
            "-s", "read-only",
            "--skip-git-repo-check",
            *([] if limits is not None else ["--ephemeral"]),
            "--output-schema", str(schema_path),
            "-o", str(out_path),
            "--json",  # event stream on stdout; its last event carries token usage
        ]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=workdir, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ModelError(f"codex took longer than {timeout}s")
        except FileNotFoundError:
            raise ModelError("the `codex` command isn't installed or isn't on PATH")
        if proc.returncode != 0 or not out_path.exists():
            detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            raise ModelError(f"codex failed: {detail[0][:300]}")
        if usage is not None:
            for line in proc.stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "turn.completed":
                    for key, value in (event.get("usage") or {}).items():
                        usage[key] = usage.get(key, 0) + int(value or 0)
        if limits is not None:
            limits.update(codex_limits(since=started))
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise ModelError("codex returned something that isn't JSON")


def codex_limits(since: float = 0) -> dict:
    """Plan-limit meter from the newest Codex session log written after `since`."""
    sessions = Path.home() / ".codex" / "sessions"
    logs = [p for p in sessions.rglob("*.jsonl") if p.stat().st_mtime >= since] if sessions.exists() else []
    for log in sorted(logs, key=lambda p: p.stat().st_mtime, reverse=True):
        found = None
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "used_percent" not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload", event)
            found = payload.get("rate_limits") or (payload.get("info") or {}).get("rate_limits") or found
        if found:
            primary, secondary = found.get("primary") or {}, found.get("secondary") or {}
            return {
                "five_hour_used": primary.get("used_percent"),
                "five_hour_resets_at": primary.get("resets_at"),
                "weekly_used": secondary.get("used_percent"),
                "weekly_resets_at": secondary.get("resets_at"),
            }
    return {}


def run_claude(prompt: str, schema: dict, model: str, timeout: int = 300) -> Any:
    cmd = [
        "claude", "-p", "Follow the instructions in the input and answer in the required JSON format.",
        "--tools", "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--model", model,
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
    ]
    with tempfile.TemporaryDirectory(prefix="loom-claude-") as tmp:
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=tmp, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ModelError(f"claude took longer than {timeout}s")
        except FileNotFoundError:
            raise ModelError("the `claude` command isn't installed or isn't on PATH")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ModelError(f"claude failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    if envelope.get("is_error"):
        raise ModelError(f"claude failed: {str(envelope.get('result'))[:300]}")
    answer = envelope.get("structured_output")
    if answer is None:
        text = re.sub(r"^```(?:json)?|```$", "", str(envelope.get("result", "")).strip()).strip()
        try:
            answer = json.loads(text)
        except json.JSONDecodeError:
            raise ModelError("claude returned something that isn't JSON")
    return answer
