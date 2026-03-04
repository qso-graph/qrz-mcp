"""Thread-safe in-memory TTL cache for API responses."""

from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    """Simple dictionary cache with per-entry TTL.

    Thread-safe via a single lock. Expired entries are lazily evicted on access.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return cached value or None if missing/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires, value = entry
            if time.monotonic() > expires:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        """Store a value with TTL in seconds."""
        with self._lock:
            self._store[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        """Drop all entries."""
        with self._lock:
            self._store.clear()
