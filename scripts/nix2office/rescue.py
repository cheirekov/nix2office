"""Interactive rescue-to-install orchestration. Erasure requires a final typed disk ID."""
import ipaddress
import json
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from .draft import directory, load, save
from .config import ConfigError, load_machine
from .deployment import PreparationError, check_destination, pinned_source, prepare
from .hardware import probe
from .wizard import Cancelled, wizard


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def check_rescue(ssh):
    # Passwordless root in the temporary rescue is required by install-built.py.
    # An installed workstation must never be treated as rescue just by its name.
    run(ssh + ["test -e /iso && findmnt -n -t squashfs,iso9660 >/dev/null && "
               "test -e /etc/NIXOS && test \"$(id -un)\" = nixos && sudo -n true"])


def recovery_command(host, dest, resume=False):
    return shlex.join(['nix', 'run', '--refresh', '--option', 'builders', '',
                       'github:cheirekov/nix2office#install', '--', '--target', host,
                       '--output', str(dest), '--resume' if resume else '--prepared'])


def install(args):
    import questionary as q
    def ask(question):
        value = question.ask()
        if value is None:
            raise Cancelled
        return value

    if args.config or args.update or args.check or args.probe or args.recommend or args.hardware_json or args.ssh_socket or args.ssh_config:
        raise ConfigError("--rescue accepts --target IP, --output DIR and optional --prepared/--resume; use #configure for advanced modes.")
    last = directory(Path(args.output).expanduser().absolute().parent) / 'last-rescue.json'
    def valid_host(value):
        try:
            ipaddress.IPv4Address(value)
            return True
        except ValueError:
            return 'Въведи IPv4 адреса от rescue екрана, например 192.168.1.50.'
    host = args.target or ask(q.text("IP адресът от екрана на nixos-rescue:", default=load(last).get('host', ''), validate=valid_host))
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        raise ConfigError("Enter the rescue IPv4 address only, without user@ or SSH options.") from None
    save(last, {'host': host})
    if args.resume and args.prepared:
        raise ConfigError("Choose --prepared (fresh install) or --resume (already mounted disk), not both.")
    dest = Path(args.output).expanduser().absolute()
    if args.resume or args.prepared:
        check_destination(dest, update=True)
    else:
        if (dest / 'machine.toml').is_file() and (dest / '.nix2office.json').is_file():
            raise PreparationError('Вече има подготвена конфигурация. За нова инсталация от нея:\n'
                                   + recovery_command(host, dest)
                                   + '\nАко инсталацията вече е започнала и дискът е монтиран:\n'
                                   + recovery_command(host, dest, resume=True))
        check_destination(dest)
    source = pinned_source(args.project, args.source)
    print("Подготовка → хардуер → настройки → build → проверка → изрично разрешение за изтриване.")
    print("SSH паролата се въвежда в OpenSSH. Не се записва; подразбиращият rescue login е nixos.")
    with tempfile.TemporaryDirectory(prefix="nix2office-rescue-") as tmp:
        private = Path(tmp)
        # A private known_hosts prevents IP reuse from clobbering normal SSH trust.
        scanned = subprocess.run(["ssh-keyscan", "-T", "5", "-t", "ed25519", host],
                                 capture_output=True, text=True, timeout=15)
        lines = [line for line in scanned.stdout.splitlines() if line.startswith(host + " ")]
        if len(lines) != 1:
            raise PreparationError("Cannot read the rescue ED25519 host key; check IP/network.")
        known = private / "known_hosts"
        known.write_text(lines[0] + "\n")
        known.chmod(0o600)
        fp = subprocess.check_output(["ssh-keygen", "-lf", str(known)], text=True).strip()
        print("На rescue конзолата: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub")
        print("Получен през мрежата ключ: " + fp)
        if not ask(q.confirm("Отпечатъкът съвпада ли с този на конзолата?", default=False)):
            raise Cancelled
        socket = private / "ssh.sock"
        config = private / "ssh_config"
        config.write_text(f'''Host rescue
  HostName {host}
  User nixos
  UserKnownHostsFile {known}
  StrictHostKeyChecking yes
  ForwardAgent no
  IdentityAgent none
  IdentityFile none
  IdentitiesOnly yes
  PreferredAuthentications password,keyboard-interactive
  ControlMaster auto
  ControlPersist 30m
  ControlPath {socket}
  ConnectTimeout 10
  ServerAliveInterval 30
''')
        config.chmod(0o600)
        base = ["ssh", "-F", str(config)]
        installation_started = False
        try:
            run(base + ["-fN", "rescue"])
            ssh = base + ["-o", "BatchMode=yes", "rescue"]
            check_rescue(ssh)
            if not (args.resume or args.prepared):
                inventory = probe("rescue", config, socket)
                local_args = SimpleNamespace(**vars(args))
                local_args.target, local_args.ssh_config, local_args.ssh_socket = "rescue", config, socket
                local_args.draft_scope = host
                machine, dest, generated = wizard(local_args)
                dest = prepare(machine, dest, source, generated)
                (dest / "hardware.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n")
                (dest / "hardware.json").chmod(0o600)
                run(["git", "-C", str(dest), "add", "--", "hardware.json"])
            machine = load_machine(dest / "machine.toml")
            hostname, disk = machine["hostname"], machine["disk"]
            print("Изграждане на системата на административната машина. Builders са изключени.")
            # Git flakes include tracked deployment files, never the ignored age keys.
            run(["nix", "build", "--option", "builders", "", "--out-link", str(dest / "result"),
                 f"{dest}#nixosConfigurations.{hostname}.config.system.build.toplevel",
                 f"{dest}#nixosConfigurations.{hostname}.config.system.build.diskoScript"])
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "install-built.py"),
                       "--target", f"nixos@{host}", "--socket", str(socket), "--disk", disk,
                       "--deployment", str(dest)]
            if args.resume:
                command += ["--resume"]
            run(command)
            if not ask(q.confirm("Build и проверките приключиха. Да започна инсталация?", default=False)):
                print(f"Готов build в {dest}. Дискът не е променен.")
                print("За по-късна инсталация: " + recovery_command(host, dest, resume=args.resume))
                return 0
            action = "Продължаване БЕЗ форматиране" if args.resume else "ИЗТРИВАНЕ НА ЦЕЛИЯ ДИСК"
            print(f"{action}: {disk} на {host} → {hostname}")
            if ask(q.text("За потвърждение въведи целия /dev/disk/by-id/... път:")) != disk:
                raise Cancelled
            reboot = ask(q.confirm("Рестарт след успешна инсталация?", default=True))
            installation_started = True
            run(command + ["--execute"] + (["--reboot"] if reboot else []))
            print("Инсталирано. Избери вътрешния SSD от boot менюто и влез с избрания потребител.")
        except (ConfigError, PreparationError, subprocess.CalledProcessError, OSError, KeyboardInterrupt, Cancelled):
            if (dest / 'machine.toml').is_file():
                print('Конфигурацията е запазена. Продължи без повторно попълване с:')
                print(recovery_command(host, dest, args.resume or installation_started))
            else:
                print('Ако вече си попълвал менютата, отговорите са в локалната .nix2office чернова. Повтори помощника; паролите се въвеждат отново.')
            raise
        finally:
            subprocess.run(base + ["-O", "exit", "rescue"], capture_output=True)
    return 0
