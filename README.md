# gvt — Git Visual Timeline

A keyboard-driven TUI for exploring the commit history of any file in a git repo. Think lazygit meets a video timeline scrubber, focused on per-file history.

## Install

```bash
pip install git-visual-timeline
```

## Usage

```bash
# Open in any git repo
gvt

# Jump directly to a file
gvt path/to/file.py
```

## Features

- **Visual timeline** with heatmap-colored ticks (green=adds, red=deletes, amber=mixed)
- **Step-through mode** — scrub one commit at a time to see what changed
- **Pin mode** — press `x` to mark start/end and diff any two commits, `X` to snap nearest pin
- **Syntax-highlighted diffs** with inline, whole-file, and side-by-side views
- **Diff search** (`/`) — regex search within the diff with `n`/`p` to navigate matches
- **Commit search** (`c`) — fuzzy search all repo commits by message, branch name, or author, then drill into changed files
- **File search** (`f`) — fzf-style file picker
- **Time filter** (`t`) — filter timeline by date range (1w, 1m, 3m, 6m, 1y, custom date)
- **Inline blame** (`b`) — right-aligned blame annotations
- **Contributor breakdown** (`B`) — visual bar chart of who changed the file
- **WIP indicator** — hollow tick showing uncommitted changes on the timeline
- **Changed files pane** — see all files touched by the current commit, select to navigate
- **Side-by-side diff** (`d`) — toggle between inline and side-by-side diff views
- **Copy to clipboard** (`y`/`Y`) — copy short or full commit hash
- **Open in editor** (`e`) — open current file in `$VISUAL`/`$EDITOR`/vim
- **Remember last file** — reopens to the last file you were viewing per repo
- **5-pane layout** with numbered switching (1-5) and Ctrl+hjkl navigation
- **tmux integration** — seamless pane switching at edges (add `gvt` to your `is_vim` regex)
- **Lazy file tree** — loads directories on demand for large repos
- **Preloaded diffs** — adjacent commits pre-cached for instant navigation
- **Context-sensitive status bar** showing relevant shortcuts per pane
- **Untracked files** — shown in a separate section, viewable as read-only preview

## Keybindings

### Global

| Key | Action |
|-----|--------|
| `1`-`5` | Jump to pane |
| `Ctrl+h/j/k/l` | Navigate panes directionally |
| `c` | Search commits (all repo) |
| `f` / `Ctrl+P` | Search files |
| `t` | Time filter |
| `w` | Toggle whole-file view |
| `d` | Toggle side-by-side diff |
| `b` | Toggle inline blame |
| `B` | Contributor breakdown |
| `/` | Search in diff |
| `n`/`p` | Next/prev diff hunk |
| `y` / `Y` | Copy short/full commit hash |
| `e` | Open file in editor |
| `?` | Help |
| `q` | Quit (with confirmation) |
| `qq` | Quit immediately |

### Timeline (Pane 2)

| Key | Action |
|-----|--------|
| `h`/`l` | Move cursor |
| `0`/`$` | Jump to first/last commit |
| `x` | Pin commit (1st=start, 2nd=end, 3rd=clear) |
| `X` | Snap nearest pin to cursor |

### Diff (Pane 4)

| Key | Action |
|-----|--------|
| `j`/`k` | Scroll |
| `g`/`G` | Top/bottom |
| `+`/`-` or `m`/`l` | More/less context lines |
| `Shift+Left/Right` | Horizontal scroll |

### Search Modals

| Key | Action |
|-----|--------|
| `Tab` / `Shift+Tab` | Navigate results |
| `Ctrl+n` / `Ctrl+p` | Navigate results (alternative) |
| `Enter` | Select |
| `Esc` | Close |

## Requirements

- Python 3.10+
- A git repository

## License

MIT
