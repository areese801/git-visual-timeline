#!/usr/bin/env bash
################################################################################
# harness.sh — bash helpers for gvt end-to-end tests
#
# Provides: make_repo, run_cli, tmux_spawn, send_keys, capture_pane,
#           assert_contains, assert_exit_code, log_result, cleanup_sessions
################################################################################
set -euo pipefail

export TERM="${TERM:-xterm-256color}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
GVT="${REPO_ROOT}/venv-e2e/bin/gvt"
PYTHON="${REPO_ROOT}/venv-e2e/bin/python"
RESULTS_TAP="${SCRIPT_DIR}/results.tap"
TEST_COUNT=0
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
_TMUX_SESSIONS=()

# ── make_repo <path> ────────────────────────────────────────────────────────
# Creates a tiny git repo with 2-3 commits for testing.
make_repo() {
    local path="$1"
    rm -rf "$path"
    mkdir -p "$path"
    (
        cd "$path"
        git init -q
        git config user.email "test@test.com"
        git config user.name "Test"

        echo "line1" > file.py
        git add file.py
        git commit -q -m "Initial commit"

        echo "line2" >> file.py
        git add file.py
        git commit -q -m "Second commit"

        echo "line3" >> file.py
        git add file.py
        git commit -q -m "Third commit"
    )
}

# ── make_empty_repo <path> ──────────────────────────────────────────────────
# Creates an empty git repo with no commits.
make_empty_repo() {
    local path="$1"
    rm -rf "$path"
    mkdir -p "$path"
    (
        cd "$path"
        git init -q
        git config user.email "test@test.com"
        git config user.name "Test"
    )
}

# ── run_cli <args...> ──────────────────────────────────────────────────────
# Runs gvt with given args, captures stdout/stderr/exit code.
# Sets: CLI_STDOUT, CLI_STDERR, CLI_EXIT
run_cli() {
    local tmp_stdout tmp_stderr
    tmp_stdout=$(mktemp)
    tmp_stderr=$(mktemp)
    set +e
    "$GVT" "$@" >"$tmp_stdout" 2>"$tmp_stderr"
    CLI_EXIT=$?
    set -e
    CLI_STDOUT=$(cat "$tmp_stdout")
    CLI_STDERR=$(cat "$tmp_stderr")
    rm -f "$tmp_stdout" "$tmp_stderr"
}

# ── tmux_spawn <session> <cmd> ─────────────────────────────────────────────
# Spawns a tmux detached session with the given command.
tmux_spawn() {
    local session="$1"
    shift
    local cmd="$*"
    # Kill existing session if any
    tmux kill-session -t "$session" 2>/dev/null || true
    tmux new-session -d -s "$session" -x 120 -y 40 "$cmd"
    _TMUX_SESSIONS+=("$session")
}

# ── send_keys <session> <keys> ─────────────────────────────────────────────
send_keys() {
    local session="$1"
    shift
    tmux send-keys -t "$session" "$@"
}

# ── capture_pane <session> ─────────────────────────────────────────────────
# Captures visible pane content. Sets PANE_TEXT.
capture_pane() {
    local session="$1"
    PANE_TEXT=$(tmux capture-pane -t "$session" -p 2>/dev/null || echo "")
}

# ── session_alive <session> ────────────────────────────────────────────────
# Returns 0 if tmux session exists, 1 otherwise.
session_alive() {
    tmux has-session -t "$1" 2>/dev/null
}

# ── wait_for_exit <session> <timeout_secs> ─────────────────────────────────
# Waits up to timeout for tmux session to die.
wait_for_exit() {
    local session="$1"
    local timeout="${2:-10}"
    local elapsed=0
    while session_alive "$session" && [ "$elapsed" -lt "$timeout" ]; do
        sleep 0.5
        elapsed=$((elapsed + 1))
    done
}

# ── wait_for_content <session> <pattern> <timeout_secs> ───────────────────
# Waits until capture_pane matches pattern or timeout.
wait_for_content() {
    local session="$1"
    local pattern="$2"
    local timeout="${3:-15}"
    local elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        capture_pane "$session"
        if echo "$PANE_TEXT" | grep -qF "$pattern" 2>/dev/null; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# ── assert_contains <haystack> <needle> <msg> ─────────────────────────────
assert_contains() {
    local haystack="$1"
    local needle="$2"
    local msg="$3"
    if echo "$haystack" | grep -qF "$needle" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# ── assert_exit_code <actual> <expected> <msg> ────────────────────────────
assert_exit_code() {
    local actual="$1"
    local expected="$2"
    local msg="$3"
    if [ "$actual" -eq "$expected" ]; then
        return 0
    else
        return 1
    fi
}

# ── log_result <name> <pass|fail|skip> <msg> ──────────────────────────────
log_result() {
    local name="$1"
    local status="$2"
    local msg="$3"
    TEST_COUNT=$((TEST_COUNT + 1))
    case "$status" in
        pass)
            PASS_COUNT=$((PASS_COUNT + 1))
            echo "ok $TEST_COUNT - $name: $msg" >> "$RESULTS_TAP"
            echo "  ✓ $name: $msg"
            ;;
        fail)
            FAIL_COUNT=$((FAIL_COUNT + 1))
            echo "not ok $TEST_COUNT - $name: $msg" >> "$RESULTS_TAP"
            echo "  ✗ $name: $msg"
            ;;
        skip)
            SKIP_COUNT=$((SKIP_COUNT + 1))
            echo "ok $TEST_COUNT - $name # SKIP $msg" >> "$RESULTS_TAP"
            echo "  - $name: SKIP $msg"
            ;;
    esac
}

# ── cleanup_sessions ──────────────────────────────────────────────────────
cleanup_sessions() {
    for s in "${_TMUX_SESSIONS[@]:-}"; do
        tmux kill-session -t "$s" 2>/dev/null || true
    done
    _TMUX_SESSIONS=()
}

# ── emit_summary ──────────────────────────────────────────────────────────
emit_summary() {
    echo ""
    echo "═══════════════════════════════════════════════"
    echo "TAP Summary: $TEST_COUNT tests — $PASS_COUNT pass, $FAIL_COUNT fail, $SKIP_COUNT skip"
    echo "═══════════════════════════════════════════════"

    # Prepend TAP plan line
    local tmp
    tmp=$(mktemp)
    echo "1..$TEST_COUNT" > "$tmp"
    cat "$RESULTS_TAP" >> "$tmp"
    mv "$tmp" "$RESULTS_TAP"
}

# ── emit_junit_xml ────────────────────────────────────────────────────────
# Converts results.tap to a basic JUnit XML.
emit_junit_xml() {
    local xml_file="${SCRIPT_DIR}/results.xml"
    {
        echo '<?xml version="1.0" encoding="UTF-8"?>'
        echo "<testsuites tests=\"$TEST_COUNT\" failures=\"$FAIL_COUNT\" skipped=\"$SKIP_COUNT\">"
        echo "  <testsuite name=\"gvt-e2e\" tests=\"$TEST_COUNT\" failures=\"$FAIL_COUNT\" skipped=\"$SKIP_COUNT\">"

        while IFS= read -r line; do
            # Skip plan line
            [[ "$line" =~ ^1\.\. ]] && continue

            if [[ "$line" =~ ^ok\ [0-9]+\ -\ (.*)#\ SKIP\ (.*) ]]; then
                local tname="${BASH_REMATCH[1]}"
                local reason="${BASH_REMATCH[2]}"
                echo "    <testcase name=\"${tname}\"><skipped message=\"${reason}\"/></testcase>"
            elif [[ "$line" =~ ^ok\ [0-9]+\ -\ (.*) ]]; then
                local tname="${BASH_REMATCH[1]}"
                echo "    <testcase name=\"${tname}\"/>"
            elif [[ "$line" =~ ^not\ ok\ [0-9]+\ -\ (.*) ]]; then
                local tname="${BASH_REMATCH[1]}"
                echo "    <testcase name=\"${tname}\"><failure message=\"test failed\"/></testcase>"
            fi
        done < "$RESULTS_TAP"

        echo "  </testsuite>"
        echo "</testsuites>"
    } > "$xml_file"
}

trap cleanup_sessions EXIT
