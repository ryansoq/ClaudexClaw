#!/bin/bash
# scheduler-sentinel.sh — external watchdog for ClawX apscheduler.
#
# ClawX has an internal _scheduler_watchdog, but if ClawX itself wedges
# nobody wakes it up. This script runs from system cron every 10 min and
# is fully decoupled from ClawX state.
#
# Behavior on each run:
#   1. Find latest clawx-YYYYMMDD.log
#   2. Look for [Schedule] / [Inject] events in the last 75 minutes
#      (covers ≥ 2 missed heartbeats at */30 cadence)
#   3. If 0 events: send SIGHUP to ClawX, log + alert
#   4. Escalate alert severity on consecutive failures (does NOT hard-kill,
#      because ClawX is started from an interactive bash and has no
#      supervisor to bring it back — Ryan must manually restart).
#
# State stored in /tmp/clawx-sentinel.state (consecutive_failures count).

set -u

CLAWD_DIR=/home/ymchang/clawd
LOG_DIR="$CLAWD_DIR/logs"
STATE_FILE=/tmp/clawx-sentinel.state
SENTINEL_LOG="$LOG_DIR/scheduler-sentinel.log"
TG_TOKEN_FILE=/home/ymchang/.claude/channels/telegram/.env
TG_CHAT_ID=5168530096
WINDOW_MINUTES=75

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" >> "$SENTINEL_LOG"; }

mkdir -p "$LOG_DIR"

# Telegram alert helper (best-effort)
tg_alert() {
    local msg="$1"
    if [ ! -f "$TG_TOKEN_FILE" ]; then return; fi
    local token
    token=$(grep '^TELEGRAM_BOT_TOKEN=' "$TG_TOKEN_FILE" | cut -d= -f2)
    [ -z "$token" ] && return
    curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        -d chat_id="$TG_CHAT_ID" \
        -d text="$msg" \
        -o /dev/null
}

# 1. Find latest clawx log
LATEST_LOG=$(ls -t "$LOG_DIR"/clawx-*.log 2>/dev/null | head -1)
if [ -z "$LATEST_LOG" ]; then
    log "ERROR: no clawx log found in $LOG_DIR"
    exit 1
fi

# 2. Find ClawX PID (parent python process running clawx.py)
CLAWX_PID=$(pgrep -f 'python.*clawx.py' | head -1)
if [ -z "$CLAWX_PID" ]; then
    log "ERROR: no ClawX python process found"
    tg_alert "🚨 [sentinel] ClawX 整個不在了！沒看到 python clawx.py 程序"
    exit 1
fi

# 3. Count [Schedule] or [Inject] events within window
#    Logs are mostly text but have stray null bytes — use strings + grep.
CUTOFF_EPOCH=$(date -d "$WINDOW_MINUTES minutes ago" +%s)

EVENT_COUNT=$(strings "$LATEST_LOG" 2>/dev/null \
    | grep -E '\[(Schedule|Inject|FIFO)\]' \
    | awk -v cutoff="$CUTOFF_EPOCH" '
        {
            # Parse "YYYY-MM-DD HH:MM:SS,mmm" prefix
            datestr = $1 " " $2
            sub(/,.*/, "", datestr)
            cmd = "date -d \"" datestr "\" +%s 2>/dev/null"
            cmd | getline epoch
            close(cmd)
            if (epoch >= cutoff) print
        }' \
    | wc -l)

# 4. Read state
FAILURES=0
if [ -f "$STATE_FILE" ]; then
    FAILURES=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
fi

# 5. Decide action
if [ "$EVENT_COUNT" -gt 0 ]; then
    # Healthy — reset
    if [ "$FAILURES" -gt 0 ]; then
        log "RECOVERED: $EVENT_COUNT events in last ${WINDOW_MINUTES}min, clearing $FAILURES prior failures"
        tg_alert "✅ [sentinel] ClawX scheduler 恢復正常 ($EVENT_COUNT 個事件 / ${WINDOW_MINUTES}min)"
    fi
    echo 0 > "$STATE_FILE"
    log "OK: $EVENT_COUNT events in last ${WINDOW_MINUTES}min (pid=$CLAWX_PID)"
    exit 0
fi

# Unhealthy
FAILURES=$((FAILURES + 1))
echo "$FAILURES" > "$STATE_FILE"
log "ALERT: 0 events in last ${WINDOW_MINUTES}min (failure #$FAILURES, pid=$CLAWX_PID)"

log "Attempting SIGHUP to $CLAWX_PID (failure #$FAILURES)"
if kill -HUP "$CLAWX_PID" 2>/dev/null; then
    if [ "$FAILURES" -le 2 ]; then
        tg_alert "⚠️ [sentinel] ClawX scheduler 靜默 ${WINDOW_MINUTES}min — 已 SIGHUP 自救（第 $FAILURES 次）"
    elif [ "$FAILURES" -eq 3 ]; then
        tg_alert "🚨 [sentinel] SIGHUP 連 3 次都救不了 ClawX scheduler — Ryan 需手動 restart：cd ~/clawd && python clawx.py"
    fi
    # After 3, stay quiet to avoid flooding — sentinel keeps trying SIGHUP
    # silently. State counter keeps growing so logs reflect reality.
else
    tg_alert "🚨 [sentinel] ClawX scheduler 靜默 ${WINDOW_MINUTES}min — SIGHUP 失敗！pid=$CLAWX_PID 可能掛了"
fi
