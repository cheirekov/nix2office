import unittest
from nix2office.hardware import hardware_review, machine_hardware, parse_probe, PROBE
from tests.test_assistant import inventory_text
class HardwareReviewTests(unittest.TestCase):
    def test_9400_gt_auto_nouveau_from_pci_even_without_drm_node(self):
        inv=parse_probe(inventory_text().replace('N2O_GPU=i915','N2O_PCI=030000:10de:0641:nouveau 020000:14e4:1692:tg3\nN2O_FIRMWARE_LOG_READABLE=1\nN2O_GPU='))
        r=hardware_review(inv)
        self.assertEqual(r['early_modules'],['nouveau'])
        self.assertFalse(r['needs_review'])
        self.assertTrue(any('9400 GT' in n for n in r['notes']))
        self.assertEqual(machine_hardware(inv)['initrd_modules'],['nouveau'])
        self.assertFalse(inv['bluetooth_detected'])
    def test_unbound_and_firmware_are_distinct_evidence(self):
        r=hardware_review(dict(pci_ids=['020000:14e4:1692:unbound'],driver_candidates=['020000:14e4:1692:tg3'],firmware_log_readable=True))
        self.assertTrue(r['needs_review']);self.assertTrue(any('tg3' in n for n in r['notes']))
        r=hardware_review(dict(missing_firmware=['example.bin']))
        self.assertTrue(r['needs_review']);self.assertTrue(any('example.bin' in n for n in r['notes']))
    def test_unknown_nvidia_and_hybrid_need_review(self):
        for ids in (['030000:10de:ffff:unbound'],['030000:10de:0641:nouveau','030000:8086:1234:i915']):
            self.assertTrue(hardware_review(dict(pci_ids=ids))['needs_review'])
    def test_usb_interface_and_storage_coverage(self):
        self.assertTrue(hardware_review(dict(usb_interfaces=['0bda:b723:e0:unbound']))['needs_review'])
        self.assertFalse(hardware_review(dict(usb_interfaces=['0bda:b723:e0:btusb']))['needs_review'])
        self.assertTrue(hardware_review(dict(pci_ids=['010000:8086:1234:unbound']))['needs_review'])
        self.assertFalse(hardware_review(dict(pci_ids=['060400:8086:1234:unbound'],driver_candidates=['060400:8086:1234:intel_agp']))['needs_review'])
    def test_probe_does_not_load_candidates(self):
        self.assertIn('modprobe --resolve-alias',PROBE)
        self.assertNotIn('modprobe -a',PROBE)
