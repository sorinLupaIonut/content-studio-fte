"""A ceiling on accidents, not a security boundary.

The budget gate in `accounts.py` bounds what a person may deliberately spend.
This bounds what a *mistake* can do in a minute: a page left in a retry loop, a
held-down button, a script someone points at the API. The two are different
problems and they are answered separately - a rate limit that tried to enforce
money would have to know the price of a request before serving it, which is the
same thing the budget gate cannot know either.

The counter lives in memory, so it is per replica. With `minReplicas: 1` that is
the whole story; scaled out to three replicas the effective limit is three times
the number, which is the correct trade to make here - a shared counter would
mean a Redis, and a Redis for three users is a second thing to keep alive for no
gain. The number is a guard rail, not an accountancy.
"""

from __future__ import annotations

import time
from collections import deque

from content_studio.config import RATE_LIMIT_PER_MINUTE

WINDOW_SECONDS = 60.0

#: An allowlist, not a denylist. The harness also serves the Blazor application,
#: and a first load of that is several hundred files - counted, it would trip the
#: limit before the page had finished appearing. Only the API is metered.
LIMITED_PREFIXES = ("/api/", "/runs", "/sessions/")

#: Long-lived streams open once and stay open; counting them would punish the
#: page that is behaving.
EXEMPT_SUFFIXES = ("/events",)


class RateLimiter:
    """A sliding window per key, kept as the timestamps still inside it.

    A deque rather than a fixed-window counter because a fixed window lets a
    caller spend the whole allowance in the last second of one window and the
    whole allowance again in the first second of the next - twice the intended
    rate, at exactly the moment something is running away.
    """

    def __init__(self, per_minute: int | None = None) -> None:
        # Read now, not at import: a default evaluated in the signature is
        # frozen when the module first loads, which makes the setting a lie in
        # any process that configures itself after importing - the tests, and
        # anything that ever reloads configuration.
        self.per_minute = RATE_LIMIT_PER_MINUTE if per_minute is None else per_minute
        self._hits: dict[str, deque[float]] = {}

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0

    def retry_after(self, key: str, now: float | None = None) -> int | None:
        """Seconds to wait, or None when the caller is inside the limit."""
        if not self.enabled:
            return None

        moment = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()

        cutoff = moment - WINDOW_SECONDS
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.per_minute:
            # The oldest hit is the one whose expiry frees a slot. Rounded up,
            # so a client that obeys the header never comes back too early.
            wait = hits[0] + WINDOW_SECONDS - moment
            return max(1, int(wait) + (1 if wait % 1 else 0))

        hits.append(moment)
        if not hits:  # pragma: no cover - defensive; a key with no live hits
            self._hits.pop(key, None)
        return None

    def forget(self, key: str) -> None:
        self._hits.pop(key, None)


def is_limited(path: str) -> bool:
    return path.startswith(LIMITED_PREFIXES) and not path.endswith(EXEMPT_SUFFIXES)


def key_for(headers, client_host: str | None) -> str:
    """Who is being limited.

    The principal when Easy Auth put one on the request, the peer address
    otherwise. Not the email: two people can share an address in a way they
    cannot share a principal id, and an unauthenticated flood has no email at
    all.
    """
    principal = headers.get("x-ms-client-principal-id", "").strip()
    if principal:
        return f"principal:{principal}"
    return f"peer:{client_host or 'unknown'}"
