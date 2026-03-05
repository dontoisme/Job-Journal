"""Slack notification for job monitor alerts."""

import json
import logging
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from jj.config import load_config

logger = logging.getLogger("jj.notifier")


def format_slack_message(new_jobs: list[dict[str, Any]], summary: dict[str, Any]) -> dict:
    """Build Slack message payload with Block Kit formatting.

    Args:
        new_jobs: List of dicts with keys: title, company, location, score, url
        summary: Dict with keys: companies_checked, boards_checked, timestamp
    """
    timestamp = summary.get("timestamp", datetime.now().strftime("%H:%M"))
    companies = summary.get("companies_checked", 0)
    boards = summary.get("boards_checked", 0)

    if not new_jobs:
        text = (
            f"*Job Monitor: No new listings found*\n\n"
            f"_Checked {companies} companies + {boards} VC boards at {timestamp}_"
        )
        return {"text": text}

    # Group by score tier
    strong = [j for j in new_jobs if (j.get("score") or 0) >= 80]
    good = [j for j in new_jobs if 50 <= (j.get("score") or 0) < 80]
    other = [j for j in new_jobs if (j.get("score") or 0) < 50]

    lines = [f"*Job Monitor: {len(new_jobs)} new listing{'s' if len(new_jobs) != 1 else ''} found*\n"]

    if strong:
        lines.append("*Strong fits (80+):*")
        for j in strong:
            url_part = f" — <{j['url']}|View>" if j.get("url") else ""
            location = f" ({j['location']})" if j.get("location") else ""
            lines.append(
                f"• {j.get('company', '?')} — {j.get('title', '?')}{location}"
                f" — Score: {j.get('score', '?')}{url_part}"
            )
        lines.append("")

    if good:
        lines.append("*Good fits (50+):*")
        for j in good:
            url_part = f" — <{j['url']}|View>" if j.get("url") else ""
            location = f" ({j['location']})" if j.get("location") else ""
            lines.append(
                f"• {j.get('company', '?')} — {j.get('title', '?')}{location}"
                f" — Score: {j.get('score', '?')}{url_part}"
            )
        lines.append("")

    if other:
        lines.append(f"*Other ({len(other)} listing{'s' if len(other) != 1 else ''}):*")
        for j in other[:5]:
            url_part = f" — <{j['url']}|View>" if j.get("url") else ""
            location = f" ({j['location']})" if j.get("location") else ""
            lines.append(
                f"• {j.get('company', '?')} — {j.get('title', '?')}{location}{url_part}"
            )
        if len(other) > 5:
            lines.append(f"  _... and {len(other) - 5} more_")
        lines.append("")

    lines.append("Run `jj app list --status prospect` to review and finish applying.")
    lines.append(f"_Checked {companies} companies + {boards} VC boards at {timestamp}_")

    return {"text": "\n".join(lines)}


def notify_slack(webhook_url: str, new_jobs: list[dict[str, Any]],
                 summary: dict[str, Any]) -> bool:
    """POST formatted message to Slack incoming webhook.

    Returns True on success, False on failure.
    """
    payload = format_slack_message(new_jobs, summary)
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


def send_notification(new_jobs: list[dict[str, Any]], summary: dict[str, Any]) -> bool:
    """Read config and dispatch notification to Slack.

    Returns True if notification was sent successfully.
    """
    config = load_config()
    monitor_config = config.get("monitor", {})
    webhook_url = monitor_config.get("slack_webhook_url", "")

    if not webhook_url:
        logger.warning("No slack_webhook_url configured in config.yaml")
        return False

    return notify_slack(webhook_url, new_jobs, summary)
