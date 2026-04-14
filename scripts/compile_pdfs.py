#!/usr/bin/env python3
"""
Step 3 — Run this after OpenCode has finished tailoring.
Finds every resume.tex in /output/ and compiles it to a PDF.

Usage (from repo root):
  python scripts/compile_pdfs.py
  python scripts/compile_pdfs.py --skip-existing   # Only compile new ones
"""

import os
import subprocess
import shutil
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"


def check_pdflatex():
    if not shutil.which("pdflatex"):
        print("❌ pdflatex not found. Install it first:")
        print("   macOS:   brew install --cask mactex-no-gui")
        print("   Ubuntu:  sudo apt install texlive-latex-recommended texlive-fonts-recommended")
        print("   Windows: https://miktex.org/download")
        return False
    return True


def compile_tex(tex_path: str) -> bool:
    tex_dir  = os.path.dirname(os.path.abspath(tex_path))
    tex_file = os.path.basename(tex_path)

    cmd = ["pdflatex", "-interaction=nonstopmode", "-output-directory", tex_dir, tex_file]

    for _ in range(2):  # Run twice to resolve refs
        result = subprocess.run(cmd, cwd=tex_dir, capture_output=True, text=True)

    # Clean aux files
    for ext in [".aux", ".log", ".out", ".toc"]:
        aux = os.path.join(tex_dir, tex_file.replace(".tex", ext))
        if os.path.exists(aux):
            os.remove(aux)

    pdf_path = os.path.join(tex_dir, tex_file.replace(".tex", ".pdf"))
    return os.path.exists(pdf_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-existing", action="store_true", help="Skip if PDF already exists")
    args = parser.parse_args()

    if not check_pdflatex():
        return

    # Find all resume.tex files
    tex_files = []
    for root, _, files in os.walk(str(OUTPUT_DIR)):
        for f in files:
            if f == "resume.tex":
                tex_files.append(os.path.join(root, f))

    if not tex_files:
        print(f"No resume.tex files found in {OUTPUT_DIR.relative_to(REPO_ROOT)}/")
        print("Run opencode first to generate tailored resumes.")
        return

    print(f"Found {len(tex_files)} resume.tex files\n")

    success = 0
    skipped = 0
    failed  = 0

    for i, tex_path in enumerate(tex_files, 1):
        pdf_path = tex_path.replace(".tex", ".pdf")
        label    = os.path.dirname(tex_path).replace(str(OUTPUT_DIR) + os.sep, "")

        if args.skip_existing and os.path.exists(pdf_path):
            print(f"[{i:>3}/{len(tex_files)}] ⏭  {label}")
            skipped += 1
            continue

        print(f"[{i:>3}/{len(tex_files)}] 🔄  {label}")
        ok = compile_tex(tex_path)
        if ok:
            print(f"            ✅ PDF saved")
            success += 1
        else:
            print(f"            ❌ Compilation failed — check {tex_path}")
            failed += 1

    print(f"\n{'─'*50}")
    print(f"Done.  ✅ {success}  ⏭ {skipped}  ❌ {failed}")


if __name__ == "__main__":
    main()