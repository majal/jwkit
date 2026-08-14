from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

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


class FfinpaintInpaintTest(unittest.TestCase):
    """inpaint() itself was previously untested - only its write_mask/config
    helpers were. Mocks subprocess.run rather than requiring a real
    E2FGVI-HQ checkout (see docs/ffinpaint.md: never bundled, opt-in only)."""

    def setUp(self) -> None:
        self.ffinpaint = load_script_module("ffinpaint")
        self.ffinpaint.probe_size = lambda source: (1280, 720, 30.0)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / "e2fgvi"
        root.mkdir()
        (root / "test.py").write_text("# stub")
        checkpoint = Path(self.tmp.name) / "ckpt.pth"
        checkpoint.write_text("stub")
        self.config = {"e2fgvi_root": str(root), "e2fgvi_checkpoint": str(checkpoint)}
        self.calls = []

    def fake_run(self, make_frames=True, make_result=True):
        def run(cmd, check=True, cwd=None, **kwargs):
            self.calls.append(cmd)
            if cmd[0] == self.ffinpaint.FFMPEG_BIN:
                if make_frames:
                    out_pattern = Path(cmd[-1])
                    (out_pattern.parent / "00000001.png").write_bytes(b"x")
            else:
                if make_result:
                    results_dir = Path(cwd) / "results"
                    results_dir.mkdir(parents=True, exist_ok=True)
                    (results_dir / "frames_results.mp4").write_bytes(b"video")
            return None
        return run

    def test_returns_false_when_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as out_dir:
            result = self.ffinpaint.inpaint(
                "in.mp4", Path(out_dir) / "out.mp4", (10, 10, 20, 20),
                {"e2fgvi_root": "", "e2fgvi_checkpoint": ""},
            )
        self.assertFalse(result)
        self.assertEqual(self.calls, [])

    def test_builds_correct_commands_and_copies_result(self) -> None:
        with mock.patch.object(self.ffinpaint.subprocess, "run", self.fake_run()):
            with tempfile.TemporaryDirectory() as out_dir:
                output = Path(out_dir) / "out.mp4"
                result = self.ffinpaint.inpaint("in.mp4", output, (10, 10, 20, 20), self.config, start=1.0, end=5.0)
                # Assert inside the TemporaryDirectory block - it (and
                # `output` within it) is deleted on exit.
                self.assertTrue(result)
                self.assertTrue(output.exists())
        self.assertEqual(len(self.calls), 2)
        extract_cmd, runner_cmd = self.calls
        self.assertIn("-ss", extract_cmd)
        self.assertIn("1.0", extract_cmd)
        self.assertIn("-to", extract_cmd)
        self.assertIn("5.0", extract_cmd)
        self.assertIn("--model", runner_cmd)
        self.assertIn("e2fgvi_hq", runner_cmd)
        self.assertIn("--savefps", runner_cmd)
        self.assertIn("30", runner_cmd)  # round(30.0)
        self.assertIn(str(Path(self.config["e2fgvi_checkpoint"])), runner_cmd)

    def test_raises_when_no_frames_extracted(self) -> None:
        with mock.patch.object(self.ffinpaint.subprocess, "run", self.fake_run(make_frames=False)):
            with tempfile.TemporaryDirectory() as out_dir:
                with self.assertRaises(RuntimeError):
                    self.ffinpaint.inpaint("in.mp4", Path(out_dir) / "out.mp4", (10, 10, 20, 20), self.config)

    def test_raises_when_e2fgvi_produces_no_result(self) -> None:
        with mock.patch.object(self.ffinpaint.subprocess, "run", self.fake_run(make_result=False)):
            with tempfile.TemporaryDirectory() as out_dir:
                with self.assertRaises(RuntimeError):
                    self.ffinpaint.inpaint("in.mp4", Path(out_dir) / "out.mp4", (10, 10, 20, 20), self.config)
