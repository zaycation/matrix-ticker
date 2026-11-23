"""Ping for the dashboard: round trip to Cloudflare's 1.1.1.1, like `ping 1.1.1.1`.

On Windows this uses the same system call as ping.exe (IcmpSendEcho in iphlpapi.dll), which
needs no admin rights. Elsewhere, or if that fails, it falls back to timing a TCP connection,
which can read noticeably high on Windows (connection setup and security software add time).
A background thread measures every 2 seconds; ping() returns the latest result.
"""
import ctypes
import socket
import struct
import sys
import threading
import time

HOST, PORT = "1.1.1.1", 443
EVERY_S = 2.0
TIMEOUT_S = 1.5
GOOD_MS, OK_MS = 60, 150         # green below 60 ms, gold below 150, red above (or down)

_state = {"ms": None, "fails": 0, "thread": None, "last": 0.0}
_lock = threading.Lock()


_icmp = {"handle": None, "failed": False}


def icmp_ping(host=HOST, timeout=TIMEOUT_S):
    """Real ping through Windows' ICMP API. ms, None if no reply, or raises if unavailable."""
    if sys.platform != "win32":
        raise OSError("ICMP API is Windows-only")
    lib = ctypes.windll.iphlpapi
    if _icmp["handle"] is None:
        lib.IcmpCreateFile.restype = ctypes.c_void_p
        lib.IcmpSendEcho.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint16,
                                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        lib.IcmpSendEcho.restype = ctypes.c_uint32
        handle = lib.IcmpCreateFile()
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError("IcmpCreateFile failed")
        _icmp["handle"] = handle
    addr = int.from_bytes(socket.inet_aton(host), "little")      # IPAddr: network byte order in memory
    data = b"matrix-ticker-ping".ljust(32, b".")
    reply = ctypes.create_string_buffer(256)
    n = lib.IcmpSendEcho(_icmp["handle"], addr, data, len(data), None, reply, len(reply), int(timeout * 1000))
    if not n:
        return None
    _address, status, rtt = struct.unpack_from("<III", reply.raw)  # ICMP_ECHO_REPLY: Address, Status, RTT
    return float(rtt) if status == 0 else None


def measure(host=HOST, port=PORT, timeout=TIMEOUT_S):
    """One round trip in ms, or None if it failed. Real ping when possible."""
    if not _icmp["failed"]:
        try:
            return icmp_ping(host, timeout)
        except Exception:
            _icmp["failed"] = True         # not Windows, or the API isn't there: use TCP from now on
    return tcp_ping(host, port, timeout)


def tcp_ping(host=HOST, port=PORT, timeout=TIMEOUT_S):
    """Time a TCP connection (a round trip plus connection-setup overhead)."""
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
