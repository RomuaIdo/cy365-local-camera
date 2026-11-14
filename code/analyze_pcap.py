"Analyses the app capture (PCAPdroid, raw IP): decrypts PPCS packets with SHIX and extracts video JPEGs. See --help."
import argparse, collections, os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p2pcrypto as c  # noqa: E402

MAGIC_AV = b"\x55\xaa\x15\xa8"


def read_pcap(path):
    data = open(path, "rb").read()
    off, out = 24, []
    while off + 16 <= len(data):
        _, _, incl, _ = struct.unpack("<IIII", data[off:off + 16])
        off += 16
        out.append(data[off:off + incl])
        off += incl
    return out


def udp_of(p):
    if len(p) < 28 or p[0] >> 4 != 4 or p[9] != 17:
        return None
    ihl = (p[0] & 15) * 4
    sp, dp = struct.unpack(">HH", p[ihl:ihl + 4])
    src = ".".join(map(str, p[12:16]))
    dst = ".".join(map(str, p[16:20]))
    return src, sp, dst, dp, p[ihl + 8:]


def body(d):
    i = d.index(bytes([0x06, 0x0A]))
    n = struct.unpack("<I", d[i + 4:i + 8])[0]
    return d[i + 8:i + 8 + n].decode("latin1", "replace")


def mask(s):
    return re.sub(r'("pwd"\s*:\s*")[^"]*(")', r"\1***\2", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap")
    ap.add_argument("--cam", required=True, help="camera IP in the capture")
    ap.add_argument("--key", default="SHIX")
    ap.add_argument("--frames", default=None, help="folder to save the JPEGs")
    a = ap.parse_args()
    key = a.key.encode()

    up, down = [], []
    for p in read_pcap(a.pcap):
        u = udp_of(p)
        if not u:
            continue
        src, sp, dst, dp, pay = u
        if src == a.cam:
            down.append(c.decrypt(key, pay))
        elif dst == a.cam:
            up.append(c.decrypt(key, pay))

    for name, lst in (("camera -> phone", down), ("phone -> camera", up)):
        kinds = collections.Counter((hex(d[1]), (d[2] << 8 | d[3]) == len(d) - 4) for d in lst if len(d) >= 4)
        print(f"{name}: {len(lst)} packets; types (type, len matches?): {kinds.most_common(8)}")

    print("\nJSON commands from the phone (password masked):")
    seen = set()
    for d in up:
        if d[1] == 0xD0 and d[8:12] == bytes([0x06, 0x0A, 0xA0, 0x80]):
            b = mask(body(d))
            k = b[:60]
            if k not in seen:
                seen.add(k)
                print("  ", b[:220])
    print("\nJSON replies from the camera:")
    for d in down:
        if d[1] == 0xD0 and d[8:12] == bytes([0x06, 0x0A, 0xA1, 0x80]):
            print("  ", mask(body(d)).replace("\n", " ").replace("\t", "")[:220])
            break

    frames, cur = [], None
    for d in down:
        if d[1] == 0xD0 and d[4] == 0xD1 and d[5] == 1:
            chunk = d[8:]
            if chunk[:4] == MAGIC_AV:
                if cur is not None:
                    frames.append(cur)
                cur = bytearray(chunk[32:])
            elif cur is not None:
                cur += chunk
    if cur is not None:
        frames.append(cur)
    saved = 0
    if a.frames:
        os.makedirs(a.frames, exist_ok=True)
    for i, fr in enumerate(frames):
        s = fr.find(b"\xff\xd8")
        e = fr.find(b"\xff\xd9", s + 2) if s >= 0 else -1
        if s == 0 and e > 0 and a.frames:
            open(os.path.join(a.frames, f"frame_{i:03d}.jpg"), "wb").write(bytes(fr[:e + 2]))
            saved += 1
    print(f"\nVideo frames rebuilt: {len(frames)}; complete JPEGs saved: {saved}")


if __name__ == "__main__":
    main()
