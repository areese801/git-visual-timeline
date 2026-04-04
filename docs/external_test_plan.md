# gvt External (End-to-End) Test Plan

## Goal

Exercise `gvt` the way a real user does — as an installed CLI binary hitting real git repos — to catch the classes of bugs that unit + Textual-pilot tests miss: terminal restoration, tmux integration, editor launch, clipboard integration, big-repo performance, stale-cache edge cases, and crash-recovery.

## Scope

In-scope:
- `gvt` CLI entry point (argument handling, exit codes, terminal cleanup)
- Keyboard interaction against diverse repo shapes
- Integration with external tools (`$EDITOR`, `pbcopy`/`xclip`, `tmux`, git CLI)
- Log file creation + rotation behavior under real load

Out-of-scope:
- Logic already covered by pytest (timeline math, diff parsing, cache LRU)

## Test Environment

| Component | Value |
|---|---|
| Binary | `gvt` from `pip install -e .` in fresh venv |
| Python | 3.14 (match pyproject) |
| Terminal | iTerm2 (primary), `tmux` inside iTerm2 (secondary) |
| Repos | See "Test Corpus" below |
| Log file | `~/.config/gvt/gvt.log` — tailed in a side pane |

## Test Corpus (real repos to exercise against)

| Repo | Purpose |
|---|---|
| `git-visual-timeline` itself (this repo) | small, fast, known shape |
| `cpython` or `linux` (clone ~1GB) | large-repo performance, `_build_ref_map` resilience |
| A fresh `git init` with 1 commit | edge case: minimal history |
| An empty repo (no commits) | should error gracefully, not crash |
| A repo with detached HEAD | `get_branches` detached path |
| A repo with a deliberately corrupted ref | `_build_ref_map` corrupt-ref path |
| A repo with a file that has a `--follow` rename | rename tracking |
| A repo with merge commits, octopus merges | multi-parent commits |

## Test Matrix

### A. CLI entry & lifecycle

| # | Action | Expected |
|---|---|---|
| A1 | `gvt --version` | prints `gvt X.Y.Z`, exit 0 |
| A2 | `gvt --help` | usage text, exit 0 |
| A3 | `gvt` outside any git repo | error to stderr, exit 1, no TUI |
| A4 | `gvt path/to/file.py` with valid file | opens TUI on that file |
| A5 | `gvt does-not-exist.py` | error to stderr, exit 1 |
| A6 | `gvt /abs/path/to/repo-file.py` from elsewhere | resolves and opens |
| A7 | `gvt` in subdirectory of repo | finds repo root, opens fine |
| A8 | `gvt` in empty repo (no commits) | does not crash |
| A9 | Launch, press `q` twice (qq) | exits cleanly, terminal restored |
| A10 | Launch, press `q` once then wait | modal appears, y quits, n stays |
| A11 | Launch, `kill -TERM <pid>` | terminal restored (alt-screen exited, cursor visible) |
| A12 | Launch, `kill -KILL <pid>` | terminal corrupted (expected); `stty sane` recovers |
| A13 | Launch, Ctrl+C | terminal restored |

### B. Timeline navigation

| # | Action | Expected |
|---|---|---|
| B1 | Open small repo, press `h`/`l` 20× each | cursor moves, diff updates, no lag |
| B2 | Open cpython, navigate a hot file (e.g. `Python/ceval.c`) | scrubbing stays responsive (<200ms diff updates) |
| B3 | `0` / `$` | jump to first/last |
| B4 | `x` then move then `x` | pin range renders, diff spans range |
| B5 | `x x x` | pins clear, back to step mode |
| B6 | `X` (snap) with pins | nearest pin snaps to cursor |
| B7 | Esc with pins | pins clear |
| B8 | `t`, pick 1w/1m/3m/6m/1y/All, also custom `2024-01-01` | timeline filters correctly, title reflects filter |
| B9 | `t`, enter garbage like `abc` | falls back to full range (no crash) |
| B10 | Navigate past end/start with `h`/`l` | cursor clamps |

### C. Diff pane

| # | Action | Expected |
|---|---|---|
| C1 | `j`/`k`/`g`/`G` in diff | scroll works |
| C2 | `+` / `-` / `m` / `l` | context lines change, diff reloads |
| C3 | `w` | whole-file view toggles |
| C4 | `d` | side-by-side toggle, columns aligned |
| C5 | `n` / `p` with multiple hunks | jumps between hunks, flash visible |
| C6 | `/pattern`, type, Enter, `n`, `N` | search highlights and navigates |
| C7 | `/` with invalid regex (`[`) | no crash, empty matches |
| C8 | Esc after search | clears highlights |
| C9 | `b` (blame) on a non-WIP commit | blame annotations appear right-aligned |
| C10 | `b` on WIP commit | no blame (skipped by design) |

### D. File tree & changed files

| # | Action | Expected |
|---|---|---|
| D1 | `1` focus file tree, `j`/`k`, Enter | opens file timeline |
| D2 | `o` on a directory | expands/collapses |
| D3 | Open an untracked file | preview with line numbers, no history |
| D4 | Open a binary file | graceful message, no crash |
| D5 | Open a 10MB text file | loads in reasonable time (<3s) |
| D6 | `5` focus changed files, Enter | opens selected file timeline |

### E. Modals & search

| # | Action | Expected |
|---|---|---|
| E1 | `c` opens commit search | input focused, first 50 results visible |
| E2 | Type 20 chars in commit search | results update per keystroke, no visible lag |
| E3 | Select commit, pick file | opens that file timeline |
| E4 | `f` / Ctrl+P | file search, fuzzy matching works |
| E5 | `?` / Esc | help modal open/close |

### F. External tool integration

| # | Action | Expected |
|---|---|---|
| F1 | `y` (short hash) | toast "Copied abc1234", system clipboard has hash |
| F2 | `Y` (full hash) | toast with full 40-char hash |
| F3 | `y` with `PATH=''` (no clipboard tool) | toast "No clipboard tool found", no crash |
| F4 | `e` with `EDITOR=nvim` | suspends TUI, nvim opens, quit returns to gvt cleanly |
| F5 | `e` with `EDITOR=nonexistent-xyz` | toast "Could not launch editor: …", TUI intact |
| F6 | `e` with editor that exits nonzero (e.g. `EDITOR='sh -c "exit 2"'`) | toast "Editor exited with code 2" |
| F7 | Inside tmux: Ctrl+h/l at edge panes | hands off to tmux-select-pane |
| F8 | Outside tmux: Ctrl+h/l at edge | no-op (does not crash) |

### G. Logging

| # | Action | Expected |
|---|---|---|
| G1 | Default run | `~/.config/gvt/gvt.log` created, level WARNING |
| G2 | `GVT_LOG_LEVEL=DEBUG gvt` | DEBUG lines written |
| G3 | Cause a failure (corrupt ref, missing editor) | WARNING appears in log |
| G4 | Run many sessions until log > 512KB | file rotates to `.log.1`, `.log.2` |
| G5 | Chmod `~/.config/gvt` to read-only, launch gvt | does not crash (fallback NullHandler) |

### H. Performance & load

| # | Action | Expected |
|---|---|---|
| H1 | Open file with 5000+ commits | initial load < 5s, `notify("Loading history…")` shown |
| H2 | Rapid `l l l l l l l l l l` on a hot file | stays responsive, no queue blow-up |
| H3 | `c` on cpython | commit list loads within 10s |
| H4 | Hold `l` for 3s | cursor scrubs smoothly (thanks to preload cache) |
| H5 | Watch `gvt.log` during rapid scrub | no warnings (no errors swallowed) |

### I. Crash recovery & resilience

| # | Action | Expected |
|---|---|---|
| I1 | Corrupt `.git/refs/heads/foo` to garbage, launch gvt | launches, log shows skipped ref |
| I2 | Checkout detached HEAD, launch | status bar shows `HEAD` as branch |
| I3 | Delete `.git/HEAD` mid-session | no crash on next refresh (gracefully errors) |
| I4 | Externally commit while gvt running | known-stale: commit-search cache doesn't refresh (documented in TODO) |
| I5 | Run pytest on gvt's repo while gvt running on same repo | no lock conflicts |

## Execution Options

### Manual walkthrough (1 person, ~60 min)
Work the matrix by hand. Low overhead, but not repeatable.

### Scripted with `expect` / `tmux send-keys` (repeatable, ~2 days setup)
- `tmux` new-session detached, `tmux send-keys` to drive keypresses
- `tmux capture-pane -p` to assert on visible output
- Wrap each row as a small bash function; emit TAP output

### Delegate to cage (autonomous, hands-off)
A `trusty-cage` container with:
- this repo mounted
- `cpython` cloned for big-repo cases
- `tmux` + `expect` installed
- a driver script that walks the matrix and emits JUnit XML
The cage can run the whole matrix unsupervised and report back.
**Best fit given the breadth of the matrix and the repeatability we want.**

## Deliverables

1. `tests/e2e/` directory with `tmux`-driven harness + one driver file per matrix section (A-I).
2. `scripts/e2e-run.sh` — spins up tmux, runs drivers, captures `gvt.log`, emits JUnit.
3. CI job (GitHub Actions) that runs sections A/G/I on every PR (fast, hermetic).
4. Local-only job for sections B/H (needs big repo, too slow for CI).
5. This document kept in sync with new features.

## Pre-requisites for the Cage

```bash
# Inside the cage:
apt-get install tmux expect git
git clone https://github.com/python/cpython /work/cpython  # ~1GB, slow
pip install -e /work/git-visual-timeline
```

## Open Questions

- Do we want video recordings (asciinema) of failures for debugging?
- Should the CI matrix run on macOS runners (pbcopy) as well as linux (xclip)?
- Acceptance threshold for "responsive" (B2/H1/H4) — set explicit ms budget?
