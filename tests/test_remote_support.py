import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import toml
from nacl.bindings import crypto_sign_keypair, crypto_sign, crypto_sign_open
from nix2office.config import validate_machine, ConfigError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rd', ROOT / 'scripts/rustdesk-settings.py')
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)

SETTINGS = dict(mode='unattended', id_server='example.org', relay_server='example.org', public_key='test')
PASSWORD = 'TEST_ONLY_LONG_PASSWORD'


def existing_identity(client_id='123456789'):
    public, secret = crypto_sign_keypair()
    return dict(id=client_id, enc_id='', salt='existing-salt', key_pair=[list(secret), list(public)],
                key_confirmed=True, keys_confirmed={'example.org': True})


class RemoteSupportTests(unittest.TestCase):
    def test_merge_and_clear_password(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / 'config'
            secret = root / 'secret'
            secret.write_text(PASSWORD)
            rd.apply(SETTINGS, cfg, str(secret))
            self.assertEqual(toml.load(cfg / 'RustDesk.toml')['password'], PASSWORD)
            c = toml.load(cfg / 'RustDesk.toml')
            c['id'] = '123'
            (cfg / 'RustDesk.toml').write_text(toml.dumps(c))
            c2 = toml.load(cfg / 'RustDesk2.toml')
            c2['options']['unmanaged-setting'] = 'keep'
            c2['options']['stop-service'] = 'Y'
            (cfg / 'RustDesk2.toml').write_text(toml.dumps(c2))
            rd.apply(dict(SETTINGS, mode='consent'), cfg)
            self.assertEqual(toml.load(cfg / 'RustDesk.toml'), dict(id='123', password=''))
            options = toml.load(cfg / 'RustDesk2.toml')['options']
            self.assertEqual(options['approve-mode'], 'click')
            self.assertEqual(options['verification-method'], 'use-temporary-password')
            self.assertEqual(options['stop-service'], '')
            self.assertEqual(options['unmanaged-setting'], 'keep')
            self.assertEqual(cfg.stat().st_mode & 0o777, 0o700)
            for file in cfg.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_off_does_not_read_secret_or_create_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'absent'
            rd.apply(dict(mode='off'), cfg, '/missing')
            rd.prepare_system(dict(mode='off'), cfg, '/missing', '/missing', [])
            self.assertFalse(cfg.exists())

    def test_missing_or_invalid_secret_preserves_existing_configs(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'config'
            rd.apply(dict(SETTINGS, mode='consent'), cfg)
            before = {p.name: p.read_bytes() for p in cfg.iterdir()}
            with self.assertRaises(FileNotFoundError):
                rd.apply(SETTINGS, cfg, str(Path(d) / 'missing'))
            secret = Path(d) / 'secret'
            for value in ('short', 'a' * 129, 'TEST_ONLY_LONG\nPASSWORD', 'TEST_ONLY_LONG\rPASSWORD', 'a' * 12 + '\0'):
                secret.write_text(value)
                with self.subTest(value_length=len(value)), self.assertRaises(ValueError):
                    rd.apply(SETTINGS, cfg, str(secret))
                self.assertEqual({p.name: p.read_bytes() for p in cfg.iterdir()}, before)
            secret.write_text('a' * 128 + '\n')
            rd.apply(SETTINGS, cfg, str(secret))
            self.assertEqual(toml.load(cfg / 'RustDesk.toml')['password'], 'a' * 128)

    def test_reject_redirected_or_nonregular_config_before_any_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / 'documents'
            target.mkdir()
            (root / 'linked').symlink_to(target, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                rd.apply(dict(SETTINGS, mode='consent'), root / 'linked' / 'config')
            self.assertEqual(list(target.iterdir()), [])
            cfg = root / 'config'
            rd.apply(dict(SETTINGS, mode='consent'), cfg)
            original = (cfg / 'RustDesk.toml').read_bytes()
            (cfg / 'RustDesk2.toml').unlink()
            for kind in ('symlink', 'hardlink', 'fifo'):
                with self.subTest(kind=kind):
                    path = cfg / 'RustDesk2.toml'
                    if kind == 'symlink':
                        path.symlink_to(cfg / 'RustDesk.toml')
                    elif kind == 'hardlink':
                        os.link(cfg / 'RustDesk.toml', path)
                    else:
                        os.mkfifo(path)
                    with self.assertRaises(RuntimeError):
                        rd.apply(SETTINGS, cfg, password=PASSWORD)
                    self.assertEqual((cfg / 'RustDesk.toml').read_bytes(), original)
                    path.unlink()

    def test_accounts_share_identity_and_modes_before_daemon_start(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            accounts = {name: root / name for name in ('office', 'lightdm')}
            previous = existing_identity()
            rd.apply(SETTINGS, accounts['office'], shared_identity=previous, password=PASSWORD)
            rd.apply(SETTINGS, accounts['lightdm'], shared_identity=existing_identity('999'), password=PASSWORD)

            def local_account(action, username, payload=None):
                cfg = accounts[username]
                if action == 'identity':
                    return rd.identity(toml.load(cfg / 'RustDesk.toml'))
                rd.apply(payload['settings'], cfg, shared_identity=payload['identity'], password=payload['password'])

            with patch.object(rd, 'as_user', side_effect=local_account), patch.object(rd.subprocess, 'run') as native:
                for mode in ('consent', 'unattended', 'consent'):
                    settings = dict(SETTINGS, mode=mode)
                    secret = root / 'credential'
                    secret.write_text(PASSWORD)
                    rd.prepare_system(settings, root / 'root', str(secret), '/unused', list(accounts))
                    for cfg in [root / 'root', *accounts.values()]:
                        main = toml.load(cfg / 'RustDesk.toml')
                        self.assertEqual(rd.identity(main), previous)
                        self.assertEqual(main['password'], PASSWORD if mode == 'unattended' else '')
                        options = toml.load(cfg / 'RustDesk2.toml')['options']
                        self.assertEqual(options['approve-mode'], 'password' if mode == 'unattended' else 'click')
                        self.assertEqual(options['verification-method'], 'use-permanent-password' if mode == 'unattended' else 'use-temporary-password')
                        self.assertEqual(options['custom-rendezvous-server'], SETTINGS['id_server'])
                        self.assertEqual(options['key'], SETTINGS['public_key'])
                native.assert_not_called()

    def test_new_root_identity_uses_native_id_and_libsodium_key_format(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'root'

            def initialize(argv, **kwargs):
                self.assertEqual(argv, ['/test/rustdesk', '--get-id'])
                main = toml.load(cfg / 'RustDesk.toml')
                main.update(id='123456789')
                (cfg / 'RustDesk.toml').write_text(toml.dumps(main))

            with patch.object(rd, 'as_user', return_value={}) as account, patch.object(rd.subprocess, 'run', side_effect=initialize):
                rd.prepare_system(dict(SETTINGS, mode='consent'), cfg, '', '/test/rustdesk', ['office', 'lightdm'])
                identity = rd.identity(toml.load(cfg / 'RustDesk.toml'))
                secret, public = map(bytes, identity['key_pair'])
                self.assertEqual(crypto_sign_open(crypto_sign(b'test', secret), public), b'test')
                for call in account.call_args_list[1:]:
                    self.assertEqual(call.args[2]['identity'], identity)

    def test_as_user_payload_uses_pipe_and_drops_groups(self):
        account = pwd.getpwuid(os.geteuid())
        with patch.object(rd.pwd, 'getpwnam', return_value=account), patch.object(rd.os, 'geteuid', return_value=0), patch.object(rd.subprocess, 'run') as run:
            rd.as_user('apply', account.pw_name, {'password': PASSWORD})
            argv = run.call_args.args[0]
            kwargs = run.call_args.kwargs
            self.assertNotIn(PASSWORD, ' '.join(argv))
            self.assertEqual(json.loads(kwargs['input'])['password'], PASSWORD)
            self.assertEqual(kwargs['user'], account.pw_uid)
            self.assertEqual(kwargs['group'], account.pw_gid)
            self.assertEqual(kwargs['extra_groups'], [])
            self.assertNotIn('PYTHONPATH', kwargs['env'])
            self.assertNotIn('XDG_CONFIG_HOME', kwargs['env'])

    def test_real_child_in_pinned_python_with_clean_environment(self):
        # Exercise the actual interpreter, imports and child CLI; no root or account edits.
        with tempfile.TemporaryDirectory() as d:
            values = list(pwd.getpwuid(os.geteuid()))
            values[5] = d
            account = pwd.struct_passwd(values)
            payload = dict(settings=dict(SETTINGS, mode='consent'), identity=existing_identity(), password='')
            with patch.object(rd.pwd, 'getpwnam', return_value=account):
                rd.as_user('apply', account.pw_name, payload)
                self.assertEqual(rd.as_user('identity', account.pw_name), payload['identity'])

    def test_cli_error_does_not_log_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            payload = dict(settings=SETTINGS, identity={}, password='short-SECRET')
            payload['settings'] = dict(SETTINGS, mode='invalid')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/rustdesk-settings.py'), '--child', 'apply', d],
                                    input=json.dumps(payload), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('short-SECRET', result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_validation(self):
        for r in ({'mode': 'invalid'}, {'mode': 'consent'}, {'public_key': 'bad'}, {'id_server': 'host; command'}, {'id_server': 'host:99999'}, {'password': 'NO_SECRET_IN_TOML'}):
            with self.assertRaises(ConfigError):
                validate_machine(dict(disk='/dev/disk/by-id/ata-EXAMPLE', remote_support=r))


@unittest.skipUnless(shutil.which('nix'), 'Nix is needed for pinned module evaluation')
class RemoteSupportEvaluationTests(unittest.TestCase):
    def test_off_consent_unattended_units(self):
        expression = r'''
          let
            f = builtins.getFlake (toString ROOT);
            lib = f.inputs.nixpkgs.lib;
            check = mode:
              let
                c = (f.nixosConfigurations.office-example.extendModules {
                  modules = [{ nix2office.remoteSupport = {
                    inherit mode;
                    idServer = "example.org"; relayServer = "example.org"; publicKey = "test";
                  }; }];
                }).config;
                active = mode != "off";
                unit = c.systemd.services.rustdesk or {};
              in {
                inherit mode;
                assertions = builtins.all (x: x.assertion) c.assertions;
                service = builtins.hasAttr "rustdesk" c.systemd.services;
                userService = builtins.hasAttr "nix2office-rustdesk" c.home-manager.users.office.systemd.user.services;
                package = builtins.elem "rustdesk" (map lib.getName c.environment.systemPackages);
                config = if active then unit.serviceConfig else {};
                wantedBy = unit.wantedBy or [];
                lightdm = c.services.xserver.displayManager.lightdm.extraConfig;
              };
          in map check [ "off" "consent" "unattended" ]
        '''.replace('ROOT', json.dumps(str(ROOT)))
        result = subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', expression],
                                check=True, text=True, capture_output=True, timeout=180)
        for case in json.loads(result.stdout):
            with self.subTest(mode=case['mode']):
                active = case['mode'] != 'off'
                self.assertTrue(case['assertions'])
                self.assertEqual(case['service'], active)
                self.assertEqual(case['package'], active)
                self.assertFalse(case['userService'])
                if active:
                    config = case['config']
                    self.assertEqual(config['User'], 'root')
                    self.assertTrue(config['ExecStart'].endswith('/bin/rustdesk --service'))
                    self.assertNotIn('--password', config['ExecStart'])
                    self.assertEqual(config['LoadCredential'], ['password:/run/secrets/rustdesk-password'] if case['mode'] == 'unattended' else [])
                    self.assertIn('multi-user.target', case['wantedBy'])
                    self.assertIn('user-authority-in-system-dir=false', case['lightdm'])


if __name__ == '__main__':
    unittest.main()
