#!/usr/bin/env python3
"""
Build and check one job's tailored resume in output/<slug>/. This is the only
command a tailoring session (pick-resume-auto) is allowed to run.

  python scripts/tailor_build.py <slug> start <bucket>   # copy the bucket resume as-is
  python scripts/tailor_build.py <slug> build            # compile the edited .tex and check it

start keeps any resume already in output/<slug>/ in output/<slug>/previous/,
then copies buckets/<bucket>/Manas_Dalvi_Resume.tex and .pdf there, and saves them
as base.tex / base.pdf so later builds can show what changed.

build compiles Manas_Dalvi_Resume.tex and checks the pick-resume invariants:
one page, no em dashes, a unique opening verb per bullet, no text past the page
bottom. It also warns about new wrapped lines (TeX can squeeze them onto the
page) and banned words in changed lines, and draws preview.png with changed
lines highlighted. The result is printed as JSON and saved to build.json; the
exit code is 0 only when every check passes.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
BUCKETS_DIR = REPO_ROOT / "buckets"
BUCKETS = ("ai-agents", "mle", "mobile", "generalist")
NAME = "Manas_Dalvi_Resume"
PAGE_BOTTOM = 770.4  # points from the top of the page; the template's 0.30in margin
# The owner's banned resume vocabulary (resume-bullet-style); checked only in changed lines
BANNED = re.compile(r"\b(architected|engineered|orchestrated|enhanced|streamlining|ensuring|"
                    r"actionable insights|cross-functional teams)\b", re.I)
_SLUG = re.compile(r"[\w-]{1,100}")  # add_job.make_slug: word characters and hyphens


class BuildError(ValueError):
    pass


def job_dir(slug: str) -> Path:
    if not _SLUG.fullmatch(slug) or ".." in slug:
        raise BuildError(f"not a job slug: {slug!r}")
    if not (REPO_ROOT / "jobs" / f"{slug}.md").is_file():
        raise BuildError(f"no job file jobs/{slug}.md")
    return OUTPUT_DIR / slug


def start(slug: str, bucket: str) -> dict:
    if bucket not in BUCKETS:
        raise BuildError(f"bucket must be one of {', '.join(BUCKETS)}")
    out = job_dir(slug)
    out.mkdir(parents=True, exist_ok=True)
    old = [out / f"{NAME}.{ext}" for ext in ("tex", "pdf")]
    if any(p.exists() for p in old) and not (out / "base.tex").exists():  # a resume from before tailoring
        (out / "previous").mkdir(exist_ok=True)
        for p in old:
            if p.exists():
                shutil.copy2(p, out / "previous" / p.name)
    for ext in ("tex", "pdf"):
        shutil.copy2(BUCKETS_DIR / bucket / f"{NAME}.{ext}", out / f"{NAME}.{ext}")
    shutil.copy2(BUCKETS_DIR / bucket / f"{NAME}.tex", out / "base.tex")
    shutil.copy2(BUCKETS_DIR / bucket / f"{NAME}.pdf", out / "base.pdf")
    (out / "build.json").unlink(missing_ok=True)
    _preview(out / f"{NAME}.pdf", [], out / "preview.png")
    return {"ok": True, "bucket": bucket, "note": "bucket resume copied as-is"}


# ── Checks ───────────────────────────────────────────────────────────

def _bullets(tex: str) -> list[str]:
    body = "\n".join(line for line in tex.splitlines() if not line.lstrip().startswith("%"))
    return re.findall(r"\\resumeItem\{(.*?)\}\s*$", body, flags=re.M)


def _opening_verb(bullet: str) -> str:
    word = re.sub(r"\\[a-zA-Z]+\{|[{}\\]", "", bullet).split()
    return word[0].lower() if word else ""


def _pdf_lines(pdf: Path) -> tuple[int, list[tuple[str, tuple[float, float, float, float]]], dict[str, float]]:
    """(pages, [(text, bbox)], {section header: y}) from the PDF."""
    import fitz
    doc = fitz.open(pdf)
    lines, headers = [], {}
    for block in doc[0].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = " ".join("".join(span["text"] for span in line["spans"]).split())
            if text:
                lines.append((text, tuple(line["bbox"])))
                if text in ("Education", "Experience", "Projects", "Technical Skills"):
                    headers[text] = line["bbox"][1]
    pages = doc.page_count
    doc.close()
    return pages, lines, headers


def _preview(pdf: Path, changed: list[tuple[float, float, float, float]], dest: Path) -> None:
    import fitz
    doc = fitz.open(pdf)
    page = doc[0]
    for x0, y0, x1, y1 in changed:
        page.draw_rect(fitz.Rect(x0 - 2, y0 - 1, x1 + 2, y1 + 1), color=None, fill=(1, 0.86, 0.3), fill_opacity=0.35, overlay=True)
    page.get_pixmap(dpi=110).save(dest)
    doc.close()


def build(slug: str) -> dict:
    out = job_dir(slug)
    tex_file, base_tex = out / f"{NAME}.tex", out / "base.tex"
    if not tex_file.exists() or not base_tex.exists():
        raise BuildError("run `start <bucket>` first")
    proc = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{NAME}.tex"],
                          cwd=out, capture_output=True, text=True, timeout=120)
    log_tail = "\n".join((proc.stdout or "").splitlines()[-15:])
    for ext in ("aux", "out", "log"):
        (out / f"{NAME}.{ext}").unlink(missing_ok=True)
    result: dict = {"ok": False, "built": datetime.now().isoformat(timespec="seconds"), "checks": {}, "warnings": []}
    if proc.returncode != 0 or not (out / f"{NAME}.pdf").exists():
        result["error"] = "LaTeX didn't compile:\n" + log_tail
        return _save(out, result)

    tex = tex_file.read_text(encoding="utf-8")
    base = base_tex.read_text(encoding="utf-8")
    pages, lines, headers = _pdf_lines(out / f"{NAME}.pdf")
    checks = result["checks"]
    checks["one page"] = pages == 1
    checks["nothing past the page bottom"] = all(bbox[3] <= PAGE_BOTTOM + 0.5 for _, bbox in lines)
    tex_body = "\n".join(line for line in tex.splitlines() if not line.lstrip().startswith("%"))
    checks["no em dashes"] = "---" not in tex_body and "—" not in tex_body and not any("—" in t for t, _ in lines)
    verbs = [_opening_verb(b) for b in _bullets(tex)]
    repeats = sorted({v for v in verbs if v and verbs.count(v) > 1})
    checks["unique opening verbs"] = not repeats
    if repeats:
        result["repeated_verbs"] = repeats

    # What changed, compared with the bucket resume
    base_pdf = out / "base.pdf"
    base_lines, base_headers = [], {}
    if base_pdf.exists():
        _, base_lines, base_headers = _pdf_lines(base_pdf)
    base_texts = {t for t, _ in base_lines}
    changed = [(t, bbox) for t, bbox in lines if t not in base_texts]
    result["changed_lines"] = [t for t, _ in changed]
    if base_lines and len(lines) > len(base_lines):
        result["warnings"].append(f"{len(lines) - len(base_lines)} more line(s) than the bucket resume: "
                                  "a tweak wrapped, and TeX may have squeezed the spacing to fit")
    moved = {h: round(y - base_headers[h], 1) for h, y in headers.items() if h in base_headers and abs(y - base_headers[h]) > 1}
    if moved:
        result["warnings"].append("section headings moved (points): " + ", ".join(f"{h} {d:+}" for h, d in moved.items()))
    base_bullets = set(_bullets(base))
    for bullet in _bullets(tex):
        if bullet not in base_bullets and BANNED.search(bullet):
            result["warnings"].append(f"banned word in a changed bullet: {BANNED.search(bullet).group()}")
    _preview(out / f"{NAME}.pdf", [bbox for _, bbox in changed], out / "preview.png")
    result["ok"] = all(checks.values())
    return _save(out, result)


def _save(out: Path, result: dict) -> dict:
    (out / "build.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    args = sys.argv[1:]
    try:
        if len(args) == 3 and args[1] == "start":
            result = start(args[0], args[2])
        elif len(args) == 2 and args[1] == "build":
            result = build(args[0])
        else:
            print(__doc__.strip().split("\n\n")[1])
            return 2
    except BuildError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
