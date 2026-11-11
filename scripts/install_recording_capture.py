"""Verify and transfer one captured session to the separate debuggable Preview app."""
import argparse
import json
from pathlib import Path
import subprocess
from farol.recording_capture import load_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--device", required=True)
    parser.add_argument("--adb", default="C:/Android/Sdk/platform-tools/adb.exe")
    args = parser.parse_args()
    data = load_capture(args.capture)
    adb = [args.adb, "-s", args.device]
    package = "com.rideedge.app.preview"
    subprocess.run([*adb, "shell", "am", "force-stop", package], check=True, capture_output=True)
    # run-as is scoped to the Preview sandbox; no shared-storage receipt or key.
    subprocess.run([*adb, "shell", "run-as", package, "mkdir", "-p", "files"], check=True, capture_output=True)
    # ADB's shell transport normalizes CRLF. Send canonical LF JSON so the
    # byte-for-byte readback is independent of the Windows text writer.
    content = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
    subprocess.run([*adb, "shell", "run-as", package, "sh", "-c",
                    "'cat > files/captured-session.json.tmp'"], input=content, check=True, capture_output=True)
    subprocess.run([*adb, "shell", "run-as", package, "mv", "files/captured-session.json.tmp",
                    "files/captured-session.json"], check=True, capture_output=True)
    actual = subprocess.check_output([*adb, "exec-out", "run-as", package, "cat", "files/captured-session.json"])
    if actual != content:
        raise RuntimeError("Phone receipt did not match; recording was not launched")
    subprocess.run([*adb, "shell", "am", "start", "-W", "-n", package + "/com.rideedge.app.MainActivity",
                    "--es", "radar_fixture_state", "recording", "--ei", "recording_step", "0"], check=True, capture_output=True)
    print(json.dumps({"installed_capture": data["capture_id"], "snapshot_id": data["stages"][0]["radar"]["snapshot_id"],
                      "verified_bytes": len(content)}))


if __name__ == "__main__":
    main()
