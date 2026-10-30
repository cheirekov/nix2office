import importlib.util
from pathlib import Path
import tempfile
import unittest
import toml
from nix2office.config import validate_machine, ConfigError
spec=importlib.util.spec_from_file_location('rd',Path(__file__).resolve().parents[1]/'scripts/rustdesk-settings.py')
rd=importlib.util.module_from_spec(spec);spec.loader.exec_module(rd)
class RemoteSupportTests(unittest.TestCase):
    def test_merge_and_clear_password(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cfg=root/'config';secret=root/'secret';secret.write_text('TEST_ONLY_LONG_PASSWORD')
            r=dict(mode='unattended',id_server='example.org',relay_server='example.org',public_key='test')
            rd.apply(r,cfg,str(secret))
            self.assertEqual(toml.load(cfg/'RustDesk.toml')['password'],'TEST_ONLY_LONG_PASSWORD')
            c=toml.load(cfg/'RustDesk.toml');c['id']='123';(cfg/'RustDesk.toml').write_text(toml.dumps(c))
            r['mode']='consent';rd.apply(r,cfg)
            self.assertEqual(toml.load(cfg/'RustDesk.toml'),dict(id='123',password=''))
            self.assertEqual(toml.load(cfg/'RustDesk2.toml')['options']['approve-mode'],'click')
            self.assertEqual((cfg/'RustDesk.toml').stat().st_mode & 0o777,0o600)
    def test_missing_secret_does_not_enable_password_access(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):rd.apply(dict(mode='unattended'),d+'/cfg',d+'/missing')
            self.assertFalse((Path(d)/'cfg/RustDesk2.toml').exists())
    def test_validation(self):
        for r in ({'mode':'invalid'},{'mode':'consent'},{'public_key':'bad'},{'id_server':'host; command'},{'id_server':'host:99999'},{'password':'NO_SECRET_IN_TOML'}):
            with self.assertRaises(ConfigError):validate_machine(dict(disk='/dev/disk/by-id/ata-EXAMPLE',remote_support=r))
