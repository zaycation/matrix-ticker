"""Keep Windows from going to sleep on its own while the ticker runs.

The monitors can still turn off; only automatic (idle) sleep is held off. Choosing Sleep
yourself still works: the display loses power then (it runs off the PC's power supply), and
the app reconnects when the PC wakes. The request belongs to the calling thread, so call
keep_awake(True) from the thread that runs the ticker and keep_awake(False) when it ends.
"""
import sys

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def keep_awake(on=True):
    if sys.platform != "win32":
        return False
    import ctypes
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
