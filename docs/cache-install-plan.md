# Plan: cache-first installation from nixos-rescue

Status: design only. The working installer continues to stream missing paths over authenticated SSH. No cache service or AWS resource is provisioned.

This is milestone M3 of the [project roadmap](roadmap-bg.md), followed by M4
pull updates. Our experimental machines will use the **existing
nix-aws-build-infra cache**, publishing selected full system closures and their
dependencies. A second cache is not needed for the first tests. Cache URL and
public keys belong in private deployment settings; signing identities and
decrypted secrets must never be published. Independent users can supply an
existing endpoint or create their own through the separate infrastructure
project. This document does not enable any of these transports yet.

## Why

The administrative machine should evaluate and build; the rescue target should download available binaries directly into the SSD store at `/mnt`. This avoids relaying official binaries through the controller and re-exporting/recompressing the whole closure. It does not eliminate the target's network, CPU, decompression or disk limits. At 100 Mbit/s, 10 GiB of uncompressed data takes roughly 14 minutes at ideal line rate; compressed transfer size must be measured separately.

## Incremental implementation

1. Record negotiated link speed, total closure/NAR bytes, actual compressed bytes, transfer wall time, and target CPU/disk load for the existing path. Compare identical closures and empty target stores, not unrelated GC results on the controller.
2. Add an explicit transport choice: `ssh` (current default), `cache-first` and eventually `cache-only`. Keep hardware, secret handling, disk confirmation and installation identical across transports.
3. After disko mounts the SSD, let the target substitute the exact prebuilt closure from the official cache, using the running rescue Nix version's verified local-store options for `/mnt`. Do not evaluate/build on the target and do not download into the RAM-backed live store.
4. Transfer only remaining locally built system, Home Manager, Bulgarian language-pack and custom ArtCraft paths over the existing trusted SSH stream. Report cache hits, misses and remaining bytes. Resume must transfer only missing paths and must never reformat.
5. Use the existing nix-aws-build-infra cache as an explicit deployment input for our tests, with signatures and a public trust key. Publish only selected complete closures. Keep signing identities and SOPS age keys outside the Nix store. Fetch hashes of upstream ArtCraft artifacts remain pinned independently.
6. Document a supplied endpoint or separate cache-only infrastructure for independent users. Plan costs, authentication, teardown and retention before any new provisioning. Clients need read access, not publisher credentials. A short-lived controller LAN cache remains an optional later alternative.

## Acceptance

Compare current SSH and cache-first on the same 100 Mbit/s and gigabit LAN where available. Record actual speed and RAM/store usage. Simulate one interruption, ensure only missing paths are retried, and fail closed on invalid signatures. Confirm the host age identity never appears in cache publication or build inputs. A complete closure must be present on the SSD before bootloader installation/reboot.

## Open questions

- Which compressed cache format gives the best end-to-end result on Celeron J1800 and AMD A6-1450?
- Can official-cache access overlap with transfer of custom paths without increasing target memory pressure?
- What retention policy should apply to the explicitly selected experimental system closures and their dependencies?
- Which Nix store commands work consistently on the project's supported rescue versions? Validate before exposing flags in the beginner guide.
