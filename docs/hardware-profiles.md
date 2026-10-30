# Hardware recommendations and CPU policy

Use `nix run .#configure -- --recommend --target rescue-host` for a read-only
report. SSH must already have trusted host/key access; a verified existing
control master also works with `--ssh-config` and `--ssh-socket`. The helper
does not collect SSH passwords. `--probe` saves JSON; `--recommend --hardware-json
/private/path/hardware.json` replays it without connecting. No source pin,
passwords or private deployment generation is needed for these inspection modes.

The report reads the target's CPUID family/model, usable RAM, online CPU threads,
kernel CPU-frequency driver, governors, policy maximum frequency, boot mode,
bound DRM drivers and disks. Available governors are the intersection across
CPU policies, so a choice must work on all reported policies. The reported
maximum is a firmware/driver policy fact, not a measured boost limit or benchmark.
USB/read-only disks remain excluded from suggested installation disks.

## Conservative application suggestions

Light is suggested with less than 4 GiB usable RAM, at most two threads, an AMD
family 14h/16h CPU (decimal 20/22), or a known policy maximum at most 1600 MHz.
These older AMD families include low-power Bobcat/Jaguar/Puma processors; four
cores and ample RAM do not by themselves imply strong single-thread performance.
These are conservative hints, not a performance ranking. If frequency data are
missing, the helper keeps the existing RAM/thread-count fallback. Old JSON/TOML
files remain accepted; re-probe to obtain the additional facts.

Light selects Firefox ESR, LibreOffice and PDF Arranger; Standard additionally
suggests Xournal++. Every application remains selectable. Both use the same
XFCE baseline with compositing disabled, zram and SSD TRIM. Installing one extra
PDF tool does not itself consume RAM while it is closed; the profiles describe
starting application sets, not different CPU acceleration levels.

## CPU governor

The template accepts an optional section:

```toml
[performance]
cpu_governor = "auto"
```

| Value | Meaning |
| --- | --- |
| `auto` | Leave the kernel's governor selection unchanged; default for existing deployments |
| `schedutil` | Scheduler-driven scaling; suggested if available with generic frequency drivers |
| `ondemand` | Dynamic fallback when available and schedutil is not |
| `powersave` | Suggested only with active `intel_pstate` or `amd-pstate-epp`; its semantics depend on the driver |
| `performance` | Request the highest frequency allowed by the policy; optional comparison, not an overclock or guaranteed speedup |

The menu offers Automatic, the detected balanced choice, and Performance if
available. A generic ACPI `powersave` governor can hold a CPU near its minimum
frequency, so it is not recommended simply because its name sounds balanced.
Selected governors map to NixOS `powerManagement.cpuFreqGovernor`. Existing
deployments remain on `auto` unless explicitly changed. If supplied, the saved
available-governor list is checked by Python and Nix; it is not proof that a
different future kernel or firmware will expose the same capabilities.

No minimum/maximum frequency, boost limit, undervolt or hardware power limit is
changed. Performance may increase heat/power draw and thermal limiting can still
apply. Compare real application use after installation before keeping it. The
helper does not change the running rescue environment during discovery.

## AMD CPU and graphics

AMD detection enables AMD microcode instead of Intel microcode. Redistributable
firmware and Mesa graphics were already part of the office baseline. The helper
now recognizes the older `radeon` DRM driver as well as `amdgpu`, and includes
the detected driver in the early-boot modules for splash. It does not force a
different driver merely because the vendor is AMD, or set `amd_pstate=active`
on an older processor without the required capabilities.

For older Radeon hardware, validate actual rendering/video decoding after the
graphical installation. A detected kernel driver alone does not prove VA-API,
browser codec acceleration or modern video-codec support. Generic cached Nixpkgs
packages remain in use; the helper does not switch the entire system to a local
`-march=native` rebuild.

References: [kernel CPU frequency governors](https://www.kernel.org/doc/html/latest/admin-guide/pm/cpufreq.html),
[AMD P-state requirements](https://www.kernel.org/doc/html/latest/admin-guide/pm/amd-pstate.html),
[Radeon/AMDGPU module parameters](https://www.kernel.org/doc/html/latest/gpu/amdgpu/module-parameters.html).

## Peripheral discovery

The probe records PCI class/vendor/device IDs and bound driver names, USB IDs,
and Bluetooth presence from sysfs (including standard USB Bluetooth interfaces).
It flags unbound graphics, audio and network controllers and NVIDIA graphics for
review. This is detection of the rescue environment, not proof that every optional
feature will work after installation. Unknown/proprietary drivers and hybrid PRIME
need model-specific review. The assistant does not guess a supported NVIDIA branch.

Redistributable firmware stays enabled. Additional unfree firmware is offered as
an explicit opt-in and is not a substitute for a missing kernel driver. Detected
Bluetooth recommends BlueZ and Blueman. PipeWire already supplies audio; select
HDMI/analog output in the sound GUI. WirePlumber remembers that personal choice.

See [rescue installation](rescue-install-bg.md) and the future
[cache-first transport plan](cache-install-plan.md).
