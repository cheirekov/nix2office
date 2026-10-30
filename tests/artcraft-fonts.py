#!/usr/bin/env python3
"""Exercise the built WordCraft release's font scanner without a display.

See docs/artcraft-fonts.md for the pinned build and invocation. Requires Linux
user/mount namespaces; run outside the Nix build sandbox.
"""

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from xml.sax.saxutils import escape


class ArtCraftFonts(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="artcraft-font-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ("home", "runtime", "cache", "xdg data", "installed fonts"):
            (self.root / name).mkdir()
        self.env = dict(os.environ)
        self.env.update(
            HOME=str(self.root / "home"),
            TMPDIR=str(self.root / "runtime"),
            XDG_DATA_HOME=str(self.root / "xdg data"),
            XDG_CONFIG_HOME=str(self.root / "home" / ".config"),
            XDG_CACHE_HOME=str(self.root / "cache"),
        )
        self.config = self.root / "fonts.conf"
        self.env["FONTCONFIG_FILE"] = str(self.config)
        self.config.write_text(
            f"<fontconfig><include>{escape(str(self.root / 'included.conf'))}</include>"
            '<dir prefix="xdg">fonts</dir>'
            f"<cachedir>{escape(str(self.root / 'cache'))}</cachedir></fontconfig>"
        )
        (self.root / "included.conf").write_text(
            f"<fontconfig><dir>{escape(str(self.root / 'installed fonts'))}"
            "</dir></fontconfig>"
        )

    def run_cli(self, *args, original=False, check=True):
        # Hide FHS fonts and any Flatpak host font mounts to model NixOS. All
        # executables/libraries used by the release live in the Nix store.
        executable = OPTIONS.package / ("libexec" if original else "bin") / "wordcraft-cli"
        result = subprocess.run(
            [str(OPTIONS.bwrap), "--bind", "/", "/", "--tmpfs", "/usr",
             "--tmpfs", "/run", "--", str(executable), *args],
            env=self.env, text=True, capture_output=True, timeout=60, check=check,
        )
        return result

    def families(self, original=False):
        result = self.run_cli("run", "--cmd", 'font.list={"all":true}',
                              "--print", original=original)
        return set(json.loads(result.stdout.split(": ", 1)[1])["families"])

    def install_fixture(self, user=False):
        directory = self.root / ("xdg data/fonts" if user else "installed fonts")
        directory.mkdir(exist_ok=True)
        # Exercise spaces, quotes, shell syntax, a newline and an uppercase
        # extension. A line-based list or shell evaluation would break this.
        path = directory / "font ' $(touch INJECTED)\nfixture.TTF"
        shutil.copyfile(OPTIONS.font, path)
        return path

    def assert_clean(self):
        self.assertEqual(list((self.root / "runtime").iterdir()), [])
        self.assertEqual(list((self.root / "home").iterdir()), [])
        self.assertFalse((self.root / "INJECTED").exists())
        self.assertFalse(Path("INJECTED").exists())

    def test_included_fontconfig_directory_reaches_actual_scanner(self):
        self.install_fixture()
        baseline = self.families(original=True)
        self.assertNotIn(OPTIONS.family, baseline)
        self.assertIn(OPTIONS.family, self.families())
        self.assertIn("Source Sans 3", baseline)  # Embedded release fonts remain.
        self.assert_clean()

    def test_custom_xdg_data_home(self):
        self.install_fixture(user=True)
        self.assertNotIn(OPTIONS.family, self.families(original=True))
        self.assertIn(OPTIONS.family, self.families())
        self.assert_clean()

    def test_removal_has_no_stale_projection(self):
        path = self.install_fixture()
        self.assertIn(OPTIONS.family, self.families())
        path.unlink()
        self.assertNotIn(OPTIONS.family, self.families())
        self.assert_clean()

    def test_concurrent_launches(self):
        self.install_fixture()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.families(), range(3)))
        self.assertTrue(all(OPTIONS.family in families for families in results))
        self.assert_clean()

    def test_empty_fontconfig_keeps_bundled_fonts(self):
        # Fontconfig may add its compiled-in minimal fallback when no fonts
        # were found. The embedded release families must all remain available.
        self.assertTrue(self.families(original=True).issubset(self.families()))
        self.assert_clean()

    def test_cli_error_status_and_cleanup(self):
        baseline = self.run_cli("not-a-command", original=True, check=False)
        wrapped = self.run_cli("not-a-command", check=False)
        self.assertNotEqual(baseline.returncode, 0)
        self.assertEqual(wrapped.returncode, baseline.returncode)
        self.assert_clean()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--family", default="Carlito")
    parser.add_argument("--bwrap", type=Path, required=True)
    OPTIONS = parser.parse_args()
    unittest.main(argv=[__file__], verbosity=2)
