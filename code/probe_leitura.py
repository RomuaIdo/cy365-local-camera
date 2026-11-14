"READ-ONLY probe of the camera capabilities. Only get_* commands; output in captures/probe/."
import argparse
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cy_session as S  # noqa: E402

PAUSE_S = 1.0
CMD_TIMEOUT_S = 5.0
DEFAULT_OUT_DIR = os.path.join(HERE, "..", "captures", "probe")

# (pro, cmd, fields) — fields may depend on the current date
def _calendar_fields(now):
    return {"year": now.year, "month": now.month}


def _list_fields(now):
    return {"year": now.year, "month": now.month, "day": now.day, "hour": 0}


READ_COMMANDS = [
    ("get_product", 200, None),
    ("get_wifi", 112, None),
    ("get_parms", 101, None),
    ("get_whiteLight", 305, None),
    ("get_vol", 134, None),
    ("get_alarm", 107, None),
    ("get_sd", 110, None),
    ("get_record_param", 199, None),
    ("get_record_day", 205, _calendar_fields),
    ("get_record_list", 206, _list_fields),
]

# Excluded on purpose (reason in parentheses): see the reverse-engineering notes
EXCLUDED = {
    "scan_wifi": "changes the Wi-Fi radio during the scan",
    "get_user": "returns the camera's user accounts and passwords",
    "get_videofiles": "requires the filename of a recorded file",
    "get_temp": "3D printer (priority 3)",
    "get_cloudsupport": "cloud (priority 3)",
    "get_cloudinfo": "cloud (priority 3)",
    "check_ota": "cloud/OTA (priority 3)",
}

# Names that must never appear in the probe
FORBIDDEN = re.compile(
    r"^(set_|add_|edit_|del_|start_|stop_|play_|end_|pr_|down_file|upload_|talk|ptz|dev_control|reboot|format|restore)"
    r"|_control$|cloud|cypush|ota$",
    re.IGNORECASE,
)
EXPECTED_LOGIN = "check_user"


def validate_command(pro, cmd):
    "Raises ValueError if the command is not an allowed read command for this probe."
    if pro == EXPECTED_LOGIN:
        return
    if not pro.startswith("get_"):
        raise ValueError(f"the probe only sends get_*: {pro}")
    if FORBIDDEN.search(pro):
        raise ValueError(f"forbidden name in the probe: {pro}")
    if pro in EXCLUDED:
        raise ValueError(f"excluded from the probe ({EXCLUDED[pro]}): {pro}")
    if not any(p == pro and c == cmd for p, c, _ in READ_COMMANDS):
        raise ValueError(f"command not in the read list: {pro}/{cmd}")


def build_body(pro, cmd, fields, user="admin", pwd="***"):
    "JSON body as cy_session sends it (no DRW header). Used by the plan and the tests."
    body = {"pro": pro, "cmd": cmd, **(fields or {}), "user": user, "pwd": pwd}
    return json.dumps(body, separators=(",", ":"))


def choose(only_text):
    "'get_vol,get_alarm' -> set of names from READ_COMMANDS. Unknown name: ValueError."
    if not only_text:
        return None
    requests = {n.strip() for n in only_text.split(",") if n.strip()}
    known = {pro for pro, _, _ in READ_COMMANDS}
    outside = sorted(requests - known)
    if outside:
        raise ValueError(f"not in the read list: {', '.join(outside)}; allowed: {', '.join(sorted(known))}")
    return requests


def plan(now=None, only=None):
    "List of (pro, cmd, fields) to send, in order, with the fields already computed."
    now = now or dt.datetime.now()
    output = [(EXPECTED_LOGIN, 100, {"devmac": "0000"})]
    for pro, cmd, fn in READ_COMMANDS:
        if only is not None and pro not in only:
            continue
        output.append((pro, cmd, fn(now) if fn else None))
    return output


def mask_obj(obj):
    "Replaces values of sensitive keys (pwd, senha, token, pass) with *** at any depth."
    if isinstance(obj, dict):
        return {k: ("***" if re.search(r"pwd|pass|token|senha", k, re.I) else mask_obj(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_obj(v) for v in obj]
    return obj


def probe(session, pause=PAUSE_S, log=print, now=None, timeout=CMD_TIMEOUT_S, only=None):
    "Runs the probe over an already connected session. Returns the dict written to the JSON."
    results = []
    login = None
    try:
        login = session.login()
    except S.CameraError as e:
        raise SystemExit(f"login failed; probe stopped: {e}")
    log(f"login ok: result={login.get('result')}")

    for i, (pro, cmd, fields) in enumerate(plan(now, only)[1:]):
        validate_command(pro, cmd)
        time.sleep(pause)
        t0 = time.time()
        record = {"pro": pro, "cmd": cmd, "campos": fields, "enviado_em": dt.datetime.now().isoformat(timespec="seconds")}
        try:
            response = session.command(pro, cmd, fields, timeout=timeout)
            record.update({"status": "ok", "resposta": mask_obj(response), "erro": None})  # output keys stay in Portuguese
        except S.CameraError as e:
            record.update({"status": "sem resposta", "resposta": None, "erro": e.reason})
        record["tempo_s"] = round(time.time() - t0, 2)
        results.append(record)
        log(f"[{i + 1}] {pro}/{cmd}: {record['status']} ({record['tempo_s']} s)")
    return {"login": {k: login.get(k) for k in S.LOGIN_FIELDS}, "comandos": results}


def save_capture(data, folder, ip, port):
    os.makedirs(folder, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(folder, f"capacidades_{ts}.json")
    doc = {"gerado_em": dt.datetime.now().isoformat(timespec="seconds"), "ip": ip, "porta": port, **data}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return path


def _tests():
    import tempfile

    failures = []

    def ok(name, cond, extra=""):
        print(f"[{'ok' if cond else 'FAILED'}] {name} {extra}".rstrip())
        if not cond:
            failures.append(name)

    now = dt.datetime(2026, 10, 15, 12, 0)
    ps = plan(now)
    names = [p for p, _, _ in ps]

    # 1. every planned command passes validation and none is forbidden
    ok("plan: all validated", all(validate_command(p, c) is None for p, c, _ in ps))
    ok("plan: no forbidden name", not any(FORBIDDEN.search(p) for p in names if p != "check_user"), str(names))
    ok("plan: each command once", len(names) == len(set(names)))
    ok("plan: check_user first", names[0] == "check_user")

    # 2. dangerous commands are refused by validation
    for pro, cmd in [("set_wifi", 114), ("dev_control", 102), ("ptz_control", 128), ("set_cypush", 1),
                     ("get_cloudinfo", 9002), ("get_user", 103), ("scan_wifi", 113), ("reboot", 1), ("get_xyz", 999)]:
        try:
            validate_command(pro, cmd)
            ok(f"refuses {pro}/{cmd}", False)
        except ValueError:
            ok(f"refuses {pro}/{cmd}", True)

    # 3. built JSON: date fields, masked pwd, separators as in the app
    body = build_body("get_record_day", 205, _calendar_fields(now))
    ok("JSON get_record_day", body == '{"pro":"get_record_day","cmd":205,"year":2026,"month":10,"user":"admin","pwd":"***"}', body)
    ok("JSON is valid", isinstance(json.loads(body), dict))

    # 4. reply masking
    ok("mask_obj hides pwd and cyToken",
       mask_obj({"pwd": "example-pwd", "cyToken": "abc", "wifissid": "fake-network", "cmd": 112})
       == {"pwd": "***", "cyToken": "***", "wifissid": "fake-network", "cmd": 112})

    # 5. probe with a fake session: order, pause, no-reply, generated file
    class FakeSession:
        def __init__(self):
            self.sent = []
            self.timeouts = []

        def login(self):
            return {"result": 0, "admin": 1, "type": 2020, "mode": 2020, "checkstr": "SHIX"}

        def command(self, pro, cmd, fields=None, timeout=5.0):
            self.sent.append((pro, cmd))
            self.timeouts.append(timeout)
            if pro == "get_wifi":
                raise S.CameraError(f"command {pro}/{cmd}", "no reply within 5.0s")
            return {"cmd": cmd, "result": 0, "pwd": "example-pwd", "wifissid": "fake-network"}

    sf = FakeSession()
    logs = []
    data = probe(sf, pause=0.0, log=logs.append, now=now)
    ok("probe: sends the list in order", [p for p, _ in sf.sent] == [p for p, _, _ in ps[1:]])
    ok("probe: no command outside the list", all(not FORBIDDEN.search(p) for p, _ in sf.sent))
    wifi = [c for c in data["comandos"] if c["pro"] == "get_wifi"][0]
    ok("probe: no-reply recorded", wifi["status"] == "sem resposta" and wifi["resposta"] is None)
    prod = [c for c in data["comandos"] if c["pro"] == "get_product"][0]
    ok("probe: reply with masked password", prod["resposta"]["pwd"] == "***")
    ok("probe: password does not appear in the result", "example-pwd" not in json.dumps(data))
    # 6. --so e --timeout
    ok("choose: empty becomes None", choose(None) is None)
    ok("choose: comma-separated list", choose("get_product, get_vol") == {"get_product", "get_vol"})
    try:
        choose("get_vol,set_wifi")
        ok("choose: name outside the list is refused", False)
    except ValueError as e:
        ok("choose: name outside the list is refused", "set_wifi" in str(e))
    only = choose("get_product,get_vol")
    ps_so = plan(now, only)
    ok("plan --so: only the chosen ones (+ login)", [p for p, _, _ in ps_so] == ["check_user", "get_product", "get_vol"],
       str([p for p, _, _ in ps_so]))
    sf2 = FakeSession()
    data2 = probe(sf2, pause=0.0, log=logs.append, now=now, timeout=7.5, only=only)
    ok("probe --so: sends only the chosen ones", [p for p, _ in sf2.sent] == ["get_product", "get_vol"],
       str(sf2.sent))
    ok("probe --timeout: passed to each command", sf2.timeouts == [7.5, 7.5], str(sf2.timeouts))
    ok("probe --so: write commands stay blocked", not any(c in sf2.sent for c in [("set_wifi", 114)]))
    try:
        validate_command("set_wifi", 114)
        ok("safety guard kept (set_wifi refused)", False)
    except ValueError:
        ok("safety guard kept (set_wifi refused)", True)

    with tempfile.TemporaryDirectory() as folder:
        path = save_capture(data, folder, "192.168.1.100", 12804)
        doc = json.load(open(path, encoding="utf-8"))
        ok("capacidades_<ts>.json file generated", os.path.basename(path).startswith("capacidades_")
           and doc["comandos"] and "example-pwd" not in open(path, encoding="utf-8").read())

    print("\nRESULT:", "all ok" if not failures else f"FAILED: {failures}")
    return not failures


def main():
    ap = argparse.ArgumentParser(description="Read-only probe of the CY365 camera.")
    ap.add_argument("--plano", dest="plan", action="store_true", help="shows the commands and JSON that would be sent; does not connect")
    ap.add_argument("--testes", dest="tests", action="store_true", help="offline tests")
    ap.add_argument("--cam", default=None, help="camera IP (optional; LanSearch discovers it)")
    ap.add_argument("--port", type=int, default=None, help="UDP port (optional)")
    ap.add_argument("--pwd", default=None, help="camera password (not saved)")
    ap.add_argument("--pausa", dest="pause", type=float, default=PAUSE_S)
    ap.add_argument("--timeout", type=float, default=CMD_TIMEOUT_S,
                    help="seconds to wait for each command's reply (default 5)")
    ap.add_argument("--so", dest="only", default=None, metavar="COMANDOS",
                    help="repeat only these read commands, comma-separated (e.g.: get_product,get_vol)")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR)
    a = ap.parse_args()
    try:
        only = choose(a.only)
    except ValueError as e:
        sys.exit(f"--so: {e}")
    if a.timeout <= 0:
        sys.exit("--timeout must be greater than zero")

    if a.tests:
        sys.exit(0 if _tests() else 1)
    if a.plan:
        for pro, cmd, fields in plan(only=only):
            validate_command(pro, cmd)
            print(f"{cmd:>5}  {build_body(pro, cmd, fields)}")
        return
    if not a.pwd:
        sys.exit("missing --pwd")

    session = S.CameraSession(a.cam, a.port, a.pwd)
    session.connect()
    try:
        data = probe(session, pause=a.pause, timeout=a.timeout, only=only)
    finally:
        session.close()
    path = save_capture(data, a.out, session.ip, session.port)
    print(f"saved: {path}")


if __name__ == "__main__":
    main()
