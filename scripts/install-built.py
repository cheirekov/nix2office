#!/usr/bin/env python3
"""Install an already built system using an existing verified rescue SSH master."""
import argparse
from pathlib import Path
import shlex
import subprocess


def quote(value):
    return shlex.quote(str(value))


p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--target", required=True, help="Rescue user@host")
p.add_argument("--socket", type=Path, required=True)
p.add_argument("--disk", required=True, help="Verified internal whole-disk by-id")
p.add_argument("--deployment", type=Path, default=Path(".deployment"))
p.add_argument("--execute", action="store_true", help="Actually erase and install the selected disk")
p.add_argument("--reboot", action="store_true")
p.add_argument("--resume", action="store_true", help="Reuse the verified disk already mounted at /mnt; never format it")
args = p.parse_args()
deploy = args.deployment.resolve()
system = (deploy / "result").resolve(strict=True)
disko = (deploy / "result-1").resolve(strict=True)
if not args.disk.startswith("/dev/disk/by-id/") or args.disk not in disko.read_text():
    raise SystemExit("Disk must be a by-id path matching the built disko script")
if not (system / "bin/switch-to-configuration").exists():
    raise SystemExit("result is not a built NixOS system")
ssh = ["ssh", "-F", "/dev/null", "-S", str(args.socket), "-o", "StrictHostKeyChecking=yes",
       "-o", "BatchMode=yes", "-o", "IdentityAgent=none", "-o", "IdentityFile=none",
       "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no"]
subprocess.run(ssh + ["-O", "check", args.target], check=True)


def remote(command, **kwargs):
    return subprocess.run(ssh + [args.target, command], check=True, **kwargs)


remote("set -eu; d=" + quote(args.disk) + "; test -b \"$d\"; "
       "test \"$(lsblk -dn -o TYPE \"$d\")\" = disk; "
       "test \"$(lsblk -dn -o TRAN \"$d\")\" != usb; "
       "if " + ("false" if args.resume else "lsblk -nr -o MOUNTPOINTS \"$d\" | grep -q '[^[:space:]]'") + "; then "
       "echo 'Refusing to format a mounted disk' >&2; exit 1; fi; "
       "lsblk -dn -o NAME,SIZE,MODEL,TRAN \"$d\"")
print(f"Selected system: {system}\nSelected disk: {args.disk}", flush=True)
if not args.execute:
    print("Preconditions passed. No changes made; --execute is required to install.")
    raise SystemExit(0)


def transfer(output, target_store):
    paths = subprocess.check_output(["nix-store", "-qR", str(output)], text=True).splitlines()
    # A partial installation or another closure may already supply most paths.
    missing = []
    for start in range(0, len(paths), 128):
        missing.extend(remote("sudo -n nix-store --store " + quote(target_store) +
                              " --check-validity --print-invalid " +
                              " ".join(map(quote, paths[start:start + 128])),
                              capture_output=True, text=True).stdout.splitlines())
    if not missing:
        return
    exporter = subprocess.Popen(["nix-store", "--export", *missing], stdout=subprocess.PIPE)
    compressor = subprocess.Popen(["gzip", "-1"], stdin=exporter.stdout, stdout=subprocess.PIPE)
    exporter.stdout.close()
    importer = subprocess.Popen(ssh + [args.target,
        "set -o pipefail; gzip -d | sudo -n nix-store --store " + quote(target_store) + " --import"],
        stdin=compressor.stdout)
    compressor.stdout.close()
    statuses = [importer.wait(), compressor.wait(), exporter.wait()]
    if any(statuses):
        raise SystemExit(f"Closure transfer failed: {statuses}")


if not args.resume:
    print("Transferring disk tool to the live store", flush=True)
    transfer(disko, "/")
    print("Formatting the selected internal disk and mounting /mnt", flush=True)
    remote("sudo -n " + quote(disko))
remote("set -eu; d=$(readlink -f " + quote(args.disk) + "); "
       "s=$(findmnt -n -o SOURCE /mnt); "
       "test \"$(lsblk -dn -o PKNAME \"$s\")\" = \"$(basename \"$d\")\"")
remote("s=$(readlink -f /dev/disk/by-partlabel/disk-system-swap); "
       "swapon --noheadings --raw --show=NAME | grep -qxF \"$s\" || sudo -n swapon \"$s\"")
print("Streaming the system closure directly to the SSD store", flush=True)
transfer(system, "/mnt")
remote("sudo -n install -Dm600 /dev/stdin /mnt/var/lib/sops-nix/key.txt",
       input=(deploy / "keys/host.age").read_bytes())
remote("sudo -n nix-store --store /mnt -qR " + quote(system) + " >/dev/null")
print("Installing system and BIOS bootloader", flush=True)
remote("sudo -n nixos-install --root /mnt --system " + quote(system) +
       " --no-root-password --no-channel-copy --option builders ''")
# Establish the installed host key over the trusted live SSH connection.
remote("sudo -n mkdir -p /mnt/etc/ssh; "
       "sudo -n test -e /mnt/etc/ssh/ssh_host_ed25519_key || "
       "sudo -n ssh-keygen -q -t ed25519 -N '' -f /mnt/etc/ssh/ssh_host_ed25519_key")
public = remote("sudo -n cat /mnt/etc/ssh/ssh_host_ed25519_key.pub", capture_output=True, text=True).stdout.strip()
host = args.target.rsplit("@", 1)[-1]
known = deploy / "known_hosts"
known.write_text(host + " " + public + "\n")
known.chmod(0o600)
print("Installed. Verified host key saved in private deployment known_hosts.", flush=True)
if args.reboot:
    remote("sudo -n sync; sudo -n systemctl reboot --no-block")
