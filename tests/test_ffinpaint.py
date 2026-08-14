from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests.support import load_script_module


class FfinpaintConfigAndMaskTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ffinpaint = load_script_module("ffinpaint")

    def test_defaults_are_safe_without_a_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.ffinpaint.CONFIG_FILE = Path(tmp) / "missing.toml"
            config = self.ffinpaint.load_config()
            self.assertEqual(config["fallback"], "blur")
            self.assertFalse(self.ffinpaint.configured(config))

    def test_mask_marks_only_the_requested_box(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mask.pgm"
            self.ffinpaint.write_mask(path, 4, 3, (1, 1, 2, 1))
            payload = path.read_bytes().split(b"\n", 3)[3]
            self.assertEqual(payload, bytes([0, 0, 0, 0, 0, 255, 255, 0, 0, 0, 0, 0]))
