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
import logging
import shutil
import subprocess
from typing import Any, Optional

logger = logging.getLogger("jj.scoring")

SCORE_TIMEOUT_SEC = 900  # 15 min per job, matches the Slack pipeline
ALLOWED_TOOLS = "Bash,WebFetch,WebSearch,Read,Write,Grep,Glob"


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
        rc, _out, err = run_full_score(url)
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
