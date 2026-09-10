"""Exponential backoff for repeated login failures.

Keyed by the submitted player name rather than the client address: behind the
Cloudflare tunnel every request arrives from 127.0.0.1, and even keyed on
`CF-Connecting-IP` an attacker holding an IPv6 /64 has 2**64 addresses to
rotate through. The set of names is small and fixed, so it is the only key
that cannot be cheaply sidestepped.

State is per-process and in memory on purpose. The alternative -- counting in
the store -- would hand an unauthenticated caller a database write on every
request, and SQLite write-lock contention is already this app's `503 busy`
failure mode. A restart clears the counters, which is fine: restarts are
manual, so an attacker cannot provoke one.
"""
import heapq
import threading

# Entries stay resident this long after their penalty expires, then a later
# failure prunes them. Bounds the table when someone posts junk names.
IDLE_TTL = 300.0
PURGE_ABOVE = 64  # only walk the table once it is worth walking

# Hard ceiling, for a burst of junk names that is still inside IDLE_TTL and so
# cannot be reclaimed by age. Trimming down to a low-water mark amortises the
# sort over the next MAX_ENTRIES/2 failures instead of paying it every time.
MAX_ENTRIES = 1024
KEEP_ENTRIES = MAX_ENTRIES // 2


class Throttle:
    def __init__(self, free: int = 4, cap: float = 300.0):
        self._free = free
        self._cap = cap
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[int, float]] = {}   # key -> (failures, unlock_at)

    def _delay(self, failures: int) -> float:
        """0 while the free attempts last, then 2s doubling up to the cap."""
        if failures <= self._free:
            return 0.0
        return min(2.0 ** (failures - self._free), self._cap)

    def retry_after(self, key: str, now: float) -> float:
        """Seconds the caller must wait before this attempt may be evaluated."""
        with self._lock:
            entry = self._hits.get(key)
        if entry is None:
            return 0.0
        return max(0.0, entry[1] - now)

    def fail(self, key: str, now: float) -> None:
        with self._lock:
            failures = self._hits.get(key, (0, 0.0))[0] + 1
            self._hits[key] = (failures, now + self._delay(failures))
            if len(self._hits) > PURGE_ABOVE:
                self._purge(now)

    def succeed(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def _purge(self, now: float) -> None:
        """Drop entries whose penalty expired and that have since gone idle,
        then enforce the hard ceiling.

        The ceiling evicts by soonest unlock, which is what we want under a
        junk-name flood: a single stray failure carries no penalty and expires
        immediately, while a name being actively guessed has the furthest
        unlock time and is evicted last.
        """
        self._hits = {k: v for k, v in self._hits.items()
                      if v[1] + IDLE_TTL > now}
        if len(self._hits) > MAX_ENTRIES:
            keep = heapq.nlargest(KEEP_ENTRIES, self._hits.items(),
                                  key=lambda kv: kv[1][1])
            self._hits = dict(keep)

    def __len__(self) -> int:
        with self._lock:
            return len(self._hits)
