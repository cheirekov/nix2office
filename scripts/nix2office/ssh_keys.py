"""List public agent identities only; never sign, unlock or read private keys."""
import base64
import hashlib
import os
from pathlib import Path
import subprocess

from .config import ConfigError, validate_public_key


def fingerprint(key):
    validate_public_key(key)
    if not key:
        raise ConfigError("Empty public key.")
    return "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(key.split()[1])).digest()).decode().rstrip("=")


def agent_keys():
    uid = os.getuid()
    sockets = list(dict.fromkeys(filter(None, [os.environ.get("SSH_AUTH_SOCK"),
        f"/run/user/{uid}/gnupg/S.gpg-agent.ssh", f"/run/user/{uid}/keyring/ssh", f"/run/user/{uid}/gcr/ssh"])))
    found = {}
    for socket in sockets:
        if not Path(socket).exists():
            continue
        try:
            result = subprocess.run(["ssh-add", "-L"], env=dict(os.environ, SSH_AUTH_SOCK=socket),
                                    capture_output=True, text=True, timeout=5)
            if result.returncode:
                continue
            for key in result.stdout.splitlines():
                try:
                    fp = fingerprint(key)
                except (ConfigError, ValueError):
                    continue
                found.setdefault(fp, (key, socket))
        except (OSError, subprocess.TimeoutExpired):
            continue
    return found


def choose_public_key(ask, select, field):
    keys = agent_keys()
    mode = select("Публичен SSH ключ за admin:", [
        ("agent", "Избор от SSH agent / YubiKey (само публични ключове)"),
        ("paste", "Поставяне на един OpenSSH публичен ключ"),
        ("file", "Прочитане на публичен ключ от файл (.pub)"),
    ], "agent" if keys else "paste")
    if mode == "agent":
        if not keys:
            raise ConfigError("No public keys in reachable SSH agents; use paste or .pub file.")
        fp = select("Избери ключ по отпечатък (без подписване/докосване):", [
            (fp, f"{fp} | {key.split()[0]} | {' '.join(key.split()[2:])} | {socket}")
            for fp, (key, socket) in keys.items()], next(iter(keys)))
        key = keys[fp][0]
    elif mode == "paste":
        key = field("Публичен ключ (ssh-ed25519 …; никога частен ключ):", section="admin", key="ssh_public_key")
    else:
        try:
            key = Path(field("Път до публичния OpenSSH ключ (.pub):")).expanduser().read_text().strip()
        except OSError:
            raise ConfigError("Cannot read the public SSH key file.") from None
    print("Admin public key: " + fingerprint(key))
    return key
