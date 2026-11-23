"""Open Matrix Ticker when you sign in to Windows (hidden in the system tray).

Uses the same per-user registry entry as the installer's "Start when Windows starts" box:
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run, value "MatrixTicker".
Installed app: runs MatrixTicker.exe --tray. From source: runs pythonw.exe gui.py --tray.
"""
import os
import sys

KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "MatrixTicker"


def command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")      # no console window
    if os.path.exists(pyw):
        exe = pyw
    gui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui.py")
    return f'"{exe}" "{gui}" --tray'


def enabled():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            winreg.QueryValueEx(k, NAME)
            return True
    except OSError:
        return False


def set_enabled(on):
    """Returns an error message or None."""
    if sys.platform != "win32":
        return "Starting with Windows only works on Windows."
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except FileNotFoundError:
                    pass
    except OSError as e:
        return f"Couldn't change startup setting: {e}"
    return None
