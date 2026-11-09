"""Launch a FreeRDP session (full desktop or RemoteApp) without leaking the password.

The connection details and password travel through a private temporary .rdp file,
so they never appear in the process list. Redirect flags come from the config.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


REDIRECT = {
    "smartcard": ["/smartcard"],
    "clipboard": ["/clipboard"],
    # Sound output only. Microphone redirection needs a running PulseAudio/PipeWire
    # session and fails fatally (POST_CONNECT_FAILED) in the thin kiosk.
    "audio": ["/sound"],
    "drives": [],  # filled below with the local home path
    "usb": ["/usb:auto"],
}


def remote_app_flag(app):
    # FreeRDP 3 wants /app:program:<path> or /app:program:||<alias>.
    if app.startswith("||") or "\\" in app or "/" in app or (len(app) >= 2 and app[1] == ":"):
        value = app
    else:
        value = "||" + app
    return "/app:program:" + value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Launch an RDP session for Nix2office.")
    parser.add_argument("--config", required=True, help="RDP config JSON produced at build time.")
    parser.add_argument("--password-file", help="Optional decrypted password file (sops).")
    parser.add_argument("--profile", required=True, help="Profile name from the config.")
    parser.add_argument("--app", help="Optional RemoteApp alias.")
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    profile = next((p for p in config.get("profiles", []) if p.get("name") == args.profile), None)
    if profile is None:
        sys.exit(f"Unknown RDP profile: {args.profile}")

    host = profile.get("host", "")
    user = profile.get("user", "")
    port = profile.get("port", 3389)
    home = config.get("home", "")

    # Build the command: credentials in the file, everything else as flags.
    lines = [
        f"full address:s:{host}:{port}",
        f"username:s:{user}",
    ]
    password = None
    if args.password_file and Path(args.password_file).is_file():
        password = Path(args.password_file).read_text().strip("\n\r")
    if password:
        lines.append(f"password:s:{password}")
    else:
        lines.append("prompt for credentials:i:1")

    fd, rdp_file = tempfile.mkstemp(suffix=".rdp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
        command = ["xfreerdp", rdp_file, "/cert:tofu"]
        for key in config.get("redirect", []):
            if key == "drives":
                if home:
                    command.append(f"/drive:home,{home}")
                continue
            command.extend(REDIRECT.get(key, []))
        if args.app:
            command.append(remote_app_flag(args.app))
        subprocess.run(command, check=False)
    finally:
        try:
            os.unlink(rdp_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()

