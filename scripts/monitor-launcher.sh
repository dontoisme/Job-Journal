#!/usr/bin/env bash
# monitor-launcher.sh — LaunchAgent wrapper for jj monitor
#
# Called by macOS LaunchAgent (com.jj.monitor.plist) at scheduled times.
# Sets up the environment and runs claude -p to execute the /monitor skill.

set -euo pipefail

# Timestamp for logging
echo "=== Monitor run: $(date '+%Y-%m-%d %H:%M:%S') ==="

# Ensure PATH includes common tool locations + project venv
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

# Find project directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Activate project venv if it exists (puts jj on PATH)
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# Source user profile for nvm, pyenv, etc. if available
if [ -f "$HOME/.zprofile" ]; then
    source "$HOME/.zprofile" 2>/dev/null || true
fi
if [ -f "$HOME/.zshrc" ]; then
    source "$HOME/.zshrc" 2>/dev/null || true
fi

# Ensure logs directory exists
mkdir -p "$HOME/.job-journal/logs"

# Verify claude is available
if ! command -v claude &>/dev/null; then
    echo "ERROR: 'claude' not found in PATH"
    echo "PATH=$PATH"
    exit 1
fi

# Verify jj is available
if ! command -v jj &>/dev/null; then
    echo "ERROR: 'jj' not found in PATH"
    echo "PATH=$PATH"
    exit 1
fi

# Run the monitor skill via headless Claude Code
# --print: non-interactive output mode
# --allowedTools: restrict to only the tools the monitor needs
claude --print \
    -p "Run /monitor" \
    --cwd "$PROJECT_DIR" \
    --allowedTools "Bash(python3*),Bash(jj*),WebFetch,Read,Grep,Glob" \
    2>&1

EXIT_CODE=$?

echo "=== Monitor complete: $(date '+%Y-%m-%d %H:%M:%S') (exit: $EXIT_CODE) ==="
exit $EXIT_CODE
