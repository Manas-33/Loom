#!/usr/bin/env python3
"""
Coverage score for a tailored resume: how much of what the posting asks for
the resume covers, as the bucket resume stands and after the owner's tweaks.

No model runs here. The tailoring session (pick-resume-auto) lists the
posting's keywords once: on the resume (with the resume text that covers
each), missing but backed by cv.md, and not claimable. baseline() freezes that
list after checking every quoted text really is in the bucket resume. score()
then recounts against the resume file as it is now:

  as_is  the bucket resume before any tweak
  now    after the applied tweaks (a tweak can also lose a keyword, when it
         replaces the line that covered one)
  max    if every keyword the owner can honestly claim were on the page

Preferred qualifications count double, since pick-resume treats preferred
coverage as what predicts getting through the screen.
"""

from __future__ import annotations

import re
from datetime import datetime

WEIGHTS = {"min": 1, "pref": 2}
CLAIMABLE = ("present", "unverified", "can add")


def plain(text: str) -> str:
    """Resume text without LaTeX markup, comments or case, so a quote matches however it was copied."""
    lines = [line for line in str(text or "").splitlines() if not line.lstrip().startswith("%")]
    out = "\n".join(lines)
    out = re.sub(r"\\([&%_#$])", r"\1", out)       # \& → &
    out = re.sub(r"\\[a-zA-Z]+\*?", " ", out)       # \textbf{x} → {x}
    out = re.sub(r"[{}$]", "", out).replace("~", " ")
    return re.sub(r"\s+", " ", out).strip().casefold()


def has(body: str, quote: str) -> bool:
    """True when the quote appears in the (already plain) resume text as whole words."""
    q = plain(quote)
    if not q:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(q) + r"(?![a-z0-9])", body) is not None


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.]+", plain(text))


def survives(quote: str, text: str, slack: int = 3) -> bool:
    """True when the quote's words still appear in order in the text, with at most `slack` words inserted
    between them. A tweak that adds "Java" to "Python, TypeScript, Go, SQL" keeps the line's other keywords."""
    q, words = _words(quote), _words(text)
    if not q:
        return False
    for start in (i for i, w in enumerate(words) if w == q[0]):
        matched, extra = 1, 0
        for w in words[start + 1:]:
            if matched == len(q):
                break
            if w == q[matched]:
                matched += 1
            else:
                extra += 1
                if extra > slack:
                    break
        if matched == len(q):
            return True
    return False


def still_covered(keyword: str, quote: str, body: str, lines: list[str], tweaks: list[dict] = ()) -> bool:
    """A keyword whose quoted text changed since the first check: still covered if the text survives with
    small insertions, if an applied tweak rewrote it and the new text still names the keyword ("Natural
    Language Processing" → "NLP"), or if the resume line that best matches the old quote still names it."""
    if quote and survives(quote, body):
        return True
    q_plain = plain(quote)
    if q_plain and any(q_plain in plain(t.get("before")) and has(plain(t.get("after")), keyword)
                       and has(body, t.get("after")) for t in tweaks):
        return True
    q = set(_words(quote))
    if not q:
        return False
    best, line = 0.0, ""
    for candidate in lines:
        overlap = len(q & set(re.findall(r"[a-z0-9+#.]+", candidate))) / len(q)
        if overlap > best:
            best, line = overlap, candidate
    return best >= 0.6 and has(line, keyword)


def _key(keyword) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", str(keyword or "").casefold()).strip()


def baseline(result: dict, as_is_tex: str) -> dict | None:
    """The frozen keyword list for one job, from the session's first gap analysis. None when the
    result is in the old format (present keywords as plain strings) or names no keywords."""
    keywords = (result or {}).get("keywords") or {}
    present = keywords.get("present") or []
    if any(not isinstance(item, dict) for item in present):
        return None
    body = plain(as_is_tex)
    rows, seen = [], set()

    def add(item: dict, status: str) -> None:
        key = _key(item.get("keyword"))
        if not key or key in seen:
            return
        seen.add(key)
        row = {"keyword": str(item["keyword"]).strip(), "status": status,
               "tier": item.get("tier") if item.get("tier") in WEIGHTS else "min"}
        if status in ("present", "unverified"):
            row["quote"] = str(item.get("quote") or "")
        rows.append(row)

    for item in present:
        add(item, "present" if has(body, item.get("quote")) else "unverified")
    for item in keywords.get("missing") or []:
        add(item, "can add")
    for item in keywords.get("not_claimable") or []:
        add(item, "cannot claim")
    if not rows:
        return None
    return {"keywords": rows, "frozen": datetime.now().isoformat(timespec="seconds")}


def score(base: dict | None, result: dict | None, tex: str, as_is_tex: str | None = None) -> dict | None:
    """Coverage of the frozen keyword list by the resume as it is now. None without a baseline.
    as_is_tex: the bucket resume before any tweak. A keyword the first check couldn't confirm but a later turn
    quotes from text that was already there counts as present all along, not as something a tweak added."""
    rows = (base or {}).get("keywords") or []
    total = sum(WEIGHTS[r["tier"]] for r in rows)
    if not total:
        return None
    result = result or {}
    body = plain(tex)
    lines = [p for p in (plain(line) for line in str(tex or "").splitlines()) if p]
    before = plain(as_is_tex) if as_is_tex else None
    tweaks = [t for t in result.get("tweaks") or [] if isinstance(t, dict)]
    applied = [t for t in tweaks if t.get("status") == "applied"]
    pending = [t for t in tweaks if t.get("status") == "pending"]
    latest = {_key(p.get("keyword")): p.get("quote") for p in (result.get("keywords") or {}).get("present") or []
              if isinstance(p, dict)}

    def covers(tweak: dict) -> set[str]:
        return {_key(c) for c in tweak.get("covers") or []}

    points = {"as_is": 0, "now": 0, "max": 0}
    tiers = {t: {"as_is": 0, "now": 0, "max": 0, "total": 0} for t in WEIGHTS}
    gained, lost, open_, cannot, unverified, vouched, covered_now = [], [], [], [], [], [], set()
    for row in rows:
        key, tier, weight = _key(row["keyword"]), row["tier"], WEIGHTS[row["tier"]]
        tiers[tier]["total"] += 1
        if row["status"] == "cannot claim":
            # Unless the owner vouched for it: a tweak they approved puts it on the page (e.g. after a comment)
            via = next((t.get("id") for t in applied if key in covers(t) and has(body, t.get("after"))), None)
            if via is None:
                cannot.append({"keyword": row["keyword"], "tier": tier})
                continue
            for name in ("now", "max"):
                points[name] += weight
                tiers[tier][name] += 1
            covered_now.add(key)
            vouched.append({"keyword": row["keyword"], "tier": tier, "tweak": via})
            continue
        as_is = row["status"] == "present" or bool(
            before is not None and row["status"] == "unverified" and latest.get(key) and has(before, latest[key]))
        quote = row.get("quote") or latest.get(key)
        now, via = as_is and (has(body, quote) or still_covered(row["keyword"], quote, body, lines, applied)), None
        if not now:
            for t in applied:
                if key in covers(t) and has(body, t.get("after")):
                    now, via = True, t.get("id")
                    break
        if not now and latest.get(key) and has(body, latest[key]):
            now = True
        for name, hit in (("as_is", as_is), ("now", now), ("max", True)):
            if hit:
                points[name] += weight
                tiers[tier][name] += 1
        item = {"keyword": row["keyword"], "tier": tier}
        if now:
            covered_now.add(key)
        if now and not as_is:
            gained.append({**item, "tweak": via})
        elif as_is and not now:
            quote = plain(row.get("quote"))
            blame = next((t.get("id") for t in applied if quote and quote in plain(t.get("before"))), None)
            lost.append({**item, "tweak": blame})
        elif not now:
            (unverified if row["status"] == "unverified" else open_).append(item)

    def pct(n: int) -> int:
        return round(100 * n / total)

    # What each pending tweak would do: the keywords it says it covers, minus any whose covering
    # text sits in the line it replaces
    kept = [(r, plain(r.get("quote"))) for r in rows if r["status"] == "present" and _key(r["keyword"]) in covered_now]
    would_add = {}
    for t in pending:
        keys, before, after = covers(t), plain(t.get("before")), plain(t.get("after"))
        # a pending tweak can carry a keyword the owner vouched for in a comment, so "cannot claim" counts here too
        gains = [r for r in rows if (r["status"] in CLAIMABLE or r["status"] == "cannot claim")
                 and _key(r["keyword"]) in keys and _key(r["keyword"]) not in covered_now]
        loses = [r for r, quote in kept if quote and quote in before and quote not in after
                 and not survives(quote, after) and not has(after, r["keyword"])]
        if gains or loses:
            net = sum(WEIGHTS[r["tier"]] for r in gains) - sum(WEIGHTS[r["tier"]] for r in loses)
            would_add[str(t.get("id"))] = {"points": pct(net), "keywords": [r["keyword"] for r in gains],
                                           "loses": [r["keyword"] for r in loses]}
    return {
        "as_is": pct(points["as_is"]), "now": pct(points["now"]), "max": pct(points["max"]),
        "tiers": tiers, "applied": len(applied),
        "gained": gained, "lost": lost, "open": open_, "cannot_claim": cannot, "unverified": unverified,
        "vouched": vouched,  # on the page on the owner's word; cv.md doesn't back it yet
        "would_add": would_add,
    }
