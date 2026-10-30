"""The versioned, secret-free machine.toml schema."""
import base64
import copy
import ipaddress
import json
import re
import struct
import tomllib
from pathlib import Path


class ConfigError(ValueError):
    pass


CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text())

DEFAULTS = {
    "version": 1,
    "hostname": "office-pc",
    "disk": "",
    "boot_mode": "bios",
    "profile": "light",
    "boot_splash": True,
    "performance": {"cpu_governor": "auto"},
    "remote_support": {"mode": "off", "id_server": "", "relay_server": "", "public_key": ""},
    "tools": {"comma": False},
    "fonts": {"microsoft_core": False, "office_fallbacks": True},
    "devices": {"bluetooth": False, "unfree_firmware": False},
    "user": {"name": "office", "full_name": "Офис", "email": ""},
    "apps": {"browser": "firefox-esr", "office": "libreoffice", "pdf_editor": "pdfarranger", "nextcloud": True, "artcraft": False, "extra": []},
    "keyboard": {"bulgarian": "phonetic"},
    "sharing": {"mode": "client", "workgroup": "WORKGROUP", "folder": "Shared", "network": "192.0.2.0/24", "read_only": False},
    "vpn": {"wireguard": True, "tailscale": False, "zerotier": False, "zerotier_networks": []},
    "admin": {"network": "192.0.2.0/24", "ssh_public_key": ""},
    "hardware": {"cpu": "", "cpu_vendor": "unknown", "cpu_family": 0, "cpu_model": 0, "cpu_max_mhz": 0,
                 "frequency_drivers": [], "frequency_governors": [], "frequency_current_governors": [],
                 "memory_mib": 0, "threads": 0, "boot_mode": "unknown", "initrd_modules": [], "pci_ids": [], "usb_ids": [], "bluetooth_detected": False},
}
BROWSERS = ("firefox-esr", "chromium", "brave", "google-chrome")
OFFICES = ("libreoffice", "onlyoffice", "none")
PDF_EDITORS = ("none", "pdfarranger", "xournalpp", "both")
GPU_MODULES = ("i915", "xe", "amdgpu", "radeon", "nouveau")
CPU_GOVERNORS = ("auto", "schedutil", "ondemand", "powersave", "performance")
RESERVED_USERS = {
    "root", "admin", "nixos", "nobody", "lightdm", "daemon", "bin", "sys", "sync",
    "games", "man", "lp", "mail", "news", "uucp", "proxy", "www-data", "backup",
    "list", "irc", "gnats", "messagebus", "polkituser", "sshd", "ntp", "chrony",
    "dbus", "avahi", "cups", "rpc",
}


def text(value, field, limit=512):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError(f"{field}: expected text without control characters (up to {limit} characters).")
    return value


def pattern(value, field, regex):
    text(value, field)
    if not re.fullmatch(regex, value):
        raise ConfigError(f"{field}: invalid format.")


def validate_public_key(value):
    text(value, "admin.ssh_public_key", 16384)
    if not value:
        return
    parts = value.split()
    supported = {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
                 "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com"}
    try:
        if len(parts) < 2 or parts[0] not in supported:
            raise ValueError
        blob = base64.b64decode(parts[1], validate=True)
        length = struct.unpack(">I", blob[:4])[0]
        if blob[4:4 + length].decode("ascii") != parts[0] or len(blob) <= 4 + length:
            raise ValueError
    except (ValueError, UnicodeError, struct.error):
        raise ConfigError("admin.ssh_public_key: expected one OpenSSH public key, never a private key.") from None


def validate_machine(raw):
    """Validate before any key generation, file creation or Nix evaluation."""
    if not isinstance(raw, dict):
        raise ConfigError("Expected a TOML document.")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ConfigError("Unknown top-level field(s): " + ", ".join(sorted(unknown)) + ". Secrets do not belong in machine.toml.")
    m = copy.deepcopy(DEFAULTS)
    if raw.get("profile") == "standard":
        m["apps"]["pdf_editor"] = "both"
    for key, value in raw.items():
        if isinstance(DEFAULTS[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{key}: expected a table.")
            unknown = set(value) - set(DEFAULTS[key])
            if unknown:
                raise ConfigError(f"Unknown {key} field(s): " + ", ".join(sorted(unknown)) + ". No passwords or private keys are accepted.")
            m[key].update(value)
        else:
            m[key] = value
    for key in ("hostname", "disk", "boot_mode", "profile"):
        text(m[key], key)
    if type(m["version"]) is not int or m["version"] != 1:
        raise ConfigError("Only machine.toml version = 1 is supported.")
    pattern(m["hostname"], "hostname", r"[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]")
    pattern(m["disk"], "disk", r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+")
    if Path(m["disk"]).name in {".", ".."} or re.search(r"-part[0-9]+$", m["disk"]):
        raise ConfigError("disk: select a whole disk by-id, not a partition.")
    for field, choices in (("boot_mode", ("bios", "uefi")), ("profile", ("light", "standard"))):
        if m[field] not in choices:
            raise ConfigError(f"{field}: choose from {', '.join(choices)}.")
    user = m["user"]
    pattern(user["name"], "user.name", r"[a-z_][a-z0-9_.-]{0,30}")
    if user["name"] in RESERVED_USERS or user["name"].startswith(("nixbld", "systemd-")):
        raise ConfigError("user.name: choose a separate desktop account, not a reserved system/admin name.")
    text(user["full_name"], "user.full_name", 128)
    if not user["full_name"].strip() or any(c in user["full_name"] for c in ":,"):
        raise ConfigError("user.full_name: enter a displayed name without GECOS separators (: or comma).")
    text(user["email"], "user.email", 254)
    if user["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", user["email"]):
        raise ConfigError("user.email: enter an e-mail address, or leave it empty.")
    for key, choices in (("browser", BROWSERS), ("office", OFFICES), ("pdf_editor", PDF_EDITORS)):
        if m["apps"][key] not in choices:
            raise ConfigError(f"apps.{key}: choose from {', '.join(choices)}.")
    if m["keyboard"]["bulgarian"] not in ("phonetic", "bds"):
        raise ConfigError("keyboard.bulgarian: choose phonetic or bds.")
    r = m["remote_support"]
    if r["mode"] not in ("off", "consent", "unattended"):
        raise ConfigError("remote_support.mode: choose off, consent or unattended.")
    for key in ("id_server", "relay_server"):
        text(r[key], "remote_support." + key)
        if r[key] and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?", r[key]):
            raise ConfigError("remote_support: use a hostname/IPv4 with optional port.")
        if ":" in r[key] and not 1 <= int(r[key].rsplit(":", 1)[1]) <= 65535:
            raise ConfigError("remote_support: invalid port.")
    text(r["public_key"], "remote_support.public_key")
    if r["public_key"]:
        try:
            if len(base64.b64decode(r["public_key"], validate=True)) != 32:
                raise ValueError
        except (ValueError, base64.binascii.Error):
            raise ConfigError("remote_support.public_key: expected a base64 32-byte public key.") from None
    if r["mode"] != "off" and not all(r[k] for k in ("id_server", "relay_server", "public_key")):
        raise ConfigError("remote_support: provide both servers and the public key.")
    extra = m["apps"]["extra"]
    if not isinstance(extra, list) or any(not isinstance(x, str) or x not in CATALOG for x in extra) or len(set(extra)) != len(extra):
        raise ConfigError("apps.extra: choose unique application IDs from the supported catalog.")
    if type(m["tools"]["comma"]) is not bool:
        raise ConfigError("tools.comma: expected true or false.")
    for key, value in m["fonts"].items():
        if type(value) is not bool:
            raise ConfigError(f"fonts.{key}: expected true or false.")
    sharing = m["sharing"]
    if sharing["mode"] not in ("client", "both"):
        raise ConfigError("sharing.mode: choose client or both.")
    pattern(sharing["workgroup"], "sharing.workgroup", r"[A-Za-z0-9][A-Za-z0-9_-]{0,14}")
    pattern(sharing["folder"], "sharing.folder", r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
    if sharing["folder"].lower() in {"global", "homes", "printers"}:
        raise ConfigError("sharing.folder: choose a folder name other than a reserved Samba section.")
    for field, value in (("sharing.network", sharing["network"]), ("admin.network", m["admin"]["network"])):
        text(value, field)
        try:
            if not re.fullmatch(r"[0-9.]+/(0|[1-9][0-9]?)", value):
                raise ValueError
            ipaddress.IPv4Network(value)
        except ValueError:
            hint = "192.168.1.0/24 or one IP /32; 0.0.0.0/0 allows every IPv4 source"
            raise ConfigError(f"{field}: expected an explicit IPv4 CIDR, e.g. {hint}.") from None
    validate_public_key(m["admin"]["ssh_public_key"])
    for field, value in (("boot_splash", m["boot_splash"]), ("apps.nextcloud", m["apps"]["nextcloud"]), ("apps.artcraft", m["apps"]["artcraft"]),
                         ("sharing.read_only", sharing["read_only"]),
                         *(("vpn." + k, m["vpn"][k]) for k in ("wireguard", "tailscale", "zerotier"))):
        if type(value) is not bool:
            raise ConfigError(f"{field}: expected true or false.")
    networks = m["vpn"]["zerotier_networks"]
    if not isinstance(networks, list) or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", v) for v in networks):
        raise ConfigError("vpn.zerotier_networks: expected a list of 16-digit hexadecimal network IDs.")
    if networks and not m["vpn"]["zerotier"]:
        raise ConfigError("Enable vpn.zerotier before supplying its network IDs.")
    for key, value in m["devices"].items():
        if type(value) is not bool:
            raise ConfigError(f"devices.{key}: expected true or false.")
    h = m["hardware"]
    if type(h["bluetooth_detected"]) is not bool:
        raise ConfigError("hardware.bluetooth_detected: expected true or false.")
    for key, regex in (("pci_ids", r"[0-9a-f]{6}:[0-9a-f]{4}:[0-9a-f]{4}:[A-Za-z0-9_-]+"), ("usb_ids", r"[0-9a-f]{4}:[0-9a-f]{4}")):
        if not isinstance(h[key], list) or any(not isinstance(v, str) or not re.fullmatch(regex, v) for v in h[key]):
            raise ConfigError(f"hardware.{key}: invalid device inventory.")
    text(h["cpu"], "hardware.cpu")
    if h["cpu_vendor"] not in ("intel", "amd", "unknown") or h["boot_mode"] not in ("bios", "uefi", "unknown"):
        raise ConfigError("hardware: invalid CPU vendor or detected boot mode.")
    for key in ("memory_mib", "threads", "cpu_family", "cpu_model", "cpu_max_mhz"):
        if type(h[key]) is not int or h[key] < 0:
            raise ConfigError(f"hardware.{key}: expected a non-negative integer.")
    if not isinstance(h["initrd_modules"], list) or any(v not in GPU_MODULES for v in h["initrd_modules"]):
        raise ConfigError("hardware.initrd_modules: unsupported early graphics driver.")
    for key in ("frequency_drivers", "frequency_governors", "frequency_current_governors"):
        if not isinstance(h[key], list) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", v) for v in h[key]):
            raise ConfigError(f"hardware.{key}: expected a list of driver/governor names.")
    governor = m["performance"]["cpu_governor"]
    if governor not in CPU_GOVERNORS:
        raise ConfigError("performance.cpu_governor: choose auto, schedutil, ondemand, powersave or performance.")
    if governor != "auto" and h["frequency_governors"] and governor not in h["frequency_governors"]:
        raise ConfigError("performance.cpu_governor: not available in this target's hardware snapshot; re-probe before selecting another governor.")
    return m


def load_machine(path):
    try:
        return validate_machine(tomllib.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as e:
        # TOML parser diagnostics can include the offending line, possibly a secret.
        raise ConfigError(f"Cannot read machine.toml ({type(e).__name__}); check its syntax and location.") from None


def dump_machine(machine):
    m = validate_machine(machine)
    lines = ["# Nix2office configuration. Never put passwords, tokens or private keys here."]
    for key, value in m.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    for section, values in m.items():
        if isinstance(values, dict):
            lines.extend(("", f"[{section}]"))
            lines.extend(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items())
    return "\n".join(lines) + "\n"
