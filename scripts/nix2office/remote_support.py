"""Optional remote support menu; credentials are collected only during preparation."""
def choose(machine, q, ask):
    r = machine['remote_support']
    r['mode'] = ask(q.select('RustDesk — отдалечена поддръжка:', choices=[q.Choice('Изключено', value='off'), q.Choice('С потвърждение от потребителя', value='consent'), q.Choice('Без присъствие (след рестарт и на екрана за вход)', value='unattended')], default=r['mode']))
    if r['mode'] != 'off':
        r['id_server'] = ask(q.text('ID server (hbbs), host или host:port:', default=r['id_server'])).strip()
        r['relay_server'] = ask(q.text('Relay server (hbbr):', default=r['relay_server'] or r['id_server'])).strip()
        r['public_key'] = ask(q.text('Публичен server key (id_ed25519.pub):', default=r['public_key'])).strip()
    return machine
