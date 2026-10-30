"""Exercise destructive-install boundaries with fake SSH/build commands only."""
import base64
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from nix2office import rescue
from nix2office.config import ConfigError, validate_machine
from nix2office.hardware import parse_probe, recommendation
from nix2office.ssh_keys import fingerprint
from nix2office.wizard import Cancelled
from tests.test_assistant import inventory_text


class DiscoveryTests(unittest.TestCase):
    def test_device_facts_drive_recommendations(self):
        raw = inventory_text().replace('N2O_GPU=i915', 'N2O_PCI=030000:10de:1c82:nouveau 028000:14e4:43a0:unbound\nN2O_USB=0bda:b723\nN2O_BLUETOOTH=1\nN2O_GPU=i915')
        inv = parse_probe(raw)
        self.assertTrue(inv['bluetooth_detected'])
        notes = '\n'.join(recommendation(inv)['notes'])
        self.assertIn('NVIDIA', notes)
        self.assertIn('028000:14e4:43a0:unbound', notes)
        self.assertIn('Blueman', notes)

    def test_dotted_user_and_optional_features_roundtrip(self):
        from nix2office.config import dump_machine
        import tomllib
        m = validate_machine({'disk':'/dev/disk/by-id/ata-EXAMPLE', 'user':{'name':'yordan.cheyrekov'}, 'apps':{'artcraft':True}, 'devices':{'bluetooth':True}})
        self.assertEqual(validate_machine(tomllib.loads(dump_machine(m))), m)
        with self.assertRaises(ConfigError):
            validate_machine({'disk':'/dev/disk/by-id/ata-EXAMPLE', 'devices':{'bluetooth':'true'}})

    def test_fingerprint_matches_openssh(self):
        with tempfile.TemporaryDirectory() as d:
            key = Path(d)/'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public = key.with_suffix('.pub').read_text().strip()
            fp = subprocess.check_output(['ssh-keygen','-lf',str(key.with_suffix('.pub'))],text=True).split()[1]
            self.assertEqual(fingerprint(public),fp)


class RescueBoundaries(unittest.TestCase):
    def simulate(self, confirms, typed='wrong-disk', failure=False):
        args = SimpleNamespace(config=None, update=False, check=False, probe=False, recommend=False,
            hardware_json=None, ssh_socket=None, ssh_config=None, target='192.0.2.10', output=Path('/tmp/fake-deploy'),
            resume=True, prepared=False, project=Path('/tmp'), source=None)
        machine = validate_machine({'disk':'/dev/disk/by-id/ata-EXAMPLE'})
        calls = []
        def execute(command, **kwargs):
            calls.append(command)
            if failure and 'sudo -n true' in command[-1]:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command,0,stdout='192.0.2.10 ssh-ed25519 AAAA\n')
        with patch('questionary.confirm') as confirm, patch('questionary.text') as text, \
             patch.object(rescue,'check_destination'), patch.object(rescue,'pinned_source',return_value='github:owner/repo/'+'a'*40), \
             patch.object(rescue,'load_machine',return_value=machine), \
             patch.object(rescue.subprocess,'run',side_effect=execute), \
             patch.object(rescue.subprocess,'check_output',return_value='SHA256:EXAMPLE'):
            confirm.return_value.ask.side_effect = confirms
            text.return_value.ask.return_value = typed
            try:
                rescue.install(args)
            except (Cancelled,subprocess.CalledProcessError):
                pass
        return calls

    def test_unconfirmed_host_never_authenticates_or_builds(self):
        calls=self.simulate([False])
        self.assertFalse(any('-fN' in c or c[0]=='nix' for c in calls))

    def test_nonrescue_never_builds_or_installs(self):
        calls=self.simulate([True],failure=True)
        self.assertFalse(any(c[0]=='nix' or '--execute' in c for c in calls))

    def test_declined_install_never_executes(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            calls=self.simulate([True,False])
        self.assertIn('--resume',output.getvalue())
        self.assertNotIn('--prepared',output.getvalue())
        self.assertTrue(any(c[0]=='nix' for c in calls))
        self.assertFalse(any('--execute' in c for c in calls))

    def test_wrong_disk_confirmation_never_executes(self):
        calls=self.simulate([True,True])
        self.assertFalse(any('--execute' in c for c in calls))

    def test_resume_never_loses_resume_flag_and_reboot_is_optional(self):
        calls=self.simulate([True,True,False],typed='/dev/disk/by-id/ata-EXAMPLE')
        execute=[c for c in calls if '--execute' in c]
        self.assertEqual(len(execute),1)
        self.assertIn('--resume',execute[0])
        self.assertNotIn('--reboot',execute[0])

if __name__=='__main__':
    unittest.main()
