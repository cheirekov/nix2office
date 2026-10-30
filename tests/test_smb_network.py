"""Explicit SMB IPv4 CIDRs, including the requested all-IPv4 range."""
from pathlib import Path
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from nix2office.config import ConfigError, dump_machine, validate_machine


def machine(network, mode="both"):
    return {
        "disk": "/dev/disk/by-id/ata-EXAMPLE_SSD",
        "sharing": {"mode": mode, "network": network},
    }


class SMBNetworkTests(unittest.TestCase):
    def test_explicit_all_ipv4_and_scoped_ranges_roundtrip(self):
        for mode in ("client", "both"):
            for network in (
                "0.0.0.0/0", "0.0.0.0/1", "128.0.0.0/1",
                "192.168.1.0/24", "203.0.113.10/32", "0.0.0.0/32",
            ):
                with self.subTest(mode=mode, network=network):
                    validated = validate_machine(machine(network, mode))
                    self.assertEqual(validated["sharing"]["network"], network)
                    restored = validate_machine(tomllib.loads(dump_machine(validated)))
                    self.assertEqual(restored, validated)

    def test_bare_address_explains_explicit_all_ipv4(self):
        for mode in ("client", "both"):
            with self.subTest(mode=mode):
                with self.assertRaises(ConfigError) as error:
                    validate_machine(machine("0.0.0.0", mode))
                message = str(error.exception)
                self.assertIn("sharing.network", message)
                self.assertIn("explicit IPv4 CIDR", message)
                self.assertIn("0.0.0.0/0 allows every IPv4 source", message)

    def test_rejects_malformed_or_implicit_networks(self):
        for network in (
            "", "192.168.1.0", "203.0.113.10", "192.168.1.10/24",
            "1.2.3.4/0", "0.0.0.0/00", "0.0.0.0/01", "0.0.0.0/33",
            "0.0.0.0/-1", "0.0.0.0/+0", "0.0.0.0/0.0.0.0",
            "192.168.1.0/255.255.255.0", "256.0.0.0/24", "192.168.01.0/24",
            "::/0", "::ffff:192.168.1.0/120", "0.0.0.0/0 ", " 0.0.0.0/0",
            "0.0.0.0/0; accept", "0.0.0.0/0\n", "0.0.0.0/0\x00",
        ):
            with self.subTest(network=network):
                with self.assertRaisesRegex(ConfigError, r"sharing\.network"):
                    validate_machine(machine(network))

    def test_rejects_non_text(self):
        for network in (None, False, 0, [], {}):
            with self.subTest(network=network):
                with self.assertRaisesRegex(ConfigError, r"sharing\.network"):
                    validate_machine(machine(network))

    def test_default_network_stays_scoped(self):
        validated = validate_machine({"disk": "/dev/disk/by-id/ata-EXAMPLE_SSD"})
        self.assertEqual(validated["sharing"]["network"], "192.0.2.0/24")
        self.assertEqual(validated["sharing"]["mode"], "client")

    def test_smb_and_admin_networks_are_independent(self):
        raw = machine("0.0.0.0/0")
        raw["admin"] = {"network": "203.0.113.10/32"}
        validated = validate_machine(raw)
        self.assertEqual(validated["sharing"]["network"], "0.0.0.0/0")
        self.assertEqual(validated["admin"]["network"], "203.0.113.10/32")
        raw["sharing"]["network"] = "192.168.1.0/24"
        raw["admin"]["network"] = "0.0.0.0/0"
        validated = validate_machine(raw)
        self.assertEqual(validated["sharing"]["network"], "192.168.1.0/24")
        self.assertEqual(validated["admin"]["network"], "0.0.0.0/0")
        raw["admin"]["network"] = "0.0.0.0"
        with self.assertRaisesRegex(ConfigError, r"admin\.network"):
            validate_machine(raw)


if __name__ == "__main__":
    unittest.main()
