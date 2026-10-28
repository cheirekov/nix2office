"""Read-only Linux inventory, locally or through a verified SSH connection."""
import json
import re
import subprocess

from .config import ConfigError, DEFAULTS, GPU_MODULES


PROBE = r'''set -eu
export LC_ALL=C
printf 'N2O_MEMORY_KIB='; awk '/^MemTotal:/ { print $2 }' /proc/meminfo
printf 'N2O_THREADS='; awk '/^processor[[:space:]]*:/ { n++ } END { print n+0 }' /proc/cpuinfo
printf 'N2O_CPU='; sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -n 1
printf 'N2O_VENDOR='; sed -n 's/^vendor_id[[:space:]]*: //p' /proc/cpuinfo | head -n 1
printf 'N2O_FAMILY='; awk '/^cpu family[[:space:]]*:/ { print $4; exit }' /proc/cpuinfo
printf 'N2O_MODEL='; awk '/^model[[:space:]]*:/ { print $3; exit }' /proc/cpuinfo
printf 'N2O_MAX_KHZ='; for p in /sys/devices/system/cpu/cpufreq/policy*/cpuinfo_max_freq; do test ! -r "$p" || cat "$p"; done | awk 'BEGIN { max=0 } $1>max { max=$1 } END { print max }'
printf 'N2O_FREQ_DRIVERS='; for p in /sys/devices/system/cpu/cpufreq/policy*/scaling_driver; do test ! -r "$p" || cat "$p"; done | sort -u | tr '\n' ' '; printf '\n'
printf 'N2O_GOVERNORS='; for p in /sys/devices/system/cpu/cpufreq/policy*/scaling_available_governors; do test ! -r "$p" || { tr '\n' ' ' < "$p"; printf ';'; }; done; printf '\n'
printf 'N2O_CURRENT_GOVERNORS='; for p in /sys/devices/system/cpu/cpufreq/policy*/scaling_governor; do test ! -r "$p" || cat "$p"; done | sort -u | tr '\n' ' '; printf '\n'
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
        policy_governors = [set(part.split()) for part in fields.get("N2O_GOVERNORS", "").split(";") if part.strip()]
        governors = sorted(set.intersection(*policy_governors)) if policy_governors else []
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
                "cpu_family": int(fields.get("N2O_FAMILY", "0") or "0"),
                "cpu_model": int(fields.get("N2O_MODEL", "0") or "0"),
                "cpu_max_mhz": int(fields.get("N2O_MAX_KHZ", "0") or "0") // 1000,
                "frequency_drivers": sorted(set(fields.get("N2O_FREQ_DRIVERS", "").split())),
                "frequency_governors": governors,
                "frequency_current_governors": sorted(set(fields.get("N2O_CURRENT_GOVERNORS", "").split())),
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
    # Family 14h/16h are AMD's Bobcat/Jaguar/Puma low-power CPUs. Four cores alone
    # do not make these a fast desktop. A low reported policy maximum is also
    # a conservative signal, never a cross-architecture performance benchmark.
    legacy_amd = inventory.get("cpu_vendor") == "amd" and inventory.get("cpu_family") in (20, 22)
    low_clock = 0 < inventory.get("cpu_max_mhz", 0) <= 1600
    light = memory < 4096 or threads <= 2 or legacy_amd or low_clock
    notes = ["Препоръките са отправна точка, а не гарантиран капацитет или сравнение на браузъри."]
    if memory < 2048:
        notes.append("Малко RAM: малко браузърни табове и избирателна Nextcloud синхронизация; не включвай ненужни VPN услуги.")
    if legacy_amd or low_clock:
        notes.append("По-слаб CPU: Light е по-консервативният начален избор дори при достатъчно RAM; броят ядра не е измерване на скоростта.")
    if inventory.get("cpu_vendor") == "amd":
        notes.append("AMD microcode и redistributable firmware се включват; amd-pstate не се налага на неподдържан процесор.")
    if "radeon" in inventory.get("initrd_modules", []):
        notes.append("Открит е radeon: запазваме работещия драйвер и го зареждаме рано за splash; без принудително преминаване към amdgpu.")
    if any(d.get("rotational") for d in eligible_disks(inventory)):
        notes.append("Има механичен диск; SSD би помогнал при отваряне на приложения и swap.")
    governor = balanced_governor(inventory)
    notes.append("CPU governor: " + governor + ". Performance остава избор за сравнение след инсталация, с повече консумация/топлина; няма обещан процент ускорение.")
    return {"profile": "light" if light else "standard", "cpu_governor": governor, "browser": "firefox-esr", "office": "libreoffice",
            "pdf_editor": "pdfarranger" if light else "both", "notes": notes}


def machine_hardware(inventory):
    # Old saved inventories remain valid and get unknown/empty new facts.
    return {k: inventory.get(k, default) for k, default in DEFAULTS["hardware"].items()}


def balanced_governor(inventory):
    available = inventory.get("frequency_governors", [])
    drivers = inventory.get("frequency_drivers", [])
    # With active P-state drivers, powersave is dynamic, not a minimum-clock lock.
    # Never recommend it for generic acpi-cpufreq (where semantics differ).
    if drivers and all(d in ("intel_pstate", "amd-pstate-epp") for d in drivers):
        return "powersave" if "powersave" in available else "auto"
    for governor in ("schedutil", "ondemand"):
        if governor in available:
            return governor
    return "auto"


def describe_inventory(inventory):
    advice = recommendation(inventory)
    print(f'CPU: {inventory["cpu"]}; нишки: {inventory["threads"]}; RAM: {inventory["memory_mib"]} MiB; boot: {inventory["boot_mode"]}')
    print(f'CPU policy maximum: {inventory.get("cpu_max_mhz", 0) or "unknown"} MHz (не е измерен turbo максимум)')
    print('Честотен драйвер: ' + (', '.join(inventory.get("frequency_drivers", [])) or 'unknown'))
    print('Текущ governor: ' + (', '.join(inventory.get("frequency_current_governors", [])) or 'unknown'))
    print('Графични драйвери: ' + (', '.join(inventory["initrd_modules"]) or 'unknown'))
    for disk in eligible_disks(inventory):
        print(f'Вътрешен диск: {disk["model"]} | {disk["size_bytes"] / 2**30:.1f} GiB | {"HDD" if disk["rotational"] else "SSD/flash"}')
    print('Препоръка: ' + advice['profile'] + ', Firefox ESR, LibreOffice; PDF: ' + advice['pdf_editor'])
    for note in advice['notes']:
        print('• ' + note)
    return advice
