"""Additive inventory metadata and per-device evidence, without TOML changes."""
import copy
import unittest

from tests.test_assistant import inventory_text
from nix2office.config import ConfigError, DEFAULTS
from nix2office.hardware import hardware_review, machine_hardware, parse_probe, PROBE, RULES_VERSION


def inventory(pci, details=""):
    return parse_probe(inventory_text().replace(
        "N2O_GPU=i915", "N2O_KERNEL=6.18.1\nN2O_PCI=" + pci + "\n" + details
        + "N2O_FIRMWARE_LOG_READABLE=1\nN2O_GPU="))


class HardwareEvidenceTests(unittest.TestCase):
    def test_old_inventory_and_toml_are_compatible(self):
        old = parse_probe(inventory_text())
        self.assertEqual(old['kernel_version'], 'unknown')
        self.assertEqual(old['pci_devices'], [])
        self.assertEqual(set(machine_hardware(old)), set(DEFAULTS['hardware']))

    def test_intel_and_old_amd_keep_bound_drivers(self):
        for vendor, device, driver in [('8086', '1234', 'i915'), ('1002', '983d', 'radeon')]:
            raw = '030000:' + vendor + ':' + device + ':' + driver
            detail = 'N2O_PCI_DETAIL=0000:01:00.0\t030000\t' + vendor + '\t' + device + '\t' + driver + '\t' + driver + ',\tgpu/optional.bin,\n'
            inv = inventory(raw, detail)
            before = copy.deepcopy(inv)
            report = hardware_review(inv)
            self.assertEqual(inv, before)
            self.assertEqual(report['kernel_version'], '6.18.1')
            self.assertEqual(report['rules_version'], RULES_VERSION)
            self.assertEqual(report['early_modules'], [driver])
            fact = report['devices'][0]
            self.assertEqual(fact['address'], '0000:01:00.0')
            self.assertEqual(fact['candidates'], [driver])
            self.assertEqual(fact['firmware_declared_sample'], ['gpu/optional.bin'])
            self.assertEqual(fact['status'], 'pass') # Binding only, not acceleration.
            self.assertIn('не доказва', fact['action'])

    def test_identical_pci_ids_keep_distinct_bus_addresses(self):
        raw = '020000:8086:1234:e1000e'
        details = ''.join('N2O_PCI_DETAIL=' + address + '\t020000\t8086\t1234\te1000e\te1000e,\tnone\n'
                          for address in ['0000:01:00.0', '0000:02:00.0'])
        report = hardware_review(inventory(raw + ' ' + raw, details))
        self.assertEqual([d['address'] for d in report['devices']], ['0000:01:00.0', '0000:02:00.0'])

    def test_essential_interfaces_receive_status_and_action(self):
        inv = inventory('010000:8086:1234:ahci 020000:14e4:1692:unbound 040300:8086:1234:snd_hda_intel 060400:8086:1234:unbound')
        report = hardware_review(inv)
        self.assertEqual([d['status'] for d in report['devices']], ['pass', 'warning', 'pass', 'not-applicable'])
        self.assertTrue(all(d['action'] for d in report['devices']))
        self.assertTrue(report['needs_review'])

    def test_invalid_bus_address_is_not_accepted_as_fact(self):
        with self.assertRaises(ConfigError):
            inventory('030000:8086:1234:i915', 'N2O_PCI_DETAIL=bad\t030000\t8086\t1234\ti915\ti915,\tnone\n')

    def test_probe_reads_metadata_without_loading_modules(self):
        self.assertIn('uname -r', PROBE)
        self.assertIn('modinfo -F firmware', PROBE)
        self.assertIn('modprobe --resolve-alias', PROBE)
        self.assertNotIn('modprobe -a', PROBE)

    def test_malformed_additive_metadata_gives_config_error(self):
        for value in ('invalid', [None], [1]):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                hardware_review({'pci_devices': value})


if __name__ == '__main__':
    unittest.main()
