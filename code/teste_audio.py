"Live audio test for the CY365 camera. Standard library plus cy_session. See --help."
import argparse
import math
import os
import struct
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cy_session as S  # noqa: E402

MAGIC = b"\x55\xaa\x15\xa8"
CODEC_IMA_ADPCM = 0x0B
AV_HEADER_LEN = 32
MAX_FRAME_SIZE = 1024
RATE = 8000
OUT_DIR = os.path.join(HERE, "..", "captures", "audio")


# ----- G.711 A-law -------------------------------------------------------------

def alaw_to_pcm16(byte):
    "One A-law byte -> signed 16-bit PCM sample. Reference: g711.c (ITU-T G.711). Check values: 0xD5 -> +8, 0x55 -> -8, 0xAA -> +32256, 0x2A -> -32256."
    a = (byte & 0xFF) ^ 0x55
    t = (a & 0x0F) << 4
    seg = (a & 0x70) >> 4
    if seg == 0:
        t += 8
    elif seg == 1:
        t += 0x108
    else:
        t += 0x108
        t <<= seg - 1
    return t if a & 0x80 else -t


ALAW_TABLE = [alaw_to_pcm16(b) for b in range(256)]


# IMA ADPCM (4 bits, HIGH nibble first), state reset per frame.
# Confirmed: CAdpcm::ADPCMDecode (0x1d30fc) for codec 0x0B (Gemini); audio listened to and approved.
IMA_STEP = [7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767]
IMA_INDEX = [-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8]


def ima_pcm_bytes(data):
    "Decodes one IMA ADPCM frame to 16-bit little-endian PCM (state reset at the start of the frame)."
    pred, idx, out = 0, 0, []
    for b in data:
        for n in ((b >> 4) & 15, b & 15):
            step = IMA_STEP[idx]
            diff = step >> 3
            if n & 4:
                diff += step
            if n & 2:
                diff += step >> 1
            if n & 1:
                diff += step >> 2
            pred += -diff if n & 8 else diff
            pred = max(-32768, min(32767, pred))
            idx = max(0, min(88, idx + IMA_INDEX[n]))
            out.append(pred)
    return b"".join(struct.pack("<h", x) for x in out)


def alaw_to_pcm_bytes(data):
    "A-law block -> 16-bit little-endian PCM bytes."
    return b"".join(struct.pack("<h", ALAW_TABLE[b]) for b in data)


# ----- frame reassembly -----

class FrameParser:
    "Takes audio-channel payloads and returns A-law frames in arrival order. One DRW payload may hold several frames: the magic is searched in the whole payload, each frame is consumed by its header size, and identical payloads (retransmissions) are dropped."

    def __init__(self):
        self.frames = []
        self.pending = None        # [expected size, bytearray] of a frame that continues in the next payload
        self._seen = set()
        self.n_packets = 0
        self.n_duplicates = 0
        self.n_orphans = 0           # payload without magic and without a pending frame
        self.n_rest = 0            # bytes between frames that belong to none
        self.n_other_codec = 0
        self.n_size_mismatch = 0       # invalid header size (0 or > MAX_FRAME_SIZE)
        self.n_incomplete = 0      # frame that did not close in the next payload nor at the end

    def feed(self, payload):
        p = bytes(payload)
        self.n_packets += 1
        if p in self._seen:
            self.n_duplicates += 1
            return
        self._seen.add(p)
        if self.pending is not None:
            if p[:4] == MAGIC:
                self.n_incomplete += 1          # previous frame never closed
                self.pending = None
            else:
                pos = self._complete(p, 0)
                self._scan(p, pos)
                return
        if p.find(MAGIC) != 0:
            if MAGIC not in p:
                self.n_orphans += 1
                return
            self.n_rest += p.find(MAGIC)
        self._scan(p, p.find(MAGIC))

    def _scan(self, p, pos):
        while 0 <= pos < len(p):
            i = p.find(MAGIC, pos)
            if i < 0:
                self.n_rest += len(p) - pos
                return
            self.n_rest += i - pos
            pos = self._open_frame(p, i)

    def _open_frame(self, p, i):
        "Reads the header at p[i:]; returns the position right after the frame (or len(p) if it continues)."
        if len(p) - i < AV_HEADER_LEN:
            self.n_rest += len(p) - i
            return len(p)
        n = struct.unpack_from("<I", p, i + 16)[0]
        start_at = i + AV_HEADER_LEN
        if n == 0 or n > MAX_FRAME_SIZE:
            self.n_size_mismatch += 1
            n = len(p) - start_at              # uses what is left of the payload
        if p[i + 4] != CODEC_IMA_ADPCM:
            self.n_other_codec += 1
            return min(len(p), start_at + n)
        if start_at + n <= len(p):
            self.frames.append(p[start_at:start_at + n])
            return start_at + n
        self.pending = [n, bytearray(p[start_at:])]
        return len(p)

    def _complete(self, p, pos):
        "Fills the pending frame with the start of p from pos; returns the next free position."
        n, data = self.pending
        needed = n - len(data)
        chunk = p[pos:pos + needed]
        data += chunk
        if len(data) >= n:
            self.frames.append(bytes(data))
            self.pending = None
        return pos + len(chunk)

    def end(self):
        if self.pending is not None:
            self.n_incomplete += 1
            self.pending = None
        return self.frames


def build_frames(payloads):
    r = FrameParser()
    for p in payloads:
        r.feed(p)
    return r.end(), r


# ----- metrics and WAV -----

def metrics(samples):
    n = len(samples)
    if n == 0:
        return {"amostras": 0, "rms": 0.0, "pico": 0, "pct_nao_zero": 0.0, "pct_acima_piso": 0.0}
    rms = math.sqrt(sum(s * s for s in samples) / n)
    return {
        "amostras": n,
        "duracao_s": round(n / RATE, 3),
        "rms": round(rms, 1),
        "pico": max(abs(s) for s in samples),
        "pct_nao_zero": round(100.0 * sum(1 for s in samples if s != 0) / n, 2),
        # the A-law silence code (0xD5/0x55) decodes to +-8; this counts only what goes above that floor
        "pct_acima_piso": round(100.0 * sum(1 for s in samples if abs(s) > 8) / n, 2),
    }


def save_wav(path, pcm_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm_bytes)
    return path


def samples_of(pcm_bytes):
    return list(struct.unpack("<%dh" % (len(pcm_bytes) // 2), pcm_bytes))


# ----- real capture -----

def capture(session, seconds, log):
    "Starts audio, waits and returns (payloads, format). Does not stop audio: the caller does it in finally."
    received = []
    session.start_audio(on_audio=lambda p: received.append((time.time(), p)))
    log(f"audio on (stream audio=1); recording {seconds:g} s")
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(0.2)
    return received, session.observed_format()


def run_capture(a):
    session = S.CameraSession(a.cam, a.port, a.pwd, log=print)
    started = False
    try:
        session.connect()
        session.login()
        print("login ok")
        received, formats = None, None
        started = True
        received, formats = capture(session, a.seconds, print)
        started = False
        session.stop_audio()
    except S.CameraError as e:
        print(f"failed at [{e.stage}]: {e.reason}")
        return 1
    finally:
        if started:
            try:
                session.stop_audio()
            except S.CameraError:
                pass
        session.close()

    print(f"non-video channels received: {sorted(formats.keys())}")
    if 2 not in formats:
        print("ERROR: no packets on channel 2 (audio). Possible causes: audio was not turned on in the camera, "
              "the stream audio=1 command was not accepted, or the audio channel is another one. See observed_format().")
        print(f"observed format: {formats}")
        return 2
    payloads = [p for _, p in received]
    frames, rem = build_frames(payloads)
    pcm = b"".join(ima_pcm_bytes(f) for f in frames)
    m = metrics(samples_of(pcm))
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = save_wav(os.path.join(a.out, f"audio_{ts}.wav"), pcm)
    print(f"packets received (non-video channels): {len(payloads)}")
    print(f"frames assembled: {len(frames)} | A-law bytes: {sum(len(f) for f in frames)}")
    print(f"discarded: orphans={rem.n_orphans} other_codec={rem.n_other_codec} size_mismatch={rem.n_size_mismatch}")
    print(f"duration: {m['duracao_s']} s | RMS: {m['rms']} | peak: {m['pico']}")
    print(f"samples != 0: {m['pct_nao_zero']}% | above silence floor (|x|>8): {m['pct_acima_piso']}%")
    print(f"WAV: {path}")
    return 0


# ----- real payloads from the app capture -----

DEFAULT_PCAP = os.path.join(HERE, "..", "captures", "PCAPdroid_15_out._01_26_14.pcap")
PCAP_CAMERA_IP = "192.168.1.100"


def pcap_payloads(path=DEFAULT_PCAP, cam=PCAP_CAMERA_IP, channel=2):
    "DRW payloads of the given channel sent by the camera, decrypted with SHIX. Returns [(seq, payload)]."
    import analyze_pcap as A
    import p2pcrypto as C
    out = []
    for frame in A.read_pcap(path):
        u = A.udp_of(frame)
        if not u or u[0] != cam:
            continue
        q = C.decrypt(b"SHIX", u[4])
        if len(q) >= 8 and q[1] == 0xD0 and q[4] == 0xD1 and q[5] == channel:
            out.append(((q[6] << 8) | q[7], q[8:]))
    return out


# ----- offline tests -----

def _tests():
    import tempfile
    failures = []

    def ok(name, cond, extra=""):
        print(f"[{'ok' if cond else 'FAILED'}] {name} {extra}".rstrip())
        if not cond:
            failures.append(name)

    # 1. A-law reference values
    first_samples = samples_of(ima_pcm_bytes(bytes.fromhex("18282101 0198aa00 a89d")))
    ok("IMA: first real frame (capture) = known first samples",
       first_samples[:8] == [1, 1, 4, 4, 7, 8, 8, 9], str(first_samples[:8]))
    # 1c. first frame of the real capture decodes to the known first samples
    if os.path.exists(DEFAULT_PCAP):
        capture_frames, _ = build_frames([p for _, p in pcap_payloads()])
        ok("IMA: first capture frame = [1, 1, 4, 4, 7, 8, 8, 9]",
           samples_of(ima_pcm_bytes(capture_frames[0]))[:8] == [1, 1, 4, 4, 7, 8, 8, 9],
           str(samples_of(ima_pcm_bytes(capture_frames[0]))[:8]))
    ok("A-law 0xD5 -> +8", alaw_to_pcm16(0xD5) == 8, str(alaw_to_pcm16(0xD5)))
    ok("A-law 0x55 -> -8", alaw_to_pcm16(0x55) == -8, str(alaw_to_pcm16(0x55)))
    ok("A-law 0xAA -> +32256 (full scale)", alaw_to_pcm16(0xAA) == 32256, str(alaw_to_pcm16(0xAA)))
    ok("A-law 0x2A -> -32256", alaw_to_pcm16(0x2A) == -32256, str(alaw_to_pcm16(0x2A)))
    positives = [alaw_to_pcm16(b) for b in range(256) if alaw_to_pcm16(b) > 0]
    ok("A-law: 128 distinct positive levels",
       sorted(set(positives)) == sorted(positives) and len(set(positives)) == 128, f"{len(set(positives))} levels")
    ok("A-law: 256 codes, symmetry (x and -x)",
       all(alaw_to_pcm16(b) == -alaw_to_pcm16(b ^ 0x80) for b in range(256)))
    pcm = alaw_to_pcm_bytes(bytes([0xD5, 0x55, 0xAA]))
    ok("PCM bytes LE of 3 samples", struct.unpack("<3h", pcm) == (8, -8, 32256), pcm.hex(" "))

    # 1b. equivalence with the app's ADecode (libobject_jni.so:001d352c), transcribed to Python
    def adecode_app(b):
        u = (b ^ 0x55) & 0xFF
        seg = ((u >> 4)) & 7
        step = (u & 0xF) << 4
        if seg == 1:
            val = step | 0x108
        elif seg == 0:
            val = step | 8
        else:
            val = (step | 0x108) << (seg - 1)
        return val if (u & 0x80) else -val
    ok("A-law = app ADecode for all 256 codes", all(alaw_to_pcm16(b) == adecode_app(b) for b in range(256)))

    # 2. reassembly of fabricated frames
    def header(n, codec=CODEC_IMA_ADPCM):
        return MAGIC + bytes([codec, 1, 0, 0]) + b"\x00" * 8 + struct.pack("<I", n) + b"\x00" * 12

    f1 = bytes(range(160))
    f2 = bytes([0xD5]) * 352
    frames, r = build_frames([header(160) + f1, header(352)[:32] + f2])
    ok("reassembly: 2 complete frames (160 and 352)", [len(f) for f in frames] == [160, 352], str([len(f) for f in frames]))
    ok("reassembly: frame content preserved", frames[0] == f1)

    # frame split across two packets
    frames, r = build_frames([header(352) + f2[:320], f2[320:]])
    ok("reassembly: frame split across packets", len(frames) == 1 and frames[0] == f2, f"{len(frames)} frame(s)")

    # header size larger than the packet and no continuation -> discarded
    frames, r = build_frames([header(352) + b"\x01" * 10])
    ok("reassembly: incomplete frame without continuation is not output", frames == [], str(len(frames)))

    # orphan data before the first magic and a different codec
    frames, r = build_frames([b"\x11" * 40, header(160, codec=0x08) + f1, header(160) + f1])
    ok("reassembly: orphan and different codec are counted",
       len(frames) == 1 and r.n_orphans == 1 and r.n_other_codec == 1, f"orphans={r.n_orphans} codec={r.n_other_codec}")

    # absurd size falls back to what is left of the packet
    frames, r = build_frames([header(0xFFFF) + f1])
    ok("reassembly: size mismatch uses the rest of the packet",
       len(frames) == 1 and frames[0] == f1 and r.n_size_mismatch == 1)

    # 2b. several frames per payload, retransmissions and garbage before the magic
    frames, r = build_frames([header(160) + f1 + header(160) + f1[::-1]])
    ok("two frames in the same payload (offsets 0 and 192)",
       len(frames) == 2 and frames[0] == f1 and frames[1] == f1[::-1], f"{len(frames)} frame(s)")
    frames, r = build_frames([header(160) + f1, header(160) + f1])
    ok("identical payload is a retransmission (dropped)", len(frames) == 1 and r.n_duplicates == 1)
    frames, r = build_frames([b"\x00" * 5 + header(160) + f1])
    ok("garbage before the magic counted in n_rest", len(frames) == 1 and r.n_rest == 5, f"rest={r.n_rest}")

    # 2c. real app capture
    if os.path.exists(DEFAULT_PCAP):
        pairs = pcap_payloads()
        pays = [p for _, p in pairs]
        ok("pcap: 64 channel-2 payloads", len(pays) == 64, str(len(pays)))
        ok("pcap: 4 of 192 bytes and 60 of 384 bytes",
           sorted(len(p) for p in pays).count(192) == 4 and sorted(len(p) for p in pays).count(384) == 60)
        raw_magics = sum(p.count(MAGIC) for p in pays)
        frames, r = build_frames(pays)
        ok("pcap: raw magic = 124 (60x2 + 4x1, with repetitions)", raw_magics == 124, str(raw_magics))
        ok("pcap: 12 retransmissions dropped", r.n_duplicates == 12, str(r.n_duplicates))
        ok("pcap: unique frames = 100", len(frames) == 100, str(len(frames)))
        ok("pcap: each frame has 160 bytes of audio", all(len(f) == 160 for f in frames))
        ok("pcap: no magic inside the audio", not any(MAGIC in f for f in frames))
        ok("pcap: no orphans, other codec, mismatches or incomplete frames",
           (r.n_orphans, r.n_other_codec, r.n_size_mismatch, r.n_incomplete) == (0, 0, 0, 0),
           f"orphans={r.n_orphans} codec={r.n_other_codec} size={r.n_size_mismatch} inc={r.n_incomplete}")
    else:
        print("[skipped] real capture: PCAP does not exist")

    # 3. metrics
    m = metrics([0, 0, 0, 0])
    ok("metrics: pure silence (RMS 0)", m["rms"] == 0 and m["pct_nao_zero"] == 0)
    m = metrics([8, -8, 8, -8])
    ok("metrics: A-law silence floor is != 0 but not above the floor", m["pct_nao_zero"] == 100 and m["pct_acima_piso"] == 0)
    m = metrics([1000, -1000] * 4000)
    ok("metrics: signal of 1000 (RMS 1000, peak 1000)", m["rms"] == 1000.0 and m["pico"] == 1000, str(m))
    ok("metrics: duration 1 s for 8000 samples", metrics([1] * 8000)["duracao_s"] == 1.0)

    # 4. WAV: write and reopen
    with tempfile.TemporaryDirectory() as folder:
        samples = [1000, -1000, 0, 32000] * 100
        pcm_test = struct.pack("<%dh" % len(samples), *samples)
        path = save_wav(os.path.join(folder, "t.wav"), pcm_test)
        with wave.open(path, "rb") as w:
            params = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
            read_value = w.readframes(w.getnframes())
        ok("WAV: mono, 16 bits, 8000 Hz, correct frames", params == (1, 2, 8000, len(samples)), str(params))
        ok("WAV: reopened samples equal", samples_of(read_value) == samples)

    print("\nRESULT:", "all ok" if not failures else f"FAILED: {failures}")
    return not failures


def make_pcap_wav(output):
    "WAV from the real capture payloads, decoded frame by frame with IMA ADPCM (state reset per frame)."
    frames, r = build_frames([p for _, p in pcap_payloads()])
    pcm = b"".join(ima_pcm_bytes(f) for f in frames)
    samples = samples_of(pcm)
    m = metrics(samples)
    m["near_zero_|x|<=64_%"] = round(100.0 * sum(1 for x in samples if abs(x) <= 64) / len(samples), 2)
    save_wav(output, pcm)
    print(f"frames: {len(frames)} | duplicates dropped: {r.n_duplicates}")
    for k, v in m.items():
        print(f"{k}: {v}")
    print(f"WAV: {output}")


def main():
    ap = argparse.ArgumentParser(description="Live audio test for the CY365 camera.")
    ap.add_argument("--cam", default=None, help="camera IP (optional; LanSearch discovers it)")
    ap.add_argument("--port", type=int, default=None, help="camera UDP port (optional)")
    ap.add_argument("--pwd", default=None, help="camera password (not saved or printed)")
    ap.add_argument("--segundos", dest="seconds", type=float, default=10.0)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--testes", dest="tests", action="store_true", help="offline tests, no camera")
    ap.add_argument("--pcap", metavar="WAV", default=None,
                    help="builds the WAV from the app capture (no camera) and prints metrics")
    a = ap.parse_args()
    if a.tests:
        sys.exit(0 if _tests() else 1)
    if a.pcap:
        make_pcap_wav(a.pcap)
        return
    if not a.pwd:
        sys.exit("missing --pwd")
    sys.exit(run_capture(a))


if __name__ == "__main__":
    main()
