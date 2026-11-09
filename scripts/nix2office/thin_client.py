"""Optional RDP thin-client menu; no credentials are collected here."""
import copy

from .config import ConfigError, DEFAULTS, validate_machine


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
        apps = ask(q.text('RemoteApp alias-и (разделени със запетая; може празно):')).strip()
        if apps:
            profile['remote_apps'] = [a.strip() for a in apps.replace(',', ' ').split() if a.strip()]
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

