"""Focused checks for the FreeRDP launcher: no password in argv, correct flags."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rdp-launch.py"
_spec = importlib.util.spec_from_file_location("rdp_launch", _SCRIPT)
rdp_launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rdp_launch)


def write_config(tmp, profiles, redirect=None, shared="/home/maria/Shared", fullscreen=False, unicode_keyboard=False, gfx="auto"):
    config = {
        "credentials": "interactive",
        "redirect": redirect or ["smartcard", "clipboard", "audio", "drives", "usb"],
        "shared": shared,
        "fullscreen": fullscreen,
        "unicode_keyboard": unicode_keyboard,
        "gfx": gfx,
        "profiles": profiles,
    }
    path = Path(tmp) / "rdp-config.json"
    path.write_text(json.dumps(config))
    return path


def launch(config_path, profile, app=None, password_file=None, shell=None):
    captured = {"command": None, "rdp": ""}
    writes = []
    created = []
    makedirs = []
    real_mkstemp = tempfile.mkstemp

    class Capture:
        def write(self, text):
            writes.append(text)

        def flush(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_mkstemp(suffix=".rdp"):
        fd, path = real_mkstemp(suffix=suffix)
        created.append(path)
        return fd, path

    def fake_fdopen(fd, *args, **kwargs):
        os.close(fd)
        return Capture()

    def fake_makedirs(path, exist_ok=False):
        makedirs.append(path)

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    argv = ["--config", str(config_path), "--profile", profile]
    if app:
        argv += ["--app", app]
    if shell:
        argv += ["--shell", shell]
    if password_file:
        argv += ["--password-file", str(password_file)]
    with patch.object(rdp_launch.subprocess, "run", side_effect=fake_run), patch.object(
        rdp_launch.tempfile, "mkstemp", side_effect=fake_mkstemp
    ), patch.object(rdp_launch.os, "fdopen", side_effect=fake_fdopen), patch.object(
        rdp_launch.os, "makedirs", side_effect=fake_makedirs
    ):
        rdp_launch.main(argv)
    captured["rdp"] = "".join(writes)
    captured["makedirs"] = makedirs
    captured["files_gone"] = all(not os.path.exists(p) for p in created)
    return captured


class RdpLaunchTests(unittest.TestCase):
    def test_full_session_flags_and_no_password_in_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "accountant", "port": 3390}])
            secret = Path(tmp) / "pass"
            secret.write_text("s3cret")
            result = launch(config, "win", password_file=secret)
            command = result["command"]
            self.assertNotIn("s3cret", command)
            self.assertNotIn("s3cret", " ".join(command))
            self.assertEqual(command[0], "xfreerdp")
            for flag in ("/smartcard", "/clipboard", "/sound", "/usb:auto", "/drive:Shared,/home/maria/Shared", "/cert:tofu"):
                self.assertIn(flag, command)
            self.assertIn("/home/maria/Shared", result["makedirs"])
            self.assertNotIn("--from-file", command)
            self.assertNotIn("/microphone", command)
            self.assertIn("full address:s:192.0.2.10:3390", result["rdp"])
            self.assertIn("username:s:accountant", result["rdp"])
            self.assertIn("password:s:s3cret", result["rdp"])
            self.assertTrue(result["files_gone"])

    def test_fullscreen_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], fullscreen=True)
            command = launch(config, "win")["command"]
            self.assertIn("/f", command)
            self.assertNotIn("/floatbar:", command)
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            command = launch(config, "win")["command"]
            self.assertNotIn("/f", command)
            self.assertNotIn("/floatbar:", command)

    def test_floatbar_only_for_fullscreen_remoteapp(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], fullscreen=True)
            command = launch(config, "win", app="Expecta")["command"]
            self.assertIn("/f", command)
            self.assertIn("/floatbar:sticky:on,default:visible,show:fullscreen", command)

    def test_unicode_keyboard_app_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], unicode_keyboard=True)
            self.assertIn("/kbd:unicode:on", launch(config, "win", app="Expecta")["command"])
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            self.assertNotIn("/kbd:unicode:on", launch(config, "win", app="Expecta")["command"])
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], unicode_keyboard=True)
            self.assertNotIn("/kbd:unicode:on", launch(config, "win")["command"])

    def test_remote_app_alias_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u", "remote_apps": ["Accounting"]}])
            result = launch(config, "win", app="Accounting")
            self.assertIn("/app:program:||Accounting", result["command"])
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            result = launch(config, "win", app=r"C:\Program Files (x86)\Expecta\ExpectaClient.exe")
            self.assertIn(r"/app:program:C:\Program Files (x86)\Expecta\ExpectaClient.exe", result["command"])

    def test_alternate_shell_uses_shell_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            result = launch(config, "win", shell=r"C:\Program Files (x86)\Expecta\ExpectaClient.exe")
            self.assertIn(r"/shell:C:\Program Files (x86)\Expecta\ExpectaClient.exe", result["command"])
            self.assertNotIn("/app:program:", result["command"])

    def test_alternate_shell_ignored_for_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            result = launch(config, "win", shell="Accounting")
            self.assertNotIn("/shell:", result["command"])
            self.assertNotIn("/app:program:", result["command"])

    def test_shell_does_not_use_unicode_keyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], unicode_keyboard=True)
            result = launch(config, "win", shell=r"C:\App.exe")
            self.assertNotIn("/kbd:unicode:on", result["command"])

    def test_gfx_auto_adds_no_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            command = launch(config, "win")["command"]
            self.assertNotIn("/gfx:RFX", command)
            self.assertNotIn("/gdi:sw", command)

    def test_gfx_rfx(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], gfx="rfx")
            command = launch(config, "win")["command"]
            self.assertIn("/gfx:RFX", command)
            self.assertNotIn("/gdi:sw", command)

    def test_gfx_software(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], gfx="software")
            command = launch(config, "win")["command"]
            self.assertIn("/gfx:RFX", command)
            self.assertIn("/gdi:sw", command)

    def test_app_mode_forces_software_gdi(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], gfx="rfx")
            app = launch(config, "win", app="Expecta")["command"]
            self.assertIn("/gfx:RFX", app)
            self.assertIn("/gdi:sw", app)
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}], gfx="auto")
            app = launch(config, "win", app="Expecta")["command"]
            self.assertIn("/gdi:sw", app)
            self.assertNotIn("/gfx:RFX", app)

    def test_app_and_shell_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            argv = ["--config", str(config), "--profile", "win", "--app", "X", "--shell", "Y"]
            with self.assertRaises(SystemExit), patch("sys.stderr", new=io.StringIO()):
                rdp_launch.main(argv)

    def test_unknown_profile_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            with self.assertRaises(SystemExit), patch("sys.stderr", new=io.StringIO()):
                launch(config, "missing")

    def test_prompt_when_no_password_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            result = launch(config, "win")
            self.assertIn("prompt for credentials:i:1", result["rdp"])
            self.assertNotIn("password:s:", result["rdp"])

    def test_wait_for_file_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "secret"
            secret.write_text("x")
            self.assertTrue(rdp_launch.wait_for_file(str(secret), 5))

    def test_wait_for_file_timeout(self):
        with patch.object(rdp_launch.time, "sleep", return_value=None), patch.object(
            rdp_launch.time, "monotonic", side_effect=[0.0, 0.5, 1.1]
        ):
            self.assertFalse(rdp_launch.wait_for_file("/definitely/missing", 1))

    def test_wait_for_tcp_success(self):
        with patch.object(rdp_launch.socket, "create_connection", return_value=MagicMock()):
            self.assertTrue(rdp_launch.wait_for_tcp("10.0.0.1", 3389, 1))

    def test_wait_for_tcp_refused_then_timeout(self):
        with patch.object(
            rdp_launch.socket, "create_connection", side_effect=OSError("refused")
        ), patch.object(rdp_launch.time, "sleep", return_value=None), patch.object(
            rdp_launch.time, "monotonic", side_effect=[0.0, 0.5, 1.1]
        ):
            self.assertFalse(rdp_launch.wait_for_tcp("10.0.0.1", 3389, 1))

    def test_retry_loop_stops_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            calls = []

            def fake_run_once(config_, profile_, password_file_, app_, shell_=None):
                calls.append(1)
                return 141 if len(calls) < 3 else 0

            argv = ["--config", str(config), "--profile", "win", "--attempts", "3", "--backoff", "0"]
            with patch.object(rdp_launch, "_run_once", side_effect=fake_run_once), patch.object(
                rdp_launch.time, "sleep", return_value=None
            ):
                self.assertEqual(rdp_launch.main(argv), 0)
            self.assertEqual(len(calls), 3)

    def test_retry_loop_gives_up_after_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            calls = []

            def fake_run_once(*args):
                calls.append(1)
                return 141

            argv = ["--config", str(config), "--profile", "win", "--attempts", "3", "--backoff", "0"]
            with patch.object(rdp_launch, "_run_once", side_effect=fake_run_once), patch.object(
                rdp_launch.time, "sleep", return_value=None
            ):
                self.assertEqual(rdp_launch.main(argv), 141)
            self.assertEqual(len(calls), 3)

    def test_logoff_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_config(tmp, [{"name": "win", "host": "192.0.2.10", "user": "u"}])
            calls = []

            def fake_run_once(*args):
                calls.append(1)
                return 2  # XF_EXIT_LOGOFF

            argv = ["--config", str(config), "--profile", "win", "--attempts", "6", "--backoff", "0"]
            with patch.object(rdp_launch, "_run_once", side_effect=fake_run_once), patch.object(
                rdp_launch.time, "sleep", return_value=None
            ):
                self.assertEqual(rdp_launch.main(argv), 2)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
