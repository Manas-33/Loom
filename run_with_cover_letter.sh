#!/bin/bash
cd "$(dirname "$0")"

# Full pipeline — resumes + cover letters in one script.
#
# Usage:
#   chmod +x run_with_cover_letter.sh         (only needed once)
#   ./run_with_cover_letter.sh                 (process all jobs)
#   ./run_with_cover_letter.sh --limit 10      (process first 10 jobs)
#   ./run_with_cover_letter.sh --filter-company Google

# ── Step 1: Prepare job files ──────────────────────────────
echo "📂 Step 1: Preparing job files..."
python scripts/prepare_jobs.py --skip-existing "$@"
echo ""

# ── Step 2: Tailor resumes via OpenCode ────────────────────
echo "🧠 Step 2: Tailoring resumes..."
echo ""

for job_file in jobs/*.md; do
    slug=$(basename "$job_file" .md)
    output="output/$slug/resume.tex"

    if [ -f "$output" ]; then
        echo "⏭  Skipping resume: $slug"
        continue
    fi

    echo "🔄 Resume: $slug"
    opencode run "Read prompts/TASK.md, cv.md, and templates/template.tex. Then process only this one job file: $job_file. Write the tailored resume to the output path listed inside it."
done

echo ""

# ── Step 3: Write cover letters via OpenCode ───────────────
echo "✉️  Step 3: Writing cover letters..."
echo ""

for job_file in jobs/*.md; do
    slug=$(basename "$job_file" .md)
    output="output/$slug/cover_letter.json"

    if [ -f "$output" ]; then
        echo "⏭  Skipping cover letter: $slug"
        continue
    fi

    echo "🔄 Cover letter: $slug"
    opencode run "Read prompts/cover_letter_task.md, cv.md, and templates/cover_letter_template.md. Then process only this one job file: $job_file. Write the cover letter data to output/$slug/cover_letter.json (valid JSON only, schema in templates/cover_letter_template.md)."
done

echo ""

# ── Step 4: Compile all PDFs ───────────────────────────────
echo "📄 Step 4: Compiling resume PDFs..."
python scripts/compile_pdfs.py --skip-existing

echo ""
echo "📄 Step 5: Building cover letter DOCX files..."
python scripts/build_cover_letters.py --skip-existing

echo ""
echo "🎉 Done! Check the /output/ folder."