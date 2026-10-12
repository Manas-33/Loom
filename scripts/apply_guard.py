#!/usr/bin/env python3
"""
Hook for the apply agent's browser session (Claude in Chrome). Claude Code runs
it before and after every browser tool call and passes the call as JSON on stdin.

  apply_guard.py <slug> pre    # before a call: exit 2 blocks it
  apply_guard.py <slug> post   # after a call: {"continue": false} stops the session

The limits come from output/<slug>/apply_scope.json, written by scripts/tailor.py:
  {"hosts": ["job-boards.greenhouse.io", ...], "any_site": true, "uploads": ["/…/output/<slug>/Manas_Dalvi_Resume.pdf"]}

  - file_upload may only upload those files
  - navigate / tabs_create may only open web pages (http/https). With "any_site"
    (the owner's choice, 2026-09-30: this Chrome has no personal accounts) that's
    all; without it, only pages on those hosts (or their subdomains), and if the
    working tab ends up anywhere else the session is stopped at once

A page can say anything; these checks don't depend on the model obeying it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
_URL = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)


def load_scope(slug: str) -> dict:
    try:
        return json.loads((OUTPUT_DIR / slug / "apply_scope.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"hosts": [], "uploads": []}


def host_allowed(url: str, hosts: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and any(host == h or host.endswith("." + h) for h in hosts)


def working_tab_url(text: str) -> str | None:
    """The URL of the tab a Chrome tool just acted on, from its "Tab Context" footer."""
    tab = re.search(r"Executed on tabId:\s*(\S+)", text)
    if tab:
        line = re.search(rf"tabId {re.escape(tab.group(1))}\b[^\n]*", text)
        if line:
            urls = _URL.findall(line.group(0))
            if urls:
                return urls[-1]
    return None


def check_pre(call: dict, scope: dict) -> str | None:
    """A reason to block the call, or None to let it run."""
    name = call.get("tool_name", "")
    args = call.get("tool_input") or {}
    if name.endswith("__navigate"):
        url = str(args.get("url") or "")
        if url in ("back", "forward"):
            return None
        if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) and not url.lower().startswith(("http://", "https://")):
            return f"Blocked: {url.split(':')[0]}: pages can't be opened. Only web pages."
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if not scope.get("any_site") and not host_allowed(url, scope["hosts"]):
            return f"Blocked: {url} isn't this job's application site. Stay on the application form."
    if name.endswith("__file_upload"):
        paths = args.get("paths") or ([args["path"]] if args.get("path") else [])
        allowed = {str(Path(p).resolve()) for p in scope["uploads"]}
        bad = [p for p in paths if str(Path(p).resolve()) not in allowed]
        if bad or not paths:
            return f"Blocked: only the tailored resume may be uploaded ({', '.join(scope['uploads'])})."
    return None


def check_post(call: dict, scope: dict) -> str | None:
    """A reason to stop the whole session, or None."""
    response = call.get("tool_response")
    text = response if isinstance(response, str) else json.dumps(response)
    url = working_tab_url(text)
    if url and not scope.get("any_site") and not host_allowed(url, scope["hosts"]):
        return f"The browser left the application site ({urlparse(url).hostname}); stopped for safety."
    return None


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[2] not in ("pre", "post"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 1
    try:
        call = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        call = {}
    scope = load_scope(sys.argv[1])
    if sys.argv[2] == "pre":
        reason = check_pre(call, scope)
        if reason:
            print(reason, file=sys.stderr)
            return 2  # blocks the tool call; the reason goes back to the model
        return 0
    reason = check_post(call, scope)
    if reason:
        print(json.dumps({"continue": False, "stopReason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
