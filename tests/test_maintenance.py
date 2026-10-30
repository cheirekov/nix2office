"""Maintenance validation and activation boundaries; all remote operations mocked."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from nix2office import maintenance as m
from nix2office.config import ConfigError,validate_machine

SYSTEM='/nix/store/'+'a'*32+'-nixos-system-office1-test'
OLD='/nix/store/'+'b'*32+'-nixos-system-office1-old'

class MaintenanceTests(unittest.TestCase):
    def test_catalog_and_font_validation(self):
        v=validate_machine({'disk':'/dev/disk/by-id/ata-EXAMPLE','fonts':{'microsoft_core':True},'apps':{'extra':['remmina','vlc']}})
        self.assertTrue(v['fonts']['microsoft_core'])
        for bad in (['missing'],['remmina','remmina'],['remmina; sudo foo'],[{}],'remmina'):
            with self.assertRaises(ConfigError):
                validate_machine({'disk':v['disk'],'apps':{'extra':bad}})
        with self.assertRaises(ConfigError):
            validate_machine({'disk':v['disk'],'fonts':{'microsoft_core':'true'}})

    def simulate(self,apply=True,actual='office1',answer='office1',tty=True,bad_password=False):
        machine=validate_machine({'hostname':'office1','disk':'/dev/disk/by-id/ata-EXAMPLE'})
        orig=Path.resolve
        def resolve(p,*args,**kwargs):
            return Path(SYSTEM) if p.name=='result-maintenance' else orig(p,*args,**kwargs)
        def remote(ssh,command,**kwargs):
            if bad_password and 'sudo' in command: raise subprocess.CalledProcessError(1,ssh)
            output=actual if command.endswith('hostname') else OLD
            if command=='readlink -f /run/current-system' and remote.calls>1: output=SYSTEM
            remote.calls+=1
            return subprocess.CompletedProcess(ssh,0,stdout=output+'\n')
        remote.calls=0
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'known_hosts').touch()
            args=['maintain','--deployment',d,'--revision','c'*40]+(['--apply','--target','admin@192.0.2.10'] if apply else [])
            with patch.object(sys,'argv',args),patch.object(m,'load_machine',return_value=machine),patch.object(m,'prepare'),patch.object(m,'pinned_source',return_value='github:owner/repo/'+'c'*40),patch.object(m,'run') as run,patch.object(m,'remote',side_effect=remote) as r,patch.object(m,'transfer') as transfer,patch.object(Path,'resolve',resolve),patch.object(m.os,'isatty',return_value=tty),patch('builtins.input',return_value=answer),patch.object(m.getpass,'getpass',return_value='TEST_ONLY') as password,contextlib.redirect_stdout(io.StringIO()):
                status=m.main()
                return status,r.call_args_list,transfer.call_count,password.call_count

    def test_build_only_never_uses_ssh_or_password(self):
        status,calls,transfers,passwords=self.simulate(apply=False)
        self.assertEqual((status,len(calls),transfers,passwords),(0,0,0,0))

    def test_wrong_target_stops_before_password_and_transfer(self):
        status,calls,transfers,passwords=self.simulate(actual='other')
        self.assertEqual((status,transfers,passwords),(1,0,0))

    def test_declined_activation_stops_before_password(self):
        status,calls,transfers,passwords=self.simulate(answer='no')
        self.assertEqual((status,transfers,passwords),(0,0,0))
        self.assertFalse(any('sudo' in c.args[1] for c in calls))

    def test_noninteractive_activation_is_rejected(self):
        status,calls,transfers,passwords=self.simulate(tty=False)
        self.assertEqual((status,transfers,passwords),(1,0,0))

    def test_failed_password_never_transfers_or_activates(self):
        status,calls,transfers,passwords=self.simulate(bad_password=True)
        self.assertEqual((status,transfers,passwords),(1,0,1))
        self.assertFalse(any('switch-to-configuration' in c.args[1] for c in calls))

    def test_explicit_activation_checks_final_system(self):
        status,calls,transfers,passwords=self.simulate()
        self.assertEqual((status,transfers,passwords),(0,1,1))
        activate=[c.args[1] for c in calls if 'switch-to-configuration' in c.args[1]]
        self.assertEqual(len(activate),1)
        self.assertIn(OLD,activate[0])
        self.assertIn(SYSTEM,activate[0])
