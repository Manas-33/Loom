#!/usr/bin/env python3
"""
Phone access: reach the dashboard from your phone over Tailscale.

The dashboard stays bound to 127.0.0.1 and has no login. `tailscale serve`
forwards https://<this-mac>.<tailnet>.ts.net to it, for devices signed in to
your tailnet only. This never uses Funnel (Tailscale's public tunnel), and `on`
refuses to run while Funnel is on.

`on` saves this Mac's tailnet name and your Tailscale login in data/phone.json.
The dashboard answers a forwarded request only when it carries that name and
that login, and answers nothing forwarded while the file is missing. While the
file is there, a running dashboard also keeps the Mac awake on AC power.

Usage (from repo root):
  python scripts/phone.py on       # start forwarding and print the phone link
  python scripts/phone.py off      # stop forwarding
  python scripts/phone.py status
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"  # the Mac App Store build has no `tailscale` on PATH
PORT = 8000


class PhoneError(Exception):
    pass


def settings_file(root: Path = REPO_ROOT) -> Path:
    return Path(root) / "data" / "phone.json"


def load(root: Path = REPO_ROOT) -> dict:
    """{"host", "login", "url", "since"} while phone access is on, else {}."""
    try:
        data = json.loads(settings_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("host") and data.get("login") else {}


def cli() -> str:
    found = shutil.which("tailscale") or (APP_CLI if Path(APP_CLI).exists() else None)
    if not found:
        raise PhoneError("Tailscale isn't installed on this Mac. Install it, sign in, and run this again.")
    return found


def tailscale(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    # TAILSCALE_BE_CLI stops the app binary from opening its window instead
    return subprocess.run([cli(), *args], capture_output=capture, text=True,
                          env={**os.environ, "TAILSCALE_BE_CLI": "1"})


def identity() -> tuple[str, str]:
    """This Mac's tailnet name and the login it's signed in with."""
    done = tailscale("status", "--json")
    try:
        status = json.loads(done.stdout)
    except ValueError:
        raise PhoneError(f"Couldn't read Tailscale's status: {(done.stderr or done.stdout).strip()}")
    if status.get("BackendState") != "Running":
        raise PhoneError(f"Tailscale isn't connected ({status.get('BackendState') or 'unknown'}). Open it and sign in.")
    me = status.get("Self") or {}
    host = str(me.get("DNSName") or "").rstrip(".")
    login = ((status.get("User") or {}).get(str(me.get("UserID"))) or {}).get("LoginName") or ""
    if not host or not login:
        raise PhoneError("Tailscale didn't report this Mac's name and login. Turn on MagicDNS in the admin console.")
    return host, login


def funnel_on() -> bool:
    try:
        config = json.loads(tailscale("serve", "status", "--json").stdout or "{}")
    except ValueError:
        return False
    return any((config.get("AllowFunnel") or {}).values())


def dashboard_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/diagnostics", timeout=2):
            return True
    except OSError:
        return False


def on(root: Path = REPO_ROOT) -> dict:
    host, login = identity()
    if funnel_on():
        raise PhoneError("Tailscale Funnel is on, which is public. Turn it off first: tailscale funnel reset")
    # Not captured: the first run may print a link to turn on HTTPS certificates for the tailnet
    done = tailscale("serve", "--bg", "--https=443", f"http://127.0.0.1:{PORT}", capture=False)
    if done.returncode:
        raise PhoneError("`tailscale serve` failed (see above).")
    saved = {"host": host, "login": login, "url": f"https://{host}",
             "since": datetime.now().isoformat(timespec="seconds")}
    settings_file(root).parent.mkdir(parents=True, exist_ok=True)
    settings_file(root).write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
    return saved


def off(root: Path = REPO_ROOT) -> None:
    settings_file(root).unlink(missing_ok=True)  # first, so the dashboard stops answering even if Tailscale fails
    done = tailscale("serve", "--https=443", "off")
    if done.returncode and "not found" not in (done.stderr + done.stdout).lower():
        raise PhoneError(f"The dashboard now refuses phone requests, but `tailscale serve` is still set: "
                         f"{(done.stderr or done.stdout).strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reach the dashboard from your phone over Tailscale.")
    parser.add_argument("cmd", choices=("on", "off", "status"))
    args = parser.parse_args()
    try:
        if args.cmd == "on":
            saved = on()
            print(f"Phone link: {saved['url']}  (only for {saved['login']}, only on your tailnet)")
            print("Restart the dashboard so it keeps the Mac awake while plugged in." if dashboard_running()
                  else f"The dashboard isn't running on 127.0.0.1:{PORT}. Start it to use the link.")
        elif args.cmd == "off":
            off()
            print("Phone access is off.")
            if dashboard_running():
                print("Restart the dashboard so it stops keeping the Mac awake.")
        else:
            saved = load()
            print(f"On since {saved['since']}: {saved['url']} for {saved['login']}" if saved else "Phone access is off.")
            print(tailscale("serve", "status").stdout.strip())
    except PhoneError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
