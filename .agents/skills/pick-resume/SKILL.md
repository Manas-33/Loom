---
name: pick-resume
description: Route a job description to the right bucket resume (ai-agents, mle, mobile, or generalist), suggest a few optional evidence-backed tweaks, and produce a verified one-page PDF. Use when the user provides a JD from jobs/, pastes a job description, or asks which resume to send for a role.
---

# Pick Resume

Pick the right prebuilt resume for one job posting and optionally sharpen it slightly. Speed and consistency matter more than novelty: default to sending the bucket resume as-is. The user's explicit instructions take precedence over this workflow.

## Anchor paths to the repository root

Resolve every path below relative to the Loom repository root: the directory containing `cv.md`, `buckets/`, `jobs/`, and `output/` (normally `/Users/dalvi/Documents/loom`). The shell working directory may drift into an output directory or this skill folder. If a referenced file appears missing, locate the repository root first; do not reconstruct content from another source.

## Input

Accept a job description as either a file such as `jobs/<Company>_<Role>.md` or pasted text. If the user supplies only a company and role, look for a matching file in `jobs/`. If no matching file exists, ask the user to paste the JD. Do not fetch a job-posting URL.

## 1. Route to a bucket

Read the entire job description, including company, team, product, responsibilities, minimum qualifications, and preferred qualifications. Route based on who will evaluate the resume and what they value:

- Weight the title least; titles are often marketing.
- Treat generic requirements as possible boilerplate, especially at specialist companies.
- Identify minimum and preferred qualification tiers semantically. Preferred signals may appear as "nice to have," "bonus," "is a plus," "ideally," "you'll stand out if," or hedging inside a required line. Preferred qualifications usually reveal what screeners rank most heavily.
- Give strong weight to company, team, product, and responsibility language when it reveals the real domain.

| Dominant signal | Bucket |
|---|---|
| Agents, RAG, LLM apps, copilots, prompt/context engineering, applied AI | `buckets/ai-agents/` |
| Model training, evaluation, serving, inference, ML infrastructure, PyTorch, or quant-research-adjacent ML | `buckets/mle/` |
| Flutter, mobile, iOS, or Android, where cross-platform experience is acceptable | `buckets/mobile/` |
| Generic SWE, backend, full-stack, quant SWE, SRE, production, or anything else | `buckets/generalist/` |

### Company-domain check

Requirements alone are insufficient when a company's domain determines how its engineers read resumes. Determine what the company builds from the JD's About or Company section. If the company is unfamiliar and web search is available, run one search for `what does <company> build`.

- Generic SWE at a compute, inference, or ML-infrastructure company (GPU cloud, serving platform, training infrastructure) routes to `mle`; BGSD and Orbit are likely to resonate more than the generalist page.
- Generic SWE at an agent or LLM-product company routes to `ai-agents`.
- Generic SWE at a consumer mobile-first company may route to `mobile`.
- If domain and requirements genuinely conflict, explain the conflict in one line and let the user choose. At a true generalist company, let the requirements dominate.

Apply these edge rules:

- If a native-mobile JD requires Swift or Kotlin, warn that the mobile bucket is Flutter-only and let the user decide whether to apply.
- For a hybrid JD such as agent platform plus inference, route by the dominant requirements. If it is genuinely balanced, state both options in one line and let the user choose.
- Quant-shop SWE routes to `generalist` unless the posting is explicitly an ML role.

Report the chosen bucket and the one or two requirement lines that determined it. Keep this brief.

## 2. Analyze gaps from the files

Read the selected `buckets/<name>/Manas_Dalvi_Resume.tex` and `cv.md`; do not rely on memory. Extract the JD's notable languages, frameworks, tools, techniques, and recurring requirement phrases. Repetition increases importance.

Account for each notable keyword in exactly one of these groups:

- **Present keywords:** already in the selected resume's skills or bullets. List without elaboration.
- **Missing keywords:** absent from this resume but supported by `cv.md`. Note the evidence inline, for example `fine-tuning (Premier League bullet)`. These are candidates for the next step.
- **Not claimable keywords:** unsupported anywhere. Never add these. Optionally note when one is realistically a small project away. Do not classify vLLM, SGLang, or Ollama as unsupported for this user; the experience is real and defensible.

Do not pad the groups with generic requirements the JD does not weight, such as communication skills or a bachelor's degree.

Tag each keyword as minimum or preferred based on the semantic tiers from the routing step. Add one candid line estimating how much of the preferred list the resume covers. If coverage remains thin after plausible tweaks, say that the user should weight the posting lower or lean on a referral.

## 3. Suggest up to three tweaks, then wait

Bias toward zero changes. Suggest a tweak only when it could plausibly change the screening outcome. Allowed changes are:

- Reorder or add an evidenced skills-line item.
- Replace one bullet with a better matching bullet from `cv.md`.
- Replace one project for a strong fit, such as Reenact with BGSD for evaluation infrastructure.
- For the `mle` bucket, consider Orbit to Moment for applied product or media ML without infrastructure language. Keep Orbit for ML infrastructure, inference, or platform roles.

Present each suggestion as a one-line diff, such as `add X to skills` or `swap bullet A for B`. Recommend `send as-is` explicitly when gaps are minor. Do not edit or build until the user chooses.

## 4. Build the deliverable

Never modify a master under `buckets/` in this workflow. Bucket masters change only when the user separately requests that work.

When the user approves one or more tweaks:

1. Create `output/<job-md-basename>/` and copy the selected `Manas_Dalvi_Resume.tex` into it.
2. Apply only the approved tweaks to the copy.
3. From that output directory, run `pdflatex -interaction=nonstopmode Manas_Dalvi_Resume.tex`, then remove only the generated `.aux`, `.out`, and `.log` files.
4. Verify with `pypdf` that the PDF has exactly one page. If an approved tweak caused wrapping or overflow, shorten that tweak without changing unrelated content and rebuild.
5. If any bullet changed, verify that every bullet's opening verb remains unique on the page.
6. Give the user a clickable link to `Manas_Dalvi_Resume.pdf` and one line naming the bucket and applied tweaks.

The source and PDF must both remain named `Manas_Dalvi_Resume`; never ship `resume.pdf`.

If the user approves zero tweaks, link the existing `buckets/<name>/Manas_Dalvi_Resume.pdf` directly without copying or recompiling it.

## 5. Boost the odds

After delivering the resume, provide three to five short, company-specific actions. Skip anything for which there is no specific advice.

1. **Sponsorship:** If web search is available, search `"<company>" H-1B sponsorship new grad`. Treat H1BData or MyVisaJobs as useful signals. If sponsorship appears unavailable, say so plainly.
2. **Hiring process:** When useful, search `"<company>" new grad software engineer hiring process <year>` for details such as OA-first pipelines, resume-book deadlines, team matching, or whether cold applications are reviewed. Do not fetch the job-posting URL.
3. **Referral path:** Suggest the best specific angle: USC alumni first, then VIT alumni, GSoC or Liquid Galaxy connections, or hackathon contacts. Include a concrete LinkedIn search and recommend asking before or on the same day as applying because some systems ignore post-application referrals.
4. **Outreach:** Recommend recruiter or hiring-manager outreach when it could help, usually at startups and mid-size companies rather than Google-scale employers. Offer to draft a three-sentence note using one JD-specific hook, one numeric proof line from the resume, and one ask. Never send it for the user.
5. **Timing:** If posting age is known, state whether the application is early or late.

Keep this section to one short screen.

## Invariants

- Keep the resume to one compiled and verified page.
- Claim only skills and experience supported by `cv.md`; never lift unsupported JD keywords.
- Use no em dashes, keep one idea per bullet, and stay terse. The first bullet of an entry must remain legible to a non-engineer.
- Keep opening verbs unique across bullets on the page.
- Preserve `manasman@usc.edu`, `manasdalvi.dev`, and the Awards line as the final item under Technical Skills.
- Use metrics only when the number strengthens the claim; do not pad capability bullets with weak numbers.

## State discipline

Do not save a run's bucket, approved tweaks, or default tweak set to memory. Each application must be evaluated from its JD, `cv.md`, and this skill. If a run exposes a genuine gap in these rules, propose an edit to this `SKILL.md` and let the user approve it.

End with at most these two reminders when relevant:

- Apply the same day; timing beats wording.
- On Workday, correct autofilled fields because its parser may place Projects under the last dated job.
