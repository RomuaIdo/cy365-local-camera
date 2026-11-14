"Server with a fake camera for interface tests. Usage: python3 -I -B teste_servidor_falso.py PORT [--audio-feed | --audio-burst]"
import os
import struct
import sys
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import servidor as S

FRAME_BYTES = 160       # 320 samples = 40 ms at 8000 Hz
FRAME_PERIOD_S = 0.04


def audio_feed(burst=False):
    """Send fake IMA frames to the audio callback of the latest session: real time, or bursts of 10 every 400 ms."""
    header = b"\x55\xaa\x15\xa8\x0b\x01\x00\x00" + b"\x00" * 8 + struct.pack("<I", FRAME_BYTES) + b"\x00" * 12
    while True:
        time.sleep(0.4 if burst else FRAME_PERIOD_S)
        if not S.FakeCamera.created:
            continue
        callback = S.FakeCamera.created[-1].audio_callback
        if callback is None:
            continue
        for _ in range(10 if burst else 1):
            callback(header + os.urandom(FRAME_BYTES))


if __name__ == "__main__":
    port = int(sys.argv[1])
    if "--audio-feed" in sys.argv[2:] or "--audio-burst" in sys.argv[2:]:
        threading.Thread(target=audio_feed, args=("--audio-burst" in sys.argv[2:],), daemon=True).start()
    httpd = S.create_server("127.0.0.1", port, factory=S._fake_factory)
    print("ready", flush=True)
    httpd.serve_forever()
