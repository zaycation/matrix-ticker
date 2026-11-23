"""Ping for the dashboard: how long a quick connection to the internet takes.

Real ICMP ping needs admin rights on Windows, so this times a TCP connection to Cloudflare's
1.1.1.1 instead (one network round trip, the same number ping shows, give or take a ms).
A background thread measures every 2 seconds; ping() returns the latest result.
"""
import socket
import threading
import time

HOST, PORT = "1.1.1.1", 443
EVERY_S = 2.0
TIMEOUT_S = 1.5
GOOD_MS, OK_MS = 60, 150         # green below 60 ms, gold below 150, red above (or down)

_state = {"ms": None, "fails": 0, "thread": None, "last": 0.0}
_lock = threading.Lock()


def measure(host=HOST, port=PORT, timeout=TIMEOUT_S):
    """One round trip in ms, or None if it failed."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.perf_counter() - t0) * 1000
    except OSError:
        return None


def _loop():
    while True:
        ms = measure()
        with _lock:
            if ms is None:
                _state["fails"] += 1
                if _state["fails"] >= 2:          # one lost packet isn't "down"
                    _state["ms"] = None
            else:
                _state["fails"] = 0
                prev = _state["ms"]
                # light smoothing so the number doesn't jump around every reading
                _state["ms"] = ms if prev is None else 0.5 * prev + 0.5 * ms
            _state["last"] = time.time()
        time.sleep(EVERY_S)


def ping():
    """Latest ping in ms; None if the internet seems down (or no reading yet)."""
    with _lock:
        if _state["thread"] is None:
            _state["thread"] = threading.Thread(target=_loop, daemon=True)
            _state["thread"].start()
        return _state["ms"]


def started():
    """True once at least one reading has come back (so 'no value' means down, not 'not yet')."""
    with _lock:
        return _state["last"] > 0
