# gvt End-to-End Tests

Bash + tmux harness that drives the installed `gvt` binary against real
temporary git repos. Complements the `pytest` unit/integration suite — these
catch CLI-level bugs (terminal restoration, editor launch, signal handling,
logging) that in-process tests can't.

## Prerequisites

- `bash`, `tmux`, `git` on `$PATH`
- A dedicated venv with `gvt` installed as `venv-e2e/` at the repo root

### One-time setup

```bash
# From the repo root
python3 -m venv venv-e2e
venv-e2e/bin/pip install -e .
venv-e2e/bin/gvt --version   # sanity check
```

The harness hardcodes `${REPO_ROOT}/venv-e2e/bin/gvt` — do not rename the venv.
`venv-e2e/` is gitignored.

### macOS notes

- `tmux` via Homebrew: `brew install tmux`
- These tests assume a POSIX-ish environment; they were developed on Linux
  (trusty-cage container) and are expected to work on macOS but some tmux
  timing constants may need nudging if TUI scenarios flake.

### Linux notes

- `apt-get install tmux` (or your distro equivalent)

## Running

```bash
bash tests/e2e/run_all.sh
```

Output:
- TAP on stdout and in `tests/e2e/results.tap`
- JUnit XML in `tests/e2e/results.xml`
- Both results files are gitignored (regenerated on every run)

## Running a single section

```bash
bash tests/e2e/section_A.sh   # CLI lifecycle
bash tests/e2e/section_G.sh   # Logging
bash tests/e2e/section_I.sh   # Resilience
```

## What's covered

| Section | Scenarios | What it exercises |
|---|---|---|
| A | A1–A13 | `--version`, `--help`, exit codes, file arg, qq quit, single-q modal, SIGTERM/Ctrl+C cleanup |
| G | G1–G5 | `~/.config/gvt/gvt.log` creation, `GVT_LOG_LEVEL`, log rotation, read-only log dir fallback |
| I | I1–I3 | Corrupt ref file, detached HEAD, `.git/HEAD` deletion mid-session |

Scenarios B, C, D, E, F, H are intentionally out of scope for this harness —
they need interactive TUI validation or a large external repo (e.g. cpython).
See `docs/external_test_plan.md` (gitignored, local-only) for the full matrix.

## Expected results

At time of writing: 21 scenarios — 18 pass, 3 skip (A12 SIGKILL, I4 concurrent
commit, I5 concurrent pytest), 0 fail.

## Debugging a failure

1. Rerun the specific section with bash trace: `bash -x tests/e2e/section_A.sh`
2. For TUI scenarios, drop into an interactive tmux session and step manually:
   ```bash
   tmux new-session -s debug -x 120 -y 40
   # Inside tmux:
   export PATH=$PWD/venv-e2e/bin:$PATH
   gvt /path/to/file
   ```
3. Check `~/.config/gvt/gvt.log` for structured logs from gvt itself
   (bump level with `GVT_LOG_LEVEL=DEBUG`).

## Contributing new scenarios

Add to the appropriate section script, following the existing pattern:

```bash
# ── X99: short description
run_cli <args>
if assert_exit_code "$CLI_EXIT" 0 "exit 0" && \
   assert_contains "$CLI_STDOUT" "expected substring" "desc"; then
    log_result "X99" pass "what passed"
else
    log_result "X99" fail "got exit=$CLI_EXIT stdout='$CLI_STDOUT'"
fi
```

Update the scenario count in `docs/external_test_plan.md` and in this README.

## Do NOT modify `src/` to make e2e tests pass

These tests exist to find real bugs. If one fails, triage it in
`tests/e2e/FAILURES.md` and file a proper fix — don't chase green by
mutating the code under test.
