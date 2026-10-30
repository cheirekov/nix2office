"""Build and explicitly apply an existing private deployment. Never invokes disko."""
import argparse
import getpass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from .config import CATALOG, ConfigError, load_machine
from .deployment import PreparationError, pinned_source, prepare, summary


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def remote(ssh, command, **kwargs):
    return run(ssh + [command], **kwargs)


def transfer(system, ssh, password):
    paths = subprocess.check_output(['nix-store', '-qR', str(system)], text=True).splitlines()
    missing = []
    for start in range(0, len(paths), 128):
        missing += remote(ssh, 'nix-store --check-validity --print-invalid ' + shlex.join(paths[start:start+128]),
                          capture_output=True, text=True).stdout.splitlines()
    if not missing:
        print('Цялата closure вече е на машината.')
        return
    print(f'Прехвърляне на {len(missing)} липсващи store paths (gzip).', flush=True)
    exporter = subprocess.Popen(['nix-store', '--export', *missing], stdout=subprocess.PIPE)
    compressor = subprocess.Popen(['gzip', '-1'], stdin=exporter.stdout, stdout=subprocess.PIPE)
    exporter.stdout.close()
    # The password is one hidden input line; it is never an argument, file or log.
    command = "sudo -k -S -p '' -- sh -c " + shlex.quote('set -eu; gzip -d | nix-store --import')
    importer = subprocess.Popen(ssh + [command], stdin=subprocess.PIPE)
    try:
        importer.stdin.write((password+'\n').encode()); importer.stdin.flush()
        shutil.copyfileobj(compressor.stdout, importer.stdin)
        importer.stdin.close()
        statuses = [importer.wait(), compressor.wait(), exporter.wait()]
        if any(statuses):
            raise PreparationError('Closure transfer failed; activation has not started.')
    finally:
        compressor.stdout.close()
        for p in (importer, compressor, exporter):
            if p.poll() is None:
                p.terminate(); p.wait()


def edit(machine):
    import questionary as q
    def ask(prompt):
        result = prompt.ask()
        if result is None:
            raise KeyboardInterrupt
        return result
    machine['apps']['extra'] = ask(q.checkbox('Допълнителни програми (Space за избор):', choices=[
        q.Choice(v['label'], value=k, checked=k in machine['apps']['extra']) for k,v in CATALOG.items()]))
    for key,label in [('office_fallbacks','Carlito/Caladea'),('microsoft_core','Microsoft Core Fonts (unfree, собствен лиценз)')]:
        machine['fonts'][key] = ask(q.confirm(label+'?', default=machine['fonts'][key]))
    return machine


def main():
    p=argparse.ArgumentParser(description='Maintain an installed Nix2office machine: optional menus, local build, explicit remote activation. No partitioning or reinstall.')
    p.add_argument('--deployment',type=Path,default=Path('.deployment'))
    p.add_argument('--edit',action='store_true',help='Choose additional applications and fonts, preserving all other settings/secrets')
    p.add_argument('--revision',help='Public Nix2office Git revision (40 hex); default: this helper revision')
    p.add_argument('--apply',action='store_true',help='After build, verify installed target and ask before activation')
    p.add_argument('--target',help='admin@HOST; needed with --apply')
    p.add_argument('--socket',type=Path,help='Reuse an existing authenticated SSH master')
    p.add_argument('--identity',type=Path,help='SSH identity/public selector')
    p.add_argument('--ssh-agent',type=Path,help='SSH agent socket, e.g. GPG agent for YubiKey')
    a=p.parse_args()
    if a.apply and (not a.target or not re.fullmatch(r'admin@[A-Za-z0-9][A-Za-z0-9.-]*',a.target)):
        p.error('--apply requires --target admin@HOST')
    if a.revision and not re.fullmatch('[0-9a-f]{40}',a.revision):
        p.error('--revision must have 40 lowercase hexadecimal digits')
    try:
        d=a.deployment.expanduser().resolve()
        machine=load_machine(d/'machine.toml')
        if a.edit:
            machine=edit(machine)
        source=pinned_source(Path.cwd(), 'github:cheirekov/nix2office/'+a.revision if a.revision else os.environ.get('NIX2OFFICE_SOURCE'))
        prepare(machine,d,source,update=True)
        summary(machine)
        result=d/'result-maintenance'
        run(['nix','build','--option','builders','','--out-link',str(result),
             f'{d}#nixosConfigurations.{machine["hostname"]}.config.system.build.toplevel'])
        system=result.resolve(strict=True)
        if not re.fullmatch(r'/nix/store/[a-z0-9]{32}-nixos-system-[A-Za-z0-9.+_-]+',str(system)):
            raise PreparationError('Unexpected system output path.')
        print('Готов build: '+str(system))
        if not a.apply:
            print('Системата на офис машината не е променена. За прилагане: --apply --target admin@HOST.')
            return 0
        known=d/'known_hosts'
        if not known.is_file():
            raise PreparationError('Missing deployment known_hosts; verify the installed SSH host key first.')
        ssh=['ssh','-F','/dev/null','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),
             '-o','BatchMode=yes','-o','ConnectTimeout=10']
        if a.socket: ssh += ['-S',str(a.socket.expanduser().resolve())]
        if a.identity: ssh += ['-o','IdentitiesOnly=yes','-i',str(a.identity.expanduser().resolve())]
        if a.ssh_agent: ssh += ['-o','IdentityAgent='+str(a.ssh_agent.expanduser().resolve())]
        ssh += [a.target]
        actual=remote(ssh,'test -e /etc/NIXOS && test ! -e /iso && hostname',capture_output=True,text=True).stdout.strip()
        if actual != machine['hostname']:
            raise PreparationError('Target hostname/live-environment check failed; no transfer or activation.')
        old=remote(ssh,'readlink -f /run/current-system',capture_output=True,text=True).stdout.strip()
        if not re.fullmatch(r'/nix/store/[a-z0-9]{32}-nixos-system-[A-Za-z0-9.+_-]+',old):
            raise PreparationError('Invalid current system path.')
        print('Текуща система: '+old)
        if Path(old).exists():
            run(['nix','store','diff-closures',old,str(system)])
        if not os.isatty(0) or not os.isatty(2):
            raise PreparationError('Activation requires an interactive terminal for confirmation and password.')
        if input('За прилагане въведи hostname '+actual+': ').strip() != actual:
            print('Отказано; готовият build е запазен.')
            return 0
        password=getpass.getpass('Sudo парола за admin (не се записва): ')
        # Verify before any binary stream; a wrong password cannot consume NAR data.
        remote(ssh,"sudo -k -S -p '' -- true",input=password+'\n',text=True)
        try:
            transfer(system,ssh,password)
            q=shlex.quote
            command='set -eu; test "$(readlink -f /run/current-system)" = '+q(old)+'; '
            command+='nix-store -qR '+q(str(system))+' >/dev/null; '
            command+='nix-env --profile /nix/var/nix/profiles/system --set '+q(str(system))+'; '
            command+=q(str(system)+'/bin/switch-to-configuration')+' switch'
            print('Предишна система за възстановяване: '+old,flush=True)
            remote(ssh,"sudo -k -S -p '' -- sh -c "+q(command),input=password+'\n',text=True)
        finally:
            del password
        active=remote(ssh,'readlink -f /run/current-system',capture_output=True,text=True).stdout.strip()
        if active != str(system):
            raise PreparationError('Activation did not leave the expected active system; inspect before retrying.')
        print('Обновено успешно. При нов kernel рестартирайте в удобен момент.')
        return 0
    except (KeyboardInterrupt,EOFError):
        print('Отказано.');return 130
    except (ConfigError,PreparationError,OSError,subprocess.CalledProcessError) as e:
        print('Поддръжката спря: '+(str(e) if isinstance(e,(ConfigError,PreparationError)) else type(e).__name__))
        print('Не използвайте #install за поправка на обновяване. При частична activation изберете предишна генерация от boot менюто.')
        return 1
