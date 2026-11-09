"""Focused checks for the RDP thin-client schema."""
import sys
from pathlib import Path
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from nix2office.config import ConfigError, dump_machine, validate_machine


def machine(role="office", thin=None):
    m = {"disk": "/dev/disk/by-id/ata-EXAMPLE", "role": role}
    if thin is not None:
        m["thin_client"] = thin
    return m


class ThinClientTests(unittest.TestCase):
    def test_default_role_is_office_and_no_profiles(self):
        m = validate_machine({"disk": "/dev/disk/by-id/ata-EXAMPLE"})
        self.assertEqual(m["role"], "office")
        self.assertEqual(m["thin_client"]["profiles"], [])

    def test_hybrid_requires_profiles(self):
        with self.assertRaises(ConfigError):
            validate_machine(machine("hybrid"))

    def test_profiles_roundtrip_with_remote_apps(self):
        m = machine("hybrid", {
            "credentials": "sops",
            "redirect": ["smartcard", "clipboard"],
            "profiles": [
                {"name": "win", "host": "172.16.19.20", "user": "accountant", "port": 3389, "remote_apps": ["Accounting"]},
            ],
        })
        validated = validate_machine(m)
        self.assertEqual(validated["thin_client"]["profiles"][0]["name"], "win")
        restored = validate_machine(tomllib.loads(dump_machine(validated)))
        self.assertEqual(restored, validated)

    def test_rejects_bad_credentials_redirect_profile(self):
        bad = [
            {"credentials": "bad"},
            {"redirect": ["bogus"]},
            {"redirect": ["smartcard", "smartcard"]},
            {"profiles": [{"name": "x", "host": "", "user": "u"}]},
            {"profiles": [{"name": "x", "host": "h", "user": "u", "port": 99999}]},
            {"profiles": [{"name": "x", "host": "h", "user": "u", "remote_apps": ["ok", ""]}]},
            {"profiles": [{"name": "x", "host": "h", "user": "u"}, {"name": "x", "host": "h", "user": "u"}]},
            {"profiles": [{"name": "x", "host": "h", "user": "u", "unknown": "y"}]},
        ]
        for thin in bad:
            with self.subTest(thin=thin):
                with self.assertRaises(ConfigError):
                    validate_machine(machine("hybrid", thin))

    def test_office_ignores_thin_profiles(self):
        m = validate_machine(machine("office", {"profiles": [{"name": "win", "host": "h", "user": "u"}]}))
        self.assertEqual(m["role"], "office")


if __name__ == "__main__":
    unittest.main()

