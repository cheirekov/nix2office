# Nix2office

A lightweight NixOS 26.05 office desktop for users accustomed to Windows.
The default profile uses Bulgarian, XFCE/Xorg, a bottom taskbar and application
menu, Firefox ESR, LibreOffice with a tabbed toolbar, PDF tools, network printing
and scanning, and the Nextcloud desktop sync client.

## Everyday desktop controls

- The taskbar shows the current keyboard language as text. Click it or press
  **Alt+Shift** to switch between English and the selected Bulgarian layout
  (phonetic or BDS).
  The LightDM login screen also has a keyboard layout selector, so passwords
  can be entered with the appropriate layout before starting the desktop.
- Open **Settings → Звук** (Sound), or the sound settings from the taskbar volume
  icon. In **Configuration**, choose an available analog or HDMI profile; in
  **Output Devices**, choose the output and volume. WirePlumber remembers the
  selection. A connected display must support audio for HDMI playback.
- Firefox ESR is registered with both the desktop's browser helper and its URL
  associations, including links opened by Nextcloud. The browser selected in
  `machine.toml` is reapplied at each Home Manager activation, including its XFCE
  helper and URL associations.
- Application shortcuts are executable, user-owned desktop files. Home Manager
  refreshes the supplied shortcuts on activation; their contents are managed by
  this profile.
- Plymouth's spinner hides most kernel messages during startup. Set
  `nix2office.bootSplash.enable = false;` for text startup. If a machine needs an
  early graphics driver for the splash, add it to that host's
  `boot.initrd.kernelModules` (for example, `"i915"` for supported Intel graphics).

Thunar includes SMB client support: use **Go → Open Location** and enter
`smb://SERVER/SHARE`. The assistant also offers an authenticated Samba server
for one folder, with the selected Workgroup and a trusted LAN. WireGuard uses
NetworkManager; optional Tailscale has Trayscale GUI; ZeroTier uses its daemon
and admin CLI. Account enrollment remains interactive after installation.

## Full installation wizard

From a private working directory on the administrative Linux computer:

```sh
nix run --refresh --option builders '' github:cheirekov/nix2office#install
```

Enter the rescue IP, compare its SSH fingerprint on the console, enter the rescue
password, and follow the hardware/settings menus. The wizard builds locally,
checks the disk, then asks permission and requires the full disk ID before erasing.
`--prepared` reuses a saved deployment for a new installation; `--resume` continues
an interrupted installation on an already mounted target without formatting.
See the [complete Bulgarian beginner guide](docs/rescue-install-bg.md).

Experimental ArtCraft contains **WordCraft, GridCraft, DeckCraft and PdfCraft
only**, with pinned upstream binaries and hashes. The office menu offers it alone
or together with LibreOffice/ONLYOFFICE. In `machine.toml`, set `apps.artcraft = true`
(and `apps.office = "none"` for ArtCraft alone), or build `.#artcraft` separately.
When combined, the main suite retains its default document handlers.

## Maintain an installed machine

Use `nix run github:cheirekov/nix2office#maintain -- --edit` to choose additional
applications and fonts and build locally. Remote activation requires `--apply`,
verified SSH trust, typed hostname confirmation and the admin sudo password.
See the [Bulgarian maintenance guide](docs/maintenance-bg.md).

## Start with the assistant

```sh
nix run --option builders '' .#configure
# An existing .deployment is preserved; prepare another machine with:
nix run --option builders '' .#configure -- --output .deployment/new-office
```

Outside a checkout, run `nix run github:cheirekov/nix2office#configure` from a
private directory. The terminal assistant discovers the **target** hardware,
suggests a light/standard starting profile, then offers menus for browser,
office, PDF tools, Nextcloud, keyboard, sharing and VPN clients. It separates the
login (`maria`), displayed name (`Мария Димитрова`) and optional e-mail.

It prepares a private Git flake and SOPS-encrypted password hashes. It does not
build, erase, install or modify the target. The resulting `machine.toml` remains
the actual configuration input on future rebuilds. See the
[complete guide](docs/configuration-assistant.md),
[editable template](examples/machine.toml) and
[future personal-settings recovery design](docs/personal-settings.md).

To inspect a new target and see recommendations without generating a deployment:

```sh
nix run .#configure -- --recommend --target rescue-host
# Or use a private inventory previously collected with --probe:
nix run .#configure -- --recommend --hardware-json /private/path/hardware.json
```

The assistant considers older low-power CPUs as well as RAM/thread count,
preserves detected `radeon`/`amdgpu` graphics, and offers CPU governors supported
by the target. See [hardware recommendations and CPU policy](docs/hardware-profiles.md).

## Public modules

This flake exports `nixosModules.office`, `nixosModules.disk` (BIOS or UEFI),
`nixosModules.legacy-bios` (compatibility wrapper), `homeManagerModules.office`,
`lib.machineModule file`, `apps.configure`, and `nixosConfigurations.office-example`.
The example has locked accounts and a placeholder disk: **do not install it**.
The office module includes Home Manager and sops-nix. Both disk modules include
disko and require `nix2office.diskDevice` to identify the whole internal disk.
The example targets x86_64; the Bulgarian LibreOffice language pack is x86_64.

The selected desktop login (default `office`) is an ordinary user; `admin` has
password-protected sudo.
Root is locked, automatic graphical login is disabled, and SSH is enabled only
when `nix2office.adminAuthorizedKeys` is populated. The firewall permits SSH
only from the explicitly configured IPv4 `nix2office.adminNetwork` CIDR.
CUPS is a local print client, not a shared print server. Network scanning uses
SANE/airscan; device-specific compatibility still requires a real device test.

## Create a private deployment

First commit the public source. The initializer pins the deployment to that
local Git revision; it never points at an uncommitted working tree. Use the
menus above, or copy and edit `examples/machine.toml` in a private location:

```sh
nix run .#configure -- --config /private/path/machine.toml --check
nix run .#configure -- --config /private/path/machine.toml
nix flake lock ./.deployment
git -C .deployment add machine.toml flake.lock
```

The explicit `scripts/init-deployment.py` accepts the same `--config` under
`nix develop`. Its original `--hostname`, `--disk`, `--admin-network` and
`--admin-key` arguments remain supported with the default office account.

The ignored `.deployment/` is a separate local Git repository. Its tracked
files contain the host configuration, encrypted SOPS hashes, public recipients,
and pinned inputs. Keys and generated passwords are mode 0600, ignored, and
never printed by the initializer. Hidden entered passwords are not saved as
plaintext. If you selected generation, read `.deployment/credentials.json`
locally to obtain the first login passwords. The host and operator each have an age
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

Replace `office-pc` with your TOML hostname (and `.deployment` with your output).

```sh
nix fmt -- --check flake.nix modules/*.nix home/*.nix lib/*.nix packages/*.nix examples/*.nix
nix eval ./.deployment#nixosConfigurations.office-pc.config.system.build.toplevel.drvPath
nix build --option builders '' \
  ./.deployment#nixosConfigurations.office-pc.config.system.build.toplevel \
  ./.deployment#nixosConfigurations.office-pc.config.system.build.diskoScript \
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

**Installation destroys the selected internal disk.** Both layouts use GPT,
4 GiB swap and an ext4 root. BIOS adds a 1 MiB boot partition and GRUB; UEFI
adds a 512 MiB FAT ESP and systemd-boot. Boot the rescue USB in the same mode. zram uses 50% of RAM
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
   from the live system, install the configured bootloader, then reboot into the
   internal SSD.

Validate these exact store options against the running rescue Nix version.
Avoid nixos-anywhere kexec or target-side evaluation on low-memory machines.
Retain generated credentials and the operator identity securely outside Git.

The included installer automates these steps through an already established,
host-key-verified SSH control master. It verifies that the built disk ID matches
the requested disk and refuses USB or mounted disks. For assistant-created
deployments it also checks the rescue boot mode against `machine.toml`. Without `--execute`, it
only checks preconditions. Use the same target/user as the existing master:

```sh
python3 scripts/install-built.py --target nixos@RESCUE_IP \
  --socket /path/to/rescue-control.sock \
  --disk /dev/disk/by-id/ata-YOUR_INTERNAL_SSD
# Repeat with --execute --reboot to erase, install and reboot.
```

After an interrupted transfer, `--resume --execute` reuses the verified `/mnt`
filesystem without formatting and transfers only missing store paths.

The installed SSH host public key is captured over the trusted rescue session
in `.deployment/known_hosts`; use that file for the first admin connection.
The old live-system key in your normal known_hosts is not removed or bypassed.

After reboot, check graphical login, administrative SSH, browser, Writer/Calc,
Nextcloud startup and memory pressure. Configure Nextcloud and select folders
before syncing a large account. Test printing/scanning when devices are present.
No extended test suite or machine backup is required for the experimental host.

## Updates

Update the public inputs explicitly, evaluate and build, and commit the tested
source. Repin an assistant-created deployment with:

```sh
nix run .#configure -- --config .deployment/machine.toml --output .deployment --update
nix flake update --flake .deployment nix2office
```

Alternatively, edit the private flake's `nix2office` URL to the new immutable
revision before updating that input and rebuilding.
Direct edits to `machine.toml` are consumed at the next rebuild; no regeneration
is needed. Changing an installed login name needs a separate migration.
Keep `system.stateVersion` and `home.stateVersion` at their installation value.
System upgrades and reboot are manual. Previous boot generations remain
available; selecting one does not recover erased data or rotate old credentials.

Before publication inspect `git ls-files` and scan tracked content for private
keys, password hashes, addresses and host identifiers. Only the generic public
repository belongs on GitHub; `.deployment/` has no public remote.

For a focused helper check on the build machine:

```sh
nix develop --option builders '' -c python3 -m unittest discover -s tests -v
nix eval --impure --json --expr 'import ./tests/evaluate.nix { root = toString ./.; }'
```

MIT licensed. Application packages retain their own licenses.
