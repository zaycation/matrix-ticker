"""Messages from a phone, through ntfy (https://ntfy.sh): free, open source, no account.

The phone (an iPhone Shortcut, or the ntfy app/website) POSTs text to
https://ntfy.sh/<topic>; the app checks that topic every few seconds. The topic name is a
long random code, so only people you give it to can send. A sender name can ride along
in the "Title" header (the Shortcut sets it).

A new message cuts in right away (a heart, the sender, then the text scrolling across) and
then stays in the cycle as the MESSAGES item until midnight, or until a newer one arrives
or it's cleared. The latest message is saved to message.json so it survives a restart.
"""
import datetime as dt
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request

from . import style
from .font import ICON_CHAR
from .paths import DATA_DIR
from .sleeper import clean

BASE = "https://ntfy.sh"
POLL_S = 10
MESSAGE_FILE = os.path.join(DATA_DIR, "message.json")
PINK = (255, 90, 150)
ATTENTION = (PINK, (255, 255, 255)) * 5    # pink, white, five times, before the message scrolls
MAX_CHARS = 200


def new_topic():
    return "matrix-ticker-" + secrets.token_hex(8)


def url(topic):
    return f"{BASE}/{topic}"


def fetch(topic, since):
    """New messages on the topic since `since` (a message id or a unix time), oldest first."""
    q = urllib.parse.urlencode({"poll": "1", "since": str(since)})
    req = urllib.request.Request(f"{BASE}/{urllib.parse.quote(topic)}/json?{q}",
                                 headers={"User-Agent": "matrix-ticker"})
    with urllib.request.urlopen(req, timeout=20) as r:
        lines = r.read().decode("utf-8", "replace").splitlines()
    out = []
    for line in lines:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("event") == "message" and (m.get("message") or "").strip():
            out.append(m)
    return sorted(out, key=lambda m: m.get("time", 0))


def send(topic, text, sender=""):
    """Post a message (the app's own Send box uses this; so could anything else)."""
    headers = {"User-Agent": "matrix-ticker"}
    if sender:
        headers["Title"] = sender
    req = urllib.request.Request(url(topic), data=text.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


# ---------- the current message ----------
_lock = threading.Lock()


def load():
    try:
        with open(MESSAGE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(state):
    with open(MESSAGE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def current(now=None):
    """(sender, text) of today's message, or None (it expires at midnight, local time)."""
    m = load().get("current")
    if not m:
        return None
    now = now or dt.datetime.now()
    if dt.datetime.fromtimestamp(m.get("time", 0)).date() != now.date():
        return None
    return m.get("sender", ""), m.get("text", "")


def clear():
    with _lock:
        state = load()
        state.pop("current", None)
        _save(state)


def _label(sender):
    return clean(sender, 16) if sender and sender.strip() else "MESSAGE"


def segments(sender, text):
    return [(ICON_CHAR["heart"], None), ("  ", style.WHITE), (_label(sender), PINK), (" : ", style.GRAY),
            (clean(text, MAX_CHARS), style.WHITE)]


class Watcher(threading.Thread):
    """Checks the topic every POLL_S seconds; each new message becomes the current one and
    cuts in through on_alert. Starts from 'now', so old messages aren't replayed."""

    def __init__(self, settings, on_alert, stop_event, log=print, interval=POLL_S):
        super().__init__(daemon=True)
        self.s, self.on_alert, self.stop, self.log, self.interval = settings, on_alert, stop_event, log, interval
        self.since = load().get("last_id") or int(time.time())

    def poll(self, fetcher=fetch):
        from .alerts import Alert
        topic = self.s.message_topic.strip()
        if not topic or "MESSAGES" not in self.s.leagues:
            return
        try:
            new = fetcher(topic, self.since)
        except Exception:
            return                       # offline; try again next time
        for m in new:
            self.since = m.get("id") or self.since
            sender, text = (m.get("title") or "").strip(), m["message"].strip()[:MAX_CHARS]
            with _lock:
                state = load()
                state.update(last_id=m.get("id"), current={"sender": sender, "text": text,
                                                           "time": m.get("time", int(time.time()))})
                _save(state)
            self.on_alert(Alert("MESSAGE", PINK, scroll=segments(sender, text), flash=ATTENTION,
                                log_text=f"Message from {sender or 'phone'}: {text}"))

    def run(self):
        while not self.stop.is_set():
            self.poll()
            end = time.time() + self.interval
            while time.time() < end and not self.stop.is_set():
                time.sleep(0.5)
