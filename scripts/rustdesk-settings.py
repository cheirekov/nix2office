"""Prepare RustDesk 1.4.5 configs before the system dispatcher starts.

Secrets travel through a systemd credential or a pipe, never command arguments.
Writes to desktop/greeter homes happen only after dropping root privileges.
"""
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile

import toml


IDENTITY_DEFAULTS = {
    'id': '', 'enc_id': '', 'salt': '', 'key_pair': [[], []],
    'key_confirmed': False, 'keys_confirmed': {},
}


def private_directory(directory):
    directory = Path(os.path.abspath(directory))
    # Validate before creating anything below an existing component.
    for component in reversed((directory, *directory.parents)):
        if component.is_symlink():
            raise RuntimeError('RustDesk directory must not contain symlinks')
        if not component.exists():
            component.mkdir(mode=0o700)
        if not component.is_dir():
            raise RuntimeError('RustDesk config must be a directory')
    if directory.stat().st_uid != os.geteuid():
        raise RuntimeError('RustDesk config directory has the wrong owner')
    directory.chmod(0o700)
    return directory


def read_config(directory, name):
    path = Path(directory) / name
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid()):
        raise RuntimeError('RustDesk config must be a private regular file')
    return toml.loads(path.read_text())


def write_config(directory, name, current):
    fd, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            toml.dump(current, stream)
        os.replace(temporary, Path(directory) / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identity(config):
    result = {key: config.get(key, default) for key, default in IDENTITY_DEFAULTS.items()}
    for key in ('id', 'enc_id', 'salt'):
        if not isinstance(result[key], str):
            raise ValueError('Invalid RustDesk identity')
    pair = result['key_pair']
    if (not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(v, list) for v in pair)
            or any(type(b) is not int or not 0 <= b <= 255 for v in pair for b in v)
            or [len(v) for v in pair] not in ([0, 0], [64, 32])):
        raise ValueError('Invalid RustDesk signing key')
    if type(result['key_confirmed']) is not bool or not isinstance(result['keys_confirmed'], dict):
        raise ValueError('Invalid RustDesk key confirmation')
    return result


def password_value(settings, password_file):
    if settings['mode'] == 'consent':
        return ''
    password = Path(password_file).read_text().rstrip('\n')
    # RustDesk's ENCRYPT_MAX_LEN is 128 Unicode characters.
    if not 12 <= len(password) <= 128 or any(c in password for c in '\n\r\0'):
        raise ValueError('RustDesk password must have 12 through 128 characters')
    return password


def apply(settings, directory, password_file='', *, shared_identity=None, password=None):
    if settings['mode'] == 'off':
        return
    if settings['mode'] not in ('consent', 'unattended'):
        raise ValueError('Invalid RustDesk mode')
    # Validate the secret before changing either access settings or identity.
    if password is None:
        password = password_value(settings, password_file)
    elif settings['mode'] == 'consent':
        password = ''
    elif not 12 <= len(password) <= 128 or any(c in password for c in '\n\r\0'):
        raise ValueError('Invalid RustDesk password')
    directory = private_directory(directory)
    main = read_config(directory, 'RustDesk.toml')
    network = read_config(directory, 'RustDesk2.toml')
    if shared_identity is not None:
        main.update(identity(shared_identity))
    main['password'] = password
    network.setdefault('options', {}).update({
        'custom-rendezvous-server': settings['id_server'],
        'relay-server': settings['relay_server'],
        'key': settings['public_key'],
        'approve-mode': 'click' if settings['mode'] == 'consent' else 'password',
        'verification-method': ('use-temporary-password' if settings['mode'] == 'consent'
                                else 'use-permanent-password'),
        'stop-service': '',
    })
    # Both documents are parsed and checked before either is replaced.
    write_config(directory, 'RustDesk.toml', main)
    write_config(directory, 'RustDesk2.toml', network)


def as_user(action, username, payload=None):
    account = pwd.getpwnam(username)
    # The system service always takes the root branch. Allow the same-user
    # preparation smoke test without attempting privileged setgroups(2).
    if os.geteuid() == 0:
        privileges = dict(user=account.pw_uid, group=account.pw_gid, extra_groups=[])
    elif account.pw_uid == os.geteuid():
        privileges = {}
    else:
        raise PermissionError('Root is required to prepare another account')
    # A fresh environment avoids sudo -E/XDG_CONFIG_HOME selecting root's config.
    command = [sys.executable, str(Path(__file__).resolve()), '--child', action,
               str(Path(account.pw_dir) / '.config/rustdesk')]
    result = subprocess.run(
        command, input=json.dumps(payload) if payload is not None else '',
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        **privileges, cwd='/',
        env={'HOME': account.pw_dir, 'PATH': os.defpath}, timeout=30,
    )
    return json.loads(result.stdout) if action == 'identity' else None


def prepare_system(settings, directory, password_file, binary, usernames):
    if settings['mode'] == 'off':
        return
    password = password_value(settings, password_file)
    directory = private_directory(directory)
    root_identity = identity(read_config(directory, 'RustDesk.toml'))
    if not (root_identity['id'] or root_identity['enc_id']):
        # Preserve the office user's established identity when upgrading from tray-only.
        previous = as_user('identity', usernames[0])
        if previous.get('id') or previous.get('enc_id'):
            root_identity = identity(previous)
    apply(settings, directory, shared_identity=root_identity, password=password)
    if not (root_identity['id'] or root_identity['enc_id']):
        # Let the pinned RustDesk binary generate its own ID format, not a guessed ID.
        subprocess.run([binary, '--get-id'], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        root_identity = identity(read_config(directory, 'RustDesk.toml'))
        if not (root_identity['id'] or root_identity['enc_id']):
            raise RuntimeError('RustDesk did not initialize its identity')
    if not root_identity['key_pair'][0]:
        # Same libsodium Ed25519 primitive and (secret, public) byte vectors as
        # hbb_common Config::get_key_pair(), needed for its is_empty()/IPC sync.
        from nacl.bindings import crypto_sign_keypair
        public, secret = crypto_sign_keypair()
        root_identity['key_pair'] = [list(secret), list(public)]
    apply(settings, directory, shared_identity=root_identity, password=password)
    for username in usernames:
        as_user('apply', username, {
            'settings': settings, 'identity': root_identity, 'password': password,
        })


def main():
    if sys.argv[1] == '--child':
        action, directory = sys.argv[2:4]
        if action == 'identity':
            # Do not create an old profile just to inspect it.
            if not Path(directory).exists():
                print('{}')
                return
            private_directory(directory)
            print(json.dumps(identity(read_config(directory, 'RustDesk.toml'))))
        elif action == 'apply':
            data = json.load(sys.stdin)
            apply(data['settings'], directory, shared_identity=data['identity'],
                  password=data['password'])
        else:
            raise ValueError('Unknown RustDesk preparation action')
    elif sys.argv[1] == '--system':
        settings_file, directory, password_file, binary, *usernames = sys.argv[2:]
        prepare_system(json.loads(Path(settings_file).read_text()), directory,
                       password_file, binary, usernames)
    else:
        apply(json.loads(Path(sys.argv[1]).read_text()),
              Path.home() / '.config/rustdesk', sys.argv[2])


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.exit('RustDesk preparation failed; check private config/secret. No credentials were logged.')
