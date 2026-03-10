"""Slack notification for job monitor alerts."""

import json
import logging
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from jj.config import load_config

logger = logging.getLogger("jj.notifier")


def _score_label(score_type: str, threshold: int) -> str:
    """Return tier header text based on score_type and threshold."""
    if score_type == "Corpus Fit":
        if threshold >= 80:
            return "Strong fits (80+)"
        elif threshold >= 65:
            return "Good fits (65+)"
        else:
            return "Moderate fits (50+)"
    else:
        # Title Fit (default)
        if threshold >= 80:
            return "Strong title match (80+)"
        else:
            return "Good title match (50+)"


def _verdict_for_score(score: int) -> str:
    """Return verdict text for a corpus fit score."""
    if score >= 80:
        return "Strong Fit"
    elif score >= 65:
        return "Good Fit"
    elif score >= 50:
        return "Moderate"
    return ""


def _format_job_line(j: dict[str, Any], show_verdict: bool = False) -> str:
    """Format a single job listing line for Slack."""
    url_part = f" — <{j['url']}|View>" if j.get("url") else ""
    location = f" ({j['location']})" if j.get("location") else ""
    score_type = j.get("score_type", "Score")
    score_text = f" — {score_type}: {j.get('score', '?')}"

    # Add verdict for corpus-scored jobs
    verdict = j.get("verdict", "")
    if show_verdict and verdict:
        score_text += f" ({verdict})"

    # Add resume link if available
    doc_url = j.get("doc_url")
    resume_part = f" — <{doc_url}|Resume>" if doc_url else ""

    # Add fabrication warning if flagged
    warning = " :warning:" if j.get("fabrication_warning") else ""

    return (
        f"• {j.get('company', '?')} — {j.get('title', '?')}{location}"
        f"{score_text}{resume_part}{url_part}{warning}"
    )


def format_slack_message(new_jobs: list[dict[str, Any]], summary: dict[str, Any],
                         email_sync: dict[str, Any] | None = None) -> dict:
    """Build Slack message payload with Block Kit formatting.

    Args:
        new_jobs: List of dicts with keys: title, company, location, score, url,
                  score_type, verdict, doc_url, fabrication_warning
        summary: Dict with keys: companies_checked, boards_checked, timestamp,
                 prospects_created, resumes_generated
        email_sync: Optional dict with keys: confirmations_found, resolutions_found,
                    applications_checked
    """
    timestamp = summary.get("timestamp", datetime.now().strftime("%H:%M"))
    companies = summary.get("companies_checked", 0)
    boards = summary.get("boards_checked", 0)
    prospects_created = summary.get("prospects_created", 0)
    resumes_generated = summary.get("resumes_generated", 0)

    if not new_jobs:
        text = (
            f"*Job Monitor: No new listings found*\n\n"
            f"_Checked {companies} companies + {boards} VC boards at {timestamp}_"
        )
        # Add email sync summary even when no new jobs
        if email_sync:
            sync_line = _format_email_sync_line(email_sync)
            if sync_line:
                text += f"\n{sync_line}"
        return {"text": text}

    # Determine dominant score_type for tier headers
    score_types = [j.get("score_type", "Score") for j in new_jobs]
    dominant_type = "Corpus Fit" if "Corpus Fit" in score_types else "Title Fit"
    show_verdict = dominant_type == "Corpus Fit"

    # Group by score tier — use corpus-fit thresholds when available
    if dominant_type == "Corpus Fit":
        strong = [j for j in new_jobs if (j.get("score") or 0) >= 80]
        good = [j for j in new_jobs if 65 <= (j.get("score") or 0) < 80]
        moderate = [j for j in new_jobs if 50 <= (j.get("score") or 0) < 65]
        other = [j for j in new_jobs if (j.get("score") or 0) < 50]
    else:
        strong = [j for j in new_jobs if (j.get("score") or 0) >= 80]
        good = [j for j in new_jobs if 50 <= (j.get("score") or 0) < 80]
        moderate = []
        other = [j for j in new_jobs if (j.get("score") or 0) < 50]

    lines = [f"*Job Monitor: {len(new_jobs)} new listing{'s' if len(new_jobs) != 1 else ''} found*\n"]

    if strong:
        lines.append(f"*{_score_label(dominant_type, 80)}:*")
        for j in strong:
            lines.append(_format_job_line(j, show_verdict=show_verdict))
        lines.append("")

    if good:
        threshold = 65 if dominant_type == "Corpus Fit" else 50
        lines.append(f"*{_score_label(dominant_type, threshold)}:*")
        for j in good:
            lines.append(_format_job_line(j, show_verdict=show_verdict))
        lines.append("")

    if moderate:
        lines.append(f"*{_score_label(dominant_type, 50)}:*")
        for j in moderate:
            lines.append(_format_job_line(j, show_verdict=show_verdict))
        lines.append("")

    if other:
        lines.append(f"*Other ({len(other)} listing{'s' if len(other) != 1 else ''}):*")
        for j in other[:5]:
            lines.append(_format_job_line(j, show_verdict=False))
        if len(other) > 5:
            lines.append(f"  _... and {len(other) - 5} more_")
        lines.append("")

    # Footer
    lines.append("<http://localhost:8000/prospects|View Prospects Dashboard> or run `jj app list --status prospect`")

    # Prospects and resumes summary
    footer_parts = []
    if prospects_created > 0:
        footer_parts.append(f"{prospects_created} prospect{'s' if prospects_created != 1 else ''} created")
    if resumes_generated > 0:
        footer_parts.append(f"{resumes_generated} resume{'s' if resumes_generated != 1 else ''} generated")
    if footer_parts:
        lines.append(f"_{', '.join(footer_parts)}_")

    lines.append(f"_Checked {companies} companies + {boards} VC boards at {timestamp}_")

    # Email sync summary
    if email_sync:
        sync_line = _format_email_sync_line(email_sync)
        if sync_line:
            lines.append(sync_line)

    return {"text": "\n".join(lines)}


def _format_email_sync_line(email_sync: dict[str, Any]) -> str | None:
    """Format email sync results as a one-line summary."""
    if not email_sync:
        return None

    confirmations = email_sync.get("confirmations_found", 0)
    resolutions = email_sync.get("resolutions_found", 0)
    checked = email_sync.get("applications_checked", 0)

    parts = []
    if confirmations > 0:
        parts.append(f"{confirmations} confirmation{'s' if confirmations != 1 else ''}")
    if resolutions > 0:
        parts.append(f"{resolutions} resolution{'s' if resolutions != 1 else ''}")

    if parts:
        return f"_Email sync: {', '.join(parts)} (checked {checked} apps)_"
    elif checked > 0:
        return f"_Email sync: no new updates ({checked} apps checked)_"
    return None


def notify_slack(webhook_url: str, new_jobs: list[dict[str, Any]],
                 summary: dict[str, Any],
                 email_sync: dict[str, Any] | None = None) -> bool:
    """POST formatted message to Slack incoming webhook.

    Returns True on success, False on failure.
    """
    payload = format_slack_message(new_jobs, summary, email_sync=email_sync)
    data = json.dumps(payload).encode("utf-8")

    req = Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("Slack notification sent (%d jobs)", len(new_jobs))
                return True
            logger.warning("Slack returned status %d", resp.status)
            return False
    except URLError as e:
        logger.error("Slack notification failed: %s", e)
        return False


def send_notification(new_jobs: list[dict[str, Any]], summary: dict[str, Any],
                      email_sync: dict[str, Any] | None = None) -> bool:
    """Read config and dispatch notification to Slack.

    Returns True if notification was sent successfully.
    """
    config = load_config()
    monitor_config = config.get("monitor", {})
    webhook_url = monitor_config.get("slack_webhook_url", "")

    if not webhook_url:
        logger.warning("No slack_webhook_url configured in config.yaml")
        return False

    return notify_slack(webhook_url, new_jobs, summary, email_sync=email_sync)
