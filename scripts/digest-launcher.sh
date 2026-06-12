#!/usr/bin/env bash
# digest-launcher.sh — LaunchAgent wrapper for the daily prospect digest
#
# Called by macOS LaunchAgent (com.jj.daily-digest.plist) once a day.
# Sends the top new + backlog prospects to Slack via jj monitor digest.

echo "=== Daily digest: $(date '+%Y-%m-%d %H:%M:%S') ==="

export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "ERROR: No venv found at $PROJECT_DIR/.venv"
    exit 1
fi

if [ -z "$(command -v jj 2>/dev/null)" ]; then
    echo "ERROR: 'jj' not found in PATH"
    exit 1
fi

jj monitor digest 2>&1

EXIT_CODE=$?
echo "=== Daily digest complete: $(date '+%Y-%m-%d %H:%M:%S') (exit: $EXIT_CODE) ==="
exit $EXIT_CODE
