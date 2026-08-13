import threading
import time

# Простой in-memory rate limiter (скользящее окно по ключу).
# Для одного воркера/потоков достаточно; при нескольких воркерах лимит
# становится приблизительным — для антибрутфорса это приемлемо.
# В идеале вынести в Redis, если воркеров станет много.

_locks = {}


def _lock_for(key: str) -> threading.Lock:
    lock = _locks.get(key)
    if lock is None:
        with threading.Lock():
            lock = _locks.get(key)
            if lock is None:
                lock = threading.Lock()
                _locks[key] = lock
    return lock


class RateLimiter:
    def __init__(self, max_count: int, window_seconds: int):
        self.max_count = max_count
        self.window = window_seconds
        self._entries = {}
        self._mu = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """(можно_ли_продолжить, сколько_ждать_секунд)"""
        now = time.monotonic()
        with _lock_for(key):
            with self._mu:
                hits = self._entries.get(key, [])
                hits = [t for t in hits if now - t < self.window]
                if len(hits) >= self.max_count:
                    self._entries[key] = hits
                    wait = int(self.window - (now - hits[0])) + 1
                    return False, wait
                hits.append(now)
                self._entries[key] = hits
                return True, 0

    def prune(self):
        now = time.monotonic()
        with self._mu:
            self._entries = {k: [t for t in v if now - t < self.window] for k, v in self._entries.items()}
