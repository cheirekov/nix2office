"""Bounded, read-only measurements. Short decode tests; never changes settings.

runner has subprocess.run's interface; tests inject it without probing the host.
The video check measures VA-API hardware decode against software decode on a
generated H.264 clip. Missing tools, drivers or a render node remain honest
unknown, never a guess.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys

from .hardware import RULES_VERSION
from .diagnostics import _write_json


TIMEOUT = 30
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


def collect_report(*, runner=None, environ=None, resolution="360p"):
    """Return JSON-safe measurements. Missing tools always remain unknown."""
    env = dict(os.environ if environ is None else environ)
    env.update(LC_ALL="C", LANG="C")
    runner = subprocess.run if runner is None else runner
    driver_dir = _driver_dir(env)
    if driver_dir:
        env["LIBVA_DRIVERS_PATH"] = driver_dir
    run = lambda args: _run(runner, args, env)
    return {
        "schema_version": 1,
        "read_only": True,
        "kernel_version": platform.release(),
        "rules_version": RULES_VERSION,
        "measurements": {
            "video_decode": _video_decode(run, resolution),
        },
    }


def _readable(report):
    statuses = {"pass": "проверено", "warning": "внимание", "unknown": "неизвестно", "not-applicable": "неприложимо"}
    lines = [
        "nix2office — измервания (кратки, само за четене)",
        "Kernel: " + report.get("kernel_version", "unknown") + "; правила: " + report.get("rules_version", "unknown"),
    ]
    video = report["measurements"]["video_decode"]
    lines.append("Видео (H.264 " + video["details"].get("resolution", "360p") + ") [" + statuses[video["status"]] + "]: " + video["message"])
    details = video["details"]
    lines.append("  VA-API драйвер: " + (details.get("driver") or "unknown"))
    lines.append("  H.264/VP9/AV1/HEVC декодиране: " + "/".join(
        "да" if details.get(k) else "не" for k in ("h264_decode", "vp9_decode", "av1_decode", "hevc_decode")))
    decode = details.get("decode")
    if decode:
        lines.append("  CPU (hardware/software, секунди): {}/{}".format(decode.get("hw_cpu_s"), decode.get("sw_cpu_s")))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Кратки измервания на nix2office (без промяна на настройки).")
    parser.add_argument("--json", action="store_true", help="Изведи JSON.")
    parser.add_argument("--output", type=Path, help="Запиши JSON атомарно с права 0600.")
    parser.add_argument("--resolution", choices=("360p", "720p", "1080p"), default="360p",
                        help="Резолюция на тестовия H.264 клип.")
    args = parser.parse_args(argv)
    report = collect_report(resolution=args.resolution)
    if args.output:
        _write_json(args.output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_readable(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

