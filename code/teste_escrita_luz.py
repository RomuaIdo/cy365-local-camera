"First write test: white light (set_whiteLight, cmd 304), reversible. Runs only with --confirmar."
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cy_session as S  # noqa: E402


def state(sess):
    r = sess.command("get_whiteLight", 305)
    return r.get("status"), r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", required=True)
    ap.add_argument("--pwd", required=True)
    ap.add_argument("--confirmar", dest="confirm", action="store_true", help="required: confirms the write to the camera")
    a = ap.parse_args()
    if not a.confirm:
        print("Not run: --confirmar is missing (this step writes to the camera).")
        return 2

    sess = S.CameraSession(a.cam, None, a.pwd)
    sess.connect()
    sess.login()
    print("1. login ok")
    original, _ = state(sess)
    print(f"2. white light original: status={original}")
    target = 1 if original != 1 else 0
    r = sess.command("set_whiteLight", 304, {"status": target})
    print(f"3. set_whiteLight status={target} -> reply: result={r.get('result')}")
    current, _ = state(sess)
    print(f"4. white light now: status={current}")
    r = sess.command("set_whiteLight", 304, {"status": original})
    print(f"5. restoring original status={original} -> result={r.get('result')}")
    final, _ = state(sess)
    print(f"6. final white light: status={final} (original={original})")
    sess.close()
    print("RESULT:", "ok" if (current == target and final == original) else "DIVERGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
