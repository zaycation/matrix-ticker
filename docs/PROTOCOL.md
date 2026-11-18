# Matrix900 USB protocol (decoded from captures)

The display is a USB HID device: VID `2E3C`, PID `6500`, vendor usage page `0xFF1B`.
Every packet is 64 bytes: `[0]=01` report ID, `[1]=command`, `[5]=payload length`.
The panel echoes each packet back to **every** open handle (so other apps see your traffic).

## Commands

| Cmd | Bytes | Meaning |
|---|---|---|
| 06 | `01 06 00 00 00 3a` + unix time (big-endian, `[6..9]`) + sensor values | NexLinq's once-a-second live data |
| 04 | `01 04 00 00 00 01 b4` | Begin update (`b4`/`84` depends on layout) |
| 05 | `01 05 ff 00 00 01 00` | Prepare (`.. 01` before an image) |
| 02 | `01 02 00 00 00 n+1 idx` + text, ff-padded to 50, 7 zeros | Text for widget `idx` (50 chars max) |
| 03 | `01 03 count 00 index 29` + 41 bytes | One widget: layout, category, item, scroll, position, colors |
| 05 data | `01 05 00 00 idx 3a 5a 0a` + 56 bytes RGB | Image chunk (49 per 90x10 frame) |

- Updates are always `04 → 05 → (02 text | 05 image data) → 03`. A text packet alone is ignored.
- Text widget (`03` payload): `layout 04 00 scroll 02 | text RGB | bg RGB | icon RGB`.
- Image (Creator EDITOR, item `01`): 900 pixels, RGB, rows of 90 left to right from the top-left.
  Only 90x10 displays. Every frame needs the full sequence; the panel needs > 0.05 s after each
  frame (about 3.5 frames/s).
- NexLinq reacts to image uploads by sending its own image, so it must be closed for bitmaps.
- Font of the text widget can't draw `| & _ ; $ " ~` (they show as `A`).

## Tools

- `tools/find_device.py`, `tools/descriptor.py`: identify the device and its report sizes
- `tools/analyze.py`: `summary` / `changes` / `diff` on tshark captures
- `tools/drawtest.py`: pixel order, frame speed and gap tests
- `tools/save_layout.py`: save a NexLinq layout upload from a capture for replay
