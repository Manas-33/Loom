#!/usr/bin/env python3
"""
Read a saved job's application questions before applying.

Greenhouse (its job board API with ?questions=true) and Ashby (its job board's
GraphQL) publish every field on the application form, and Lever's public apply
page carries its custom questions as JSON. Other sites (Workday, iCIMS, company
career sites) only show theirs after signing in or during the application, so
they return no questions; the fill finds them and the job's session drafts them.

  fetch(url) -> {"source": "greenhouse" | "ashby" | "lever" | None, "questions": [...]}

Each question: {"id", "label", "description", "required", "type", "options", "section"}
  type: text | textarea | select | multiselect | boolean | file | date | number
  section: "application", "eeo" (voluntary self-identification) or "location"

Usage (from repo root):
  python scripts/app_questions.py <posting url>
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_job import job_id_from_url  # noqa: E402
from boards import _request, board_from_url, html_to_text  # noqa: E402

CANDIDATES_DIR = Path(__file__).resolve().parent.parent / "data" / "candidates"

_GH_TYPES = {"input_text": "text", "textarea": "textarea", "input_file": "file",
             "multi_value_single_select": "select", "multi_value_multi_select": "multiselect"}
_ASHBY_TYPES = {"String": "text", "Email": "text", "Phone": "text", "SocialLink": "text", "Location": "text",
                "LongText": "textarea", "File": "file", "Boolean": "boolean", "ValueSelect": "select",
                "MultiValueSelect": "multiselect", "Date": "date", "Number": "number"}
_ASHBY_QUERY = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    applicationForm { sections { title fieldEntries { ... on FormFieldEntry { isRequired descriptionHtml field } } } }
  }
}"""


def _question(qid, label, required, qtype, options=(), section="application", description="") -> dict:
    return {"id": str(qid), "label": " ".join(str(label or "").split()), "description": description,
            "required": bool(required), "type": qtype, "options": [str(o) for o in options if str(o).strip()],
            "section": section}


def _greenhouse(board: str, job: str) -> list[dict]:
    resp = _request("GET", f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job}?questions=true",
                    retry_on=(403, 429))
    if resp.status_code != 200:
        return []
    data = resp.json()
    out = []

    def add(q: dict, section: str):
        for field in q.get("fields") or []:
            qtype = _GH_TYPES.get(field.get("type"))
            if qtype is None:  # hidden fields (latitude, longitude)
                continue
            out.append(_question(field.get("name"), q.get("label"), q.get("required"), qtype,
                                 [v.get("label") for v in field.get("values") or []], section,
                                 html_to_text(q.get("description") or "")))
            break  # a question's extra fields are the same answer in another form (e.g. a file or pasted text)

    for q in data.get("questions") or []:
        add(q, "application")
    for q in data.get("location_questions") or []:
        add(q, "location")
    for block in data.get("compliance") or []:
        for q in block.get("questions") or []:
            add(q, "eeo")
    demo = data.get("demographic_questions") or {}
    for q in demo.get("questions") or []:
        qtype = _GH_TYPES.get(q.get("type"), "text")
        out.append(_question(f"demographic_{q.get('id')}", q.get("label"), q.get("required"), qtype,
                             [o.get("label") for o in q.get("answer_options") or []], "application",
                             html_to_text(demo.get("description") or "")))
    return out


def _ashby(board: str, job: str) -> list[dict]:
    resp = _request("POST", "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting",
                    json={"operationName": "ApiJobPosting", "query": _ASHBY_QUERY,
                          "variables": {"organizationHostedJobsPageName": board, "jobPostingId": job}},
                    headers={"Content-Type": "application/json"})
    if resp.status_code != 200:
        return []
    posting = ((resp.json().get("data") or {}).get("jobPosting") or {})
    out = []
    for section in ((posting.get("applicationForm") or {}).get("sections") or []):
        name = "eeo" if "eeo" in str(section.get("title") or "").lower() or "voluntary" in str(section.get("title") or "").lower() \
            else "application"
        for entry in section.get("fieldEntries") or []:
            field = entry.get("field") or {}
            if not field:
                continue
            out.append(_question(field.get("path") or field.get("id"), field.get("title"), entry.get("isRequired"),
                                 _ASHBY_TYPES.get(field.get("type"), "text"),
                                 [o.get("label") for o in field.get("selectableValues") or []], name,
                                 html_to_text(entry.get("descriptionHtml") or "")))
    return out


_LEVER_TYPES = {"text": "text", "textarea": "textarea", "multiple-choice": "select", "dropdown": "select",
                "multiple-select": "multiselect", "file-upload": "file", "date": "date"}
# The standard fields every Lever form has, by input name (labels as Lever shows them)
_LEVER_STANDARD = [("resume", "Resume/CV", "file"), ("name", "Full name", "text"), ("email", "Email", "text"),
                   ("phone", "Phone", "text"), ("location", "Current location", "text"),
                   ("org", "Current company", "text"), ("urls[LinkedIn]", "LinkedIn URL", "text"),
                   ("urls[GitHub]", "GitHub URL", "text"), ("urls[Portfolio]", "Portfolio URL", "text"),
                   ("urls[Other]", "Other website", "text"), ("comments", "Additional information", "textarea")]


def _lever(board: str, job: str) -> list[dict]:
    """Lever's apply page: the standard fields, the custom question cards (JSON in hidden inputs) and EEO selects."""
    resp = _request("GET", f"https://jobs.lever.co/{board}/{job}/apply")
    if resp.status_code != 200:
        return []
    page = resp.text
    out = []
    for name, label, qtype in _LEVER_STANDARD:
        if f'name="{name}"' in page:
            required = bool(re.search(rf'name="{re.escape(name)}"[^>]*required', page))
            out.append(_question(name, label, required or name in ("resume", "name", "email"), qtype))
    for value, card in re.findall(r'<input[^>]*value="([^"]*)"[^>]*name="cards\[([0-9a-f-]+)\]\[baseTemplate\]"', page):
        try:
            template = json.loads(html.unescape(value))
        except ValueError:
            continue
        for n, field in enumerate(template.get("fields") or []):
            out.append(_question(f"cards[{card}][field{n}]", field.get("text"), field.get("required"),
                                 _LEVER_TYPES.get(field.get("type"), "text"),
                                 [o.get("text") for o in field.get("options") or []], "application",
                                 html_to_text(field.get("description") or "")))
    for name, body in re.findall(r'<select[^>]*name="(eeo\[(?:gender|race|veteran|disability)\])"[^>]*>(.*?)</select>', page, re.S):
        options = [html.unescape(o).strip() for o in re.findall(r"<option[^>]*>([^<]*)</option>", body)]
        label = {"eeo[gender]": "Gender", "eeo[race]": "Race", "eeo[veteran]": "Veteran status",
                 "eeo[disability]": "Disability status"}[name]
        out.append(_question(name, label, False, "select", [o for o in options if o and not o.lower().startswith("select")], "eeo"))
    return out


def board_hint(job_id: str) -> tuple[str, str] | None:
    """(site, board) the board check recorded for a job, for links on a company's own domain
    (e.g. example.com/jobs?gh_jid=123) that don't name their Greenhouse board."""
    ids = {i.strip() for i in str(job_id or "").split(",") if i.strip()}
    for path in sorted(CANDIDATES_DIR.glob("*.jsonl"), reverse=True):
        for line in path.read_text(encoding="utf-8").splitlines():
            if any(f'"job_id": "{i}"' in line for i in ids):
                site, _, board = json.loads(line).get("_board", "").partition(":")
                if site and board:
                    return site, board
    return None


_NOT_A_NAME = {"www", "com", "io", "co", "org", "net", "ai", "us", "careers", "career", "jobs", "job", "apply", "boards"}


def greenhouse_board_for(url: str, job: str, company: str = "") -> str | None:
    """The Greenhouse board of a job shown on a company's own site (e.g. pinterestcareers.com/jobs/…?gh_jid=123),
    found by trying names from the company and the domain. A name counts only if Greenhouse has this exact job on it."""
    host = (urlparse(url or "").hostname or "").lower()
    names = [company] + [part for part in host.split(".") if part not in _NOT_A_NAME]
    tries: list[str] = []
    for name in names:
        base = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
        for guess in (base, re.sub(r"(careers?|jobs|hiring|talent|inc)$", "", base), re.sub(r"^(careers?|jobs)", "", base)):
            if len(guess) >= 2 and guess not in tries:
                tries.append(guess)
    for guess in tries[:6]:
        try:
            if _request("GET", f"https://boards-api.greenhouse.io/v1/boards/{guess}/jobs/{job}",
                        retry_on=(403, 429)).status_code == 200:
                return guess
        except RuntimeError:
            continue
    return None


def fetch(url: str, job_id: str = "", company: str = "") -> dict:
    """The application form's questions for a posting link, when its site publishes them."""
    board = board_from_url(url or "")
    link_id = job_id_from_url(url or "") or ""
    job = link_id.split(":")[-1]
    if not board and job:
        board = board_hint(job_id or link_id)
    if not board and link_id.startswith("greenhouse:"):  # a gh_jid link on the company's own site
        token = greenhouse_board_for(url, job, company)
        board = ("greenhouse", token) if token else None
    if not board or not job:
        return {"source": None, "questions": []}
    try:
        if board[0] == "greenhouse":
            return {"source": "greenhouse", "questions": _greenhouse(board[1], job)}
        if board[0] == "ashby":
            return {"source": "ashby", "questions": _ashby(board[1], job)}
        if board[0] == "lever":
            return {"source": "lever", "questions": _lever(board[1], job)}
    except (RuntimeError, ValueError):
        return {"source": board[0], "questions": [], "error": "couldn't read the form"}
    return {"source": None, "questions": []}


if __name__ == "__main__":
    print(json.dumps(fetch(sys.argv[1]), indent=2))
