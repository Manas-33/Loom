---
name: app-answers
description: Headless answer drafting for the Loom dashboard. In a job's existing tailoring session (Claude or Codex), sorts each question on the job's real application form into facts from the owner's profile, written answers to draft, questions only the owner can answer, uploads and not-applicable follow-ups, and returns them as structured output for approval. Only scripts/tailor.py runs this.
---

# app-answers

You are continuing this job's tailoring session, without a person watching. The dashboard read the job's real application form and saved it to `output/<slug>/questions.json`. Return one entry per question in that file, using its `id`; nothing more.

## The rule that matters most

**Facts are never made up.** They come only from the `application:` section of `profile.local.yaml`. If the profile doesn't hold the fact (or holds `null`), the question goes to the owner as `you`. When in doubt between `fact` and `you`, pick `you`.

## Kinds

- **fact:** answerable from the profile. Set `profile_key` to the key that holds it (or `how_heard`, whose value the prompt gives for this job).
  - Text questions: leave `value` empty; the dashboard copies the profile value exactly.
  - Select, multiselect and yes/no questions: `value` is the option (copied exactly from `options`; for yes/no, `Yes` or `No`) that states the profile fact. Multiselect: separate options with ` | `. If no option says what the profile says, use `you`.
  - EEO (voluntary self-identification) questions: answer from `gender`, `race_ethnicity`, `hispanic_latino`, `veteran_status` and `disability_status`, picking the option that says the same thing ("No" disability → "No, I do not have a disability"; "Not a protected veteran" → "I am not a protected veteran"). Where the profile value declines, pick the option that declines ("Decline To Self Identify", "I don't wish to answer"). If no option matches, use `you`.
  - Work authorization and sponsorship come from `authorized_to_work_us`, `needs_sponsorship_now_or_future`, `visa_status` and `authorization_detail`.
- **written:** needs prose in the owner's voice ("Why do you want to work here?", "Tell us about a project"). Draft it in `value` (rules below).
- **you:** only the owner can answer. Always: past employment with the government, signatures, background-check authorizations, and any fact the profile doesn't hold. `value` stays empty; `reason` says what's needed in a few words.
- **upload:** file fields. The resume field gets the tailored resume (`reason`: "tailored resume").
- **Cover letter fields are written, not upload:** whenever the form has a cover letter field, required or optional, draft the letter (see "Cover letters").

Standing answers from the owner (2026-09-30; they review every form before submitting):
- Contact consent (texts, calls, emails about the application or jobs): `fact` from `communication_consent`. Terms, privacy and "I certify the information is accurate" acknowledgements: `fact` from `accept_terms_and_certify`.
- Street address, city, state, zip code and country, phone type: facts.
- Worked for this company before, know or are related to someone there, referred by someone: facts from `previously_employed_here`, `knows_someone_at_company`, `referred_by` (unless `cv.md` lists this company).
- Salary or pay expectations: `written`. The range the job file states, or a figure inside it; with no stated range, "Negotiable". Keep it to that one line.
- **skip:** a follow-up whose condition doesn't apply given the other answers ("If yes, when?" after a No), or an optional field that's better left empty. `reason` says why.

`reason` is one short line for every kind. `general` is true only for a written answer that isn't about this company and could be reused elsewhere ("Describe a project you're proud of").

## Written answers

Read `prompts/cover_letter_task.md` for tone (its Tone & Style and Company resonance sections; not its three-paragraph structure) and follow it. On top of that, in this owner's voice:

- No em dashes. Short, varied sentences, written the way a person talks about the work. No colon-then-fragment lists, no triads, no summary or callback sentences ("That's the kind of work I want to do"), no cleft openers ("What I like about X is that…"), no "instead of being Y" contrasts, no "a big part of the appeal", no aphorisms.
- Don't start with "I".
- "Why this company / role": about the company's problem and product, specific enough that it couldn't be pasted into another company's form. One concrete link to the owner's work at most, from `cv.md`. Not a rehash of resume bullets or metrics.
- "Tell us about a project / experience": one project, what the owner did and how, from `cv.md`, preferring what's on `output/<slug>/Manas_Dalvi_Resume.tex`. Numbers only where they're wins.
- Company facts only from the job file, or from at most 2 web searches if the job file says too little. Never invent a product, value or fact.
- Length: follow any limit in the question or its description. Otherwise about 80 to 150 words for "why" questions and 120 to 200 for project questions.
- The prompt may list answers the owner approved for other jobs. Reuse one only if it truly answers this question, adapt it to this company, and say so in `reason`.

Also read `.claude/skills/cover-letter/SKILL.md` (its "Additional rules" and "Pre-review checklist") and apply what fits a short answer.

### Before returning any written answer

Check the literal text, one item at a time, and rewrite until every item passes. Never return a draft that fails one; the dashboard also scans for these and flags them on the owner's card.

1. Doesn't open with "I".
2. No banned phrases: "express my interest", "excited to apply", "aligns", "passionate about", "I hope to hear", "look forward to discussing", "I am writing".
3. No em dashes, and no sentence starts with Furthermore, Moreover, Additionally, Consequently, Ultimately or Overall.
4. None of the owner's banned words: architected, engineered, orchestrated, enhanced, streamlining, ensuring, leveraged, actionable insights, cross-functional teams.
5. No trailing ", ensuring…", ", enabling…", ", driving…" clauses.
6. Short, varied sentences (most under 20 words), written like a person talking. No triads, no colon-then-list.
7. At most one number repeated from the resume.
8. No summary or callback closer, no cleft opener, no "instead of" contrast, no aphorism.

## Cover letters

Draft the letter as that question's answer: `kind` `written`, `general` false, `value` the three body paragraphs separated by one blank line. No date, address, salutation or sign-off; the file adds them.

Follow `prompts/cover_letter_task.md` in full here (tone, the three-paragraph structure and the evidence rules) and the cover-letter skill's "Additional rules" and "Pre-review checklist" (`.claude/skills/cover-letter/SKILL.md`). Its evidence comes from what's on the resume being sent, and claims only from `cv.md`. Pass that checklist and the one below before returning it. `reason` says whether the field is required. The owner approves it on the answers card, and approving it builds `cover_letter.docx` for the form.

## Later turns

A later prompt may ask you to rewrite specific answers with the owner's feedback. Change only those, keep the same kind unless the feedback says otherwise, and return every question again with the others exactly as they were.

## Output

`answers` (one entry per question: `id`, `kind`, `profile_key`, `value`, `reason`, `general`) and `message` (one or two sentences: how many need the owner, anything odd about the form).
