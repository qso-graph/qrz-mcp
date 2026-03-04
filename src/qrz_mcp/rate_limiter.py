"""Rate limiter with token bucket, minimum delay, and freeze on errors."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Thread-safe rate limiter for QRZ API calls.

    - 500ms minimum delay between requests
    - Token bucket: 35 requests per minute
    - Freeze on auth failure (60s) or connection refused / IP ban (3600s)
    """

    def __init__(
        self,
        min_delay: float = 0.5,
        tokens_per_min: int = 35,
    ) -> None:
        self._min_delay = min_delay
        self._max_tokens = tokens_per_min
        self._tokens = float(tokens_per_min)
        self._last_call = 0.0
        self._last_refill = time.monotonic()
        self._frozen_until = 0.0
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * (self._max_tokens / 60.0))
        self._last_refill = now

    def wait(self) -> None:
        """Block until a request is allowed."""
        with self._lock:
            now = time.monotonic()

            # Respect freeze
            if now < self._frozen_until:
                wait = self._frozen_until - now
                self._lock.release()
                time.sleep(wait)
                self._lock.acquire()
                now = time.monotonic()

            # Refill tokens
            self._refill()

            # Wait for token
            if self._tokens < 1.0:
                deficit = 1.0 - self._tokens
                wait = deficit * (60.0 / self._max_tokens)
                self._lock.release()
                time.sleep(wait)
                self._lock.acquire()
                self._refill()

            # Enforce minimum delay
            since_last = now - self._last_call
            if since_last < self._min_delay:
                self._lock.release()
                time.sleep(self._min_delay - since_last)
                self._lock.acquire()

            self._tokens -= 1.0
            self._last_call = time.monotonic()

    def freeze_auth(self) -> None:
        """Freeze for 60 seconds on auth failure."""
        with self._lock:
            self._frozen_until = time.monotonic() + 60.0

    def freeze_ban(self) -> None:
        """Freeze for 1 hour on connection refused (IP ban)."""
        with self._lock:
            self._frozen_until = time.monotonic() + 3600.0
