"""Writes packaging/icon.ico (used for the .exe and the installer)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from matrix.icon import save_ico  # noqa: E402

save_ico(os.path.join(HERE, "icon.ico"))
print("wrote", os.path.join(HERE, "icon.ico"))
