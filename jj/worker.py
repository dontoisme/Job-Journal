"""Background worker for Job Journal task processing."""

import json
import signal
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from rich.console import Console
from rich.table import Table

from jj.config import JJ_HOME
from jj.db import (
    create_task,
    get_pending_tasks,
    get_recent_tasks,
    get_task,
    get_task_stats,
    init_database,
    log_event,
    update_task_status,
)

console = Console()

# Task handlers registry
TASK_HANDLERS: dict[str, Callable] = {}


def register_handler(task_type: str):
    """Decorator to register a task handler."""
    def decorator(func: Callable):
        TASK_HANDLERS[task_type] = func
        return func
    return decorator


# --------------------------------------------------------------------------
# Task Handlers
# --------------------------------------------------------------------------

@register_handler('email_sync')
def handle_email_sync(payload: dict) -> dict:
    """Handle email sync task - check for confirmations and updates."""
    try:
        from jj.db import (
            get_applications_for_update_check,
            get_applications_missing_confirmation,
            update_application,
            update_application_email_confirmation,
            update_application_latest_update,
        )
        from jj.gmail_checker import (
            get_gmail_service,
            search_updates,
            verify_confirmations,
        )

        service = get_gmail_service()
        if not service:
            return {'error': 'Gmail not configured', 'confirmations': 0, 'updates': 0}

        results = {
            'confirmations_found': 0,
            'updates_found': 0,
            'applications_checked': 0,
        }

        # Check for confirmation emails
        unconfirmed = get_applications_missing_confirmation()
        if unconfirmed:
            confirmations = verify_confirmations(service, unconfirmed)
            for app_id, result in confirmations.items():
                if result.confirmed:
                    update_application_email_confirmation(
                        app_id,
                        confirmed=True,
                        confirmed_at=result.confirmed_at,
                        email_id=result.email_id,
                    )
                    log_event(
                        'email_confirmed',
                        entity_type='application',
                        entity_id=app_id,
                        new_value={'email_id': result.email_id},
                    )
                    results['confirmations_found'] += 1

        # Check for updates
        days = payload.get('days', 7)
        to_check = get_applications_for_update_check()
        if to_check:
            updates = search_updates(service, to_check, days=days)
            for app_id, update in updates.items():
                update_application_latest_update(
                    app_id,
                    update_type=update.update_type,
                    update_at=update.update_at,
                    subject=update.subject,
                    email_id=update.email_id,
                )

                # Auto-update status based on email type
                if update.update_type == 'interview':
                    update_application(app_id, status='interview')
                elif update.update_type == 'rejection':
                    update_application(app_id, status='rejected')

                log_event(
                    'email_update_received',
                    entity_type='application',
                    entity_id=app_id,
                    new_value={
                        'update_type': update.update_type,
                        'subject': update.subject,
                    },
                )
                results['updates_found'] += 1

        results['applications_checked'] = len(unconfirmed) + len(to_check)
        return results

    except ImportError:
        return {'error': 'Gmail module not available', 'confirmations': 0, 'updates': 0}
    except Exception as e:
        return {'error': str(e), 'confirmations': 0, 'updates': 0}


@register_handler('schedule_email_sync')
def handle_schedule_email_sync(payload: dict) -> dict:
    """Schedule the next email sync task."""
    # Schedule next sync in 1 hour
    next_run = (datetime.now() + timedelta(hours=1)).isoformat()
    task_id = create_task('email_sync', priority=5, scheduled_for=next_run)
    return {'scheduled_task_id': task_id, 'scheduled_for': next_run}


@register_handler('workflow_apply')
def handle_workflow_apply(payload: dict) -> dict:
    """Handle apply workflow - placeholder for web-triggered applies."""
    # This would coordinate with Claude Code via subprocess or API
    # For now, return a status indicating manual action needed
    return {
        'status': 'manual_required',
        'message': 'Apply workflow requires Claude Code terminal. Use /apply command.',
        'application_id': payload.get('application_id'),
    }


# --------------------------------------------------------------------------
# Worker Process
# --------------------------------------------------------------------------

class Worker:
    """Background task processor."""

    def __init__(self, poll_interval: int = 5):
        self.poll_interval = poll_interval
        self.running = False
        self.processed = 0
        self.errors = 0

    def process_task(self, task: dict) -> bool:
        """Process a single task. Returns True if successful."""
        task_id = task['id']
        task_type = task['task_type']
        payload = json.loads(task['payload']) if task['payload'] else {}

        handler = TASK_HANDLERS.get(task_type)
        if not handler:
            update_task_status(task_id, 'failed', error=f'Unknown task type: {task_type}')
            return False

        # Mark as running
        update_task_status(task_id, 'running')

        try:
            result = handler(payload)
            update_task_status(task_id, 'completed', result=result)
            log_event(
                'task_completed',
                entity_type='task',
                entity_id=task_id,
                new_value={'result': result},
            )
            return True
        except Exception as e:
            error_msg = str(e)
            update_task_status(task_id, 'failed', error=error_msg)
            log_event(
                'task_failed',
                entity_type='task',
                entity_id=task_id,
                new_value={'error': error_msg},
            )
            return False

    def run_once(self) -> int:
        """Process pending tasks once. Returns number processed."""
        tasks = get_pending_tasks(limit=10)
        processed = 0

        for task in tasks:
            success = self.process_task(task)
            processed += 1
            if success:
                self.processed += 1
            else:
                self.errors += 1

        return processed

    def run(self):
        """Run the worker loop."""
        self.running = True
        console.print("[green]Worker started[/green]")

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            console.print("\n[yellow]Shutting down worker...[/yellow]")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while self.running:
            try:
                processed = self.run_once()
                if processed > 0:
                    console.print(f"[dim]Processed {processed} tasks[/dim]")
            except Exception as e:
                console.print(f"[red]Worker error: {e}[/red]")

            # Sleep between polls
            for _ in range(self.poll_interval):
                if not self.running:
                    break
                time.sleep(1)

        console.print(f"[green]Worker stopped. Processed: {self.processed}, Errors: {self.errors}[/green]")


# --------------------------------------------------------------------------
# CLI Interface
# --------------------------------------------------------------------------

def start_worker(poll_interval: int = 5, daemon: bool = False):
    """Start the background worker."""
    init_database()

    if daemon:
        # Daemonize (Unix only)
        import os
        pid = os.fork()
        if pid > 0:
            # Parent process
            pid_file = JJ_HOME / 'worker.pid'
            pid_file.write_text(str(pid))
            console.print(f"[green]Worker started in background (PID: {pid})[/green]")
            return

    worker = Worker(poll_interval=poll_interval)
    worker.run()


def stop_worker():
    """Stop the background worker."""
    import os
    import signal

    pid_file = JJ_HOME / 'worker.pid'
    if not pid_file.exists():
        console.print("[yellow]No worker PID file found[/yellow]")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink()
        console.print(f"[green]Stopped worker (PID: {pid})[/green]")
    except ProcessLookupError:
        console.print("[yellow]Worker process not found[/yellow]")
        pid_file.unlink()
    except Exception as e:
        console.print(f"[red]Error stopping worker: {e}[/red]")


def worker_status():
    """Show worker status and recent tasks."""
    import os

    pid_file = JJ_HOME / 'worker.pid'

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            console.print(f"[green]Worker running (PID: {pid})[/green]")
        except (ProcessLookupError, ValueError):
            console.print("[yellow]Worker not running (stale PID file)[/yellow]")
    else:
        console.print("[yellow]Worker not running[/yellow]")

    # Show task stats
    stats = get_task_stats()
    console.print("\n[bold]Task Stats (last 24h):[/bold]")
    console.print(f"  Pending: {stats['pending']}")
    console.print(f"  Running: {stats['running']}")
    console.print(f"  Completed: {stats['completed']}")
    console.print(f"  Failed: {stats['failed']}")

    # Show recent tasks
    recent = get_recent_tasks(limit=10)
    if recent:
        console.print("\n[bold]Recent Tasks:[/bold]")
        table = Table(show_header=True)
        table.add_column("ID", width=6)
        table.add_column("Type", width=20)
        table.add_column("Status", width=10)
        table.add_column("Created", width=20)

        for task in recent:
            status_style = {
                'pending': 'yellow',
                'running': 'blue',
                'completed': 'green',
                'failed': 'red',
            }.get(task['status'], 'white')

            table.add_row(
                str(task['id']),
                task['task_type'],
                f"[{status_style}]{task['status']}[/{status_style}]",
                task['created_at'][:16] if task['created_at'] else '-',
            )

        console.print(table)


def schedule_email_sync(hours: int = 1):
    """Schedule recurring email sync."""
    init_database()

    # Create immediate sync task
    task_id = create_task('email_sync', priority=5)
    console.print(f"[green]Created email sync task (ID: {task_id})[/green]")

    # Schedule next sync
    next_run = (datetime.now() + timedelta(hours=hours)).isoformat()
    create_task(
        'schedule_email_sync',
        priority=1,
        scheduled_for=next_run,
    )
    console.print(f"[dim]Next sync scheduled for {next_run}[/dim]")


def run_task_now(task_type: str, payload: Optional[dict] = None):
    """Run a task immediately (for testing/CLI)."""
    init_database()

    task_id = create_task(task_type, payload=payload, priority=10)
    console.print(f"[dim]Created task {task_id}[/dim]")

    # Process it immediately
    task = get_task(task_id)
    if task:
        worker = Worker()
        worker.process_task(task)

        # Show result
        task = get_task(task_id)
        if task['status'] == 'completed':
            result = json.loads(task['result']) if task['result'] else {}
            console.print("[green]Task completed:[/green]")
            console.print(result)
        else:
            console.print(f"[red]Task failed: {task['error']}[/red]")
