"""Batched quick screen: one model call over many listings, plain facts only.

This is the tier between the zero-cost ``score_title_fit`` rule and the
per-URL full score (``/slack-apply`` via ``jj.scoring``). The title rule used
to be a gate: anything under 50 was dropped before a prospect existed. Here it
becomes a ranking. New listings are sent to the model in batches of up to a
hundred, with only the facts the scanner stored (title, company, location,
pay, first-seen date) plus the person's profile documents, and the model
answers one of four words for each with a sentence of reasoning. Only
``fair`` and ``strong`` go on to the expensive full read.

Cost shape (from Pinloop's measured ratio, docs/comparison-pinloop-cli.md):
one batch of a hundred listings costs about as much as seven full scores.

Nothing here is a gate on the person's judgment: every verdict is stored in
``judgments`` with its reasoning and prompt version, ``jj judgments`` reads
and overrides them, and a person's verdict always outranks the model's.
"""

import json
import logging
import re
import shutil
import subprocess
from datetime import date
from typing import Any, Optional

from jj.prompts import (
    PROMPT_VERSION,
    VERDICTS,
    at_or_above,
    describe_missing_documents,
    drop_reason,
    load_profile_documents,
    load_quick_screen_prompt,
)

logger = logging.getLogger("jj.quick_screen")

DEFAULT_BATCH_SIZE = 50
MAX_BATCH_SIZE = 100
DEFAULT_MODEL = "haiku"
QUICK_SCREEN_TIMEOUT_SEC = 300
#: How many corpus roles and skills the profile excerpt carries.
CORPUS_ROLE_LIMIT = 8
CORPUS_SKILL_LIMIT = 40
#: Verdicts at or above this word create or upgrade a prospect.
DEFAULT_KEEP = "fair"


# ---------------------------------------------------------------------------
# Building the request
# ---------------------------------------------------------------------------


def listing_ref(index: int) -> str:
    """The short reference a listing carries in the request: L1, L2, ..."""
    return f"L{index + 1}"


def listing_facts(listing: dict[str, Any], ref: str) -> dict[str, Any]:
    """The plain facts one listing contributes to the request, and nothing else."""
    return {
        "ref": ref,
        "title": listing.get("title") or "",
        "company": listing.get("company_name") or listing.get("company") or "",
        "location": listing.get("location") or "",
        "pay": listing.get("salary") or "",
        "first_seen": (listing.get("first_seen_at") or listing.get("posted_at") or "")[:10],
    }


def corpus_excerpt() -> str:
    """A compact view of the person's roles and skills from the corpus DB.

    Empty string when the corpus is empty or unreadable, so a quick screen on
    a fresh install still runs and the report says what was missing.
    """
    try:
        from jj.db import get_roles, get_skills
        roles = get_roles()
        skills = get_skills()
    except Exception:  # noqa: BLE001 - any DB problem means "no excerpt"
        logger.debug("corpus excerpt unavailable", exc_info=True)
        return ""

    lines: list[str] = []
    if roles:
        lines.append("Roles (most recent first):")
        for r in roles[:CORPUS_ROLE_LIMIT]:
            span = f"{r.get('start_date') or '?'} to {r.get('end_date') or 'present'}"
            lines.append(f"- {r.get('title')} at {r.get('company')} ({span})")
            if r.get("summary"):
                lines.append(f"  {str(r['summary']).strip()[:240]}")
    if skills:
        names = [s.get("name") for s in skills if s.get("name")][:CORPUS_SKILL_LIMIT]
        if names:
            lines.append("")
            lines.append("Skills: " + ", ".join(names))
    return "\n".join(lines).strip()


def profile_summary() -> str:
    """The few profile.yaml facts a screen needs: location, authorization, remote preference."""
    try:
        from jj.config import load_profile
        profile = load_profile() or {}
    except Exception:  # noqa: BLE001
        return ""
    contact = profile.get("contact") or {}
    auth = profile.get("authorization") or {}
    defaults = profile.get("defaults") or {}
    exp = profile.get("experience") or {}
    parts = []
    if contact.get("location"):
        parts.append(f"Lives in {contact['location']}.")
    if exp.get("current_title"):
        parts.append(f"Current or most recent title: {exp['current_title']}.")
    if exp.get("years"):
        parts.append(f"About {exp['years']} years of experience.")
    if auth.get("status"):
        parts.append(f"Work authorization: {auth['status']}.")
    if auth.get("requires_sponsorship"):
        parts.append("Requires visa sponsorship.")
    if defaults.get("remote_preference"):
        parts.append(f"Remote preference: {defaults['remote_preference']}.")
    if defaults.get("willing_to_relocate") is False:
        parts.append("Not willing to relocate.")
    return " ".join(parts)


def build_documents() -> dict[str, Any]:
    """Every document the screen sends, labelled, plus what was missing."""
    docs = load_profile_documents()
    present: dict[str, str] = dict(docs["present"])
    missing: list[str] = list(docs["missing"])
    excerpt = corpus_excerpt()
    if excerpt:
        present["corpus"] = excerpt
    else:
        missing.append("corpus")
    summary = profile_summary()
    if summary:
        present["profile"] = summary
    return {"present": present, "missing": missing}


def build_request(
    listings: list[dict[str, Any]],
    documents: dict[str, Any],
    instructions: Optional[str] = None,
) -> tuple[str, list[str]]:
    """The full text sent to the model for one batch, and the refs it must answer for."""
    if instructions is None:
        instructions, _source = load_quick_screen_prompt()
    refs = [listing_ref(i) for i in range(len(listings))]
    facts = [listing_facts(listing, ref) for listing, ref in zip(listings, refs)]

    parts = [instructions.strip(), "", "## Postings", ""]
    for f in facts:
        line = f"{f['ref']}: {f['title']} | {f['company']} | {f['location'] or 'location not stated'}"
        if f["pay"]:
            line += f" | pay: {f['pay']}"
        if f["first_seen"]:
            line += f" | first seen {f['first_seen']}"
        parts.append(line)
    parts += ["", "## Answer for exactly these references", "", ", ".join(refs), "", "## Profile", ""]
    present = documents.get("present") or {}
    if not present:
        parts.append("(no profile documents are stored)")
    for name, text in present.items():
        parts += [f"### {name}", "", text.strip(), ""]
    return "\n".join(parts), refs


# ---------------------------------------------------------------------------
# Reading the answer
# ---------------------------------------------------------------------------

_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def parse_verdicts(text: str, expected_refs: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Read the model's JSON array. Returns (verdicts by ref, problems).

    Tolerates prose or code fences around the array. A row with an unknown ref,
    a missing ref, or a word outside the four is dropped and named in problems;
    an expected ref with no usable row is named too, so nothing goes missing
    quietly.
    """
    problems: list[str] = []
    verdicts: dict[str, dict[str, str]] = {}
    match = _JSON_ARRAY.search(text or "")
    if not match:
        return {}, ["no JSON array found in the model's answer"]
    try:
        rows = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return {}, [f"the model's answer was not valid JSON: {e}"]
    if not isinstance(rows, list):
        return {}, ["the model's answer was JSON but not a list"]

    expected = set(expected_refs)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"row {i + 1} was not an object")
            continue
        ref = str(row.get("ref") or "").strip()
        word = str(row.get("verdict") or "").strip().lower()
        if ref not in expected:
            problems.append(f"row {i + 1} named an unknown reference {ref!r}")
            continue
        if word not in VERDICTS:
            problems.append(f"{ref}: verdict {word!r} is not one of {', '.join(VERDICTS)}")
            continue
        verdicts[ref] = {"verdict": word, "reasoning": str(row.get("reasoning") or "").strip()}

    for ref in expected_refs:
        if ref not in verdicts:
            problems.append(f"{ref}: no verdict came back, so it could not be screened")
    return verdicts, problems


# ---------------------------------------------------------------------------
# Talking to the model
# ---------------------------------------------------------------------------


def run_claude(prompt: str, model: str, timeout: int = QUICK_SCREEN_TIMEOUT_SEC) -> tuple[int, str, str]:
    """One headless `claude -p` call with no tools. Returns (rc, stdout, stderr).

    rc=127 if the claude CLI is absent, 124 on timeout, matching jj.scoring.
    The prompt travels on stdin so a hundred-posting batch never hits the
    argument-length ceiling.
    """
    claude = shutil.which("claude")
    if not claude:
        return 127, "", "'claude' not found in PATH"
    # The positional prompt comes before --tools: that option is variadic and
    # would otherwise swallow the prompt as a tool name.
    cmd = [
        claude, "-p",
        "Follow the instructions in the input exactly and answer with the JSON array only.",
        "--model", model, "--output-format", "text", "--tools", "",
    ]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Timed out after {timeout}s"
    except OSError as e:
        return 1, "", str(e)


def _batches(items: list[Any], size: int) -> list[list[Any]]:
    size = max(1, min(int(size), MAX_BATCH_SIZE))
    return [items[i:i + size] for i in range(0, len(items), size)]


def _monitor_config_value(key: str, default: Any = None) -> Any:
    try:
        from jj.config import load_config
        return ((load_config() or {}).get("monitor", {}) or {}).get(key, default)
    except Exception:  # noqa: BLE001
        return default


def _config_value(key: str, default: Any) -> Any:
    try:
        from jj.config import load_config
        monitor = (load_config() or {}).get("monitor", {}) or {}
        quick = monitor.get("quick_screen", {}) or {}
        return quick.get(key, default)
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def quick_screen_listings(
    listings: list[dict[str, Any]],
    *,
    model: Optional[str] = None,
    batch_size: Optional[int] = None,
    documents: Optional[dict[str, Any]] = None,
    instructions: Optional[str] = None,
    runner=run_claude,
) -> dict[str, Any]:
    """Screen ``listings`` in batches and return verdicts keyed by url.

    Pure orchestration: stores nothing. ``runner`` is injectable for tests.
    """
    model = model or _config_value("model", DEFAULT_MODEL)
    batch_size = batch_size or _config_value("batch_size", DEFAULT_BATCH_SIZE)
    documents = documents if documents is not None else build_documents()
    if instructions is None:
        instructions, prompt_source = load_quick_screen_prompt()
    else:
        prompt_source = "caller"

    result: dict[str, Any] = {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "prompt_source": prompt_source,
        "documents": {"present": sorted(documents.get("present", {}).keys()),
                      "missing": list(documents.get("missing", []))},
        "batches": 0,
        "failed_batches": 0,
        "problems": [],
        "verdicts": {},   # url -> {"verdict", "reasoning", "listing"}
    }

    for batch in _batches(listings, batch_size):
        result["batches"] += 1
        request, refs = build_request(batch, documents, instructions)
        rc, out, err = runner(request, model)
        if rc != 0:
            result["failed_batches"] += 1
            result["problems"].append(f"batch {result['batches']}: model call failed (rc {rc}): {(err or '').strip()[-200:]}")
            continue
        verdicts, problems = parse_verdicts(out, refs)
        result["problems"].extend(f"batch {result['batches']}: {p}" for p in problems)
        for listing, ref in zip(batch, refs):
            got = verdicts.get(ref)
            if got:
                result["verdicts"][listing["url"]] = {**got, "listing": listing}
    return result


def _upsert_prospect(listing: dict[str, Any], verdict: str, reasoning: str) -> str:
    """Create or annotate the prospect for a kept listing. Returns what happened."""
    from jj.db import create_application, find_duplicate_application, update_application

    company = listing.get("company_name") or listing.get("company") or ""
    title = listing.get("title") or ""
    url = listing["url"]
    title_score = listing.get("title_score")
    note_tail = f"Quick screen: {verdict}. {reasoning}".strip()

    existing = find_duplicate_application(company=company, position=title, job_url=url)
    if existing and (existing.get("job_url") or "") != url:
        # The fuzzy company+title match hit a different posting. Do not write
        # this verdict onto that record; say so instead.
        return "duplicate_of_other_url"
    if existing:
        notes = existing.get("notes") or ""
        if notes.startswith("Fit:"):
            return "already_full_scored"
        if "Quick screen:" in notes:
            return "already_noted"
        head = notes.strip() or f"Title Fit: {title_score if title_score is not None else 0}."
        update_application(existing["id"], notes=f"{head} {note_tail}")
        return "annotated"

    create_application(
        company=company,
        position=title,
        job_url=url,
        location=listing.get("location"),
        ats_type=listing.get("ats_type"),
        fit_score=title_score if title_score is not None else 0,
        status="prospect",
        notes=f"Title Fit: {title_score if title_score is not None else 0}. {note_tail}",
    )
    return "created"


def quick_screen_new_listings(
    limit: int = 100,
    since: Optional[str] = None,
    keep: str = DEFAULT_KEEP,
    preview: bool = False,
    model: Optional[str] = None,
    batch_size: Optional[int] = None,
    runner=run_claude,
) -> dict[str, Any]:
    """Screen the highest-ranked unscreened listings and store the verdicts.

    ``preview`` calls nothing: it returns what a run would do (how many
    listings, how many batches, which documents are missing) so the person
    can be asked before anything is spent.
    """
    from jj.db import get_unscreened_listings, record_judgment

    model = model or _config_value("model", DEFAULT_MODEL)
    batch_size = batch_size or _config_value("batch_size", DEFAULT_BATCH_SIZE)
    if since is None:
        # Same net-new policy as score-new: the old backlog is screened on
        # demand, not by the scheduled run. Pass since="" to consider all.
        since = _monitor_config_value("score_new_since") or None
    elif since == "":
        since = None
    candidates = get_unscreened_listings(limit=limit, since=since)
    documents = build_documents()
    batches = _batches(candidates, batch_size) if candidates else []

    summary: dict[str, Any] = {
        "date": date.today().isoformat(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "keep": keep,
        "since": since,
        "candidates": len(candidates),
        "batches_planned": len(batches),
        "batch_size": max(1, min(int(batch_size), MAX_BATCH_SIZE)),
        "documents": {"present": sorted(documents["present"].keys()), "missing": documents["missing"]},
        "missing_notes": describe_missing_documents(
            [m for m in documents["missing"] if m != "corpus"]
        ),
        "preview": preview,
        "coverage": {"covered": 0, "total": len(candidates)},
        "screened": 0,
        "batches": 0,
        "failed_batches": 0,
        "verdict_counts": {v: 0 for v in VERDICTS},
        "kept": 0,
        "dropped": [],
        "prospects": {"created": 0, "annotated": 0, "already_full_scored": 0, "already_noted": 0,
                      "duplicate_of_other_url": 0},
        "problems": [],
        "items": [],
    }
    if "corpus" in documents["missing"]:
        summary["missing_notes"].append(
            "the corpus has no roles or skills yet, so the model screened on profile documents only"
        )
    if preview or not candidates:
        return summary

    run = quick_screen_listings(
        candidates, model=model, batch_size=batch_size, documents=documents, runner=runner,
    )
    summary["batches"] = run["batches"]
    summary["failed_batches"] = run["failed_batches"]
    summary["problems"] = run["problems"]
    summary["prompt_source"] = run["prompt_source"]

    for listing in candidates:
        url = listing["url"]
        got = run["verdicts"].get(url)
        item = {
            "url": url,
            "title": listing.get("title"),
            "company": listing.get("company_name"),
            "title_score": listing.get("title_score"),
        }
        if not got:
            item["status"] = "unscreened"
            summary["items"].append(item)
            continue
        verdict, reasoning = got["verdict"], got["reasoning"]
        summary["screened"] += 1
        summary["verdict_counts"][verdict] += 1
        item.update({"verdict": verdict, "reasoning": reasoning})
        record_judgment(
            url, verdict, reasoning, judged_by="model-quick", model=model,
            prompt_version=PROMPT_VERSION, listing_id=listing.get("id"),
            title=listing.get("title"), company=listing.get("company_name"),
        )
        if at_or_above(verdict, keep):
            summary["kept"] += 1
            outcome = _upsert_prospect(listing, verdict, reasoning)
            summary["prospects"][outcome] = summary["prospects"].get(outcome, 0) + 1
            item["prospect"] = outcome
            item["status"] = "kept"
        else:
            item["status"] = "dropped"
            summary["dropped"].append({"url": url, "reason": drop_reason(verdict, keep)})
        summary["items"].append(item)

    summary["coverage"] = {"covered": summary["screened"], "total": len(candidates)}
    return summary

