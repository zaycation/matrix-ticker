"""Patch notes for games you pick: a quick summary on the panel when a game is updated.

Two kinds of source, per game:

- An official notes page (preferred): one page that gains a new dated section per update,
  like Blizzard's "WoW: Forever Hotfixes" or Rockstar Support's "Title Update Notes"
  ("November 23, 2026" or "[October 27, 2026] - PC"). The newest section is summarized:
  date, number of changes, and the first change in each of the top categories.
- No page yet: watch news headlines (Google News search) for "<game>" + "patch notes"
  and announce new ones, so you hear about notes the moment they're posted somewhere.

Pages are checked every CHECK_S; the first check is only a baseline (no cut-in), but a
recent update (within RECENT_DAYS) still shows in the cycle as the PATCHES item.
"""
import datetime as dt
import html
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from . import style
from .sleeper import clean

CHECK_S = 15 * 60
RECENT_DAYS = 2
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 matrix-ticker")
LABEL, DATE_RGB, COUNT_RGB = (120, 160, 255), (255, 200, 0), (160, 160, 160)
MONTHS = ("january february march april may june july august september october november december").split()
DATE_RE = re.compile(r"^\W*(" + "|".join(MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})", re.I)
SKIP_HEADINGS = re.compile(r"^(hotfixes|developers?'? ?notes?|known issues|last updated)\b", re.I)

DEFAULT_GAMES = [
    {"name": "WoW Forever", "url": "https://news.blizzard.com/en-us/article/24315281"},
    {"name": "GTA 6", "url": "https://support.rockstargames.com/articles/sN5pEdFYZdlvijKXd6xpJ/"
                              "grand-theft-auto-vi-launch-updates-ps5-xbox-series-x-or-s"},
]


# ---------- reading a notes page ----------
class _Lines(HTMLParser):
    """HTML -> [(kind, depth, text)]: kind is 'head' (h1-h6, or a block that is only bold
    text), 'item' (a list item's own text; depth = list nesting), or 'text'."""
    BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.buf, self.bold, self.depth, self.skip = [], [], 0, 0, 0
        self.kind, self.all_bold = "text", True

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(t for t, _ in self.buf)).strip()
        if text:
            kind = self.kind
            if kind == "text" and self.all_bold and any(b for _, b in self.buf if _.strip()):
                kind = "head"
            self.out.append((kind, self.depth, text))
        self.buf, self.kind, self.all_bold = [], "text", True

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "nav", "header", "footer"):
            self.skip += 1
        elif tag in ("strong", "b"):
            self.bold += 1
        elif tag in ("ul", "ol"):
            self._flush()
            self.depth += 1
        elif tag in self.BLOCKS or tag == "br":
            self._flush()
            if tag[0] == "h" and tag[1:].isdigit():
                self.kind = "head"
            elif tag == "li":
                self.kind = "item"

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "nav", "header", "footer"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("strong", "b"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("ul", "ol"):
            self._flush()
            self.depth = max(0, self.depth - 1)
        elif tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data):
        if self.skip:
            return
        self.buf.append((data, self.bold > 0))
        if data.strip() and not self.bold:
            self.all_bold = False


def lines(page_html):
    p = _Lines()
    p.feed(page_html)
    p._flush()
    return p.out


def _date(text):
    m = DATE_RE.match(text)
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
    except ValueError:
        return None


def sections(page_html):
    """[(date, header, [(kind, depth, text), ...])] for each dated section, newest first."""
    out, cur = [], None
    for kind, depth, text in lines(page_html):
        d = _date(text) if len(text) < 90 else None
        if d:
            cur = (d, text, [])
            out.append(cur)
        elif cur is not None:
            cur[2].append((kind, depth, text))
    out.sort(key=lambda s: s[0], reverse=True)
    return out


_TRIM = [
    (r"^fixed (an?|several|multiple|some|various) (issues?|bugs?|crash(es)?) (that|which) (caused|could cause|"
     r"resulted in) (the game|clients?|the client) (to crash|crashing|crashes?)\b", "FIXED: CRASHES"),
    (r"^fixed (several|multiple|some|various) crash(es)?\b", "FIXED: CRASHES"),
    (r"^fixed (an?|several|multiple|some|various) (issues?|bugs?) (that resulted in|that caused|that could cause|"
     r"in which|where|that|which|with|causing)\s+", "FIXED: "),
    (r"^fixed\s+", "FIXED: "),
    (r"\bnow correctly\b", "now"),
    (r"\bas intended\b|\bthan intended\b", ""),
    (r"\s+", " "),
]


def shorten(text, n=70):
    t = text.strip().rstrip(".")
    for pat, rep in _TRIM:
        t = re.sub(pat, rep, t, flags=re.I)
    t = clean(t, 400)
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(" ,;:-") + ".."
    return t


GENERIC_RE = re.compile(r"^(GENERAL|MISC|MISCELLANEOUS|OTHER|FIXES|BUG FIXES)?(\s*[/&,]\s*(GENERAL|MISC|MISCELLANEOUS|OTHER))*$")


def summarize(section, top=3):
    """-> (n_changes, [(category, change)]) for one dated section."""
    _date_, header, body = section
    # "[November 23, 2026] - General / Miscellaneous": what follows the date is the first category
    category = re.sub(r"^\W*\w+\s+\d{1,2},?\s+\d{4}\W*", "", header).strip(" -\u2013\u2014")
    parents, leaves, seen, n = {}, [], set(), 0
    for i, (kind, depth, text) in enumerate(body):
        if kind == "head" or (kind == "text" and depth == 0 and len(text) < 40):
            if not SKIP_HEADINGS.match(text):
                category = text
            continue
        if kind != "item":
            continue
        nxt = body[i + 1] if i + 1 < len(body) else None
        parents[depth] = text
        if nxt and nxt[0] == "item" and nxt[1] > depth:
            continue                                   # has sub-bullets: it's a label (e.g. "Druid")
        if text.lower().startswith("developers"):
            continue
        n += 1
        label = parents.get(depth - 1) if depth > 1 else category
        key = (category or label or "").lower()
        leaves.append((key, clean(label or category or "", 24), shorten(text)))
    # one change from each of the first `top` categories; if there are fewer categories than
    # that, fill up with further changes (a one-category update still shows 3 changes)
    picks = []
    for key, label, change in leaves:
        if key not in seen and len(picks) < top:
            seen.add(key)
            picks.append((label, change))
    for key, label, change in leaves:
        if len(picks) >= top:
            break
        if (label, change) not in picks:
            picks.append((label, change))
    order = {lc: i for i, lc in enumerate((lab, ch) for _, lab, ch in leaves)}
    picks.sort(key=lambda p: order[p])
    # don't repeat a label for consecutive changes in the same category
    out, prev = [], None
    for label, change in picks:
        out.append(("" if label == prev or GENERIC_RE.match(label) else label, change))
        prev = label
    return n, out


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Hand redirects back to fetch(), which follows them itself (see there)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirects)
_REFRESH_RE = re.compile(r"url\s*=\s*['\"]?([^'\";>\s]+)", re.I)
_META_REFRESH_RE = re.compile(r"<meta[^>]+http-equiv=['\"]?refresh['\"]?[^>]*content=['\"][^'\"]*?url=([^'\">]+)", re.I)
_NEXT_REDIRECT_RE = re.compile(r"NEXT_REDIRECT;(?:push|replace);([^;\"\\]+);30[178]")


def _redirect_target(headers, body):
    """Where a 3xx response points: Location header, else Refresh header, else a meta refresh
    or Next.js redirect marker in the body (some sites send 308 without a Location header)."""
    if headers.get("Location"):
        return headers["Location"]
    m = _REFRESH_RE.search(headers.get("Refresh") or "")
    if m:
        return m.group(1)
    text = body.decode("utf-8", "replace")
    for pat in (_META_REFRESH_RE, _NEXT_REDIRECT_RE):
        m = pat.search(text)
        if m:
            return html.unescape(m.group(1))
    return None


def fetch(url, hops=6):
    """GET a page as text, following redirects (including ones Python can't follow itself)."""
    for _ in range(hops):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                                                   "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
        try:
            with _opener.open(req, timeout=25) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise
            body = e.read() or b""
            target = _redirect_target(e.headers, body)
            if not target:
                heads = "; ".join(f"{k}: {v}" for k, v in e.headers.items())
                snippet = re.sub(r"\s+", " ", body[:300].decode("utf-8", "replace"))
                raise RuntimeError(f"{e.code} redirect with no address to follow. Headers: {heads} | Body: {snippet}")
            url = urllib.parse.urljoin(url, target)
    raise RuntimeError(f"too many redirects (last: {url})")


def page_update(url, fetcher=fetch):
    """Newest section of an official notes page: dict(date, key, changes, picks) or None."""
    secs = sections(fetcher(url))
    if not secs:
        return None
    newest = secs[0]
    n, picks = summarize(newest)
    return {"date": newest[0], "header": newest[1], "changes": n, "picks": picks,
            "key": f"{newest[0]}:{n}"}


# ---------- no official page yet: headline watch ----------
NEWS_URL = "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en"
NOTES_WORDS = re.compile(r"patch notes|title update|hotfix|update notes", re.I)


def news_updates(game, fetcher=fetch):
    """Recent 'patch notes' headlines about the game: [(id, published, title)] newest first."""
    q = urllib.parse.quote(f'"{game}" "patch notes" when:3d')
    root = ET.fromstring(fetcher(NEWS_URL.format(q)))
    out = []
    for item in root.iter("item"):
        title = html.unescape(item.findtext("title") or "")
        title = re.sub(r"\s+-\s+[^-]+$", "", title)          # drop " - Site Name"
        if not NOTES_WORDS.search(title) or game.lower().split()[0] not in title.lower():
            continue
        try:
            when = dt.datetime.strptime(item.findtext("pubDate") or "", "%a, %d %b %Y %H:%M:%S %Z")
        except ValueError:
            when = None
        out.append((item.findtext("guid") or title, when, title))
    out.sort(key=lambda h: h[1] or dt.datetime.min, reverse=True)
    return out


VERSION_RE = re.compile(r"\b(\d{1,2}\.\d{2,3}\.\d{2,3}|\d+\.\d+\.\d+\.\d+|(?:update|patch|hotfix)\s+\d+(?:\.\d+)+)\b", re.I)


def version_of(title):
    """'GTA 6 Update 01.002.002 Patch Notes' -> '01.002.002' (so many articles about one patch
    count as one update). None if the headline names no version."""
    m = VERSION_RE.search(title)
    return re.sub(r"^(update|patch|hotfix)\s+", "", m.group(1), flags=re.I).lower() if m else None


# ---------- display ----------
def segments(game, upd):
    """Scrolling summary: WOW FOREVER UPDATE : NOV 23  6 CHANGES  CLASSES: DRUID ..  DUNGEONS: .."""
    segs = [(clean(game, 20), LABEL), (" UPDATE : ", style.GRAY)]
    if upd.get("headline"):
        head = clean(upd["headline"], 160)
        name = clean(game, 20)
        if head.startswith(name + " "):        # "GTA 6 UPDATE 01.002.002 ..." already names the game
            return [(name, LABEL), (head[len(name):], style.WHITE)]
        return segs + [(head, style.WHITE)]
    d = upd["date"]
    segs += [(f"{d.strftime('%b').upper()} {d.day}", DATE_RGB),
             (f"  {upd['changes']} CHANGE{'S' if upd['changes'] != 1 else ''}", COUNT_RGB)]
    for cat, change in upd["picks"]:
        segs += [("   ", style.WHITE)]
        if cat:
            segs += [(cat + ": ", LABEL)]
        segs += [(change, style.WHITE)]
    return segs


class Watcher(threading.Thread):
    """Checks each game's source every CHECK_S; new updates cut in via on_alert.
    .latest holds the most recent update per game for the PATCHES item."""

    def __init__(self, settings, on_alert, stop_event, log=print, interval=CHECK_S, fetcher=fetch):
        super().__init__(daemon=True)
        self.s, self.on_alert, self.stop, self.log = settings, on_alert, stop_event, log
        self.interval, self.fetcher = interval, fetcher
        self.seen, self.latest, self.lock = {}, {}, threading.Lock()

    def recent(self, today=None):
        """[(game, update)] updated in the last RECENT_DAYS, for the PATCHES item."""
        today = today or dt.date.today()
        with self.lock:
            return [(g, u) for g, u in self.latest.items() if (today - u["date"]).days <= RECENT_DAYS]

    def poll_game(self, game, url):
        from .alerts import Alert
        name = game.strip()
        if not name:
            return
        if url.strip():
            upd = page_update(url.strip(), self.fetcher)
            if not upd:
                return
            key = upd["key"]
        else:
            heads = news_updates(name, self.fetcher)
            if not heads:
                return
            gid, when, title = heads[0]
            upd = {"date": (when or dt.datetime.now(dt.timezone.utc)).date(), "headline": title}
            # one cut-in per update: articles naming the same version (or, with no version,
            # published the same day) are all the same news
            key = version_of(title) or f"day:{upd['date']}"
        with self.lock:
            first = name not in self.seen
            changed = self.seen.get(name) != key
            self.seen[name] = key
            self.latest[name] = upd
        if changed and not first:
            text = (f"{name}: {upd['headline']}" if upd.get("headline") else
                    f"{name} update {upd['date']}: {upd['changes']} changes")
            self.on_alert(Alert("UPDATE", LABEL, scroll=segments(name, upd), log_text=f"Patch notes: {text}"))

    def poll(self):
        if "PATCHES" not in self.s.leagues:
            return
        for g in self.s.patch_games:
            if self.stop.is_set():
                return
            try:
                self.poll_game(g.get("name", ""), g.get("url", ""))
            except Exception as e:
                self.log(f"Patch notes ({g.get('name')}): couldn't check ({e})")

    def run(self):
        while not self.stop.is_set():
            self.poll()
            end = time.time() + self.interval
            while time.time() < end and not self.stop.is_set():
                time.sleep(0.5)
