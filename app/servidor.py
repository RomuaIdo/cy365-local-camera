"Local server for the CY365 app. Standard library only; API in notes/app/ui_spec.md, section 2. Binds 127.0.0.1 by default."
import argparse
import http.client
import json
import mimetypes
import os
import queue
import re
import struct
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(HERE, "..", "code")
sys.path.insert(0, CODE)
import cy_session as S  # noqa: E402
import cy_viewer as V  # noqa: E402
from teste_audio import FrameParser, ima_pcm_bytes  # noqa: E402

FEATURES = os.path.join(HERE, "..", "docs", "features.md")
STATIC = os.path.join(HERE, "static")
DEFAULT_PORT = 8080
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
COMMAND_TIMEOUT_S = 5.0
MAX_BODY = 16 * 1024
IPV4 = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
RESERVED_KEYS = {"pro", "cmd", "user", "pwd"}
# The camera has NO SD card slot (reported by the user; notes/capacidades_camera.md).
# These commands are removed from the list and blocked (403) in /api/comando.
NO_SD_SLOT = {"get_sd", "set_sd", "get_record_param", "set_record_param", "get_record_day",
               "get_record_list", "play_record_file", "del_record_file", "start_videofiles",
               "stop_videofiles", "get_videofiles"}


# ----- resources (notes/features.md) -----

def load_resources(path=FEATURES):
    "Reads the notes/features.md table: one item per command of priority 1 and 2. SD commands are left out; no file gives an empty list."
    if not os.path.exists(path):
        return []
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("| **"):
                continue
            col = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(col) < 7:
                continue
            m = re.search(r"\d", col[6])
            priority = int(m.group()) if m else 0
            if priority not in (1, 2):
                continue
            names = re.findall(r"`([A-Za-z_0-9]+)`", col[1])
            numbers = [int(n) for g in re.findall(r"\(([\d /]+)\)", col[1]) for n in re.findall(r"\d+", g)]
            if len(names) == len(numbers):
                pairs = list(zip(names, numbers))
            elif len(names) == 1 and numbers:
                pairs = [(names[0], n) for n in numbers]
            else:
                pairs = []
            proven = "sim" in col[4].lower()
            name = col[0].strip("* ")
            for pro, cmd in pairs:
                if pro in NO_SD_SLOT:
                    continue
                items.append({"id": pro, "cmd": cmd, "name": name, "priority": priority,
                              "proven": proven, "write": not pro.startswith("get_")})
    return items


def _mask_obj(obj):
    "Replaces values of sensitive keys with *** at any depth (camera output)."
    if isinstance(obj, dict):
        return {k: ("***" if re.search(r"pwd|pass|token|senha", k, re.I) else _mask_obj(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_obj(v) for v in obj]
    return obj


def _log(msg):
    # CameraSession already masks "pwd" in its messages
    print(msg, file=sys.stderr, flush=True)


# ----- single session state -----

class State:
    def __init__(self):
        self._lock = threading.Lock()
        self._listeners = []
        self._session = None
        self._fields = {"state": "disconnected", "reason": None, "video_on": False,
                        "audio_on": False, "last_error": None}

    def snapshot(self):
        with self._lock:
            return dict(self._fields)

    def _publish(self):
        snap = dict(self._fields)
        for q in self._listeners:
            try:
                q.put_nowait(snap)
            except queue.Full:
                pass
        return snap

    def update(self, **fields):
        with self._lock:
            self._fields.update(fields)
            return self._publish()

    def start_connection(self):
        "Moves to 'connecting' atomically. False if already connecting or connected."
        with self._lock:
            if self._fields["state"] in ("connecting", "connected"):
                return False
            self._fields.update(state="connecting", reason=None)
            self._publish()
            return True

    def session(self):
        with self._lock:
            return self._session

    def set_session(self, s):
        with self._lock:
            self._session = s

    def listen(self):
        q = queue.Queue(maxsize=64)
        with self._lock:
            self._listeners.append(q)
        return q

    def stop_listening(self, q):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)


# ----- server -----

WAV_RATE = 8000
MAX_PAYLOADS_PER_PARSER = 512   # the parser's dedupe set grows per payload; recreate it periodically
LISTENER_QUEUE_CHUNKS = 50      # ~2 s of 40 ms frames; slow listeners lose the oldest chunks
READBACK_WAIT_S = 0.5           # dev_control has no reply; wait before reading get_parms back
READBACK_TRIES = 3


def _wav_header_streaming():
    """WAV header with unknown length (0xFFFFFFFF) for a live stream: PCM 16 bit, mono, 8000 Hz."""
    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, WAV_RATE, WAV_RATE * 2, 2, 16)
            + b"data" + struct.pack("<I", 0xFFFFFFFF))


def _put_dropping_oldest(q, item):
    while True:
        try:
            q.put_nowait(item)
            return
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass


PACING_MAX_LAG_S = 0.25  # resynchronise the send clock after this much delay


def chunk_duration(nbytes):
    """Seconds of audio in a 16-bit mono PCM chunk."""
    return nbytes / (2 * WAV_RATE)


def pacing_step(now, due, duration, max_lag=PACING_MAX_LAG_S):
    """Return (send_at, next_due): chunks leave one `duration` apart; a stall restarts the clock."""
    if due is None or now - due > max_lag:
        due = now  # late: send now, do not burst to catch up
    send_at = max(now, due)
    return send_at, send_at + duration


class AudioHub:
    """Decodes camera IMA ADPCM frames to PCM and fans them out to /audio.wav listeners."""

    def __init__(self):
        self._lock = threading.Lock()
        self._parser = FrameParser()
        self._listeners = []

    def reset(self):
        with self._lock:
            self._parser = FrameParser()

    def feed(self, payload):
        """Session thread callback: one non-video payload at a time."""
        with self._lock:
            if self._parser.n_packets >= MAX_PAYLOADS_PER_PARSER:
                self._parser = FrameParser()
            self._parser.feed(payload)
            frames, self._parser.frames = self._parser.frames, []
            for frame in frames:
                pcm = ima_pcm_bytes(frame)  # state is reset per frame, as in the camera
                for q in self._listeners:
                    _put_dropping_oldest(q, pcm)

    def subscribe(self):
        q = queue.Queue(maxsize=LISTENER_QUEUE_CHUNKS)
        with self._lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)


def _read_back(s, key, expected):
    """Poll get_parms until `key` equals `expected`; returns the last value read."""
    value = None
    for _ in range(READBACK_TRIES):
        time.sleep(READBACK_WAIT_S)
        value = s.command("get_parms", 101).get(key)
        if value == expected:
            break
    return value


class App:
    def __init__(self, factory, resources):
        self.state = State()
        self.factory = factory
        self.resources = resources
        self.allowed = {(r["id"], r["cmd"]): not r["write"] for r in resources}
        self.audio = AudioHub()


def _close_quietly(session):
    try:
        session.close()
    except Exception:
        pass


class Handler(V.Handler):
    "Inherits _stream and log_message from cy_viewer; adds the API and static files."

    server_version = "CY365App/1.0"
    app = None  # set in create_server()

    # ----- HTTP helpers -----

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, msg, **extra):
        self._json(code, {"error": msg, **extra})

    def _host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host in ALLOWED_HOSTS:
            return True
        self._error(403, "host not allowed")
        return False

    def _body(self, optional=False):
        "JSON body as a dict. Answers 400/413 and returns None if invalid."
        size = int(self.headers.get("Content-Length") or 0)
        if size == 0 and optional:
            return {}
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind != "application/json":
            self._error(400, "expects Content-Type: application/json")
            return None
        if size > MAX_BODY:
            self._error(413, "request body too large")
            return None
        try:
            obj = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            self._error(400, "invalid JSON")
            return None
        if not isinstance(obj, dict):
            self._error(400, "the body must be a JSON object")
            return None
        return obj

    # ----- routing -----

    def do_GET(self):
        if not self._host_ok():
            return
        path = urlparse(self.path).path
        try:
            if path == "/stream":
                return self._stream_route()
            if path == "/api/estado":
                return self._json(200, self.app.state.snapshot())
            if path == "/api/recursos":
                return self._json(200, {"resources": self.app.resources})
            if path == "/api/info":
                return self._info()
            if path == "/api/rede":
                return self._network()
            if path == "/audio.wav":
                return self._audio_wav()
            if path == "/api/eventos":
                return self._events()
            if path == "/":
                return self._file("index.html")
            if path.startswith("/static/"):
                return self._file(path[len("/static/"):])
            return self._error(404, "not found")
        except Exception as e:  # never returns the exception text (it may hold sensitive data)
            return self._error(500, f"internal error: {type(e).__name__}")

    def do_POST(self):
        if not self._host_ok():
            return
        path = urlparse(self.path).path
        routes = {
            "/api/conectar": self._connect,
            "/api/desconectar": self._disconnect,
            "/api/video": self._video,
            "/api/audio": self._audio,
            "/api/comando": self._command,
            "/api/indicador": self._indicator,
            "/api/infravermelho": self._infrared,
        }
        if path not in routes:
            return self._error(404, "not found")
        body = self._body(optional=(path == "/api/desconectar"))
        if body is None:
            return
        try:
            return routes[path](body)
        except Exception as e:
            return self._error(500, f"internal error: {type(e).__name__}")

    def _stream_route(self):
        if not self.app.state.snapshot()["video_on"]:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._stream()  # cy_viewer: multipart/x-mixed-replace with the latest frame

    # ----- connection lifecycle -----

    def _connect(self, c):
        pwd = c.get("pwd")
        if not isinstance(pwd, str) or not pwd:
            return self._error(400, "Password required")
        ip = c.get("ip")
        if ip is not None and (not isinstance(ip, str) or not IPV4.match(ip)):
            return self._error(400, "invalid IP address")
        port = c.get("port")
        if port is not None and (not isinstance(port, int) or isinstance(port, bool)):
            return self._error(400, "invalid port")
        E = self.app.state
        if not E.start_connection():
            return self._error(409, "Session already connected")

        session = self.app.factory(ip, port, pwd, log=_log)
        try:
            session.connect()
            info = session.login()
        except S.CameraError as e:
            _close_quietly(session)
            if e.stage == "login" and "result=" in e.reason:
                code, msg = 401, "Incorrect password"
                detail = e.reason
            elif e.stage == "login" or e.stage in ("lansearch", "handshake"):
                code, msg = 504, "Camera did not respond on the local network"
                detail = e.reason
            else:
                code, msg, detail = 502, "Camera failure", e.reason
            snap = E.update(state="error", reason=msg, last_error=f"{msg}: {detail}",
                           video_on=False, audio_on=False)
            return self._json(code, {"error": msg, "detail": detail, "stage": e.stage, "state": snap})
        except Exception as e:
            _close_quietly(session)
            snap = E.update(state="error", reason="Internal failure", last_error=type(e).__name__,
                           video_on=False, audio_on=False)
            return self._json(500, {"error": "Internal failure", "state": snap})

        E.set_session(session)
        snap = E.update(state="connected", reason=None, last_error=None,
                       video_on=False, audio_on=False)
        info = {k: info.get(k) for k in S.LOGIN_FIELDS if k != "result"}
        return self._json(200, {"state": snap["state"], "info": info})

    def _active_session(self):
        "Connected session, or None after answering 401/409."
        E = self.app.state
        state = E.snapshot()["state"]
        if state == "connecting":
            self._error(409, "connection in progress")
            return None
        s = E.session()
        if state != "connected" or s is None:
            self._error(401, "Session not connected")
            return None
        return s

    def _disconnect(self, _):
        E = self.app.state
        if E.snapshot()["state"] == "connecting":
            return self._error(409, "connection in progress")
        s = E.session()
        if s is None:
            return self._error(401, "Session not connected")
        snap = E.snapshot()
        try:
            if snap["video_on"]:
                s.stop_video()
            if snap["audio_on"]:
                s.stop_audio()
        except S.CameraError:
            pass  # the session is closed anyway
        _close_quietly(s)
        E.set_session(None)
        snap = E.update(state="disconnected", reason=None, video_on=False, audio_on=False)
        return self._json(200, {"state": snap["state"]})

    # ----- video and audio -----

    def _video(self, c):
        on = c.get("on")
        if not isinstance(on, bool):
            return self._error(400, "on must be true or false")
        s = self._active_session()
        if s is None:
            return
        E = self.app.state
        if on != E.snapshot()["video_on"]:
            try:
                s.start_video(V.publish) if on else s.stop_video()
            except S.CameraError as e:
                return self._error(502, "Camera failure", detail=e.reason)
            E.update(video_on=on)
        return self._json(200, {"video_on": on})

    def _audio(self, c):
        on = c.get("on")
        if not isinstance(on, bool):
            return self._error(400, "on must be true or false")
        s = self._active_session()
        if s is None:
            return
        E = self.app.state
        if on != E.snapshot()["audio_on"]:
            try:
                if on:
                    self.app.audio.reset()
                    s.start_audio(self.app.audio.feed)
                else:
                    s.stop_audio()
            except S.CameraError as e:
                return self._error(502, "Camera failure", detail=e.reason)
            E.update(audio_on=on)
        return self._json(200, {"audio_on": on})

    # ----- info, indicator, infrared, network and playable audio -----

    def _info(self):
        s = self._active_session()
        if s is None:
            return
        try:
            parms = s.command("get_parms", 101)
        except S.CameraError as e:
            return self._error(504, "Camera did not reply in time", detail=e.reason)
        return self._json(200, {
            "battery": parms.get("power"),
            "charging": parms.get("charging") == 1,
            "firmware": parms.get("sysver"),
            "time": parms.get("time"),
            "led_status": parms.get("lamp"),
        })

    def _set_dev_control(self, field, value):
        """Send dev_control (no reply expected) and read the value back. Returns (ok, value_read)."""
        s = self._active_session()
        if s is None:
            return False, None
        try:
            s._send_command_no_reply("dev_control", 102, {field: value})
            read = _read_back(s, field, value)
        except S.CameraError as e:
            self._error(504, "Camera did not reply in time", detail=e.reason)
            return False, None
        _log(f"dev_control {field}={value} read={read}")
        return True, read

    def _indicator(self, c):
        on = c.get("on")
        if not isinstance(on, bool):
            return self._error(400, "on must be true or false")
        value = 1 if on else 0
        ok, read = self._set_dev_control("lamp", value)
        if ok:
            self._json(200, {"indicator": read == 1, "confirmed": read == value})

    def _infrared(self, c):
        mode = c.get("mode")
        if not isinstance(mode, int) or isinstance(mode, bool) or mode not in (0, 1, 2):
            return self._error(400, "mode must be 0, 1 or 2")
        ok, read = self._set_dev_control("icut", mode)
        if ok:
            self._json(200, {"mode": read, "confirmed": read == mode})

    def _network(self):
        s = self._active_session()
        if s is None:
            return
        try:
            wifi = s.command("get_wifi", 112)
        except S.CameraError as e:
            return self._error(504, "Camera did not reply in time", detail=e.reason)
        return self._json(200, {"ssid": wifi.get("ssid"), "conmode": wifi.get("conmode")})

    def _audio_wav(self):
        E = self.app.state
        if not E.snapshot()["audio_on"]:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()
        q = self.app.audio.subscribe()
        due = None
        try:
            self.wfile.write(_wav_header_streaming())
            self.wfile.flush()
            while E.snapshot()["audio_on"]:
                try:
                    chunk = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                send_at, due = pacing_step(time.monotonic(), due, chunk_duration(len(chunk)))
                wait = send_at - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.app.audio.unsubscribe(q)

    # ----- commands -----

    def _command(self, c):
        pro, cmd = c.get("pro"), c.get("cmd")
        fields = c.get("fields", {})
        if not isinstance(pro, str) or not pro:
            return self._error(400, "pro is required")
        if not isinstance(cmd, int) or isinstance(cmd, bool):
            return self._error(400, "cmd must be an integer")
        if not isinstance(fields, dict):
            return self._error(400, "fields must be an object")
        if set(fields) & RESERVED_KEYS:
            return self._error(400, "fields cannot contain pro, cmd, user or pwd")
        s = self._active_session()
        if s is None:
            return
        key = (pro, cmd)
        if key not in self.app.allowed:
            return self._error(403, "Command not allowed")
        reading = self.app.allowed[key]
        if not reading and c.get("confirmed") is not True:
            return self._error(403, "Write operation needs explicit confirmation (confirmed=true)")
        try:
            response = s.command(pro, cmd, fields, timeout=COMMAND_TIMEOUT_S)
        except S.CameraError as e:
            return self._error(504, "Camera did not reply in time", detail=e.reason)
        return self._json(200, {"success": True, "response": _mask_obj(response)})

    # ----- SSE and files -----

    def _event(self, name, obj):
        self.wfile.write(f"event: {name}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        E = self.app.state
        q = E.listen()
        try:
            self._event("state", E.snapshot())
            while True:
                try:
                    snap = q.get(timeout=15)
                    self._event("state", snap)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            E.stop_listening(q)

    def _file(self, relative):
        base = os.path.realpath(STATIC)
        target = os.path.realpath(os.path.join(base, relative))
        if not target.startswith(base + os.sep) or not os.path.isfile(target):
            return self._error(404, "not found")
        kind = mimetypes.guess_type(target)[0] or "application/octet-stream"
        with open(target, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(host="127.0.0.1", port=DEFAULT_PORT, factory=None, resources=None):
    "Builds the server. factory(ip, port, pwd, log=...) creates the session (CameraSession by default)."
    rec = load_resources() if resources is None else resources
    app = App(factory or S.CameraSession, rec)

    class H(Handler):
        pass

    H.app = app
    return Server((host, port), H)


# ----- offline tests (fake camera) -----

class FakeCamera:
    "Test double for CameraSession: records calls; login_failure makes the login refuse."

    created = []
    login_failure = None
    command_failure = False
    ignore_dev_control = False

    def __init__(self, ip, port, pwd, log=None):
        self.ip = ip or "192.168.1.100"
        self.port = port or 12804
        self.pwd = pwd
        self.calls = []
        self.parms = {"power": 100, "charging": 1, "sysver": "CYCAM_T99_v32_0226",
                      "time": 1792106270, "lamp": 1, "icut": 0}
        self.wifi = {"ssid": "fake-network", "conmode": 1, "pwd": "example-pwd"}  # the camera echoes pwd; masking must hide it
        self.audio_callback = None
        FakeCamera.created.append(self)

    def connect(self, lansearch_timeout=5.0):
        self.calls.append("connect")

    def login(self):
        if FakeCamera.login_failure:
            raise S.CameraError("login", FakeCamera.login_failure)
        return {"result": 0, "admin": 1, "type": 2020, "mode": 2020, "checkstr": "SHIX", "checkver": 3}

    def command(self, pro, cmd, fields=None, timeout=5.0):
        self.calls.append(("command", pro, cmd, fields))
        if FakeCamera.command_failure:
            raise S.CameraError(f"command {pro}/{cmd}", "no reply within 5.0s")
        if pro == "get_parms":
            return {"cmd": 101, "result": 0, **self.parms}
        if pro == "get_wifi":
            return {"cmd": 112, "result": 0, **self.wifi}
        return {"cmd": cmd, "result": 0, "wifissid": "fake-network", "pwd": "example-pwd"}

    def _send_command_no_reply(self, pro, cmd, fields):
        self.calls.append(("fire", pro, cmd, fields))
        if pro == "dev_control" and not FakeCamera.ignore_dev_control:
            for k in ("lamp", "icut"):
                if k in fields:
                    self.parms[k] = fields[k]

    def start_video(self, cb):
        self.calls.append("start_video")

    def stop_video(self):
        self.calls.append("stop_video")

    def start_audio(self, cb=None):
        self.calls.append("start_audio")
        self.audio_callback = cb

    def stop_audio(self):
        self.calls.append("stop_audio")

    def close(self):
        self.calls.append("close")


def _fake_factory(ip, port, pwd, log=None):
    return FakeCamera(ip, port, pwd, log=log)


def _tests():
    global READBACK_WAIT_S, READBACK_TRIES
    failures = []

    def ok(name, cond, extra=""):
        print(f"[{'ok' if cond else 'FAILED'}] {name} {extra}".rstrip())
        if not cond:
            failures.append(name)

    resources = load_resources()
    ids = {(r["id"], r["cmd"]) for r in resources}
    ok("resources: get_wifi allowed", ("get_wifi", 112) in ids)
    ok("resources: set_wifi allowed as a write", ("set_wifi", 114) in ids and
       [r for r in resources if r["id"] == "set_wifi"][0]["write"])
    ok("resources: no cloud (priority 3)", not any(r["id"] in ("set_cypush", "get_cloudinfo") for r in resources))
    ok("resources: priorities are only 1 and 2", all(r["priority"] in (1, 2) for r in resources))
    sd_in_list = sorted({r["id"] for r in resources} & NO_SD_SLOT)
    ok("resources: no SD card command in the list", sd_in_list == [], str(sd_in_list))

    def start(login_failure=None, command_failure=False):
        FakeCamera.created = []
        FakeCamera.login_failure = login_failure
        FakeCamera.command_failure = command_failure
        FakeCamera.ignore_dev_control = False
        httpd = create_server("127.0.0.1", 0, factory=_fake_factory, resources=resources)
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        return httpd, httpd.server_address[1]

    def req(port, method, path, body=None, headers=None, kind="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        data = None
        h = {}
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h = {"Content-Type": kind}
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        text = r.read().decode("utf-8", "replace")
        conn.close()
        return r.status, text

    PWD = "example-pwd"
    httpd, port = start()
    all_responses = []

    st, txt = req(port, "GET", "/api/estado")
    all_responses.append(txt)
    ok("initial state disconnected", st == 200 and json.loads(txt)["state"] == "disconnected", txt)

    st, txt = req(port, "POST", "/api/video", {"on": True})
    ok("video without session: 401", st == 401, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "get_wifi", "cmd": 112, "fields": {}})
    ok("command without session: 401", st == 401, str(st))
    st, txt = req(port, "POST", "/api/conectar", {})
    ok("connect without password: 400", st == 400 and "Password required" in txt, str(st))
    st, txt = req(port, "POST", "/api/conectar", b"{not json", None)
    ok("invalid JSON: 400", st == 400, str(st))
    st, txt = req(port, "POST", "/api/conectar", b'{"pwd": "example-pwd"}', kind="text/plain")
    ok("wrong content-type: 400", st == 400, str(st))
    st, txt = req(port, "GET", "/api/estado", headers={"Host": "evil.example"})
    ok("foreign host: 403", st == 403, str(st))

    st, txt = req(port, "POST", "/api/conectar", {"pwd": PWD})
    all_responses.append(txt)
    body = json.loads(txt)
    ok("connect: 200 and state connected", st == 200 and body["state"] == "connected", txt)
    ok("connect: login info without password", body.get("info", {}).get("checkstr") == "SHIX" and "pwd" not in txt)
    st, txt = req(port, "POST", "/api/conectar", {"pwd": PWD})
    ok("connect again: 409", st == 409, str(st))

    st, txt = req(port, "POST", "/api/video", {"on": "yes"})
    ok("video on non-boolean: 400", st == 400, str(st))
    st, txt = req(port, "POST", "/api/video", {"on": True})
    ok("video on: 200 video_on true", st == 200 and json.loads(txt) == {"video_on": True}, txt)
    ok("video on called start_video", "start_video" in FakeCamera.created[0].calls)
    st, txt = req(port, "POST", "/api/audio", {"on": True})
    ok("audio on: 200", st == 200 and json.loads(txt) == {"audio_on": True}, txt)
    st, txt = req(port, "GET", "/api/estado")
    ok("state shows video and audio on", json.loads(txt)["video_on"] and json.loads(txt)["audio_on"], txt)

    st, txt = req(port, "POST", "/api/comando", {"pro": "get_wifi", "cmd": 112, "fields": {}})
    all_responses.append(txt)
    ok("read command: 200", st == 200 and json.loads(txt)["success"] is True, txt)
    ok("command: password masked in the reply", '"pwd": "***"' in txt and PWD not in txt, txt)

    st, txt = req(port, "POST", "/api/comando", {"pro": "set_wifi", "cmd": 114, "fields": {"wifissid": "x"}})
    ok("write without confirmation: 403", st == 403 and "confirmation" in txt, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "set_wifi", "cmd": 114, "fields": {"wifissid": "x"},
                                                  "confirmed": False})
    ok("write with confirmed false: 403", st == 403, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "set_wifi", "cmd": 114, "fields": {"wifissid": "x"},
                                                  "confirmed": True})
    ok("confirmed write: 200", st == 200, str(st))
    ok("confirmed write reached the camera", ("command", "set_wifi", 114, {"wifissid": "x"})
       in FakeCamera.created[0].calls)

    st, txt = req(port, "POST", "/api/comando", {"pro": "set_cypush", "cmd": 1, "fields": {}, "confirmed": True})
    ok("cloud (set_cypush) blocked even when confirmed: 403", st == 403, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "get_sd", "cmd": 110, "fields": {}})
    ok("SD command (camera has no slot) blocked: 403", st == 403, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "set_sd", "cmd": 110, "fields": {"format": 1}, "confirmed": True})
    ok("SD format blocked even when confirmed: 403", st == 403, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "reboot", "cmd": 1, "fields": {}, "confirmed": True})
    ok("command outside the list blocked: 403", st == 403, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "get_wifi", "cmd": 999, "fields": {}})
    ok("right pro with wrong cmd: 403", st == 403, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "get_wifi", "cmd": 112, "fields": {"pwd": "x"}})
    ok("fields with pwd: 400", st == 400, str(st))
    st, txt = req(port, "POST", "/api/comando", {"pro": "get_wifi", "cmd": "112"})
    ok("cmd as text: 400", st == 400, str(st))

    st, txt = req(port, "GET", "/api/recursos")
    items = json.loads(txt)["resources"]
    ok("resources: include get_wifi and set_wifi", any(r["id"] == "get_wifi" for r in items)
       and any(r["id"] == "set_wifi" for r in items))
    ok("resources: no cloud", not any(r["id"] == "set_cypush" for r in items))

    st, txt = req(port, "GET", "/static/../servidor.py")
    ok("static: no directory traversal", st == 404 and "CY365App" not in txt, str(st))
    st, txt = req(port, "GET", "/rota-que-nao-existe")
    ok("unknown route: 404", st == 404, str(st))

    st, txt = req(port, "POST", "/api/video", {"on": False})
    ok("video off: 200", st == 200 and json.loads(txt) == {"video_on": False}, txt)
    st, txt = req(port, "POST", "/api/desconectar", None)
    all_responses.append(txt)
    ok("disconnect: 200 disconnected", st == 200 and json.loads(txt)["state"] == "disconnected", txt)
    ok("disconnect closed the camera", "close" in FakeCamera.created[0].calls)
    st, txt = req(port, "POST", "/api/desconectar", None)
    ok("disconnect without session: 401", st == 401, str(st))
    httpd.shutdown()

    # login refused (result != 0) -> 401 and state error
    httpd, port = start(login_failure="result=13 (cmd=100)")
    st, txt = req(port, "POST", "/api/conectar", {"pwd": PWD})
    all_responses.append(txt)
    ok("wrong password: 401 Incorrect password", st == 401 and "Incorrect password" in txt, txt)
    st, txt = req(port, "GET", "/api/estado")
    ok("wrong password: state error with reason", json.loads(txt)["state"] == "error"
       and json.loads(txt)["last_error"], txt)
    httpd.shutdown()

    # camera does not answer on the LAN -> 504
    httpd, port = start(login_failure="no reply from check_user")
    st, txt = req(port, "POST", "/api/conectar", {"pwd": PWD})
    ok("no reply from camera: 504", st == 504 and "did not respond" in txt, str(st))
    httpd.shutdown()

    # command without reply -> 504
    httpd, port = start(command_failure=True)
    req(port, "POST", "/api/conectar", {"pwd": PWD})
    st, txt = req(port, "POST", "/api/comando", {"pro": "get_wifi", "cmd": 112, "fields": {}})
    ok("command without reply: 504", st == 504, str(st))
    httpd.shutdown()

    # the password never appears in the captured replies
    ok("password appears in no reply", all(PWD not in t for t in all_responses))

    # SSE: initial event and state change
    httpd, port = start()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/api/eventos")
    r = conn.getresponse()

    def next_state():
        while True:
            line = r.fp.readline().decode()
            if line.startswith("data:"):
                return json.loads(line[5:])

    initial = next_state()
    ok("SSE: initial event", initial["state"] == "disconnected", str(initial))
    req(port, "POST", "/api/conectar", {"pwd": PWD})
    states = [next_state()["state"]]
    while states[-1] != "connected":
        states.append(next_state()["state"])
    ok("SSE: events on connect (connecting -> connected)", states == ["connecting", "connected"], str(states))
    conn.close()
    httpd.shutdown()

    # /stream: MJPEG reused from cy_viewer, only with video on
    httpd, port = start()
    st, _ = req(port, "GET", "/stream")
    ok("stream with video off: 204", st == 204, str(st))
    req(port, "POST", "/api/conectar", {"pwd": PWD})
    req(port, "POST", "/api/video", {"on": True})
    jpeg = b"\xff\xd8\xff\xe0" + b"x" * 40 + b"\xff\xd9"
    stop = threading.Event()

    def publish():
        while not stop.is_set():
            V.publish(jpeg)
            time.sleep(0.05)

    threading.Thread(target=publish, daemon=True).start()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/stream", timeout=5) as response:
        kind = response.headers.get("Content-Type")
        piece = response.read(200)
    stop.set()
    ok("stream: multipart with frame and image/jpeg",
       kind.startswith("multipart/x-mixed-replace") and b"--frame" in piece and b"image/jpeg" in piece, kind)
    httpd.shutdown()

    # ----- pacing (pure functions) -----
    steps = []
    due = None
    for _ in range(5):  # steady stream: chunks arrive on time
        send, due = pacing_step(0.0 + 0.04 * len(steps), due, 0.04)
        steps.append(send)
    ok("pacing: steady stream is sent on arrival", all(abs(a - 0.04 * i) < 1e-9 for i, a in enumerate(steps)), str(steps))
    burst = []
    due = None
    for _ in range(10):  # burst of ten chunks at the same instant
        send, due = pacing_step(1.0, due, 0.04)
        burst.append(send)
    ok("pacing: a burst is spread out at real time",
       all(abs(a - (1.0 + 0.04 * i)) < 1e-9 for i, a in enumerate(burst)), str(burst[-1] - burst[0]))
    send, due = pacing_step(10.0, 0.2, 0.04)  # 9.8 s late: resynchronise, no catch-up burst
    send2, due2 = pacing_step(10.0 + 0.0, due, 0.04)
    ok("pacing: a stall restarts the clock without a catch-up burst",
       send == 10.0 and abs(due - 10.04) < 1e-9 and abs(send2 - 10.04) < 1e-9, f"{send} {due} {send2}")
    ok("pacing: 640 bytes of PCM is 40 ms", abs(chunk_duration(640) - 0.04) < 1e-12, str(chunk_duration(640)))
    ok("pacing: lag exactly at the limit is not a stall",
       pacing_step(0.25, 0.0, 0.04, max_lag=0.25) == (0.25, 0.29))

    # ----- info, indicator, infrared, network, playable audio -----
    import random

    READBACK_WAIT_S, READBACK_TRIES = 0.01, 3   # keep the offline suite fast

    def ima_frame(n_bytes, seed):
        return random.Random(seed).randbytes(n_bytes)

    def camera_payload(frames):
        """DRW payload on channel 2: AV header (magic, codec 0x0B, LE32 size @16) + IMA data, per frame."""
        out = b""
        for data in frames:
            head = b"\x55\xaa\x15\xa8\x0b\x01\x00\x00" + b"\x00" * 8 + struct.pack("<I", len(data)) + b"\x00" * 12
            out += head + data
        return out

    # 1. routes need a session (401) and reject bad values (400)
    httpd, port = start()
    for method, path, body in [("GET", "/api/info", None), ("GET", "/api/rede", None),
                                   ("POST", "/api/indicador", {"on": True}),
                                   ("POST", "/api/infravermelho", {"mode": 1})]:
        st, _ = req(port, method, path, body)
        ok(f"{method} {path} without session: 401", st == 401, str(st))
    req(port, "POST", "/api/conectar", {"pwd": PWD})

    # 2. info: fields renamed to English keys, charging as bool
    st, txt = req(port, "GET", "/api/info")
    info = json.loads(txt)
    ok("info: 200 with English keys", st == 200 and info == {
        "battery": 100, "charging": True, "firmware": "CYCAM_T99_v32_0226",
        "time": 1792106270, "led_status": 1}, txt)
    FakeCamera.created[-1].parms["charging"] = 0
    st, txt = req(port, "GET", "/api/info")
    ok("info: charging is False when charging != 1", json.loads(txt)["charging"] is False)

    # 3. indicator: send, read back, report the value the camera confirms
    st, txt = req(port, "POST", "/api/indicador", {"on": "yes"})
    ok("indicator: non-boolean on: 400", st == 400, str(st))
    st, txt = req(port, "POST", "/api/indicador", {})
    ok("indicator: missing on: 400", st == 400, str(st))
    st, txt = req(port, "POST", "/api/indicador", {"on": False})
    body = json.loads(txt)
    ok("indicator off: 200, read off and confirmed", st == 200 and body == {"indicator": False, "confirmed": True}, txt)
    ok("indicator off: dev_control lamp=0 sent without reply",
       ("fire", "dev_control", 102, {"lamp": 0}) in FakeCamera.created[-1].calls)
    st, txt = req(port, "POST", "/api/indicador", {"on": True})
    ok("indicator on: back to on", json.loads(txt) == {"indicator": True, "confirmed": True}, txt)

    # 4. indicator: camera ignores the command -> confirmed False, value read is the real one
    FakeCamera.ignore_dev_control = True
    st, txt = req(port, "POST", "/api/indicador", {"on": False})
    ok("indicator: camera ignores command -> confirmed False",
       st == 200 and json.loads(txt) == {"indicator": True, "confirmed": False}, txt)
    FakeCamera.ignore_dev_control = False

    # 5. infrared mode: 0, 1, 2 only; booleans are not modes
    for value in (3, "1", True, None):
        st, txt = req(port, "POST", "/api/infravermelho", {"mode": value})
        ok(f"infrared: mode {value!r} rejected: 400", st == 400, str(st))
    st, txt = req(port, "POST", "/api/infravermelho", {"mode": 2})
    ok("infrared: mode 2 applied and confirmed", st == 200 and json.loads(txt) == {"mode": 2, "confirmed": True}, txt)
    ok("infrared: dev_control icut=2 sent", ("fire", "dev_control", 102, {"icut": 2}) in FakeCamera.created[-1].calls)

    # 6. network: read-only, ssid and conmode only
    st, txt = req(port, "GET", "/api/rede")
    ok("network: ssid and conmode", st == 200 and json.loads(txt) == {"ssid": "fake-network", "conmode": 1}, txt)
    st, txt = req(port, "POST", "/api/rede", {"ssid": "x"})
    ok("network: no Wi-Fi write route (POST 404)", st == 404, str(st))
    for path in ("/api/wifi", "/api/reboot", "/api/sd", "/api/upgrade"):
        st, _ = req(port, "POST", path, {})
        ok(f"POST {path} does not exist: 404", st == 404, str(st))

    # 7. audio.wav: 204 while audio is off
    st, _ = req(port, "GET", "/audio.wav")
    ok("audio.wav with audio off: 204", st == 204, str(st))
    st, _ = req(port, "GET", "/audio.wav", headers={"Host": "evil.example"})
    ok("audio.wav with foreign Host: 403", st == 403, str(st))
    httpd.shutdown()

    # 8. audio.wav with audio on: WAV header and PCM from fabricated camera frames
    httpd, port = start()
    req(port, "POST", "/api/conectar", {"pwd": PWD})
    st, _ = req(port, "POST", "/api/audio", {"on": True})
    app = httpd.RequestHandlerClass.app
    frames = [ima_frame(160, 1), ima_frame(160, 2), ima_frame(352, 3)]
    expected_pcm = b"".join(ima_pcm_bytes(f) for f in frames)
    result = {}

    def read_wav():
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/audio.wav", timeout=10) as r:
            result["type"] = r.headers.get("Content-Type")
            result["header"] = r.read(44)
            result["pcm"] = r.read(len(expected_pcm))

    reader = threading.Thread(target=read_wav, daemon=True)
    reader.start()
    for _ in range(100):
        if app.audio._listeners:
            break
        time.sleep(0.05)
    cam = FakeCamera.created[-1]
    cam.audio_callback(camera_payload(frames[:2]))
    cam.audio_callback(camera_payload(frames[2:]))
    reader.join(timeout=10)
    header = result.get("header", b"")
    ok("audio.wav: Content-Type audio/wav", result.get("type") == "audio/wav", str(result.get("type")))
    ok("audio.wav: RIFF/WAVE header, PCM 16 bit mono 8000 Hz",
       len(header) == 44 and header[:4] == b"RIFF" and header[8:12] == b"WAVE" and
       struct.unpack("<HHIIHH", header[20:36]) == (1, 1, 8000, 16000, 2, 16), header.hex())
    ok("audio.wav: PCM equals the decoded frames (3 frames: 320+320+704 = 1344 samples)",
       result.get("pcm") == expected_pcm and len(expected_pcm) == 2 * (320 + 320 + 704),
       f"{len(result.get('pcm') or b'')} bytes")
    req(port, "POST", "/api/audio", {"on": False})
    reader_end = time.time() + 3
    while app.audio._listeners and time.time() < reader_end:
        time.sleep(0.05)
    ok("audio.wav: listener removed when audio turns off", app.audio._listeners == [])
    httpd.shutdown()

    print("\nRESULT:", "all ok" if not failures else f"FAILED: {failures}")
    return not failures


def main():
    ap = argparse.ArgumentParser(description="Local server for the CY365 app.")
    ap.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1; only loopback is accepted in Host")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--testes", dest="tests", action="store_true", help="offline tests with a fake camera")
    a = ap.parse_args()
    if a.tests:
        sys.exit(0 if _tests() else 1)
    httpd = create_server(a.host, a.port)
    print(f"CY365 app at http://{a.host}:{a.port}  (Ctrl+C to quit)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
