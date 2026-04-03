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
    """Full recursive directory tree with tracked and untracked sections."""

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

    def compose(self):
        tree: Tree[str] = Tree(".", id="file-tree-inner")
        tree.show_root = True
        tree.guide_depth = 2
        self._tree = tree

        # Build tree structure from flat file list
        dirs: dict[str, TreeNode] = {}

        def get_or_create_dir(parts: tuple[str, ...], parent: TreeNode) -> TreeNode:
            key = "/".join(parts)
            if key in dirs:
                return dirs[key]
            node = parent.add(parts[-1], data=key, expand=True)
            node.allow_expand = True
            dirs[key] = node
            return node

        for file_path in sorted(self.tracked_files):
            parts = file_path.split("/")
            if len(parts) == 1:
                tree.root.add_leaf(parts[0], data=file_path)
            else:
                parent = tree.root
                for i in range(len(parts) - 1):
                    parent = get_or_create_dir(tuple(parts[: i + 1]), parent)
                parent.add_leaf(parts[-1], data=file_path)

        # Add untracked section
        if self.untracked_files:
            untracked_label = Text("── Untracked ──", style=f"bold {COLOR_UNTRACKED}")
            untracked_node = tree.root.add(untracked_label, data="__untracked_header__", expand=True)
            untracked_node.allow_expand = True

            # Reset dirs for untracked section
            untracked_dirs: dict[str, TreeNode] = {}

            def get_or_create_untracked_dir(parts: tuple[str, ...], parent: TreeNode) -> TreeNode:
                key = "__ut__/" + "/".join(parts)
                if key in untracked_dirs:
                    return untracked_dirs[key]
                label = Text(parts[-1], style=COLOR_DIM)
                node = parent.add(label, data=key, expand=True)
                node.allow_expand = True
                untracked_dirs[key] = node
                return node

            for file_path in sorted(self.untracked_files):
                parts = file_path.split("/")
                label = Text(f"? {parts[-1]}", style=COLOR_DIM)
                if len(parts) == 1:
                    untracked_node.add_leaf(label, data=file_path)
                else:
                    parent = untracked_node
                    for i in range(len(parts) - 1):
                        parent = get_or_create_untracked_dir(tuple(parts[: i + 1]), parent)
                    parent.add_leaf(label, data=file_path)

        tree.root.expand()
        yield tree

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
