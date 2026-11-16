"""Summarize and diff USBPcap captures of NexLinq talking to the Matrix.

Needs tshark (ships with Wireshark) on PATH.

    python tools/analyze.py summary red.pcapng --addr 1.7
    python tools/analyze.py diff red.pcapng green.pcapng --addr 1.7

--addr is "bus.device" from Wireshark's usb.src/usb.dst columns (e.g. 1.7).
Default is host->device (OUT). Add --dir in to see the panel's replies.
"""
import argparse
import collections
import subprocess

FIELDS = ["frame.time_relative", "usb.src", "usb.dst", "usb.endpoint_address",
          "usb.transfer_type", "usbhid.data", "usb.capdata", "usb.data_fragment"]


def packets(path, addr, direction="out"):
    cmd = ["tshark", "-r", path, "-T", "fields", "-E", "separator=|"]
    for f in FIELDS:
        cmd += ["-e", f]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"tshark failed on {path} (exit {res.returncode}):\n{res.stderr.strip()}")
    out = res.stdout
    for line in out.splitlines():
        t, src, dst, ep, ttype, *datas = line.split("|")
        peer = dst if direction == "out" else src
        if addr and not peer.startswith(addr):
            continue
        hexdata = next((d for d in datas if d), "").replace(":", "")
        if hexdata:
            yield float(t or 0), ep, ttype, bytes.fromhex(hexdata)


def summary(args):
    pkts = list(packets(args.pcap, args.addr, args.dir))
    if not pkts:
        print(f"no {args.dir.upper()} payloads; check --addr")
        return
    dur = pkts[-1][0] - pkts[0][0] or 1
    print(f"{len(pkts)} {args.dir.upper()} packets over {dur:.1f}s ({len(pkts)/dur:.1f}/s)")
    by_ep = collections.Counter((ep, tt, len(p)) for _, ep, tt, p in pkts)
    for (ep, tt, n), c in by_ep.most_common():
        print(f"  ep={ep} type={tt} len={n}: {c} packets")
    # Header bytes that vary vs. stay fixed hint at command/sequence fields.
    print("\nfirst bytes histogram (likely command IDs / sequence numbers):")
    for i in range(min(8, min(len(p) for *_, p in pkts))):
        vals = collections.Counter(p[i] for *_, p in pkts)
        print(f"  byte[{i}]: {len(vals)} distinct, top: "
              + " ".join(f"{v:02x}x{c}" for v, c in vals.most_common(6)))
    print("\nfirst 6 packets:")
    for t, ep, _, p in pkts[:6]:
        print(f"  {t:8.3f} ep={ep} {p[:48].hex(' ')}{' ...' if len(p) > 48 else ''}")


def diff(args):
    a = [p for *_, p in packets(args.a, args.addr, args.dir)]
    b = [p for *_, p in packets(args.b, args.addr, args.dir)]
    print(f"A: {len(a)} packets, B: {len(b)} packets; comparing first {args.n}")
    for i, (pa, pb) in enumerate(zip(a[:args.n], b[:args.n])):
        changed = [j for j in range(min(len(pa), len(pb))) if pa[j] != pb[j]]
        if not changed:
            print(f"#{i}: identical")
            continue
        print(f"#{i}: {len(changed)} bytes differ, offsets {changed[:12]}"
              f"{'...' if len(changed) > 12 else ''}")
        for j in changed[:6]:
            print(f"     [{j}] {pa[j]:02x} -> {pb[j]:02x}")


def changes(args):
    """Full first packet, then for each later packet only the bytes that changed."""
    pkts = list(packets(args.pcap, args.addr, args.dir))
    if not pkts:
        print(f"no {args.dir.upper()} payloads; check --addr")
        return
    t0, _, _, first = pkts[0]
    print(f"{t0:8.3f} full ({len(first)} bytes):")
    for off in range(0, len(first), 16):
        print(f"    [{off:2d}] {first[off:off + 16].hex(' ')}")
    prev = first
    for t, _, _, p in pkts[1:]:
        diff = [f"[{j}] {prev[j]:02x}->{p[j]:02x}" for j in range(min(len(p), len(prev))) if p[j] != prev[j]]
        if len(p) != len(prev):
            diff.append(f"len {len(prev)}->{len(p)}")
        print(f"{t:8.3f} " + ("  ".join(diff) if diff else "(identical)"))
        prev = p


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(required=True)
s = sub.add_parser("summary"); s.add_argument("pcap"); s.set_defaults(fn=summary)
c = sub.add_parser("changes"); c.add_argument("pcap"); c.set_defaults(fn=changes)
d = sub.add_parser("diff"); d.add_argument("a"); d.add_argument("b")
d.add_argument("-n", type=int, default=20); d.set_defaults(fn=diff)
for p in (s, c, d):
    p.add_argument("--addr", default="", help='device as "bus.dev.", e.g. 3.9.')
    p.add_argument("--dir", choices=["out", "in"], default="out",
                   help="out = NexLinq->panel (default), in = panel->NexLinq")
args = ap.parse_args()
args.fn(args)
