# Loom

Spreadsheet in, tailored résumé PDFs out. **Loom** turns a list of job postings into per-role LaTeX résumés (and PDFs) using one source CV, a fixed LaTeX template, and [OpenCode](https://opencode.ai/docs/cli) for the tailoring step.

## Prerequisites

- **Python 3** with `pandas` and `openpyxl` (for `jobs.xlsx`):  
  `pip install pandas openpyxl`
- **[OpenCode](https://opencode.ai/)** CLI on your `PATH`, configured with your model provider (`opencode auth login`, etc.)
- **`pdflatex`** (TeX Live / MacTeX / MiKTeX) for `compile_pdfs.py`

## Quick start

1. **CV** — Copy `cv.example.md` to `cv.md` and fill it with your real experience (see `TASK.md` for how tailoring uses it).
2. **Jobs** — Add `jobs.xlsx` at the repo root. Column names expected by `prepare_jobs.py` are: `Company`, `Title`, `Location`, `About_the_job`, `Category`, `Salary`, `Status` (edit the script if your sheet differs).
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

## Repository layout

| Path | Purpose |
|------|---------|
| `jobs.xlsx` | Source spreadsheet (gitignored; keep local or private) |
| `prepare_jobs.py` | Writes one `jobs/<slug>.md` per row |
| `TASK.md` | Instructions for the tailoring agent |
| `cv.md` | Full content pool for experience and projects (gitignored) |
| `cv.example.md` | Safe template to copy → `cv.md` |
| `template.tex` | LaTeX skeleton with placeholders |
| `jobs/` | Per-job markdown (gitignored) |
| `output/<slug>/resume.tex` | Tailored LaTeX (gitignored) |
| `compile_pdfs.py` | Runs `pdflatex` on each `output/**/resume.tex` |
| `run_all.sh` | Prepare jobs → OpenCode per missing output → compile PDFs |

## Privacy

`.gitignore` excludes `cv.md`, `jobs.xlsx`, `jobs/`, and `output/` so résumé text, job exports, and generated TeX/PDFs stay local.
