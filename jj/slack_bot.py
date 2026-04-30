"""Slack Socket Mode bot for jj — handles [Go] button clicks.

Listens for block_actions interactions from the Slack workspace via
Socket Mode (no public endpoint required). When the user clicks a
[Go] button on a job notification, the bot:

  1. Validates the clicker against slack_authorized_users
  2. Pre-checks the DB for an existing score + resume
  3. Enqueues the job for a single worker thread
  4. Orchestrates a 4-phase pipeline:
     Phase 1: /slack-apply (score + 2 candidate resumes)
     Phase 2: /resume-eval via Opus 4.7 (compare + recommend)
     Phase 3: /resume-refine (apply improvements, generate final PDF)
     Phase 4: /resume-eval --final via Opus 4.7 (final scoring)
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
SCORE_TIMEOUT_SEC = 600  # 10-minute hard limit (kept for reference)
APPLY_TIMEOUT_SEC = 900  # 15-minute limit for score + apply chain
ACTION_ID = "score_job"
WORKER_POLL_INTERVAL = 1.0
ALLOWED_TOOLS = "Bash,WebFetch,WebSearch,Read,Write,Grep,Glob"

# Pipeline phase timeouts (seconds)
PHASE_TIMEOUTS = {
    "phase1": 900,   # 15 min: score + 2 candidate resumes
    "phase2": 600,   # 10 min: Opus 4.7 eval + WebSearch
    "phase3": 600,   # 10 min: apply improvements + generate final
    "phase4": 300,   # 5 min: final eval (no WebSearch)
}
PIPELINE_EVAL_MODEL = "opus"

# --- Log verb prefixes (Rich markup) ---
# Primary events — designed to pop visually:
V_SPAWN  = "[bold cyan]▶ SPAWN[/bold cyan]"   # subprocess kicked off
V_DONE   = "[bold green]✓ DONE [/bold green]"  # subprocess returned success
V_FAIL   = "[bold red]✗ FAIL [/bold red]"      # subprocess returned failure
V_READY  = "[bold green]◉ READY[/bold green]"  # bot connected + listening
# Secondary events — lower contrast:
V_CLICK  = "[cyan]· CLICK[/cyan]"
V_QUEUE  = "[cyan]· QUEUE[/cyan]"
V_SKIP   = "[yellow]· SKIP [/yellow]"          # already scored, pre-check hit
V_DENY   = "[red]⚠ DENY [/red]"                # unauthorized user
V_STOP   = "[dim]◯ STOP [/dim]"                # shutdown signal / worker exit
V_NOTE   = "[dim]·[/dim]"                       # informational / bookkeeping
V_WARN   = "[bold yellow]⚠ WARN [/bold yellow]"


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
    """Fetch the latest application row matching `job_url`, including
    whether it has a full /score run against it.

    Adds a derived field `has_full_score` (bool). We detect this by the
    `notes` prefix rather than the `evaluation_reports` table because
    the committed /score skill writes notes like "Fit: 82% (Strong Fit).
    ..." but does NOT write to evaluation_reports — that's in a WIP
    version of the skill. A bare `notes` starting with "Title Fit:"
    means the row is just the hourly scan's title pre-filter and the
    button should actually run /score.
    """
    from jj.db import get_connection, init_database

    init_database()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, company, position, fit_score, notes, status, "
            "resume_id, rj_before, rj_after "
            "FROM applications WHERE job_url = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (url,),
        ).fetchone()
        if not row:
            return None
        app = dict(row)
        notes = (app.get("notes") or "").strip()
        # "Title Fit: N ..." = bare title pre-filter from scan-apis.
        # "Fit: N% ..." = real corpus run from /score.
        # Empty / unknown = treat as not fully scored.
        app["has_full_score"] = bool(notes) and not notes.startswith("Title Fit:")
        return app


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
# Subprocess — spawn headless Claude for scoring / score+apply
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
    logger.info("%s /score %s", V_SPAWN, url)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SCORE_TIMEOUT_SEC,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        logger.error("%s timeout after %ds", V_FAIL, SCORE_TIMEOUT_SEC)
        return 124, "", f"Timed out after {SCORE_TIMEOUT_SEC}s"
    except Exception as e:
        logger.exception("Subprocess launch failed")
        return 1, "", str(e)


def _run_slack_apply_subprocess(url: str) -> tuple[int, str, str]:
    """Spawn the headless /slack-apply run (score + resume). Returns (returncode, stdout, stderr)."""
    claude_path = shutil.which("claude")
    if not claude_path:
        return 127, "", "'claude' not found in PATH"

    cmd = [
        claude_path,
        "-p",
        f"/slack-apply {url}",
        "--allowedTools",
        ALLOWED_TOOLS,
    ]
    logger.info("%s /slack-apply %s", V_SPAWN, url)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=APPLY_TIMEOUT_SEC,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        logger.error("%s timeout after %ds", V_FAIL, APPLY_TIMEOUT_SEC)
        return 124, "", f"Timed out after {APPLY_TIMEOUT_SEC}s"
    except Exception as e:
        logger.exception("Subprocess launch failed")
        return 1, "", str(e)


def _run_phase_subprocess(
    prompt: str,
    timeout: int,
    model: Optional[str] = None,
) -> tuple[int, str, str]:
    """Spawn a headless Claude CLI subprocess for one pipeline phase."""
    claude_path = shutil.which("claude")
    if not claude_path:
        return 127, "", "'claude' not found in PATH"

    cmd = [claude_path, "-p", prompt, "--allowedTools", ALLOWED_TOOLS]
    if model:
        cmd.extend(["--model", model])

    logger.info("%s %s%s", V_SPAWN, prompt.split()[0], f" (model={model})" if model else "")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        logger.error("%s timeout after %ds", V_FAIL, timeout)
        return 124, "", f"Timed out after {timeout}s"
    except Exception as e:
        logger.exception("Subprocess launch failed")
        return 1, "", str(e)


def _parse_app_id(stdout: str) -> Optional[int]:
    """Extract App ID from skill stdout."""
    import re
    match = re.search(r"App ID:\s*(\d+)", stdout)
    return int(match.group(1)) if match else None


def _degrade_pipeline(app_id: int, phase: int, error: str = "") -> None:
    """Graceful degradation: link the best available resume when a phase fails."""
    from jj.db import get_pipeline_run_by_app, update_pipeline_run, update_application

    pipeline = get_pipeline_run_by_app(app_id)
    if not pipeline:
        return

    run_id = pipeline["id"]
    status = f"degraded_phase{phase}"

    if phase == 2:
        best_id = pipeline.get("resume_strict_id")
    elif phase == 3:
        base = pipeline.get("eval_recommended_base", "strict")
        best_id = (
            pipeline.get("resume_strict_id") if base == "strict"
            else pipeline.get("resume_freeform_id") or pipeline.get("resume_strict_id")
        )
    elif phase == 4:
        best_id = pipeline.get("resume_final_id")
    else:
        best_id = None

    update_pipeline_run(
        run_id,
        pipeline_status=status,
        phase_reached=phase - 1,
        error=error,
        completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    if best_id:
        update_application(app_id, resume_id=best_id)

    logger.warning(
        "%s pipeline degraded at phase %d (app %d), using resume %s",
        V_WARN, phase, app_id, best_id,
    )


def _run_pipeline(url: str) -> tuple[int, str, str]:
    """Orchestrate the 4-phase resume evaluation pipeline.

    Returns (returncode, stdout, stderr) from the perspective of the
    overall pipeline. rc=0 means at least Phase 1 succeeded; the
    pipeline_runs table has the authoritative status.
    """
    t0 = time.time()

    # Phase 1: Score + generate 2 candidate resumes
    logger.info("%s Phase 1/4: score + candidate resumes", V_NOTE)
    rc, stdout, stderr = _run_phase_subprocess(
        f"/slack-apply {url}", timeout=PHASE_TIMEOUTS["phase1"],
    )
    if rc != 0:
        return rc, stdout, stderr

    app_id = _parse_app_id(stdout)
    if not app_id:
        logger.error("%s Could not parse App ID from Phase 1 output", V_FAIL)
        return rc, stdout, stderr

    # Check if score was below threshold (no pipeline started)
    if "RESULT: SCORE_ONLY" in stdout:
        logger.info("%s Below threshold, pipeline not started", V_NOTE)
        return 0, stdout, stderr

    elapsed = int(time.time() - t0)
    logger.info("%s Phase 1 done in %ds (app %d)", V_DONE, elapsed, app_id)

    # Phase 2: Opus 4.7 evaluation
    logger.info("%s Phase 2/4: Opus evaluation", V_NOTE)
    rc2, stdout2, stderr2 = _run_phase_subprocess(
        f"/resume-eval {app_id}",
        timeout=PHASE_TIMEOUTS["phase2"],
        model=PIPELINE_EVAL_MODEL,
    )
    if rc2 != 0:
        logger.warning("%s Phase 2 failed (rc=%d), degrading", V_WARN, rc2)
        _degrade_pipeline(app_id, phase=2, error=stderr2[-500:] if stderr2 else "")
        return 0, stdout, stderr

    elapsed = int(time.time() - t0)
    logger.info("%s Phase 2 done in %ds total", V_DONE, elapsed)

    # Phase 3: Apply improvements, generate final resume
    logger.info("%s Phase 3/4: refinement", V_NOTE)
    rc3, stdout3, stderr3 = _run_phase_subprocess(
        f"/resume-refine {app_id}", timeout=PHASE_TIMEOUTS["phase3"],
    )
    if rc3 != 0:
        logger.warning("%s Phase 3 failed (rc=%d), degrading", V_WARN, rc3)
        _degrade_pipeline(app_id, phase=3, error=stderr3[-500:] if stderr3 else "")
        return 0, stdout, stderr

    elapsed = int(time.time() - t0)
    logger.info("%s Phase 3 done in %ds total", V_DONE, elapsed)

    # Phase 4: Final evaluation
    logger.info("%s Phase 4/4: final evaluation", V_NOTE)
    rc4, stdout4, stderr4 = _run_phase_subprocess(
        f"/resume-eval {app_id} --final",
        timeout=PHASE_TIMEOUTS["phase4"],
        model=PIPELINE_EVAL_MODEL,
    )
    if rc4 != 0:
        logger.warning("%s Phase 4 failed (rc=%d), degrading", V_WARN, rc4)
        _degrade_pipeline(app_id, phase=4, error=stderr4[-500:] if stderr4 else "")
        return 0, stdout, stderr

    elapsed = int(time.time() - t0)

    # Update application fit_score with the final pipeline score
    _promote_final_score(app_id)

    logger.info("%s Pipeline complete in %ds (app %d)", V_DONE, elapsed, app_id)
    return 0, stdout, stderr


def _promote_final_score(app_id: int) -> None:
    """Update the application's fit_score with the pipeline's final score."""
    from jj.db import get_pipeline_run_by_app, update_application

    pipeline = get_pipeline_run_by_app(app_id)
    if not pipeline:
        return
    final_score = pipeline.get("final_score")
    if final_score is not None:
        update_application(app_id, fit_score=final_score)
        logger.info(
            "%s promoted final score %d to app %d",
            V_NOTE, final_score, app_id,
        )


def _lookup_pipeline_result(app_id: int) -> Optional[dict[str, Any]]:
    """Fetch pipeline run data for the Slack result message."""
    from jj.db import get_pipeline_run_by_app

    return get_pipeline_run_by_app(app_id)


def _format_result_message(
    url: str,
    app: Optional[dict[str, Any]],
    returncode: int,
    stderr_tail: str,
) -> str:
    """Build the Slack text for a completed (or failed) score+apply job."""
    if returncode == 124:
        return (
            f":warning: Score+Apply timed out after {APPLY_TIMEOUT_SEC // 60} min. "
            f"<{url}|View JD>"
        )
    if returncode != 0 or app is None:
        tail = (stderr_tail or "(no error output)").strip()[-300:]
        return (
            f":x: Score+Apply failed (exit {returncode}) for <{url}|this job>.\n"
            f"```{tail}```"
        )
    score = app.get("fit_score")
    verdict = _verdict_from_score(score)
    company = app.get("company", "?")
    position = app.get("position", "?")
    app_id = app.get("id")
    resume_id = app.get("resume_id")
    rj_before = app.get("rj_before")
    rj_after = app.get("rj_after")
    dash = f"http://localhost:8000/prospects/{app_id}" if app_id else None

    line = (
        f":white_check_mark: *{position}* @ *{company}* — "
        f"Fit: *{score}* ({verdict})"
    )

    # Check for pipeline data
    pipeline = _lookup_pipeline_result(app_id) if app_id else None

    if pipeline and pipeline.get("pipeline_status", "").startswith(("completed", "degraded")):
        final_score = pipeline.get("final_score")
        final_verdict = pipeline.get("final_verdict", "")
        score_strict = pipeline.get("eval_score_strict")
        score_freeform = pipeline.get("eval_score_freeform")
        status = pipeline["pipeline_status"]

        scores_line = []
        if score_strict is not None:
            scores_line.append(f"Strict: {score_strict}")
        if score_freeform is not None:
            scores_line.append(f"Freeform: {score_freeform}")
        if final_score is not None:
            scores_line.append(f"*Final: {final_score}*")
        if scores_line:
            line += f"\n:bar_chart: RJ Scores: {' | '.join(scores_line)}"

        if final_verdict:
            line += f" ({final_verdict})"

        if status.startswith("degraded"):
            phase = pipeline.get("phase_reached", "?")
            line += f"\n:warning: Pipeline degraded at phase {phase}/4"

        if resume_id:
            doc_url = _lookup_resume_doc_url(resume_id)
            line += "\n:page_facing_up: Final resume generated"
            if doc_url:
                line += f" — <{doc_url}|Google Doc>"
            line += "\n:file_folder: `~/Documents/Resumes/.../slack/{company}/`"

    elif resume_id:
        rj_text = ""
        if rj_before is not None and rj_after is not None:
            rj_text = f" | RJ: {rj_before}→{rj_after}"
        doc_url = _lookup_resume_doc_url(resume_id)
        line += f"\n:page_facing_up: Resume generated{rj_text}"
        if doc_url:
            line += f" — <{doc_url}|Google Doc>"
        line += "\n:file_folder: `~/Documents/Resumes/.../slack/{company}/`"
    elif score is not None and score < 65:
        line += "\n_Below 65 threshold — no resume generated_"

    if dash:
        line += f"\n<{dash}|View details>"
    return line


def _lookup_resume_doc_url(resume_id: int) -> Optional[str]:
    """Fetch the Google Doc URL for a generated resume."""
    from jj.db import get_connection, init_database

    init_database()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT google_doc_id FROM resumes WHERE id = ?", (resume_id,),
        ).fetchone()
        if row:
            doc_id = dict(row).get("google_doc_id")
            if doc_id:
                return f"https://docs.google.com/document/d/{doc_id}/edit"
    return None


# =============================================================================
# Worker loop — single thread, drains the queue serially
# =============================================================================

def _worker_loop(web: WebClient) -> None:
    logger.info("%s Score worker started", V_NOTE)
    while not _shutdown.is_set():
        try:
            job = _job_queue.get(timeout=WORKER_POLL_INTERVAL)
        except queue.Empty:
            continue
        try:
            url = job["url"]
            channel = job["channel"]
            thread_ts = job.get("thread_ts")

            t0 = time.time()
            rc, stdout, stderr = _run_pipeline(url)
            elapsed = int(time.time() - t0)

            app = _lookup_application_by_url(url) if rc == 0 else None

            if rc == 0 and app is not None:
                score = app.get("fit_score")
                verdict = _verdict_from_score(score)
                company = app.get("company", "?")
                position = app.get("position", "?")
                pipeline = _lookup_pipeline_result(app.get("id")) if app.get("id") else None
                p_status = pipeline.get("pipeline_status", "") if pipeline else ""
                logger.info(
                    "%s %3ds  %s @ %s → Fit:%s (%s) pipeline=%s",
                    V_DONE, elapsed, position, company, score, verdict, p_status or "n/a",
                )
            elif rc == 124:
                logger.warning("%s %3ds  timeout  %s", V_FAIL, elapsed, url)
            else:
                logger.warning("%s %3ds  rc=%d  %s", V_FAIL, elapsed, rc, url)

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
    logger.info("%s Score worker exiting", V_STOP)


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

        logger.info("%s user=%s  %s", V_CLICK, user, url)

        # 1) Authorization check
        if authorized_users and user not in authorized_users:
            logger.info("%s user=%s not in allowlist", V_DENY, user)
            _post_ephemeral(
                web,
                channel=channel,
                user=user,
                text=":lock: Not authorized — this button is restricted.",
            )
            continue

        # 2) Already-processed pre-check — only skip if a completed
        #    pipeline exists, or score is below threshold. Old single-pass
        #    results (resume_id but no pipeline) are allowed to re-run.
        existing = _lookup_application_by_url(url)
        if existing and existing.get("has_full_score"):
            score = existing.get("fit_score")
            app_id = existing.get("id")
            pipeline = _lookup_pipeline_result(app_id) if app_id else None
            p_done = pipeline and pipeline.get("pipeline_status", "").startswith(("completed", "degraded"))
            # Skip only if: pipeline already completed, or score < 65 (no resume expected)
            if p_done or (score is not None and score < 65):
                resume_id = existing.get("resume_id")
                verdict = _verdict_from_score(score)
                company = existing.get("company", "?")
                position = existing.get("position", "?")
                dash = f"http://localhost:8000/prospects/{app_id}" if app_id else None
                logger.info(
                    "%s already processed: %s @ %s → Fit:%s (%s) resume=%s pipeline=%s",
                    V_SKIP, position, company, score, verdict, resume_id,
                    pipeline.get("pipeline_status") if pipeline else "n/a",
                )
                text = (
                    f":repeat: Already processed: *{position}* @ *{company}* — "
                    f"Fit: *{score}* ({verdict})"
                )
                if resume_id:
                    doc_url = _lookup_resume_doc_url(resume_id)
                    if doc_url:
                        text += f"\n:page_facing_up: <{doc_url}|Resume>"
                if dash:
                    text += f" — <{dash}|View details>"
                _post_message(web, channel=channel, thread_ts=thread_ts, text=text)
                continue

        # 3) Ephemeral ack (within 3s — Slack requires it)
        if user:
            _post_ephemeral(
                web,
                channel=channel,
                user=user,
                text=f":hourglass_flowing_sand: Pipeline queued (score → eval → refine → final): {url}",
            )

        # 4) Visible threaded progress message
        _post_message(
            web,
            channel=channel,
            thread_ts=thread_ts,
            text=f":mag: Starting 4-phase pipeline for <{url}|this job>…",
        )

        # 5) Enqueue for the worker thread
        _job_queue.put({
            "url": url,
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
        })
        logger.info("%s qsize=%d  %s", V_QUEUE, _job_queue.qsize(), url)


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


def _setup_logging() -> None:
    """Configure logging with Rich color formatter.

    Uses `force_terminal=True` so ANSI codes are written even when stdout
    is redirected to a file (LaunchAgent's StandardOutPath). Tailing the
    log file with `tail -f` will render the colors correctly.
    """
    try:
        from rich.console import Console
        from rich.logging import RichHandler
    except ImportError:
        # Fall back to plain logging if rich isn't available
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            stream=sys.stdout,
        )
        return

    # force_terminal=True → ANSI codes even when stdout is a file
    # width=200 → don't wrap long lines (URLs etc.)
    console = Console(
        file=sys.stdout,
        force_terminal=True,
        color_system="truecolor",
        width=200,
        soft_wrap=True,
    )
    handler = RichHandler(
        console=console,
        show_path=False,
        show_level=False,
        show_time=True,
        markup=True,
        rich_tracebacks=True,
        omit_repeated_times=False,
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%H:%M:%S]",
        handlers=[handler],
    )
    # Quiet slack_sdk's chatty socket_mode logs unless something's wrong
    logging.getLogger("slack_sdk.socket_mode.builtin.client").setLevel(logging.WARNING)


def run_bot() -> int:
    """Main entrypoint. Blocks until SIGTERM/SIGINT."""
    _setup_logging()

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
        logger.info("%s Allowlist: %s", V_NOTE, authorized_users)
    else:
        logger.warning("%s No allowlist — any channel member can click [Score]", V_WARN)

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
        logger.info("%s signal %d received", V_STOP, signum)
        _shutdown.set()
        try:
            sm.disconnect()
        except Exception:
            logger.debug("Error during sm.disconnect()", exc_info=True)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("%s Connecting Socket Mode…", V_NOTE)
    try:
        sm.connect()
    except Exception:
        logger.exception("Socket Mode connect failed")
        return 1
    logger.info("%s Listening for [Go] button clicks", V_READY)

    # Block main thread; SocketModeClient runs its own internal threads
    while not _shutdown.is_set():
        time.sleep(1.0)

    worker.join(timeout=5.0)
    logger.info("%s Bot shutdown complete", V_STOP)
    return 0
