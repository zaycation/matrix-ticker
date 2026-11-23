"""Look inside NexLinq's install folder for its LED font / widget graphics.

    python tools/nexlinq_assets.py

Read-only: it lists files, nothing is changed. Paste the output back.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from matrix.paths import CONFIG_FILE  # noqa: E402

KEYWORDS = ("font", "glyph", "char", "led", "matrix", "digit", "number", "pixel", "dot", "clock", "widget", "screen")
FONT_EXT = {".ttf", ".otf", ".woff", ".woff2", ".fnt", ".bdf", ".fon"}


def candidates():
    try:
        with open(CONFIG_FILE) as f:
            p = json.load(f).get("nexlinq_path")
        if p:
            yield os.path.dirname(p)
    except (OSError, ValueError):
        pass
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")):
        if not base or not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if "phanteks" in name.lower() or "nexlinq" in name.lower():
                yield os.path.join(base, name)


def main():
    roots = []
    for c in candidates():
        c = os.path.normpath(c)
        if os.path.isdir(c) and c not in roots:
            roots.append(c)
    if not roots:
        print("Couldn't find NexLinq's folder. Right-click its desktop shortcut -> Open file location, and send me that path.")
        return
    for root in roots:
        print("=" * 70)
        print("Folder:", root)
        exts, total, hits = collections.Counter(), 0, []
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                full = os.path.join(dirpath, f)
                ext = os.path.splitext(f)[1].lower()
                exts[ext or "(none)"] += 1
                total += 1
                low = f.lower()
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = -1
                if ext in FONT_EXT or ext == ".asar" or low.endswith(("data.unity3d", "resources.assets")) \
                        or any(k in low for k in KEYWORDS):
                    hits.append((os.path.relpath(full, root), size))
        print(f"{total} files. Types:", ", ".join(f"{e} x{n}" for e, n in exts.most_common(15)))
        print("Interesting files:")
        for rel, size in sorted(hits)[:80]:
            print(f"  {size:>10,}  {rel}")
        if len(hits) > 80:
            print(f"  ... and {len(hits) - 80} more")


if __name__ == "__main__":
    main()
