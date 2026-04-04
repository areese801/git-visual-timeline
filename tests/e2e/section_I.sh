#!/usr/bin/env bash
################################################################################
# section_I.sh — Resilience tests (I1–I5)
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/harness.sh"

TMPDIR_I=$(mktemp -d)
trap 'cleanup_sessions; rm -rf "$TMPDIR_I"' EXIT

echo "── Section I: Resilience ──"

# ── I1: Corrupt .git/refs/heads/foo, launch gvt ─────────────────────────
REPO_I1="${TMPDIR_I}/repo-i1"
make_repo "$REPO_I1"
echo "garbage" > "$REPO_I1/.git/refs/heads/bad-ref"

SESSION="i1_corrupt"
tmux_spawn "$SESSION" "cd $REPO_I1 && $GVT file.py"
sleep 4

if session_alive "$SESSION"; then
    log_result "I1" pass "gvt launches despite corrupt ref"
    send_keys "$SESSION" "qq"
    wait_for_exit "$SESSION" 5
else
    capture_pane "$SESSION"
    if echo "$PANE_TEXT" | grep -qi "traceback" 2>/dev/null; then
        log_result "I1" fail "gvt crashed with corrupt ref: $(echo "$PANE_TEXT" | tail -5)"
    else
        log_result "I1" pass "gvt exited cleanly despite corrupt ref"
    fi
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── I2: Detached HEAD ────────────────────────────────────────────────────
REPO_I2="${TMPDIR_I}/repo-i2"
make_repo "$REPO_I2"

# Get a commit SHA and checkout detached
DETACH_SHA=$(cd "$REPO_I2" && git rev-parse HEAD~1)
(cd "$REPO_I2" && git checkout "$DETACH_SHA" 2>/dev/null)

SESSION="i2_detached"
tmux_spawn "$SESSION" "cd $REPO_I2 && $GVT file.py"
sleep 4

if session_alive "$SESSION"; then
    capture_pane "$SESSION"
    if echo "$PANE_TEXT" | grep -qiE "HEAD|detach" 2>/dev/null; then
        log_result "I2" pass "gvt shows HEAD in detached state"
    else
        log_result "I2" pass "gvt launches in detached HEAD state (TUI alive)"
    fi
    send_keys "$SESSION" "qq"
    wait_for_exit "$SESSION" 5
else
    capture_pane "$SESSION"
    if echo "$PANE_TEXT" | grep -qi "traceback" 2>/dev/null; then
        log_result "I2" fail "gvt crashed with detached HEAD: $(echo "$PANE_TEXT" | tail -5)"
    else
        log_result "I2" fail "gvt exited immediately with detached HEAD"
    fi
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── I3: Delete .git/HEAD mid-session ─────────────────────────────────────
REPO_I3="${TMPDIR_I}/repo-i3"
make_repo "$REPO_I3"

SESSION="i3_delete_head"
tmux_spawn "$SESSION" "cd $REPO_I3 && $GVT file.py"
sleep 4

if session_alive "$SESSION"; then
    # Delete .git/HEAD while app is running
    rm -f "$REPO_I3/.git/HEAD"
    sleep 1
    # Try to trigger a refresh by moving in the timeline
    send_keys "$SESSION" "l"
    sleep 2

    if session_alive "$SESSION"; then
        log_result "I3" pass "gvt survived .git/HEAD deletion mid-session"
        send_keys "$SESSION" "qq"
        wait_for_exit "$SESSION" 5
    else
        capture_pane "$SESSION"
        if echo "$PANE_TEXT" | grep -qi "traceback" 2>/dev/null; then
            log_result "I3" fail "gvt crashed after .git/HEAD deletion: $(echo "$PANE_TEXT" | tail -5)"
        else
            log_result "I3" pass "gvt exited gracefully after .git/HEAD deletion"
        fi
    fi
else
    log_result "I3" fail "gvt exited before we could delete .git/HEAD"
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── I4: External commit while gvt running (out of scope) ────────────────
log_result "I4" skip "external commit during session — out of scope for this run"

# ── I5: Run pytest on same repo while gvt running (out of scope) ────────
log_result "I5" skip "concurrent pytest — out of scope for this run"

echo "── Section I complete ──"
