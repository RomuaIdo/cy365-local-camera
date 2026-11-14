"Live CY365 viewer in the browser (MJPEG). Standard library only."
import argparse
import glob
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOUNDARY = "frame"
DEFAULT_FPS = 15.0

_queue = queue.Queue(maxsize=1)          # only the latest frame matters
_cond = threading.Condition()
_latest = None                          # last published JPEG (bytes)
_frame_count = 0                          # counter so clients can tell whether there is a new frame
_start_lock = threading.Lock()
_pumping = False

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CY365 live</title>
<style>
  html, body { margin: 0; height: 100%; background: #000; overflow: hidden; }
  img { display: block; width: 100vw; height: 100vh; object-fit: contain; }
</style>
</head>
<body>
<img src="/stream" alt="CY365 live">
</body>
</html>
"""


def _pump():
    "Thread: takes frames from the queue, keeps the latest one and wakes the /stream clients."
    global _latest, _frame_count
    while True:
        jpeg = _queue.get()
        with _cond:
            _latest = jpeg
            _frame_count += 1
            _cond.notify_all()


def _ensure_pump():
    global _pumping
    with _start_lock:
        if not _pumping:
            threading.Thread(target=_pump, daemon=True).start()
            _pumping = True


def publish(jpeg: bytes):
    "Publishes a JPEG. If the queue is full, drops the older frame (keeps only the newest)."
    _ensure_pump()
    while True:
        try:
            _queue.put_nowait(jpeg)
            return
        except queue.Full:
            try:
                _queue.get_nowait()
            except queue.Empty:
                pass


class Handler(BaseHTTPRequestHandler):
    server_version = "CY365Viewer/1.0"

    def log_message(self, fmt, *args):
        pass  # no log line per request

    def do_GET(self):
        if self.path == "/":
            body = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/stream":
            self._stream()
        else:
            self.send_error(404)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        interval = 1.0 / DEFAULT_FPS
        try:
            while True:
                t0 = time.time()
                with _cond:
                    jpeg = _latest
                if jpeg is not None:
                    self.wfile.write(
                        f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n".encode()
                    )
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                time.sleep(max(0.0, interval - (time.time() - t0)))
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser closed the tab


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host="127.0.0.1", port=8080):
    "Starts the HTTP server and blocks until Ctrl+C."
    _ensure_pump()
    httpd = Server((host, port), Handler)
    print(f"CY365 live at http://{host}:{port}  (Ctrl+C to quit)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _demo(folder, fps):
    "Reads the JPEGs in a folder and publishes them in a loop, to test without the camera."
    files = sorted(glob.glob(os.path.join(folder, "*.jpg")))
    if not files:
        raise SystemExit(f"no .jpg in {folder}")
    frames = []
    for path in files:
        with open(path, "rb") as f:
            frames.append(f.read())
    print(f"demo: {len(frames)} frames from {folder}, {fps:.0f} fps in a loop", flush=True)
    interval = 1.0 / fps
    while True:
        for jpeg in frames:
            t0 = time.time()
            publish(jpeg)
            time.sleep(max(0.0, interval - (time.time() - t0)))


def main():
    global DEFAULT_FPS
    ap = argparse.ArgumentParser(description="MJPEG viewer for the CY365 camera.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--demo", metavar="DIR", default=None, help="publishes the .jpg files in the folder in a loop")
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS, help="frames per second for /stream and the demo")
    a = ap.parse_args()
    DEFAULT_FPS = a.fps

    if a.demo:
        threading.Thread(target=_demo, args=(a.demo, a.fps), daemon=True).start()
    serve(a.host, a.port)


if __name__ == "__main__":
    main()
