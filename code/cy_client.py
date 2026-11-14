"LAN client for the CY365 camera (PPCS/PPPP), command-line tool. Flow: notes/protocol-findings.md, section 15."
import argparse
import json
import os
import re
import socket
import struct
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cy_session  # noqa: E402
import p2pcrypto as C  # noqa: E402
import video_assemble as VA  # noqa: E402
import cy_viewer as V  # noqa: E402
import p2pframe as F  # noqa: E402

KEY = b"SHIX"
PORT_LAN = 32108
VIEW = False
MAGIC_AV = b"\x55\xaa\x15\xa8"
AV_HEADER_LEN = 32
ALIVE_EVERY_S = 2.0
CMD_MARK = bytes([0x06, 0x0A, 0xA0, 0x80])  # phone -> camera command
RESP_MARK = bytes([0x06, 0x0A, 0xA1, 0x80])  # camera -> phone reply
# DID from the app capture (section 15): XXX / 000000 / XXXXX
DID_DEFAULT = cy_session.DEFAULT_DID


def log(step, ok, msg=""):
    print(f"[{step}] {'ok' if ok else 'FAILED'} {msg}".rstrip(), flush=True)


def mask(s: str) -> str:
    return re.sub(r'("pwd"\s*:\s*")[^"]*(")', r"\1***\2", s)


def local_ip() -> str:
    "Outgoing interface IP (connect() on UDP sends no packet)."
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def did_payload(prefix: bytes, number: int, suffix: bytes) -> bytes:
    "20 bytes of the PunchPkt: prefix @0, BE32 number @8, suffix @12 (zeros elsewhere)."
    p = bytearray(20)
    p[0:len(prefix)] = prefix
    struct.pack_into(">I", p, 8, number)
    p[12:12 + len(suffix)] = suffix
    return bytes(p)


def json_body(obj: dict) -> bytes:
    # separators without spaces, as the app does: the header size depends on it
    return json.dumps(obj, separators=(",", ":")).encode()


def cmd_packet(channel: int, seq: int, obj: dict) -> bytes:
    "DRW command: F1 D0 len | D1 ch seq | 06 0a a0 80 | len LE32 | JSON."
    body = json_body(obj)
    payload = CMD_MARK + struct.pack("<I", len(body)) + body
    return F.build_drw(channel, seq, payload)


def parse_cmd_response(plain: bytes):
    "Returns the JSON dict if the packet is a channel-0 command reply; else None."
    if len(plain) < 16 or plain[0] != 0xF1 or plain[1] != 0xD0:
        return None
    if plain[4] != 0xD1 or plain[5] != 0:
        return None
    payload = plain[8:]
    if payload[:4] != RESP_MARK:
        return None
    n = struct.unpack("<I", payload[4:8])[0]
    try:
        return json.loads(payload[8:8 + n].decode("utf-8", "replace"))
    except ValueError:
        return {"_erro": "invalid JSON"}


def jpeg_from_frame(frame: bytes):
    "Complete JPEG starting at byte 0 and ending at FF D9, or None."
    s = frame.find(b"\xff\xd8")
    if s != 0:
        return None
    e = frame.find(b"\xff\xd9", s + 2)
    return bytes(frame[:e + 2]) if e > 0 else None


class FrameAssembler:
    "Reassembles frames from channel-1 DRW chunks, ignoring repeated seq."

    def __init__(self):
        self.cur = None
        self.last_seq = None
        self.dups = 0

    def feed(self, seq: int, chunk: bytes):
        "Returns the frames (bytes after the header) that became complete."
        if self.last_seq is not None and seq == self.last_seq:
            self.dups += 1
            return []
        self.last_seq = seq
        done = []
        if chunk[:4] == MAGIC_AV:
            if self.cur is not None:
                done.append(bytes(self.cur))
            self.cur = bytearray(chunk[AV_HEADER_LEN:])
        elif self.cur is not None:
            self.cur += chunk
        return done

    def flush(self):
        if self.cur is None:
            return []
        out, self.cur = [bytes(self.cur)], None
        return out


def ack_packet(ch: int, seqs) -> bytes:
    "DRW ACK: F1 D1 len | D1 ch | n BE16 | n x seq BE16 (format from the app capture)."
    body = bytes([0xD1, ch]) + struct.pack(">H", len(seqs)) + b"".join(struct.pack(">H", q) for q in seqs)
    return bytes([0xF1, 0xD1]) + struct.pack(">H", len(body)) + body


class Link:
    def __init__(self, sock):
        self.s = sock

    def send(self, ip, port, plain: bytes):
        self.s.sendto(C.encrypt(KEY, plain), (ip, port))

    def recv(self, timeout: float):
        "(plain, (ip, port), raw), or None on timeout."
        self.s.settimeout(timeout)
        try:
            raw, addr = self.s.recvfrom(4096)
        except socket.timeout:
            return None
        return C.decrypt(KEY, raw), addr, raw


def step_lansearch(link, dests, timeout):
    pkt = C.encrypt(KEY, F.build_lan_search())
    for _ in range(3):
        for d in dests:
            link.s.sendto(pkt, (d, PORT_LAN))
        time.sleep(0.3)
    end = time.time() + timeout
    while time.time() < end:
        r = link.recv(0.5)
        if r is None:
            continue
        plain, (ip, port), raw = r
        if len(plain) >= 2 and plain[0] == 0xF1 and plain[1] == 0x30:
            continue  # echo of our own LanSearch
        print(f"    reply from {ip}:{port}, {len(raw)} bytes")
        print(f"    raw: {raw.hex(' ')}")
        print(f"    decrypted: {plain.hex(' ')}")
        if len(plain) >= 2 and plain[0] == 0xF1 and plain[1] in (0x41, 0x42):
            return ip, port
    return None


def step_handshake(link, ip, port, payload, tries=3, wait=3.0):
    plain = F.build_session(0x41, payload)
    for _ in range(tries):
        link.send(ip, port, plain)
        end = time.time() + wait
        while time.time() < end:
            r = link.recv(0.5)
            if r is None:
                continue
            p, addr, _ = r
            if addr[0] == ip and len(p) >= 2 and p[0] == 0xF1 and p[1] == 0x42:
                return True
    return False


def step_login(link, ip, port, pwd, seq=0, tries=5, wait=1.5):
    obj = {"pro": "check_user", "cmd": 100, "devmac": "0000", "user": "admin", "pwd": pwd}
    pkt = cmd_packet(0, seq, obj)
    for _ in range(tries):
        link.send(ip, port, pkt)
        end = time.time() + wait
        while time.time() < end:
            r = link.recv(0.3)
            if r is None:
                continue
            p, addr, _ = r
            if addr[0] != ip:
                continue
            response = parse_cmd_response(p)
            if response is not None:
                return response
    return None


def run_stream(link, ip, port, pwd, seconds, out_dir, seq=1):
    link.send(ip, port, cmd_packet(0, seq, {"pro": "stream", "cmd": 111, "video": 1,
                                             "camsmode": 0, "user": "admin", "pwd": pwd}))
    asm = VA.VideoAssembler(window=300)
    stats = {}
    saved = 0
    os.makedirs(out_dir, exist_ok=True)
    dump = open(os.path.join(out_dir, "ch1_dump.bin"), "wb")
    stamp = int(time.time())
    end = time.time() + seconds
    next_alive = 0.0
    closed = False
    while time.time() < end:
        now = time.time()
        if now >= next_alive:
            link.send(ip, port, F.build_alive())
            next_alive = now + ALIVE_EVERY_S
        r = link.recv(0.2)
        if r is None:
            continue
        p, addr, _ = r
        if addr[0] == ip and len(p) >= 2:
            key = (hex(p[0]), hex(p[1]), p[5] if len(p) > 5 and p[1] == 0xD0 and p[4] == 0xD1 else None)
            stats[key] = stats.get(key, 0) + 1
        if addr[0] != ip or len(p) < 4 or p[0] != 0xF1:
            continue
        if p[1] == 0xD0 and len(p) >= 8 and p[4] == 0xD1:
            seq_in = (p[6] << 8) | p[7]
            link.send(ip, port, ack_packet(p[5], [seq_in]))  # the camera only advances with an ACK
        if p[1] == 0xD0 and len(p) >= 8 and p[4] == 0xD1 and p[5] == 1:
            dump.write(struct.pack(">I", len(p)) + p)
            for _, fr in asm.feed(seq_in, p[8:]):
                saved += _save(fr, out_dir, stamp, saved)
        elif p[1] == 0xE0:
            link.send(ip, port, F.build_session(0xE1))
        elif p[1] == 0xF0:
            closed = True
            print("    camera sent Close (F1 F0)")
            break
    for _, fr in asm.flush():
        saved += _save(fr, out_dir, stamp, saved)
    dump.close()
    print(f"    duplicates ignored: {asm.n_dups}")
    print("    packets received (type, DRW type, channel): " + str(sorted(stats.items(), key=lambda kv: -kv[1])[:8]))
    return saved, closed


def _save(frame, out_dir, stamp, n):
    jpg = jpeg_from_frame(frame)
    if jpg is None:
        return 0
    if VIEW:
        V.publish(jpg)
    path = os.path.join(out_dir, f"frame_{stamp}_{n:05d}.jpg")
    with open(path, "wb") as f:
        f.write(jpg)
    print(f"    frame saved: {path} ({len(jpg)} bytes)")
    return 1


def main():
    ap = argparse.ArgumentParser(description="LAN client for CY365 (MJPEG video).")
    ap.add_argument("--cam", default=None, help="camera IP (default: source of the LanSearch reply)")
    ap.add_argument("--pwd", required=True, help="camera password (not saved or printed)")
    ap.add_argument("--out", default="captures/live", help="folder for the JPEGs")
    ap.add_argument("--seconds", type=float, default=30.0, help="stream duration")
    ap.add_argument("--timeout", type=float, default=5.0, help="wait for the LanSearch reply")
    ap.add_argument("--broadcast", default=None, help="subnet broadcast, e.g.: 192.168.1.255")
    ap.add_argument("--port", type=int, default=None,
                    help="camera UDP port (in the app capture: 29528); required if LanSearch gets no reply")
    ap.add_argument("--view", type=int, default=None,
                    help="show the live video at http://127.0.0.1:PORT (e.g.: 8080)")
    ap.add_argument("--did-prefix", default=DID_DEFAULT[0].decode())
    ap.add_argument("--did-number", type=int, default=DID_DEFAULT[1])
    ap.add_argument("--did-suffix", default=DID_DEFAULT[2].decode())
    a = ap.parse_args()
    global VIEW
    VIEW = a.view is not None
    if VIEW:
        threading.Thread(target=V.serve, kwargs={"host": "127.0.0.1", "port": a.view}, daemon=True).start()
        print(f"    live video: http://127.0.0.1:{a.view}")

    ip = local_ip()
    bcast = a.broadcast or ".".join(ip.split(".")[:3] + ["255"])
    dests = ["255.255.255.255"] + ([bcast] if bcast != "255.255.255.255" else [])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    link = Link(sock)
    print(f"local IP: {ip} | LanSearch destinations: {', '.join(dests)}")

    # 1-2. Encrypted LanSearch -> camera IP and port
    r = step_lansearch(link, dests, a.timeout)
    if r is None:
        if not (a.cam and a.port):
            log("1 LanSearch", False, "no PunchPkt/P2PRdy (0x41/0x42) reply decrypted; "
                "use --cam and --port to skip discovery; stopping")
            sys.exit(1)
        # In the app capture LanSearch also got no reply; the app went straight to port 29528.
        log("1 LanSearch", False, "no reply (same as the app capture); continuing with --cam/--port")
        resp_ip, resp_port = a.cam, a.port
    else:
        resp_ip, resp_port = r
        if a.cam and a.cam != resp_ip:
            print(f"    warning: --cam {a.cam} differs from the reply source {resp_ip}")
        log("1 LanSearch", True, f"camera at {resp_ip}:{resp_port}")
    cam_ip = a.cam or resp_ip
    log("2 alvo", True, f"{cam_ip}:{resp_port}")

    # 3. PunchPkt with the 20 DID bytes
    payload = did_payload(a.did_prefix.encode(), a.did_number, a.did_suffix.encode())
    if not step_handshake(link, cam_ip, resp_port, payload):
        log("3 handshake", False, "no F1 42 (P2PRdy) from camera; stopping")
        sys.exit(1)
    log("3 handshake", True, f"PunchPkt of {len(payload)} bytes; P2PRdy received")

    # 4. check_user
    response = step_login(link, cam_ip, resp_port, a.pwd)
    if response is None:
        log("4 login", False, "no reply 06 0a a1 80; stopping")
        sys.exit(1)
    if response.get("result") != 0:
        log("4 login", False, f"result={response.get('result')} (cmd={response.get('cmd')}); stopping")
        sys.exit(1)
    log("4 login", True, f"result=0 type={response.get('type')} mode={response.get('mode')} checkstr={response.get('checkstr')}")

    # 5-6. stream + Alive until the time runs out or Ctrl+C
    closed = False
    try:
        saved, closed = run_stream(link, cam_ip, resp_port, a.pwd, a.seconds, a.out)
        log("5 stream", saved > 0, f"{saved} JPEG saved to {a.out}")
    except KeyboardInterrupt:
        print("    interrupted")
    finally:
        if not closed:
            link.send(cam_ip, resp_port, F.build_session(0xF0))
            log("6 close", True, "F1 F0 sent")
        sock.close()


if __name__ == "__main__":
    main()
