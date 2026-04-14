# Loom

Spreadsheet in, tailored résumé PDFs (and optional cover-letter DOCX files) out. **Loom** turns a list of job postings into per-role LaTeX résumés and PDFs using one source CV, a fixed LaTeX template, and [OpenCode](https://opencode.ai/docs/cli) for the tailoring step. A parallel path produces structured cover letters as JSON, then Word documents.

## Prerequisites

- **Python 3** with `pandas` and `openpyxl` (for `jobs.xlsx`):  
  `pip install pandas openpyxl`
- **`python-docx`** (only if you use the cover-letter builder):  
  `pip install python-docx`
- **[OpenCode](https://opencode.ai/)** CLI on your `PATH`, configured with your model provider (`opencode auth login`, etc.)
- **`pdflatex`** (TeX Live / MacTeX / MiKTeX) for `compile_pdfs.py`

## Quick start (résumés only)

1. **CV** — Copy `cv.example.md` to `cv.md` and fill it with your real experience (see `TASK.md` for how tailoring uses it).
2. **Jobs** — Add `jobs.xlsx` at the repo root. Column names expected by `prepare_jobs.py` are: `Company`, `Title`, `Location`, `About_the_job`, `Category`, `Salary`, `Status`. Optional: `Company_Intro` becomes a `## Company Intro` section in each job file (useful for company-specific context in résumés and cover letters). Edit the script if your sheet differs.
3. **LaTeX** — Adjust `template.tex` for your heading and education (placeholders are filled for experience, projects, and skills).
4. **Run the pipeline**

```bash
chmod +x run_all.sh    # once
./run_all.sh           # optional: --limit 10, --filter-company Name (passed through to prepare_jobs.py)
```

Or run steps manually:

```bash
python prepare_jobs.py --skip-existing
# For each job, or scripted: tailor using TASK.md + cv.md + template.tex → output/<slug>/resume.tex
opencode run "Read TASK.md, cv.md, and template.tex. Then process only this one job file: jobs/Some_Job.md. Write the tailored resume to the output path listed inside it."
python compile_pdfs.py --skip-existing
```

`run_all.sh` uses `opencode run` so the prompt is not mistaken for a project path (see OpenCode [CLI / run](https://opencode.ai/docs/cli)).

## Cover letters

OpenCode writes **`output/<slug>/cover_letter.json`** per job using `cover_letter_task.md`, `cv.md`, and `cover_letter_template.md` (schema and field rules). Then **`build_cover_letters.py`** turns each JSON file into **`cover_letter.docx`** in the same folder.

**Letterhead** (name, address, phone, email, links) is set at the top of `build_cover_letters.py`; edit those constants to match you.

**One-shot script** — After `chmod +x run_with_cover_letter.sh` once:

```bash
./run_with_cover_letter.sh              # same optional args as prepare_jobs: --limit N, --filter-company Name
```

That script prepares job markdown, runs OpenCode for cover letters only, runs `compile_pdfs.py` (for any existing `resume.tex` files), then `build_cover_letters.py`. The résumé tailoring loop inside `run_with_cover_letter.sh` is currently commented out; generate new `resume.tex` files with **`./run_all.sh`** (or uncomment the block) before compiling PDFs if you need fresh résumés.

**Manual cover-letter step** (single job example):

```bash
opencode run "Read cover_letter_task.md, cv.md, and cover_letter_template.md. Then process only this one job file: jobs/Some_Job.md. Write the cover letter data to output/<slug>/cover_letter.json (valid JSON only, schema in cover_letter_template.md)."
python build_cover_letters.py --skip-existing
```

## Repository layout

| Path | Purpose |
|------|---------|
| `jobs.xlsx` | Source spreadsheet (gitignored; keep local or private) |
| `prepare_jobs.py` | Writes one `jobs/<slug>.md` per row |
| `TASK.md` | Instructions for the résumé tailoring agent |
| `cv.md` | Full content pool for experience and projects (gitignored) |
| `cv.example.md` | Safe template to copy → `cv.md` |
| `template.tex` | LaTeX skeleton with placeholders |
| `jobs/` | Per-job markdown (gitignored) |
| `output/<slug>/resume.tex` | Tailored LaTeX (gitignored) |
| `output/<slug>/resume.pdf` | Compiled PDF (gitignored) |
| `output/<slug>/cover_letter.json` | Cover letter content from OpenCode (gitignored) |
| `output/<slug>/cover_letter.docx` | Built Word cover letter (gitignored) |
| `compile_pdfs.py` | Runs `pdflatex` on each `output/**/resume.tex` |
| `run_all.sh` | Prepare jobs → OpenCode per missing résumé → compile PDFs |
| `cover_letter_task.md` | Instructions for the cover-letter agent |
| `cover_letter_template.md` | JSON schema / rules for `cover_letter.json` |
| `build_cover_letters.py` | JSON → `cover_letter.docx` |
| `run_with_cover_letter.sh` | Prepare jobs → OpenCode cover letters → PDFs → DOCX |

## Privacy

`.gitignore` excludes `cv.md`, `jobs.xlsx`, `jobs/`, and `output/` so résumé text, job exports, generated TeX/PDFs, cover-letter JSON, and DOCX files stay local.
