"""Interactive terminal menus; no system changes are made here."""
import copy
import json
from pathlib import Path

from .config import CATALOG, ConfigError, DEFAULTS, validate_machine, validate_public_key
from .deployment import PreparationError, check_destination, summary
from .ssh_keys import choose_public_key
from .hardware import describe_inventory, eligible_disks, machine_hardware, probe


class Cancelled(Exception):
    pass


def load_inventory(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        required = ("architecture", "cpu", "cpu_vendor", "memory_mib", "threads", "boot_mode", "initrd_modules", "disks")
        if not isinstance(value, dict) or not all(key in value for key in required):
            raise ValueError
        # Validate facts before using them as defaults or menu entries.
        validate_machine({"disk": "/dev/disk/by-id/ata-EXAMPLE", "hardware": machine_hardware(value)})
        if not isinstance(value["architecture"], str) or not isinstance(value["disks"], list):
            raise ValueError
        for d in value["disks"]:
            if not isinstance(d, dict) or not isinstance(d["by_id"], list):
                raise ValueError
            for disk in d["by_id"]:
                validate_machine({"disk": disk})
            if type(d["size_bytes"]) is not int or d["size_bytes"] < 0:
                raise ValueError
            for k in ("model", "transport", "name"):
                if not isinstance(d[k], str) or any(ord(c) < 32 or ord(c) == 127 for c in d[k]):
                    raise ValueError
            for k in ("read_only", "rotational"):
                if type(d[k]) is not bool:
                    raise ValueError
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise ConfigError("Invalid hardware JSON; use an inventory produced by --probe.") from None


def wizard(args):
    try:
        import questionary as q
    except ImportError:
        raise PreparationError("Interactive menus need questionary. Use nix run .#configure or nix develop.") from None

    def ask(question):
        answer = question.ask()
        if answer is None:
            raise Cancelled
        return answer

    def select(message, items, default):
        return ask(q.select(message, choices=[q.Choice(label, value=value) for value, label in items], default=default))

    def field(message, default="", section=None, key=None):
        def valid(value):
            if key is None:
                return True
            trial = copy.deepcopy(DEFAULTS)
            trial["disk"] = "/dev/disk/by-id/ata-EXAMPLE"
            if section:
                trial[section][key] = value.strip()
            else:
                trial[key] = value.strip()
            try:
                validate_machine(trial)
                return True
            except ConfigError as error:
                return str(error)
        return ask(q.text(message, default=default, validate=valid)).strip()

    m = copy.deepcopy(DEFAULTS)
    dest = check_destination(args.output)
    print("\nNix2office — подготовка на конфигурация. Стрелки за избор, Enter за потвърждение, Ctrl+C за отказ.")
    print("Първо избираме чий хардуер проверяваме; административният компютър може да е различен.\n")
    inventory = None
    if args.hardware_json:
        inventory = load_inventory(args.hardware_json)
    elif args.target is not None:
        inventory = probe(args.target, args.ssh_config, args.ssh_socket)
    else:
        method = select("Хардуер на офис машината:", [
            ("ssh", "Отдалечена машина през вече доверен SSH достъп"),
            ("local", "Този компютър (тук ще се инсталира NixOS)"),
            ("json", "Запазен JSON от --probe"),
            ("manual", "Ръчно, без автоматична препоръка"),
        ], "ssh")
        if method == "ssh":
            inventory = probe(field("SSH alias или user@host:"), args.ssh_config, args.ssh_socket)
        elif method == "local":
            inventory = probe()
        elif method == "json":
            inventory = load_inventory(Path(field("Път до hardware.json:")).expanduser())
    if inventory:
        if inventory["architecture"] != "x86_64":
            raise ConfigError("This profile currently supports x86_64 Linux only (including its LibreOffice language pack).")
        advice = describe_inventory(inventory)
        m["hardware"] = machine_hardware(inventory)
        m["profile"] = advice["profile"]
        m["performance"]["cpu_governor"] = advice["cpu_governor"]
        m["boot_mode"] = inventory["boot_mode"] if inventory["boot_mode"] in ("bios", "uefi") else "bios"
    if inventory and not inventory.get("bluetooth_detected"):
        m["devices"]["bluetooth"] = False
        print("Bluetooth: не е открит адаптер; BlueZ/Blueman остават изключени. Може да се включат по-късно в machine.toml.")
    else:
        m["devices"]["bluetooth"] = ask(q.confirm("Открит Bluetooth: включване на BlueZ + Blueman?" if inventory else "Bluetooth + Blueman (няма хардуерна проверка)?", default=bool(inventory)))
    m["devices"]["unfree_firmware"] = ask(q.confirm("Допълнителен unfree firmware? Redistributable firmware вече е включен.", default=False))
    m["profile"] = select("Начален профил (пакетите остават избираеми):", [
        ("light", "Light — Firefox ESR, LibreOffice, PDF Arranger"),
        ("standard", "Standard — същите + Xournal++ за PDF бележки"),
    ], m["profile"])
    m["apps"]["pdf_editor"] = "pdfarranger" if m["profile"] == "light" else "both"
    governors = [("auto", "Автоматично — запази избора на ядрото")]
    recommended = m["performance"]["cpu_governor"]
    if recommended != "auto":
        governors.insert(0, (recommended, f"Балансирано — {recommended} (препоръчано за открития драйвер)"))
    if inventory and "performance" in inventory.get("frequency_governors", []):
        governors.append(("performance", "Performance — висока заявена честота; повече консумация и топлина"))
    m["performance"]["cpu_governor"] = select("CPU режим (не е овърклок):", governors, recommended)
    disks = eligible_disks(inventory) if inventory else []
    if disks:
        choices = [(d["by_id"][0], f'{d["model"]} | {d["size_bytes"] / 2**30:.1f} GiB | {"HDD" if d["rotational"] else "SSD/flash"} | {d["by_id"][0]}') for d in disks]
        m["disk"] = select("Вътрешен диск (сега НЕ се форматира):", choices, choices[0][0])
    else:
        m["disk"] = field("Цял вътрешен диск /dev/disk/by-id/... (без USB/partition):", key="disk")
    probed_boot = inventory["boot_mode"] if inventory else None
    m["boot_mode"] = select("Начин на зареждане:", [("bios", "Legacy BIOS — GRUB"), ("uefi", "UEFI — systemd-boot")], m["boot_mode"])
    if probed_boot in ("bios", "uefi") and m["boot_mode"] != probed_boot:
        raise ConfigError(f"Rescue работи в {probed_boot}, а изборът е {m['boot_mode']}. Рестартирай USB в избрания режим и повтори подготовката.")
    m["hostname"] = field("Име на компютъра:", m["hostname"], key="hostname")
    m["user"]["name"] = field("Потребителско име за вход (латиница):", "maria", "user", "name")
    m["user"]["full_name"] = field("Име за показване (може на кирилица):", "Мария Димитрова", "user", "full_name")
    m["user"]["email"] = field("E-mail (незадължителен, само метаданни):", section="user", key="email")
    m["apps"]["browser"] = select("Браузър по подразбиране:", [
        ("firefox-esr", "Firefox ESR — препоръчан начален избор"),
        ("chromium", "Chromium"), ("brave", "Brave"),
        ("google-chrome", "Google Chrome — proprietary/unfree"),
    ], m["apps"]["browser"])
    office = select("Офис приложения (избери пакет или комбинация):", [
        ("libreoffice", "LibreOffice — български интерфейс, Tabbed, Writer/Calc/Impress/Draw"),
        ("onlyoffice", "ONLYOFFICE Desktop Editors — документи, таблици, презентации"),
        ("artcraft", "ArtCraft — WordCraft, DeckCraft, GridCraft, PdfCraft (експериментален)"),
        ("libreoffice+artcraft", "LibreOffice + ArtCraft (експериментален)"),
        ("onlyoffice+artcraft", "ONLYOFFICE + ArtCraft (експериментален)"),
        ("none", "Без офис пакет"),
    ], m["apps"]["office"])
    m["apps"]["artcraft"] = "artcraft" in office.split("+")
    m["apps"]["office"] = "none" if office == "artcraft" else office.split("+")[0]
    m["apps"]["pdf_editor"] = select("PDF инструменти (Atril четецът винаги е включен):", [
        ("none", "Без допълнителен PDF редактор"),
        ("pdfarranger", "PDF Arranger — подреждане, разделяне и събиране на страници"),
        ("xournalpp", "Xournal++ — писане и бележки върху PDF"),
        ("both", "PDF Arranger + Xournal++"),
    ], m["apps"]["pdf_editor"])
    m["apps"]["extra"] = ask(q.checkbox("Допълнителни програми (Space за избор; може без отметки):", choices=[q.Choice(v["label"], value=k) for k, v in CATALOG.items()]))
    from .remote_support import choose
    choose(m, q, ask)
    m["tools"]["comma"] = ask(q.confirm("Comma — временни програми с готов малък индекс (отделен фиксиран nixpkgs)?", default=False))
    m["fonts"]["office_fallbacks"] = ask(q.confirm("Carlito/Caladea — съвместими заместители за Calibri/Cambria?", default=True))
    m["fonts"]["microsoft_core"] = ask(q.confirm("Microsoft Core Fonts — Times New Roman, Arial и др. (unfree, със собствен лиценз)?", default=False))
    m["apps"]["nextcloud"] = ask(q.confirm("Nextcloud клиент с автоматично стартиране?", default=True))
    m["keyboard"]["bulgarian"] = select("Българска клавиатура (плюс английска):", [("phonetic", "Фонетична"), ("bds", "БДС")], "phonetic")
    m["boot_splash"] = ask(q.confirm("Графичен splash при зареждане?", default=True))
    m["sharing"]["workgroup"] = field("Windows Workgroup:", "WORKGROUP", "sharing", "workgroup")
    m["sharing"]["mode"] = select("Windows папки:", [("client", "Достъп до папки на други машини"), ("both", "Достъп + споделяне на собствена папка с парола")], "client")
    if m["sharing"]["mode"] == "both":
        m["sharing"]["folder"] = field("Име на споделена папка в Home (латиница):", "Shared", "sharing", "folder")
        m["sharing"]["network"] = field("IPv4 достъп до SMB: мрежа (172.16.16.0/24), IP/32 или всички IPv4 (0.0.0.0/0):", section="sharing", key="network")
        m["sharing"]["read_only"] = ask(q.confirm("Споделената папка само за четене?", default=False))
        print("След инсталация admin задава отделна SMB парола: sudo smbpasswd -a " + m["user"]["name"])
    enabled = ask(q.checkbox("VPN инструменти (Space включва/изключва; може без отметки; добавят се и по-късно с rebuild):", choices=[
        q.Choice("WireGuard — NetworkManager import", value="wireguard", checked=True),
        q.Choice("Tailscale — отделна услуга + Trayscale GUI", value="tailscale"),
        q.Choice("ZeroTier — отделна услуга; настройка през admin/CLI", value="zerotier"),
    ]))
    for name in ("wireguard", "tailscale", "zerotier"):
        m["vpn"][name] = name in enabled
    if m["vpn"]["zerotier"]:
        m["vpn"]["zerotier_networks"] = field("ZeroTier network IDs, разделени с интервал (може празно):").replace(",", " ").split()
    if ask(q.confirm("Да включа SSH за admin само с публичен ключ?", default=True)):
        m["admin"]["ssh_public_key"] = choose_public_key(ask, select, field)
        access = select("Откъде да е разрешен SSH достъпът за admin?", [
            ("cidr", "Задавам IPv4 мрежа или един IP с /32"),
            ("any", "Отвсякъде — всички IPv4 (0.0.0.0/0)"),
        ], "cidr")
        m["admin"]["network"] = "0.0.0.0/0" if access == "any" else field("IPv4 CIDR за SSH (напр. 192.168.1.0/24 или 203.0.113.10/32):", m["sharing"]["network"] if m["sharing"]["mode"] == "both" else "", "admin", "network")
    else:
        print("SSH ще е ИЗКЛЮЧЕН след инсталация. Admin ще влиза от локалната конзола.")
        if not ask(q.confirm("Продължавам без отдалечен SSH достъп?", default=False)):
            raise Cancelled
    generated = args.generate_passwords or select("Първоначални пароли за потребителя и admin:", [
        (False, "Въвеждам ги скрито в терминала; не се записват като текст"),
        (True, "Генерирай случайни; само локално в credentials.json (0600)"),
    ], False)
    m = validate_machine(m)
    print("\nПреглед преди подготовка:")
    summary(m)
    print(f"Локална директория: {dest}")
    if not ask(q.confirm("Да подготвя частния flake и SOPS тайните? Дискът не се променя.", default=True)):
        raise Cancelled
    return m, dest, generated
