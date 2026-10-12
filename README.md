# Loom

A personal job-search workspace: discover opportunities, review your inbox, and keep track of applications.

Company board checks and description reviews send promising roles to an inbox. Only jobs you **Keep** enter the application tracker. Pasted postings go straight to the tracker after you review them.

## Run locally

```bash
pip install -r dashboard_requirements.txt
uvicorn dashboard.app:app --host 127.0.0.1 --port 8000 --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Keep the server bound to `127.0.0.1`; the dashboard has no login.

The built React interface is included in `dashboard/static/`, so Node is only needed when changing the frontend. The backend is FastAPI; data stays in the local SQLite inbox, `jobs.xlsx`, job markdown files, and generated documents.

## Phone access

The dashboard can be reached from your phone over [Tailscale](https://tailscale.com), and only by devices signed in to your own tailnet. It stays bound to `127.0.0.1`; never put it behind a public tunnel.

1. Install Tailscale on the Mac and the phone and sign in to both with the same account. In the admin console, turn on MagicDNS and HTTPS certificates.
2. Turn it on, then open the printed `https://<mac>.<tailnet>.ts.net` link on the phone:

```bash
python scripts/phone.py on       # tailscale serve → 127.0.0.1:8000, prints the link
python scripts/phone.py status
python scripts/phone.py off
```

`on` saves the Mac's tailnet name and your Tailscale login in `data/phone.json`. The dashboard answers a forwarded request only when it arrives under that name with that login, so another tailnet user, Tailscale Funnel, or a request under any other hostname gets a 403. `on` also refuses to run while Funnel is on. While phone access is on, a running dashboard keeps the Mac awake on AC power (`caffeinate -s`); a closed laptop lid still sleeps. The System page shows the link.

## The dashboard

- **Inbox**: review job cards with posting links, sources, suggested resume buckets, experience requirements, flags, and the reason a role passed. Search, filter by resume or source, and optionally hide no-sponsorship postings. Expand the description, or open full details.
- **Keep / Reject**: act on one job or select several. Keep saves through the shared `add_job` writer as **Not Applied**. A brief Undo toast reverses the decision. Undo preserves pre-existing duplicates and refuses to erase a job that has since been edited or given documents.
- **Review**: every kept job gets a resume tailored from its bucket, with up to three suggested tweaks to Use or Skip, and drafted answers to the application's written questions. Work through them one at a time. Filter by search, kind (resumes, answers, quick look), resume, and source. Shortcuts: `Enter` done, `y` use all tweaks, `n` send as-is, `f` fill the application, `j` / `k` next and previous.
- **Forms**: applications filled in your Chrome that still need you, one at a time. Answer the fields the form couldn't fill, leave a comment to change anything on the filled form, then press **Submit for me** or mark it submitted yourself. Only jobs still **Not Applied** appear. Filter by search, form status, and source. Shortcuts: `Enter` fills your answers in, `s` submits, `m` marks it submitted, `j` / `k` next and previous.
- **My jobs**: a compact tracker with total / not-applied counts, search, status filters, and direct posting links. Click a role to open its full page. Select several to fill their applications, tailor them, or change their status at once. Available statuses: **Not Applied, Applied, OA, Interview, Offer, Reject, Ignore**. Resume PDFs and cover letters appear when available. Removing a job requires confirmation; recovery files are retained under `data/trash/`.
- **Job details**: description, application and posting links, suggested resume, flags, status, and documents, followed by the tailored resume with its tweaks, the drafted application answers, and the Application section that fills the form in your Chrome and stops before Submit.
- **Add job**: paste the full posting text, click **Fill in form**, review any warnings, edit the fields, and save. A duplicate shows the existing entry before offering **Add anyway**. An identical company/title/location combination cannot be duplicated because it shares the same document path.
- **System**: view the last board check, description-review totals, inbox counts, live board counts, recorded Codex capacity, phone access, and local diagnostics. This page is view-only.

The interface has light and dark appearances, bottom navigation on phones, and reduced-motion support. On a touch screen, swipe a card right to Keep or left to Reject; buttons remain available. Desktop inbox shortcuts: `j` / `k` select a card, `y` keeps it, `n` rejects it, and `/` focuses search.

## Frontend development

React + Vite builds into the static directory served by FastAPI:

```bash
cd dashboard/frontend
npm ci
npm run build
```

For hot reload, run FastAPI on port 8000, then `npm run dev` in `dashboard/frontend`. Vite proxies API and document requests to FastAPI. Rebuild after edits to update the regular port-8000 dashboard.

```bash
# From the repository root; every write is isolated to a temporary workspace.
python -m unittest discover -s dashboard/tests -v
```

## Job data and documents

All new jobs are validated, deduplicated, and saved through `scripts/add_job.py`. The writer locks the workbook across processes, saves it atomically, and backs up the original before adding columns. Status changes, removal, and inbox undo use the same writer and lock. Tracker listings read the workbook, so old orphan document folders do not create phantom jobs.

```bash
pbpaste | python scripts/extract_job.py - --add
python scripts/add_job.py records.jsonl
```

Set `LOOM_EXTRACT_ENGINE=claude` to extract with Claude instead of Codex; `LOOM_EXTRACT_MODEL` selects the model. Extraction preserves posting links only when present in the pasted text.

Tailoring starts when you keep a job: `scripts/tailor.py` runs the `pick-resume-auto` skill in that job's own Claude session (or Codex), starting from your bucket resumes in `buckets/`, which stay local. The same session drafts application answers (`app-answers`); a separate Claude in Chrome session fills the form (`apply-form`). The `pick-resume` skill is still there for picking a resume by hand. Cover letters use the `cover-letter` skill, `prompts/cover_letter_task.md`, `templates/cover_letter_template.md`, and `scripts/build_cover_letters.py`.

Legacy pipeline scripts, templates, and the previous frontend are preserved locally in `archive/`. Pipeline execution endpoints and controls have been removed from the dashboard.

### Company job-board list

`scripts/build_boards.py` builds the list of company job boards (Greenhouse, Ashby, Lever, Workday) that Loom checks for new jobs. It merges five sources: the [job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) company lists, the [find-jobs](https://github.com/blakegrudzien/find-jobs) lists, board links in recent Common Crawl snapshots, apply links in the [SimplifyJobs new-grad list](https://github.com/SimplifyJobs/New-Grad-Positions), and the links in your own `jobs.xlsx`. Each new board is checked once through its public API and marked ok, dead, closed (a Workday site not taking applicants right now) or error.

```bash
python scripts/build_boards.py            # full refresh, run monthly
python scripts/build_boards.py --stats    # counts per site
```

The list is saved to `data/boards.json`, which is gitignored.

### Daily job-board check

`scripts/check_boards.py` checks every live board in `data/boards.json` for new jobs:

1. **Download** each board's job list. Greenhouse, Ashby and Lever send nothing when a board hasn't changed since the last run. Workday is read newest first and stops at older jobs.
2. **Filter** with `scripts/job_filters.py`: location first (US or remote-US; unclear locations are kept), then title (engineering, not senior, not an internship).
3. **Keep new jobs** that weren't seen before. Descriptions are fetched only for those, and they're written to `data/candidates/<date>.jsonl` for the description check.

```bash
python scripts/check_boards.py              # daily
python scripts/check_boards.py --workday-full   # weekly: read Workday sites in full
```

State (board versions, the seen list, run history) lives in `data/loom.db`.

### Description check and inbox

`scripts/check_descriptions.py` decides which candidates from the daily check are real early-career fits. Free checks run first (recruiting platforms, title rules, security clearance or US citizenship, plain titles asking for 3+ years, jobs already in your sheet). Then Codex reads the full description in batches of 25 and checks experience, graduation window, location, PhD and GPA. Your graduation date, degree, school and GPA come from `profile.local.yaml` (gitignored).

Jobs that pass go to the **inbox** (`scripts/inbox.py`), not your sheet. You keep or reject each one, and only kept jobs are added to `jobs.xlsx`, as Not Applied.

```bash
python scripts/check_descriptions.py                      # candidates → inbox
python scripts/check_descriptions.py --preview --limit 10 # print decisions, save nothing
python scripts/inbox.py list                              # what's waiting
python scripts/inbox.py keep <job_id>                     # add to jobs.xlsx
python scripts/inbox.py reject <job_id>
python scripts/inbox.py page                              # data/inbox.html to browse
```

### LinkedIn and Handshake sweeps

The `sweep` skill (`.agents/skills/sweep/`, linked into `.claude/skills/`) has Codex or Claude read LinkedIn and Handshake job search in your own signed-in Chrome, only when you ask ("run the sweep") and only while you're at the Mac. It records each posting's description and real application link, never applies, and never signs in. `scripts/sweep_add.py` then treats that file as untrusted: the same location and title rules, duplicates merged, descriptions re-read from the company board when the link is one, and new boards added to the board list.

```bash
python scripts/sweep_add.py data/sweeps/<date>-linkedin.jsonl --dry-run   # what would happen
python scripts/sweep_add.py data/sweeps/<date>-linkedin.jsonl --check     # candidates, then the description check
```

Sweep finds sort to the top of the inbox. Easy Apply and Handshake-only postings are tagged on the card.

### Evening email

`scripts/daily_email.py` builds the day's new inbox jobs as a styled card, grouped by source, with the dashboard's tags, links into the dashboard (the phone link when phone access is on) and one line on how the daily check ended. A Claude routine (Routines in the Claude app) sends it through the Gmail connector to one fixed address. The fallback is `--send`: `smtplib` with `LOOM_EMAIL_USER` and `LOOM_EMAIL_APP_PASSWORD` (a Gmail app password) in `.env`, sent to that same account.

```bash
python scripts/daily_email.py                 # print today's email
python scripts/daily_email.py --date 2026-09-29
python scripts/daily_email.py --send          # fallback sender
```

## Privacy

`jobs.xlsx`, `jobs/`, `output/`, `cv.md`, `buckets/`, `dashboard_statuses.json`, `data/`, `archive/`, `profile.local.yaml`, exported application history (`simplify_import*.csv`), and `.env` are gitignored. Keep personal records and test datasets in those local locations. The production frontend assets contain no personal data.
