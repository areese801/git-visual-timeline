# gvt — Git Visual Timeline

## Context

Inspecting the history of a single file in git is cumbersome. `git log --follow` gives a wall of text. GUIs like GitKraken visualize this well but are heavy, mouse-driven, and not terminal-native. There is no keyboard-oriented TUI that lets you scrub through a file's commit history on a visual timeline and instantly see diffs between any two points.

`gvt` fills this gap: a fast, colorful, keyboard-driven TUI for exploring the commit history of any file in a git repo. Think lazygit meets a video timeline scrubber, focused on per-file history.

---

## Overview

`gvt` is a Python TUI built with Textual. It presents three panes:

1. **File tree** (left) — full directory tree of the repo for selecting a file
2. **Timeline + commit messages** (top-right) — horizontal timeline with heatmap-colored ticks per commit, two independent cursors for range selection, and a two-row commit message preview
3. **Diff viewer** (bottom-right) — syntax-highlighted diff between the two selected commits

The user navigates entirely by keyboard, with vim-style keys, arrow keys, and numbered pane switching (lazygit-style).

---

## Architecture

### Approach: Monolithic Textual App with Async Cache

A single Textual `App` owns all widgets. Git operations are handled by a `GitRepo` wrapper (using `gitpython`). An LRU cache (`DiffCache`) stores computed diffs keyed by `(file_path, commit_a, commit_b)`. Expensive operations (diffs, blame) run in Textual `@work` async workers to keep the UI responsive.

This is simpler than a client-server split while still providing instant navigation for previously viewed diffs.

### Dependencies

| Package | Purpose |
|---|---|
| `textual` | TUI framework — layout, widgets, keybindings, CSS styling |
| `gitpython` | Git operations — log, diff, blame, file listing |
| `pygments` | Syntax highlighting for diffs |
| `thefuzz` | Fuzzy string matching for commit and file search modals |

**Dev dependencies**: `pytest`, `textual-dev`, `ruff`

---

## Components

### Widgets

| Widget | Pane | Responsibility |
|---|---|---|
| `FileTreeWidget` | `[1] Files` | Full recursive directory tree, j/k/arrow nav, inline fuzzy filter (`/`), expand/collapse dirs |
| `TimelineWidget` | `[2] Timeline` | Horizontal commit timeline with heatmap ticks, two independent cursors `[`/`]`, range highlight |
| `CommitMessageBar` | `[3] Commits` | Two rows between timeline and diff — one per cursor. First line of message, truncated with `+N lines` badge for multiline. Press Enter/m to expand full popup |
| `DiffViewWidget` | `[4] Diff` | Syntax-highlighted diff (Pygments), inline and side-by-side toggle, scrollable, line numbers |
| `CommitSearchModal` | Overlay | fzf-style fuzzy search over commit messages for current file. Results show hash, date, message (matched text highlighted), +/- stats |
| `FileSearchModal` | Overlay | Ctrl+P / `f` fuzzy file picker across all tracked files |
| `CommitDetailPopup` | Overlay | Full commit message, author, date, file stats. Opened from CommitMessageBar |
| `BlameView` | Alternate for `[4]` | Line-by-line blame annotation in the diff pane (v1 stretch) |
| `StatusBar` | Footer | Current file, commit position, branch, change stats, active mode |

### Data Layer

| Module | Responsibility |
|---|---|
| `GitRepo` | Wraps gitpython. Provides: `get_file_commits(path)`, `get_diff(path, a, b)`, `get_blame(path, commit)`, `get_tracked_files()`, `get_branches()` |
| `DiffCache` | LRU cache (~100 entries) keyed by `(file_path, commit_a_hash, commit_b_hash)`. Populated by async workers. Cache miss triggers `@work` background computation |

---

## Data Flow

```
User selects file in tree
  -> GitRepo.get_file_commits(path) -> list of commits with stats
  -> TimelineWidget renders ticks with heatmap colors
  -> Cursors default: [ = first commit, ] = latest commit
  -> CommitMessageBar shows both messages
  -> DiffCache.get_or_compute(path, commit_a, commit_b)
      -> cache hit: instant render
      -> cache miss: @work async worker calls git diff,
         populates cache, triggers DiffViewWidget refresh

User moves a cursor
  -> CommitMessageBar updates that row
  -> DiffCache lookup (same flow as above)
  -> DiffViewWidget re-renders

User opens commit search (c)
  -> GitRepo returns all commits for current file
  -> CommitSearchModal fuzzy-matches against messages
  -> User selects -> cursor jumps -> triggers diff reload

User opens file search (f / Ctrl+P)
  -> GitRepo.get_tracked_files() (cached)
  -> FileSearchModal fuzzy-matches against paths
  -> User selects -> equivalent to selecting in file tree
```

---

## Keybindings

### Global

| Key | Action |
|---|---|
| `1` / `2` / `3` / `4` | Jump to pane: Files / Timeline / Commits / Diff |
| `Tab` / `Shift+Tab` | Cycle panes forward / back |
| `?` | Help overlay |
| `q` | Quit |
| `c` | Open commit search modal |
| `f` / `Ctrl+P` | Open file search modal |
| `b` | Toggle blame view in diff pane (v1 stretch) |
| `d` | Toggle inline / side-by-side diff (v1 stretch) |

### File Tree (Pane 1)

| Key | Action |
|---|---|
| `j` / `k` / `Up` / `Down` | Navigate files |
| `Enter` | Select file, load its timeline |
| `/` | Activate inline filter (type to narrow, Esc to clear) *(v1 stretch)* |
| `o` | Expand / collapse directory |

### Timeline (Pane 2)

| Key | Action |
|---|---|
| `h` / `l` / `Left` / `Right` | Move `[` cursor |
| `H` / `L` / `Shift+Left` / `Shift+Right` | Move `]` cursor |
| `0` / `$` | Jump cursor to first / last commit |
| `s` | Swap `[` and `]` positions |

### Commit Messages (Pane 3)

| Key | Action |
|---|---|
| `j` / `k` / `Up` / `Down` | Toggle focus between the two rows |
| `Enter` / `m` | Expand full message popup for focused row |

### Diff (Pane 4)

| Key | Action |
|---|---|
| `j` / `k` / `Up` / `Down` | Scroll diff |
| `g` / `G` | Jump to top / bottom of diff |
| `n` / `N` | Jump to next / previous hunk |

### Modals

| Key | Action |
|---|---|
| `Esc` | Close modal |
| `Up` / `Down` | Navigate results |
| `Enter` | Select (jump to commit or file) |
| `Ctrl+[` | Set result as `[` cursor (commit search) |
| `Ctrl+]` | Set result as `]` cursor (commit search) |

---

## Visual Design

### Color Palette (Tokyo Night)

| Element | Hex |
|---|---|
| Background | `#1a1b26` |
| Panel borders (unfocused) | `#3b4261` |
| Primary text | `#c0caf5` |
| Dimmed text | `#565f89` |
| Accent / `[` cursor | `#7aa2f7` |
| `]` cursor | `#bb9af7` |
| Additions | `#9ece6a` |
| Deletions | `#f7768e` |
| Mixed / warnings | `#e0af68` |
| Status bar background | `#7aa2f7` |
| Selected item background | `#283457` |

### Timeline Heatmap

- Tick **color**: green (pure adds) -> amber (mixed) -> red (pure deletes)
- Tick **height**: proportional to total lines changed (capped at max)
- Tick **opacity**: increases with magnitude
- Range between `[` and `]` highlighted with a gradient bar

### Pane Chrome

- Each pane has a labeled border: `[1] Files`, `[2] Timeline`, `[3] Commits`, `[4] Diff`
- Focused pane border brightens to accent blue
- Unfocused pane borders stay dim

### Diff Styling

- Pygments syntax highlighting with dark theme
- Added lines: subtle green background tint (`#1f2d1f`)
- Removed lines: subtle red background tint (`#2d1f1f`)
- Line numbers in dimmed gutter

---

## Project Structure

```
git-visual-timeline/
├── pyproject.toml              # Package config, entry point: gvt
├── README.md
├── src/
│   └── gvt/
│       ├── __init__.py         # Version
│       ├── app.py              # Main Textual App, keybindings, layout
│       ├── widgets/
│       │   ├── __init__.py
│       │   ├── file_tree.py    # FileTreeWidget
│       │   ├── timeline.py     # TimelineWidget
│       │   ├── commit_bar.py   # CommitMessageBar
│       │   ├── diff_view.py    # DiffViewWidget + BlameView
│       │   ├── status_bar.py   # StatusBar
│       │   └── modals.py       # CommitSearchModal, FileSearchModal, CommitDetailPopup
│       ├── git/
│       │   ├── __init__.py
│       │   ├── repo.py         # GitRepo wrapper
│       │   └── cache.py        # DiffCache (LRU)
│       ├── styles/
│       │   └── app.tcss        # Textual CSS for layout and theming
│       └── cli.py              # CLI entry point (argparse), launches App
└── tests/
    ├── __init__.py
    ├── test_git_repo.py
    ├── test_cache.py
    └── test_widgets.py
```

### Entry Point

`pyproject.toml` defines:
```toml
[project.scripts]
gvt = "gvt.cli:main"
```

Invocation:
- `gvt` — opens TUI in current repo, file tree visible
- `gvt path/to/file` — opens directly to that file's timeline
- `gvt --version` — print version and exit
- `gvt --help` — print usage and exit

### Error Handling

- **Not a git repo**: print `"Error: not a git repository (or any parent)"` and exit 1
- **File has no commits**: show empty timeline with a message: `"No commits found for this file"`
- **Binary file selected**: show message in diff pane: `"Binary file — diff not available"`
- **File argument doesn't exist**: print `"Error: file not found: <path>"` and exit 1

---

## Scope & Prioritization

### v1 Core (must ship)

- Three-pane layout (file tree, timeline + commit msgs, diff)
- Full directory tree with j/k/arrow navigation
- Horizontal timeline with heatmap ticks
- Two independent cursors `[`/`]` with range diff
- Commit message bar (two rows, truncated, expand popup)
- Syntax-highlighted diff (inline mode)
- Commit search modal (`c`)
- File search modal (`f` / `Ctrl+P`)
- Numbered pane switching (`1`/`2`/`3`/`4`)
- `gvt` CLI entry point, optional `gvt <file>` to jump directly
- LRU diff cache with async workers
- Tokyo Night color scheme
- PyPI distribution (`pip install git-visual-timeline`)

### v1 Stretch (if time allows)

- Side-by-side diff mode (toggle with `d`)
- Blame view (toggle with `b`)
- Branch awareness (show branch name per commit, switch branches)
- Inline file tree filter (`/` in file pane)

### v2 Future

- `--theme` flag / config file for alternative color schemes
- Live file watching (refresh timeline on new commits)
- Multi-file diff (select multiple files, combined timeline)
- Stash / WIP awareness on timeline
- `git vt` subcommand alias
- Homebrew formula

---

## Testing & Verification

### Unit Tests

- `test_git_repo.py` — test GitRepo wrapper against a fixture repo (created in test setup with known commits and file history)
- `test_cache.py` — test LRU eviction, cache hit/miss, key generation

### Widget Tests (textual-dev)

- Mount each widget in isolation, verify rendering
- Test keybinding dispatch (e.g. pressing `h` moves `[` cursor left)
- Test cursor boundary conditions (can't go past first/last commit)
- Test modal open/close lifecycle

### Integration Tests

- Launch full App against a fixture repo
- Simulate: select file -> move cursors -> verify diff pane updates
- Simulate: open commit search -> type query -> select result -> verify cursor jumps

### Manual Verification Checklist

1. `pip install -e .` in a real git repo
2. Run `gvt` — app launches, file tree populates
3. Select a file with many commits — timeline renders with heatmap ticks
4. Move `[` and `]` cursors — diff updates, commit messages update
5. Press `Enter` on a multiline commit — popup shows full message
6. Press `c` — commit search opens, fuzzy matching works
7. Press `f` — file search opens, selecting a file switches the timeline
8. Press `1`/`2`/`3`/`4` — pane focus jumps correctly
9. Run `gvt path/to/specific/file` — opens directly to that file's timeline
