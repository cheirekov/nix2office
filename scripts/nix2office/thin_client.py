"""Configure the selected kiosk connections and RDP settings."""
from .config import (
    AWS_WORKSPACES_PROFILE, ConfigError, KEP_PROVIDERS, KIOSK_CLIENTS,
    kiosk_client_names, text, validate_connection_name, validate_portal_url,
)


def parse_remote_apps(text):
    """Comma-separated RemoteApp entries; spaces are kept and quotes are optional."""
    entries = []
    for part in text.split(','):
        entry = part.strip()
        if len(entry) >= 2 and entry[0] == entry[-1] and entry[0] in ('"', "'"):
            entry = entry[1:-1].strip()
        if entry:
            entries.append(entry)
    return entries


def _field(q, ask, label, check, default=""):
    def valid(value):
        try:
            check(value.strip())
        except ConfigError as error:
            return str(error)
        return True

    return ask(q.text(label, default=default, validate=valid)).strip()


def _required_text(value, label):
    if not text(value, label):
        raise ConfigError(f"{label} е задължително поле.")


def _rdp_host(value):
    _required_text(value, "Windows хост")
    if any(char.isspace() for char in value):
        raise ConfigError("Въведи IP адрес или име на хост, без интервали.")


def _rdp_port(value):
    if value and (not value.isascii() or not value.isdecimal() or len(value) > 5
                  or not 1 <= int(value) <= 65535):
        raise ConfigError("Портът трябва да е цяло число от 1 до 65535.")


def _add_rdp_profiles(tc, names, q, ask, *, required):
    while (required and not tc["profiles"]) or ask(q.confirm(
        f'Добави още един RDP профил ({len(tc["profiles"]) + 1})?' if required and tc["profiles"]
        else "Добавяне на RDP профил?",
        default=not tc["profiles"],
    )):
        prefix = f'RDP {len(tc["profiles"]) + 1} · ' if required else ""
        name = _field(q, ask, f"{prefix}Име на профила (латиница):",
                      lambda value: validate_connection_name(value, names))
        host = _field(q, ask, f"{prefix}Windows хост (IP или име):", _rdp_host)
        user = _field(q, ask, f"{prefix}Windows потребител:",
                      lambda value: _required_text(value, "Windows потребител"))
        port = _field(q, ask, f"{prefix}Порт (Enter = 3389):", _rdp_port, "3389")
        apps = ask(q.text(f"{prefix}RemoteApp (пълен път или alias, разделени със запетая; може празно):"))
        tc["profiles"].append({
            "name": name, "host": host, "user": user, "port": int(port or "3389"),
            "remote_apps": parse_remote_apps(apps),
        })
        names.add(name)


def _add_portals(tc, names, q, ask):
    while not tc["portals"] or ask(q.confirm(
        f'Добави още един HTTPS портал ({len(tc["portals"]) + 1})?', default=False,
    )):
        prefix = f'HTTPS {len(tc["portals"]) + 1}'
        name = _field(q, ask, f"{prefix} · Име на портала (латиница):",
                      lambda value: validate_connection_name(value, names))
        url = _field(q, ask, f"{prefix} · Адрес на портала (https://…):", validate_portal_url)
        tc["portals"].append({"name": name, "url": url})
        names.add(name)


def _choose_kiosk_startup(tc, q, ask):
    tc["startup"] = ask(q.select("При вход в киоска:", choices=[
        q.Choice("Покажи менюто за връзки", value="menu"),
        q.Choice("Отвори избрана връзка автоматично", value="auto"),
    ], default="menu"))
    tc["startup_profile"] = ""
    if tc["startup"] == "auto":
        choices = [
            q.Choice(f'{label} — {profile["name"]}', value=profile["name"])
            for label, profiles in (("RDP", tc["profiles"]), ("HTTPS", tc["portals"]))
            for profile in profiles
        ] + [
            q.Choice(KIOSK_CLIENTS[name]["label"], value=name)
            for name in kiosk_client_names(tc)
        ]
        tc["startup_profile"] = choices[0].value if len(choices) == 1 else ask(q.select(
            "Коя връзка да се отвори автоматично?", choices=choices,
        ))


def choose(machine, q, ask):
    tc = machine["thin_client"]
    is_kiosk = machine["role"] == "thin"
    names = {profile["name"] for profile in tc["profiles"] + tc["portals"]}
    if is_kiosk:
        enabled = kiosk_client_names(tc)
        choices = [
            q.Choice("Директен RDP към Windows (FreeRDP)", value="rdp", checked=bool(tc["profiles"]) or not (tc["portals"] or enabled)),
            q.Choice("HTTPS портал", value="https", checked=bool(tc["portals"])),
        ] + [
            q.Choice(client["label"], value=name, checked=name in enabled)
            for name, client in KIOSK_CLIENTS.items()
        ]
        selected = ask(q.checkbox(
            "Връзки на киоска (Space избира, Enter продължава):", choices=choices,
            validate=lambda values: bool(values) or "Избери поне един вид връзка.",
        ))
        tc["aws_workspaces"] = AWS_WORKSPACES_PROFILE in selected
        tc["native_clients"] = [name for name in selected if name in KIOSK_CLIENTS and name != AWS_WORKSPACES_PROFILE]
        if "rdp" not in selected:
            tc["profiles"] = []
            tc["redirect"] = []
        if "https" not in selected:
            tc["portals"] = []
        names = {profile["name"] for profile in tc["profiles"] + tc["portals"]}
        names.update(kiosk_client_names(tc))
        if "rdp" in selected:
            _add_rdp_profiles(tc, names, q, ask, required=True)
            _choose_rdp_settings(tc, q, ask, is_kiosk=True)
        if "https" in selected:
            _add_portals(tc, names, q, ask)
        _choose_kiosk_startup(tc, q, ask)
    else:
        _add_rdp_profiles(tc, names, q, ask, required=False)
        _choose_rdp_settings(tc, q, ask, is_kiosk=False)
        tc["native_clients"] = ask(q.checkbox(
            "Допълнителни клиенти за отдалечени връзки (Space избира):",
            choices=[
                q.Choice(client["label"], value=name, checked=name in tc["native_clients"])
                for name, client in KIOSK_CLIENTS.items() if client.get("hybrid")
            ],
        ))
    return machine


def _choose_rdp_settings(tc, q, ask, *, is_kiosk):
    tc['credentials'] = ask(q.select('RDP парола:', choices=[
        q.Choice('Интерактивно (не се записва)', value='interactive'),
        q.Choice('sops-nix криптирана', value='sops'),
    ], default=tc['credentials']))
    tc['allow_other_account'] = ask(q.confirm(
        'Разреши „Вход с друг акаунт“ за готовите RDP профили?',
        default=tc['allow_other_account'],
    ))
    tc['allow_personal_connections'] = ask(q.confirm(
        'Разреши добавяне и редактиране на лични RDP връзки?',
        default=tc['allow_personal_connections'],
    ))
    if is_kiosk:
        tc['usb_storage'] = ask(q.confirm(
            'USB флашки в Windows RDP? Флашките са само за четене.',
            default=tc['usb_storage'],
        ))
        use_kep = ask(q.confirm('Ще се използва ли КЕП през Windows RDP?', default=bool(tc['kep_provider'])))
        tc['kep_provider'] = ask(q.select('Доставчик на КЕП:', choices=[
            q.Choice(label, value=provider) for provider, label in KEP_PROVIDERS.items()
        ], default=tc['kep_provider'] or 'unspecified')) if use_kep else ''
    redirects = [
        q.Choice('Clipboard', value='clipboard', checked='clipboard' in tc['redirect']),
        q.Choice('Аудио', value='audio', checked='audio' in tc['redirect']),
        q.Choice('Папка Shared', value='drives', checked='drives' in tc['redirect']),
        q.Choice('USB', value='usb', checked='usb' in tc['redirect']),
    ]
    if is_kiosk:
        print('Папката Shared е постоянно достъпна през RDP.')
        redirects = [choice for choice in redirects
                     if choice.value != 'drives' and (not tc['usb_storage'] or choice.value != 'usb')]
    if is_kiosk:
        devices = ask(q.checkbox('Пренасочване на устройства:', choices=redirects))
        tc['redirect'] = (['smartcard'] if tc['kep_provider'] else []) + devices
    else:
        redirects.insert(0, q.Choice('Смарткарта (КЕП)', value='smartcard', checked='smartcard' in tc['redirect']))
        tc['redirect'] = ask(q.checkbox('Пренасочване на устройства:', choices=redirects))
    tc['fullscreen'] = ask(q.confirm('Пълен екран за RDP сесията?', default=is_kiosk))
    if any(profile.get('remote_apps') for profile in tc['profiles']):
        tc['unicode_keyboard'] = ask(q.confirm(
            'RemoteApp: Unicode вход от локалната подредба (Alt+Shift за BG/EN)?',
            default=True,
        ))
