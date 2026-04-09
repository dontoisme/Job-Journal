#!/usr/bin/env bash
# slack-bot-launcher.sh — LaunchAgent wrapper for the jj Slack Socket Mode bot
#
# Called by macOS LaunchAgent (com.jj.slack-bot.plist) at load and whenever
# the bot crashes. Activates the project venv, ensures claude + jj are on
# PATH, then exec's `jj monitor bot-run` (exec so SIGTERM from `launchctl
# unload` reaches the Python process directly instead of the bash wrapper).

echo "=== Slack bot start: $(date '+%Y-%m-%d %H:%M:%S') ==="

# Ensure PATH includes common tool locations + project venv
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

# Find project directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
echo "Project dir: $PROJECT_DIR"

# Activate project venv if it exists (puts jj on PATH and uses correct python)
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    echo "Activating venv..."
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "ERROR: No venv found at $PROJECT_DIR/.venv"
    exit 1
fi

# Source user profile for nvm, pyenv, etc. so `claude` resolves
[ -f "$HOME/.zprofile" ] && source "$HOME/.zprofile" 2>/dev/null || true
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null || true

# Ensure logs directory exists (LaunchAgent plist writes here)
mkdir -p "$HOME/.job-journal/logs"

# Verify jj + claude are available
JJ_PATH="$(command -v jj 2>/dev/null || true)"
CLAUDE_PATH="$(command -v claude 2>/dev/null || true)"
if [ -z "$JJ_PATH" ]; then
    echo "ERROR: 'jj' not found in PATH"
    echo "PATH=$PATH"
    exit 1
fi
if [ -z "$CLAUDE_PATH" ]; then
    echo "ERROR: 'claude' not found in PATH — bot cannot spawn /score subprocesses"
    echo "PATH=$PATH"
    exit 1
fi
echo "jj:     $JJ_PATH"
echo "claude: $CLAUDE_PATH"

cd "$PROJECT_DIR"

# exec so SIGTERM from launchctl reaches the Python process, not bash
exec jj monitor bot-run
