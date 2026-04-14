#!/bin/bash

# Full resume tailoring pipeline — runs everything in one script.
#
# Usage:
#   chmod +x run_all.sh         (only needed once)
#   ./run_all.sh                 (process all jobs)
#   ./run_all.sh --limit 10      (process first 10 jobs)
#   ./run_all.sh --filter-company Google

# ── Step 1: Prepare job files ──────────────────────────────
echo "📂 Step 1: Preparing job files..."
python prepare_jobs.py --skip-existing "$@"

echo ""

# ── Step 2: Tailor resumes via OpenCode ────────────────────
echo "🧠 Step 2: Tailoring resumes..."
echo ""

for job_file in jobs/*.md; do
    slug=$(basename "$job_file" .md)
    output="output/$slug/resume.tex"

    # Skip if already done
    if [ -f "$output" ]; then
        echo "⏭  Skipping: $slug"
        continue
    fi

    echo "🔄 Processing: $slug"
    opencode run "Read TASK.md, cv.md, and template.tex. Then process only this one job file: $job_file. Write the tailored resume to the output path listed inside it."
done

echo ""

# ── Step 3: Compile PDFs ───────────────────────────────────
echo "📄 Step 3: Compiling PDFs..."
echo ""
python compile_pdfs.py --skip-existing

echo ""
echo "🎉 Done!"