#!/usr/bin/env bash
# monitor-launcher.sh — LaunchAgent wrapper for jj monitor
#
# Called by macOS LaunchAgent (com.jj.monitor.plist) at scheduled times.
# Sets up the environment and runs claude -p to execute the /monitor skill.

# Timestamp for logging
echo "=== Monitor run: $(date '+%Y-%m-%d %H:%M:%S') ==="

# Ensure PATH includes common tool locations + project venv
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

# Find project directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
echo "Project dir: $PROJECT_DIR"

# Activate project venv if it exists (puts jj on PATH)
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    echo "Activating venv..."
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "WARNING: No venv found at $PROJECT_DIR/.venv"
fi

# Source user profile for nvm, pyenv, etc. if available
[ -f "$HOME/.zprofile" ] && source "$HOME/.zprofile" 2>/dev/null || true
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null || true

# Ensure logs directory exists
mkdir -p "$HOME/.job-journal/logs"

# Verify claude is available
CLAUDE_PATH="$(command -v claude 2>/dev/null || true)"
if [ -z "$CLAUDE_PATH" ]; then
    echo "ERROR: 'claude' not found in PATH"
    echo "PATH=$PATH"
    exit 1
fi
echo "claude: $CLAUDE_PATH"

# Verify jj is available
JJ_PATH="$(command -v jj 2>/dev/null || true)"
if [ -z "$JJ_PATH" ]; then
    echo "ERROR: 'jj' not found in PATH"
    echo "PATH=$PATH"
    exit 1
fi
echo "jj: $JJ_PATH"

# Run the monitor skill via headless Claude Code
# -p: non-interactive output mode (prints result, no TUI)
# --allowedTools: restrict to only the tools the monitor needs
cd "$PROJECT_DIR"
echo "Launching claude -p from $(pwd)..."
claude -p "Run /monitor" \
    --allowedTools "Bash,WebFetch,Read,Grep,Glob" \
    2>&1

EXIT_CODE=$?
echo "=== Monitor complete: $(date '+%Y-%m-%d %H:%M:%S') (exit: $EXIT_CODE) ==="
exit $EXIT_CODE
