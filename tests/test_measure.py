"""Focused checks for the bounded video/decode measurement."""
import io
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import contextlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import nix2office.measure as measure
from nix2office.measure import collect_report


VAINFO_H264 = (
    "vainfo: VA-API version: 1.22 (libva 2.22.0)\n"
    "vainfo: Driver version: Intel i965 driver for Intel(R) Bay Trail - 2.4.1\n"
    "vainfo: Supported profile and entrypoints\n"
    "      VAProfileH264Main            :\tVAEntrypointVLD\n"
    "      VAProfileH264High            :\tVAEntrypointVLD\n"
)


def completed(args, rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, rc, stdout, stderr)


class FakeRunner:
    def __init__(self, vainfo=VAINFO_H264, generate_rc=0, sw_rc=0, hw_rc=0):
        self.vainfo = vainfo
        self.generate_rc = generate_rc
        self.sw_rc = sw_rc
        self.hw_rc = hw_rc
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "vainfo":
            if self.vainfo is None:
                raise FileNotFoundError
            return completed(args, 0, self.vainfo)
        if args[0] == "ffmpeg":
            if "-c:v" in args:
                return completed(args, self.generate_rc)
            if "-hwaccel" in args:
                return completed(args, self.hw_rc)
            return completed(args, self.sw_rc)
        return completed(args, 1)


class MeasureTests(unittest.TestCase):
    def video(self, runner, cpu=None, render="/dev/dri/renderD128", resolution="360p"):
        patches = [patch.object(measure, "_render_node", return_value=render)]
        if cpu is not None:
            patches.append(patch.object(measure, "_child_cpu", side_effect=cpu))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return collect_report(runner=runner, environ={}, resolution=resolution)["measurements"]["video_decode"]

    def test_missing_vainfo_is_unknown(self):
        self.assertEqual(self.video(FakeRunner(vainfo=None))["status"], "unknown")

    def test_vainfo_without_profiles_is_unknown(self):
        video = self.video(FakeRunner(vainfo="vainfo: Driver version: none\n"))
        self.assertEqual(video["status"], "unknown")
        self.assertFalse(video["details"]["h264_decode"])

    def test_hardware_offload_is_pass(self):
        video = self.video(FakeRunner(), cpu=[0.0, 2.0, 2.0, 2.5])
        self.assertEqual(video["status"], "pass")
        self.assertEqual(video["details"]["driver"], "Intel i965 driver for Intel(R) Bay Trail - 2.4.1")
        self.assertTrue(video["details"]["h264_decode"])
        self.assertEqual(video["details"]["decode"]["offload_ratio"], 0.25)
        self.assertEqual(video["details"]["decode"]["hw_cpu_s"], 0.5)
        self.assertEqual(video["details"]["decode"]["sw_cpu_s"], 2.0)

    def test_no_offload_is_warning(self):
        video = self.video(FakeRunner(), cpu=[0.0, 2.0, 2.0, 4.0])
        self.assertEqual(video["status"], "warning")
        self.assertEqual(video["details"]["decode"]["offload_ratio"], 1.0)

    def test_hardware_decode_failure_is_warning(self):
        video = self.video(FakeRunner(hw_rc=1), cpu=[0.0, 2.0, 2.0, 2.5])
        self.assertEqual(video["status"], "warning")
        self.assertTrue(video["details"]["decode"]["sw_success"])
        self.assertFalse(video["details"]["decode"]["hw_success"])

    def test_decode_cannot_run_is_unknown(self):
        video = self.video(FakeRunner(generate_rc=1))
        self.assertEqual(video["status"], "unknown")
        self.assertIsNone(video["details"]["decode"])

    def test_no_render_node_is_unknown(self):
        video = self.video(FakeRunner(), render=None)
        self.assertEqual(video["status"], "unknown")

    def test_resolution_controls_generated_clip(self):
        runner = FakeRunner()
        video = self.video(runner, cpu=[0.0, 2.0, 2.0, 2.5], resolution="720p")
        generate = next(c for c in runner.calls if c[0] == "ffmpeg" and "-c:v" in c)
        self.assertTrue(any("size=1280x720" in a for a in generate))
        self.assertEqual(video["details"]["resolution"], "720p")

    def test_report_is_read_only_and_structured(self):
        report = collect_report(runner=FakeRunner(), environ={})
        self.assertTrue(report["read_only"])
        self.assertEqual(set(report["measurements"]), {"video_decode"})
        self.assertIn("rules_version", report)


if __name__ == "__main__":
    unittest.main()

