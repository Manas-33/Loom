#!/usr/bin/env python3
"""
Step 1 — Run this first.
Reads jobs.xlsx and writes each job as a structured markdown file into jobs/.
These files are what OpenCode reads when it does the tailoring.
Optional spreadsheet column `Company_Intro` becomes a `## Company Intro` section
(after `## Job Description`) for company-specific context in cover letters and résumés.

Usage (from repo root):
  python scripts/prepare_jobs.py
  python scripts/prepare_jobs.py --limit 10          # Only first 10 jobs
  python scripts/prepare_jobs.py --filter-company Google
  python scripts/prepare_jobs.py --skip-existing     # Skip jobs already prepared
"""

import os
import re
import argparse
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Settings ────────────────────────────────────────────────
JOBS_FILE    = REPO_ROOT / "jobs.xlsx"
JOBS_DIR     = REPO_ROOT / "jobs"       # Where prompt files go
OUTPUT_DIR   = REPO_ROOT / "output"     # Where OpenCode writes tailored resumes

# Column names — adjust if your sheet headers differ
COL_COMPANY  = "Company"
COL_TITLE    = "Title"
COL_LOCATION = "Location"
COL_DESC     = "About_the_job"
COL_CATEGORY = "Category"
COL_SALARY   = "Salary"
COL_STATUS   = "Status"
# Optional: short “about the company” blurb for cover letters (omit column if unused)
COL_COMPANY_INTRO = "Company_Intro"
# ────────────────────────────────────────────────────────────


def make_slug(company, title, location=""):
    slug = f"{company}_{title}"
    if location:
        slug += f"_{location}"
    slug = re.sub(r'[^\w\-]', '_', slug)
    slug = re.sub(r'_+', '_', slug)
    return slug[:100]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",          type=int, default=None)
    parser.add_argument("--filter-company", type=str, default=None)
    parser.add_argument("--filter-category",type=str, default=None)
    parser.add_argument("--skip-existing",  action="store_true")
    args = parser.parse_args()

    # Load spreadsheet
    df = pd.read_excel(str(JOBS_FILE))
    print(f"Loaded {len(df)} rows from {JOBS_FILE.relative_to(REPO_ROOT)}")

    # Drop rows with no job description
    df = df[df[COL_DESC].notna() & (df[COL_DESC].str.strip() != "")]
    print(f"{len(df)} rows have a job description")

    # Optional filters
    if args.filter_company:
        df = df[df[COL_COMPANY].str.contains(args.filter_company, case=False, na=False)]
    if args.filter_category:
        df = df[df[COL_CATEGORY].str.contains(args.filter_category, case=False, na=False)]
    if args.limit:
        df = df.iloc[:args.limit]

    print(f"Preparing {len(df)} jobs...\n")

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    for _, row in df.iterrows():
        company  = str(row.get(COL_COMPANY,  "Unknown")).strip()
        title    = str(row.get(COL_TITLE,    "Role")).strip()
        location = str(row.get(COL_LOCATION, "")).strip()
        desc     = str(row.get(COL_DESC,     "")).strip()
        salary   = str(row.get(COL_SALARY,   "")).strip()
        category = str(row.get(COL_CATEGORY, "")).strip()

        company_intro = ""
        if COL_COMPANY_INTRO in row.index:
            raw_ci = row.get(COL_COMPANY_INTRO)
            if pd.notna(raw_ci) and str(raw_ci).strip():
                company_intro = str(raw_ci).strip()

        slug     = make_slug(company, title, location)
        job_file = JOBS_DIR / f"{slug}.md"
        out_dir  = OUTPUT_DIR / slug
        out_tex_rel = (Path("output") / slug / "resume.tex").as_posix()

        # Skip if already has a tailored resume
        if args.skip_existing and (out_dir / "resume.tex").exists():
            skipped += 1
            continue

        # Write structured prompt file for OpenCode
        content = f"""# Job: {title} at {company}

## Details
- **Company:** {company}
- **Title:** {title}
- **Location:** {location}
- **Category:** {category}
- **Salary:** {salary}

## Output Path
`{out_tex_rel}`

## Job Description

{desc}
"""
        if company_intro:
            content += f"""
## Company Intro

{company_intro}
"""
        with open(job_file, "w", encoding="utf-8") as f:
            f.write(content)

        out_dir.mkdir(parents=True, exist_ok=True)
        written += 1

    print(f"✅ {written} job files written to {JOBS_DIR.relative_to(REPO_ROOT)}/")
    if skipped:
        print(f"⏭  {skipped} skipped (resume.tex already exists)")
    print(f"\nNext step: open OpenCode and it will follow prompts/TASK.md to tailor all jobs.")


if __name__ == "__main__":
    main()