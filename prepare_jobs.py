#!/usr/bin/env python3
"""
Step 1 — Run this first.
Reads jobs.xlsx and writes each job as a structured markdown file into /jobs/
These files are what OpenCode reads when it does the tailoring.

Usage:
  python prepare_jobs.py
  python prepare_jobs.py --limit 10          # Only first 10 jobs
  python prepare_jobs.py --filter-company Google
  python prepare_jobs.py --skip-existing     # Skip jobs already prepared
"""

import os
import re
import argparse
import pandas as pd

# ── Settings ────────────────────────────────────────────────
JOBS_FILE    = "jobs.xlsx"
JOBS_DIR     = "jobs"       # Where prompt files go
OUTPUT_DIR   = "output"     # Where OpenCode writes tailored resumes

# Column names — adjust if your sheet headers differ
COL_COMPANY  = "Company"
COL_TITLE    = "Title"
COL_LOCATION = "Location"
COL_DESC     = "About_the_job"
COL_CATEGORY = "Category"
COL_SALARY   = "Salary"
COL_STATUS   = "Status"
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
    df = pd.read_excel(JOBS_FILE)
    print(f"Loaded {len(df)} rows from {JOBS_FILE}")

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

    os.makedirs(JOBS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    written = 0
    skipped = 0

    for _, row in df.iterrows():
        company  = str(row.get(COL_COMPANY,  "Unknown")).strip()
        title    = str(row.get(COL_TITLE,    "Role")).strip()
        location = str(row.get(COL_LOCATION, "")).strip()
        desc     = str(row.get(COL_DESC,     "")).strip()
        salary   = str(row.get(COL_SALARY,   "")).strip()
        category = str(row.get(COL_CATEGORY, "")).strip()

        slug     = make_slug(company, title, location)
        job_file = os.path.join(JOBS_DIR, f"{slug}.md")
        out_dir  = os.path.join(OUTPUT_DIR, slug)

        # Skip if already has a tailored resume
        if args.skip_existing and os.path.exists(os.path.join(out_dir, "resume.tex")):
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
`{out_dir}/resume.tex`

## Job Description
{desc}
"""
        with open(job_file, "w", encoding="utf-8") as f:
            f.write(content)

        os.makedirs(out_dir, exist_ok=True)
        written += 1

    print(f"✅ {written} job files written to /{JOBS_DIR}/")
    if skipped:
        print(f"⏭  {skipped} skipped (resume.tex already exists)")
    print(f"\nNext step: open OpenCode and it will follow TASK.md to tailor all jobs.")


if __name__ == "__main__":
    main()