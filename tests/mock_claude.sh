#!/bin/bash
# Mock Claude CLI for ClawX tests.
#
# Behavior:
#   - Logs every event to $MOCK_LOG (env var, defaults to /tmp/mock_claude.log)
#   - Echoes received stdin lines as "RECV: <line>" to the log
#   - Reacts to special commands: EXIT (clean exit 0), CRASH (exit 1)
#   - Handles SIGTERM/SIGINT cleanly
#   - Stays alive forever otherwise (so ClawX sees it as healthy)

LOG="${MOCK_LOG:-/tmp/mock_claude.log}"
mkdir -p "$(dirname "$LOG")"

echo "MOCK_STARTED pid=$$ args=$*" >> "$LOG"
echo "MOCK_CWD $(pwd)" >> "$LOG"

cleanup() {
    echo "MOCK_TERM pid=$$" >> "$LOG"
    exit 0
}
trap cleanup TERM INT

while IFS= read -r line; do
    # Strip carriage returns from PTY
    line="${line%$'\r'}"
    echo "RECV: $line" >> "$LOG"

    case "$line" in
        EXIT)
            echo "MOCK_EXIT_CLEAN" >> "$LOG"
            exit 0
            ;;
        CRASH)
            echo "MOCK_CRASH" >> "$LOG"
            exit 1
            ;;
    esac
done

echo "MOCK_STDIN_CLOSED" >> "$LOG"
