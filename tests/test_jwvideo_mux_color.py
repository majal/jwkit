from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from tests.support import load_script_module


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


if __name__ == "__main__":
    unittest.main()
