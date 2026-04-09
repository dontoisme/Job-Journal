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

# Step 1: Always run the fast API scan first (~30 seconds)
# This hits Greenhouse, Lever, and Ashby APIs directly for quick discovery
cd "$PROJECT_DIR"
echo "Running quick API scan..."
jj monitor scan-apis 2>&1
API_EXIT=$?
echo "API scan exit: $API_EXIT"

# Step 2: Run full /monitor only at 6am and 6pm (deep scan with corpus scoring + resume gen)
# At other hours, the quick API scan above is sufficient
CURRENT_HOUR=$(date '+%H')
if [ "$CURRENT_HOUR" = "06" ] || [ "$CURRENT_HOUR" = "18" ]; then
    echo "Full monitor run (hour $CURRENT_HOUR)..."
    # -p: non-interactive output mode (prints result, no TUI)
    # --allowedTools: restrict to only the tools the monitor needs
    claude -p "Run /monitor" \
        --allowedTools "Bash,WebFetch,Read,Grep,Glob" \
        2>&1
    FULL_EXIT=$?
    echo "Full monitor exit: $FULL_EXIT"
else
    echo "Skipping full monitor (hour $CURRENT_HOUR — only runs at 06 and 18)"
    FULL_EXIT=0
fi

EXIT_CODE=$((API_EXIT > FULL_EXIT ? API_EXIT : FULL_EXIT))
echo "=== Monitor complete: $(date '+%Y-%m-%d %H:%M:%S') (exit: $EXIT_CODE) ==="
exit $EXIT_CODE
