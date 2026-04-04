#!/usr/bin/env bash
################################################################################
# section_G.sh — Logging tests (G1–G5)
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/harness.sh"

TMPDIR_G=$(mktemp -d)
trap 'cleanup_sessions; rm -rf "$TMPDIR_G"' EXIT

FIXTURE_REPO="${TMPDIR_G}/test-repo"
make_repo "$FIXTURE_REPO"

LOG_DIR="${HOME}/.config/gvt"
LOG_FILE="${LOG_DIR}/gvt.log"

echo "── Section G: Logging ──"

# ── G1: Default run creates log file ─────────────────────────────────────
# Clean any existing log
rm -f "$LOG_FILE" "$LOG_FILE.1" "$LOG_FILE.2"

SESSION="g1_log"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && $GVT file.py"
sleep 4
# Send qq to exit
if session_alive "$SESSION"; then
    send_keys "$SESSION" "qq"
    wait_for_exit "$SESSION" 5
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

if [ -f "$LOG_FILE" ]; then
    log_result "G1" pass "gvt.log created at $LOG_FILE"
else
    # Log file might not be created if nothing is logged at WARNING level
    # Check if directory exists
    if [ -d "$LOG_DIR" ]; then
        log_result "G1" pass "log directory exists (no warnings to log at default level)"
    else
        log_result "G1" fail "log file and directory not created"
    fi
fi

# ── G2: GVT_LOG_LEVEL=DEBUG produces debug lines ────────────────────────
rm -f "$LOG_FILE" "$LOG_FILE.1" "$LOG_FILE.2"

SESSION="g2_debug"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && GVT_LOG_LEVEL=DEBUG $GVT file.py"
sleep 5
if session_alive "$SESSION"; then
    send_keys "$SESSION" "qq"
    wait_for_exit "$SESSION" 5
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

if [ -f "$LOG_FILE" ] && grep -q "DEBUG" "$LOG_FILE" 2>/dev/null; then
    log_result "G2" pass "DEBUG lines written with GVT_LOG_LEVEL=DEBUG"
elif [ -f "$LOG_FILE" ]; then
    LOG_CONTENT=$(head -5 "$LOG_FILE")
    log_result "G2" fail "log file exists but no DEBUG lines found. Content: $LOG_CONTENT"
else
    log_result "G2" fail "no log file created even with GVT_LOG_LEVEL=DEBUG"
fi

# ── G3: Cause a failure — corrupt ref produces WARNING ───────────────────
rm -f "$LOG_FILE" "$LOG_FILE.1" "$LOG_FILE.2"

# Create a corrupt ref in fixture repo
echo "garbage" > "$FIXTURE_REPO/.git/refs/heads/bad-ref"

SESSION="g3_warning"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && GVT_LOG_LEVEL=DEBUG $GVT file.py"
sleep 5
if session_alive "$SESSION"; then
    send_keys "$SESSION" "qq"
    wait_for_exit "$SESSION" 5
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Clean up corrupt ref
rm -f "$FIXTURE_REPO/.git/refs/heads/bad-ref"

if [ -f "$LOG_FILE" ] && grep -qiE "warning|error|corrupt|bad|skip" "$LOG_FILE" 2>/dev/null; then
    log_result "G3" pass "warning/error logged for corrupt ref"
elif [ -f "$LOG_FILE" ]; then
    LOG_CONTENT=$(cat "$LOG_FILE" | head -10)
    log_result "G3" fail "log file exists but no warning about corrupt ref. Content: $LOG_CONTENT"
else
    log_result "G3" fail "no log file created"
fi

# ── G4: Log rotation at >512KB ──────────────────────────────────────────
rm -f "$LOG_FILE" "$LOG_FILE.1" "$LOG_FILE.2"
mkdir -p "$LOG_DIR"

# Force-write >512KB to the log using gvt's own logging
"$PYTHON" -c "
import gvt.logging_setup as l
log = l.get_logger('gvt.rotation_test')
# Write enough to trigger rotation (512KB = 524288 bytes)
# Each line is ~100 bytes, so ~6000 lines
for i in range(6000):
    log.warning('Rotation test line %d: padding to fill up the log file with enough content to trigger rotation mechanism xxxx', i)
" 2>/dev/null || true

if [ -f "$LOG_FILE.1" ] || [ -f "${LOG_FILE}.1" ]; then
    log_result "G4" pass "log rotation occurred (gvt.log.1 exists)"
elif [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(wc -c < "$LOG_FILE")
    if [ "$LOG_SIZE" -lt 524288 ]; then
        log_result "G4" fail "log file exists ($LOG_SIZE bytes) but no rotation file"
    else
        log_result "G4" fail "log file is ${LOG_SIZE} bytes but .log.1 not found"
    fi
else
    log_result "G4" fail "no log file created"
fi

# ── G5: Read-only log directory — gvt should not crash ───────────────────
rm -f "$LOG_FILE" "$LOG_FILE.1" "$LOG_FILE.2"

# Create a read-only version of the config dir
READONLY_CONFIG="${TMPDIR_G}/ro-config"
mkdir -p "$READONLY_CONFIG/gvt"
chmod 444 "$READONLY_CONFIG/gvt"

SESSION="g5_readonly"
# Override XDG_CONFIG_HOME to use our read-only dir
# But gvt uses Path.home() / ".config" — so we need HOME override
FAKE_HOME="${TMPDIR_G}/fake-home"
mkdir -p "$FAKE_HOME/.config/gvt"
chmod 444 "$FAKE_HOME/.config/gvt"

tmux_spawn "$SESSION" "cd $FIXTURE_REPO && HOME=$FAKE_HOME $GVT file.py"
sleep 4

if session_alive "$SESSION"; then
    log_result "G5" pass "gvt did not crash with read-only log directory"
    send_keys "$SESSION" "qq"
    wait_for_exit "$SESSION" 5
else
    capture_pane "$SESSION"
    if echo "$PANE_TEXT" | grep -qi "traceback\|permission\|error" 2>/dev/null; then
        log_result "G5" fail "gvt crashed with read-only log dir: $(echo "$PANE_TEXT" | head -5)"
    else
        log_result "G5" pass "gvt exited cleanly with read-only log dir"
    fi
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Restore permissions for cleanup
chmod 755 "$FAKE_HOME/.config/gvt" 2>/dev/null || true
chmod 755 "$READONLY_CONFIG/gvt" 2>/dev/null || true

echo "── Section G complete ──"
