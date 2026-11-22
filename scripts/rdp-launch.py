"""Launch a FreeRDP session (full desktop or RemoteApp) without leaking the password.

The connection details and password travel through a private temporary .rdp file,
so they never appear in the process list. Redirect flags come from the config.

In kiosk mode (--wait-* / --attempts) it first waits for the sops secret and for
TCP reachability of the Windows host, then retries a failed connection with
backoff. Without those flags it keeps the one-shot behavior used by launchers.
"""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
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
    "drives": [],  # filled below with the local shared folder
    "usb": ["/usb:auto"],
}

# FreeRDP X11 exit codes that mean the connection could not be established.
# Retrying these is useful at boot (network/server not ready).
RETRY_EXIT_CODES = frozenset({131, 133, 136, 137, 138, 139, 140, 141, 142, 143, 147, 150, 160})
# FreeRDP X11 preserves the RDP disconnect reason for these ordinary exits.
# Windows may report RPC disconnect/logoff (1/2) or user disconnect/logoff (11/12).
NORMAL_SESSION_EXITS = frozenset({0, 1, 2, 11, 12})


def is_program_path(app):
    """True for a full executable path, False for a bare published RemoteApp alias."""
    return (
        app.startswith("||")
        or "\\" in app
        or "/" in app
        or (len(app) >= 2 and app[1] == ":")
    )


def remote_app_flag(app):
    # FreeRDP 3 wants /app:program:<path> or /app:program:||<alias>.
    value = app if is_program_path(app) else "||" + app
    return "/app:program:" + value


def alternate_shell_flags(app):
    # /shell needs the real executable path on the server. A bare published
    # alias has no path to hand over, so it has no alternate-shell form.
    if is_program_path(app) and not app.startswith("||"):
        return ["/shell:" + app]
    return []


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


def ask_other_account(dialog, profile, default_user=""):
    title = f'--title=Вход в Windows — {profile["name"]}'
    user = subprocess.run(
        [dialog, "--entry", title, "--text=Въведи потребителско име за Windows.", f"--entry-text={default_user}"],
        capture_output=True, text=True, check=False,
    )
    if user.returncode:
        return None
    name = user.stdout.removesuffix("\n").strip()
    if not name or any(c in name for c in "\r\n\x00"):
        return None
    password = subprocess.run(
        [dialog, "--password", title],
        capture_output=True, text=True, check=False,
    )
    if password.returncode:
        return None
    secret = password.stdout.removesuffix("\n")
    if not secret or any(c in secret for c in "\r\n\x00"):
        return None
    return name, secret


def _run_once(config, profile, password_file, app=None, shell=None, *, account=None):
    host = profile.get("host", "")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    user = profile.get("user", "") if account is None else ""
    port = profile.get("port", 3389)
    shared = config.get("shared", "")

    lines = [
        f"full address:s:{host}:{port}",
        f"username:s:{user}",
    ]
    password = None
    if account is None and password_file and Path(password_file).is_file():
        password = Path(password_file).read_text().strip("\n\r")
    if password:
        lines.append(f"password:s:{password}")
    elif account is None:
        lines.append("prompt for credentials:i:1")

    fd, rdp_file = tempfile.mkstemp(suffix=".rdp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
        command = ["xfreerdp", rdp_file, "/cert:tofu"]
        if config.get("personal_session"):
            command.append("-clipboard")
        usb_storage = config.get("usb_storage", False)
        if usb_storage:
            command.append("/drive:hotplug,*")
            if config.get("usb_action") and not app:
                command.append(f'/action-script:{config["usb_action"]}')
        for key in config.get("redirect", []):
            if (usb_storage and key == "usb") or (config.get("kiosk_shared") and key == "drives"):
                continue
            if key == "drives":
                if shared:
                    os.makedirs(shared, exist_ok=True)
                    command.append(f"/drive:Shared,{shared}")
                continue
            command.extend(REDIRECT.get(key, []))
        if config.get("kiosk_shared"):
            folder = Path(shared)
            if not folder.is_symlink():
                folder.mkdir(mode=0o700, exist_ok=True)
                command.append(f"/drive:Shared,{folder}")
            else:
                print("Shared е символна връзка и няма да се споделя.", file=sys.stderr)
        if shell:
            command.extend(alternate_shell_flags(shell))
        elif app:
            command.append(remote_app_flag(app))
            # Let the X11 client send characters from the local keyboard layout.
            if config.get("unicode_keyboard"):
                command.append("/kbd:unicode:on")
        if not app:
            # Full desktop (and alternate shell): tuned codec/GDI path.
            gfx = config.get("gfx", "auto")
            if gfx in ("rfx", "software"):
                command.append("/gfx:RFX")
            if gfx == "software":
                command.append("/gdi:sw")
        if config.get("fullscreen"):
            command.append("/f")
        if account is None:
            result = subprocess.run(command, check=False)
        else:
            name, secret = account
            # FreeRDP accepts one option per line through stdin.
            options = [*command[1:], f"/u:{name}", f"/p:{secret}"]
            result = subprocess.run(
                ["xfreerdp", "/args-from:stdin"],
                input="\n".join(options) + "\n", encoding="utf-8", check=False,
            )
        return result.returncode
    finally:
        try:
            os.unlink(rdp_file)
        except OSError:
            pass


def run_manual_account(dialog, config, profile, default_user=""):
    account = ask_other_account(dialog, profile, default_user)
    if account is None:
        return 0
    status = _run_once(config, profile, None, account=account)
    if status in NORMAL_SESSION_EXITS:
        return 0
    subprocess.run([
        dialog, "--error", "--title=Вход в Windows", "--no-markup",
        "--text=Връзката не успя. Провери адреса, акаунта и паролата.",
    ], check=False)
    return status


def personal_profile(name, host, port, user):
    if not all(isinstance(v, str) and not any(ord(c) < 32 or ord(c) == 127 for c in v)
               for v in (name, host, port, user)):
        raise ValueError("Полетата трябва да съдържат обикновен текст.")
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        if "%" in host:
            raise ValueError
        ipaddress.ip_address(host)
    except ValueError:
        if not host or len(host) > 253 or not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in host.removesuffix(".").split(".")
        ):
            raise ValueError("Въведи IP адрес или DNS име. Портът е в отделно поле.") from None
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise ValueError("Портът трябва да е число от 1 до 65535.")
    name, user = name.strip(), user.strip()
    if not 1 <= len(name) <= 80 or len(user) > 256:
        raise ValueError("Името на връзката трябва да е от 1 до 80 знака, а потребителят до 256.")
    return {"name": name, "host": host, "port": int(port), "user": user}


def personal_menu(dialog, config):
    title = "--title=Лични RDP връзки"

    def prompt(*args):
        result = subprocess.run([dialog, title, *args], capture_output=True, text=True, check=False)
        return result.stdout.removesuffix("\n") if result.returncode == 0 else None

    def edit(previous):
        fields = (
            ("name", "Име на връзката", ""),
            ("host", "Windows адрес (IP или DNS име)", ""),
            ("port", "RDP порт", "3389"),
            ("user", "Windows потребител (по желание)", ""),
        )
        values = []
        for key, label, default in fields:
            value = prompt("--entry", f"--text={label}", f'--entry-text={previous.get(key, default)}')
            if value is None:
                return None
            values.append(value)
        return personal_profile(*values)

    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    directory = state_home / "nix2office"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "rdp-connections.json"
    with (directory / "rdp-connections.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            prompt("--info", "--text=Менюто за лични връзки вече е отворено.")
            return 0
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, list):
                raise ValueError
            if any(not isinstance(p, dict) or set(p) != {"name", "host", "port", "user"} for p in saved):
                raise ValueError
            profiles = [personal_profile(p["name"], p["host"], str(p["port"]), p["user"]) for p in saved]
        except FileNotFoundError:
            profiles = []
        except (OSError, ValueError, KeyError, TypeError):
            prompt("--error", "--text=Запазените лични връзки не могат да се прочетат.")
            return 1

        while True:
            rows = ["add", "Добави връзка", ""]
            for index, profile in enumerate(profiles):
                rows.extend([str(index), profile["name"], f'{profile["host"]} · {profile["port"]}'])
            chosen = prompt("--list", "--width=560", "--height=360", "--ok-label=Избери",
                            "--cancel-label=Затвори", "--column=ID", "--hide-column=1",
                            "--print-column=1", "--column=Връзка", "--column=Адрес и порт", "--", *rows)
            if not chosen:
                return 0
            try:
                if chosen == "add":
                    profile = edit({})
                    if profile is None:
                        continue
                    profiles.append(profile)
                else:
                    index = int(chosen)
                    if not 0 <= index < len(profiles):
                        raise ValueError("Избери връзка от списъка.")
                    profile = profiles[index]
                    action = prompt("--list", "--width=390", "--height=275", "--ok-label=Избери",
                                    "--column=ID", "--hide-column=1", "--print-column=1",
                                    "--column=Действие", "connect", "Свържи", "edit", "Редактирай",
                                    "remove", "Премахни")
                    if action == "connect":
                        # Personal destinations do not receive the kiosk's local resources.
                        session = {"fullscreen": config.get("fullscreen", False), "personal_session": True}
                        run_manual_account(dialog, session, profile, profile["user"])
                        continue
                    if action == "edit":
                        changed = edit(profile)
                        if changed is None:
                            continue
                        profiles[index] = changed
                    elif action == "remove":
                        if prompt("--question", "--text=Премахване на избраната лична връзка?",
                                  "--ok-label=Премахни", "--cancel-label=Отказ") is None:
                            continue
                        del profiles[index]
                    else:
                        continue
                fd, temporary = tempfile.mkstemp(dir=directory)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        json.dump(profiles, stream, ensure_ascii=False, indent=2)
                    os.replace(temporary, path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            except (ValueError, OSError) as error:
                prompt("--error", "--no-markup", f"--text={error}")
                if isinstance(error, OSError):
                    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Launch an RDP session for Nix2office.")
    parser.add_argument("--config", required=True, help="RDP config JSON produced at build time.")
    parser.add_argument("--password-file", help="Optional decrypted password file (sops).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--profile", help="Profile name from the config.")
    mode.add_argument("--personal", action="store_true", help="Manage and open personal RDP connections.")
    parser.add_argument("--app", help="Optional RemoteApp alias.")
    parser.add_argument("--shell", help="Optional program path to run as the alternate shell (full session).")
    parser.add_argument("--other-account", action="store_true", help="Prompt for Windows credentials for this connection.")
    parser.add_argument("--wait-secret-timeout", type=int, default=0,
                        help="Kiosk: seconds to wait for the sops password file.")
    parser.add_argument("--wait-network-timeout", type=int, default=0,
                        help="Kiosk: seconds to wait for TCP reachability of the host.")
    parser.add_argument("--attempts", type=int, default=1,
                        help="Kiosk: number of connection attempts.")
    parser.add_argument("--backoff", type=int, default=5,
                        help="Kiosk: seconds to sleep between attempts.")
    args = parser.parse_args(argv)
    if args.app and args.shell:
        parser.error("--app and --shell are mutually exclusive.")

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.personal:
        if args.other_account or args.app or args.shell:
            parser.error("--personal opens full RDP sessions from its own menu.")
        dialog = config.get("personal_dialog")
        if not dialog:
            parser.error("Personal RDP connections are disabled.")
        return personal_menu(dialog, config)
    profile = next((p for p in config.get("profiles", []) if p.get("name") == args.profile), None)
    if profile is None:
        sys.exit(f"Unknown RDP profile: {args.profile}")

    if args.other_account:
        dialog = config.get("account_dialog")
        if not dialog:
            parser.error("Manual Windows account entry is disabled.")
        if args.app or args.shell:
            parser.error("--other-account requires a full RDP session.")
        return run_manual_account(dialog, config, profile)

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
        last = _run_once(config, profile, args.password_file, args.app, args.shell)
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
