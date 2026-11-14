"Test of the blue indicator LED: dev_control cmd 102 with field lamp. Runs only with --confirmar; never prints the password."
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cy_session as S  # noqa: E402


def lamp(sess):
    r = sess.command("get_parms", 101)
    return r.get("lamp")


def send_value(sess, value):
    # dev_control has no guaranteed reply: send without waiting.
    sess._send_command_no_reply("dev_control", 102, {"lamp": value})


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
    print("1. login ok")
    original = lamp(sess)
    print(f"2. lamp original: {original}")
    target = 0 if original != 0 else 1
    send_value(sess, target)
    print(f"3. sent dev_control lamp={target}")
    import time; time.sleep(1.5)
    current = lamp(sess)
    print(f"4. lamp now (get_parms): {current}")
    send_value(sess, original)
    print(f"5. restoring lamp={original}")
    time.sleep(1.5)
    final = lamp(sess)
    print(f"6. final lamp (get_parms): {final} (original={original})")
    sess.close()
    print("RESULT:", "ok" if (current == target and final == original) else "DIVERGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
