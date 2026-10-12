#!/usr/bin/env python3
"""
Notifications when a filled application needs the owner: ready to submit, the
form needs answers, the fill stopped or failed.

Two channels, each can be switched off in data/notify.json (or Settings):
  - phone: ntfy (https://ntfy.sh). The owner's ntfy app subscribes to a private,
    random topic made on first use. Messages carry the company, the role and a
    link to the job in the dashboard, nothing else. Anyone who knows the topic
    can read it, so it's never printed in logs or committed (data/ is gitignored).
  - mac: a macOS notification banner (osascript).

The link opens the job on the phone through Tailscale when phone access is on
(data/phone.json), otherwise on this Mac.

send() never raises: a notification problem must not break a fill.

Usage (from repo root):
  python scripts/notify.py setup     # make the topic (once) and say how to subscribe
  python scripts/notify.py test      # send a test notification
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_ROOT / "data" / "notify.json"
PHONE_FILE = REPO_ROOT / "data" / "phone.json"
LOCAL_DASHBOARD = "http://127.0.0.1:8000"
DEFAULTS = {"phone": True, "mac": True, "ntfy_server": "https://ntfy.sh", "ntfy_topic": ""}


def config(create: bool = True) -> dict:
    """The saved settings; the first call makes the private ntfy topic."""
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    cfg = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    if create and not cfg["ntfy_topic"]:
        cfg["ntfy_topic"] = "loom-" + secrets.token_hex(12)  # 96 random bits: unguessable
        save(cfg)
    return cfg


def save(cfg: dict) -> dict:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({k: cfg[k] for k in DEFAULTS}, indent=2), encoding="utf-8")
    return cfg


def update(changes: dict) -> dict:
    cfg = config()
    for key in ("phone", "mac"):
        if key in changes:
            cfg[key] = bool(changes[key])
    return save(cfg)


def job_link(slug: str) -> str:
    """The job's page: through Tailscale when phone access is on, else this Mac."""
    try:
        base = json.loads(PHONE_FILE.read_text(encoding="utf-8")).get("url") or LOCAL_DASHBOARD
    except (OSError, ValueError):
        base = LOCAL_DASHBOARD
    return f"{base.rstrip('/')}/#job/{quote(slug)}"


def _mac(title: str, message: str) -> None:
    script = f"display notification {json.dumps(message)} with title {json.dumps('Loom')} subtitle {json.dumps(title)}"
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)


def _phone(cfg: dict, title: str, message: str, link: str, priority: int, tags: list[str]) -> None:
    import requests
    payload = {"topic": cfg["ntfy_topic"], "title": title, "message": message, "priority": priority, "tags": tags}
    if link:
        payload["click"] = link
        payload["actions"] = [{"action": "view", "label": "Open job", "url": link}]
    requests.post(cfg["ntfy_server"], json=payload, timeout=10).raise_for_status()


def send(title: str, message: str, link: str = "", priority: int = 3, tags: list[str] | None = None) -> list[str]:
    """Send on every channel that's on. Returns what failed (empty when all went out)."""
    errors = []
    try:
        cfg = config()
    except OSError as exc:
        return [f"config: {exc}"]
    if cfg["mac"]:
        try:
            _mac(title, message)
        except Exception as exc:  # noqa: BLE001 - never break the caller
            errors.append(f"mac: {exc}")
    if cfg["phone"] and cfg["ntfy_topic"]:
        try:
            _phone(cfg, title, message, link, priority, tags or [])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"phone: {exc}")
    return errors


# What each fill result tells the owner: (title, priority, ntfy tag)
FILL_NOTICES = {
    "ready_to_submit": ("Ready to submit", 3, "white_check_mark"),
    "needs_you": ("The form needs you", 3, "pencil2"),
    "blocked": ("Fill stopped: needs you in Chrome", 3, "warning"),
    "failed": ("Couldn't fill the form", 3, "x"),
    "submitted": ("Submitted", 2, "tada"),
}


def fill_notice(slug: str, row: dict, block: dict, owner_fields: list[dict]) -> list[str]:
    """Tell the owner how a fill turn ended. owner_fields: what only the owner can answer."""
    status = block.get("status")
    if status not in FILL_NOTICES:
        return []
    title, priority, tag = FILL_NOTICES[status]
    job = f"{row.get('company') or 'A job'} · {row.get('title') or ''}".strip(" ·")
    if status == "ready_to_submit":
        detail = "Filled and waiting in Chrome. Check it and submit."
    elif status == "needs_you":
        labels = [str(u.get("label") or "").strip() for u in owner_fields][:3]
        more = len(owner_fields) - len(labels)
        detail = (f"{len(owner_fields)} field{'s' if len(owner_fields) != 1 else ''} to answer: " + "; ".join(labels)
                  + (f" and {more} more" if more > 0 else ""))
    elif status == "failed":
        detail = str(block.get("error") or "The fill didn't finish.")[:180]
    else:
        detail = str(block.get("message") or "")[:180]
    return send(title, f"{job}\n{detail}".strip(), job_link(slug), priority, [tag])


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        cfg = config()
        print("Phone: install the ntfy app (App Store / Play Store), tap +, and subscribe to this topic on ntfy.sh:")
        print(f"  {cfg['ntfy_topic']}")
        print("Keep it private: anyone with the topic name can read these notifications.")
        return 0
    if cmd == "test":
        errors = send("Test", "Notifications from Loom are working.", job_link(""), 3, ["bell"])
        print("sent" if not errors else "problems: " + "; ".join(errors))
        return 0 if not errors else 1
    print(__doc__.strip().split("\n\n")[-1])
    return 2


if __name__ == "__main__":
    sys.exit(main())
