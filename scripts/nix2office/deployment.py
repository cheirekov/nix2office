"""Create a private Git flake; credentials never become Nix inputs."""
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import string
import subprocess
from urllib.parse import parse_qs, urlparse

from .config import ConfigError, dump_machine, load_machine, validate_machine


class PreparationError(RuntimeError):
    pass


def run(*args, **kwargs):
    # Always capture subprocess output: a failing secret-handling tool may echo input.
    try:
        return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)
    except (OSError, subprocess.CalledProcessError):
        raise PreparationError(f"{Path(args[0]).name} failed; secret-handling output was not displayed.") from None


def pinned_source(project, override=None):
    if override:
        source = override
    elif (project / "modules/office.nix").is_file() and (project / ".git").exists():
        status = run("git", "-C", str(project), "status", "--porcelain", "--untracked-files=normal").stdout
        if status.strip():
            raise PreparationError("Commit the public project before preparing a deployment; its source must be pinned to a clean revision.")
        revision = run("git", "-C", str(project), "rev-parse", "HEAD").stdout.strip()
        source = f"git+{project.resolve().as_uri()}?rev={revision}"
    else:
        source = os.environ.get("NIX2OFFICE_SOURCE", "")
    immutable = re.fullmatch(r"github:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[0-9a-f]{40}", source or "")
    if not immutable and source and source.startswith(("git+file:", "git+https:", "git+ssh:")):
        rev = parse_qs(urlparse(source).query).get("rev", [""])
        immutable = len(rev) == 1 and re.fullmatch(r"[0-9a-f]{40}", rev[0])
    if not immutable or any(c in source for c in ("\n", "\r", "${")):
        raise PreparationError("Use a clean Nix2office checkout, or --source with an immutable Git revision (40 hexadecimal digits).")
    return source


def check_destination(dest, update=False):
    """Refuse overwrites and public output paths before collecting passwords."""
    dest = Path(os.path.abspath(dest.expanduser()))
    if dest.is_symlink():
        raise PreparationError("The deployment directory must not be a symlink.")
    if dest.exists() and not update:
        raise PreparationError("Deployment directory already exists. Keep its keys intact; choose another --output (for example .deployment/new-office).")
    if update and (not (dest / "machine.toml").is_file() or not (dest / ".nix2office.json").is_file()):
        raise PreparationError("--update requires a deployment created by this assistant; legacy deployments need explicit migration.")
    parent = dest.parent
    while not parent.exists():
        parent = parent.parent
    result = subprocess.run(["git", "-C", str(parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if result.returncode == 0:
        gitroot = Path(result.stdout.strip()).resolve()
        # An existing deployment is its own repository, whose ignore rules protect keys.
        candidate = dest / "keys/host.age"
        ignored = subprocess.run(["git", "-C", str(gitroot), "check-ignore", "-q", "--", str(candidate)], capture_output=True)
        if ignored.returncode != 0:
            raise PreparationError("The output is inside a Git checkout without private-deployment ignore rules. Use an ignored .deployment directory or a location outside that checkout.")
    return dest


def _write(path, content):
    path = Path(path)
    if path.is_symlink():
        raise PreparationError("Refusing to replace a symlink inside the deployment.")
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def prompt_password(label, minimum=8, maximum=None):
    # No piped-input fallback: getpass would otherwise warn and echo on stdin.
    if not os.isatty(0) or not os.isatty(2):
        raise PreparationError("Passwords require an interactive terminal. Use --generate-passwords for an unattended preparation.")
    while True:
        first = getpass.getpass(f"Парола за {label} (не се показва): ")
        if len(first) < minimum or (maximum is not None and len(first) > maximum) or any(ord(c) < 32 or ord(c) == 127 for c in first):
            limits = f"{minimum}–{maximum}" if maximum is not None else f"поне {minimum}"
            print(f"Използвай {limits} знака, без контролни символи. Опитай отново.")
            continue
        second = getpass.getpass("Повтори паролата: ")
        if first != second:
            print("Паролите не съвпадат. Опитай отново.")
        else:
            return first


def collect_passwords(user, generate=False):
    if generate:
        alphabet = string.ascii_letters + string.digits
        return {name: "".join(secrets.choice(alphabet) for _ in range(20)) for name in (user, "admin")}
    return {user: prompt_password(user), "admin": prompt_password("admin")}


def _flake(source):
    source_nix = json.dumps(source)
    return '''{
  description = "Private Nix2office deployment";
  inputs.nix2office.url = SOURCE;
  inputs.nixpkgs.follows = "nix2office/nixpkgs";
  outputs = { nix2office, nixpkgs, ... }:
    let machine = builtins.fromTOML (builtins.readFile ./machine.toml);
    in {
      nixosConfigurations.${machine.hostname} = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          nix2office.nixosModules.office
          nix2office.nixosModules.disk
          (nix2office.lib.machineModule ./machine.toml)
          ./host.nix
          ({ config, lib, ... }: lib.mkIf ((machine.remote_support.mode or "off") == "unattended") {
            sops.secrets.rustdesk-password = {
              sopsFile = ./rustdesk.yaml;
              key = "password";
              owner = machine.user.name;
              mode = "0400";
            };
            nix2office.remoteSupport.passwordFile = config.sops.secrets.rustdesk-password.path;
          })
        ];
      };
    };
}
'''.replace("SOURCE", source_nix)


def _host(user):
    return '''{ config, ... }: {
  assertions = [ {
    assertion = config.nix2office.user.name == INITIAL_USER;
    message = "Changing the installed login name needs a separate home/ownership/keyring migration or a new deployment.";
  } ];
  nix2office = {
    officePasswordFile = config.sops.secrets.office.path;
    adminPasswordFile = config.sops.secrets.admin.path;
  };
  sops = {
    defaultSopsFile = ./secrets.yaml;
    age.keyFile = "/var/lib/sops-nix/key.txt";
    age.sshKeyPaths = [];
    gnupg.sshKeyPaths = [];
    secrets.office.neededForUsers = true;
    secrets.admin.neededForUsers = true;
  };
}
'''.replace("INITIAL_USER", json.dumps(user))


def prepare_rustdesk_secret(machine, dest):
    if machine['remote_support']['mode'] != 'unattended' or (dest/'rustdesk.yaml').exists():
        return
    password = prompt_password('RustDesk — постоянна парола, 12–128 знака', minimum=12, maximum=128)
    recipients = [run('age-keygen', '-y', str(dest/'keys'/f'{name}.age')).stdout.strip() for name in ('host', 'operator')]
    encrypted = run('sops', '--encrypt', '--age', ','.join(recipients), '--input-type', 'json', '--output-type', 'yaml', '/dev/stdin', input=json.dumps({'password': password})).stdout
    _write(dest/'rustdesk.yaml', encrypted)
    run('git', '-C', str(dest), 'add', 'rustdesk.yaml')


def prepare(machine, dest, source, generate_passwords=False, update=False):
    m = validate_machine(machine)
    dest = check_destination(dest, update)
    for command in (("git",) if update else ("git", "age-keygen", "sops", "mkpasswd")):
        if not shutil.which(command):
            raise PreparationError(f"Missing {command}; use nix run .#configure or nix develop.")
    if update:
        marker = json.loads((dest / ".nix2office.json").read_text())
        if marker.get("user") != m["user"]["name"]:
            raise PreparationError("Changing the login name needs a separate migration or a new deployment; keys/passwords were not changed.")
        prepare_rustdesk_secret(m, dest)
        _write(dest / "machine.toml", dump_machine(m))
        _write(dest / "flake.nix", _flake(source))
        return dest
    # All validation and overwrite checks precede prompts, key generation and writes.
    passwords = collect_passwords(m["user"]["name"], generate_passwords)
    hashes = {role: run("mkpasswd", "--method=yescrypt", "--stdin", input=passwords[name] + "\n").stdout.strip()
              for role, name in (("office", m["user"]["name"]), ("admin", "admin"))}
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest.mkdir(mode=0o700)
    try:
        (dest / "keys").mkdir(mode=0o700)
        recipients = []
        for name in ("host", "operator"):
            key = dest / "keys" / f"{name}.age"
            run("age-keygen", "-o", str(key))
            key.chmod(0o600)
            recipients.append(run("age-keygen", "-y", str(key)).stdout.strip())
        encrypted = run("sops", "--encrypt", "--age", ",".join(recipients), "--input-type", "json", "--output-type", "yaml", "/dev/stdin", input=json.dumps(hashes)).stdout
        _write(dest / "secrets.yaml", encrypted)
        if generate_passwords:
            _write(dest / "credentials.json", json.dumps(passwords, indent=2) + "\n")
        _write(dest / ".sops.yaml", "creation_rules:\n  - path_regex: secrets\\.yaml$\n    age: " + ",".join(recipients) + "\n")
        _write(dest / ".gitignore", "keys/\ncredentials.json\nresult*\n*.log\n*.nar*\n*.sock\nknown_hosts\n__pycache__/\n")
        _write(dest / "machine.toml", dump_machine(m))
        _write(dest / "host.nix", _host(m["user"]["name"]))
        _write(dest / "flake.nix", _flake(source))
        _write(dest / ".nix2office.json", json.dumps({"version": 1, "user": m["user"]["name"]}) + "\n")
        _write(dest / "README.md", f'''# Private deployment: {m["hostname"]}

Edit machine.toml to choose applications, displayed name, e-mail, keyboard,
workgroup and VPN clients. The login name is guarded against accidental renames.
Then rebuild this private Git flake; do not use path: flakes.

Passwords are SOPS-encrypted yescrypt hashes in secrets.yaml. Private age keys
in keys/ stay outside Git and the Nix store. Entered passwords are not saved;
generated ones are only in the ignored mode-0600 credentials.json.

Samba server mode requires an additional local SMB password after installation:
sudo smbpasswd -a {m["user"]["name"]}
Tailscale sign-in is through Trayscale. ZeroTier networks may need approval in
their controller; removing an ID from TOML does not leave that network.
WireGuard secrets belong in runtime NetworkManager profiles, not machine.toml.

The helper prepares configuration only. It does not build, format, install,
enrol VPNs or configure Nextcloud accounts.
''')
        run("git", "-C", str(dest), "init", "-b", "main")
        prepare_rustdesk_secret(m, dest)
        run("git", "-C", str(dest), "add", ".gitignore", ".sops.yaml", ".nix2office.json", "README.md", "machine.toml", "host.nix", "flake.nix", "secrets.yaml")
    except BaseException:
        # Only this newly created, mode-0700 directory is ever removed on failure.
        shutil.rmtree(dest)
        raise
    return dest


def summary(m):
    u = m["user"]
    office = [] if m["apps"]["office"] == "none" else [m["apps"]["office"]]
    if m["apps"]["artcraft"]:
        office.append("ArtCraft (WordCraft, DeckCraft, GridCraft, PdfCraft)")
    print(f'Машина: {m["hostname"]} | {m["boot_mode"].upper()} | профил {m["profile"]}')
    print(f'Потребител: {u["name"]} — {u["full_name"]} | e-mail: {u["email"] or "(не е зададен)"}')
    print(f'Диск: {m["disk"]}')
    print(f'Приложения: {m["apps"]["browser"]}; офис: {" + ".join(office) or "без офис пакет"}; PDF: {m["apps"]["pdf_editor"]}; Nextcloud: {m["apps"]["nextcloud"]}')
    print("RustDesk: " + m["remote_support"]["mode"])
    print("Comma с готов малък индекс: " + ("включен" if m["tools"]["comma"] else "изключен"))
    print("Допълнителни програми: " + (", ".join(m["apps"]["extra"]) or "няма"))
    print(f'Шрифтове: Microsoft Core={m["fonts"]["microsoft_core"]}; Carlito/Caladea={m["fonts"]["office_fallbacks"]}')
    print(f'Клавиатура: US + BG {m["keyboard"]["bulgarian"]}; Workgroup: {m["sharing"]["workgroup"]} ({m["sharing"]["mode"]})')
    print('VPN: ' + (', '.join(k for k in ("wireguard", "tailscale", "zerotier") if m["vpn"][k]) or '(няма)'))
    print(f'Bluetooth: {m["devices"]["bluetooth"]}; unfree firmware: {m["devices"]["unfree_firmware"]}')
    access = "всички IPv4 (0.0.0.0/0)" if m['admin']['network'] == "0.0.0.0/0" else m['admin']['network']
    print('Admin SSH: ' + ('включен, само с ключ, от ' + access if m['admin']['ssh_public_key'] else 'ИЗКЛЮЧЕН'))
    print('CPU governor: ' + m["performance"]["cpu_governor"])


def completion(dest, m, generated=False, update=False):
    print(f'\nПодготвено: {dest / "machine.toml"}')
    print('Няма инсталация или промяна на избрания диск. Няма стартирани VPN връзки.')
    if generated and not update:
        print(f'Генерираните пароли са само локално в {dest / "credentials.json"} (0600).')
    print('Следва: заключи inputs, build и преглед на конфигурацията според README, преди инсталация.')
