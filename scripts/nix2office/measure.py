"""Bounded, read-only measurements. Short decode tests; never changes settings.

runner has subprocess.run's interface; tests inject it without probing the host.
Video measures VA-API decode against software decode; memory records zram, swap,
swappiness, OOM daemons, PSI pressure and an optional bounded page-out probe.
Missing tools or devices remain honest unknown, never a guess.
"""
import argparse
import ctypes
import ctypes.util
import json
import mmap
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time

from .hardware import RULES_VERSION
from .diagnostics import _write_json


TIMEOUT = 30
PAGE_SIZE = 4096
MADV_PAGEOUT = 21
STATUSES = ("pass", "warning", "unknown", "not-applicable")
UNAVAILABLE = "Няма достъп, липсва инструмент или проверката не завърши."
DECODE_ENTRYPOINTS = ("VAEntrypointVLD", "VAEntrypointIDCT", "VAEntrypointMoComp")
RESOLUTIONS = {
    "360p": (640, 360),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}


def _check(status, message, **details):
    return {"status": status, "message": message, "details": details}


def _run(runner, args, env, timeout=TIMEOUT):
    try:
        return runner(args, capture_output=True, text=True, timeout=timeout,
                      check=False, env=env)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def _child_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def _render_node():
    try:
        nodes = sorted(Path("/dev/dri").glob("renderD*"))
    except OSError:
        return None
    return str(nodes[0]) if nodes else None


def _driver_dir(environ):
    candidates = [p for p in environ.get("LIBVA_DRIVERS_PATH", "").split(":") if p]
    candidates.append("/run/opengl-driver/lib/dri")
    for directory in candidates:
        try:
            path = Path(directory)
            if path.is_dir() and any(path.glob("*_drv_video.so")):
                return directory
        except OSError:
            continue
    return None


def _vainfo(run):
    result = run(["vainfo", "--display", "drm"])
    if result is None:
        return None
    text_out = result.stdout or ""
    driver = None
    match = re.search(r"Driver version:\s*(.+)", text_out)
    if match:
        driver = " ".join(match.group(1).split())[:128]
    capabilities = re.findall(
        r"\b(VAProfile[A-Za-z0-9_]+)\s*:\s*(VAEntrypoint[A-Za-z0-9_]+)\b", text_out)

    def has(prefix):
        return any(profile.startswith(prefix) and entrypoint in DECODE_ENTRYPOINTS
                   for profile, entrypoint in capabilities)

    return {
        "driver": driver,
        "h264_decode": has("VAProfileH264"),
        "vp9_decode": has("VAProfileVP9"),
        "av1_decode": has("VAProfileAV1"),
        "hevc_decode": has("VAProfileHEVC"),
        "capability_count": len(capabilities),
    }


def _decode(run, render, size):
    """Return a decode measurement dict, or None when it cannot be produced."""
    if render is None:
        return None
    width, height = size
    clip = "/tmp/nix2office-measure-h264-{}x{}.mp4".format(width, height)
    generated = run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=duration=4:size={}x{}:rate=30".format(width, height),
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=4",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-y", clip,
    ])
    if generated is None or generated.returncode != 0:
        return None
    before = _child_cpu()
    sw = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", clip, "-f", "null", "-"])
    sw_cpu = _child_cpu() - before
    before = _child_cpu()
    hw = run(["ffmpeg", "-hide_banner", "-loglevel", "error",
              "-hwaccel", "vaapi", "-vaapi_device", render,
              "-i", clip, "-f", "null", "-"])
    hw_cpu = _child_cpu() - before
    sw_ok = sw is not None and sw.returncode == 0
    hw_ok = hw is not None and hw.returncode == 0
    if not sw_ok and not hw_ok:
        return None
    return {
        "hw_success": hw_ok,
        "sw_success": sw_ok,
        "hw_cpu_s": round(hw_cpu, 3) if hw_ok else None,
        "sw_cpu_s": round(sw_cpu, 3) if sw_ok else None,
    }


def _video_decode(run, resolution):
    size = RESOLUTIONS.get(resolution, RESOLUTIONS["360p"])
    base = {"resolution": resolution}
    facts = _vainfo(run)
    if facts is None:
        return _check("unknown", UNAVAILABLE, driver=None, h264_decode=None,
                      vp9_decode=None, av1_decode=None, hevc_decode=None, decode=None, **base)
    if facts["capability_count"] == 0:
        return _check("unknown", "vainfo не откри VA-API профили; провери драйвера и firmware.",
                      driver=facts["driver"], h264_decode=False, vp9_decode=False,
                      av1_decode=False, hevc_decode=False, decode=None, **base)
    base.update({key: facts[key] for key in ("driver", "h264_decode", "vp9_decode", "av1_decode", "hevc_decode")})
    measurement = _decode(run, _render_node(), size)
    if measurement is None:
        return _check("unknown", "VA-API възможности са налични, но декодирането не можа да се измери.",
                      decode=None, **base)
    if measurement["sw_success"] and measurement["hw_success"]:
        ratio = measurement["hw_cpu_s"] / max(measurement["sw_cpu_s"], 1e-9)
        measurement["offload_ratio"] = round(ratio, 3)
        if ratio < 0.85:
            return _check("pass", "Хардуерното H.264 декодиране намалява измереното CPU.",
                          decode=measurement, **base)
        return _check("warning", "VA-API е наличен, но измереното CPU намаление е малко.",
                      decode=measurement, **base)
    if measurement["sw_success"]:
        return _check("warning", "Софтуерното декодиране мина, но VA-API декодирането не успя.",
                      decode=measurement, **base)
    return _check("warning", "VA-API декодирането мина, но софтуерното сравнение не бе налично.",
                  decode=measurement, **base)


def _read_text(path):
    try:
        return Path(path).read_text(encoding="ascii", errors="replace")
    except OSError:
        return None


def _meminfo():
    text = _read_text("/proc/meminfo")
    if text is None:
        return {}
    fields = {}
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if sep and rest.split():
            fields[key.strip()] = int(rest.split()[0])
    return fields


def _swappiness():
    text = _read_text("/proc/sys/vm/swappiness")
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def _swaps():
    text = _read_text("/proc/swaps")
    if text is None:
        return []
    devices = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            try:
                devices.append({
                    "device": parts[0],
                    "size_mib": int(parts[2]) // 1024,
                    "used_mib": int(parts[3]) // 1024,
                    "priority": int(parts[4]),
                })
            except ValueError:
                continue
    return devices


def _zram_sizes(path):
    """Return (orig_data_size, compr_data_size) in bytes across kernel versions."""
    orig_text = _read_text(path / "orig_data_size")
    compr_text = _read_text(path / "compr_data_size")
    if orig_text is not None and compr_text is not None:
        return int(orig_text.strip() or "0"), int(compr_text.strip() or "0")
    # Newer kernels (6.11+) consolidate these into mm_stat:
    # orig_data_size compr_data_size mem_used_total mem_limit mem_used_max ...
    mm_stat = _read_text(path / "mm_stat")
    if mm_stat is not None:
        parts = mm_stat.split()
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    return 0, 0


def _zram():
    devices = []
    try:
        paths = sorted(Path("/sys/block").glob("zram*"))
    except OSError:
        return []
    for path in paths:
        try:
            algorithm = _read_text(path / "comp_algorithm") or ""
            match = re.search(r"\[(\w+)\]", algorithm)
            disksize = int((_read_text(path / "disksize") or "0").strip() or "0")
            orig, compr = _zram_sizes(path)
            devices.append({
                "name": path.name,
                "algorithm": match.group(1) if match else algorithm.strip(),
                "disksize_mib": disksize // (1024 * 1024),
                "data_mib": round(orig / (1024 * 1024), 3),
                "compressed_mib": round(compr / (1024 * 1024), 3),
                "ratio": round(orig / compr, 3) if compr > 0 else None,
            })
        except (OSError, ValueError):
            continue
    return devices


def _pressure():
    text = _read_text("/proc/pressure/memory")
    if text is None:
        return {}
    result = {}
    for line in text.splitlines():
        if line.startswith("some"):
            match = re.search(r"avg60=([0-9.]+)", line)
            result["some_60s"] = float(match.group(1)) if match else None
        elif line.startswith("full"):
            match = re.search(r"avg60=([0-9.]+)", line)
            result["full_60s"] = float(match.group(1)) if match else None
    return result


def _oom(run):
    states = {}
    for unit in ("systemd-oomd", "earlyoom"):
        result = run(["systemctl", "is-active", unit])
        states[unit] = (result.stdout or "").strip() if result is not None else "unknown"
    return states


def _zram_totals():
    devices = _zram()
    return sum(d["data_mib"] for d in devices), sum(d["compressed_mib"] for d in devices)


def _disk_swap_used():
    return sum(d["used_mib"] for d in _swaps() if not d["device"].startswith("/dev/zram"))


def _madvise_pageout(buf, size):
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        address = ctypes.addressof(ctypes.c_char.from_buffer(buf))
    except (OSError, AttributeError, TypeError):
        return False
    return libc.madvise(ctypes.c_void_p(address), ctypes.c_size_t(size), ctypes.c_int(MADV_PAGEOUT)) == 0


def _probe(probe_mib, total_mib):
    """Allocate, touch, page out and measure zram; safe and bounded."""
    if probe_mib <= 0:
        return None
    if total_mib:
        probe_mib = min(probe_mib, total_mib // 3)
    if probe_mib < 32:
        return {"skipped": "твърде малък headroom за probe"}
    size = probe_mib * 1024 * 1024
    data_before, compressed_before = _zram_totals()
    disk_before = _disk_swap_used()
    buf = mmap.mmap(-1, size)
    try:
        # Unique per page so zram does not deduplicate, but still compressible.
        for i in range(size // PAGE_SIZE):
            page = bytearray([0xAA]) * PAGE_SIZE
            page[0:8] = i.to_bytes(8, "little")
            buf.write(page)
        buf.flush()
        pageout_ok = _madvise_pageout(buf, size)
        time.sleep(1.5)
        data_after, compressed_after = _zram_totals()
        disk_after = _disk_swap_used()
    finally:
        buf.close()
    data_delta = data_after - data_before
    compressed_delta = compressed_after - compressed_before
    return {
        "probe_mib": probe_mib,
        "pattern": "per-page unique, compressible",
        "pageout_ok": pageout_ok,
        "zram_data_delta_mib": round(data_delta, 3),
        "zram_compressed_delta_mib": round(compressed_delta, 3),
        "ratio": round(data_delta / compressed_delta, 3) if compressed_delta > 0 else None,
        "disk_swap_used_delta_mib": round(disk_after - disk_before, 3),
    }


def _memory(run, probe_mib=0):
    mem = _meminfo()
    if not mem:
        return _check("unknown", UNAVAILABLE)
    total_mib = mem.get("MemTotal", 0) // 1024
    available_mib = mem.get("MemAvailable", 0) // 1024
    zram = _zram()
    swappiness = _swappiness()
    swaps = _swaps()
    oom = _oom(run)
    psi = _pressure()
    disk_swap_used = _disk_swap_used()
    probe = _probe(probe_mib, total_mib)
    warnings = []
    status = "pass"
    if not zram:
        status = "warning"
        warnings.append("Няма активен zram; паметта се swap-ва само към диск.")
    if psi.get("full_60s") is not None and psi["full_60s"] > 10:
        status = "warning"
        warnings.append("PSI full 60s = {} (натиск върху паметта).".format(psi["full_60s"]))
    if available_mib < 128:
        status = "warning"
        warnings.append("Наличната RAM е под 128 MiB.")
    if disk_swap_used > 0:
        status = "warning"
        warnings.append("Използва се дисков swap ({} MiB).".format(disk_swap_used))
    message = "; ".join(warnings) if warnings else "В момента няма отчетен натиск върху паметта."
    return _check(status, message,
                  mem_total_mib=total_mib, mem_available_mib=available_mib,
                  swappiness=swappiness, zram=zram, swaps=swaps, oom=oom, psi=psi,
                  disk_swap_used_mib=disk_swap_used, probe=probe)


def collect_report(*, runner=None, environ=None, resolution="360p", memory_only=False, probe_mib=0):
    """Return JSON-safe measurements. Missing tools always remain unknown."""
    env = dict(os.environ if environ is None else environ)
    env.update(LC_ALL="C", LANG="C")
    runner = subprocess.run if runner is None else runner
    driver_dir = _driver_dir(env)
    if driver_dir:
        env["LIBVA_DRIVERS_PATH"] = driver_dir
    run = lambda args: _run(runner, args, env)
    measurements = {"memory": _memory(run, probe_mib)}
    if not memory_only:
        measurements["video_decode"] = _video_decode(run, resolution)
    return {
        "schema_version": 1,
        "read_only": True,
        "kernel_version": platform.release(),
        "rules_version": RULES_VERSION,
        "measurements": measurements,
    }


def _readable(report):
    statuses = {"pass": "проверено", "warning": "внимание", "unknown": "неизвестно", "not-applicable": "неприложимо"}
    lines = [
        "nix2office — измервания (кратки, само за четене)",
        "Kernel: " + report.get("kernel_version", "unknown") + "; правила: " + report.get("rules_version", "unknown"),
    ]
    video = report["measurements"].get("video_decode")
    if video:
        lines.append("Видео (H.264 " + video["details"].get("resolution", "360p") + ") [" + statuses[video["status"]] + "]: " + video["message"])
    memory = report["measurements"].get("memory")
    if memory:
        lines.append("Памет [" + statuses[memory["status"]] + "]: " + memory["message"])
        d = memory["details"]
        lines.append("  RAM: общо {}/налично {} MiB; swappiness {}".format(d.get("mem_total_mib"), d.get("mem_available_mib"), d.get("swappiness")))
        if d.get("zram"):
            lines.append("  zram: " + ", ".join("{}={}/ratio {}".format(z["algorithm"], z["disksize_mib"], z["ratio"]) for z in d["zram"]))
        lines.append("  oom: systemd-oomd={}, earlyoom={}".format(d.get("oom", {}).get("systemd-oomd"), d.get("oom", {}).get("earlyoom")))
        lines.append("  PSI full 60s: {}".format(d.get("psi", {}).get("full_60s")))
        probe = d.get("probe")
        if probe and "ratio" in probe:
            lines.append("  probe: {} MiB, ratio {}, disk swap delta {} MiB".format(probe["probe_mib"], probe["ratio"], probe["disk_swap_used_delta_mib"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Кратки измервания на nix2office (без промяна на настройки).")
    parser.add_argument("--json", action="store_true", help="Изведи JSON.")
    parser.add_argument("--output", type=Path, help="Запиши JSON атомарно с права 0600.")
    parser.add_argument("--resolution", choices=("360p", "720p", "1080p"), default="360p",
                        help="Резолюция на тестовия H.264 клип.")
    parser.add_argument("--memory-only", action="store_true", help="Само измерване на паметта (без видео).")
    parser.add_argument("--probe-mib", type=int, default=0, help="Разпредели MiB и измери zram ratio (0 = без probe).")
    args = parser.parse_args(argv)
    report = collect_report(resolution=args.resolution, memory_only=args.memory_only, probe_mib=args.probe_mib)
    if args.output:
        _write_json(args.output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_readable(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

