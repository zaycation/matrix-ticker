"""Dump the Matrix900's HID report descriptor and summarize its reports.

    python tools/descriptor.py

Tells you: report IDs, and how many bytes each input/output/feature report is.
Needs hidapi >= 0.14 (pip install -U hidapi).
"""
import hid

VID, PID = 0x2E3C, 0x6500

d = hid.device()
d.open(VID, PID)
print("manufacturer:", d.get_manufacturer_string())
print("product:     ", d.get_product_string())
try:
    desc = bytes(d.get_report_descriptor())
except AttributeError:
    raise SystemExit("hidapi too old: run  pip install -U hidapi")
d.close()

print(f"\nraw descriptor ({len(desc)} bytes):\n{desc.hex(' ')}\n")

# Minimal HID short-item parser: track report ID / size / count, print main items.
state = {"id": 0, "size": 0, "count": 0}
reports = {}
i = 0
while i < len(desc):
    b = desc[i]
    n = (0, 1, 2, 4)[b & 3]
    val = int.from_bytes(desc[i + 1:i + 1 + n], "little")
    tag = b & 0xFC
    if tag == 0x84: state["id"] = val          # Report ID
    elif tag == 0x74: state["size"] = val      # Report Size (bits)
    elif tag == 0x94: state["count"] = val     # Report Count
    elif tag in (0x80, 0x90, 0xB0):            # Input / Output / Feature
        kind = {0x80: "input", 0x90: "output", 0xB0: "feature"}[tag]
        key = (kind, state["id"])
        reports[key] = reports.get(key, 0) + state["size"] * state["count"]
    i += 1 + n

print("reports (payload bytes, excluding the report-ID byte):")
for (kind, rid), bits in sorted(reports.items()):
    print(f"  {kind:7s} id=0x{rid:02x}: {bits // 8} bytes")
