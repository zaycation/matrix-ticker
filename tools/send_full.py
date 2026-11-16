"""Replay NexLinq's exact upload sequence (from creator2.pcapng, the ABD change)
with only the text swapped.

    python tools/send_full.py "LAL 98"

Sequence, byte-for-byte from the capture:
    04 (begin) -> 05 ff (prepare) -> 02 (text) -> 4x 03 (layout 0x05 widgets)

Timing copied from NexLinq's capture (creator2, ABC change at 9.02 s):
    04 +100ms 05 +112ms 02 +51ms 03 +50ms 03 +51ms 03 +51ms 03
Add --slow to wait 300 ms after every packet instead.
"""
import sys
import time
import hid

VID, PID = 0x2E3C, 0x6500
TEXT_MAX = 50

BEGIN = "01040000000184".ljust(128, "0")
PREP = "0105ff00000100".ljust(128, "0")
LAYOUT = [
    "0103040000290501010200161e00000400ffffff000000ff00000000ff0000000000000000000000000000000000000000000000000000000000000000000000",
    "01030400012905020101020307d007d007d000500001ffffff00ffc83200ffff0000ffffffff6400ff3200ff0000000000000000000000000000000000000000",
    "01030400022905020102020307d007d007d000500001ffffff00ffc83200ffff0000ffffffff6400ff3200ff0000000000000000000000000000000000000000",
    "0103040003290504000102ffffff000000ff00640000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
]


def text_packet(text):
    data = text.encode("ascii", errors="replace")[:TEXT_MAX]
    # [5] = payload length (length byte + text), same field as 0x29 in 03 packets
    # [6] is always 03 in NexLinq captures (ABC, XYZW, LAL 98 GSW 95), not the length
    pkt = bytes([0x01, 0x02, 0x00, 0x00, 0x00, len(data) + 1, 0x03])
    return pkt + data + b"\xff" * (TEXT_MAX - len(data)) + b"\x00" * 7


def sequence(text):
    pkts = [bytes.fromhex(BEGIN), bytes.fromhex(PREP), text_packet(text)]
    pkts += [bytes.fromhex(h) for h in LAYOUT]
    assert all(len(p) == 64 for p in pkts)
    return pkts


# Wait after each packet, in seconds, matching NexLinq.
NEXLINQ_GAPS = [0.100, 0.112, 0.051, 0.050, 0.051, 0.051, 0.0]


def main():
    args = [a for a in sys.argv[1:] if a != "--slow"]
    slow = "--slow" in sys.argv
    text = args[0] if args else "HELLO"
    gaps = [0.3] * 7 if slow else NEXLINQ_GAPS
    d = hid.device()
    d.open(VID, PID)
    try:
        for p, gap in zip(sequence(text), gaps):
            t0 = time.perf_counter()
            d.write(p)
            # Every open handle gets every reply, so NexLinq's once-a-second 06 echoes
            # show up here too. Skip those and wait for the echo of our own packet.
            echo, deadline = b"", time.perf_counter() + 1.0
            while time.perf_counter() < deadline:
                r = bytes(d.read(64, timeout_ms=200))
                if not r or (r[1] == 0x06 and p[1] != 0x06):
                    continue
                echo = r
                break
            ok = "ok" if echo == p else ("NO ECHO" if not echo else "ECHO DIFFERS: " + echo.hex(" "))
            print(f"cmd {p[1]:02x}: {ok}")
            # sleep the remainder so the gap is measured from the write, like the capture
            time.sleep(max(0.0, gap - (time.perf_counter() - t0)))
    finally:
        d.close()


if __name__ == "__main__":
    main()
