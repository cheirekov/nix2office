"""Optional remote support menu; credentials are collected only during preparation."""
import copy
from .config import ConfigError, DEFAULTS, validate_machine


def choose(machine, q, ask):
    r = machine['remote_support']
    r['mode'] = ask(q.select('RustDesk — отдалечена поддръжка:', choices=[q.Choice('Изключено', value='off'), q.Choice('С потвърждение от потребителя', value='consent'), q.Choice('Без присъствие (след рестарт и на екрана за вход)', value='unattended')], default=r['mode']))
    if r['mode'] != 'off':
        def valid(key):
            def check(value):
                trial = copy.deepcopy(DEFAULTS)
                trial['disk'] = '/dev/disk/by-id/ata-EXAMPLE'
                trial['remote_support'][key] = value.strip()
                if not value.strip():
                    return 'Полето е задължително за включен RustDesk.'
                try:
                    validate_machine(trial)
                    return True
                except ConfigError as error:
                    return str(error)
            return check
        r['id_server'] = ask(q.text('ID server (hbbs), host или host:port:', default=r['id_server'], validate=valid('id_server'))).strip()
        r['relay_server'] = ask(q.text('Relay server (hbbr):', default=r['relay_server'] or r['id_server'], validate=valid('relay_server'))).strip()
        r['public_key'] = ask(q.text('Публичен server key (id_ed25519.pub):', default=r['public_key'], validate=valid('public_key'))).strip()
    return machine
