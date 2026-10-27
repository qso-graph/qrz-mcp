"""Rate limiter with token bucket, minimum delay, and freeze on errors.

Three mechanisms, kept distinct: spacing (the minimum gap and the token
bucket), a freeze after QRZ refuses us, and the interval a 429 asks for. See
qso-graph-devel/planning/MCP-SECURITY-FRAMEWORK.md.
"""

from __future__ import annotations

import threading
import time

MIN_BACKOFF = 60.0
MAX_BACKOFF = 3600.0


class RateLimited(RuntimeError):
    """QRZ asked us to stop. The message is safe to show a user.

    A RuntimeError subclass so callers that already handle this client's
    failures keep working, and so FastMCP flags the tool result isError either
    way.
    """

    def __init__(self, wait_seconds: float) -> None:
        self.retry_after = max(1, round(wait_seconds))
        super().__init__(
            "QRZ is rate limiting this client; try again in "
            f"{self.retry_after} s"
        )


def retry_after(header: str | None) -> float:
    """Seconds to wait, from a Retry-After header, clamped to our bounds.

    Retry-After may also be an HTTP date. That form is not parsed and falls back
    to the floor rather than guessing, because a wrong parse would either hammer
    QRZ or strand the user.
    """
    try:
        seconds = float(header) if header else 0.0
    except ValueError:
        seconds = 0.0
    return min(max(seconds, MIN_BACKOFF), MAX_BACKOFF)


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
        self._tokens = min(
            self._max_tokens, self._tokens + elapsed * (self._max_tokens / 60.0),
        )
        self._last_refill = now

    def wait(self) -> None:
        """Allow a request through, or refuse if QRZ has told us to stop.

        Two different waits live here and they are treated differently.

        The short ones are slept: the minimum gap between requests, and a
        token-bucket deficit, which at 35 a minute is under two seconds. Those
        are spacing, and sleeping them is the whole point.

        A freeze is not slept. It lasts a minute after an auth failure and an
        hour after an apparent IP ban, and this server answers a synchronous
        tool call behind a client timeout -- so sleeping one out is a hang, not
        restraint. It used to: a user whose address QRZ had blocked got an hour
        of silence from every tool rather than a sentence telling them what had
        happened. Now it raises, and the message says how long.

        The sleeps are taken outside the lock rather than by releasing and
        re-acquiring it mid-block, which left the lock unheld if a sleep was
        interrupted and then failed on the way out.
        """
        while True:
            with self._lock:
                now = time.monotonic()
                remaining = self._frozen_until - now
                if remaining > 0:
                    raise RateLimited(remaining)

                self._refill()

                if self._tokens < 1.0:
                    deficit = 1.0 - self._tokens
                    delay = deficit * (60.0 / self._max_tokens)
                else:
                    since_last = now - self._last_call
                    if since_last < self._min_delay:
                        delay = self._min_delay - since_last
                    else:
                        self._tokens -= 1.0
                        self._last_call = now
                        return
            time.sleep(delay)

    def freeze(self, seconds: float) -> None:
        """Send nothing to QRZ for this long. Replaces any shorter freeze."""
        with self._lock:
            self._frozen_until = max(
                self._frozen_until, time.monotonic() + seconds
            )

    def freeze_auth(self) -> None:
        """Freeze for 60 seconds on auth failure."""
        self.freeze(60.0)

    def freeze_ban(self) -> None:
        """Freeze for 1 hour on connection refused (IP ban)."""
        self.freeze(3600.0)

    def note_429(self, header: str | None) -> float:
        """Honour a 429: freeze for the interval QRZ asked for, bounded.

        A 429 carrying Retry-After is QRZ stating its limit outright, which is
        the most explicit form of the stated limit guarantee 8 requires
        honouring. The interval is bounded rather than taken verbatim: a header
        asking for a day would strand an interactive tool, and one asking for
        nothing would let us hammer. Returns the interval, for the error the
        caller raises.
        """
        seconds = retry_after(header)
        self.freeze(seconds)
        return seconds
