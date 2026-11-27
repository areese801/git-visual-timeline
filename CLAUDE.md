# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**gvt** (Git Visual Timeline) is a keyboard-driven Python TUI for exploring per-file git commit history. Built with Textual, it presents a 5-pane layout with a heatmap timeline, syntax-highlighted diffs, commit search, inline blame, and more. Think lazygit meets a video timeline scrubber.

## Build & Development

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run
gvt                          # Open in any git repo
gvt path/to/file.py          # Jump to a specific file

# Lint & format
ruff format .
ruff check --fix .

# Tests
pytest
pytest tests/test_foo.py              # single file
pytest tests/test_foo.py::test_bar    # single test

# Build & publish
make build          # Build wheel and sdist
make publish-test   # Upload to TestPyPI
make publish        # Upload to PyPI
make help           # Show all targets
```

## Architecture

### Tech Stack

- **Textual** for TUI framework (layout, widgets, keybindings, CSS styling)
- **gitpython** for git operations (with direct `git` CLI calls to avoid tree parsing bugs)
- **Pygments** for syntax highlighting
- **thefuzz** for fuzzy string matching

### Layout

```
[1] Files          │  [2] Timeline
                   │  [3] Commits
                   │  [4] Diff
[5] Changed Files  │
```

### Key Modules

| Module | Purpose |
|---|---|
| `src/gvt/app.py` | Main Textual App — layout, keybindings, data wiring |
| `src/gvt/cli.py` | CLI entry point (argparse), SIGTERM handler |
| `src/gvt/git/repo.py` | GitRepo wrapper — commits, diffs, blame, file listing |
| `src/gvt/git/cache.py` | LRU diff cache (~100 entries) |
| `src/gvt/evolution.py` | Pure binning/layout math for the Evolution views (no git, no Textual) |
| `src/gvt/exclusions.py` | Evolution exclusion rules: presets, `.gitattributes`, config files, filtering |
| `src/gvt/widgets/evolution_screen.py` | Evolution screen (`v`): tabs, data loading, authored/everything, jump into history |
| `src/gvt/widgets/calendar_view.py` / `frequency_view.py` | The two Evolution views; `evolution_common.py` holds their base class and `PeriodChosen` |
| `src/gvt/widgets/` | All TUI widgets (timeline, diff_view, file_tree, modals, calendar_view, frequency_view, etc.) |
| `src/gvt/styles/app.tcss` | Textual CSS — Tokyo Night color scheme |

### Design Patterns

- **Async data loading**: File commits, diffs, blame, and commit search all load in background threads via Textual's `@work` decorator. UI stays responsive.
- **LRU cache**: Diffs are cached by `(file, commit_a, commit_b)` to avoid recomputation when navigating back and forth.
- **Message-based communication**: Widgets post messages (e.g. `CursorMoved`, `FileSelected`) that the app handles to coordinate updates across panes.
- **Direct git CLI calls**: Use `self.repo.git.diff(...)` / `self.repo.git.show(...)` instead of gitpython's tree traversal, which crashes on large repos.

## Evolution Screen

`v` opens a full-screen view of how a file, directory or the whole repo changed
over time: a contribution calendar and a frequency chart (split adds/deletes, or
`m` volume mode: size over time above churn). User-facing behavior and the config
reference are in README.md ("Evolution" and "Configuring Evolution exclusions").

### Data flow

1. `GVTApp._resolve_evolution_scope()` picks the scope: the highlighted file-tree
   node when the tree has focus, otherwise the file in the timeline, otherwise the
   whole repo (`"."`). Untracked nodes fall back to the whole repo.
2. `EvolutionScreen._load_history` (a `@work` thread) calls
   `GitRepo.get_scope_commits(scope)`, which runs one
   `git log --no-merges --numstat -- <scope>`. It returns newest-first `CommitInfo`
   objects whose `files` hold per-file `(path, adds, dels)`, with renames resolved
   to the new path and binary files as 0. Results are LRU-cached by `(scope, HEAD)`.
   The worker also loads tags, the repo's first commit date, and
   `Exclusions.load(repo_root)`, then runs `exclusions.apply(commits)`.
3. `EvolutionScreen._show()` picks the commits for the mode (authored or
   everything), applies the `t` time filter (`base_size` = net lines before the
   cutoff, so volume mode's size starts at the right height), sets
   `FrequencyView.history_start`, and hands the commits to both views.
4. The views compute everything through pure functions in `gvt/evolution.py`.
   They never call git.
5. `Enter` posts `PeriodChosen` → `CommitSearchModal` with that period's commits →
   `CommitFilesModal` (skipped for a file scope) → the screen dismisses with
   `(path, sha)` → `GVTApp._load_file(path, focus_sha=sha)` opens the timeline on
   that commit.

### Rules to keep

- Binning, scaling and label layout belong in `gvt/evolution.py`, pure and
  unit-tested; the widgets only render.
- Exclusions are applied in memory to per-file stats, never as git pathspecs, so
  `x` toggles instantly and regex rules work.
- Exclusions affect only the Evolution screen. The timeline, diffs, blame, commit
  search and the file picker always show everything.
- While an `EvolutionScreen` is on the stack, `GVTApp.check_action` disables every
  app binding except those in `_EVOLUTION_ALLOWED_ACTIONS` (quit, help). New app
  bindings are blocked there automatically; add them to that set only if they make
  sense over the Evolution screen.
- The legend (`LEGENDS` in `evolution_screen.py`) drops entries with the highest
  priority number first on narrow terminals. Keep `x`, `X`, `Enter` and `Esc` at
  priority 1–2.
- The frequency axis spans `history_start` (repo's first commit or the
  time-filter cutoff) to today, at the finest granularity that fits (day, week,
  month, year), with at least `MIN_PERIODS` periods.

### Exclusion rules (`gvt/exclusions.py`)

- Layers, applied in order, last match wins, `!` re-includes: built-in `PRESETS`
  (`DEFAULT_PRESETS` on), `.gitattributes` linguist attributes, the user config
  (`user_config_path()`: `$GVT_CONFIG` or `~/.config/gvt/config.toml`), then the
  repo's `.gvt.toml`. Within config files, scalars (`default_mode`, `presets`,
  `use_gitattributes`, `ignore_revs`) are replaced by the later file and lists
  (`exclude`, `ignore_files`) are appended.
- Patterns are gitignore-style globs (`glob_to_regex`); `re:` marks a regex;
  `ignore_files` entries can set `syntax = "regex"` for a whole file.
- `Exclusions.apply()` returns a `FilterResult`: kept commits (new objects;
  inputs are never mutated), excluded line totals, lines and file counts per rule,
  per-file details, and the largest kept files. `Exclusions.layers` records how
  each layer resolved; the `X` details modal (`ExclusionDetailsModal`) and
  `gvt --show-rules` (`describe()`) render these.
- Config problems become `config.warnings`; they never raise. `load` trims them
  with `_trim_warnings` (`MAX_WARNINGS`, `MAX_WARNING_LENGTH`), and the
  Evolution screen toasts only the first `MAX_WARNING_TOASTS`; `X` lists the rest.
- **Rules from files inside the repo are untrusted** (the repo may come from a
  stranger). Keep these properties, each covered by `TestUntrustedRepoRules`:
  - Globs are matched by the linear-time `Glob` matcher, never compiled to a
    regex. Don't reintroduce `re` for globs; backtracking regexes can hang the
    UI for hours, and Python's `re` holds the GIL.
  - Regex rules from repo files (`.gvt.toml`, in-repo ignore files) are
    skipped unless the **user** config sets `trust_repo_regex`. The repo layer
    can't set it. `.gitattributes` is always glob-only.
  - Paths from the repo layer must resolve inside the repo (`_inside`),
    including through symlinks, and file reads are capped
    (`MAX_RULE_FILE_BYTES`). Patterns (`MAX_PATTERN_LENGTH`,
    `MAX_PATTERN_SEGMENTS`), rules per source (`MAX_RULES_PER_SOURCE`) and
    matched paths (`MAX_MATCH_PATH`) are capped. Character-class ranges stay
    as (low, high) pairs; never expand them into sets.
  - One `Exclusions.load` shares a `_LoadBudget` across every source:
    `ignore_files` entries (`MAX_RULE_FILES_PER_LOAD`, repeats and missing
    paths count), bytes read (`MAX_RULE_BYTES_PER_LOAD`) and accepted rules
    (`MAX_RULES_PER_LOAD`). Each is checked before the next stat, read or
    compile. Going past one raises `LoadBudgetExceeded`; `load` then returns
    an `over_budget` `Exclusions` with no rules or ignore-revs (all history)
    and a warning first in `config.warnings`. New rule sources must read
    through `_read_small(..., budget)` and add rules through `add()`.
  - `rule_for` scans rules newest-first and stops at the first match (same
    result as "last match wins", much cheaper). `Glob` caches per-segment
    results. `apply(should_stop=...)` lets the screen's worker stop when it's
    cancelled, and `apply` gives up on exclusions (`over_budget`, show
    everything) after `MATCH_BUDGET_SECONDS`, so the worst case is bounded.
  - Config values are type-checked in `_read_layer`; malformed config becomes
    a warning and never raises.
- `EvolutionScreen._apply_history` drops results whose scope no longer
  matches `self.scope`: a slow load can finish after `u` widened the scope.
- **When you change `PRESETS`, update the presets table in README.md.**
  `test_readme_lists_every_preset_pattern` fails if they drift.

### Untrusted repository content

gvt is often run in repos the user didn't write, so everything read from a repo
(commit messages, author names, file names and contents, `.gitattributes`,
`.gvt.toml`) is untrusted:

- Text shown on screen goes through `gvt.textsafe.safe_text()` at the
  `GitRepo` boundary, so control characters and bidi controls are displayed as
  escapes and never reach the terminal.
- Never put repo text into Textual markup: escape it with
  `textual.markup.escape()` (border titles), pass `markup=False` to `notify()`,
  and give `Label`/`Static`/tree nodes `Text` objects, not strings.
- Git runs with literal pathspecs (`GIT_LITERAL_PATHSPECS=1`),
  `core.quotePath=false` and `core.fsmonitor=false`, and diffs and blame use
  `--no-ext-diff --no-textconv`. Keep paths after `--`.
- `tests/test_hostile_repo.py` exercises all of this against a hostile repo;
  add a case there when adding a new place that shows repo content.

### Helping a user configure exclusions

1. Run `gvt --show-rules` in their repo, or open `v` and press `X`, to see what is
   excluded, which files each rule caught, and the largest files still counted.
   The latter flags files a preset that's off would catch.
2. Put repo-specific paths in a committed `.gvt.toml`; put personal preferences
   that apply everywhere in `~/.config/gvt/config.toml`. Ask before editing the
   user's config file.
3. Remember that `presets` replaces the defaults (list every preset you want),
   while `exclude` adds to them. Use `!pattern` to re-include and `re:` for a
   regular expression.
4. Run `gvt --show-rules` again to confirm, and check its warnings section.

## Code Conventions

### Imports
- All imports at the top of the file — no inline or lazy imports inside functions
- Exception: `import re` inside `_parse_diff` is acceptable (single-use in hot path)

### Colors
- Tokyo Night palette defined as constants in each widget file
- Keep color definitions close to where they're used (not a central colors.py)

### Gitpython Gotchas
- **Never use `commit.tree / path`** — crashes on large repos with `IndexError: index out of range`
- Use `self.repo.git.show(f"{commit}:{path}")` for file content
- Use `self.repo.git.ls_tree("-r", "--name-only", "HEAD")` for tracked files
- Use `self.repo.git.diff(...)` with explicit flags for diffs

## Testing Workflow

Two layers of tests live in this repo:

1. **Unit / integration tests** — `tests/test_*.py`, run with `pytest -q` (~350 tests)
2. **End-to-end tests** — `tests/e2e/*.sh`, a bash+tmux harness that exercises
   the installed `gvt` binary against real temp git repos. Sections:
   - `section_A.sh` — CLI lifecycle (A1–A14)
   - `section_G.sh` — logging file creation & rotation (G1–G5)
   - `section_I.sh` — crash recovery & resilience (I1–I5)
   - Runner: `bash tests/e2e/run_all.sh` (emits TAP + JUnit XML)

**Whenever you're asked to test, run, or verify gvt, do BOTH layers:**

- Run `pytest -q` for unit/integration coverage
- Run `bash tests/e2e/run_all.sh` for CLI behavior (requires `venv-e2e/`
  with `gvt` installed; create once with
  `python3 -m venv venv-e2e && venv-e2e/bin/pip install -e .`)

Supplement with manual TUI testing for things e2e can't easily cover
(timeline scrubbing feel, diff rendering, side-by-side, blame overlays, the
Evolution charts at 80 columns and at a wide size).

Test notes:
- An autouse fixture in `tests/conftest.py` points `$GVT_CONFIG` at a missing
  file, so a developer's personal config never changes test results. Tests that
  need a user config pass `user_config=` or set `GVT_CONFIG` themselves.
- Evolution view tests pass `tz=UTC` and pin `FrequencyView.today`, so they don't
  depend on the machine's time zone or clock.
- `tests/e2e/run_all.sh` repeats every scenario inline instead of sourcing the
  section files, so add a new scenario to both its section file and `run_all.sh`.

Do NOT modify `src/` to make e2e scenarios pass — if an e2e test fails,
it has found a real bug. Triage in `tests/e2e/FAILURES.md`.

## Git Workflow

- Work happens on feature branches off `main`
- `main` has branch protection enabled (enforce admins, no force push)
- Merges to `main` via PR on GitHub

## Release Workflow

- Always merge to `main` via PR before publishing to PyPI
- Never publish from an unmerged branch

## Versioning

Follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

Version is set in two places (keep in sync):
- `pyproject.toml` → `version`
- `src/gvt/__init__.py` → `__version__`

Published on PyPI as `git-visual-timeline` — CLI command is `gvt`.
