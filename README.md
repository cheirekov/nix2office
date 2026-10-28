# Nix2office

A lightweight NixOS 26.05 office desktop for users accustomed to Windows.
The default profile uses Bulgarian, XFCE/Xorg, a bottom taskbar and application
menu, Firefox ESR, LibreOffice with a tabbed toolbar, PDF tools, network printing
and scanning, and the Nextcloud desktop sync client.

## Public modules

This flake exports `nixosModules.office`, `nixosModules.legacy-bios`,
`homeManagerModules.office`, and `nixosConfigurations.office-example`.
The example has locked accounts and a placeholder disk: **do not install it**.
The office module includes Home Manager and sops-nix. The BIOS module includes
disko and requires `nix2office.diskDevice` to identify the whole internal disk.
The example targets x86_64; the Bulgarian LibreOffice language pack is x86_64.

`office` is an ordinary desktop user; `admin` has password-protected sudo.
Root is locked, automatic graphical login is disabled, and SSH is enabled only
when `nix2office.adminAuthorizedKeys` is populated. The firewall permits SSH
only from the explicitly configured IPv4 `nix2office.adminNetwork` CIDR.
CUPS is a local print client, not a shared print server. Network scanning uses
SANE/airscan; device-specific compatibility still requires a real device test.

## Create a private deployment

First commit the public source. The initializer pins the deployment to that
local Git revision; it never points at an uncommitted working tree.

```sh
nix develop
python3 scripts/init-deployment.py \
  --hostname office-test \
  --disk /dev/disk/by-id/ata-YOUR_INTERNAL_SSD \
  --admin-network 192.168.1.0/24 \
  --admin-key ~/.ssh/YOUR_PUBLIC_KEY.pub
nix flake lock ./.deployment
git -C .deployment add flake.lock
```

The ignored `.deployment/` is a separate local Git repository. Its tracked
files contain the host configuration, encrypted SOPS hashes, public recipients,
and pinned inputs. Keys and generated passwords are mode 0600, ignored, and
never printed by the initializer. Read `.deployment/credentials.json` locally
to obtain the first login passwords. The host and operator each have an age
identity under `.deployment/keys/`; the operator identity permits future edits:

```sh
SOPS_AGE_KEY_FILE="$PWD/.deployment/keys/operator.age" sops .deployment/secrets.yaml
```

Store **password hashes**, not plaintext passwords, in the `office` and `admin`
SOPS entries. They are decrypted before users are created. Changing a password
means changing its hash and rebuilding; `users.mutableUsers = false`.
Nextcloud sign-in is interactive; its credentials use the desktop keyring.

Always address the deployment as `./.deployment`, or its Git URL. **Never use
`path:.deployment`**: path flakes can copy ignored private keys into the Nix
store. Never add private files with `git add -f`. Public forks and CI need no
decryption keys and must not build a source tree containing ignored secrets.

## Evaluate and build

```sh
nix fmt -- --check flake.nix modules/*.nix home/*.nix packages/*.nix examples/*.nix
nix eval ./.deployment#nixosConfigurations.office-test.config.system.build.toplevel.drvPath
nix build --option builders '' \
  ./.deployment#nixosConfigurations.office-test.config.system.build.toplevel \
  ./.deployment#nixosConfigurations.office-test.config.system.build.diskoScript \
  --out-link .deployment/result
```

`result` is the installed system and `result-1` is the disk preparation script.
Build on the administrative machine using `cache.nixos.org`. AWS builders are
an explicit alternative via nix-aws-build-infra after reviewing cost; this
project does not provision AWS resources or publish a binary cache.

The cached LibreOffice binary is supplemented with the matching official
Bulgarian translations and dictionaries. The language-pack URL and hash are
fixed. Updating LibreOffice requires updating that version and hash together;
an assertion prevents accidentally mixing versions. The initial tabbed layout
is seeded only for a new user profile, preserving later user preferences.

## Installation from a running rescue USB

**The BIOS disk layout destroys the selected internal disk.** It creates GPT,
a 1 MiB BIOS boot partition, 4 GiB swap and an ext4 root. zram uses 50% of RAM
at higher priority than disk swap. No backup is performed by this project.

1. Verify the rescue host key, disk ID/model/capacity and that the selected disk
   is not the rescue USB. Keep SSH access to the live system available.
2. Transfer the small `result-1` closure to the rescue system and execute that
   script as root. It formats and mounts the target at `/mnt`. Enable the new
   swap partition for the remaining installation on low-memory machines.
3. Stream the built system closure directly to the target's `/mnt` store:
   `nix-store --store /mnt --import`. Do not first import the system into the
   RAM-backed live store. `nix-store --export` with its full requisites on the
   controller supplies the stream; compression can reduce network traffic.
4. Provision the host age identity to `/mnt/var/lib/sops-nix/key.txt`, root-owned
   and mode 0600, using the verified SSH connection. This is a runtime file,
   never a Nix input. Verify the closure in the `/mnt` store.
5. Run `nixos-install --root /mnt --system SYSTEM_STORE_PATH --no-root-password`
   from the live system, install GRUB, then reboot into the internal SSD.

Validate these exact store options against the running rescue Nix version.
Avoid nixos-anywhere kexec or target-side evaluation on low-memory machines.
Retain generated credentials and the operator identity securely outside Git.

The included installer automates these steps through an already established,
host-key-verified SSH control master. It verifies that the built disk ID matches
the requested disk and refuses USB or mounted disks. Without `--execute`, it
only checks preconditions. Use the same target/user as the existing master:

```sh
python3 scripts/install-built.py --target nixos@RESCUE_IP \
  --socket /path/to/rescue-control.sock \
  --disk /dev/disk/by-id/ata-YOUR_INTERNAL_SSD
# Repeat with --execute --reboot to erase, install and reboot.
```

The installed SSH host public key is captured over the trusted rescue session
in `.deployment/known_hosts`; use that file for the first admin connection.
The old live-system key in your normal known_hosts is not removed or bypassed.

After reboot, check graphical login, administrative SSH, browser, Writer/Calc,
Nextcloud startup and memory pressure. Configure Nextcloud and select folders
before syncing a large account. Test printing/scanning when devices are present.
No extended test suite or machine backup is required for the experimental host.

## Updates

Update the public inputs explicitly, evaluate and build, and commit the tested
source. Update the private flake's `nix2office` URL to the new immutable revision,
then run `nix flake update --flake .deployment nix2office` and rebuild.
Keep `system.stateVersion` and `home.stateVersion` at their installation value.
System upgrades and reboot are manual. Previous boot generations remain
available; selecting one does not recover erased data or rotate old credentials.

Before publication inspect `git ls-files` and scan tracked content for private
keys, password hashes, addresses and host identifiers. Only the generic public
repository belongs on GitHub; `.deployment/` has no public remote.

MIT licensed. Application packages retain their own licenses.
