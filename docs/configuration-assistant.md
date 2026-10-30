For the complete rescue → hardware → configuration → build → installation flow,
use `nix run github:cheirekov/nix2office#install` and the
[Bulgarian step-by-step guide](rescue-install-bg.md). `#configure` below retains
its preparation-only behavior.

# Configuration assistant

The assistant prepares a private flake from an editable `machine.toml`. It does
not format a disk, install or activate NixOS, start a VPN, or sign in to accounts.
Menus use arrow keys and Enter; VPN checkboxes use Space. Ctrl+C cancels.

## Start with the target's hardware

From a clean, committed checkout:

```sh
nix run --option builders '' .#configure
# Keep an existing deployment intact by choosing a new output:
nix run --option builders '' .#configure -- --output .deployment/new-office
```

Without a checkout, use the public app from a private working directory:

```sh
nix run --option builders '' github:cheirekov/nix2office#configure
```

The helper pins its generated flake to an immutable public Git revision. In a
local checkout it requires committed changes; the packaged app knows its public
revision. `--source github:OWNER/REPO/FULL_40_DIGIT_REVISION` supports a fork.
Inside another Git repository, the output must be covered by private ignore
rules. Existing directories are never replaced by a fresh preparation.

Choose **remote SSH**, **this computer**, **saved JSON**, or **manual**. Only
choose this computer if it is the intended installation target. Remote probing
requires an already trusted host key and working key authentication; the helper
never asks for an SSH password or disables host-key checking. It reads `/proc`,
sysfs, `lsblk` and persistent disk aliases without sudo or modifications.

```sh
nix run .#configure -- --target rescue-host --output .deployment/new-office
# Optional: --ssh-config /path/to/config --ssh-socket /path/to/control.sock

# Alternatively, collect facts on the target, then transfer the JSON securely:
nix run .#configure -- --probe > hardware.json
nix run .#configure -- --hardware-json hardware.json --output .deployment/new-office
```

Hardware reports contain device identifiers: keep them private. The target
needs Linux and `lsblk`; it does not need Python for remote discovery. Suggested
disks exclude USB, read-only devices and disks without a persistent by-id. A
mounted disk may be selected for a **future** installation; the separate
installer still refuses to format it while mounted. Manual input cannot prove
which physical device was selected. Installation needs a whole internal disk.

Recommendations are deliberately simple:

| Detected hardware | Starting suggestion |
| --- | --- |
| Less than 4 GiB usable RAM, or at most two CPU threads | Light: Firefox ESR, LibreOffice, PDF Arranger |
| At least 4 GiB and more than two threads | Standard: same apps plus Xournal++ |
| Less than 2 GiB | Few browser tabs, selective Nextcloud sync, enable only needed VPN services |

These are editable suggestions, not memory benchmarks or capacity guarantees.
Profiles select initial choices; explicit `[apps]` values take precedence.
Both profiles use XFCE/Xorg. x86_64 Linux is currently required, including by the
pinned Bulgarian LibreOffice bundle. CPU vendor, graphics driver and rescue
boot mode are detected; BIOS/UEFI is confirmed in the menu. UEFI uses
systemd-boot and an ESP; BIOS uses GRUB. This is not a Secure Boot setup.

## Choices and identity

[The complete template](../examples/machine.toml) lists every accepted field.
The essential distinction is:

```toml
[user]
name = "maria"
full_name = "Мария Димитрова"
email = "maria@example.org"
```

`name` is the Linux login and `/home/maria`; `full_name` is displayed at login.
The e-mail is optional metadata for future integrations. Home Manager exposes
these fields in `~/.config/nix2office/user.json`. They are configuration, not
secrets, and are also visible in the local Nix store. No mail/Nextcloud/VPN
account is configured from this address.

| Selection | Values and behavior |
| --- | --- |
| Browser | `firefox-esr`, `chromium`, `brave`, `google-chrome`; matching desktop shortcut, XFCE browser helper and HTTP/HTTPS associations |
| Office | Menu: LibreOffice, ONLYOFFICE, experimental ArtCraft, either main suite + ArtCraft, or no office. TOML keeps `office = "libreoffice"`, `"onlyoffice"` or `"none"`, with a separate `artcraft` boolean. ArtCraft alone is `office = "none"` and `artcraft = true`. |
| PDF | `pdfarranger` for page ordering/merging/splitting; `xournalpp` for handwriting/annotations; `both`; `none`. Atril always reads PDFs. LibreOffice includes Draw for basic PDF edits. These tools do not promise Acrobat-equivalent document fidelity. |
| Nextcloud | Optional desktop client and autostart; accounts and folders chosen in its GUI |
| Keyboard | `phonetic` or `bds`, alongside US English; language indicator and Alt+Shift, including a login layout selector |
| Splash | On/off; spinner with detected early graphics driver where supported |

Google Chrome is proprietary: choosing it allows that package's unfree license;
the project does not enable every unfree package. Browser RAM usage depends on
workload; the assistant makes no unsupported ranking of browser alternatives.

## Sharing and VPNs

Workgroup defaults to `WORKGROUP` and is editable. It groups SMB machines; it
is neither authentication nor Active Directory enrollment.

- `sharing.mode = "client"`: browse `smb://SERVER/SHARE` from Thunar. No file
  server is started.
- `sharing.mode = "both"`: additionally serve **one dedicated folder** under
  the desktop user's home. SMB2+, no guest login, only that user, and TCP 445
  allowed from the specified IPv4 LAN CIDR. Choose read-only or writable access.
  After installation, admin sets a separate Samba credential with
  `sudo smbpasswd -a maria`. Use `\\HOST\Shared` from Windows. Automatic Windows
  discovery/NetBIOS and domain joining are not included.

The VPN menu selects installed clients/services, not credentials:

- **WireGuard:** NetworkManager supports WireGuard natively. Import a `.conf`
  through its connection editor or `nmcli connection import type wireguard file
  /private/path/wg.conf`. Private keys belong in runtime profiles, never TOML.
- **Tailscale:** its daemon plus Trayscale GUI, configured so the desktop user
  can operate the local client. Sign in through Trayscale after installation.
  Trayscale is a separate tray app, not a NetworkManager plugin. No exit-node or
  subnet-router role is enabled by this template.
- **ZeroTier:** its daemon, optional public network IDs in TOML, and admin CLI
  management (`sudo zerotier-cli join NETWORK_ID`). The network controller may
  require approval. There is no bundled NetworkManager plugin or ZeroTier GUI.
  Removing an ID from TOML does **not** leave a previously joined network:
  explicitly run `sudo zerotier-cli leave NETWORK_ID`.

Tailscale/ZeroTier keep their state under `/var/lib`; NetworkManager is told to
leave their interfaces alone. Enabling these options can open their daemon's
UDP transport port; SSH and SMB keep their separately configured LAN rules.
VPN enrollment and account/device identity are post-installation steps.

## Passwords and private output

Review the selected machine before generating files. Choose hidden password
prompts (at least eight characters) or generated random passwords. Entered
passwords are never written as plaintext; generated passwords are only in the
ignored mode-0600 `credentials.json`. The helper sends passwords to `mkpasswd`
via stdin, then SOPS-encrypts **yescrypt hashes**, also through stdin. Child
output is captured so errors do not echo secret input.

The private directory is mode 0700 and contains its own Git repository:

- `machine.toml`, `flake.nix`, `host.nix`: declarative configuration.
- `secrets.yaml`: encrypted `office` and `admin` hashes. `office` is a secret
  role name even when the actual desktop login is `maria`.
- `.sops.yaml`: public age recipients; `.nix2office.json`: managed-deployment marker.
- `keys/host.age`, `keys/operator.age`: private identities, ignored, mode 0600.

The office user has no sudo; `admin` has password-protected sudo. SSH is disabled
unless a public administrator key and trusted LAN are supplied. Root and SSH
password login remain disabled. The host age key must be provisioned before
first activation, as described in the main README.

**Never** use `path:.deployment`, `git add -f` for private files, or put passwords,
auth tokens or private keys in TOML/Nix strings. Always use the private **Git**
flake. The helper does not migrate the existing experimental deployment.

## Edit and rebuild

The TOML is a real input read by the Nix modules on every evaluation, not a
one-time export. To validate a hand-edited file without prompts or writes:

```sh
nix run .#configure -- --config .deployment/new-office/machine.toml --check
```

To prepare from a copied template, including fresh hidden password prompts:

```sh
cp examples/machine.toml /private/path/machine.toml
# Edit disk, names, LAN and application choices first.
nix run .#configure -- --config /private/path/machine.toml --output .deployment/new-office
# Add --generate-passwords for unattended generation.
```

Then lock, evaluate and build. Replace `office-pc` with the configured hostname:

```sh
nix flake lock ./.deployment/new-office
git -C .deployment/new-office add machine.toml flake.lock
nix eval ./.deployment/new-office#nixosConfigurations.office-pc.config.system.build.toplevel.drvPath
nix build --option builders '' \
  ./.deployment/new-office#nixosConfigurations.office-pc.config.system.build.toplevel \
  ./.deployment/new-office#nixosConfigurations.office-pc.config.system.build.diskoScript \
  --out-link .deployment/new-office/result
```

Installation remains a separate deliberate operation; see the main README.
After installation, ordinary edits to applications/displayed name/e-mail/layout
need validation and rebuild. The login name is guarded: renaming an installed
user requires an explicit home/ownership/keyring migration or a new deployment.
Do not use the disk-formatting installer to apply ordinary updates.

To repin an assistant-created deployment to a newly committed public source,
without rotating secrets:

```sh
nix run .#configure -- --config .deployment/new-office/machine.toml \
  --output .deployment/new-office --update
nix flake update --flake .deployment/new-office nix2office
```

`--update` refuses legacy deployments and login renames and preserves the age
keys, encrypted hashes and generated credentials. Direct TOML edits do not
require running it. The explicit `scripts/init-deployment.py --config ...`
interface is also available under `nix develop`; its old hostname/disk/LAN/key
arguments still work.

For future backup of mutable personal preferences, see
[Personal settings and recovery](personal-settings.md). No backup job is enabled.

## New hardware and access controls

The admin SSH question defaults to Yes. Public keys can be selected from a reachable
SSH agent (including GPG/YubiKey), pasted or loaded from a `.pub` file. Listing
public keys does not sign or change hardware touch policies. Check the displayed
fingerprint; a `cardno:` comment alone is not proof of hardware backing. Declining
SSH prints an explicit warning and requires another confirmation.

User logins accept internal dots, for example `yordan.cheyrekov`. VPN checkboxes
can all be cleared; clients can be added by editing TOML and rebuilding later.

`[devices].bluetooth` enables BlueZ/Blueman; detected Bluetooth sets the wizard's
initial recommendation. `unfree_firmware` is an explicit opt-in to the additional
NixOS firmware set. Redistributable firmware is always included. PCI class/vendor/device
IDs, bound drivers and USB IDs are collected without extra tooling. Unbound network,
graphics or audio controllers are reported for review. NVIDIA is flagged for PCI-ID/driver
branch/PRIME review, with no automatic proprietary driver selection.

`[apps].artcraft = true` adds pinned experimental WordCraft, GridCraft, DeckCraft and
PdfCraft packages alongside the selected main office suite. It includes no Launcher.
