---
name: cover-letter
description: Draft a tailored cover letter for one job posting, show it for the user's review, then build the final cover_letter.docx via the existing JSON + build-script pipeline. Use when the user asks for a cover letter for a role, gives a JD and mentions a cover letter, or after /pick-resume when the posting requires one.
---

# cover-letter

Write one reviewed, evidence-backed cover letter per job. The user reads and approves the draft BEFORE anything is written to disk — no unreviewed artifact ever ships (same principle as the bucket resumes).

## Path anchoring (read first)

Every path in this skill is relative to the LOOM REPO ROOT: the directory containing `cv.md`, `buckets/`, `jobs/`, and `output/` (normally `/Users/dalvi/Documents/loom`). The shell's current working directory drifts (into `output/<slug>/`, the skill folder, etc.) — NEVER resolve these paths against the cwd or the skill's base directory. If a referenced file seems missing, you are in the wrong directory: locate the repo root first (`ls` for cv.md), do not improvise or reconstruct file contents from other sources.

## Inputs

Same as /pick-resume: a `jobs/<...>.md` path, a slug/company fragment to look up in `jobs/`, or pasted JD text (never fetch job-posting URLs). If /pick-resume already ran for this job in the conversation, reuse its JD analysis and chosen bucket.

## Authoritative style and structure rules

Read and follow `prompts/cover_letter_task.md` — it defines tone (peer-to-peer, no fluff, banned phrases, no em dashes, sentence-length limits), the 3-paragraph structure, and the evidence rules. Read `templates/cover_letter_template.md` for the JSON schema. Those two files are the source of truth; this skill only adds the workflow around them.

Additional rules layered on top:

- **Match the resume being sent.** The letter's paragraph-2 evidence must come from experiences/projects that appear on the bucket resume chosen for this job (run the /pick-resume routing step mentally if it hasn't run). A letter citing a project the attached resume doesn't show is incoherent.
- **Fill gaps, don't restate.** If /pick-resume ran, use its keyword-coverage report: the "missing" and "not claimable" lists are what the letter should address (transferable evidence, honest framing) — the "present" list is what the resume already carries and the letter should NOT repeat beyond one metric.
- **Evidence bar is the resume bar**: claims only from `cv.md`. A JD requirement with no evidence gets transferable-skill framing or silence, never a claim.
- **Numbers only where they're wins** (the Moment lesson applies to letters too).

## Workflow

1. Read the JD file, `cv.md`, and the two rule files above.
2. Pick the 1-2 strongest evidence matches for paragraph 2 (must-haves first, resume-consistent).
3. Draft the three paragraphs. Then, BEFORE showing anything, verify the draft line by line against the pre-review checklist below and fix every failure — never show a failing draft. Then show the paragraphs in chat as plain text (not JSON) with a one-line note on which evidence was chosen and why, and the line "checklist passed".
4. **Wait for the user.** They may approve, edit lines, or swap evidence. Iterate until approved. "Approve as-is" should be the common case if the draft is good.
5. On approval only:
   a. Write `output/<slug>/cover_letter.json` per the template schema (create the folder if needed; valid strict JSON, date as "Month Day, Year", real hiring-manager name only if the JD names one).
   b. Run `python scripts/build_cover_letters.py --skip-existing` from the repo root (it walks output/ and builds `cover_letter.docx` next to each JSON; --skip-existing keeps already-built letters untouched).
   c. Confirm `output/<slug>/cover_letter.docx` exists and send it to the user (SendUserFile).
6. If a `cover_letter.json` already exists for this slug, say so and ask before overwriting (and note --skip-existing would skip the rebuild; delete the old docx first or run the script without the flag for just this letter's rebuild).

## Pre-review checklist (verify the actual draft text, one item at a time)

Rules get read at the start of a run and drift by drafting time — this checklist exists because a session once read every rule and still shipped a draft violating them. Check each item against the literal draft text:

1. Does NOT open with "I"; opens with the role, company, or a concrete claim.
2. Zero banned phrases ("express my interest", "excited to apply", "aligns", "I hope to hear", "look forward to discussing"); zero em dashes; no sentence starts with Furthermore/Moreover/Additionally/Consequently.
3. Under 350 words, three paragraphs.
4. Count metrics repeated verbatim from the chosen resume: must be ≤1. Every other fact must add context the resume lacks.
5. The Step-2 coverage gaps (missing/not-claimable lists) are addressed with honest framing, or consciously skipped; nothing from the "present" list is restated.
6. Resonance: appears in exactly one paragraph, proven by a cv.md fact, no quoted slogans or values-listing; or absent entirely.
7. Paragraph 2: every sentence ≤20 words, each starting with the project name, the action, or the timeframe.

If any item fails, revise and re-check before showing the draft.

## Reminders to surface with the result

- Cover letters are read far less than resumes; spend minutes, not hours. If the posting doesn't require one, say so and let the user skip it.
- The letterhead (name, contact) is hardcoded in `scripts/build_cover_letters.py`; edit there if it ever changes.
- If the portal has a single upload slot, suggest merging resume + letter into one PDF (resume first).
