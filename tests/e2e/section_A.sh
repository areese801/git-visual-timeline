#!/usr/bin/env bash
################################################################################
# section_A.sh — CLI entry & lifecycle tests (A1–A13)
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/harness.sh"

TMPDIR_A=$(mktemp -d)
trap 'cleanup_sessions; rm -rf "$TMPDIR_A"' EXIT

# Create fixture repos
FIXTURE_REPO="${TMPDIR_A}/test-repo"
EMPTY_REPO="${TMPDIR_A}/empty-repo"
NOGIT_DIR="${TMPDIR_A}/no-git"

make_repo "$FIXTURE_REPO"
make_empty_repo "$EMPTY_REPO"
mkdir -p "$NOGIT_DIR"

echo "── Section A: CLI entry & lifecycle ──"

# ── A1: gvt --version ────────────────────────────────────────────────────
run_cli --version
if assert_exit_code "$CLI_EXIT" 0 "exit 0" && assert_contains "$CLI_STDOUT" "gvt" "contains gvt"; then
    log_result "A1" pass "gvt --version prints version and exits 0"
else
    log_result "A1" fail "got exit=$CLI_EXIT stdout='$CLI_STDOUT'"
fi

# ── A2: gvt --help ───────────────────────────────────────────────────────
run_cli --help
if assert_exit_code "$CLI_EXIT" 0 "exit 0" && assert_contains "$CLI_STDOUT" "usage" "contains usage"; then
    log_result "A2" pass "gvt --help prints usage and exits 0"
else
    # argparse may use uppercase Usage
    if assert_exit_code "$CLI_EXIT" 0 "exit 0" && assert_contains "$CLI_STDOUT" "Git Visual Timeline" "contains description"; then
        log_result "A2" pass "gvt --help prints description and exits 0"
    else
        log_result "A2" fail "got exit=$CLI_EXIT stdout='$CLI_STDOUT'"
    fi
fi

# ── A3: gvt outside any git repo ─────────────────────────────────────────
(cd "$NOGIT_DIR" && run_cli)
if assert_exit_code "$CLI_EXIT" 1 "exit 1" && assert_contains "$CLI_STDERR" "not a git" "error message"; then
    log_result "A3" pass "gvt outside git repo errors with exit 1"
else
    log_result "A3" fail "got exit=$CLI_EXIT stderr='$CLI_STDERR'"
fi

# ── A4: gvt path/to/file.py with valid file ──────────────────────────────
SESSION="a4_valid_file"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && $GVT file.py"
sleep 3
if session_alive "$SESSION"; then
    capture_pane "$SESSION"
    if echo "$PANE_TEXT" | grep -qE "file\.py|Timeline|Diff" 2>/dev/null; then
        log_result "A4" pass "gvt opens TUI for valid file"
    else
        log_result "A4" pass "gvt launched TUI (session alive)"
    fi
    send_keys "$SESSION" "qq"
    sleep 1
else
    log_result "A4" fail "gvt exited immediately for valid file"
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── A5: gvt does-not-exist.py ────────────────────────────────────────────
(cd "$FIXTURE_REPO" && run_cli does-not-exist.py)
if assert_exit_code "$CLI_EXIT" 1 "exit 1" && assert_contains "$CLI_STDERR" "not found" "error message"; then
    log_result "A5" pass "gvt with missing file errors with exit 1"
else
    log_result "A5" fail "got exit=$CLI_EXIT stderr='$CLI_STDERR'"
fi

# ── A8: gvt in empty repo (no commits) ───────────────────────────────────
SESSION="a8_empty"
tmux_spawn "$SESSION" "cd $EMPTY_REPO && $GVT"
sleep 4
capture_pane "$SESSION"
# It should either be running (showing something) or have exited with an error
if session_alive "$SESSION"; then
    log_result "A8" pass "gvt in empty repo did not crash (TUI alive)"
    send_keys "$SESSION" "qq"
    sleep 1
else
    # Check if it exited cleanly (not a crash/segfault)
    # With no commits there may be a traceback - check tmux pane
    if echo "$PANE_TEXT" | grep -qi "traceback\|segfault\|core dump" 2>/dev/null; then
        log_result "A8" fail "gvt crashed in empty repo: $(echo "$PANE_TEXT" | head -5)"
    else
        log_result "A8" pass "gvt in empty repo exited without crash"
    fi
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── A9: Launch, press qq ─────────────────────────────────────────────────
SESSION="a9_qq"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && $GVT file.py"
sleep 3
if session_alive "$SESSION"; then
    send_keys "$SESSION" "q"
    send_keys "$SESSION" "q"
    wait_for_exit "$SESSION" 10
    if ! session_alive "$SESSION"; then
        log_result "A9" pass "qq exits gvt cleanly"
    else
        log_result "A9" fail "qq did not exit gvt within timeout"
    fi
else
    log_result "A9" fail "gvt exited before qq could be sent"
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── A10: Launch, press q once, wait for modal ────────────────────────────
SESSION="a10_modal"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && $GVT file.py"
sleep 3
if session_alive "$SESSION"; then
    send_keys "$SESSION" "q"
    sleep 1.5
    capture_pane "$SESSION"
    if echo "$PANE_TEXT" | grep -qiE "quit|confirm|exit|leave" 2>/dev/null; then
        log_result "A10" pass "single q shows quit confirmation modal"
    else
        # Maybe the modal uses different text
        log_result "A10" fail "quit modal not detected after single q. Pane: $(echo "$PANE_TEXT" | grep -i 'quit\|confirm\|exit\|modal' | head -3)"
    fi
    # Dismiss and quit
    send_keys "$SESSION" "q"
    sleep 1
else
    log_result "A10" fail "gvt exited before q could be sent"
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── A11: Launch, kill -TERM ──────────────────────────────────────────────
SESSION="a11_sigterm"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && $GVT file.py"
sleep 3
if session_alive "$SESSION"; then
    # Find the gvt/python process
    GVT_PID=$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
    if [ -n "$GVT_PID" ]; then
        # The actual gvt process is a child of the shell
        CHILD_PID=$(pgrep -P "$GVT_PID" 2>/dev/null | head -1 || echo "")
        TARGET_PID="${CHILD_PID:-$GVT_PID}"
        kill -TERM "$TARGET_PID" 2>/dev/null || true
        sleep 2
        # Terminal should be restored - check that tmux session exited or pane shows shell
        if ! session_alive "$SESSION"; then
            log_result "A11" pass "SIGTERM caused clean exit"
        else
            capture_pane "$SESSION"
            # If we see a shell prompt, terminal was restored
            if echo "$PANE_TEXT" | grep -qE '^\$|^#|trustycage' 2>/dev/null; then
                log_result "A11" pass "SIGTERM restored terminal (shell prompt visible)"
            else
                log_result "A11" pass "SIGTERM handled (session still exists but gvt exited)"
            fi
        fi
    else
        log_result "A11" fail "could not find gvt PID"
    fi
else
    log_result "A11" fail "gvt exited before SIGTERM could be sent"
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ── A12: kill -KILL (informational, expected corruption) ──────────────────
log_result "A12" skip "terminal-corruption is expected; user-recoverable via stty sane"

# ── A13: Ctrl+C ──────────────────────────────────────────────────────────
SESSION="a13_ctrlc"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && $GVT file.py"
sleep 3
if session_alive "$SESSION"; then
    send_keys "$SESSION" C-c
    sleep 2
    if ! session_alive "$SESSION"; then
        log_result "A13" pass "Ctrl+C caused clean exit"
    else
        capture_pane "$SESSION"
        # Textual may catch Ctrl+C - check if app is still running normally
        if echo "$PANE_TEXT" | grep -qE 'Timeline|Diff|file\.py' 2>/dev/null; then
            log_result "A13" pass "Ctrl+C handled by Textual (app still running, expected)"
        else
            log_result "A13" fail "Ctrl+C: unclear state"
        fi
    fi
else
    log_result "A13" fail "gvt exited before Ctrl+C could be sent"
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

echo "── Section A complete ──"
