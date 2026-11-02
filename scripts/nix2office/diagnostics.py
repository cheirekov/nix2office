"""Local, read-only M1 diagnostics. No privilege escalation or device activation.

``runner`` has subprocess.run's interface; tests can inject it without probing
the host. Only selected facts enter the report, never raw command errors/logs.
"""
import argparse
from collections import Counter
import ipaddress
import json
import os
import platform
from pathlib import Path
import re
import stat
import subprocess
import sys

from .hardware import hardware_review, RULES_VERSION


TIMEOUT = 4
MAX_OUTPUT = 2 * 1024 * 1024
STATUSES = ("pass", "warning", "unknown", "not-applicable")
UNAVAILABLE = "Няма достъп, липсва инструмент или проверката не завърши."
AUDIBLE = "Необходимо е човек да потвърди чрез слушане избрания звуков изход."


def _check(status, message, **details):
    return {"status": status, "message": message, "details": details}


def _token(value, pattern=r"[A-Za-z0-9_.:@+-]{1,128}"):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else None


def _text(value):
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if c.isprintable())[:200]


def _command(runner, env, args):
    try:
        result = runner(args, capture_output=True, text=True, timeout=TIMEOUT,
                        check=False, env=env)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    if result.returncode or not isinstance(result.stdout, str) or len(result.stdout) > MAX_OUTPUT:
        return None
    return result.stdout


def _json_command(run, args):
    output = run(args)
    try:
        result = json.loads(output) if output is not None else None
    except (ValueError, RecursionError):
        return None
    return result if isinstance(result, list) and all(isinstance(x, dict) for x in result) else None


def _read(path):
    with path.open(encoding="ascii") as stream:
        return stream.read(256).strip()


def _pci(root):
    devices, incomplete = [], False
    try:
        paths = sorted((root / "bus/pci/devices").iterdir())
    except OSError:
        return _check("unknown", UNAVAILABLE, devices=[])
    for path in paths:
        try:
            address = _token(path.name, r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")
            cls, vendor, device = (_read(path / key).removeprefix("0x").lower()
                                  for key in ("class", "vendor", "device"))
            if not (address and re.fullmatch(r"[0-9a-f]{6}", cls)
                    and re.fullmatch(r"[0-9a-f]{4}", vendor)
                    and re.fullmatch(r"[0-9a-f]{4}", device)):
                raise ValueError
            try:
                driver = _token(Path(os.readlink(path / "driver")).name)
                if not driver:
                    raise ValueError
            except FileNotFoundError:
                driver = "unbound"
            devices.append(dict(address=address, pci_class=cls, vendor=vendor,
                                device=device, driver=driver))
        except (OSError, UnicodeError, ValueError):
            incomplete = True
    # Reuse the existing conservative review (bridges may legitimately be
    # unbound), but never run hardware.PROBE: it contains a sudo fallback.
    review = hardware_review({"pci_ids": [
        f'{d["pci_class"]}:{d["vendor"]}:{d["device"]}:{d["driver"]}' for d in devices]})
    for device, assessment in zip(devices, review['devices']):
        device.update(status=assessment['status'], next_action=assessment['action'])
    status = "unknown" if incomplete else "warning" if review["needs_review"] else "pass"
    if not paths:
        status = "not-applicable"
    return _check(status, "Текущи PCI обвързвания; драйверът не доказва работеща графика или звук.",
                  devices=devices, complete=not incomplete)


def _usb(root):
    devices, incomplete = [], False
    try:
        paths = sorted((root / 'bus/usb/devices').iterdir())
    except OSError:
        return _check('unknown', UNAVAILABLE, devices=[])
    for path in paths:
        try:
            cls = _read(path / 'bInterfaceClass').lower()
        except FileNotFoundError:
            continue # Whole USB devices and root hubs are not interfaces.
        except (OSError, UnicodeError):
            incomplete = True
            continue
        try:
            parent = path.resolve().parent
            vendor, device = (_read(parent / key).lower() for key in ('idVendor', 'idProduct'))
            if not (re.fullmatch(r'[0-9a-f]{2}', cls) and re.fullmatch(r'[0-9a-f]{4}', vendor)
                    and re.fullmatch(r'[0-9a-f]{4}', device)):
                raise ValueError
            try:
                driver = _token(Path(os.readlink(path / 'driver')).name)
                if not driver:
                    raise ValueError
            except FileNotFoundError:
                driver = 'unbound'
            review = hardware_review({'usb_interfaces': [f'{vendor}:{device}:{cls}:{driver}']})['usb_devices'][0]
            devices.append(dict(interface=_token(path.name), **review))
        except (OSError, UnicodeError, ValueError):
            incomplete = True
    status = 'unknown' if incomplete else 'warning' if any(d['status'] == 'warning' for d in devices) else 'pass' if devices else 'not-applicable'
    return _check(status, 'Текущи USB драйвери; отделната функция на устройството изисква проверка.', devices=devices)


def _graphics(run, env):
    if not env.get("DISPLAY"):
        return _check("unknown", "Няма съществуваща X/Xwayland сесия за glxinfo -B.")
    output = run(["glxinfo", "-B"])
    if output is None:
        return _check("unknown", UNAVAILABLE)
    fields = {}
    for line in output.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep and key in ("OpenGL renderer string", "direct rendering", "Accelerated"):
            fields[key] = value.strip()
    renderer = fields.get("OpenGL renderer string", "")
    if not renderer:
        return _check("unknown", "glxinfo не предостави графичен renderer.")
    software = bool(re.search(r"llvmpipe|softpipe|swrast|software rasterizer|swiftshader", renderer, re.I))
    disabled = fields.get("direct rendering", "").lower() == "no" or fields.get("Accelerated", "").lower() == "no"
    direct = {"yes": True, "no": False}.get(fields.get("direct rendering", "").lower())
    accelerated = {"yes": True, "no": False}.get(fields.get("Accelerated", "").lower())
    status = "warning" if software or disabled else "pass" if direct or accelerated else "unknown"
    # Direct rendering alone can also describe a software renderer.
    return _check(status,
                  "Renderer в текущата сесия; това не е benchmark или тест на всички GPU.",
                  renderer=_text(renderer), software=software,
                  direct_rendering=direct, accelerated=accelerated)


def _video(run, env):
    display = "wayland" if env.get("WAYLAND_DISPLAY") and env.get("XDG_RUNTIME_DIR") else "x11" if env.get("DISPLAY") else None
    if display is None:
        return _check("unknown", "Няма съществуваща графична сесия за VA-API проверка.")
    output = run(["vainfo", "--display", display])
    if output is None:
        return _check("unknown", UNAVAILABLE)
    capabilities = sorted(set(re.findall(r"\b(VAProfile[A-Za-z0-9_]+)\s*:\s*(VAEntrypoint[A-Za-z0-9_]+)\b", output)))
    if not capabilities:
        return _check("unknown", "vainfo не предостави разпознаваеми VA-API възможности.")
    decode = any(entry in ("VAEntrypointVLD", "VAEntrypointIDCT", "VAEntrypointMoComp")
                 for _, entry in capabilities)
    return _check("pass" if decode else "warning",
                  "VA-API възможности; реално видео възпроизвеждане не е проверено.",
                  decode_available=decode,
                  capabilities=[{"profile": p, "entrypoint": e} for p, e in capabilities[:128]])


def _output_kind(sink):
    port = sink.get("active_port")
    port = port.get("name") if isinstance(port, dict) else port
    properties = sink.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    # Use technical port/profile fields, never human descriptions or aliases.
    profile = properties.get("device.profile.name")
    connector = " ".join(v.lower() for v in (port, profile) if isinstance(v, str))
    if "hdmi" in connector or "displayport" in connector:
        return "hdmi-displayport"
    if "analog" in connector:
        return "analog"
    if "iec958" in connector or "spdif" in connector:
        return "digital"
    if properties.get("device.bus") in ("bluetooth", "usb"):
        return properties["device.bus"]
    if properties.get("device.class") == "abstract":
        return "virtual"
    return "unknown"


def _audio(run, env):
    if not (env.get("XDG_RUNTIME_DIR") or env.get("DBUS_SESSION_BUS_ADDRESS")):
        return _check("unknown", "Няма потребителска сесия. " + AUDIBLE,
                      audible_confirmation="unknown", services={}, sinks=None, cards=None)
    services = {}
    for unit in ("pipewire", "wireplumber", "pipewire-pulse"):
        output = run(["systemctl", "--user", "show", unit + ".service",
                      "--property=LoadState,ActiveState,SubState"])
        fields = dict(line.split("=", 1) for line in (output or "").splitlines() if "=" in line)
        state, load = fields.get("ActiveState"), fields.get("LoadState")
        if state not in ("active", "inactive", "failed", "activating", "deactivating", "reloading") or load not in ("loaded", "not-found", "masked", "error", "bad-setting", "merged", "stub"):
            services[unit] = _check("unknown", UNAVAILABLE)
        else:
            services[unit] = _check("pass" if state == "active" and load == "loaded" else "warning",
                                    "Състояние на потребителската услуга.", active=state, load=load)
    # Explicit local socket disables PulseAudio's implicit server autospawn and
    # ignores any remote PULSE_SERVER. Listing must not start an audio server.
    runtime = env.get("XDG_RUNTIME_DIR", "")
    server = "unix:" + runtime + "/pulse/native" if runtime.startswith("/") else None
    default = run(["pactl", "--server=" + server, "get-default-sink"]) if server else None
    default = default.strip() if default is not None else None
    sinks = _json_command(run, ["pactl", "--server=" + server, "--format=json", "list", "sinks"]) if server else None
    cards = _json_command(run, ["pactl", "--server=" + server, "--format=json", "list", "cards"]) if server else None
    # Names, descriptions, properties, port descriptions and monitor sources
    # can identify people/devices. Export only operational fields and counts.
    safe_sinks = None if sinks is None else [{
        "index": s.get("index") if type(s.get("index")) is int and s["index"] >= 0 else None,
        "output_kind": _output_kind(s),
        "default": s.get("name") == default if default and isinstance(s.get("name"), str) else None,
        "state": s.get("state") if s.get("state") in ("RUNNING", "IDLE", "SUSPENDED") else "unknown",
        "mute": s.get("mute") if isinstance(s.get("mute"), bool) else None,
    } for s in sinks]
    safe_cards = None if cards is None else [{
        "active_profile": _token(c.get("active_profile")) or "unknown"
    } for c in cards]
    states = [c["status"] for c in services.values()]
    incomplete = (safe_sinks is not None and (any(s["state"] == "unknown" or s["mute"] is None or s["index"] is None for s in safe_sinks)
                                            or bool(safe_sinks) and not any(s["default"] is True for s in safe_sinks))
                  or safe_cards is not None and any(c["active_profile"] == "unknown" for c in safe_cards))
    if "unknown" in states or sinks is None or cards is None or incomplete:
        status = "unknown"
    elif "warning" in states or not sinks or all(s.get("mute") is True for s in sinks):
        status = "warning"
    else:
        status = "pass"
    return _check(status, "Проверено е софтуерното състояние. " + AUDIBLE,
                  audible_confirmation="unknown", services=services, sinks=safe_sinks, cards=safe_cards)


def _bluetooth(run, root):
    controllers = None
    usb_adapter, usb_readable = False, False
    try:
        controllers = sorted(p.name for p in (root / "class/bluetooth").iterdir()
                             if re.fullmatch(r"hci[0-9]+", p.name))
    except FileNotFoundError:
        try:
            # No Bluetooth class is normal when no controller was detected.
            list((root / "class").iterdir())
            controllers = []
        except OSError:
            pass
    except OSError:
        pass
    try:
        usb_paths = list((root / "bus/usb/devices").iterdir())
        usb_readable = True
        for path in usb_paths:
            try:
                if [_read(path / f) for f in ("bInterfaceClass", "bInterfaceSubClass", "bInterfaceProtocol")] == ["e0", "01", "01"]:
                    usb_adapter = True
            except FileNotFoundError:
                continue
            except (OSError, UnicodeError):
                usb_readable = False
    except OSError:
        pass
    if controllers == [] and usb_readable and not usb_adapter:
        return _check("not-applicable", "В достъпния sysfs не е открит Bluetooth адаптер; възможно е да е изключен във firmware.",
                      controllers=[], usb_adapter_detected=False)
    # bluetoothctl can auto-activate org.bluez. Query the existing systemd
    # service first; never contact BlueZ while its daemon is absent/inactive.
    service = run(["systemctl", "show", "bluetooth.service", "--property=LoadState,ActiveState"])
    fields = dict(line.split("=", 1) for line in (service or "").splitlines() if "=" in line)
    if fields.get("LoadState") != "loaded" or fields.get("ActiveState") != "active":
        state = fields.get("ActiveState")
        known = state in ("inactive", "failed", "activating", "deactivating", "reloading") or fields.get("LoadState") in ("not-found", "masked")
        return _check("warning" if known and (controllers or usb_adapter) else "unknown",
                      "Bluetooth услугата не е потвърдена като вече активна; не се изпращат BlueZ заявки.",
                      controllers=controllers, usb_adapter_detected=usb_adapter,
                      service_state=state if _token(state) else "unknown")
    listing = run(["bluetoothctl", "--timeout", "3", "list"])
    if listing is None:
        return _check("unknown", UNAVAILABLE, controllers=controllers, usb_adapter_detected=usb_adapter)
    addresses = re.findall(r"^Controller ([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b", listing, re.M)
    if not addresses:
        status = "unknown" if listing.strip() else "warning" if controllers or usb_adapter else "not-applicable" if controllers == [] else "unknown"
        return _check(status, "BlueZ не отчита контролер; адаптерът може да е изключен или недостъпен.",
                      controllers=controllers, usb_adapter_detected=usb_adapter)
    powered = []
    for address in addresses[:16]:
        output = run(["bluetoothctl", "--timeout", "3", "show", address])
        match = re.search(r"^\s*Powered:\s*(yes|no)\s*$", output or "", re.M)
        powered.append(match[1] == "yes" if match else None)
    status = "unknown" if None in powered or len(addresses) > 16 else "pass" if all(powered) else "warning"
    return _check(status, "Състояние на Bluetooth контролерите; връзка с периферия не е проверена.",
                  controllers=controllers, powered=powered, usb_adapter_detected=usb_adapter)


def _ip(value):
    try:
        return ipaddress.ip_address(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _network(run):
    links = _json_command(run, ["ip", "-j", "link", "show"])
    addresses = _json_command(run, ["ip", "-j", "address", "show"])
    routes4 = _json_command(run, ["ip", "-j", "-4", "route", "show", "default"])
    routes6 = _json_command(run, ["ip", "-j", "-6", "route", "show", "default"])
    safe_links, safe_addresses, safe_routes = [], [], []
    up = set()
    for link in links or []:
        name = _token(link.get("ifname"))
        flags = link.get("flags", [])
        if not name or not isinstance(flags, list):
            continue
        state = link.get("operstate")
        state = state if state in ("UP", "DOWN", "UNKNOWN", "DORMANT", "LOWERLAYERDOWN", "NOTPRESENT", "TESTING") else "UNKNOWN"
        loopback = "LOOPBACK" in flags or name == "lo"
        active = not loopback and "UP" in flags and (state == "UP" or "LOWER_UP" in flags)
        if active:
            up.add(name)
        safe_links.append(dict(interface=name, state=state, local_link_up=active))
    configured = False
    for interface in addresses or []:
        name = _token(interface.get("ifname"))
        info = interface.get("addr_info")
        if not name or not isinstance(info, list):
            continue
        for address in info:
            if not isinstance(address, dict):
                continue
            addr = _ip(address.get("local"))
            prefix = address.get("prefixlen")
            if addr is None or type(prefix) is not int or not 0 <= prefix <= addr.max_prefixlen:
                continue
            safe_addresses.append(dict(interface=name, address=str(addr), prefixlen=prefix))
            configured |= name in up and not (addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_multicast)
    for route in (routes4 or []) + (routes6 or []):
        name, gateway = _token(route.get("dev")), _ip(route.get("gateway"))
        if name:
            safe_routes.append(dict(interface=name, gateway=str(gateway) if gateway else None))
    available = all(x is not None for x in (links, addresses, routes4, routes6))
    status = "unknown" if not available else "pass" if configured else "warning"
    return _check(status, "Локални интерфейси, адреси и маршрути; достижимостта до други машини не е проверена.",
                  links=safe_links, addresses=safe_addresses, default_routes=safe_routes,
                  local_configuration="pass" if configured else "warning" if available else "unknown",
                  internet=_check("unknown", "Интернет не е проверен: не се изпращат външни заявки."))


def _firmware(run):
    output = run(["dmesg", "--color=never"])
    if not output or not output.strip():
        return _check("unknown", "Kernel/firmware log не е достъпен; липсата на грешки не е проверена.")
    firmware_errors = sum(bool(re.search(r"firmware.*(?:fail|error|missing|not found)|(?:fail|error).*firmware", line, re.I))
                          for line in output.splitlines())
    # Do not include paths, serials, kernel command lines or any raw log text.
    return _check("warning" if firmware_errors else "pass",
                  "Преглед на достъпния kernel log; възможни са fallback и непълни/по-стари записи.",
                  firmware_error_lines=firmware_errors)


def _hex_id(value):
    # nixos-facter uses ID objects with hex/value/name; never export name/serial.
    if isinstance(value, dict):
        value = value.get("hex", value.get("value"))
    if type(value) is int and 0 <= value <= 65535:
        return f"{value:04x}"
    if isinstance(value, str) and re.fullmatch(r"(?:0x)?[0-9A-Fa-f]{4}", value):
        return value.removeprefix("0x").lower()
    return None


def _facter_pci(data):
    hardware = data["hardware"]
    if not isinstance(hardware, dict):
        raise ValueError
    explicit = hardware.get("pci")
    if explicit is not None and (not isinstance(explicit, list) or not all(isinstance(d, dict) for d in explicit)):
        raise ValueError
    devices, seen = [], set()
    # Facter normally groups PCI devices under graphics_card, bridge, sound,
    # storage_controller, etc., rather than a single hardware.pci array.
    for category, rows in hardware.items():
        if not isinstance(rows, list):
            continue
        for device in rows:
            if not isinstance(device, dict):
                continue
            bus = device.get("bus_type")
            address = _token(device.get("sysfs_bus_id"), r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]")
            is_pci = isinstance(bus, dict) and (bus.get("value") == 4 or bus.get("name") == "PCI")
            if category != "pci" and not (is_pci or address):
                continue
            if address and address in seen:
                continue
            if address:
                seen.add(address)
            devices.append(device)
    if not devices and explicit is None:
        raise ValueError
    pairs = [(_hex_id(d.get("vendor")), _hex_id(d.get("device"))) for d in devices]
    if any(None in pair for pair in pairs):
        raise ValueError
    return devices, pairs


def _facter(path, pci):
    if path is None:
        return _check("not-applicable", "Не е подаден съществуващ nixos-facter отчет.")
    try:
        # O_NONBLOCK also prevents a supplied FIFO from hanging the collector.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError
            raw = stream.read(MAX_OUTPUT + 1)
        if len(raw) > MAX_OUTPUT:
            raise ValueError
        data = json.loads(raw)
        devices, pairs = _facter_pci(data)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return _check("unknown", "nixos-facter отчетът не е достъпен или PCI форматът не се поддържа.")
    if not pci["details"].get("complete"):
        return _check("unknown", "Няма пълен текущ PCI инвентар за сравнение.")
    saved = Counter(":".join(pair) for pair in pairs)
    current = Counter(d["vendor"] + ":" + d["device"] for d in pci["details"]["devices"])
    current_by_address = {d["address"].lower(): d for d in pci["details"]["devices"]}
    changes, compared = [], 0
    for device, pair in zip(devices, pairs):
        address = device.get("sysfs_bus_id")
        now = current_by_address.get(address.lower()) if isinstance(address, str) else None
        # Driver is a kernel binding; DriverModule can have a different name
        # (bochs-drm vs bochs, virtio-pci vs virtio_pci). Never compare those.
        driver = _token(device.get("driver"))
        if now and driver and (now["vendor"], now["device"]) == pair:
            compared += 1
            if driver != now["driver"]:
                changes.append(dict(address=now["address"], saved_driver=driver, current_driver=now["driver"]))
    return _check("warning" if saved != current or changes else "pass",
                  "Сравнение на PCI IDs, брой и налични driver обвързвания; не активира модули и не доказва работоспособност.",
                  only_saved=dict(saved - current), only_current=dict(current - saved),
                  bindings_compared=compared, bindings_status="warning" if changes else "pass" if compared else "unknown",
                  driver_changes=changes)


def collect_report(*, runner=None, environ=None, sysfs_root="/sys", facter_report=None):
    """Return JSON-safe facts. Missing access/tools always remain unknown.

    Optional keyword-only dependencies make tests independent of the machine.
    Each subprocess has a four-second timeout and never uses a shell.
    """
    env = dict(os.environ if environ is None else environ)
    env.update(LC_ALL="C", LANG="C", SYSTEMD_PAGER="cat", SYSTEMD_COLORS="0")
    runner = subprocess.run if runner is None else runner
    run = lambda args: _command(runner, env, args)
    root = Path(sysfs_root)
    pci = _pci(root)
    report = {"schema_version": 1, "read_only": True,
              "kernel_version": platform.release(), "rules_version": RULES_VERSION, "checks": {
        "pci": pci,
        "usb": _usb(root),
        "graphics": _graphics(run, env),
        "video": _video(run, env),
        "audio": _audio(run, env),
        "bluetooth": _bluetooth(run, root),
        "network": _network(run),
        "firmware": _firmware(run),
        "facter": _facter(facter_report, pci),
    }}
    actions = {
        "pci": "Провери посочения PCI адрес, modalias кандидатите и firmware; запази работещите драйвери.",
        "usb": "Провери необвързания USB интерфейс, kernel modalias и firmware; свържи отново устройството само по твой избор.",
        "graphics": "Стартирай от XFCE сесията; при software renderer провери Mesa/DRM и PCI GPU драйвера.",
        "video": "Провери VA-API драйвера за конкретната карта; липсващ VA-API не изключва други видео API.",
        "audio": "В Настройки → Звук избери изход и провери mute; потвърди чрез слушане на кратък клип.",
        "bluetooth": "Провери наличието на адаптер, firmware/rfkill и BlueZ/Blueman настройката; диагностиката не ги включва.",
        "network": "Провери кабела/Wi-Fi и адреса/маршрута в NetworkManager; после потвърди достъп с браузър.",
        "firmware": "Администраторът да прегледа kernel log и конкретния firmware; недостъпен log не доказва липса на грешки.",
        "facter": "Създай локален отчет на същата машина с пакета #facter от текущия pin и сравни PCI адресите/драйверите.",
    }
    for name, check in report['checks'].items():
        if check['status'] in ('warning', 'unknown'):
            check['next_action'] = actions[name]
    return report


def _write_json(path, report):
    """Replace atomically using a private sibling file and a pinned directory.

    Never open the destination for writing: even a concurrent symlink swap
    cannot redirect the write. Reject symlinks and nonregular existing targets.
    """
    path = Path(os.path.abspath(path))
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    temporary = None
    try:
        def check_target():
            try:
                mode = os.stat(path.name, dir_fd=directory, follow_symlinks=False).st_mode
            except FileNotFoundError:
                return
            if not stat.S_ISREG(mode):
                raise ValueError("Изходът трябва да е обикновен файл, без символна връзка.")

        check_target()
        # Use dir_fd for creation, checking, replacement and cleanup so that a
        # renamed parent directory cannot redirect any of these operations.
        for _ in range(100):
            name = ".nix2office-diagnostics-" + os.urandom(12).hex()
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
                temporary = name
                break
            except FileExistsError:
                continue
        else:
            raise OSError("Неуспешно създаване на частен временен файл.")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        check_target()
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        temporary = None
        os.fsync(directory)
    finally:
        if temporary is not None:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def _readable(report):
    labels = {"pci": "PCI драйвери", "usb": "USB интерфейси", "graphics": "Графика", "video": "Видео (VA-API)",
              "audio": "Звук", "bluetooth": "Bluetooth", "network": "Мрежа",
              "firmware": "Kernel/firmware", "facter": "nixos-facter"}
    statuses = {"pass": "проверено", "warning": "внимание", "unknown": "неизвестно", "not-applicable": "неприложимо"}
    lines = ["nix2office — диагностика само за четене",
             'Kernel: ' + report.get('kernel_version', 'unknown') + '; правила: ' + report.get('rules_version', 'unknown')]
    for name, check in report["checks"].items():
        lines.append(f'{labels[name]} [{statuses[check["status"]]}]: {check["message"]}')
        details = check["details"]
        if name == "pci":
            for d in details.get("devices", []):
                lines.append(f'  {d["address"]} {d["vendor"]}:{d["device"]} → {d["driver"]} [{d["status"]}]')
                if d['status'] in ('warning', 'unknown'):
                    lines.append('    ' + d['next_action'])
        elif name == 'usb':
            for d in details.get('devices', []):
                lines.append(f'  {d["interface"]} {d["vendor"]}:{d["device"]} → {d["driver"]} [{d["status"]}]')
                if d['status'] == 'warning':
                    lines.append('    ' + d['action'])
        elif name == "graphics" and details.get("renderer"):
            lines.append("  Renderer: " + details["renderer"])
        elif name == "video" and details.get("capabilities"):
            lines.extend(f'  {c["profile"]}: {c["entrypoint"]}' for c in details["capabilities"])
        elif name == "audio":
            for unit, service in details.get("services", {}).items():
                lines.append(f'  {unit}: {statuses[service["status"]]}')
            lines.append(f'  Изходи: {len(details["sinks"]) if details.get("sinks") is not None else "неизвестно"}; карти: {len(details["cards"]) if details.get("cards") is not None else "неизвестно"}')
            kinds = {"analog": "аналогов", "hdmi-displayport": "HDMI/DisplayPort", "digital": "цифров", "bluetooth": "Bluetooth", "usb": "USB", "virtual": "виртуален", "unknown": "неизвестен тип"}
            for sink in details.get("sinks") or []:
                default = "по подразбиране" if sink["default"] is True else "друг изход" if sink["default"] is False else "неизвестен изход по подразбиране"
                muted = "да" if sink["mute"] is True else "не" if sink["mute"] is False else "неизвестно"
                index = sink["index"] if sink["index"] is not None else "?"
                lines.append(f'  Изход #{index}: {kinds[sink["output_kind"]]}, {default}, {sink["state"]}; заглушен: {muted}')
        elif name == "bluetooth" and "powered" in details:
            lines.append("  Контролери: " + ", ".join("включен" if p is True else "изключен" if p is False else "неизвестно" for p in details["powered"]))
        elif name == "network":
            for link in details["links"]:
                lines.append(f'  {link["interface"]}: {link["state"]}')
            for addr in details["addresses"]:
                lines.append(f'  {addr["interface"]}: {addr["address"]}/{addr["prefixlen"]}')
            lines.append(f'  Маршрути по подразбиране: {len(details["default_routes"])}. Интернет: неизвестно (непроверен).')
        elif name == "firmware" and "firmware_error_lines" in details:
            lines.append(f'  Редове с firmware грешки: {details["firmware_error_lines"]}')
        elif name == "facter" and "only_saved" in details:
            lines.append("  Само в записания: " + (", ".join(details["only_saved"]) or "няма"))
            lines.append("  Само в текущия: " + (", ".join(details["only_current"]) or "няма"))
            lines.append("  Сравнени driver обвързвания: " + str(details["bindings_compared"]))
            for change in details["driver_changes"]:
                lines.append(f'  {change["address"]}: {change["saved_driver"]} → {change["current_driver"]}')
        if check.get('next_action'):
            lines.append('  Следващо действие: ' + check['next_action'])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Диагностика само за четене, без промени по системата.")
    parser.add_argument("--json", action="store_true", help="JSON вместо четим отчет")
    parser.add_argument("--output", metavar="FILE", help="Запиши JSON атомично с права 0600")
    parser.add_argument("--facter-report", metavar="FILE", help="Сравни съществуващ nixos-facter JSON (само PCI)")
    args = parser.parse_args(argv)
    report = collect_report(facter_report=args.facter_report)
    if args.output:
        try:
            _write_json(args.output, report)
        except (OSError, ValueError):
            print("Неуспешен запис: изисква се достъпен обикновен файл без символна връзка.", file=sys.stderr)
            return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _readable(report))
    return 0
