#!/usr/bin/env bash
# dashboard-launcher.sh — LaunchAgent wrapper for the jj web dashboard
#
# Called by macOS LaunchAgent (com.jj.dashboard.plist) at load and whenever
# the dashboard crashes. Activates the project venv, ensures jj is on PATH,
# then exec's `jj serve --no-open` (exec so SIGTERM from launchctl unload
# reaches the uvicorn process directly).

echo "=== Dashboard start: $(date '+%Y-%m-%d %H:%M:%S') ==="

export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
echo "Project dir: $PROJECT_DIR"

if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    echo "Activating venv..."
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "ERROR: No venv found at $PROJECT_DIR/.venv"
    exit 1
fi

[ -f "$HOME/.zprofile" ] && source "$HOME/.zprofile" 2>/dev/null || true
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null || true

mkdir -p "$HOME/.job-journal/logs"

JJ_PATH="$(command -v jj 2>/dev/null || true)"
if [ -z "$JJ_PATH" ]; then
    echo "ERROR: 'jj' not found in PATH"
    echo "PATH=$PATH"
    exit 1
fi
echo "jj: $JJ_PATH"

cd "$PROJECT_DIR"

# exec so SIGTERM from launchctl reaches uvicorn, not bash
exec jj serve --no-open
