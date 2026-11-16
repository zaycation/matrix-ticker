"""Matrix900 text sender, built from NexLinq captures (ticker.pcapng).

Every packet is 64 bytes: [0]=01 report ID, [1]=command, [5]=payload length.
An update is always the full sequence; a text packet on its own is ignored:

    04  begin     01 04 00 00 00 01 b4         (b4 for the full-width layout)
    05  prepare   01 05 ff 00 00 01 00
    02  text      01 02 00 00 00 n+1 idx TEXT  (idx = widget index, ff-padded to 50, then 7 zeros)
    03  widget    01 03 count 00 index 29 | layout cat item scroll pos | text rgb | bg rgb | icon rgb

Full-width layout = layout 01 with one Creator(04) Text(00) widget.
The panel echoes every packet back to every open handle (NexLinq's included).
"""
import time

import hid

VID, PID = 0x2E3C, 0x6500
TEXT_MAX = 50

LAYOUT_FULL_WIDTH = 0x01
CAT_CREATOR, ITEM_TEXT = 0x04, 0x00
TEXT_POS = 0x02          # as captured; NexLinq's "text position" setting (untested)
GAPS = [0.100, 0.100, 0.051, 0.0]  # NexLinq's spacing after 04, 05, 02, 03


def _pad(b):
    return bytes(b).ljust(64, b"\x00")


def update_packets(text, scroll=True, color=(255, 255, 255), bg=(0, 0, 0), icon=(0xFF, 0x00, 0x64)):
    data = text.encode("ascii", errors="replace")[:TEXT_MAX]
    begin = _pad([0x01, 0x04, 0x00, 0x00, 0x00, 0x01, 0xB4])
    prep = _pad([0x01, 0x05, 0xFF, 0x00, 0x00, 0x01, 0x00])
    txt = bytes([0x01, 0x02, 0x00, 0x00, 0x00, len(data) + 1, 0x00]) + data
    txt += b"\xff" * (TEXT_MAX - len(data)) + b"\x00" * 7
    widget = _pad([0x01, 0x03, 0x01, 0x00, 0x00, 0x29,
                   LAYOUT_FULL_WIDTH, CAT_CREATOR, ITEM_TEXT, 0x01 if scroll else 0x00, TEXT_POS,
                   *color, *bg, *icon])
    pkts = [begin, prep, txt, widget]
    assert all(len(p) == 64 for p in pkts)
    return pkts


def bitmap_packets(rgb, width=90, height=10, scroll=True):
    """04 begin -> 05 ff (image) -> 05 data chunks -> 03 EDITOR widget."""
    rgb = bytes(rgb)
    assert len(rgb) == width * height * 3, len(rgb)
    pkts = [_pad([0x01, 0x04, 0x00, 0x00, 0x00, 0x01, 0x84]),
            _pad([0x01, 0x05, 0xFF, 0x00, 0x00, 0x01, 0x01])]
    for i, off in enumerate(range(0, len(rgb), 56)):
        chunk = rgb[off:off + 56]
        pkts.append(_pad([0x01, 0x05, 0x00, 0x00, i, len(chunk) + 2, width, height]) [:8] + chunk)
    pkts = [p.ljust(64, b"\x00") for p in pkts]
    pkts.append(_pad([0x01, 0x03, 0x01, 0x00, 0x00, 0x29, LAYOUT_FULL_WIDTH, CAT_CREATOR, 0x01,
                      0x01 if scroll else 0x00, 0x02,
                      0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00]))
    return pkts


class _LoggedDevice:
    """Wraps the HID device and records every write/read (full 64 bytes) with timing."""
    def __init__(self, dev, log):
        self.dev, self.log, self.t0 = dev, log, time.perf_counter()

    def write(self, data):
        n = self.dev.write(data)
        self.log.append(f"{(time.perf_counter() - self.t0) * 1000:9.2f} ms  W  {bytes(data).hex(' ')}")
        return n

    def read(self, size, timeout_ms=0):
        r = self.dev.read(size, timeout_ms=timeout_ms)
        if r:
            self.log.append(f"{(time.perf_counter() - self.t0) * 1000:9.2f} ms  R  {bytes(r).hex(' ')}")
        return r

    def close(self):
        self.dev.close()


class Matrix:
    def __init__(self, log=None):
        """log: pass a list to record every packet written and read."""
        self.dev = hid.device()
        self.dev.open(VID, PID)
        if log is not None:
            self.dev = _LoggedDevice(self.dev, log)

    def _wait_echo(self, pkt, timeout=1.0):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            r = bytes(self.dev.read(64, timeout_ms=200))
            if r and not (r[1] == 0x06 and pkt[1] != 0x06):  # skip NexLinq's heartbeat echoes
                return r == pkt
        return False

    def show_text(self, text, **kw):
        ok = True
        for pkt, gap in zip(update_packets(text, **kw), GAPS):
            t0 = time.perf_counter()
            self.dev.write(pkt)
            ok &= self._wait_echo(pkt)
            time.sleep(max(0.0, gap - (time.perf_counter() - t0)))
        return ok

    def show_bitmap(self, rgb, width=90, height=10, steps="full", careful=False, scroll=True):
        """Full-color image via the Creator EDITOR widget. NexLinq must be closed:
        it reacts to image uploads by sending its own image at the same time.

        rgb:   width*height*3 bytes, rows of 90 left to right, starting top-left.
        steps: "full"   = 04 begin, 05 prepare, data, 03 show (what NexLinq sends)
               "data03" = data + 03 only (for frames after the first)
               "data"   = data only
        careful: add NexLinq's pauses and heartbeat sync (only useful if NexLinq runs).
        Every packet waits for its echo; 03 is only sent if all data was confirmed.
        Returns (ok, message)."""
        pkts = bitmap_packets(rgb, width, height, scroll)
        begin, prep, data, widget = pkts[0], pkts[1], pkts[2:-1], pkts[-1]
        sent, skipped = set(), 0
        if careful:
            self._after_heartbeat()
        if steps == "full":
            for pkt, pause in ((begin, 0.114), (prep, 0.107)):
                t0 = time.perf_counter()
                self.dev.write(pkt)
                sent.add(pkt)
                if not self._wait_echo(pkt):
                    return False, f"no echo for {pkt[1]:02x}; stopped before sending image data"
                if careful:
                    time.sleep(max(0.0, pause - (time.perf_counter() - t0)))
        for pkt in data:
            t0 = time.perf_counter()
            n = self.dev.write(pkt)
            sent.add(pkt)
            ok, sk, odd = self._echo_detail(pkt, sent)
            skipped += sk
            if not ok:
                ms = (time.perf_counter() - t0) * 1000
                lines = [f"data packet {pkt[4]}: write returned {n}, waited {ms:.0f} ms, "
                         f"{'got an unexpected packet (is NexLinq running?)' if odd else 'timed out'}",
                         f"  sent: {pkt[:12].hex(' ')} ..."]
                lines += [f"  read: {r[:12].hex(' ')} ..." for r in odd] or ["  read: (nothing)"]
                return False, "\n".join(lines) + "\nstopped before the 03 show packet"
        if careful:
            ok, extra, bad = self._wait_quiet(sent)
            if not ok:
                return False, f"unexpected packet before 03: {bad[:12].hex(' ')} ... (is NexLinq running?)"
        if steps == "data":
            return True, "ok (data only, no 03)"
        self.dev.write(widget)
        ok = self._wait_echo(widget)
        return ok, ("ok" if ok else "no echo for 03") + (f", skipped {skipped} repeated echoes" if skipped else "")

    def _echo_detail(self, pkt, sent=(), timeout=0.5):
        """Wait for pkt's echo. Heartbeats and late/repeated echoes of packets in
        `sent` are skipped. Returns (ok, skipped_count, unexpected_reads)."""
        skipped, odd = 0, []
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            r = bytes(self.dev.read(64, timeout_ms=100))
            if not r:
                continue
            if r == pkt:
                return True, skipped, odd
            if r[1] == 0x06 or r in sent:
                skipped += r[1] != 0x06
                continue
            odd.append(r)
            return False, skipped, odd
        return False, skipped, odd

    def _wait_quiet(self, sent, quiet=0.15, limit=2.0):
        """Read until nothing but heartbeats/known echoes arrives for `quiet` seconds."""
        extra, last = 0, time.perf_counter()
        end = last + limit
        while time.perf_counter() < end and time.perf_counter() - last < quiet:
            r = bytes(self.dev.read(64, timeout_ms=30))
            if r and r[1] != 0x06:
                extra += 1
                last = time.perf_counter()
                if r not in sent:
                    return False, extra, r
        return True, extra, None

    def _after_heartbeat(self, timeout=1.5):
        """Wait for NexLinq's once-a-second 06 echo, then return immediately, so the
        next 06 can't land mid-upload. If NexLinq isn't running, just times out."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            r = bytes(self.dev.read(64, timeout_ms=100))
            if r and r[1] == 0x06:
                return

    def _drain(self):
        while self.dev.read(64, timeout_ms=30):
            pass

    def replay(self, packets):
        """Send a saved upload (list of 64-byte packets) with NexLinq's spacing."""
        ok = True
        for pkt in packets:
            self.dev.write(pkt)
            ok &= self._wait_echo(pkt)
            time.sleep(0.1 if pkt[1] in (0x04, 0x05) else 0.05)
        return ok

    def close(self):
        self.dev.close()
