"MJPEG frame assembly by sequence number. Standard library only."
import argparse
import bisect
import os
import random
import struct

MAGIC = b"\x55\xaa\x15\xa8"
AV_HEADER_LEN = 32
SEQ_MOD = 1 << 16
CHANNEL = 1


class VideoAssembler:
    "Takes (seq, payload) in any order and returns complete JPEG frames."

    def __init__(self, window=None):
        self.window = window          # window in seqs before stuck frames are dropped (None = never)
        self.chunks = {}              # unwrapped seq -> payload
        self.starts = []             # unwrapped seqs of magic packets not yet decided, in order
        self._hi = None              # highest unwrapped seq seen
        self._floor = -1              # frames starting below this are already decided
        self.n_complete = 0
        self.n_discarded = 0
        self.n_dups = 0
        self.n_late = 0

    def _unwrap(self, seq):
        "Unwraps a BE16 seq into an increasing integer (handles the 65535 -> 0 wrap)."
        if self._hi is None:
            self._hi = seq
            return seq
        base = self._hi - (self._hi % SEQ_MOD)
        u = min((base - SEQ_MOD + seq, base + seq, base + SEQ_MOD + seq), key=lambda c: abs(c - self._hi))
        if u > self._hi:
            self._hi = u
        return u

    def feed(self, seq, payload):
        "Stores the chunk and returns [(start_seq, jpeg)] for the frames just decided."
        u = self._unwrap(seq)
        if u < self._floor:
            self.n_late += 1
            return []
        if u in self.chunks:
            self.n_dups += 1
            return []
        payload = bytes(payload)
        self.chunks[u] = payload
        if payload[:4] == MAGIC and u not in self.starts:
            bisect.insort(self.starts, u)
        return self._decide(final=False)

    def flush(self):
        "End of stream: decide everything; the last frame ends at the highest seq seen."
        return self._decide(final=True)

    def missing(self):
        "BE16 seqs missing between the pending frame start and the highest seq seen."
        if not self.starts or self._hi is None:
            return []
        return [q % SEQ_MOD for q in range(self.starts[0], self._hi + 1) if q not in self.chunks]

    def _decide(self, final):
        output = []
        while self.starts and (len(self.starts) >= 2 or final):
            s0 = self.starts[0]
            s1 = self.starts[1] if len(self.starts) >= 2 else self._hi + 1
            missing = any(q not in self.chunks for q in range(s0, s1))
            expired = self.window is not None and self._hi - s0 > self.window
            if missing and not final and not expired:
                break  # wait for the rest of the range
            jpg = None if missing else self._jpeg(s0, s1)
            if jpg is None:
                self.n_discarded += 1
            else:
                self.n_complete += 1
                output.append((s0, jpg))
            for q in [q for q in self.chunks if q < s1]:
                del self.chunks[q]
            self.starts.pop(0)
            self._floor = s1
        return output

    def _jpeg(self, s0, s1):
        "JPEG of the range [s0, s1), or None if it does not start with FF D8 or has no FF D9."
        body = b"".join(self.chunks[q] for q in range(s0, s1))[AV_HEADER_LEN:]
        if body[:2] != b"\xff\xd8":
            return None
        end = body.find(b"\xff\xd9", 2)
        return None if end < 0 else body[:end + 2]


def read_dump(path):
    "Reads ch1_dump.bin: [(seq, payload)] of channel-1 DRW packets, in file order."
    with open(path, "rb") as f:
        data = f.read()
    output, i = [], 0
    while i + 4 <= len(data):
        n = struct.unpack_from(">I", data, i)[0]
        pkt = data[i + 4:i + 4 + n]
        i += 4 + n
        if len(pkt) < 8 or pkt[0] != 0xF1 or pkt[1] != 0xD0 or pkt[4] != 0xD1 or pkt[5] != CHANNEL:
            continue
        output.append(((pkt[6] << 8) | pkt[7], pkt[8:]))
    return output


def jpeg_frames_from_dump(path, shuffle=None):
    "(complete, discarded) frames from the dump. shuffle=seed reorders arrivals (test)."
    packets = read_dump(path)
    if shuffle is not None:
        random.Random(shuffle).shuffle(packets)
    asm = VideoAssembler()
    output = []
    for seq, payload in packets:
        output += asm.feed(seq, payload)
    output += asm.flush()
    output.sort(key=lambda t: t[0])
    return [jpg for _, jpg in output], asm.n_discarded


def main():
    ap = argparse.ArgumentParser(description="Assembles JPEG frames from the dump by seq.")
    ap.add_argument("dump", help="e.g.: captures/live/ch1_dump.bin")
    ap.add_argument("--exemplos", dest="examples", default=None, help="folder to save 3 sample JPEGs")
    ap.add_argument("--embaralhar", dest="shuffle", type=int, default=None, help="seed: redo with the shuffled order and compare")
    a = ap.parse_args()

    packets = read_dump(a.dump)
    complete, discarded = jpeg_frames_from_dump(a.dump)
    total = len(complete) + discarded
    rate = 100.0 * discarded / total if total else 0.0
    print(f"channel 1 packets: {len(packets)}")
    print(f"complete frames: {len(complete)}")
    print(f"discarded frames: {discarded}")
    print(f"discard rate: {rate:.1f}% ({discarded}/{total})")

    bad = [i for i, j in enumerate(complete) if not (j[:2] == b"\xff\xd8" and j[-2:] == b"\xff\xd9")]
    print(f"saved JPEGs that do not start with FF D8 and end with FF D9: {len(bad)}")

    if a.shuffle is not None:
        complete2, discarded2 = jpeg_frames_from_dump(a.dump, shuffle=a.shuffle)
        same = complete2 == complete and discarded2 == discarded
        print(f"shuffled order (seed {a.shuffle}): complete {len(complete2)}, discarded {discarded2}")
        print(f"result {'SAME' if same else 'DIFFERENT'} from the original order")

    if a.examples:
        os.makedirs(a.examples, exist_ok=True)
        chosen = [0, len(complete) // 2, len(complete) - 1]
        for n, i in enumerate(chosen):
            path = os.path.join(a.examples, f"teste_T014_{n}_quadro{i:04d}.jpg")
            with open(path, "wb") as f:
                f.write(complete[i])
            print(f"sample saved: {path} ({len(complete[i])} bytes)")


if __name__ == "__main__":
    main()
