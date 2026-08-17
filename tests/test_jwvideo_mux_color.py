from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout

from tests.support import load_script_module
from pathlib import Path


class JwvideoMuxColorOutputTest(unittest.TestCase):
    """color_print used to hardcode ANSI escape codes unconditionally,
    regardless of whether stdout was a real terminal - it now respects the
    shared Colorizer's resolved enabled/disabled state like every other
    jwkit tool, without needing every call site (it takes a raw numeric
    color code, not a named one) to change."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mux = load_script_module("jwvideo-mux")

    def test_color_print_emits_ansi_when_enabled(self) -> None:
        self.mux.COLOR = self.mux._jwkit_common.Colorizer(True)
        out = io.StringIO()
        with redirect_stdout(out):
            self.mux.color_print("hello", "31")
        self.assertIn("\033[31m", out.getvalue())

    def test_color_print_plain_when_disabled(self) -> None:
        self.mux.COLOR = self.mux._jwkit_common.Colorizer(False)
        out = io.StringIO()
        with redirect_stdout(out):
            self.mux.color_print("hello", "31")
        self.assertNotIn("\033[", out.getvalue())
        self.assertIn("hello", out.getvalue())

    def test_color_print_with_no_code_is_always_plain(self) -> None:
        self.mux.COLOR = self.mux._jwkit_common.Colorizer(True)
        out = io.StringIO()
        with redirect_stdout(out):
            self.mux.color_print("hello")
        self.assertNotIn("\033[", out.getvalue())

    def test_config_defaults_and_roundtrip_cover_behavior_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_file, old_dir = self.mux.CONFIG_FILE, self.mux.CONFIG_DIR
            self.addCleanup(setattr, self.mux, "CONFIG_FILE", old_file)
            self.addCleanup(setattr, self.mux, "CONFIG_DIR", old_dir)
            self.mux.CONFIG_DIR = Path(tmp)
            self.mux.CONFIG_FILE = Path(tmp) / "config.toml"
            defaults = self.mux.load_config()
            self.assertEqual(defaults, self.mux.DEFAULT_CONFIG)
            defaults["cleanup"] = True
            defaults["res"] = "1080p"
            self.mux.save_config(defaults)
            self.assertEqual(self.mux.load_config(), defaults)


if __name__ == "__main__":
    unittest.main()
