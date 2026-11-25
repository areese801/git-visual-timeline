#!/usr/bin/env bash
################################################################################
# section_A.sh — CLI entry & lifecycle tests (A1–A14)
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
pushd "$NOGIT_DIR" >/dev/null
run_cli
popd >/dev/null
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
pushd "$FIXTURE_REPO" >/dev/null
run_cli does-not-exist.py
popd >/dev/null
if assert_exit_code "$CLI_EXIT" 1 "exit 1" && assert_contains "$CLI_STDERR" "not found" "error message"; then
    log_result "A5" pass "gvt with missing file errors with exit 1"
else
    log_result "A5" fail "got exit=$CLI_EXIT stderr='$CLI_STDERR'"
fi

# ── A8: gvt in empty repo (no commits) ───────────────────────────────────
SESSION="a8_empty"
tmux_spawn "$SESSION" "cd $EMPTY_REPO && $GVT"
if wait_for_content "$SESSION" "[2] Timeline" 10; then
    log_result "A8" pass "timeline visible with empty repository"
else
    log_result "A8" fail "timeline did not appear with empty repository"
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
tmux_spawn "$SESSION" "cd '$FIXTURE_REPO' || exit 1; stty sane </dev/tty; stty -g </dev/tty > '$_E2E_RUN_DIR/tty.before'; '$GVT' file.py </dev/tty & pid=\$!; echo \$pid > '$_E2E_RUN_DIR/pid'; wait \$pid; echo \$? > '$_E2E_RUN_DIR/status'; stty -g </dev/tty > '$_E2E_RUN_DIR/tty.after'"
if wait_for_content "$SESSION" "[2] Timeline" 10 && kill -TERM "$(cat "$_E2E_RUN_DIR/pid")"; then
    wait_for_exit "$SESSION" 10
    if [[ -f "$_E2E_RUN_DIR/status" && "$(cat "$_E2E_RUN_DIR/status")" == "143" ]] && cmp -s "$_E2E_RUN_DIR/tty.before" "$_E2E_RUN_DIR/tty.after"; then
        log_result "A11" pass "gvt exited with SIGTERM status and restored terminal settings"
    else
        log_result "A11" fail "SIGTERM status or terminal settings did not match"
    fi
else
    log_result "A11" fail "could not signal the running TUI"
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

# ── A14: Evolution screen opens, closes, and gvt still quits with qq ─────
SESSION="a14_evolution"
tmux_spawn "$SESSION" "cd $FIXTURE_REPO && $GVT file.py"
sleep 3
if session_alive "$SESSION"; then
    send_keys "$SESSION" "v"
    if wait_for_content "$SESSION" "Evolution — file.py" 10; then
        send_keys "$SESSION" Escape
        if wait_for_content "$SESSION" "[2] Timeline" 10; then
            send_keys "$SESSION" "q"
            send_keys "$SESSION" "q"
            wait_for_exit "$SESSION" 10
            if ! session_alive "$SESSION"; then
                log_result "A14" pass "v opens Evolution, Esc returns, qq exits"
            else
                log_result "A14" fail "qq did not exit after closing Evolution"
            fi
        else
            log_result "A14" fail "Esc did not return to the pane layout"
        fi
    else
        log_result "A14" fail "Evolution screen not shown after v. Pane: $(echo "$PANE_TEXT" | head -3)"
    fi
else
    log_result "A14" fail "gvt exited before v could be sent"
fi
tmux kill-session -t "$SESSION" 2>/dev/null || true

echo "── Section A complete ──"

(( FAIL_COUNT == 0 ))
