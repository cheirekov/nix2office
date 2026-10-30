# ArtCraft font discovery

## Evidence and scope

Investigated on 2026-10-30 with Nix 2.31.4, x86_64-linux and the repository's
locked nixpkgs revision `718f670e845328e9c2cecdd832835712b2cbd065` (Fontconfig
2.17.1). Release versions and source hashes remain unchanged.

- [WordCraft 0.12.0 font directory selection](https://github.com/storytold/wordcraft/blob/3de6ff95af86c19d67030cd96dba15cd6a45a25e/crates/fonts/src/fontdb/names.rs#L201):
  scans FHS/user font directories and Flatpak's `/run/host/fonts` paths. Its
  [catalog scanner](https://github.com/storytold/wordcraft/blob/3de6ff95af86c19d67030cd96dba15cd6a45a25e/crates/fonts/src/fontdb/catalog.rs#L190)
  reads TTF/OTF/TTC/OTC files directly. It does not consult Fontconfig.
- [GridCraft 0.13.0 menu construction](https://github.com/storytold/gridcraft/blob/43284377d2466037628e57d8ad0c891778fdb45c/crates/ui-egui/src/fonts.rs#L268)
  adds a [fixed list of Office font names](https://github.com/storytold/gridcraft/blob/43284377d2466037628e57d8ad0c891778fdb45c/crates/ui-egui/src/ribbon/home.rs#L590)
  before discovered families. Seeing Arial/Calibri there does not establish
  that their files are installed or that they render with those faces.
- The installed wrappers only supplied `LD_LIBRARY_PATH`. `readelf` showed
  neither GUI binary linked to Fontconfig; a WordCraft CLI `strace` confirmed
  directory scanning. The packaged trees contain font licence files but no
  separate font files. WordCraft embeds its base fonts with `include_bytes!`;
  its release workflow also embeds craft-fonts. `font.list` in the actual
  binary confirms the embedded families. Retaining the binary preserves them.
- On the booted AMD machine, NixOS Fontconfig found Arial, Carlito, Caladea,
  Courier New and Times New Roman in store paths. The original WordCraft CLI
  listed **48** families and omitted all five (counted from its JSON response).

## Integration

Only WordCraft's GUI and CLI receive the new launcher. A small C helper uses
`FcInitLoadConfigAndFonts` / `FcFontList` to obtain the current font files,
honouring system/user configuration, `FONTCONFIG_FILE` and XDG settings.
It writes NUL-delimited filenames. Fontconfig's `fc-list` formatter cannot
produce these: [2.17.1's escape handler](https://github.com/fontconfig/fontconfig/blob/2.17.1/src/fcformat.c#L176)
turns `\0` into the literal character `0`.

Each launch creates a private temporary symlink tree of readable supported
font files, deduplicates paths, then exposes it read-only at `/run/host/fonts`
with Bubblewrap. A private `/run` permits creating that mount on NixOS without
root; the original `/run` entries, symlinks and other `/run/host` entries are
preserved. HOME, XDG variables, networking, devices and the session are retained.
The tree is removed after the child exits, including a normal CLI error.
No font copies or persistent links are installed in the user's font directory.

This needs working unprivileged user/mount namespaces. A restricted kernel or
container can refuse Bubblewrap; that launch reports an error. This is a font
mount adapter, not a security sandbox. It does not install missing proprietary
fonts, implement Fontconfig aliases in WordCraft's own renderer, or alter
GridCraft's discovery/menu policy.

## Verification

All commands ran from `/home/yc/work/nix2office` unless stated otherwise:

```sh
nix build --no-write-lock-file --no-link --print-out-paths \
  --option builders '' .#artcraft -L
```

Exit 0; all four ArtCraft packages and the combined package were realized.
The combined output is
`/nix/store/crjzhfjh9hi21g5dc7f3sml2nmnahl1z-artcraft-office-experimental`;
WordCraft is `/nix/store/846hg90vg1x8dywcrm320bjjx7lw2lc3-wordcraft-0.12.0`.
The same WordCraft output was independently built as unprivileged `admin` on
the AMD machine using this package expression and the same pinned nixpkgs
source. This did not activate or replace its system generation.

```sh
python3 tests/artcraft-fonts.py \
  --package /nix/store/crjzhfjh9hi21g5dc7f3sml2nmnahl1z-artcraft-office-experimental \
  --font /nix/store/7jk9hn4k0phpcryb8gh1jj857nyfhmdc-carlito-20130920/share/fonts/truetype/Carlito-Regular.ttf \
  --bwrap /nix/store/nnnh2ks97pxsv3cswhmvir8vzi0gc63m-bubblewrap-0.12.0/bin/bwrap
```

Six tests passed locally and on the AMD machine (the latter using the
individual WordCraft output for `--package` and pinned Python 3). They exercise
the real release scanner with FHS fonts hidden: included Fontconfig directories,
custom XDG data paths, spaces/quotes/newlines/shell syntax in a filename,
concurrent launches, font removal, embedded fonts with no configured fonts,
CLI error propagation and temporary-tree cleanup. Run outside the Nix build
sandbox, where nested namespaces may be prohibited. The fixture should be a
non-embedded family such as Carlito (`--family` defaults to Carlito).

Live CLI discovery increased from **48 to 815** families; all five missing
families above became available. The actual patched desktop binary also ran
successfully under Xvfb with an isolated profile on that machine. Its control
API returned the same 815 families and all five names, and its Font dialog was
captured. This verifies an isolated X11/software-rendering session, not the
user's existing desktop session or every document's font rendering. No reboot
or NixOS activation was performed.

Formatter check and scoped `git diff --check` passed.

Cache probes of the WordCraft output's `.narinfo` returned 404 from
`cache.nixos.org` and the configured internal HTTP cache. The configured S3 and
CloudFront endpoints returned 403, so their presence cannot be established.
Bubblewrap's `.narinfo` returned 200 from `cache.nixos.org`; the builds also
substituted pinned dependencies from that cache. No cache publication was
performed. Local realization and a successful target build do not imply that
this new WordCraft output is downloadable from a binary cache.

Rollback: the installed system still uses the original package. Close the test
processes or invoke the installed launcher to return to it; this work did not
modify the active system profile. A future deployment can revert the package
change through the normal NixOS generation workflow.
