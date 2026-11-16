"""Save a NexLinq layout from a USB recording so the ticker can replay it.

1. Load the layout in NexLinq, then record while you click Sent!:
       tshark -i \\\\.\\USBPcap3 -w loadout.pcapng -a duration:15
2. Save it (run from the folder containing main.py):
       python tools/save_layout.py loadout.pcapng default

"default" is what main.py restores on exit. Other names are for cycling later.
The panel is found by its vendor ID, so its USB address may change freely.
"""
import json
import os
import subprocess
import sys

VENDOR = "0x2e3c"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tshark(pcap, display_filter, *fields):
    cmd = ["tshark", "-r", pcap, "-Y", display_filter, "-T", "fields", "-E", "separator=|"]
    for f in fields:
        cmd += ["-e", f]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"tshark failed (exit {res.returncode}):\n{res.stderr.strip()}")
    return [line.split("|") for line in res.stdout.splitlines() if line.strip()]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pcap, name = sys.argv[1], sys.argv[2]

    rows = tshark(pcap, f"usb.idVendor == {VENDOR}", "usb.bus_id", "usb.device_address")
    if not rows:
        sys.exit("Panel (vendor 2E3C) not found in this recording. Was it recorded on the right USBPcap?")
    bus, dev = rows[0][0], rows[0][1]

    rows = tshark(pcap, f"usb.bus_id == {bus} && usb.device_address == {dev} && "
                        f"usb.endpoint_address == 0x01 && frame.len == 91",
                  "usbhid.data", "usb.capdata")
    pkts = [bytes.fromhex(next((c for c in r if c), "").replace(":", "")) for r in rows]
    pkts = [p for p in pkts if len(p) == 64]

    # Each upload starts with a 04 packet; keep the last complete one.
    uploads = []
    for p in pkts:
        if p[1] == 0x06:
            continue
        if p[1] == 0x04:
            uploads.append([])
        if uploads:
            uploads[-1].append(p)
    if not uploads or not any(p[1] == 0x03 for p in uploads[-1]):
        sys.exit("No layout upload found. Start the recording first, then click Sent! in NexLinq.")

    last = uploads[-1]
    os.makedirs(os.path.join(ROOT, "layouts"), exist_ok=True)
    path = os.path.join(ROOT, "layouts", f"{name}.json")
    with open(path, "w") as f:
        json.dump({"packets": [p.hex() for p in last]}, f, indent=1)
    cmds = " ".join(f"{p[1]:02x}" for p in last)
    print(f"Saved {len(last)} packets ({cmds}) from upload {len(uploads)} of {len(uploads)} to {path}")


if __name__ == "__main__":
    main()
