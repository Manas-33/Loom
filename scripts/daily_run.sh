#!/bin/bash
# The scheduled Loom run (launchd → loom-runner → this script; see scripts/launchd/):
#   1. check_boards.py: every company board; Sundays read Workday sites in full
#   2. check_simplify.py: new rows on the SimplifyJobs new-grad list
#   3. check_descriptions.py: free checks + Codex → inbox
#   4. on the 1st, build_boards.py: refresh the company board list
#   5. inbox.py dedupe: reject pending jobs already in the sheet or the inbox
# A missed Sunday or 1st (Mac asleep or off) catches up on the next run.
# Runs never overlap (lock in data/.run.lock). Output: data/logs/<date>.log
#
#   scripts/daily_run.sh           # the full run
#   scripts/daily_run.sh --smoke   # check paths, permissions, lock and Codex login only

set -u
REPO="/Users/dalvi/Documents/loom"
PY="/Users/dalvi/.pyenv/versions/3.12.0/envs/ottonote/bin/python3"
DESCRIPTION_LIMIT=400   # Codex jobs per run (16 batches); the rest stay pending for tomorrow
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONUNBUFFERED=1

cd "$REPO" || { echo "$(date '+%F %T') can't open $REPO"; exit 1; }
mkdir -p data/logs || exit 1
exec >>"data/logs/$(date +%F).log" 2>&1

log() { echo "[$(date +%T)] $*"; }

LOCK="data/.run.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    pid=$(cat "$LOCK/pid" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        log "another run (pid $pid) is still going; skipping"
        exit 0
    fi
    rm -rf "$LOCK" && mkdir "$LOCK" || exit 1
fi
echo $$ >"$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

# Days since the date stored in a stamp file (999 if there isn't one)
days_since() {
    local last
    last=$(cat "$1" 2>/dev/null) || { echo 999; return; }
    echo $(( ($(date +%s) - $(date -j -f %Y-%m-%d "$last" +%s)) / 86400 ))
}

if [ "${1:-}" = "--smoke" ]; then
    log "smoke test"
    "$PY" -c "import sqlite3, yaml; db = sqlite3.connect('data/loom.db'); \
print('inbox pending:', db.execute(\"SELECT COUNT(*) FROM inbox WHERE status='pending'\").fetchone()[0]); \
print('profile keys:', len(yaml.safe_load(open('profile.local.yaml')))); \
import os; print('candidate files:', len(os.listdir('data/candidates')))" || exit 1
    codex login status || exit 1
    log "smoke test ok"
    exit 0
fi

FULL_STAMP="data/.last-workday-full"
REFRESH_STAMP="data/.last-board-refresh"
failed=0
log "=== daily run ==="

board_args=()
if { [ "$(date +%u)" = 7 ] && [ "$(days_since "$FULL_STAMP")" -ge 1 ]; } || [ "$(days_since "$FULL_STAMP")" -ge 8 ]; then
    board_args+=(--workday-full)
fi
log "check_boards.py ${board_args[*]:-}"
if "$PY" scripts/check_boards.py ${board_args[@]+"${board_args[@]}"}; then
    [ ${#board_args[@]} -gt 0 ] && date +%F >"$FULL_STAMP"
else
    log "check_boards.py failed ($?)"; failed=1
fi

log "check_simplify.py"
"$PY" scripts/check_simplify.py || { log "check_simplify.py failed ($?)"; failed=1; }

log "check_descriptions.py --limit $DESCRIPTION_LIMIT"
"$PY" scripts/check_descriptions.py --limit "$DESCRIPTION_LIMIT" --parallel 3 || { log "check_descriptions.py failed ($?)"; failed=1; }

if { [ "$(date +%d)" = 01 ] && [ "$(days_since "$REFRESH_STAMP")" -ge 7 ]; } || [ "$(days_since "$REFRESH_STAMP")" -ge 32 ]; then
    log "build_boards.py"
    if "$PY" scripts/build_boards.py; then
        date +%F >"$REFRESH_STAMP"
    else
        log "build_boards.py failed ($?)"; failed=1
    fi
fi

log "inbox.py dedupe"
"$PY" scripts/inbox.py dedupe || { log "inbox.py dedupe failed ($?)"; failed=1; }
"$PY" scripts/inbox.py stats
find data/logs -name '*.log' -mtime +60 -delete
log "=== done$([ $failed = 1 ] && echo ' with failures') ==="
exit $failed
