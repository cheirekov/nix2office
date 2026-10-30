"""Interactive recovery: draft defaults, immediate field checks, password retry."""
import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import questionary
from nix2office.config import DEFAULTS
from nix2office.draft import Menus, load
from nix2office.remote_support import choose
from nix2office.deployment import prompt_password


class FakeQuestion:
    def __init__(self, value): self.value=value
    def ask(self): return self.value


class FakeQ:
    Choice=questionary.Choice
    def __init__(self): self.prompts=[];self.values=[];self.overrides={}
    def make(self,message,*args,**kwargs):
        self.prompts.append((message,kwargs))
        values=self.overrides.get(message,self.values)
        return FakeQuestion(values.pop(0) if values else kwargs.get('default'))
    text=confirm=select=make
    def checkbox(self,message,*args,**kwargs):
        kwargs.setdefault('default',[c.value for c in kwargs.get('choices',[]) if c.checked])
        return self.make(message,*args,**kwargs)


class RecoveryTests(unittest.TestCase):
    def test_full_wizard_defaults_and_checkpoint(self):
        import json
        from types import SimpleNamespace
        from nix2office.wizard import wizard
        from nix2office.hardware import parse_probe
        from tests.test_assistant import inventory_text
        import base64, struct
        kind=b'ssh-ed25519'
        key='ssh-ed25519 '+base64.b64encode(struct.pack('>I',len(kind))+kind+struct.pack('>I',32)+b'a'*32).decode()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'hardware.json';path.write_text(json.dumps(parse_probe(inventory_text())))
            args=SimpleNamespace(output=Path(d)/'.deployment',target=None,hardware_json=path,generate_passwords=False)
            q=FakeQ()
            boot=__import__('json').loads(path.read_text())['boot_mode']
            q.overrides['Начин на зареждане:']=['uefi' if boot=='bios' else 'bios',boot]
            q.overrides['Да включа SSH за admin само с публичен ключ?']=[False,True]
            q.overrides['SSH ще е изключен. Продължавам без отдалечен SSH достъп?']=[False]
            with patch.dict('sys.modules',questionary=q),patch('nix2office.wizard.choose_public_key',return_value=key),contextlib.redirect_stdout(io.StringIO()):
                m,dest,generated=wizard(args)
            self.assertEqual(m['boot_mode'],boot)
            self.assertEqual(m['user']['name'],DEFAULTS['user']['name'])
            self.assertEqual(m['admin']['network'],'0.0.0.0/0')
            self.assertEqual(m['sharing']['network'],'0.0.0.0/0')
            self.assertFalse(generated)
            files=list((Path(d)/'.nix2office').glob('*.json'))
            self.assertEqual(len(files),1)
            self.assertIn('Име на компютъра:',load(files[0])['answers'])

    def test_checkpoint_and_recover_defaults_without_reusing_other_target(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'.deployment';q=FakeQ();m=Menus(q,dest,'host-a')
            q.values=['officehost',True,['vlc']]
            m.text('Hostname').ask();m.confirm('Choice').ask()
            m.checkbox('Apps',choices=[q.Choice('VLC',value='vlc')]).ask()
            self.assertEqual(m.path.stat().st_mode & 0o777,0o600)
            self.assertEqual(m.path.parent.stat().st_mode & 0o777,0o700)
            q=FakeQ();q.values=[True];m=Menus(q,dest,'host-a')
            self.assertEqual(m.text('Hostname',default='old').ask(),'officehost')
            self.assertTrue(m.confirm('Choice',default=False).ask())
            m.checkbox('Apps',choices=[q.Choice('VLC',value='vlc'),q.Choice('Gimp',value='gimp')])
            self.assertTrue(q.prompts[-1][1]['choices'][0].checked)
            self.assertFalse(q.prompts[-1][1]['choices'][1].checked)
            other=Menus(FakeQ(),dest,'host-b')
            self.assertEqual(other.answers,{})

    def test_cancel_preserves_previous_answers_and_stale_choices_not_restored(self):
        with tempfile.TemporaryDirectory() as d:
            q=FakeQ();m=Menus(q,Path(d)/'.deployment','host');q.values=['removed',None]
            m.select('Disk',choices=['removed']).ask();m.text('Other').ask()
            self.assertNotIn('Other',load(m.path)['answers'])
            q=FakeQ();q.values=[True];m=Menus(q,Path(d)/'.deployment','host')
            self.assertEqual(m.select('Disk',choices=['present'],default='present').ask(),'present')

    def test_cancel_at_resume_prompt_stops_and_nested_output_is_supported(self):
        with tempfile.TemporaryDirectory() as d:
            q=FakeQ();m=Menus(q,Path(d)/'nested'/'.deployment','host')
            q.values=['example'];m.text('Hostname').ask()
            q=FakeQ();q.values=[None]
            with self.assertRaises(KeyboardInterrupt):
                Menus(q,Path(d)/'nested'/'.deployment','host')

    def test_rustdesk_fields_validated_when_asked(self):
        q=FakeQ();q.values=['unattended','example.org','example.org','A'*43+'=']
        m=copy.deepcopy(DEFAULTS);choose(m,q,lambda prompt:prompt.ask())
        validators=[k['validate'] for _,k in q.prompts if 'validate' in k]
        self.assertEqual(len(validators),3)
        self.assertIsNot(validators[2](''),True)
        self.assertIsNot(validators[2]('bad'),True)
        self.assertIs(validators[2]('A'*43+'='),True)
        self.assertIsNot(validators[0]('host; command'),True)

    def test_short_and_mismatched_password_retries_locally_without_logging_secret(self):
        secret='VALID_TEST_PASSWORD'
        with patch('nix2office.deployment.os.isatty',return_value=True),patch('nix2office.deployment.getpass.getpass',side_effect=['short','short',secret,'different',secret,secret]),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(prompt_password('RustDesk',12,128),secret)
        self.assertNotIn(secret,output.getvalue())
        self.assertIn('Опитай отново',output.getvalue())
