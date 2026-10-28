"""Focused checks for config validation, target inventory and secret boundaries."""
import copy
import json
import os
from pathlib import Path
import struct
import base64
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from nix2office.config import ConfigError, dump_machine, validate_machine
from nix2office.deployment import PreparationError, check_destination, pinned_source, prepare
from nix2office.hardware import parse_probe, eligible_disks, recommendation, probe
from nix2office.wizard import load_inventory

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "github:cheirekov/nix2office/" + "a" * 40


def machine():
    return validate_machine({"disk": "/dev/disk/by-id/ata-EXAMPLE_SSD", "user": {
        "name": "maria", "full_name": "Мария Димитрова", "email": "maria@example.org"}})


def inventory_text():
    devices = [
        {"name": "/dev/sda", "type": "disk", "size": 128 * 2**30, "model": "Example SSD", "tran": "sata", "rota": False, "ro": False, "mountpoints": [None]},
        {"name": "/dev/sdb", "type": "disk", "size": 16 * 2**30, "model": "Rescue USB", "tran": "usb", "rota": False, "ro": False, "mountpoints": ["/iso"]},
    ]
    return "\n".join(["N2O_MEMORY_KIB=1716224", "N2O_THREADS=2", "N2O_CPU=Example dual core", "N2O_VENDOR=GenuineIntel", "N2O_ARCH=x86_64", "N2O_BOOT=bios", "N2O_GPU=i915", "", "N2O_DISKS_JSON", json.dumps({"blockdevices": devices}), "N2O_BY_ID", "/dev/disk/by-id/ata-EXAMPLE_SSD\t/dev/sda", "/dev/disk/by-id/usb-RESCUE\t/dev/sdb", ""])


class SchemaTests(unittest.TestCase):
    def test_roundtrip_unicode_and_bds(self):
        m = machine()
        m["keyboard"]["bulgarian"] = "bds"
        self.assertEqual(validate_machine(tomllib.loads(dump_machine(m))), m)
        self.assertEqual(m["user"]["name"], "maria")
        self.assertEqual(m["user"]["full_name"], "Мария Димитрова")

    def test_public_template(self):
        validate_machine(tomllib.loads((ROOT / "examples/machine.toml").read_text()))

    def test_reject_bad_inputs_before_writes(self):
        cases = [("user", "password", "DO_NOT_ECHO"), ("user", "name", "admin"), ("user", "full_name", "Maria:root"),
                 ("sharing", "folder", "../Documents"), ("sharing", "folder", "global"), ("sharing", "network", "0.0.0.0/0"),
                 ("admin", "network", "192.0.2.0/24; ACCEPT"), ("admin", "ssh_public_key", "-----BEGIN PRIVATE KEY----- DO_NOT_ECHO"),
                 ("apps", "nextcloud", "false"), ("vpn", "zerotier_networks", ["not-a-network"])]
        for section, key, value in cases:
            with self.subTest(section=section, key=key):
                m = machine()
                m[section][key] = value
                with self.assertRaises(ConfigError) as err:
                    validate_machine(m)
                self.assertNotIn("DO_NOT_ECHO", str(err.exception))
        for disk in ("/dev/sda", "/dev/disk/by-id/ata-EXAMPLE-part1", "/dev/disk/by-id/../sda"):
            with self.assertRaises(ConfigError):
                validate_machine({"disk": disk})

    def test_public_key_and_interpolation_are_data(self):
        m = machine()
        kind = b"ssh-ed25519"
        blob = struct.pack(">I", len(kind)) + kind + struct.pack(">I", 32) + b"a" * 32
        m["admin"]["ssh_public_key"] = "ssh-ed25519 " + base64.b64encode(blob).decode() + " comment${not-nix}"
        m["user"]["full_name"] = 'Мария ${builtins.abort "bad"}'
        self.assertEqual(tomllib.loads(dump_machine(m))["user"]["full_name"], m["user"]["full_name"])

    def test_zero_tier_requires_enable(self):
        m = machine()
        m["vpn"]["zerotier_networks"] = ["0123456789abcdef"]
        with self.assertRaises(ConfigError):
            validate_machine(m)


class HardwareTests(unittest.TestCase):
    def test_empty_ssh_target_never_probes_controller(self):
        with patch("nix2office.hardware.subprocess.run") as command:
            with self.assertRaises(ConfigError):
                probe("")
            command.assert_not_called()

    def test_target_and_usb_exclusion(self):
        inv = parse_probe(inventory_text(), "test-target")
        self.assertEqual(inv["memory_mib"], 1676)
        self.assertEqual(inv["initrd_modules"], ["i915"])
        self.assertEqual([d["name"] for d in eligible_disks(inv)], ["/dev/sda"])
        self.assertEqual(recommendation(inv)["profile"], "light")
        inv.update(memory_mib=8192, threads=8)
        self.assertEqual(recommendation(inv)["profile"], "standard")

    def test_saved_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "hardware.json"
            inv = parse_probe(inventory_text())
            p.write_text(json.dumps(inv))
            self.assertEqual(load_inventory(p), inv)
            inv["disks"][0]["by_id"] = ["/dev/sda"]
            p.write_text(json.dumps(inv))
            with self.assertRaises(ConfigError):
                load_inventory(p)


class DeploymentTests(unittest.TestCase):
    def test_source_requires_immutable_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pinned_source(Path(tmp), SOURCE), SOURCE)
            for source in ("github:cheirekov/nix2office/main", "path:.", SOURCE + '${bad}'):
                with self.assertRaises(PreparationError):
                    pinned_source(Path(tmp), source)

    def test_public_output_refused(self):
        with self.assertRaises(PreparationError):
            check_destination(ROOT / "public-deployment-example")

    def test_invalid_config_never_collects_passwords(self):
        m = machine()
        m["user"]["password"] = "DO_NOT_ECHO"
        with tempfile.TemporaryDirectory() as tmp, patch("nix2office.deployment.collect_passwords") as passwords:
            with self.assertRaises(ConfigError):
                prepare(m, Path(tmp) / "private", SOURCE, True)
            passwords.assert_not_called()
            self.assertFalse((Path(tmp) / "private").exists())

    def test_real_secrets_private_git_and_update(self):
        # Run inside nix develop, which supplies age, sops and mkpasswd.
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "private"
            m = machine()
            prepare(m, dest, SOURCE, True)
            tracked = subprocess.check_output(["git", "-C", str(dest), "ls-files"], text=True).splitlines()
            self.assertNotIn("credentials.json", tracked)
            self.assertFalse(any(p.startswith("keys/") for p in tracked))
            self.assertIn("machine.toml", tracked)
            for p in (dest, dest / "keys"):
                self.assertEqual(p.stat().st_mode & 0o777, 0o700)
            for p in (dest / "keys/host.age", dest / "keys/operator.age", dest / "credentials.json"):
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            env = dict(os.environ, SOPS_AGE_KEY_FILE=str(dest / "keys/operator.age"))
            decoded = json.loads(subprocess.check_output(["sops", "-d", "--output-type", "json", str(dest / "secrets.yaml")], env=env, text=True))
            self.assertEqual(set(decoded), {"office", "admin"})
            self.assertTrue(all(v.startswith("$y$") for v in decoded.values()))
            secrets_before = {p: (dest / p).read_bytes() for p in ("keys/host.age", "keys/operator.age", "secrets.yaml", "credentials.json")}
            m["apps"]["browser"] = "brave"
            prepare(m, dest, SOURCE, update=True)
            self.assertEqual(tomllib.loads((dest / "machine.toml").read_text())["apps"]["browser"], "brave")
            for p, value in secrets_before.items():
                self.assertEqual((dest / p).read_bytes(), value)
            m["user"]["name"] = "someoneelse"
            with self.assertRaises(PreparationError):
                prepare(m, dest, SOURCE, update=True)
            with self.assertRaises(PreparationError):
                prepare(machine(), dest, SOURCE, True)

    def test_entered_passwords_are_not_persisted_as_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "private"
            entered = {"maria": "Example-only-DO-NOT-USE-1", "admin": "Example-only-DO-NOT-USE-2"}
            with patch("nix2office.deployment.collect_passwords", return_value=entered):
                prepare(machine(), dest, SOURCE)
            self.assertFalse((dest / "credentials.json").exists())
            for p in dest.rglob("*"):
                if p.is_file() and ".git" not in p.parts:
                    contents = p.read_bytes()
                    self.assertFalse(any(value.encode() in contents for value in entered.values()))


if __name__ == "__main__":
    unittest.main()
