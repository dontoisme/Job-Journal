"""Slack Socket Mode bot for jj — handles [Score] button clicks.

Listens for block_actions interactions from the Slack workspace via
Socket Mode (no public endpoint required). When the user clicks a
[Score] button on a job notification, the bot:

  1. Validates the clicker against slack_authorized_users
  2. Pre-checks the DB for an existing score on that URL
  3. Enqueues the job for a single worker thread
  4. Spawns `claude -p "/score <url>"` as a subprocess
  5. Posts the result back as a threaded reply

Designed to run as a macOS LaunchAgent with KeepAlive so it restarts
automatically on crash. Uses only `slack_sdk` (no slack_bolt).
"""

import json
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Optional

try:
    from slack_sdk.web import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
except ImportError as e:
    print(
        f"ERROR: slack_sdk not installed. Run: pip install -e '.[slack]'\n{e}",
        file=sys.stderr,
    )
    raise

from jj.config import load_config

logger = logging.getLogger("jj.slack_bot")

# --- Constants ---
SCORE_TIMEOUT_SEC = 600  # 10-minute hard limit per /score subprocess
ACTION_ID = "score_job"
WORKER_POLL_INTERVAL = 1.0
ALLOWED_TOOLS = "Bash,WebFetch,Read,Grep,Glob"


# --- Worker queue + shutdown flag ---
_job_queue: "queue.Queue[dict]" = queue.Queue()
_shutdown = threading.Event()


# =============================================================================
# Slack helpers
# =============================================================================

def _post_message(
    web: WebClient,
    *,
    channel: str,
    thread_ts: Optional[str],
    text: str,
) -> Optional[str]:
    """Post a thread reply (or channel message if thread_ts is None)."""
    try:
        resp = web.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
        return resp.get("ts")
    except Exception as e:
        logger.error("chat.postMessage failed: %s", e)
        return None


def _post_ephemeral(web: WebClient, *, channel: str, user: str, text: str) -> None:
    """Post a message only visible to `user`."""
    try:
        web.chat_postEphemeral(channel=channel, user=user, text=text)
    except Exception as e:
        logger.error("chat.postEphemeral failed: %s", e)


# =============================================================================
# DB helpers
# =============================================================================

def _lookup_application_by_url(url: str) -> Optional[dict[str, Any]]:
    """Fetch the latest application row matching `job_url`."""
    from jj.db import get_connection, init_database

    init_database()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, company, position, fit_score, notes, status "
            "FROM applications WHERE job_url = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (url,),
        ).fetchone()
        return dict(row) if row else None


def _verdict_from_score(score: Optional[int]) -> str:
    if score is None:
        return ""
    if score >= 80:
        return "Strong Fit"
    if score >= 65:
        return "Good Fit"
    if score >= 50:
        return "Moderate"
    return "Stretch"


# =============================================================================
# Subprocess — spawn `claude -p "/score <url>"`
# =============================================================================

def _run_score_subprocess(url: str) -> tuple[int, str, str]:
    """Spawn the headless /score run. Returns (returncode, stdout, stderr)."""
    claude_path = shutil.which("claude")
    if not claude_path:
        return 127, "", "'claude' not found in PATH"

    cmd = [
        claude_path,
        "-p",
        f"/score {url}",
        "--allowedTools",
        ALLOWED_TOOLS,
    ]
    logger.info("Spawning: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SCORE_TIMEOUT_SEC,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        logger.error("Score subprocess timed out after %ds", SCORE_TIMEOUT_SEC)
        return 124, "", f"Timed out after {SCORE_TIMEOUT_SEC}s"
    except Exception as e:
        logger.exception("Subprocess launch failed")
        return 1, "", str(e)


def _format_result_message(
    url: str,
    app: Optional[dict[str, Any]],
    returncode: int,
    stderr_tail: str,
) -> str:
    """Build the Slack text for a completed (or failed) score job."""
    if returncode == 124:
        return (
            f":warning: Scoring timed out after {SCORE_TIMEOUT_SEC // 60} min. "
            f"<{url}|View JD>"
        )
    if returncode != 0 or app is None:
        tail = (stderr_tail or "(no error output)").strip()[-300:]
        return (
            f":x: Scoring failed (exit {returncode}) for <{url}|this job>.\n"
            f"```{tail}```"
        )
    score = app.get("fit_score")
    verdict = _verdict_from_score(score)
    company = app.get("company", "?")
    position = app.get("position", "?")
    app_id = app.get("id")
    dash = f"http://localhost:8000/applications/{app_id}" if app_id else None

    line = (
        f":white_check_mark: Scored: *{position}* @ *{company}* — "
        f"Fit: *{score}* ({verdict})"
    )
    if dash:
        line += f" — <{dash}|View report>"
    return line


# =============================================================================
# Worker loop — single thread, drains the queue serially
# =============================================================================

def _worker_loop(web: WebClient) -> None:
    logger.info("Score worker started")
    while not _shutdown.is_set():
        try:
            job = _job_queue.get(timeout=WORKER_POLL_INTERVAL)
        except queue.Empty:
            continue
        try:
            url = job["url"]
            channel = job["channel"]
            thread_ts = job.get("thread_ts")

            logger.info("Worker picked up: %s", url)
            t0 = time.time()
            rc, stdout, stderr = _run_score_subprocess(url)
            elapsed = int(time.time() - t0)
            logger.info(
                "Score finished in %ds (rc=%d, stdout=%d bytes, stderr=%d bytes)",
                elapsed, rc, len(stdout), len(stderr),
            )

            app = _lookup_application_by_url(url) if rc == 0 else None
            text = _format_result_message(url, app, rc, stderr)
            _post_message(web, channel=channel, thread_ts=thread_ts, text=text)
        except Exception as e:
            logger.exception("Worker error processing job: %s", e)
            try:
                _post_message(
                    web,
                    channel=job.get("channel", ""),
                    thread_ts=job.get("thread_ts"),
                    text=f":x: Internal error scoring job: {e}",
                )
            except Exception:
                pass
        finally:
            _job_queue.task_done()
    logger.info("Score worker exiting")


# =============================================================================
# Interaction handler
# =============================================================================

def _extract_thread_ts(payload: dict) -> Optional[str]:
    """Pick the best thread_ts so replies nest under the original notification."""
    msg = payload.get("message", {}) or {}
    if msg.get("thread_ts"):
        return msg["thread_ts"]
    if msg.get("ts"):
        return msg["ts"]
    container = payload.get("container", {}) or {}
    return container.get("message_ts")


def _on_block_actions(web: WebClient, req: SocketModeRequest, authorized_users: list[str]) -> None:
    payload = req.payload
    actions = payload.get("actions", []) or []
    channel = (
        (payload.get("channel") or {}).get("id")
        or (payload.get("container") or {}).get("channel_id")
    )
    user = (payload.get("user") or {}).get("id")
    thread_ts = _extract_thread_ts(payload)

    for action in actions:
        if action.get("action_id") != ACTION_ID:
            continue

        url = action.get("value", "") or ""
        if not url or not channel:
            logger.warning("Bad action payload: %s", json.dumps(payload)[:300])
            continue

        # 1) Authorization check
        if authorized_users and user not in authorized_users:
            logger.info("Unauthorized click by %s on %s", user, url)
            _post_ephemeral(
                web,
                channel=channel,
                user=user,
                text=":lock: Not authorized — this button is restricted.",
            )
            continue

        # 2) Already-scored pre-check (skip subprocess if we already have a score)
        existing = _lookup_application_by_url(url)
        if existing and existing.get("fit_score") is not None:
            score = existing["fit_score"]
            verdict = _verdict_from_score(score)
            company = existing.get("company", "?")
            position = existing.get("position", "?")
            app_id = existing.get("id")
            dash = f"http://localhost:8000/applications/{app_id}" if app_id else None
            text = (
                f":repeat: Already scored: *{position}* @ *{company}* — "
                f"Fit: *{score}* ({verdict})"
            )
            if dash:
                text += f" — <{dash}|View report>"
            _post_message(web, channel=channel, thread_ts=thread_ts, text=text)
            continue

        # 3) Ephemeral ack (within 3s — Slack requires it)
        if user:
            _post_ephemeral(
                web,
                channel=channel,
                user=user,
                text=f":hourglass_flowing_sand: Scoring queued: {url}",
            )

        # 4) Visible threaded "Scoring…" so everyone in the thread sees progress
        _post_message(
            web,
            channel=channel,
            thread_ts=thread_ts,
            text=f":mag: Scoring <{url}|this job>…",
        )

        # 5) Enqueue for the worker thread
        _job_queue.put({
            "url": url,
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
        })
        logger.info(
            "Enqueued score job: %s (qsize=%d, user=%s)",
            url, _job_queue.qsize(), user,
        )


# =============================================================================
# Listener factory + main entrypoint
# =============================================================================

def _make_listener(web: WebClient, authorized_users: list[str]):
    def _listener(client: SocketModeClient, req: SocketModeRequest) -> None:
        # Ack the envelope immediately so Slack's gateway doesn't retry
        try:
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )
        except Exception:
            logger.exception("Failed to ack socket mode envelope")

        if req.type == "interactive" and req.payload.get("type") == "block_actions":
            try:
                _on_block_actions(web, req, authorized_users)
            except Exception:
                logger.exception("Error handling block_actions")

    return _listener


def run_bot() -> int:
    """Main entrypoint. Blocks until SIGTERM/SIGINT."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    cfg = load_config().get("monitor", {}) or {}
    bot_token = cfg.get("slack_bot_token") or os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = cfg.get("slack_app_token") or os.environ.get("SLACK_APP_TOKEN", "")
    authorized_users = list(cfg.get("slack_authorized_users") or [])

    if not bot_token:
        logger.error(
            "Missing slack_bot_token in ~/.job-journal/config.yaml (monitor section). "
            "Expect a value starting with 'xoxb-'."
        )
        return 2
    if not app_token:
        logger.error(
            "Missing slack_app_token in ~/.job-journal/config.yaml (monitor section). "
            "Expect a value starting with 'xapp-'."
        )
        return 2

    if not shutil.which("claude"):
        logger.error("'claude' CLI not found in PATH. The bot cannot spawn /score runs.")
        return 2

    if authorized_users:
        logger.info("Authorization allowlist: %s", authorized_users)
    else:
        logger.warning("No slack_authorized_users configured — ANY channel member can click [Score]")

    web = WebClient(token=bot_token)
    sm = SocketModeClient(app_token=app_token, web_client=web)
    sm.socket_mode_request_listeners.append(_make_listener(web, authorized_users))

    # Start worker thread
    worker = threading.Thread(
        target=_worker_loop,
        args=(web,),
        daemon=True,
        name="score-worker",
    )
    worker.start()

    # Signal handlers for clean shutdown (via launchctl unload or Ctrl-C)
    def _handle_signal(signum, _frame):
        logger.info("Signal %d received, shutting down", signum)
        _shutdown.set()
        try:
            sm.disconnect()
        except Exception:
            logger.debug("Error during sm.disconnect()", exc_info=True)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Connecting Socket Mode…")
    try:
        sm.connect()
    except Exception:
        logger.exception("Socket Mode connect failed")
        return 1
    logger.info("Bot ready. Waiting for interactions.")

    # Block main thread; SocketModeClient runs its own internal threads
    while not _shutdown.is_set():
        time.sleep(1.0)

    worker.join(timeout=5.0)
    logger.info("Bot shutdown complete")
    return 0
