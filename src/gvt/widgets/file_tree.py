"""File tree widget for gvt."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Tree
from textual.widgets._tree import TreeNode

COLOR_DIM = "#565f89"
COLOR_UNTRACKED = "#e0af68"


class FileSelected(Message):
    """Posted when a file is selected in the tree (Enter)."""

    def __init__(self, path: str, tracked: bool = True) -> None:
        self.path = path
        self.tracked = tracked
        super().__init__()


class FileHighlighted(Message):
    """Posted when cursor moves over a file in the tree (debounced)."""

    def __init__(self, path: str, tracked: bool = True) -> None:
        self.path = path
        self.tracked = tracked
        super().__init__()


class FileTreeWidget(Widget, can_focus=True):
    """Lazy-loading recursive directory tree with tracked and untracked sections."""

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("enter", "select_file", "Select"),
        ("o", "toggle_node", "Expand/Collapse"),
    ]

    selected_file: reactive[str] = reactive("")

    def __init__(
        self,
        tracked_files: list[str],
        untracked_files: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.tracked_files = tracked_files
        self.untracked_files = untracked_files or []
        self._tree: Tree[str] | None = None
        self._untracked_set: set[str] = set(self.untracked_files)
        # Pre-group files by directory for lazy loading
        self._dir_children: dict[str, tuple[list[str], list[str]]] = {}  # dir -> (subdirs, files)
        self._loaded_dirs: set[str] = set()  # directories whose children are already in the tree
        self._build_dir_index(self.tracked_files, prefix="")
        # Untracked index
        self._ut_dir_children: dict[str, tuple[list[str], list[str]]] = {}
        self._loaded_ut_dirs: set[str] = set()
        self._build_dir_index(self.untracked_files, prefix="__ut__/", target=self._ut_dir_children)

    def _build_dir_index(
        self,
        files: list[str],
        prefix: str = "",
        target: dict[str, tuple[list[str], list[str]]] | None = None,
    ) -> None:
        """Group flat file paths by their immediate parent directory."""
        if target is None:
            target = self._dir_children
        dirs_seen: dict[str, set[str]] = {}  # parent -> set of child dir names
        files_in: dict[str, list[str]] = {}  # parent -> list of file basenames (full paths)

        for file_path in sorted(files):
            parts = file_path.split("/")
            # Register the file in its parent
            if len(parts) == 1:
                parent_key = prefix.rstrip("/") if prefix else ""
                files_in.setdefault(parent_key, []).append(file_path)
            else:
                parent_key = prefix + "/".join(parts[:-1]) if prefix else "/".join(parts[:-1])
                files_in.setdefault(parent_key, []).append(file_path)

            # Register intermediate directories
            for i in range(len(parts) - 1):
                if i == 0:
                    p_key = prefix.rstrip("/") if prefix else ""
                else:
                    p_key = prefix + "/".join(parts[:i]) if prefix else "/".join(parts[:i])
                child_dir = prefix + "/".join(parts[: i + 1]) if prefix else "/".join(parts[: i + 1])
                dirs_seen.setdefault(p_key, set()).add(child_dir)

        # Consolidate into target
        all_parents = set(dirs_seen.keys()) | set(files_in.keys())
        for p in all_parents:
            subdirs = sorted(dirs_seen.get(p, set()))
            flist = files_in.get(p, [])
            target[p] = (subdirs, flist)

    def compose(self):
        tree: Tree[str] = Tree(".", id="file-tree-inner")
        tree.show_root = True
        tree.guide_depth = 2
        self._tree = tree

        # Only add root-level items (lazy — children loaded on expand)
        self._populate_node(tree.root, "", self._dir_children, self._loaded_dirs)

        # Add untracked section
        if self.untracked_files:
            untracked_label = Text("── Untracked ──", style=f"bold {COLOR_UNTRACKED}")
            untracked_node = tree.root.add(untracked_label, data="__untracked_header__", expand=False)
            untracked_node.allow_expand = True

        tree.root.expand()
        yield tree

    def _populate_node(
        self,
        parent_node: TreeNode,
        dir_key: str,
        index: dict[str, tuple[list[str], list[str]]],
        loaded: set[str],
        is_untracked: bool = False,
    ) -> None:
        """Add immediate children (subdirs + files) of dir_key to parent_node."""
        if dir_key in loaded:
            return
        loaded.add(dir_key)

        subdirs, files = index.get(dir_key, ([], []))

        for subdir in subdirs:
            # Display name is the last component
            display_name = subdir.split("/")[-1]
            if is_untracked:
                label = Text(display_name, style=COLOR_DIM)
            else:
                label = display_name
            node = parent_node.add(label, data=subdir, expand=False)
            node.allow_expand = True

        for file_path in files:
            display_name = file_path.split("/")[-1]
            if is_untracked:
                label = Text(f"? {display_name}", style=COLOR_DIM)
            else:
                label = display_name
            parent_node.add_leaf(label, data=file_path)

    @on(Tree.NodeExpanded)
    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Lazy-load children when a directory node is expanded."""
        event.stop()
        node = event.node
        if not node.data or not isinstance(node.data, str):
            return

        data = node.data
        if data == "__untracked_header__":
            # Load untracked root children
            self._populate_node(
                node, "__ut__", self._ut_dir_children, self._loaded_ut_dirs, is_untracked=True
            )
            # Also handle case where prefix is empty
            self._populate_node(
                node, "", self._ut_dir_children, self._loaded_ut_dirs, is_untracked=True
            )
            return

        # Check if it's an untracked directory
        if data.startswith("__ut__/"):
            self._populate_node(
                node, data, self._ut_dir_children, self._loaded_ut_dirs, is_untracked=True
            )
        else:
            self._populate_node(node, data, self._dir_children, self._loaded_dirs)

    def action_cursor_down(self) -> None:
        if self._tree:
            self._tree.action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._tree:
            self._tree.action_cursor_up()

    def action_select_file(self) -> None:
        if self._tree and self._tree.cursor_node:
            node = self._tree.cursor_node
            if not node.allow_expand and node.data and node.data != "__untracked_header__":
                tracked = node.data not in self._untracked_set
                self.selected_file = node.data
                self.post_message(FileSelected(node.data, tracked=tracked))
            elif node.allow_expand:
                node.toggle()

    def action_toggle_node(self) -> None:
        if self._tree and self._tree.cursor_node:
            self._tree.cursor_node.toggle()

    @on(Tree.NodeSelected)
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        node = event.node
        if not node.allow_expand and node.data and node.data != "__untracked_header__":
            tracked = node.data not in self._untracked_set
            self.selected_file = node.data
            self.post_message(FileSelected(node.data, tracked=tracked))

    def save_expand_state(self) -> set[str]:
        """Save which nodes are currently expanded."""
        expanded = set()
        if self._tree:
            def _walk(node):
                if node.allow_expand and node.is_expanded:
                    key = str(node.data) if node.data else str(node.label)
                    expanded.add(key)
                for child in node.children:
                    _walk(child)
            _walk(self._tree.root)
        return expanded

    def restore_expand_state(self, expanded: set[str]) -> None:
        """Restore previously saved expand state."""
        if self._tree:
            def _walk(node):
                if node.allow_expand:
                    key = str(node.data) if node.data else str(node.label)
                    if key in expanded:
                        node.expand()
                    else:
                        node.collapse()
                for child in node.children:
                    _walk(child)
            _walk(self._tree.root)
            # Always keep root expanded
            self._tree.root.expand()

    def on_show(self) -> None:
        """Re-expand root when the widget becomes visible (e.g. after modal closes)."""
        if self._tree:
            self._tree.root.expand()

    def focus(self, scroll_visible: bool = True) -> Widget:
        if self._tree:
            self._tree.focus(scroll_visible)
        return self
