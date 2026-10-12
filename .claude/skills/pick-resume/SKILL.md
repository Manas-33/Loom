---
name: pick-resume
description: Route a job description to the right bucket resume (ai-agents, mle, mobile, generalist), suggest at most a few optional evidence-backed tweaks, and produce a verified one-page PDF for that application. Use when the user gives a JD file from jobs/, pastes a job description, or asks which resume to send for a role.
---

# pick-resume

Pick the right pre-built resume for one job posting and optionally sharpen it slightly. Speed and consistency beat cleverness: the default outcome is "send the bucket resume as-is."

## Path anchoring (read first)

Every path in this skill is relative to the LOOM REPO ROOT: the directory containing `cv.md`, `buckets/`, `jobs/`, and `output/` (normally `/Users/dalvi/Documents/loom`). The shell's current working directory drifts (into `output/<slug>/`, the skill folder, etc.) — NEVER resolve these paths against the cwd or the skill's base directory. If a referenced file seems missing, you are in the wrong directory: locate the repo root first (`ls` for cv.md), do not improvise or reconstruct file contents from other sources.

## Inputs

A job description: a path like `jobs/<Company>_<Role>.md`, or pasted JD text. If given a company/role name with no file, look for a matching file in `jobs/`; if none, ask the user to paste the JD (never fetch job-posting URLs).

## Step 1 — Route to a bucket

Read the ENTIRE job file — about-the-company prose, team/product description, responsibilities, requirements, everything. The routing question is not "what does the requirements list say" but "who will read this resume and what do they value." Weight the signals accordingly:

- The title is marketing; weight it least.
- The requirements list matters, but at specialist companies it is often boilerplate copied from a template (the FlexAI lesson: a pure-play inference company listed generic SWE requirements — APIs, web apps, Python/Go — with zero mention of models; the readers were still inference engineers). Requirements only dominate when they're specific.
- Identify the two qualification tiers SEMANTICALLY, not by header names: the preferred tier appears as "Preferred Qualifications" but equally as "nice to have", "bonus", "is a plus", "ideally", "you'll stand out if", or a hedge inside a required line ("one internship, ideally in infrastructure"). Whatever it's called, that tier is the real signal for routing and coverage: minimums are the floor everyone in the pool meets; the preferred tier is what screeners rank with, and usually the least-boilerplate description of what the team actually does.
- The company/team/product description often carries the strongest signal of who the readers are; a JD's responsibilities and about-sections routinely reveal the real domain that the requirements list hides.

| Requirements emphasize | Bucket |
|---|---|
| agents, RAG, LLM apps, copilots, prompt/context engineering, applied AI | `buckets/ai-agents/` |
| model training/evaluation/serving, inference, ML infra, PyTorch, quant research-adjacent ML | `buckets/mle/` |
| Flutter, mobile, iOS/Android (cross-platform acceptable) | `buckets/mobile/` |
| everything else: generic SWE, backend, full-stack, quant SWE, SRE/production | `buckets/generalist/` |

**Company domain check (mandatory, learned from a FlexAI routing miss):** requirements text alone is not enough — a domain company's engineers read resumes through their domain lens even when their JD is generic. Before routing, determine what the company actually builds: use the job file's About/Company Intro section, and if the company is unfamiliar and WebSearch is available, run one search (`what does <company> build`). Then:
- Generic-SWE requirements at a **compute/inference/ML-infra company** (GPU clouds, serving platforms, training infra) → `mle` (BGSD + Orbit is the page their engineers rate highest), not generalist.
- Generic-SWE requirements at an **agents/LLM-product company** → `ai-agents`.
- Generic-SWE requirements at a **consumer mobile-first company** → consider `mobile`.
- When domain and requirements genuinely conflict, say so in one line and let the user pick; when the company is a true generalist shop, requirements rule as before.

Edge rules:
- Native-mobile JDs that REQUIRE Swift/Kotlin: warn the user this bucket is Flutter-only; they decide whether to apply at all.
- Hybrid JDs (e.g. agent platform + inference): route by whichever half dominates the requirements list; if genuinely 50/50, state both options in one line and let the user pick.
- Quant-shop SWE (Citadel/HRT/Optiver style) → generalist, not mle, unless the posting is explicitly an ML role.

Report the chosen bucket and the 1-2 requirement lines that decided it. Keep this short.

## Step 2 — Gap analysis (read the actual files, don't recall)

Read the chosen `buckets/<name>/Manas_Dalvi_Resume.tex`. Extract every notable keyword from the JD — languages, frameworks, tools, techniques, and recurring requirement phrases (a term the JD repeats matters more than one it mentions once). Report them as three bulleted groups, every keyword accounted for:

**Present keywords** — already on the resume (skills line or bullet text). Plain bullet list, no elaboration.

**Missing keywords** — absent from this resume but evidenced in `cv.md`; note the evidence in-line (e.g. "fine-tuning — Premier League bullet"). These are the tweak candidates for Step 3.

**Not claimable keywords** — no evidence anywhere. NEVER add these; list them so the user knows what the JD wants that they can't claim, and optionally note when one is a "weekend project away" (an unbacked skill is an interview trap; this was the old auto-pipeline's failure mode of lifting JD keywords). Do NOT flag vLLM/SGLang/Ollama as unbacked for this user; they are real, defensible experience.

Don't pad any group with generic filler the JD doesn't actually weight (e.g. "communication skills", "Bachelor's degree").

Tag each keyword's tier (min/pref) using the semantic reading from Step 1 (a "plus"/"ideally"/"bonus" phrasing counts as preferred), and add one honest summary line: roughly how much of the PREFERRED list the resume covers — that fraction, not the minimums, predicts screen odds. If preferred coverage is thin even after tweaks, say so plainly: the user should weight that posting lower or lean on a referral rather than expecting the resume to carry it.

## Step 3 — Suggest at most 3 tweaks, then wait

Bias to zero. Only suggest a tweak when it plausibly changes the screen outcome:
- Reorder or add a skills-line item (evidenced only).
- Swap one bullet for a cv.md pool bullet that matches the JD better.
- Swap one project (only for strong-fit cases, e.g. Reenact→BGSD for an eval-infra role).
- On the mle bucket: applied-ML JDs (product/media ML, recommendations, no infra language) → consider swapping Orbit → Moment; ML-infra/inference/platform JDs → keep Orbit, it's the strongest resonance on the page.

Present each as a one-line diff ("add X to skills", "swap bullet A for B"). The user chooses; do not apply anything before they answer. "Send as-is" is a first-class answer and should be recommended explicitly when the gaps are minor.

## Step 4 — Build the deliverable

Never modify `buckets/` masters here (bucket edits happen only when the user asks for them outside this flow).

1. `mkdir -p "output/<job-md-basename>/"` and copy the chosen `Manas_Dalvi_Resume.tex` there.
2. Apply only the tweaks the user approved.
3. Compile straight to the branded name: `pdflatex -interaction=nonstopmode Manas_Dalvi_Resume.tex`, then delete the `.aux .out .log` files. Source and PDF are both named Manas_Dalvi_Resume; the deliverable is always `Manas_Dalvi_Resume.pdf` — recruiters see this filename in their downloads; never ship a `resume.pdf`.
4. Verify with pypdf: exactly 1 page; if a tweak caused a wrap/overflow, shorten the tweak (never other content) until it fits.
5. If any bullet was changed, verify every bullet's opening verb is still unique on the page.
6. Send the PDF to the user (SendUserFile) with one line naming the bucket and applied tweaks.

If the user approved zero tweaks, send the existing `buckets/<name>/Manas_Dalvi_Resume.pdf` directly — no copy or recompile needed.

## Step 5 — Boost the odds (after the deliverable, one short section)

The resume is the smaller half; end every run with 3-5 concrete actions for THIS company, not generic advice:

1. **Sponsorship check first** — if WebSearch is available, run one search like `"<company>" H-1B sponsorship new grad` (h1bdata/myvisajobs signals count). If the company doesn't sponsor, say so plainly so the user can deprioritize before investing more; this filter kills more applications than any resume issue.
2. **Company process intel** — one more search if warranted: `"<company>" new grad software engineer hiring process <year>` for quirks worth knowing (OA-first pipelines, resume-book deadlines, team-matching, whether cold applications even get read). Never fetch the job posting URL itself.
3. **Referral path** — name the user's best angles for this company: USC alumni (strongest lever), VIT alumni, GSoC/Liquid Galaxy network, hackathon contacts (Claude/DeepMind hackathon circles). Suggest the specific LinkedIn search (e.g. "University of Southern California" + <company>) and asking for the referral BEFORE or same-day as applying, since many referral systems ignore already-applied candidates.
4. **Recruiter/hiring-manager outreach** — suggest only when it plausibly helps (startups and mid-size: yes; Google-scale: skip). A good note is 3 sentences: one specific hook from their JD, one proof line with a number from the resume ("agent in production at 1,500+ jobs/week"), one ask. Draft it on request; never send anything on the user's behalf.
5. **Timing** — if the posting's age is knowable, say whether this is early (apply now, high value) or late (apply anyway, expect noise).

Cap this section at one short screen. Skip any item with nothing specific to say.

## Memory discipline

Never write memories from a run: not the chosen bucket, not approved tweaks, not "default" tweak sets for a kind of JD. A run's choices are per-JD, and saving them biases every later run. If a run exposes a genuine gap in the routing or tweak rules, propose an edit to this SKILL.md and let the user approve it; the skill is the only place routing policy lives.

## Invariants (from the resume rules; never violate)

- One page, verified by compiling — never trust it, always check.
- Skills and bullets claim only what cv.md evidences. No JD keyword lifting.
- No em dashes; one idea per bullet; terse. First bullet of an entry stays legible to a non-engineer.
- Unique opening verb per bullet per page.
- Header: manasman@usc.edu, manasdalvi.dev. Awards line stays last under Technical Skills.
- Metrics only where the number is a win (the Moment lesson); capability bullets don't get padded with weak numbers.

## Memory

Never save a run's outcome to memory: the bucket picked, the tweaks approved, or a "default" tweak set for a kind of JD. Each run routes and suggests tweaks from its JD and this file alone, so one application's choice (often just an accepted recommendation) can't tilt the next. If a run exposes a real gap in these rules, propose an edit to this file and let the user approve it instead.

## Reminders to surface with the result (one line each, max)

- Apply same-day; timing beats wording.
- On Workday: correct the autofilled fields (its parser swallows Projects into the last dated job).
