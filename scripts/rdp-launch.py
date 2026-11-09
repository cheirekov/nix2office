"""Launch a FreeRDP session (full desktop or RemoteApp) without leaking the password.

The connection details and password travel through a private temporary .rdp file,
so they never appear in the process list. Redirect flags come from the config.

In kiosk mode (--wait-* / --attempts) it first waits for the sops secret and for
TCP reachability of the Windows host, then retries a failed connection with
backoff. Without those flags it keeps the one-shot behavior used by launchers.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


REDIRECT = {
    "smartcard": ["/smartcard"],
    "clipboard": ["/clipboard"],
    # Sound output only. Microphone redirection needs a running PulseAudio/PipeWire
    # session and fails fatally (POST_CONNECT_FAILED) in the thin kiosk.
    "audio": ["/sound"],
    "drives": [],  # filled below with the local home path
    "usb": ["/usb:auto"],
}

# FreeRDP X11 exit codes that mean the connection could not be established.
# Retrying these is useful at boot (network/server not ready). Session-end
# codes (success=0, disconnect=1, logoff=2) and permanent auth errors must stop.
RETRY_EXIT_CODES = frozenset({131, 133, 136, 137, 138, 139, 140, 141, 142, 143, 147, 150, 160})


def remote_app_flag(app):
    # FreeRDP 3 wants /app:program:<path> or /app:program:||<alias>.
    if app.startswith("||") or "\\" in app or "/" in app or (len(app) >= 2 and app[1] == ":"):
        value = app
    else:
        value = "||" + app
    return "/app:program:" + value


def wait_for_file(path, timeout):
    """Return True once path exists (or immediately when disabled), else False."""
    if not path or timeout <= 0:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if Path(path).is_file():
            return True
        time.sleep(1.0)
    return Path(path).is_file()


def wait_for_tcp(host, port, timeout):
    """Return True once host:port accepts a TCP connection (or when disabled)."""
    if timeout <= 0:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except OSError:
            time.sleep(2.0)
    return False


def _run_once(config, profile, password_file, app):
    host = profile.get("host", "")
    user = profile.get("user", "")
    port = profile.get("port", 3389)
    home = config.get("home", "")

    lines = [
        f"full address:s:{host}:{port}",
        f"username:s:{user}",
    ]
    password = None
    if password_file and Path(password_file).is_file():
        password = Path(password_file).read_text().strip("\n\r")
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
        if app:
            command.append(remote_app_flag(app))
            if config.get("unicode_keyboard"):
                command.append("/kbd:unicode:on")
        if config.get("fullscreen"):
            command.append("/f")
        result = subprocess.run(command, check=False)
        return result.returncode
    finally:
        try:
            os.unlink(rdp_file)
        except OSError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Launch an RDP session for Nix2office.")
    parser.add_argument("--config", required=True, help="RDP config JSON produced at build time.")
    parser.add_argument("--password-file", help="Optional decrypted password file (sops).")
    parser.add_argument("--profile", required=True, help="Profile name from the config.")
    parser.add_argument("--app", help="Optional RemoteApp alias.")
    parser.add_argument("--wait-secret-timeout", type=int, default=0,
                        help="Kiosk: seconds to wait for the sops password file.")
    parser.add_argument("--wait-network-timeout", type=int, default=0,
                        help="Kiosk: seconds to wait for TCP reachability of the host.")
    parser.add_argument("--attempts", type=int, default=1,
                        help="Kiosk: number of connection attempts.")
    parser.add_argument("--backoff", type=int, default=5,
                        help="Kiosk: seconds to sleep between attempts.")
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    profile = next((p for p in config.get("profiles", []) if p.get("name") == args.profile), None)
    if profile is None:
        sys.exit(f"Unknown RDP profile: {args.profile}")

    credentials = config.get("credentials", "interactive")
    if args.wait_secret_timeout > 0 and credentials == "sops" and args.password_file:
        if not wait_for_file(args.password_file, args.wait_secret_timeout):
            print(f"RDP паролата не е налична ({args.password_file}); спирам.", file=sys.stderr)
            return 2

    host = profile.get("host", "")
    port = profile.get("port", 3389)
    if args.wait_network_timeout > 0:
        if not wait_for_tcp(host, port, args.wait_network_timeout):
            print(f"RDP хост {host}:{port} не отговаря; спирам.", file=sys.stderr)
            return 3

    attempts = max(1, args.attempts)
    last = 1
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            print(f"Повтарям RDP ({attempt}/{attempts}) ...", file=sys.stderr)
        last = _run_once(config, profile, args.password_file, args.app)
        if last == 0 or last not in RETRY_EXIT_CODES:
            # Clean session end (logout/disconnect) or a permanent error: stay
            # at the openbox menu instead of relaunching a new session.
            return last
        if attempt < attempts:
            time.sleep(max(0, args.backoff))
    if attempts > 1:
        print("RDP не успя след няколко опита; отвори менюто с десен бутон на работния плот.", file=sys.stderr)
    return last


if __name__ == "__main__":
    raise SystemExit(main())
