"""M1 diagnostics: mocked commands and temporary sysfs, never host probes."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from nix2office import diagnostics as d


class Runner:
    def __init__(self):
        self.calls = []
        self.overrides = {}

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if tuple(args) in self.overrides:
            value = self.overrides[tuple(args)]
            if isinstance(value, Exception):
                raise value
            if isinstance(value, subprocess.CompletedProcess):
                return value
            return subprocess.CompletedProcess(args, 0, value, "")
        if args[0] == "glxinfo":
            output = "direct rendering: Yes\nAccelerated: yes\nOpenGL renderer string: Mesa Intel HD Graphics\n"
        elif args[0] == "vainfo":
            output = "VAProfileH264Main : VAEntrypointVLD\nVAProfileH264Main : VAEntrypointEncSlice\n"
        elif args[0] == "systemctl":
            output = "LoadState=loaded\nActiveState=active\nSubState=running\n"
        elif args[0] == "pactl":
            output = "SECRET_NAME" if args[-1] == "get-default-sink" else json.dumps([{
                "index": 42, "state": "IDLE", "mute": False, "active_profile": "output:analog-stereo",
                "active_port": "analog-output-lineout", "name": "SECRET_NAME", "properties": {"token": "SECRET_TOKEN"}}])
        elif args[0] == "bluetoothctl":
            output = "Controller AA:BB:CC:DD:EE:FF SECRET_ALIAS\n" if args[-1] == "list" else "Controller AA:BB:CC:DD:EE:FF\n\tPowered: yes\n\tAlias: SECRET_ALIAS\n"
        elif args[:4] == ["ip", "-j", "link", "show"]:
            output = json.dumps([{"ifname": "lo", "operstate": "UNKNOWN", "flags": ["LOOPBACK", "UP"]},
                                 {"ifname": "eth0", "operstate": "UP", "flags": ["UP", "LOWER_UP"], "address": "SECRET_MAC"}])
        elif args[:4] == ["ip", "-j", "address", "show"]:
            output = json.dumps([{"ifname": "eth0", "addr_info": [
                {"family": "inet", "local": "192.0.2.2", "prefixlen": 24},
                {"family": "inet6", "local": "2001:db8::2", "prefixlen": 64}]}])
        elif args[:4] == ["ip", "-j", "-4", "route"]:
            output = '[{"dst":"default","gateway":"192.0.2.1","dev":"eth0"}]'
        elif args[:4] == ["ip", "-j", "-6", "route"]:
            output = '[{"dst":"default","gateway":"fe80::1","dev":"eth0"}]'
        elif args[0] == "dmesg":
            output = "[0] SECRET_KERNEL_COMMAND_LINE\n[1] firmware loaded successfully\n"
        else:
            raise AssertionError("Unexpected probe: " + repr(args))
        return subprocess.CompletedProcess(args, 0, output, "SECRET_STDERR")


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bus/pci/devices").mkdir(parents=True)
        (self.root / "class/bluetooth/hci0").mkdir(parents=True)
        (self.root / "bus/usb/devices").mkdir(parents=True)
        self.pci("0000:00:02.0", "030000", "8086", "1234", "i915")
        self.runner = Runner()
        self.env = {"DISPLAY": ":0", "XDG_RUNTIME_DIR": "/run/user/1000",
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}

    def pci(self, address, cls, vendor, device, driver=None):
        path = self.root / "bus/pci/devices" / address
        path.mkdir()
        for key, value in (("class", cls), ("vendor", vendor), ("device", device)):
            (path / key).write_text("0x" + value + "\n")
        if driver:
            (path / "driver").symlink_to("/sys/bus/pci/drivers/" + driver)
        return path

    def report(self, **kwargs):
        return d.collect_report(runner=self.runner, environ=self.env,
                                sysfs_root=self.root, **kwargs)

    def checks(self, **kwargs):
        return self.report(**kwargs)["checks"]

    def override(self, args, output):
        self.runner.overrides[tuple(args)] = output

    def test_healthy_snapshot_has_evidence_but_no_claim_of_audible_or_internet_success(self):
        report = self.report()
        checks = report["checks"]
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["read_only"])
        for name in ("pci", "graphics", "video", "audio", "bluetooth", "network", "firmware"):
            self.assertEqual(checks[name]["status"], "pass", name)
        self.assertEqual(checks["facter"]["status"], "not-applicable")
        self.assertEqual(checks["audio"]["details"]["audible_confirmation"], "unknown")
        self.assertIn("слушане", checks["audio"]["message"])
        self.assertEqual(checks["network"]["details"]["internet"]["status"], "unknown")
        self.assertEqual(checks["pci"]["details"]["devices"][0]["driver"], "i915")
        self.assertEqual(len(checks["network"]["details"]["default_routes"]), 2)
        self.assertEqual(len(checks["network"]["details"]["addresses"]), 2)

    def test_per_interface_status_and_unavailable_checks_have_action(self):
        self.pci("0000:02:00.0", "020000", "14e4", "1692")
        report = d.collect_report(
            runner=self.runner, environ={}, sysfs_root=self.root)
        pci = report['checks']['pci']['details']['devices']
        unbound = next(v for v in pci if v['address'] == '0000:02:00.0')
        self.assertEqual(unbound['status'], 'warning')
        self.assertIn('firmware', unbound['next_action'])
        for name, check in report['checks'].items():
            if check['status'] in ('warning', 'unknown'):
                self.assertTrue(check['next_action'], name)
        self.assertEqual(report['rules_version'], d.RULES_VERSION)
        self.assertTrue(report['kernel_version'])

    def test_usb_interfaces_bound_unbound_and_inaccessible(self):
        parent = self.root / 'bus/usb/devices/1-1'
        parent.mkdir()
        (parent / 'idVendor').write_text('1234\n')
        (parent / 'idProduct').write_text('abcd\n')
        interface = parent / '1-1:1.0'
        interface.mkdir()
        (interface / 'bInterfaceClass').write_text('03\n')
        (self.root / 'bus/usb/devices/1-1:1.0').symlink_to(interface)
        check = self.checks()['usb']
        self.assertEqual(check['status'], 'warning')
        self.assertEqual(check['details']['devices'][0]['driver'], 'unbound')
        (interface / 'driver').symlink_to('/sys/bus/usb/drivers/usbhid')
        self.assertEqual(self.checks()['usb']['status'], 'pass')
        (parent / 'idVendor').write_text('not-a-vendor')
        self.assertEqual(self.checks()['usb']['status'], 'unknown')

    def test_no_raw_logs_errors_aliases_audio_properties_or_environment_exported(self):
        self.env["VERY_SECRET_TOKEN"] = "SECRET_ENVIRONMENT"
        report = json.dumps(self.report(), ensure_ascii=False)
        self.assertNotIn("SECRET", report)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", report)
        self.assertNotIn("DBUS_SESSION", report)

    def test_all_commands_are_bounded_shell_free_read_only_queries(self):
        self.report()
        for args, kwargs in self.runner.calls:
            self.assertGreater(kwargs["timeout"], 0)
            self.assertLessEqual(kwargs["timeout"], 4)
            self.assertFalse(kwargs.get("shell", False))
            self.assertFalse(kwargs["check"])
            self.assertEqual(kwargs["env"]["LC_ALL"], "C")
            self.assertNotIn(args[0], ("sudo", "modprobe", "nix", "ping", "curl", "wget"))
            self.assertFalse(set(args) & {"start", "restart", "enable", "scan", "power", "connect"})

    def test_missing_sessions_skip_graphics_video_and_audio_commands(self):
        self.env = {}
        checks = self.checks()
        for name in ("graphics", "video", "audio"):
            self.assertEqual(checks[name]["status"], "unknown")
        self.assertFalse({"glxinfo", "vainfo", "pactl"} & {a[0] for a, _ in self.runner.calls})
        self.assertFalse(any(a[0] == "systemctl" and "--user" in a for a, _ in self.runner.calls))
        self.assertIn("слушане", checks["audio"]["message"])

    def test_wayland_without_x_display_only_uses_vainfo_existing_session(self):
        del self.env["DISPLAY"]
        self.env["WAYLAND_DISPLAY"] = "wayland-0"
        checks = self.checks()
        self.assertEqual(checks["graphics"]["status"], "unknown")
        self.assertEqual(checks["video"]["status"], "pass")
        self.assertIn(["vainfo", "--display", "wayland"], [a for a, _ in self.runner.calls])

    def test_software_renderer_is_warning_even_with_direct_rendering(self):
        for renderer in ("llvmpipe (LLVM 19)", "softpipe", "Software Rasterizer", "swrast"):
            with self.subTest(renderer=renderer):
                self.override(["glxinfo", "-B"], "direct rendering: Yes\nOpenGL renderer string: " + renderer)
                self.assertEqual(self.checks()["graphics"]["status"], "warning")

    def test_disabled_acceleration_and_unparseable_renderer(self):
        self.override(["glxinfo", "-B"], "Accelerated: no\nOpenGL renderer string: Mesa Intel")
        self.assertEqual(self.checks()["graphics"]["status"], "warning")
        self.override(["glxinfo", "-B"], "SECRET_INVALID_OUTPUT")
        self.assertEqual(self.checks()["graphics"]["status"], "unknown")
        self.override(["glxinfo", "-B"], "OpenGL renderer string: Mesa Intel")
        self.assertEqual(self.checks()["graphics"]["status"], "unknown")

    def test_missing_commands_permission_and_timeouts_are_unknown_without_exception_text(self):
        for failure in (FileNotFoundError("SECRET_PATH"), PermissionError("SECRET_USER"),
                        subprocess.TimeoutExpired("glxinfo", 4, output="SECRET_OUTPUT"),
                        subprocess.CompletedProcess([], 1, "SECRET_LOG", "SECRET_ERROR")):
            with self.subTest(failure=type(failure).__name__):
                for args in (["glxinfo", "-B"], ["vainfo", "--display", "x11"], ["dmesg", "--color=never"]):
                    self.override(args, failure)
                checks = self.checks()
                for name in ("graphics", "video", "firmware"):
                    self.assertEqual(checks[name]["status"], "unknown")
                self.assertNotIn("SECRET", json.dumps(checks))

    def test_vainfo_encoding_only_is_warning_and_unparseable_is_unknown(self):
        self.override(["vainfo", "--display", "x11"], "VAProfileH264Main : VAEntrypointEncSlice")
        self.assertEqual(self.checks()["video"]["status"], "warning")
        self.override(["vainfo", "--display", "x11"], "")
        self.assertEqual(self.checks()["video"]["status"], "unknown")

    def test_audio_inactive_service_is_warning_permission_failure_unknown(self):
        args = ["systemctl", "--user", "show", "wireplumber.service", "--property=LoadState,ActiveState,SubState"]
        self.override(args, "LoadState=loaded\nActiveState=failed\nSubState=failed")
        self.assertEqual(self.checks()["audio"]["status"], "warning")
        self.override(args, subprocess.CompletedProcess(args, 1, "", "Permission denied SECRET"))
        audio = self.checks()["audio"]
        self.assertEqual(audio["status"], "unknown")
        self.assertEqual(audio["details"]["services"]["wireplumber"]["status"], "unknown")

    def test_pactl_only_connects_to_explicit_local_socket_no_remote_server_or_autospawn(self):
        self.env["PULSE_SERVER"] = "tcp:external.invalid"
        self.report()
        calls = [a for a, _ in self.runner.calls if a[0] == "pactl"]
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("--server=unix:/run/user/1000/pulse/native" in a for a in calls))
        self.assertNotIn("external.invalid", repr(calls))

    def test_dbus_without_runtime_does_not_guess_a_pulse_server(self):
        self.env = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/session"}
        self.assertEqual(self.checks()["audio"]["status"], "unknown")
        self.assertNotIn("pactl", [a[0] for a, _ in self.runner.calls])

    def test_audio_empty_muted_and_malformed_sinks(self):
        args = ["pactl", "--server=unix:/run/user/1000/pulse/native", "--format=json", "list", "sinks"]
        for output, expected in (("[]", "warning"), ('[{"mute":true,"state":"IDLE","index":42,"name":"SECRET_NAME"}]', "warning"),
                                 ('{"not":"an array"}', "unknown"), ('[null]', "unknown"),
                                 ('[{}]', "unknown"), ("invalid", "unknown")):
            with self.subTest(output=output):
                self.override(args, output)
                self.assertEqual(self.checks()["audio"]["status"], expected)

    def test_pci_unbound_network_warns_but_bridge_does_not(self):
        self.pci("0000:00:01.0", "060400", "8086", "1111")
        self.assertEqual(self.checks()["pci"]["status"], "pass")
        self.pci("0000:01:00.0", "020000", "8086", "2222")
        self.assertEqual(self.checks()["pci"]["status"], "warning")

    def test_pci_partial_inventory_and_missing_sysfs_are_unknown(self):
        path = self.pci("0000:02:00.0", "030000", "8086", "3333")
        (path / "vendor").unlink()
        pci = self.checks()["pci"]
        self.assertEqual(pci["status"], "unknown")
        self.assertFalse(pci["details"]["complete"])
        self.assertEqual(d.collect_report(runner=self.runner, environ={}, sysfs_root=self.root / "absent")["checks"]["pci"]["status"], "unknown")

    def test_bluetooth_powered_off_or_inaccessible(self):
        args = ["bluetoothctl", "--timeout", "3", "show", "AA:BB:CC:DD:EE:FF"]
        self.override(args, "\tPowered: no\n")
        self.assertEqual(self.checks()["bluetooth"]["status"], "warning")
        self.override(args, PermissionError("SECRET"))
        self.assertEqual(self.checks()["bluetooth"]["status"], "unknown")

    def test_bluetooth_no_adapter_and_usb_without_controller(self):
        (self.root / "class/bluetooth/hci0").rmdir()
        self.override(["bluetoothctl", "--timeout", "3", "list"], "")
        self.assertEqual(self.checks()["bluetooth"]["status"], "not-applicable")
        usb = self.root / "bus/usb/devices/1-1:1.0"
        usb.mkdir()
        for name, value in (("bInterfaceClass", "e0"), ("bInterfaceSubClass", "01"), ("bInterfaceProtocol", "01")):
            (usb / name).write_text(value)
        bluetooth = self.checks()["bluetooth"]
        self.assertEqual(bluetooth["status"], "warning")
        self.assertTrue(bluetooth["details"]["usb_adapter_detected"])

    def test_no_bluetooth_adapter_is_not_applicable_without_bluez_or_bluetooth_class(self):
        (self.root / "class/bluetooth/hci0").rmdir()
        (self.root / "class/bluetooth").rmdir()
        self.override(["bluetoothctl", "--timeout", "3", "list"], FileNotFoundError())
        self.assertEqual(self.checks()["bluetooth"]["status"], "not-applicable")
        self.assertFalse(any(a[0] == "bluetoothctl" or "bluetooth.service" in a for a, _ in self.runner.calls))

    def test_bluetooth_daemon_must_be_active_before_any_dbus_query(self):
        args = ["systemctl", "show", "bluetooth.service", "--property=LoadState,ActiveState"]
        for output, expected in (("LoadState=loaded\nActiveState=inactive", "warning"),
                                 ("LoadState=not-found\nActiveState=inactive", "warning"),
                                 (PermissionError(), "unknown"), (FileNotFoundError(), "unknown")):
            with self.subTest(output=output):
                self.runner.calls.clear()
                self.override(args, output)
                self.assertEqual(self.checks()["bluetooth"]["status"], expected)
                self.assertFalse(any(a[0] == "bluetoothctl" for a, _ in self.runner.calls))

    def test_audio_reports_sink_index_connector_and_default_without_names(self):
        args = ["pactl", "--server=unix:/run/user/1000/pulse/native", "--format=json", "list", "sinks"]
        self.override(args, json.dumps([
            {"index": 3, "name": "SECRET_NAME", "active_port": "hdmi-output-0", "state": "IDLE", "mute": False, "description": "SECRET_PERSONAL_DESCRIPTION"},
            {"index": 4, "name": "SECRET_ALTERNATE", "active_port": {"name": "analog-output-speaker", "description": "SECRET_PERSON"}, "state": "SUSPENDED", "mute": True},
        ]))
        audio = self.checks()["audio"]
        self.assertEqual(audio["status"], "pass")
        sinks = audio["details"]["sinks"]
        self.assertEqual([(s["index"], s["output_kind"], s["default"]) for s in sinks], [
            (3, "hdmi-displayport", True), (4, "analog", False)])
        self.assertNotIn("SECRET", json.dumps(audio))
        self.override(["pactl", "--server=unix:/run/user/1000/pulse/native", "get-default-sink"], PermissionError())
        audio = self.checks()["audio"]
        self.assertEqual(audio["status"], "unknown")
        self.assertTrue(all(s["default"] is None for s in audio["details"]["sinks"]))

    def test_local_network_pass_does_not_require_a_default_route(self):
        for version in ("-4", "-6"):
            self.override(["ip", "-j", version, "route", "show", "default"], "[]")
        network = self.checks()["network"]
        self.assertEqual(network["status"], "pass")
        self.assertEqual(network["details"]["default_routes"], [])
        self.assertEqual(network["details"]["internet"]["status"], "unknown")

    def test_network_down_linklocal_and_route_access_failure(self):
        self.override(["ip", "-j", "link", "show"], '[{"ifname":"eth0","operstate":"DOWN","flags":[]}]')
        self.assertEqual(self.checks()["network"]["status"], "warning")
        del self.runner.overrides[("ip", "-j", "link", "show")]
        self.override(["ip", "-j", "address", "show"], '[{"ifname":"eth0","addr_info":[{"local":"fe80::1","prefixlen":64}]}]')
        self.assertEqual(self.checks()["network"]["status"], "warning")
        self.override(["ip", "-j", "-6", "route", "show", "default"], PermissionError())
        self.assertEqual(self.checks()["network"]["status"], "unknown")

    def test_kernel_firmware_failure_is_counted_without_leaking_filename_or_log(self):
        self.override(["dmesg", "--color=never"], "SECRET_BOOT\nDirect firmware load for SECRET_FIRMWARE failed with error -2\nfirmware: failed to load SECRET_OTHER\n")
        firmware = self.checks()["firmware"]
        self.assertEqual(firmware["status"], "warning")
        self.assertEqual(firmware["details"]["firmware_error_lines"], 2)
        self.assertNotIn("SECRET", json.dumps(firmware))

    def facter_file(self, data):
        path = self.root / "facter.json"
        path.write_text(json.dumps(data))
        return path

    def test_facter_id_objects_categorized_hardware_and_ignored_secrets(self):
        device = {"vendor": {"hex": "8086", "name": "SECRET_VENDOR"},
                  "device": {"value": 0x1234}, "bus_type": {"name": "PCI", "value": 4},
                  "sysfs_bus_id": "0000:00:02.0", "serial": "SECRET_SERIAL", "driver": "i915",
                  "driver_module": "a_different_module_name"}
        path = self.facter_file({"hardware": {"graphics_card": [device], "pci": [device],
                                            "network_interface": [{"bus_type": {"value": 143}, "vendor": "Virtio"}],
                                            "system": {"serial": "SECRET_SYSTEM"}}})
        facter = self.checks(facter_report=path)["facter"]
        self.assertEqual(facter["status"], "pass")
        self.assertNotIn("SECRET", json.dumps(facter))
        self.assertEqual(facter["details"]["only_saved"], {})
        self.assertEqual(facter["details"]["bindings_compared"], 1)

    def test_facter_044_schema_driver_and_bus_wrappers(self):
        # From 0.4.4 pkg/hwinfo/{hardware,id}.go: device (not device_id),
        # bus_type=ID{hex,value,name}, BusPci=4, Driver != DriverModule.
        path = self.facter_file({"version": 1, "system": "x86_64-linux", "hardware": {
            "graphics_card": [{
                "bus_type": {"hex": "0004", "value": 4, "name": "pci"},
                "vendor": {"hex": "8086", "value": 32902},
                "device": {"hex": "1234", "value": 4660},
                "sysfs_bus_id": "0000:00:02.0", "driver": "old-driver", "driver_module": "old_module"}],
            "network_interface": [{"bus_type": {"hex": "008f", "value": 143}, "vendor": "Virtio", "device": "Ethernet Card 0"}],
            "usb": [{"bus_type": {"hex": "0086", "value": 134}, "vendor": {"hex": "8086"}, "device": {"hex": "ffff"}}],
        }})
        facter = self.checks(facter_report=path)["facter"]
        self.assertEqual(facter["status"], "warning")
        self.assertEqual(facter["details"]["only_saved"], {})
        self.assertEqual(facter["details"]["only_current"], {})
        self.assertEqual(facter["details"]["driver_changes"], [{
            "address": "0000:00:02.0", "saved_driver": "old-driver", "current_driver": "i915"}])

    def test_facter_mismatch_preserves_device_multiplicity(self):
        path = self.facter_file({"hardware": {"pci": [{"vendor": "0x8086", "device": "1234"}] * 2}})
        facter = self.checks(facter_report=path)["facter"]
        self.assertEqual(facter["status"], "warning")
        self.assertEqual(facter["details"]["only_saved"], {"8086:1234": 1})

    def test_facter_missing_invalid_unsupported_and_fifo_are_unknown(self):
        for data in ({}, None, {"hardware": None}, {"hardware": {"pci": {}}},
                     {"hardware": {"pci": [None]}}, {"hardware": {"pci": [{"vendor": "SECRET"}]}}):
            with self.subTest(data=data):
                self.assertEqual(self.checks(facter_report=self.facter_file(data))["facter"]["status"], "unknown")
        self.assertEqual(self.checks(facter_report=self.root / "missing")["facter"]["status"], "unknown")
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        self.assertEqual(self.checks(facter_report=fifo)["facter"]["status"], "unknown")

    def test_facter_cannot_compare_with_incomplete_live_inventory(self):
        path = self.facter_file({"hardware": {"pci": [{"vendor": "8086", "device": "1234"}]}})
        (self.root / "bus/pci/devices/0000:00:02.0/vendor").unlink()
        self.assertEqual(self.checks(facter_report=path)["facter"]["status"], "unknown")

    def test_all_command_timeouts_return_a_report_with_unknowns(self):
        def timeout(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], output="SECRET_PARTIAL_LOG")

        self.runner = timeout
        checks = self.checks()
        for name in ("graphics", "video", "audio", "bluetooth", "network", "firmware"):
            self.assertEqual(checks[name]["status"], "unknown", name)
        self.assertNotIn("SECRET", json.dumps(checks))

    def test_empty_or_oversized_logs_and_invalid_bluetooth_output_are_unknown(self):
        for output in ("", " " * (d.MAX_OUTPUT + 1)):
            self.override(["dmesg", "--color=never"], output)
            self.assertEqual(self.checks()["firmware"]["status"], "unknown")
        self.override(["bluetoothctl", "--timeout", "3", "list"], "SECRET_ERROR")
        self.assertEqual(self.checks()["bluetooth"]["status"], "unknown")

    def test_default_public_interface_uses_subprocess_run(self):
        with patch.object(d.subprocess, "run", self.runner), patch.dict(os.environ, self.env, clear=True), patch.object(d, "_pci", return_value=d._pci(self.root)):
            report = d.collect_report()
        self.assertEqual(report["checks"]["graphics"]["status"], "pass")

    def cli(self, argv):
        output, error = io.StringIO(), io.StringIO()
        with patch.object(d, "collect_report", return_value=self.report()) as collect, contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = d.main(argv)
        return code, output.getvalue(), error.getvalue(), collect

    def test_cli_bulgarian_default_json_and_facter_option(self):
        code, output, error, _ = self.cli([])
        self.assertEqual(code, 0)
        self.assertIn("диагностика само за четене", output)
        self.assertIn("Интернет: неизвестно", output)
        self.assertIn("слушане", output)
        self.assertEqual(error, "")
        code, output, _, collect = self.cli(["--json", "--facter-report", "existing.json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["read_only"])
        collect.assert_called_once_with(facter_report="existing.json")

    def test_private_atomic_output_and_existing_permissive_file(self):
        path = self.root / "output.json"
        path.write_text("old")
        path.chmod(0o644)
        original_inode = path.stat().st_ino
        code, output, error, _ = self.cli(["--json", "--output", str(path)])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(path.read_text()), json.loads(output))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotEqual(path.stat().st_ino, original_inode)
        self.assertEqual(list(self.root.glob(".nix2office-diagnostics-*")), [])

    def test_new_output_stays_0600_with_permissive_umask(self):
        path = self.root / "new.json"
        old_umask = os.umask(0)
        try:
            code, _, _, _ = self.cli(["--output", str(path)])
        finally:
            os.umask(old_umask)
        self.assertEqual(code, 0)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_output_rejects_existing_and_dangling_symlinks_and_directory(self):
        target = self.root / "target"
        target.write_text("keep")
        link = self.root / "link"
        link.symlink_to(target)
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "absent")
        for path in (link, dangling, self.root):
            code, output, error, _ = self.cli(["--output", str(path)])
            self.assertEqual(code, 2)
            self.assertEqual(output, "")
            self.assertIn("символна връзка", error)
        self.assertTrue(link.is_symlink())
        self.assertTrue(dangling.is_symlink())
        self.assertEqual(target.read_text(), "keep")

    def test_output_failure_keeps_previous_contents_and_cleans_private_temp(self):
        path = self.root / "report.json"
        path.write_text("previous")
        with patch.object(d.os, "replace", side_effect=OSError("SECRET_FAILURE")):
            code, _, error, _ = self.cli(["--output", str(path)])
        self.assertEqual(code, 2)
        self.assertNotIn("SECRET", error)
        self.assertEqual(path.read_text(), "previous")
        self.assertEqual(list(self.root.glob(".nix2office-diagnostics-*")), [])

    def test_output_symlink_swap_before_replace_never_writes_target(self):
        path = self.root / "report.json"
        target = self.root / "untouched"
        target.write_text("keep")
        replace = os.replace

        def swap_then_replace(source, destination, **kwargs):
            path.symlink_to(target)
            replace(source, destination, **kwargs)

        with patch.object(d.os, "replace", side_effect=swap_then_replace):
            d._write_json(path, {"safe": True})
        self.assertFalse(path.is_symlink())
        self.assertEqual(json.loads(path.read_text()), {"safe": True})
        self.assertEqual(target.read_text(), "keep")

    def test_output_symlink_created_during_write_is_rejected_and_temp_cleaned(self):
        path, target = self.root / "report.json", self.root / "untouched"
        target.write_text("keep")
        fsync = os.fsync

        def swap_while_flushing(fd):
            path.symlink_to(target)
            fsync(fd)

        with patch.object(d.os, "fsync", side_effect=swap_while_flushing):
            with self.assertRaises(ValueError):
                d._write_json(path, {"safe": True})
        self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_text(), "keep")
        self.assertEqual(list(self.root.glob(".nix2office-diagnostics-*")), [])


if __name__ == "__main__":
    unittest.main()
