"Passive PPCS discovery probe: sends LanSearch to UDP port 32108 and listens. No login, no commands."
import argparse
import socket
import time

PORT = 32108
LAN_SEARCH = bytes([0xF1, 0x30, 0x00, 0x00])
REPEATS = 3
SEND_GAP_S = 0.5

# Known PPCS types (notes/protocol-findings.md). 0x41 = PunchPkt, expected in a reply.
TYPE_NAMES = {
    0x00: "Hello",
    0x10: "DevLgn",
    0x12: "DevLgn_CRC [TO TEST]",
    0x13: "DevLgnAck_CRC [TO TEST]",
    0x30: "LanSearch",
    0x41: "PunchPkt",
    0xD0: "DRW",
    0xE0: "Alive",
}


def local_ip():
    "Outgoing interface IP (connect() on UDP sends no packet)."
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def describe(data: bytes) -> str:
    "Describes a received datagram. Drops nothing."
    if data[:1] == b"\xf1" and len(data) < 4:
        return f"short PPCS ({len(data)} bytes < 4-byte header)"
    if len(data) < 4 or data[0] != 0xF1:
        return "(does not start with F1 — not PPCS, kept)"
    ptype = data[1]
    n = (data[2] << 8) | data[3]
    ok = "OK" if n == len(data) - 4 else "MISMATCH"
    name = TYPE_NAMES.get(ptype, "unknown")
    return f"PPCS type=0x{ptype:02x} ({name}) len={n} ({ok})"


def open_listener():
    "Tries port 32108; if it is busy, uses a free port and warns."
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.bind(("", PORT))
        port = PORT
    except OSError as e:
        s.bind(("", 0))
        port = s.getsockname()[1]
        print(f"WARNING: port {PORT} busy ({e}); using local port {port}")
    s.settimeout(0.5)
    return s, port


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=5.0, help="seconds to listen")
    ap.add_argument("--broadcast", default=None, help="subnet broadcast, e.g.: 192.168.1.255")
    args = ap.parse_args()

    ip = local_ip()
    bcast = args.broadcast or ".".join(ip.split(".")[:3] + ["255"])
    destinations = ["255.255.255.255"]
    if bcast not in destinations:
        destinations.append(bcast)
    print(f"local IP: {ip} | destinations: {', '.join(destinations)} | port: {PORT}")

    s, my_port = open_listener()
    print(f"Listening on UDP :{my_port} for {args.timeout:g} s")

    for _ in range(REPEATS):
        for dst in destinations:
            s.sendto(LAN_SEARCH, (dst, PORT))
        time.sleep(SEND_GAP_S)
    print(f"Sent LanSearch {REPEATS}x to each destination: {LAN_SEARCH.hex(' ')}")

    seen = []
    end = time.time() + args.timeout
    while time.time() < end:
        try:
            data, (src, sport) = s.recvfrom(4096)
        except socket.timeout:
            continue
        if src == ip and data == LAN_SEARCH:
            continue  # echo of our own broadcast
        seen.append((src, sport, data))
        print(f"\n<- {src}:{sport}  {len(data)} bytes")
        print(f"   hex: {data.hex(' ')}")
        print(f"   {describe(data)}")

    s.close()
    srcs = sorted({src for src, _, _ in seen})
    kinds = sorted({f"0x{d[1]:02x}" for _, _, d in seen if len(d) >= 2 and d[0] == 0xF1})
    print(f"\nSummary: {len(seen)} packet(s) from {len(srcs)} IP(s): {', '.join(srcs) or 'none'}")
    print(f"PPCS types seen: {', '.join(kinds) if kinds else 'none'}")


if __name__ == "__main__":
    main()
