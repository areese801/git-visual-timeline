"""Tests for DiffCache."""

from gvt.git.cache import DiffCache


def test_cache_miss_calls_compute():
    cache = DiffCache(max_size=10)
    called = []

    def compute():
        called.append(1)
        return "diff content"

    result = cache.get_or_compute("file.py", "aaa", "bbb", compute)
    assert result == "diff content"
    assert len(called) == 1


def test_cache_hit_skips_compute():
    cache = DiffCache(max_size=10)
    call_count = 0

    def compute():
        nonlocal call_count
        call_count += 1
        return "diff content"

    cache.get_or_compute("file.py", "aaa", "bbb", compute)
    cache.get_or_compute("file.py", "aaa", "bbb", compute)
    assert call_count == 1


def test_cache_different_keys():
    cache = DiffCache(max_size=10)
    cache.get_or_compute("a.py", "aaa", "bbb", lambda: "diff1")
    cache.get_or_compute("b.py", "aaa", "bbb", lambda: "diff2")
    assert len(cache) == 2


def test_lru_eviction():
    cache = DiffCache(max_size=3)
    cache.get_or_compute("a.py", "1", "2", lambda: "d1")
    cache.get_or_compute("b.py", "1", "2", lambda: "d2")
    cache.get_or_compute("c.py", "1", "2", lambda: "d3")
    # This should evict "a.py"
    cache.get_or_compute("d.py", "1", "2", lambda: "d4")

    assert len(cache) == 3
    assert cache.get("a.py", "1", "2") is None
    assert cache.get("d.py", "1", "2") == "d4"


def test_lru_access_refreshes():
    cache = DiffCache(max_size=3)
    cache.get_or_compute("a.py", "1", "2", lambda: "d1")
    cache.get_or_compute("b.py", "1", "2", lambda: "d2")
    cache.get_or_compute("c.py", "1", "2", lambda: "d3")
    # Access "a" to refresh it
    cache.get_or_compute("a.py", "1", "2", lambda: "should not be called")
    # Now "b" is oldest, adding "d" should evict "b"
    cache.get_or_compute("d.py", "1", "2", lambda: "d4")

    assert cache.get("b.py", "1", "2") is None
    assert cache.get("a.py", "1", "2") == "d1"


def test_clear():
    cache = DiffCache(max_size=10)
    cache.get_or_compute("a.py", "1", "2", lambda: "d1")
    cache.clear()
    assert len(cache) == 0
