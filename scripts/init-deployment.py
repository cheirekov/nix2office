#!/usr/bin/env python3
"""Create a private, separately tracked deployment; never print generated secrets."""
import argparse
import json
import os
from pathlib import Path
import secrets
import string
import subprocess


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--hostname", default="office-test")
parser.add_argument("--disk", required=True)
parser.add_argument("--admin-network", required=True)
parser.add_argument("--admin-key", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
dest = root / ".deployment"
if (dest / "flake.nix").exists() or (dest / "keys").exists():
    raise SystemExit("Deployment already exists; refusing to overwrite keys or credentials.")
if not args.disk.startswith("/dev/disk/by-id/"):
    raise SystemExit("Select the internal disk by persistent ID.")
import ipaddress
import re
ipaddress.IPv4Network(args.admin_network)
if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", args.hostname):
    raise SystemExit("Invalid hostname")
public_key = args.admin_key.expanduser().read_text().strip()
if not public_key.startswith(("ssh-", "sk-")) or "\n" in public_key:
    raise SystemExit("Expected a single public SSH key")
revision = run("git", "-C", str(root), "rev-parse", "HEAD", capture_output=True).stdout.strip()
os.umask(0o077)
dest.mkdir(exist_ok=True, mode=0o700)
(dest / "keys").mkdir(mode=0o700)
recipients = []
for name in ("host", "operator"):
    key = dest / "keys" / f"{name}.age"
    run("age-keygen", "-o", str(key), capture_output=True)
    recipients.append(run("age-keygen", "-y", str(key), capture_output=True).stdout.strip())
passwords = {name: "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
             for name in ("office", "admin")}
hashes = {name: run("mkpasswd", "--method=yescrypt", "--stdin", input=value + "\n", capture_output=True).stdout.strip()
          for name, value in passwords.items()}
encrypted = run("sops", "--encrypt", "--age", ",".join(recipients), "--input-type", "json",
                "--output-type", "yaml", "/dev/stdin", input=json.dumps(hashes), capture_output=True).stdout
(dest / "secrets.yaml").write_text(encrypted)
(dest / "credentials.json").write_text(json.dumps(passwords, indent=2) + "\n")
(dest / ".sops.yaml").write_text("creation_rules:\n  - path_regex: secrets\\.yaml$\n    age: " + ",".join(recipients) + "\n")
(dest / ".gitignore").write_text("keys/\ncredentials.json\nresult*\n*.log\n*.nar*\n*.sock\n")
host = '''{ config, ... }: {
  networking.hostName = HOSTNAME;
  nix2office = {
    diskDevice = DISK;
    adminNetwork = NETWORK;
    adminAuthorizedKeys = [ KEY ];
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
'''
# JSON strings are valid Nix strings here; reject interpolation in user-supplied values.
for token, value in {"HOSTNAME": args.hostname, "DISK": args.disk,
                     "NETWORK": args.admin_network, "KEY": public_key}.items():
    if "${" in value:
        raise SystemExit("Nix interpolation is not allowed in deployment values")
    host = host.replace(token, json.dumps(value, ensure_ascii=False))
(dest / "host.nix").write_text(host)
flake = '''{
  description = "Private Nix2office deployment";
  inputs.nix2office.url = SOURCE;
  inputs.nixpkgs.follows = "nix2office/nixpkgs";
  outputs = { nix2office, nixpkgs, ... }: {
    nixosConfigurations.HOST = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [ nix2office.nixosModules.office nix2office.nixosModules.legacy-bios ./host.nix ];
    };
  };
}
'''
source = f"git+{root.as_uri()}?rev={revision}"
(dest / "flake.nix").write_text(flake.replace("SOURCE", json.dumps(source)).replace("HOST", args.hostname))
run("git", "-C", str(dest), "init", "-b", "main", capture_output=True)
run("git", "-C", str(dest), "add", ".gitignore", ".sops.yaml", "flake.nix", "host.nix", "secrets.yaml")
print("Private deployment created. Credentials: .deployment/credentials.json (0600).")
print("Use ./.deployment as a Git flake; NEVER path:.deployment, which would copy ignored keys to the store.")
