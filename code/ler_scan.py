"Read-only: shows the raw reply of scan_wifi (cmd 113). Writes nothing."
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cy_session as S  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", required=True)
    ap.add_argument("--pwd", required=True)
    a = ap.parse_args()
    sess = S.CameraSession(a.cam, None, a.pwd)
    sess.connect()
    sess.login()
    try:
        r = sess.command("scan_wifi", 113, timeout=20.0)
        print("reply keys:", sorted(r.keys()))
        print("reply (no passwords here):", r)
    except S.CameraError as e:
        print("no reply to scan_wifi:", e)
    finally:
        sess.close()


if __name__ == "__main__":
    sys.exit(main())
