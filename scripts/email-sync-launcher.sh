#!/usr/bin/env bash
# email-sync-launcher.sh — LaunchAgent wrapper for jj email pair
#
# Called by macOS LaunchAgent (com.jj.email-sync.plist) every 2 hours.
# Runs the email pairing sync without Claude — just the CLI directly.
# JJ_HEADLESS=1 makes Gmail auth fail loudly instead of opening a browser.

echo "=== Email sync: $(date '+%Y-%m-%d %H:%M:%S') ==="

# Ensure PATH includes common tool locations
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

# Find project directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Activate project venv
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "ERROR: No venv found at $PROJECT_DIR/.venv"
    exit 1
fi

# Verify jj is available
JJ_PATH="$(command -v jj 2>/dev/null || true)"
if [ -z "$JJ_PATH" ]; then
    echo "ERROR: 'jj' not found in PATH"
    exit 1
fi

# Check Gmail token exists before attempting sync
if [ ! -f "$HOME/.job-journal/gmail_token.json" ]; then
    echo "SKIP: No Gmail token found. Run 'jj email setup' first."
    exit 0
fi

# Run pairing sync (active applications only, non-verbose for log cleanliness)
echo "Running jj email pair..."
JJ_HEADLESS=1 jj email pair 2>&1

EXIT_CODE=$?
echo "=== Email sync complete: $(date '+%Y-%m-%d %H:%M:%S') (exit: $EXIT_CODE) ==="
exit $EXIT_CODE
