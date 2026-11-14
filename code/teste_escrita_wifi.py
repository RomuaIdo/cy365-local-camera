"Wi-Fi write test: same network and password (set_wifi, cmd 114). Runs only with --confirmar."
import argparse
import getpass
import os
import sys
import time
from urllib.parse import quote_plus

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cy_session as S  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", required=True)
    ap.add_argument("--pwd", required=True, help="camera password")
    ap.add_argument("--espera", dest="wait", type=float, default=60.0, help="seconds before searching for the camera again")
    ap.add_argument("--enc", type=int, required=True,
                    help="encryption of your network: 2 = WPA-PSK, 3 = WPA2-PSK (check on the router/phone). "
                         "The camera scan is NOT reliable: it marks every network as 0.")
    ap.add_argument("--confirmar", dest="confirm", action="store_true")
    a = ap.parse_args()
    if not a.confirm:
        print("Not run: --confirmar is missing (this step writes to the camera).")
        return 2

    sess = S.CameraSession(a.cam, None, a.pwd)
    sess.connect()
    sess.login()
    print("1. login ok")
    current = sess.command("get_wifi", 112)
    ssid = current.get("ssid")
    print(f"2. current network: ssid={ssid} conmode={current.get('conmode')}")
    scan = sess.command("scan_wifi", 113, timeout=15.0)
    networks = [r for r in scan.get("data", []) if r.get("ssid") == ssid]
    if not networks:
        print("3. the current network did NOT appear in the scan. Aborted, nothing was changed.")
        sess.close()
        return 1
    enc = a.enc
    print(f"3. scan: network found (signal={networks[0].get('signal')}); using encryption={enc} as you specified")
    password = getpass.getpass("Wi-Fi password (will not be shown): ")
    if not password:
        print("Empty password: aborted.")
        sess.close()
        return 1
    body = {
        "wifissid": ssid,
        "wifipwd": password,
        "encwifissid": quote_plus(ssid),
        "encwifipwd": quote_plus(password),
        "encryption": enc,
    }
    del password
    try:
        r = sess.command("set_wifi", 114, body, timeout=8.0)
        print(f"4. set_wifi sent: result={r.get('result')}")
    except S.CameraError as e:
        print(f"4. set_wifi sent; no reply ({e}). This may be normal: the camera switches networks.")
    try:
        sess.close()
    except Exception:
        pass
    print(f"5. waiting {a.wait:.0f} s for the camera to reconnect...")
    time.sleep(a.wait)

    sess2 = S.CameraSession(a.cam, None, a.pwd)
    try:
        sess2.connect(lansearch_timeout=30.0)
        sess2.login()
        after = sess2.command("get_wifi", 112)
        print(f"6. camera is back: ssid={after.get('ssid')} conmode={after.get('conmode')}")
        ok = after.get("ssid") == ssid
        print("RESULT:", "ok (same network restored)" if ok else "DIVERGED")
        sess2.close()
        return 0 if ok else 1
    except S.CameraError as e:
        print(f"6. camera did NOT come back: {e}")
        print("RESULT: failed. Next step: physical reset button and reconfiguration through the app.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
