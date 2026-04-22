# Loom

Spreadsheet in, tailored résumé PDFs (and optional cover-letter DOCX files) out. **Loom** turns a list of job postings into per-role LaTeX résumés and PDFs using one source CV, a fixed LaTeX template, and [OpenCode](https://opencode.ai/docs/cli) for the tailoring step. A parallel path produces structured cover letters as JSON, then Word documents.

## Prerequisites

- **Python 3** with `pandas` and `openpyxl` (for `jobs.xlsx`):  
  `pip install pandas openpyxl`
- **`python-docx`** (only if you use the cover-letter builder):  
  `pip install python-docx`
- **[OpenCode](https://opencode.ai/)** CLI on your `PATH`, configured with your model provider (`opencode auth login`, etc.)
- **`pdflatex`** (TeX Live / MacTeX / MiKTeX) for `scripts/compile_pdfs.py`

## Quick start (résumés only)

1. **CV** — Copy `cv.example.md` to `cv.md` and fill it with your real experience (see `prompts/TASK.md` for how tailoring uses it).
2. **Jobs** — Add `jobs.xlsx` at the repo root. Column names expected by `scripts/prepare_jobs.py` are: `Company`, `Title`, `Location`, `About_the_job`, `Category`, `Salary`, `Status`. Optional: `Company_Intro` becomes a `## Company Intro` section in each job file (useful for company-specific context in résumés and cover letters). Edit the script if your sheet differs.
3. **LaTeX** — Adjust `templates/template.tex` for your heading and education (placeholders are filled for experience, projects, and skills).
4. **Run the pipeline**

```bash
chmod +x run_all.sh    # once
./run_all.sh           # optional: --limit 10, --filter-company Name (passed through to prepare_jobs.py)
```

Or run steps manually (from repo root):

```bash
python scripts/prepare_jobs.py --skip-existing
# For each job, or scripted: tailor using prompts/TASK.md + cv.md + templates/template.tex → output/<slug>/resume.tex
opencode run "Read prompts/TASK.md, cv.md, and templates/template.tex. Then process only this one job file: jobs/Some_Job.md. Write the tailored resume to the output path listed inside it."
python scripts/compile_pdfs.py --skip-existing
```

`run_all.sh` uses `opencode run` so the prompt is not mistaken for a project path (see OpenCode [CLI / run](https://opencode.ai/docs/cli)).

## Cover letters

OpenCode writes **`output/<slug>/cover_letter.json`** per job using `prompts/cover_letter_task.md`, `cv.md`, and `templates/cover_letter_template.md` (schema and field rules). Then **`scripts/build_cover_letters.py`** turns each JSON file into **`cover_letter.docx`** in the same folder.

**Letterhead** (name, address, phone, email, links) is set at the top of `scripts/build_cover_letters.py`; edit those constants to match you.

**One-shot script** — After `chmod +x run_with_cover_letter.sh` once:

```bash
./run_with_cover_letter.sh              # same optional args as prepare_jobs: --limit N, --filter-company Name
```

That script prepares job markdown, runs OpenCode for each missing `resume.tex`, then for each missing `cover_letter.json`, runs `scripts/compile_pdfs.py`, then `scripts/build_cover_letters.py`.

**Manual cover-letter step** (single job example):

```bash
opencode run "Read prompts/cover_letter_task.md, cv.md, and templates/cover_letter_template.md. Then process only this one job file: jobs/Some_Job.md. Write the cover letter data to output/<slug>/cover_letter.json (valid JSON only, schema in templates/cover_letter_template.md)."
python scripts/build_cover_letters.py --skip-existing
```

## Repository layout

| Path | Purpose |
|------|---------|
| `scripts/prepare_jobs.py` | Reads `jobs.xlsx`, writes one `jobs/<slug>.md` per row |
| `scripts/compile_pdfs.py` | Runs `pdflatex` on each `output/**/resume.tex` |
| `scripts/build_cover_letters.py` | JSON → `cover_letter.docx` |
| `prompts/TASK.md` | Instructions for the résumé tailoring agent |
| `prompts/cover_letter_task.md` | Instructions for the cover-letter agent |
| `templates/template.tex` | LaTeX skeleton with placeholders |
| `templates/cover_letter_template.md` | JSON schema / rules for `cover_letter.json` |
| `jobs.xlsx` | Source spreadsheet (gitignored; keep local or private) |
| `cv.md` | Full content pool for experience and projects (gitignored) |
| `cv.example.md` | Safe template to copy → `cv.md` |
| `jobs/` | Per-job markdown (gitignored) |
| `output/<slug>/resume.tex` | Tailored LaTeX (gitignored) |
| `output/<slug>/resume.pdf` | Compiled PDF (gitignored) |
| `output/<slug>/cover_letter.json` | Cover letter content from OpenCode (gitignored) |
| `output/<slug>/cover_letter.docx` | Built Word cover letter (gitignored) |
| `run_all.sh` | Prepare jobs → OpenCode per missing résumé → compile PDFs |
| `run_with_cover_letter.sh` | Prepare jobs → résumés + cover letters → PDFs → DOCX |

## Privacy

`.gitignore` excludes `cv.md`, `jobs.xlsx`, `jobs/`, and `output/` so résumé text, job exports, generated TeX/PDFs, cover-letter JSON, and DOCX files stay local.

## Local dashboard

You can also run a **localhost-only** dashboard that wraps the same scripts and `opencode` commands with a browser UI, live logs, diagnostics, and download links.

Install the extra web dependencies:

```bash
pip install -r dashboard_requirements.txt
```

Then start the app from the repo root:

```bash
uvicorn dashboard.app:app --host 127.0.0.1 --port 8000 --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

What the dashboard can do:

- Scan `jobs/` and `output/` to show artifact status per job
- Run `scripts/prepare_jobs.py` with `--limit`, `--filter-company`, `--filter-category`, and `--skip-existing`
- Run the same `opencode run "..."` prompts as `run_all.sh` and `run_with_cover_letter.sh`
- Compile PDFs and build cover-letter DOCX files
- Stream stdout/stderr into the browser with cancel support for the active subprocess

The server is intended to stay on your machine only, so keep it bound to `127.0.0.1`.
