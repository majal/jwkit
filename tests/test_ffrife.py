from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import load_script_module


class FfrifeConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.ffrife.CONFIG_DIR = Path(td)
            self.ffrife.CONFIG_FILE = Path(td) / "config.toml"
            config = self.ffrife.load_config()
            config["rife_binary_path"] = "/fake/rife"
            self.ffrife.save_config(config)
            reloaded = self.ffrife.load_config()
            self.assertEqual(reloaded["rife_binary_path"], "/fake/rife")

    def test_defaults_when_no_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.ffrife.CONFIG_DIR = Path(td)
            self.ffrife.CONFIG_FILE = Path(td) / "does-not-exist.toml"
            config = self.ffrife.load_config()
            self.assertEqual(config, self.ffrife.DEFAULT_CONFIG)


class FfrifeEncodeArgsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_default_cpu_matches_jwsl(self) -> None:
        config = {"hardware_encoder": "cpu", "video_codec": "h264", "video_crf": "20", "video_preset": "slow"}
        args = self.ffrife.build_encode_args(config)
        self.assertIn("libx264", args)
        self.assertIn("-crf", args)
        self.assertIn("20", args)

    def test_videotoolbox_quality_matches_jwsl_formula(self) -> None:
        # Same "100 - crf" recalibration as jwsl's videotoolbox_quality_from_crf
        # (see jwsl's detect_hardware_encoder docstring for the benchmark).
        self.assertEqual(self.ffrife.videotoolbox_quality_from_crf("20"), 80)
        self.assertEqual(self.ffrife.videotoolbox_quality_from_crf("0"), 100)
        self.assertEqual(self.ffrife.videotoolbox_quality_from_crf("120"), 1)


class FfrifeProgressBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_progress_bar_fraction_clamped(self) -> None:
        self.assertEqual(self.ffrife._progress_bar(-0.5, width=10), "-" * 10)
        self.assertEqual(self.ffrife._progress_bar(1.5, width=10), "#" * 10)
        self.assertEqual(self.ffrife._progress_bar(0.5, width=10), "#####-----")


class FfrifeParseSpeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_plain_decimal(self) -> None:
        self.assertEqual(self.ffrife.parse_speed("0.5"), 0.5)
        self.assertEqual(self.ffrife.parse_speed("2.5"), 2.5)

    def test_fraction(self) -> None:
        self.assertAlmostEqual(self.ffrife.parse_speed("1/3"), 1 / 3)

    def test_percent(self) -> None:
        self.assertEqual(self.ffrife.parse_speed("40%"), 0.4)
        self.assertEqual(self.ffrife.parse_speed("150%"), 1.5)


class FfrifeAtempoChainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_no_speed_or_unity_speed_needs_no_retiming(self) -> None:
        self.assertIsNone(self.ffrife.atempo_chain(None))
        self.assertIsNone(self.ffrife.atempo_chain(1))
        self.assertIsNone(self.ffrife.atempo_chain(1.0))

    def test_speed_within_atempos_single_instance_range(self) -> None:
        self.assertEqual(self.ffrife.atempo_chain(0.5), "atempo=0.5")
        self.assertEqual(self.ffrife.atempo_chain(2.0), "atempo=2")

    def test_slow_speed_below_atempos_floor_chains_instances(self) -> None:
        # 0.25 is outside atempo's single-instance [0.5, 2.0] range, so it
        # needs two chained 0.5 instances (0.5 * 0.5 == 0.25) to stay in sync
        # with a setpts=PTS/0.25 video track.
        self.assertEqual(self.ffrife.atempo_chain(0.25), "atempo=0.5,atempo=0.5")

    def test_fast_speed_above_atempos_ceiling_chains_instances(self) -> None:
        self.assertEqual(self.ffrife.atempo_chain(3), "atempo=2.0,atempo=1.5")


class FfrifeSpeedRetimingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_fallback_path_folds_setpts_and_atempo_into_one_command(self) -> None:
        # No rife_binary_path configured -> fallback path. speed should be
        # folded into that SAME ffmpeg command (setpts on -vf, atempo on
        # -af) rather than a second retiming pass.
        config = {"rife_binary_path": "", "rife_fallback_engine": "none"}
        calls = []
        with patch.object(self.ffrife, "run_ffmpeg", lambda cmd, duration=None: calls.append(cmd)):
            ok = self.ffrife.interpolate("in.mp4", "out.mp4", config, speed=0.5)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)  # exactly one ffmpeg invocation - no separate retiming pass
        cmd = calls[0]
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("setpts=PTS/0.5", vf)
        self.assertEqual(cmd[cmd.index("-af") + 1], "atempo=0.5")
        self.assertNotIn("-c:a", cmd)  # -af and -c:a copy are mutually exclusive for the audio stream

    def test_fallback_path_without_speed_keeps_c_a_copy(self) -> None:
        config = {"rife_binary_path": "", "rife_fallback_engine": "none"}
        calls = []
        with patch.object(self.ffrife, "run_ffmpeg", lambda cmd, duration=None: calls.append(cmd)):
            self.ffrife.interpolate("in.mp4", "out.mp4", config)
        cmd = calls[0]
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "copy")
        self.assertNotIn("-vf", cmd)

    def test_rife_path_folds_setpts_into_the_merge_command(self) -> None:
        # RIFE installed/configured -> the PNG-extract-then-RIFE-then-merge
        # path. speed should land on the merge command's -vf, not a
        # separate ffmpeg pass after it.
        config = {"rife_binary_path": "/fake/rife"}
        calls = []

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            calls.append(cmd)
            if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"\x89PNG")

        def fake_run_rife(rife_path, in_frames, out_frames, target_count, slow_after=4.0):
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")
            (Path(out_frames) / "00000002.png").write_bytes(b"\x89PNG")

        with patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "run_rife", fake_run_rife), \
             patch.object(self.ffrife.subprocess, "run"):
            ok = self.ffrife.interpolate("in.mp4", "out.mp4", config, speed=0.5, fps=60)

        self.assertTrue(ok)
        # extract call, then merge call - never a third (retiming) pass
        self.assertEqual(len(calls), 2)
        merge_cmd = calls[-1]
        vf = merge_cmd[merge_cmd.index("-vf") + 1]
        self.assertIn("setpts=PTS/0.5", vf)


class FfrifeCliDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_bare_input_gets_run_prepended(self) -> None:
        # `ffrife in.mp4 -o out.mp4` (no explicit 'run') should work.
        self.assertEqual(self.ffrife.normalize_argv(["in.mp4", "-o", "out.mp4"]), ["run", "in.mp4", "-o", "out.mp4"])

    def test_explicit_run_not_double_prepended(self) -> None:
        self.assertEqual(self.ffrife.normalize_argv(["run", "in.mp4", "-o", "out.mp4"]), ["run", "in.mp4", "-o", "out.mp4"])

    def test_setup_and_config_left_alone(self) -> None:
        self.assertEqual(self.ffrife.normalize_argv(["setup"]), ["setup"])
        self.assertEqual(self.ffrife.normalize_argv(["config", "list"]), ["config", "list"])

    def test_bare_input_parses_with_expected_defaults(self) -> None:
        args = self.ffrife.build_parser().parse_args(self.ffrife.normalize_argv(["in.mp4", "-o", "out.mp4"]))
        self.assertEqual(args.command, "run")
        self.assertEqual(args.input, "in.mp4")
        self.assertEqual(args.output, "out.mp4")
        self.assertEqual(args.fps, 60)


if __name__ == "__main__":
    unittest.main()
