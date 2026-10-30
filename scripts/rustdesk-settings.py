"""Merge managed settings before RustDesk starts; never print credentials."""
import json
import os
from pathlib import Path
import sys
import tempfile
import toml


def apply(settings, directory, password_file=''):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    def merge(name, update):
        path = directory / name
        # Refuse redirected writes, including links to document files.
        if path.is_symlink():
            raise RuntimeError('RustDesk config must be a regular file')
        current = toml.loads(path.read_text()) if path.exists() else {}
        update(current)
        fd, temporary = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                toml.dump(current, stream)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    def options(c):
        c.setdefault('options', {}).update({
            'custom-rendezvous-server': settings['id_server'],
            'relay-server': settings['relay_server'],
            'key': settings['public_key'],
            'approve-mode': 'click' if settings['mode'] == 'consent' else 'password',
            'verification-method': 'use-temporary-password' if settings['mode'] == 'consent' else 'use-permanent-password',
        })
    # Require a usable secret before enabling password-only access.
    password = ''
    if settings['mode'] == 'unattended':
        password = Path(password_file).read_text().rstrip('\n')
        if len(password) < 12:
            raise RuntimeError('RustDesk password must have at least 12 characters')
    merge('RustDesk2.toml', options)
    merge('RustDesk.toml', lambda c: c.update(password=password))


if __name__ == '__main__':
    try:
        apply(json.loads(Path(sys.argv[1]).read_text()), Path.home()/'.config/rustdesk', sys.argv[2])
    except Exception:
        sys.exit('RustDesk preparation failed; check private config/secret. No credentials were logged.')
