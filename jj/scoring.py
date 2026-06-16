"""Stage 2: headless full-scoring pass for selected new prospects.

After the fast title-only scan creates prospects, this runs the full LLM
fit-score + archetype-link (/slack-apply) on the highest-value unscored
ones: every high-priority target-company posting plus non-targets clearing
the title gate. Capped per run so the cadence stays bounded and a large
backlog (e.g. a first Amazon ingest) drains over successive runs rather
than spiking cost in a single run.

This is the same headless /slack-apply path the Slack "Go" button uses;
it writes a real 'Fit:' note + fit_score and links a best-fit archetype,
which de-pollutes the digest ranking and makes target cards trustworthy.
"""
import json
import logging
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("jj.scoring")

SCORE_TIMEOUT_SEC = 900  # 15 min per job, matches the Slack pipeline
ALLOWED_TOOLS = "Bash,WebFetch,WebSearch,Read,Write,Grep,Glob"

# Burst safety net: hard ceiling on /slack-apply spawns per calendar day across
# all Stage 2 runs. A large net-new ingest (e.g. a first Amazon scrape) can
# otherwise spike token cost in a single day. Overridable via env.
DEFAULT_SCORE_DAILY_LIMIT = 15
_DAILY_COUNT_PATH = Path.home() / ".job-journal" / "logs" / "score-daily-count.json"


def _score_daily_limit() -> int:
    """Per-day spawn ceiling (env JJ_SCORE_DAILY_LIMIT, default 15)."""
    raw = os.environ.get("JJ_SCORE_DAILY_LIMIT")
    if raw is None:
        return DEFAULT_SCORE_DAILY_LIMIT
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_SCORE_DAILY_LIMIT


def _read_daily_count(today: str) -> int:
    """Spawns already recorded today (0 if file missing/stale/unreadable)."""
    try:
        data = json.loads(_DAILY_COUNT_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 0
    return int(data.get(today, 0)) if data.get("date") == today else 0


def _bump_daily_count(today: str, n: int = 1) -> int:
    """Record ``n`` more spawns for ``today``; return the new total."""
    current = _read_daily_count(today)
    new_total = current + n
    try:
        _DAILY_COUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DAILY_COUNT_PATH.write_text(json.dumps({"date": today, today: new_total}))
    except OSError:
        logger.warning("could not persist score-daily-count.json")
    return new_total


def run_full_score(url: str, timeout: int = SCORE_TIMEOUT_SEC) -> tuple[int, str, str]:
    """Spawn a headless /slack-apply run (full fit score + archetype link).

    Returns (returncode, stdout, stderr). rc=127 if the claude CLI is absent,
    124 on timeout.
    """
    claude = shutil.which("claude")
    if not claude:
        return 127, "", "'claude' not found in PATH"
    cmd = [claude, "-p", f"/slack-apply {url}", "--allowedTools", ALLOWED_TOOLS]
    logger.info("score: /slack-apply %s", url)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        logger.error("score timeout after %ds: %s", timeout, url)
        return 124, "", f"Timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001 - report any launch failure to caller
        logger.exception("score subprocess failed")
        return 1, "", str(e)


BRIEF_TIMEOUT_SEC = 900  # 15 min per brief, matches the scoring pipeline
BRIEF_ALLOWED_TOOLS = "Bash,WebFetch,WebSearch,Read,Write,Grep,Glob"


def run_research_brief(app_id: int, timeout: int = BRIEF_TIMEOUT_SEC) -> tuple[int, str, str]:
    """Spawn a headless /research-brief run (why-now + why-me research).

    Invoked with ``--id`` so the skill resolves the application (and its
    job_url) and persists the brief to applications.research_brief for that id.
    Returns (returncode, stdout, stderr). rc=127 if the claude CLI is absent,
    124 on timeout.
    """
    claude = shutil.which("claude")
    if not claude:
        return 127, "", "'claude' not found in PATH"
    cmd = [claude, "-p", f"/research-brief --id {app_id}", "--allowedTools", BRIEF_ALLOWED_TOOLS]
    logger.info("brief: /research-brief --id %s", app_id)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        logger.error("brief timeout after %ds: app %s", timeout, app_id)
        return 124, "", f"Timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001 - report any launch failure to caller
        logger.exception("brief subprocess failed")
        return 1, "", str(e)


def _has_research_brief(app_id: int) -> bool:
    """True if the application now carries a non-empty research_brief."""
    from jj.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT research_brief FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
    brief = (row["research_brief"] or "").strip() if row else ""
    return bool(brief)


def prep_apply_briefs(limit: int = 3, dry_run: bool = False) -> dict[str, Any]:
    """Generate research briefs for apply-ready prospects missing one (Stage 3).

    For each apply-ready prospect (see db.get_apply_ready_prospects) whose
    research_brief is empty, spawn a headless /research-brief run so the brief
    is ready before Don applies. Capped per run to keep cost bounded. Returns a
    summary dict: selected, prepared, already, no_change, failed, skipped.
    """
    from jj.db import get_apply_ready_prospects

    picks = get_apply_ready_prospects(limit=limit)
    summary: dict[str, Any] = {
        "selected": len(picks),
        "prepared": 0,
        "already": 0,
        "no_change": 0,
        "failed": 0,
        "skipped": 0,
        "items": [],
    }

    for p in picks:
        url = p.get("job_url") or ""
        app_id = p.get("id")
        label = f"{p.get('company', '?')} — {p.get('position', '?')}"
        existing = (p.get("research_brief") or "").strip()
        if existing:
            summary["already"] += 1
            summary["items"].append({"app": label, "status": "already"})
            continue
        if not app_id:
            summary["skipped"] += 1
            summary["items"].append({"app": label, "status": "skip_no_id"})
            continue
        if dry_run:
            summary["items"].append({"app": label, "status": "would_prep", "url": url})
            continue
        rc, _out, err = run_research_brief(app_id)
        if rc != 0:
            summary["failed"] += 1
            summary["items"].append({"app": label, "status": f"fail_rc{rc}", "err": (err or "")[-200:]})
        elif app_id and _has_research_brief(app_id):
            summary["prepared"] += 1
            summary["items"].append({"app": label, "status": "prepared"})
        else:
            # Clean exit but no brief written — typically a dead/stale JD URL.
            summary["no_change"] += 1
            summary["items"].append({"app": label, "status": "no_change"})

    return summary


STAGE_TIMEOUT_SEC = 900  # 15 min per tailored resume, matches the brief budget
STAGE_ALLOWED_TOOLS = "Bash,WebFetch,Read,Grep,Glob"  # no browser; headless gen
TAILOR_FIT_THRESHOLD = 85  # >= this -> disciplined per-JD tailor; else archetype


def run_stage_resume(app_id: int, timeout: int = STAGE_TIMEOUT_SEC) -> tuple[int, str, str]:
    """Spawn a headless /stage-resume run (disciplined per-JD tailor for top picks).

    The skill resolves the application, generates a tailored resume via
    generate_resume_programmatic, and persists resume_id + staged_resume_path.
    Returns (returncode, stdout, stderr). rc=127 if the claude CLI is absent.
    """
    claude = shutil.which("claude")
    if not claude:
        return 127, "", "'claude' not found in PATH"
    cmd = [claude, "-p", f"/stage-resume --id {app_id}", "--allowedTools", STAGE_ALLOWED_TOOLS]
    logger.info("stage: /stage-resume --id %s", app_id)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        logger.error("stage timeout after %ds: app %s", timeout, app_id)
        return 124, "", f"Timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001
        logger.exception("stage subprocess failed")
        return 1, "", str(e)


def _archetype_from_notes(notes: Optional[str]) -> str:
    """Parse 'Archetype: <variant>' from a full-score note; default 'general'."""
    import re

    m = re.search(r"Archetype:\s*([a-z\-]+)", notes or "", re.IGNORECASE)
    return m.group(1).lower() if m else "general"


def stage_archetype_resume(application: dict[str, Any], archetype: str = "general") -> Optional[str]:
    """Copy the best-fit archetype PDF to a dated per-application file; return its path.

    Mirrors the staging in `jj app prep` so apply-ready prospects carry a resume
    file before the Slack notification fires. Returns None if the archetype PDF
    or company/position are missing, or the copy fails.
    """
    import shutil as _shutil
    from datetime import date as _date

    from jj.config import load_archetypes, load_profile

    company = application.get("company")
    position = application.get("position")
    if not (company and position):
        return None

    arch_config = load_archetypes() or {}
    variants = arch_config.get("archetypes", arch_config)
    variant = variants.get(archetype) or variants.get("general")
    pdf_path = (variant or {}).get("pdf_path", "")
    if not pdf_path or not Path(pdf_path).exists():
        return None

    profile = load_profile()
    name = profile.get("name", {})
    full_name = f"{name.get('first', '')} {name.get('last', '')}".strip() or "Don Hogan"

    def _safe(part: str) -> str:
        return str(part or "").replace("/", "-").strip()

    fname = f"{full_name} - {_safe(position)} - {_safe(company)} - Resume.pdf"
    base = Path(profile.get("resume_output_dir", "~/Documents/Resumes")).expanduser()
    dated = base / _date.today().isoformat()
    try:
        dated.mkdir(parents=True, exist_ok=True)
        dest = dated / fname
        _shutil.copy2(pdf_path, dest)
        return str(dest)
    except OSError:
        logger.exception("archetype resume staging failed for app %s", application.get("id"))
        return None


def _staged_resume_path(app_id: int) -> str:
    """The application's persisted staged_resume_path (empty if none)."""
    from jj.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT staged_resume_path FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
    return (row["staged_resume_path"] or "").strip() if row else ""


def prep_apply_packages(limit: int = 2, dry_run: bool = False) -> dict[str, Any]:
    """Stage the full pre-browser package (research brief + resume) before Slack.

    For each apply-ready prospect: ensure a research brief (reusing
    run_research_brief), then stage a resume by fit -- a disciplined per-JD tailor
    via /stage-resume for fit >= TAILOR_FIT_THRESHOLD, otherwise a best-fit
    archetype copy. The tailored path persists resume_id + staged_resume_path
    itself; the archetype path is persisted here. Failures never block the Slack
    post (apply-assist stages on demand as a fallback). Returns a summary dict.
    """
    from jj.db import get_apply_ready_prospects, update_application

    picks = get_apply_ready_prospects(limit=limit)
    summary: dict[str, Any] = {
        "selected": len(picks),
        "briefs": 0,
        "resumes": 0,
        "tailored": 0,
        "archetype": 0,
        "failed": 0,
        "items": [],
    }

    for p in picks:
        app_id = p.get("id")
        fit = p.get("fit_score") or 0
        item: dict[str, Any] = {"app": f"{p.get('company', '?')} — {p.get('position', '?')}", "id": app_id}
        if not app_id:
            item["status"] = "skip_no_id"
            summary["items"].append(item)
            continue
        if dry_run:
            item["status"] = "would_prep"
            item["resume_mode"] = "tailored" if fit >= TAILOR_FIT_THRESHOLD else "archetype"
            summary["items"].append(item)
            continue

        # 1. Research brief (skip if already present)
        if (p.get("research_brief") or "").strip():
            item["brief"] = "already"
        else:
            rc, _out, _err = run_research_brief(app_id)
            if rc == 0 and _has_research_brief(app_id):
                summary["briefs"] += 1
                item["brief"] = "prepared"
            else:
                item["brief"] = f"fail_rc{rc}"

        # 2. Resume staging by fit, with archetype fallback
        staged = ""
        if fit >= TAILOR_FIT_THRESHOLD:
            rc, _out, _err = run_stage_resume(app_id)
            staged = _staged_resume_path(app_id)
            if rc == 0 and staged:
                summary["tailored"] += 1
                item["resume"] = "tailored"
        if not staged:
            path = stage_archetype_resume(p, _archetype_from_notes(p.get("notes")))
            if path:
                update_application(app_id, staged_resume_path=path)
                staged = path
                summary["archetype"] += 1
                item.setdefault("resume", "archetype")
        if staged:
            summary["resumes"] += 1
            item["staged_resume_path"] = staged
        else:
            summary["failed"] += 1
            item.setdefault("resume", "fail")
        summary["items"].append(item)

    return summary


def _is_full_scored(app_id: int) -> bool:
    """True if the application now carries a full 'Fit:' note (not 'Title Fit:')."""
    from jj.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT notes FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
    notes = (row["notes"] or "") if row else ""
    return notes.startswith("Fit:")


def score_new_prospects(
    limit: int = 10,
    dry_run: bool = False,
    since: Optional[str] = None,
) -> dict[str, Any]:
    """Full-score the top-N unscored selected prospects (net-new by default).

    ``since`` defaults to config monitor.score_new_since (the net-new cutoff);
    pass since="" to override and consider the full backlog. Returns a summary
    dict: selected, scored, no_change (e.g. stale/dead URL), failed, skipped.
    """
    from jj.config import load_config
    from jj.db import get_unscored_selected_prospects

    if since is None:
        since = (load_config().get("monitor", {}) or {}).get("score_new_since") or None
    elif since == "":
        since = None

    picks = get_unscored_selected_prospects(limit=limit, since=since)
    summary: dict[str, Any] = {
        "selected": len(picks),
        "scored": 0,
        "no_change": 0,
        "failed": 0,
        "skipped": 0,
        "items": [],
    }

    today = date.today().isoformat()
    daily_limit = _score_daily_limit()
    daily_count = _read_daily_count(today)

    for p in picks:
        url = p.get("job_url") or ""
        app_id = p.get("id")
        label = f"{p.get('company', '?')} — {p.get('position', '?')}"
        if not url:
            summary["skipped"] += 1
            summary["items"].append({"app": label, "status": "skip_no_url"})
            continue
        if dry_run:
            summary["items"].append({"app": label, "status": "would_score", "url": url})
            continue
        if daily_count >= daily_limit:
            logger.warning(
                "daily score cap reached (%d); skipping remaining %s",
                daily_limit, label,
            )
            summary["skipped"] += 1
            summary["items"].append({"app": label, "status": "skip_daily_cap"})
            continue
        rc, _out, err = run_full_score(url)
        daily_count = _bump_daily_count(today)
        if rc != 0:
            summary["failed"] += 1
            summary["items"].append({"app": label, "status": f"fail_rc{rc}", "err": (err or "")[-200:]})
        elif app_id and _is_full_scored(app_id):
            summary["scored"] += 1
            summary["items"].append({"app": label, "status": "scored"})
        else:
            # Clean exit but no full score written — typically a dead/stale JD URL.
            summary["no_change"] += 1
            summary["items"].append({"app": label, "status": "no_change"})

    return summary
