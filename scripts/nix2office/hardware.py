"""Read-only Linux inventory, locally or through a verified SSH connection."""
import json
import re
import subprocess

from .config import ConfigError, GPU_MODULES


PROBE = r'''set -eu
export LC_ALL=C
printf 'N2O_MEMORY_KIB='; awk '/^MemTotal:/ { print $2 }' /proc/meminfo
printf 'N2O_THREADS='; awk '/^processor[[:space:]]*:/ { n++ } END { print n+0 }' /proc/cpuinfo
printf 'N2O_CPU='; sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -n 1
printf 'N2O_VENDOR='; sed -n 's/^vendor_id[[:space:]]*: //p' /proc/cpuinfo | head -n 1
printf 'N2O_ARCH='; uname -m
printf 'N2O_BOOT='; if test -d /sys/firmware/efi; then echo uefi; else echo bios; fi
printf 'N2O_GPU='; for m in /sys/class/drm/card*/device/driver/module; do test ! -e "$m" || basename "$(readlink -f "$m")"; done
printf '\nN2O_DISKS_JSON\n'
lsblk --json --bytes --paths --output NAME,TYPE,SIZE,MODEL,TRAN,ROTA,RO,MOUNTPOINTS
printf '\nN2O_BY_ID\n'
for d in /dev/disk/by-id/*; do
  test -b "$d" || continue
  case "$d" in *-part[0-9]*) continue;; esac
  printf '%s\t%s\n' "$d" "$(readlink -f "$d")"
done
'''


def _clean(value):
    return "".join(c for c in str(value) if ord(c) >= 32 and ord(c) != 127).strip()


def parse_probe(output, source="local"):
    try:
        facts, rest = output.split("\nN2O_DISKS_JSON\n", 1)
        disks_json, aliases = rest.split("\nN2O_BY_ID\n", 1)
        fields = dict(line.split("=", 1) for line in facts.splitlines() if line.startswith("N2O_") and "=" in line)
        devices = json.loads(disks_json)["blockdevices"]
        ids = {}
        for line in aliases.splitlines():
            alias, device = line.split("\t", 1)
            if re.fullmatch(r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+", alias):
                ids.setdefault(device, []).append(alias)
        vendor = {"GenuineIntel": "intel", "AuthenticAMD": "amd"}.get(fields["N2O_VENDOR"], "unknown")
        # GPU driver names can occupy several lines. Only accept known KMS drivers.
        gpu_text = facts.split("N2O_GPU=", 1)[1]
        modules = sorted(set(gpu_text.splitlines()) & set(GPU_MODULES))
        disks = []
        for d in devices:
            if d.get("type") != "disk":
                continue
            disk_ids = sorted(ids.get(d["name"], []), key=lambda p: (not p.split("/")[-1].startswith(("wwn-", "nvme-eui", "nvme-uuid")), len(p), p))
            mounts = []
            def collect_mounts(node):
                mounts.extend(p for p in (node.get("mountpoints") or []) if p)
                for child in node.get("children", []):
                    collect_mounts(child)
            collect_mounts(d)
            disks.append({"name": d["name"], "by_id": disk_ids, "size_bytes": int(d["size"]),
                          "model": _clean(d.get("model") or ""), "transport": d.get("tran") or "unknown",
                          "rotational": bool(d.get("rota")), "read_only": bool(d.get("ro")), "mountpoints": mounts})
        return {"source": source, "architecture": _clean(fields["N2O_ARCH"]), "cpu": _clean(fields["N2O_CPU"]),
                "cpu_vendor": vendor, "memory_mib": int(fields["N2O_MEMORY_KIB"]) // 1024,
                "threads": int(fields["N2O_THREADS"]), "boot_mode": fields["N2O_BOOT"],
                "initrd_modules": modules, "disks": disks}
    except (ValueError, KeyError, TypeError):
        raise ConfigError("Hardware inventory could not be parsed; expected Linux /proc, sysfs and a recent lsblk.") from None


def probe(target=None, ssh_config=None, ssh_socket=None):
    command = ["sh", "-s"]
    if target is not None:
        if target.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.@:\[\]-]+", target):
            raise ConfigError("Use an SSH host alias or user@host, without shell arguments.")
        command = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ForwardAgent=no", "-o", "ConnectTimeout=10"]
        if ssh_config:
            command += ["-F", str(ssh_config)]
        if ssh_socket:
            command += ["-S", str(ssh_socket)]
        command += [target, "sh -s"]
    try:
        result = subprocess.run(command, input=PROBE, capture_output=True, text=True, timeout=45, check=True)
    except (OSError, subprocess.SubprocessError):
        raise ConfigError("Hardware discovery failed. For SSH, first establish trusted host/key access; no passwords are accepted by this helper. You can also load a saved hardware JSON inventory.") from None
    return parse_probe(result.stdout, target or "local")


def eligible_disks(inventory):
    """Never propose removable USB media or read-only disks for installation."""
    return [d for d in inventory.get("disks", [])
            if d.get("by_id") and d.get("transport") != "usb" and not d.get("read_only")]


def recommendation(inventory):
    memory = inventory.get("memory_mib", 0)
    threads = inventory.get("threads", 0)
    light = memory < 4096 or threads <= 2
    notes = ["Препоръките са отправна точка, а не гарантиран капацитет или сравнение на браузъри."]
    if memory < 2048:
        notes.append("Малко RAM: малко браузърни табове и избирателна Nextcloud синхронизация; не включвай ненужни VPN услуги.")
    if any(d.get("rotational") for d in eligible_disks(inventory)):
        notes.append("Има механичен диск; SSD би помогнал при отваряне на приложения и swap.")
    return {"profile": "light" if light else "standard", "browser": "firefox-esr", "office": "libreoffice",
            "pdf_editor": "pdfarranger" if light else "both", "notes": notes}


def machine_hardware(inventory):
    return {k: inventory[k] for k in ("cpu", "cpu_vendor", "memory_mib", "threads", "boot_mode", "initrd_modules")}
