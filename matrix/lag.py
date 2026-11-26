"""Live-data delay, so the panel doesn't beat your TV or stream.

Lagged(fn, delay) remembers what fn(*key) returned and when. Calling it returns what fn
returned about `delay()` seconds ago; .fresh(*key) returns the real-time value (and remembers
it too). Watchers poll .fresh() every 30 s, so there's always a snapshot close to the delay.
Before anything is that old (right after starting), the oldest snapshot is used.
"""
import threading
import time


class Lagged:
    def __init__(self, fn, delay):
        self.fn, self.delay = fn, delay          # delay: callable -> seconds (reads current settings)
        self.hist, self.lock = {}, threading.Lock()

    def fresh(self, *key):
        value = self.fn(*key)
        now = time.time()
        with self.lock:
            h = self.hist.setdefault(key, [])
            h.append((now, value))
            cutoff = now - max(0, self.delay())
            while len(h) > 1 and h[1][0] <= cutoff:  # keep the newest old-enough snapshot and later
                h.pop(0)
        return value

    def __call__(self, *key):
        try:
            value = self.fresh(*key)
        except Exception:
            if not self.hist.get(key):
                raise                                # nothing remembered either
            value = None
        if self.delay() <= 0 and value is not None:
            return value
        cutoff = time.time() - self.delay()
        with self.lock:
            h = self.hist[key]
            old = [v for t, v in h if t <= cutoff]
            return old[-1] if old else h[0][1]
