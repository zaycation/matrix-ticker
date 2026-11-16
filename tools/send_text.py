"""First write test: send ONLY the text packet (command 0x02) to the Matrix900.

    python tools/send_text.py "LAL 98 GSW 95"

Packet layout, copied from NexLinq's captures (ABC / ABD tests):
    [0]     01      HID report ID
    [1]     02      command: set text
    [2..4]  00 00 00
    [5]     n+1     payload length: length byte + n characters (04 for "ABC")
    [6]     03      constant in every NexLinq capture (not the length)
    [7..56] text    ASCII, padded with 0xff (50 bytes max)
    [57..63] 00

The panel echoes every packet back; this prints the echo so we can check it.
"""
import sys
import hid

VID, PID = 0x2E3C, 0x6500
TEXT_MAX = 50


def text_packet(text):
    data = text.encode("ascii", errors="replace")[:TEXT_MAX]
    # [5] = payload length (length byte + text), same field as 0x29 in 03 packets
    # [6] is always 03 in NexLinq captures (ABC, XYZW, LAL 98 GSW 95), not the length
    pkt = bytes([0x01, 0x02, 0x00, 0x00, 0x00, len(data) + 1, 0x03])
    pkt += data + b"\xff" * (TEXT_MAX - len(data))
    pkt += b"\x00" * 7
    assert len(pkt) == 64
    return pkt


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "HELLO"
    pkt = text_packet(text)
    print("sending:", pkt.hex(" "))
    d = hid.device()
    d.open(VID, PID)
    try:
        written = d.write(pkt)
        print("bytes written:", written)
        echo = bytes(d.read(64, timeout_ms=1000))
        print("panel replied:", echo.hex(" ") if echo else "(nothing within 1s)")
        if echo:
            print("echo matches:", echo == pkt)
    finally:
        d.close()


if __name__ == "__main__":
    main()
