"""Optional RDP thin-client menu; no credentials are collected here."""
import copy

from .config import ConfigError, DEFAULTS, validate_machine


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


def choose(machine, q, ask):
    tc = machine['thin_client']
    while True:
        add = ask(q.confirm('Добавяне на RDP профил?', default=not tc['profiles']))
        if not add:
            break
        profile = {
            'name': ask(q.text('Име на профила (латиница):')).strip(),
            'host': ask(q.text('Windows хост (IP или име):')).strip(),
            'user': ask(q.text('Windows потребител:')).strip(),
            'port': 3389,
            'remote_apps': [],
        }
        port = ask(q.text('Порт (Enter = 3389):', default='3389')).strip()
        if port:
            try:
                profile['port'] = int(port)
            except ValueError:
                print('Портът трябва да е цяло число 1–65535.')
                continue
        apps = ask(q.text('RemoteApp (пълен път или alias, разделени със запетая; може празно):')).strip()
        if apps:
            profile['remote_apps'] = parse_remote_apps(apps)
        trial = copy.deepcopy(DEFAULTS)
        trial['disk'] = '/dev/disk/by-id/ata-EXAMPLE'
        trial['role'] = 'hybrid'
        trial['thin_client']['profiles'] = tc['profiles'] + [profile]
        try:
            validate_machine(trial)
        except ConfigError as error:
            print(str(error))
            continue
        tc['profiles'].append(profile)
    tc['credentials'] = ask(q.select('RDP парола:', choices=[
        q.Choice('Интерактивно (не се записва)', value='interactive'),
        q.Choice('sops-nix криптирана', value='sops'),
    ], default=tc['credentials']))
    tc['redirect'] = ask(q.checkbox('Пренасочване на устройства:', choices=[
        q.Choice('Смарткарта (КЕП)', value='smartcard', checked='smartcard' in tc['redirect']),
        q.Choice('Clipboard', value='clipboard', checked='clipboard' in tc['redirect']),
        q.Choice('Аудио', value='audio', checked='audio' in tc['redirect']),
        q.Choice('Локални дискове', value='drives', checked='drives' in tc['redirect']),
        q.Choice('USB', value='usb', checked='usb' in tc['redirect']),
    ]))
    return machine

