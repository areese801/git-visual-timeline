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
- **Pin mode** — press `x` to mark start/end and diff any two commits
- **Syntax-highlighted diffs** with inline and whole-file views
- **Commit search** (`c`) — fuzzy search all repo commits by message, branch name, or author, then drill into changed files
- **File search** (`f`) — fzf-style file picker
- **Time filter** (`t`) — filter timeline by date range (1w, 1m, 3m, custom date)
- **Inline blame** (`b`) — right-aligned blame annotations
- **Contributor breakdown** (`B`) — visual bar chart of who changed the file
- **WIP indicator** — hollow tick showing uncommitted changes
- **5-pane layout** with numbered switching (1-5) and Ctrl+hjkl navigation
- **tmux integration** — seamless pane switching at edges (add `gvt` to your `is_vim` regex)
- **Context-sensitive status bar** showing relevant shortcuts per pane

## Keybindings

| Key | Action |
|-----|--------|
| `1`-`5` | Jump to pane |
| `Ctrl+h/j/k/l` | Navigate panes directionally |
| `h`/`l` | Move timeline cursor |
| `x` | Pin start/end commits |
| `X` | Snap nearest pin to cursor |
| `n`/`p` | Next/prev diff hunk |
| `w` | Toggle whole-file view |
| `b` | Toggle inline blame |
| `B` | Contributor breakdown |
| `c` | Search commits (all repo) |
| `f` | Search files |
| `t` | Time filter |
| `+`/`-` | More/less diff context |
| `?` | Help |
| `q` | Quit (with confirmation) |
| `qq` | Quit immediately |

## Requirements

- Python 3.10+
- A git repository

## License

MIT
