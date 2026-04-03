"""LRU diff cache for gvt."""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable


class DiffCache:
    """
    LRU cache for computed diffs, keyed by (file_path, commit_a, commit_b).
    """

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()

    def get_or_compute(
        self,
        file_path: str,
        commit_a: str,
        commit_b: str,
        compute_fn: Callable[[], str],
    ) -> str:
        """
        Return cached diff or compute it and cache the result.
        """
        key = (file_path, commit_a, commit_b)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        value = compute_fn()
        self._cache[key] = value
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)
        return value

    def get(self, file_path: str, commit_a: str, commit_b: str) -> str | None:
        """Return cached diff or None."""
        key = (file_path, commit_a, commit_b)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def has(self, file_path: str, commit_a: str, commit_b: str) -> bool:
        """Check if a diff is already cached."""
        return (file_path, commit_a, commit_b) in self._cache

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)
