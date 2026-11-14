"Measures the effect of icut (infrared) and set_whiteLight (light) on video frames, without looking at the camera."
import argparse
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cy_session as S  # noqa: E402


def measure(jpeg: bytes):
    "Returns (mean brightness, mean saturation) of a JPEG, via djpeg -> PPM."
    p = subprocess.run(["djpeg", "-pnm"], input=jpeg, capture_output=True)
    if p.returncode != 0:
        return None
    data = p.stdout
    # PPM header: P6 <w> <h> <max>
    parts, i = [], 0
    while len(parts) < 4:
        while data[i:i + 1].isspace():
            i += 1
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        parts.append(data[i:j])
        i = j
    i += 1
    px = data[i:]
    n = len(px) // 3
    if n == 0:
        return None
    sum_lum = sum(px) / 3.0
    sum_sat = 0
    for k in range(0, n * 3, 3):
        r, g, b = px[k], px[k + 1], px[k + 2]
        sum_sat += max(r, g, b) - min(r, g, b)
    return sum_lum / n, sum_sat / n


class Collector:
    def __init__(self):
        self.frames = []
        self.lock = threading.Lock()

    def __call__(self, jpeg):
        with self.lock:
            self.frames.append(jpeg)
            if len(self.frames) > 60:
                del self.frames[:-60]

    def grab(self, n, wait):
        with self.lock:
            self.frames.clear()
        time.sleep(wait)
        with self.lock:
            return list(self.frames[-n:])


def measure_phase(col, name, n=12, wait=4.0):
    qs = col.grab(n, wait)
    vals = [m for m in (measure(q) for q in qs) if m]
    if not vals:
        print(f"  {name}: no frames")
        return None
    lum = sum(v[0] for v in vals) / len(vals)
    sat = sum(v[1] for v in vals) / len(vals)
    print(f"  {name}: frames={len(vals)} brightness={lum:.1f} saturation={sat:.1f}")
    return lum, sat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", required=True)
    ap.add_argument("--pwd", required=True)
    ap.add_argument("--confirmar", dest="confirm", action="store_true")
    a = ap.parse_args()
    if not a.confirm:
        print("Not run: --confirmar is missing (this step writes to the camera).")
        return 2

    sess = S.CameraSession(a.cam, None, a.pwd)
    sess.connect()
    sess.login()
    print("login ok")
    pair = sess.command("get_parms", 101)
    icut0, lamp0 = pair.get("icut"), pair.get("lamp")
    light0 = sess.command("get_whiteLight", 305).get("status")
    print(f"originals: icut={icut0} light={light0} lamp={lamp0}")
    col = Collector()
    sess.start_video(col)
    results = {}
    try:
        time.sleep(2)
        print("1. baseline (current state)")
        results["base"] = measure_phase(col, "base")
        for v in (0, 1, 2):
            sess._send_command_no_reply("dev_control", 102, {"icut": v})
            print(f"2. icut={v}")
            results[f"icut{v}"] = measure_phase(col, f"icut={v}")
        for v in (0, 1):
            sess.command("set_whiteLight", 304, {"status": v})
            print(f"3. light status={v}")
            results[f"light{v}"] = measure_phase(col, f"light={v}")
    finally:
        sess._send_command_no_reply("dev_control", 102, {"icut": icut0})
        sess.command("set_whiteLight", 304, {"status": light0})
        print(f"restored: icut={icut0} light={light0}")
        sess.stop_video()
        sess.close()
    print("SUMMARY:", {k: (round(v[0], 1), round(v[1], 1)) for k, v in results.items() if v})
    return 0


if __name__ == "__main__":
    sys.exit(main())
