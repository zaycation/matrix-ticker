"""Where settings and saved data live.

- Installed app (Setup.exe, a frozen build): %APPDATA%\\MatrixTicker
- Running from source (python gui.py): the project folder, as before
Set MATRIX_TICKER_DATA to override either.
"""
import os
import sys

APP_NAME = "MatrixTicker"
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir():
    if os.environ.get("MATRIX_TICKER_DATA"):
        return os.environ["MATRIX_TICKER_DATA"]
    if getattr(sys, "frozen", False):
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    return SRC_DIR


DATA_DIR = _data_dir()
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CALIB_FILE = os.path.join(DATA_DIR, "calib.json")
LAYOUTS_DIR = os.path.join(DATA_DIR, "layouts")
RESTORE_FILE = os.path.join(LAYOUTS_DIR, "default.json")
