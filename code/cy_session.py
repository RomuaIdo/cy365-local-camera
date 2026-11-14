"Reusable camera session. Standard library plus project modules; see the usage block."
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
import p2pcrypto as C  # noqa: E402
import p2pframe as F  # noqa: E402
from video_assemble import VideoAssembler  # noqa: E402

DEFAULT_KEY = b"SHIX"
_DID_RE = re.compile(r"^([A-Za-z]{3})(\d{6})([A-Za-z]{5})$")


def parse_did(text):
    """Parse a device identifier such as ABC123456DEFGH into (prefix, number, suffix)."""
    m = _DID_RE.match(text.strip())
    if not m:
        raise ValueError("CAMERA_DID must look like PPPNNNNNNSSSSS (3 letters, 6 digits, 5 letters)")
    return m.group(1).encode(), int(m.group(2)), m.group(3).encode()


# Set CAMERA_DID to your camera's identifier; the placeholder is only for offline tests.
DEFAULT_DID = parse_did(os.environ.get("CAMERA_DID", "XXX000000XXXXX"))
LAN_PORT = 32108
CHANNEL_CMD = 0
CHANNEL_VIDEO = 1
CMD_MARK = bytes([0x06, 0x0A, 0xA0, 0x80])   # phone -> camera
RESP_MARK = bytes([0x06, 0x0A, 0xA1, 0x80])  # camera -> phone
ALIVE_EVERY_S = 2.0
CMD_RESEND_S = 1.5
VIDEO_WINDOW = 300  # seq window; frames stuck after packet loss are dropped after that
LOGIN_FIELDS = ("result", "admin", "type", "mode", "checkstr")


class CameraError(Exception):
    "Failure in one session step: `stage` says where, `reason` says why."

    def __init__(self, stage, reason):
        self.stage = stage
        self.reason = reason
        super().__init__(f"[{stage}] {reason}")


def mask(text: str) -> str:
    "Replaces the value of \"pwd\" with *** in any JSON written to a log."
    return re.sub(r'("pwd"\s*:\s*")[^"]*(")', r"\1***\2", text)


def _local_ip() -> str:
    "Outgoing interface IP (connect() on UDP sends no packet)."
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def _did_payload(prefix: bytes, number: int, suffix: bytes) -> bytes:
    "20 bytes of the PunchPkt: prefix @0, BE32 number @8, suffix @12."
    p = bytearray(20)
    p[0:len(prefix)] = prefix
    struct.pack_into(">I", p, 8, number)
    p[12:12 + len(suffix)] = suffix
    return bytes(p)


def _ack(ch: int, seq: int) -> bytes:
    "DRW ACK: F1 D1 len | D1 ch | n BE16 | seq BE16 (format from the app capture)."
    body = bytes([0xD1, ch]) + struct.pack(">H", 1) + struct.pack(">H", seq)
    return bytes([0xF1, 0xD1]) + struct.pack(">H", len(body)) + body


def _json_from_response(payload: bytes):
    "Payload of a channel-0 DRW: returns the dict if it has the 06 0a a1 80 header, else None."
    # The camera uses a1 80 for the login reply (check_user) and a0 80 for the others (e.g. cmd 9000, 126, 1).
    if len(payload) < 8 or payload[:2] != b"\x06\x0a" or payload[2] not in (0xA0, 0xA1) or payload[3] != 0x80:
        return None
    n = struct.unpack("<I", payload[4:8])[0]
    try:
        obj = json.loads(payload[8:8 + n].decode("utf-8", "replace"))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


class CameraSession:
    def __init__(self, ip, port, pwd, did=DEFAULT_DID, key=DEFAULT_KEY, user="admin", log=None):
        self.ip = ip
        self.port = port
        self.user = user
        self.did = did
        self.key = key
        self._pwd = pwd                 # never printed or saved
        self._log_fn = log or (lambda m: print(m, flush=True))
        self._sock = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._responses = {}            # cmd -> last JSON dict received on channel 0
        self._cmd_seq = -1
        self._running = False
        self._thread = None
        self._camera_closed = False
        self._on_frame = None
        self._on_audio = None
        self._asm = VideoAssembler(window=VIDEO_WINDOW)
        self._formats = {}              # channel -> data observed on the non-video channels
        self.connected = False

    # ----- helpers -----

    def _log(self, msg):
        self._log_fn(mask(msg))

    def _send(self, plain: bytes):
        self._sock.sendto(C.encrypt(self.key, plain), (self.ip, self.port))

    def _recv(self, timeout):
        "(plain, addr) or None on timeout or if the packet does not decrypt."
        self._sock.settimeout(timeout)
        try:
            raw, addr = self._sock.recvfrom(4096)
        except socket.timeout:
            return None
        try:
            return C.decrypt(self.key, raw), addr
        except Exception:
            return None

    def _next_seq(self) -> int:
        with self._lock:
            self._cmd_seq = (self._cmd_seq + 1) & 0xFFFF
            return self._cmd_seq

    # ----- connection -----

    def connect(self, lansearch_timeout=5.0):
        "Encrypted LanSearch -> PunchPkt (F1 41) -> P2PRdy (F1 42). Starts the receive thread."
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.bind(("", 0))
        ip_local = _local_ip()
        bcast = ".".join(ip_local.split(".")[:3] + ["255"])
        destinations = ["255.255.255.255", bcast] + ([self.ip] if self.ip else [])

        pkt = C.encrypt(self.key, F.build_lan_search())
        for _ in range(3):
            for d in dict.fromkeys(destinations):
                self._sock.sendto(pkt, (d, LAN_PORT))
            time.sleep(0.3)
        found = None
        deadline = time.time() + lansearch_timeout
        while time.time() < deadline and found is None:
            r = self._recv(0.5)
            if r is None:
                continue
            plain, (rip, rport) = r
            if len(plain) >= 2 and plain[0] == 0xF1 and plain[1] in (0x41, 0x42):
                found = (rip, rport)
        if found is None:
            raise CameraError("lansearch", f"no PunchPkt/P2PRdy reply within {lansearch_timeout:.0f}s")
        rip, rport = found
        if self.ip and self.ip != rip:
            self._log(f"warning: configured ip {self.ip} differs from reply {rip}; using {rip}")
        self.ip, self.port = rip, rport
        self._log(f"camera at {self.ip}:{self.port}")

        payload = _did_payload(*self.did)
        if not self._handshake(payload):
            raise CameraError("handshake", "no P2PRdy (F1 42) after 3 attempts")

        self.connected = True
        self._running = True
        self._thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._thread.start()

    def _handshake(self, payload, tries=3, wait=3.0):
        plain = F.build_session(0x41, payload)
        for _ in range(tries):
            self._send(plain)
            deadline = time.time() + wait
            while time.time() < deadline:
                r = self._recv(0.5)
                if r is None:
                    continue
                p, (rip, _) = r
                if rip == self.ip and len(p) >= 2 and p[0] == 0xF1 and p[1] == 0x42:
                    return True
        return False

    def _rx_loop(self):
        next_alive = 0.0
        while self._running:
            now = time.time()
            if now >= next_alive:
                self._send(F.build_alive())
                next_alive = now + ALIVE_EVERY_S
            r = self._recv(0.2)
            if r is None:
                continue
            p, addr = r
            try:
                self._process(p, addr)
            except Exception as e:  # a bad packet does not drop the session
                self._log(f"packet ignored: {e}")

    # ----- receive -----

    def _process(self, p: bytes, addr):
        "Handles a decrypted camera packet. Called by the receive thread (and by the tests)."
        if addr is not None and addr[0] != self.ip:
            return
        if len(p) < 4 or p[0] != 0xF1:
            return
        if p[1] == 0xD0 and len(p) >= 8 and p[4] == 0xD1:
            ch = p[5]
            seq = (p[6] << 8) | p[7]
            self._send(_ack(ch, seq))  # the camera only advances with an ACK
            payload = p[8:]
            if ch == CHANNEL_CMD:
                obj = _json_from_response(payload)
                if obj is not None and "cmd" in obj:
                    with self._cond:
                        self._responses[obj["cmd"]] = obj
                        self._cond.notify_all()
            elif ch == CHANNEL_VIDEO:
                for _, jpg in self._asm.feed(seq, payload):
                    if self._on_frame is not None:
                        self._on_frame(jpg)
            else:
                self._record_format(ch, seq, payload)
                if self._on_audio is not None:
                    self._on_audio(bytes(payload))
        elif p[1] == 0xE0:
            self._send(F.build_session(0xE1))
        elif p[1] == 0xF0:
            self._camera_closed = True
            self._log("camera sent Close (F1 F0)")

    def _record_format(self, ch, seq, payload):
        f = self._formats.setdefault(ch, {"packets": 0, "sizes": set(), "first_bytes": None,
                                          "first_seq": seq})
        f["packets"] += 1
        f["sizes"].add(len(payload))
        if f["first_bytes"] is None:
            f["first_bytes"] = bytes(payload[:16]).hex(" ")

    def observed_format(self):
        "Channel -> {packets, sizes, first_bytes (hex of the first packet), first_seq}."
        return {ch: dict(v) for ch, v in self._formats.items()}

    # ----- commands -----

    def _command_packet(self, seq, body: dict) -> bytes:
        body = json.dumps(body, separators=(",", ":")).encode()
        payload = CMD_MARK + struct.pack("<I", len(body)) + body
        return F.build_drw(CHANNEL_CMD, seq, payload)

    def command(self, pro, cmd, fields=None, timeout=5.0):
        "Sends {pro, cmd, ...fields, user, pwd} on channel 0 and returns the reply with the same cmd. Resends every CMD_RESEND_S with the same seq; replies for other cmds are stored or ignored."
        if not self.connected:
            raise CameraError(f"command {pro}/{cmd}", "session not connected")
        fields = dict(fields or {})
        if set(fields) & {"pro", "cmd"}:
            raise ValueError("fields must not contain 'pro' or 'cmd'")
        body = {"pro": pro, "cmd": cmd, **fields, "user": self.user, "pwd": self._pwd}
        seq = self._next_seq()
        packet = self._command_packet(seq, body)
        self._log(f"command {pro} cmd={cmd} seq={seq}")
        with self._cond:
            self._responses.pop(cmd, None)
        deadline = time.time() + timeout
        next_send = 0.0
        while True:
            now = time.time()
            if now >= deadline:
                raise CameraError(f"command {pro}/{cmd}", f"no reply within {timeout:.1f}s")
            if now >= next_send:
                self._send(packet)
                next_send = now + CMD_RESEND_S
            with self._cond:
                if cmd in self._responses:
                    return self._responses.pop(cmd)
                self._cond.wait(timeout=0.1)

    def _send_command_no_reply(self, pro, cmd, fields):
        "Stream commands: the camera's reply is not verified; just sends (as cy_client does)."
        body = {"pro": pro, "cmd": cmd, **fields, "user": self.user, "pwd": self._pwd}
        self._send(self._command_packet(self._next_seq(), body))

    def login(self):
        "check_user (cmd 100). Returns {result, admin, type, mode, checkstr}; CameraError on failure."
        try:
            response = self.command("check_user", 100, {"devmac": "0000"}, timeout=7.5)
        except CameraError as e:
            raise CameraError("login", f"no check_user reply ({e.reason})") from e
        result = response.get("result")
        if result != 0:
            raise CameraError("login", f"result={result} (cmd={response.get('cmd')})")
        self._log("login ok")
        return {k: response.get(k) for k in LOGIN_FIELDS}

    # ----- video and audio -----

    def start_video(self, on_frame):
        "Stream cmd 111 video=1; each complete JPEG goes to on_frame(bytes)."
        self._on_frame = on_frame
        self._send_command_no_reply("stream", 111, {"video": 1, "camsmode": 0})
        self._log("video started")

    def stop_video(self):
        "Stops delivering frames and sends stream cmd 111 video=0 (not verified on the camera)."
        self._on_frame = None
        self._send_command_no_reply("stream", 111, {"video": 0, "camsmode": 0})
        self._log("video stopped")

    def start_audio(self, on_audio=None):
        "Stream cmd 111 audio=1. Non-video payloads go to on_audio(bytes)."
        self._on_audio = on_audio
        self._send_command_no_reply("stream", 111, {"audio": 1})
        self._log("audio started")

    def stop_audio(self):
        self._on_audio = None
        self._send_command_no_reply("stream", 111, {"audio": 0})
        self._log("audio stopped")

    # ----- shutdown -----

    def close(self):
        if not self.connected:
            return
        self._running = False
        if not self._camera_closed:
            self._send(F.build_session(0xF0))
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sock.close()
        self.connected = False
        self._log("session closed")


# ----- offline tests (no camera) -----

class _FakeSocket:
    "Imitates the UDP socket: each send is decrypted, recorded and may produce camera replies."

    def __init__(self, session, responder):
        self.session = session
        self.responder = responder   # fn(body_dict, n_send) -> list of decrypted packets
        self.sent = []           # decrypted packets sent by the session
        self.n_cmd = 0

    def sendto(self, data, addr):
        plain = C.decrypt(self.session.key, data)
        self.sent.append(plain)
        if plain[:2] == bytes([0xF1, 0xD0]) and plain[4:6] == bytes([0xD1, 0]):
            payload = plain[8:]
            n = struct.unpack("<I", payload[4:8])[0]
            body = json.loads(payload[8:8 + n].decode())
            self.n_cmd += 1
            for response in self.responder(body, self.n_cmd):
                self.session._process(response, (self.session.ip, self.session.port))

    def settimeout(self, t):
        pass

    def close(self):
        pass


def _response_packet(seq, obj):
    body = json.dumps(obj, separators=(",", ":")).encode()
    payload = RESP_MARK + struct.pack("<I", len(body)) + body
    return F.build_drw(CHANNEL_CMD, seq, payload)


def _prepare(responder, pwd="example-pwd"):
    logs = []
    s = CameraSession("192.168.1.100", 12804, pwd, log=logs.append)
    s.connected = True
    s._sock = _FakeSocket(s, responder)
    return s, logs


def _tests():
    failures = []

    def ok(name, cond, extra=""):
        print(f"[{'ok' if cond else 'FAILED'}] {name} {extra}".rstrip())
        if not cond:
            failures.append(name)

    # 1. login result 0 with out-of-order reply (cmd 9000 arrives first)
    def resp_out_of_order(body, n):
        out = [_response_packet(0, {"cmd": 9000, "result": 0})]
        out.append(_response_packet(0, {"cmd": 100, "admin": 1, "result": 0, "type": 2020,
                                      "mode": 2020, "checkstr": "SHIX", "checkver": 3}))
        return out
    s, logs = _prepare(resp_out_of_order)
    info = s.login()
    ok("login result 0 with out-of-order reply", info["result"] == 0 and info["checkstr"] == "SHIX", str(info))
    ok("pwd does not appear in the log", all("example-pwd" not in l for l in logs))

    # 2. result != 0 becomes CameraError with stage login
    s, _ = _prepare(lambda c, n: [_response_packet(0, {"cmd": 100, "result": 13})])
    try:
        s.login()
        ok("result 13 raises CameraError", False)
    except CameraError as e:
        ok("result 13 raises CameraError(login)", e.stage == "login" and "result=13" in e.reason, str(e))

    # 3. no reply: explicit timeout
    s, _ = _prepare(lambda c, n: [])
    try:
        s.command("check_user", 100, {"devmac": "0000"}, timeout=0.6)
        ok("no reply raises an error", False)
    except CameraError as e:
        ok("no reply raises CameraError with timeout", "no reply" in e.reason, str(e))

    # 4. resend: the first attempt gets no reply, the second one does
    s, _ = _prepare(lambda c, n: [] if n == 1 else [_response_packet(0, {"cmd": 100, "result": 0})])
    r = s.command("check_user", 100, {"devmac": "0000"}, timeout=4.0)
    ok("command resent when the first attempt gets no reply", r.get("result") == 0 and s._sock.n_cmd == 2,
       f"sends={s._sock.n_cmd}")

    # 5. only a different cmd arrives: no match, timeout
    s, _ = _prepare(lambda c, n: [_response_packet(0, {"cmd": 9000, "result": 0})])
    try:
        s.command("check_user", 100, {"devmac": "0000"}, timeout=0.6)
        ok("different cmd does not match", False)
    except CameraError:
        ok("different cmd does not match", True)

    # 6. exact ACK for a channel-0 DRW, seq 5
    s, _ = _prepare(lambda c, n: [])
    s._process(_response_packet(5, {"cmd": 1, "result": 0}), (s.ip, s.port))
    expected_ack = bytes.fromhex("f1 d1 00 06 d1 00 00 01 00 05")
    ok("ACK F1 D1 for channel-0 DRW seq 5", expected_ack in s._sock.sent, expected_ack.hex(" "))

    # 7. close sends an encrypted F1 F0
    s, _ = _prepare(lambda c, n: [])
    s.close()
    ok("close sends F1 F0", s._sock.sent[-1] == bytes([0xF1, 0xF0, 0, 0]), s._sock.sent[-1].hex(" "))

    # 8. video: the offline dump goes through the session and yields the same JPEGs as the assembler
    dump = os.path.join(HERE, "..", "captures", "live", "ch1_dump.bin")
    if os.path.exists(dump):
        import video_assemble as V
        expected, _ = V.jpeg_frames_from_dump(dump)
        s, _ = _prepare(lambda c, n: [])
        frames = []
        s._on_frame = frames.append
        for seq, payload in V.read_dump(dump):
            s._process(F.build_drw(CHANNEL_VIDEO, seq, payload), (s.ip, s.port))
        # the dump may grow while a capture runs: compare with the assembler, not a fixed number
        ok("video: frames emitted by the session = direct assembler",
           frames == expected[:len(frames)] and len(frames) >= len(expected) - 1,
           f"session={len(frames)} assembler={len(expected)}")
    else:
        print("[skipped] video: captures/live/ch1_dump.bin does not exist")

    # 9. audio: channel 2 goes to on_audio and the format is recorded
    s, _ = _prepare(lambda c, n: [])
    received = []
    s._on_audio = received.append
    s._process(F.build_drw(2, 7, b"\x01\x02\x03\x04" * 10), (s.ip, s.port))
    fmt = s.observed_format()
    ok("audio: payload delivered to the callback", received == [b"\x01\x02\x03\x04" * 10])
    ok("audio: format recorded for channel 2", fmt.get(2, {}).get("sizes") == {40}, str(fmt.get(2)))

    # 10. masking
    ok("mask() replaces pwd", mask('{"pwd":"example-pwd","user":"admin"}') == '{"pwd":"***","user":"admin"}')

    # 11. command without connection
    s = CameraSession("192.168.1.100", 12804, "example-pwd")
    try:
        s.command("check_user", 100)
        ok("command without connection raises an error", False)
    except CameraError as e:
        ok("command without connection raises CameraError", e.stage.startswith("command"), str(e))

    print("\nRESULT:", "all ok" if not failures else f"FAILED: {failures}")
    return not failures


if __name__ == "__main__":
    if "--testes" in sys.argv:
        sys.exit(0 if _tests() else 1)
    print("usage: python3 -I -B notes/code/cy_session.py --testes   (offline tests; the camera is not used)")
