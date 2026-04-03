# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**gvt** (Git Visual Timeline) is a keyboard-driven Python TUI for exploring per-file git commit history. Built with Textual, it presents a 5-pane layout with a heatmap timeline, syntax-highlighted diffs, commit search, inline blame, and more. Think lazygit meets a video timeline scrubber.

The design spec is at `docs/superpowers/specs/2026-04-02-gvt-design.md`.

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
| `src/gvt/widgets/` | All TUI widgets (timeline, diff_view, file_tree, modals, etc.) |
| `src/gvt/styles/app.tcss` | Textual CSS — Tokyo Night color scheme |

### Design Patterns

- **Async data loading**: File commits, diffs, blame, and commit search all load in background threads via Textual's `@work` decorator. UI stays responsive.
- **LRU cache**: Diffs are cached by `(file, commit_a, commit_b)` to avoid recomputation when navigating back and forth.
- **Message-based communication**: Widgets post messages (e.g. `CursorMoved`, `FileSelected`) that the app handles to coordinate updates across panes.
- **Direct git CLI calls**: Use `self.repo.git.diff(...)` / `self.repo.git.show(...)` instead of gitpython's tree traversal, which crashes on large repos.

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

Before committing:

1. **Run pytest** — `pytest -q` (27 tests currently)
2. **Manual testing** — run `gvt` in a real repo with history and verify:
   - Timeline renders, cursor moves with h/l
   - File search (f) and commit search (c) work
   - Pin mode (x) and time filter (t) work
   - Diff loads, context +/- works, whole file (w) works

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
