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


def _format_job_block(j: dict[str, Any], show_verdict: bool = False) -> dict:
    """Format a single job as a Block Kit section with [Score] button accessory.

    The button carries the job URL in its `value` field; the Slack bot's
    block_actions handler reads this to spawn `claude -p "/score <url>"`.
    If the URL is missing or exceeds Slack's 2000-char value limit, the
    button is omitted and the job still renders as a plain section.
    """
    company = j.get("company", "?")
    title = j.get("title", "?")
    location = f" ({j['location']})" if j.get("location") else ""
    score_type = j.get("score_type", "Score")
    score_text = f"{score_type}: {j.get('score', '?')}"
    verdict = j.get("verdict", "")
    if show_verdict and verdict:
        score_text += f" ({verdict})"
    url = j.get("url", "") or ""
    doc_url = j.get("doc_url")
    warning = " :warning:" if j.get("fabrication_warning") else ""

    line1 = f"*{company}* — {title}{location}{warning}"
    line2_parts = [f"_{score_text}_"]
    if url:
        line2_parts.append(f"<{url}|View JD>")
    if doc_url:
        line2_parts.append(f"<{doc_url}|Resume>")
    line2 = " — ".join(line2_parts)

    block: dict[str, Any] = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"{line1}\n{line2}"},
    }
    if url and len(url) <= 2000:
        block["accessory"] = {
            "type": "button",
            "text": {"type": "plain_text", "text": "Score", "emoji": True},
            "action_id": "score_job",
            "value": url,
        }
    return block


def _tier_jobs(new_jobs: list[dict[str, Any]]) -> tuple[str, bool, list, list, list, list]:
    """Return (dominant_type, show_verdict, strong, good, moderate, other) tiers."""
    score_types = [j.get("score_type", "Score") for j in new_jobs]
    dominant_type = "Corpus Fit" if "Corpus Fit" in score_types else "Title Fit"
    show_verdict = dominant_type == "Corpus Fit"

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

    return dominant_type, show_verdict, strong, good, moderate, other


def _build_blocks_payload(
    new_jobs: list[dict[str, Any]],
    summary: dict[str, Any],
    email_sync: dict[str, Any] | None,
) -> dict:
    """Build a Block Kit payload with [Score] button accessories per job."""
    timestamp = summary.get("timestamp", datetime.now().strftime("%H:%M"))
    companies = summary.get("companies_checked", 0)
    boards = summary.get("boards_checked", 0)
    prospects_created = summary.get("prospects_created", 0)
    resumes_generated = summary.get("resumes_generated", 0)

    if not new_jobs:
        footer = f"Checked {companies} companies + {boards} VC boards at {timestamp}"
        if email_sync:
            sync_line = _format_email_sync_line(email_sync)
            if sync_line:
                footer += f"\n{sync_line}"
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Job Monitor: No new listings"},
                },
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"_{footer}_"}],
                },
            ]
        }

    dominant_type, show_verdict, strong, good, moderate, other = _tier_jobs(new_jobs)

    MAX_LISTED = 25
    listed = 0
    blocks: list[dict[str, Any]] = []

    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Job Monitor: {len(new_jobs)} new listing{'s' if len(new_jobs) != 1 else ''}",
        },
    })

    def _add_tier(tier_jobs: list[dict[str, Any]], label: str, verdict: bool, cap: int) -> int:
        """Append a tier header + job blocks. Returns number appended."""
        nonlocal listed
        if not tier_jobs or listed >= MAX_LISTED:
            return 0
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{label}:*"}})
        appended = 0
        for j in tier_jobs:
            if listed >= cap:
                break
            blocks.append(_format_job_block(j, show_verdict=verdict))
            listed += 1
            appended += 1
        blocks.append({"type": "divider"})
        return appended

    _add_tier(strong, _score_label(dominant_type, 80), show_verdict, MAX_LISTED)

    good_threshold = 65 if dominant_type == "Corpus Fit" else 50
    _add_tier(good, _score_label(dominant_type, good_threshold), show_verdict, MAX_LISTED)

    _add_tier(moderate, _score_label(dominant_type, 50), show_verdict, MAX_LISTED)

    if other and listed < MAX_LISTED:
        other_cap = min(listed + 5, MAX_LISTED)
        _add_tier(
            other[: other_cap - listed],
            f"Other ({len(other)} listing{'s' if len(other) != 1 else ''})",
            False,
            other_cap,
        )

    total_unlisted = len(new_jobs) - listed
    footer_lines: list[str] = []
    if total_unlisted > 0:
        footer_lines.append(
            f"_… and {total_unlisted} more — run `jj app list --status prospect` to see all_"
        )

    footer_parts = []
    if prospects_created > 0:
        footer_parts.append(f"{prospects_created} prospect{'s' if prospects_created != 1 else ''} created")
    if resumes_generated > 0:
        footer_parts.append(f"{resumes_generated} resume{'s' if resumes_generated != 1 else ''} generated")
    if footer_parts:
        footer_lines.append(f"_{', '.join(footer_parts)}_")

    footer_lines.append(
        f"<http://localhost:8000/prospects|View Prospects Dashboard> · "
        f"_Checked {companies} companies + {boards} VC boards at {timestamp}_"
    )
    if email_sync:
        sync_line = _format_email_sync_line(email_sync)
        if sync_line:
            footer_lines.append(sync_line)

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "\n".join(footer_lines)}],
    })

    # Slack hard limit: 50 blocks per message
    if len(blocks) > 50:
        blocks = blocks[:49] + [blocks[-1]]

    return {"blocks": blocks}


def format_slack_message(new_jobs: list[dict[str, Any]], summary: dict[str, Any],
                         email_sync: dict[str, Any] | None = None,
                         blocks_mode: bool = True) -> dict:
    """Build Slack message payload.

    Args:
        new_jobs: List of dicts with keys: title, company, location, score, url,
                  score_type, verdict, doc_url, fabrication_warning
        summary: Dict with keys: companies_checked, boards_checked, timestamp,
                 prospects_created, resumes_generated
        email_sync: Optional dict with keys: confirmations_found, resolutions_found,
                    applications_checked
        blocks_mode: When True (default), return Block Kit payload with
                     [Score] button accessories per job. When False, return
                     the legacy `{"text": ...}` plain-markdown payload.
    """
    if blocks_mode:
        return _build_blocks_payload(new_jobs, summary, email_sync)

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

    dominant_type, show_verdict, strong, good, moderate, other = _tier_jobs(new_jobs)

    lines = [f"*Job Monitor: {len(new_jobs)} new listing{'s' if len(new_jobs) != 1 else ''} found*\n"]

    # Cap total listed jobs to stay under Slack's ~3,000 char text limit.
    # ~100 chars/line × 25 lines ≈ 2,500 chars, leaving room for header/footer.
    MAX_LISTED = 25
    listed = 0

    if strong:
        lines.append(f"*{_score_label(dominant_type, 80)}:*")
        for j in strong:
            if listed >= MAX_LISTED:
                break
            lines.append(_format_job_line(j, show_verdict=show_verdict))
            listed += 1
        lines.append("")

    if good and listed < MAX_LISTED:
        threshold = 65 if dominant_type == "Corpus Fit" else 50
        lines.append(f"*{_score_label(dominant_type, threshold)}:*")
        for j in good:
            if listed >= MAX_LISTED:
                break
            lines.append(_format_job_line(j, show_verdict=show_verdict))
            listed += 1
        lines.append("")

    if moderate and listed < MAX_LISTED:
        lines.append(f"*{_score_label(dominant_type, 50)}:*")
        for j in moderate:
            if listed >= MAX_LISTED:
                break
            lines.append(_format_job_line(j, show_verdict=show_verdict))
            listed += 1
        lines.append("")

    if other and listed < MAX_LISTED:
        remaining_slots = min(5, MAX_LISTED - listed)
        lines.append(f"*Other ({len(other)} listing{'s' if len(other) != 1 else ''}):*")
        for j in other[:remaining_slots]:
            lines.append(_format_job_line(j, show_verdict=False))
            listed += 1
        if len(other) > remaining_slots:
            lines.append(f"  _... and {len(other) - remaining_slots} more_")
        lines.append("")

    total_unlisted = len(new_jobs) - listed
    if total_unlisted > 0:
        lines.append(f"_... and {total_unlisted} more — run `jj app list --status prospect` to see all_\n")

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
    """POST formatted message to Slack incoming webhook (legacy path).

    Kept for backwards compatibility. New installs should use a bot token
    so that interactive [Score] buttons route back to the bot correctly.

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
                logger.info("Slack notification sent via webhook (%d jobs)", len(new_jobs))
                return True
            logger.warning("Slack returned status %d", resp.status)
            return False
    except URLError as e:
        logger.error("Slack notification failed: %s", e)
        return False


def notify_slack_via_bot(
    bot_token: str,
    channel: str,
    new_jobs: list[dict[str, Any]],
    summary: dict[str, Any],
    email_sync: dict[str, Any] | None = None,
) -> bool:
    """Post notification via chat.postMessage using the bot token.

    This is the preferred path because interactive components (buttons)
    route their click events back to the posting app — so jj-bot owns the
    message and receives [Score] button clicks via Socket Mode.

    Returns True on success, False on failure.
    """
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError:
        logger.error("slack_sdk not installed. Run: pip install -e '.[slack]'")
        return False

    payload = format_slack_message(new_jobs, summary, email_sync=email_sync, blocks_mode=True)

    # chat.postMessage requires a fallback text field for mobile pushes /
    # screen readers even when blocks are provided.
    fallback_text = (
        f"Job Monitor: {len(new_jobs)} new listing{'s' if len(new_jobs) != 1 else ''}"
        if new_jobs
        else "Job Monitor: no new listings"
    )

    client = WebClient(token=bot_token)
    try:
        resp = client.chat_postMessage(
            channel=channel,
            text=fallback_text,
            blocks=payload.get("blocks"),
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as e:
        logger.error("Slack chat.postMessage failed: %s", e.response.get("error", str(e)))
        return False
    except Exception as e:
        logger.error("Slack bot notification failed: %s", e)
        return False

    if resp.get("ok"):
        logger.info("Slack notification sent via bot (%d jobs)", len(new_jobs))
        return True
    logger.warning("Slack chat.postMessage returned ok=false: %s", resp.data)
    return False


def send_notification(new_jobs: list[dict[str, Any]], summary: dict[str, Any],
                      email_sync: dict[str, Any] | None = None) -> bool:
    """Read config and dispatch notification to Slack.

    Prefers the bot-token path (enables interactive [Score] buttons).
    Falls back to the legacy webhook path if bot_token/channel aren't
    configured. Returns True if notification was sent successfully.
    """
    config = load_config()
    monitor_config = config.get("monitor", {})

    # Preferred: bot token + channel (supports interactive buttons)
    bot_token = monitor_config.get("slack_bot_token", "")
    channel = monitor_config.get("slack_default_channel", "")
    if bot_token and channel:
        return notify_slack_via_bot(bot_token, channel, new_jobs, summary, email_sync=email_sync)

    # Fallback: legacy webhook (no interactivity)
    webhook_url = monitor_config.get("slack_webhook_url", "")
    if webhook_url:
        if bot_token and not channel:
            logger.warning(
                "slack_bot_token is set but slack_default_channel is empty — "
                "falling back to webhook. Buttons will NOT be interactive."
            )
        return notify_slack(webhook_url, new_jobs, summary, email_sync=email_sync)

    logger.warning(
        "No Slack delivery configured. Set slack_bot_token + slack_default_channel "
        "(preferred) or slack_webhook_url in ~/.job-journal/config.yaml"
    )
    return False
