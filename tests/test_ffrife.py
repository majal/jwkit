from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_run_encoder_overrides_parse(self) -> None:
        args = self.ffrife.build_parser().parse_args([
            "run", "input.mp4", "-o", "output.mp4", "--encoder", "nvenc",
            "--codec", "hevc", "--crf", "24", "--preset", "fast",
        ])
        self.assertEqual((args.encoder, args.codec, args.crf, args.preset), ("nvenc", "hevc", "24", "fast"))


class FfrifeEncodeArgsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def setUp(self) -> None:
        # See SlverseEncodeArgsTest's own setUp in tests/test_slverse.py for
        # why this is stubbed rather than left to the real ffmpeg installed
        # on the test machine - same shared _jwkit_common module/cache, same
        # reasoning.
        common = self.ffrife._jwkit_common
        self._orig_has_encoder = common.ffmpeg_has_encoder
        self._orig_resolved_cache = dict(common._RESOLVED_ENCODER_CACHE)
        self._orig_warned = set(common._ENCODER_FALLBACK_WARNED)
        common._RESOLVED_ENCODER_CACHE.clear()
        common._ENCODER_FALLBACK_WARNED.clear()
        common.ffmpeg_has_encoder = lambda ffmpeg_bin, name: name in {
            "libx264", "libx265", "libsvtav1", "h264_videotoolbox", "hevc_videotoolbox",
        }
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        common = self.ffrife._jwkit_common
        common.ffmpeg_has_encoder = self._orig_has_encoder
        common._RESOLVED_ENCODER_CACHE.clear()
        common._RESOLVED_ENCODER_CACHE.update(self._orig_resolved_cache)
        common._ENCODER_FALLBACK_WARNED.clear()
        common._ENCODER_FALLBACK_WARNED.update(self._orig_warned)

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

    def test_auto_quality_is_codec_specific(self) -> None:
        for codec, crf in (("h264", "20"), ("hevc", "23"), ("av1", "30")):
            args = self.ffrife.build_encode_args({"hardware_encoder": "cpu", "video_codec": codec, "video_crf": "auto", "video_preset": "slow"}, notice=False)
            self.assertIn(crf, args)

    def test_av1_unavailable_falls_back_to_hevc(self) -> None:
        common = self.ffrife._jwkit_common
        common.ffmpeg_has_encoder = lambda ffmpeg_bin, name: name == "libx265"
        args = self.ffrife.build_encode_args({"hardware_encoder": "cpu", "video_codec": "av1", "video_crf": "auto", "video_preset": "slow"}, notice=False)
        self.assertIn("libx265", args)


class FfrifeGenericConfigOverrideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_every_non_excluded_key_gets_a_flag(self) -> None:
        parser = argparse.ArgumentParser()
        self.ffrife.add_generic_config_overrides(parser)
        dests = {action.dest for action in parser._actions}
        expected = set(self.ffrife.DEFAULT_CONFIG) - self.ffrife.GENERIC_OVERRIDE_EXCLUDED_KEYS
        self.assertTrue(expected.issubset(dests))

    def test_apply_overrides_only_provided_values(self) -> None:
        parser = argparse.ArgumentParser()
        self.ffrife.add_generic_config_overrides(parser)
        args = parser.parse_args(["--rife-binary-path", "/custom/rife"])
        config = dict(self.ffrife.DEFAULT_CONFIG)
        self.ffrife.apply_generic_config_overrides(args, config)
        self.assertEqual(config["rife_binary_path"], "/custom/rife")

    def test_ffmpeg_binary_override_applies_before_resolution(self) -> None:
        # main() applies generic overrides before resolve_ffmpeg_binary() -
        # regression guard for the ordering bug where --ffmpeg-binary was
        # applied to config only *after* FFMPEG_BIN had already been
        # resolved from the pre-override config, silently ignoring it.
        args = self.ffrife.build_parser().parse_args(["run", "in.mp4", "-o", "out.mp4", "--ffmpeg-binary", "/custom/ffmpeg"])
        config = dict(self.ffrife.DEFAULT_CONFIG)
        self.ffrife.apply_generic_config_overrides(args, config)
        self.assertEqual(config["ffmpeg_binary"], "/custom/ffmpeg")


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


class FfrifeRetimedDurationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_no_speed_or_unity_speed_leaves_duration_unchanged(self) -> None:
        self.assertEqual(self.ffrife.retimed_duration(10.0, None), 10.0)
        self.assertEqual(self.ffrife.retimed_duration(10.0, 1), 10.0)

    def test_half_speed_doubles_the_progress_bar_duration(self) -> None:
        # setpts=PTS/0.5 makes the OUTPUT run twice as long as the source
        # window ffmpeg's own out_time= progress is measured against.
        self.assertAlmostEqual(self.ffrife.retimed_duration(10.0, 0.5), 20.0)

    def test_triple_speed_shrinks_the_progress_bar_duration(self) -> None:
        self.assertAlmostEqual(self.ffrife.retimed_duration(9.0, 3), 3.0)

    def test_none_duration_passes_through(self) -> None:
        # No --start/--end given -> duration is None (whole file, unknown
        # length) - nothing to retime.
        self.assertIsNone(self.ffrife.retimed_duration(None, 0.5))


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

    def test_fallback_path_passes_retimed_duration_to_progress_bar(self) -> None:
        config = {"rife_binary_path": "", "rife_fallback_engine": "none"}
        durations = []
        with patch.object(self.ffrife, "run_ffmpeg", lambda cmd, duration=None: durations.append(duration)):
            self.ffrife.interpolate("in.mp4", "out.mp4", config, start=0.0, end=10.0, speed=0.5)
        self.assertAlmostEqual(durations[0], 20.0)

    def test_fallback_path_without_speed_keeps_c_a_copy(self) -> None:
        config = {"rife_binary_path": "", "rife_fallback_engine": "none"}
        calls = []
        with patch.object(self.ffrife, "run_ffmpeg", lambda cmd, duration=None: calls.append(cmd)):
            self.ffrife.interpolate("in.mp4", "out.mp4", config)
        cmd = calls[0]
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "copy")
        self.assertNotIn("-vf", cmd)

    def test_output_filter_is_applied_only_in_the_final_encode(self) -> None:
        config = {"rife_binary_path": "/fake/rife", "scene_detection": "false"}
        calls = []

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            calls.append(cmd)
            if cmd and str(cmd[-1]).endswith("%08d.png"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"\x89PNG")

        def fake_run_rife(rife_path, in_frames, out_frames, target_count, model_path=None, slow_after=4.0):
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")

        with patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "run_rife", fake_run_rife), \
             patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
             patch.object(self.ffrife.subprocess, "run"):
            self.ffrife.interpolate("in.mp4", "out.mp4", config, output_vf="drawtext=text='label'", fps=60)

        self.assertNotIn("-vf", calls[0])
        self.assertEqual(calls[-1][calls[-1].index("-vf") + 1], "drawtext=text='label'")

    def test_rife_path_generates_retimed_frames_before_the_merge(self) -> None:
        # RIFE installed/configured -> the PNG-extract-then-RIFE-then-merge
        # path. RIFE should generate the retimed count directly, without a
        # setpts filter that would duplicate frames in the merge.
        config = {"rife_binary_path": "/fake/rife"}
        calls = []
        target_counts = []

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            calls.append(cmd)
            if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"\x89PNG")

        def fake_run_rife(rife_path, in_frames, out_frames, target_count, model_path=None, slow_after=4.0):
            target_counts.append(target_count)
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")
            (Path(out_frames) / "00000002.png").write_bytes(b"\x89PNG")

        with patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "run_rife", fake_run_rife), \
             patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
             patch.object(self.ffrife.subprocess, "run"):
            ok = self.ffrife.interpolate("in.mp4", "out.mp4", config, speed=0.5, fps=60)

        self.assertTrue(ok)
        # extract call, then merge call - never a third (retiming) pass
        self.assertEqual(len(calls), 2)
        merge_cmd = calls[-1]
        self.assertNotIn("-vf", merge_cmd)
        self.assertEqual(target_counts, [4])  # one 30fps input frame -> 60fps, then 2x duration

    def test_rife_target_count_matches_a_non_2x_ratio(self) -> None:
        # 24fps source -> 60fps target is a 2.5x ratio, not RIFE's implicit
        # 2x default - target_count has to be computed explicitly.
        config = {"rife_binary_path": "/fake/rife", "scene_detection": "false"}
        rife_calls = []

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                for i in range(24):
                    (Path(cmd[-1]).parent / f"{i:08d}.png").write_bytes(b"\x89PNG")

        def fake_run_rife(rife_path, in_frames, out_frames, target_count, model_path=None, slow_after=4.0):
            rife_calls.append((target_count, model_path))
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")

        with patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "run_rife", fake_run_rife), \
             patch.object(self.ffrife, "probe_source_fps", return_value=24.0), \
             patch.object(self.ffrife.subprocess, "run"):
            ok = self.ffrife.interpolate("in.mp4", "out.mp4", config, fps=60)

        self.assertTrue(ok)
        self.assertEqual(len(rife_calls), 1)
        target_count, model_path = rife_calls[0]
        self.assertEqual(target_count, 60)  # 24 frames * 60/24

    def test_rife_model_path_derives_from_rife_binary_directory(self) -> None:
        config = {"rife_binary_path": "/fake/bin/rife-ncnn-vulkan", "rife_model": "rife-v4.6"}
        rife_calls = []

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"\x89PNG")

        def fake_run_rife(rife_path, in_frames, out_frames, target_count, model_path=None, slow_after=4.0):
            rife_calls.append(model_path)
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")

        with patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "run_rife", fake_run_rife), \
             patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
             patch.object(self.ffrife.subprocess, "run"):
            self.ffrife.interpolate("in.mp4", "out.mp4", config, fps=60)

        self.assertEqual(len(rife_calls), 1)
        self.assertEqual(str(rife_calls[0]), "/fake/bin/rife-v4.6")


class FfrifePruneUnusedModelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_keeps_only_the_configured_model_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            models_dir = Path(td)
            for name in ("rife-v2.3", "rife-v4", "rife-v4.6", "rife-anime"):
                (models_dir / name).mkdir()
                (models_dir / name / "flownet.param").write_bytes(b"x")
            (models_dir / "rife-ncnn-vulkan").write_bytes(b"\x7fELF")  # the executable, a file not a dir
            (models_dir / "LICENSE").write_bytes(b"MIT")

            self.ffrife.prune_unused_models(models_dir, "rife-v4.6")

            remaining_dirs = {p.name for p in models_dir.iterdir() if p.is_dir()}
            self.assertEqual(remaining_dirs, {"rife-v4.6"})
            # non-model files are untouched
            self.assertTrue((models_dir / "rife-ncnn-vulkan").exists())
            self.assertTrue((models_dir / "LICENSE").exists())


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

    def test_benchmark_not_treated_as_a_bare_input_file(self) -> None:
        # Regression guard: without "benchmark" in normalize_argv's known-
        # subcommand set, `ffrife benchmark` would get rewritten to
        # `ffrife run benchmark`, treating the word "benchmark" as an input
        # filename instead of dispatching to cmd_benchmark.
        self.assertEqual(self.ffrife.normalize_argv(["benchmark"]), ["benchmark"])
        args = self.ffrife.build_parser().parse_args(self.ffrife.normalize_argv(["benchmark", "--sample", "x.mp4"]))
        self.assertEqual(args.command, "benchmark")
        self.assertEqual(args.sample, "x.mp4")

    def test_bare_input_parses_with_expected_defaults(self) -> None:
        args = self.ffrife.build_parser().parse_args(self.ffrife.normalize_argv(["in.mp4", "-o", "out.mp4"]))
        self.assertEqual(args.command, "run")
        self.assertEqual(args.input, "in.mp4")
        self.assertEqual(args.output, "out.mp4")
        self.assertEqual(args.fps, "60")

    def test_batch_and_bulk_are_known_subcommands(self) -> None:
        for name in ("batch", "bulk"):
            argv = [name, "clips", "-O", "done"]
            self.assertEqual(self.ffrife.normalize_argv(argv), argv)
            self.assertIn(self.ffrife.build_parser().parse_args(argv).command, ("batch", "bulk"))


class FfrifeLongRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_chunk_ranges_overlap_one_frame(self) -> None:
        self.assertEqual(self.ffrife._chunk_ranges(10, 4), [(0, 4), (3, 7), (6, 10)])
        self.assertEqual(self.ffrife._chunk_ranges(10, 0), [(0, 10)])
        with self.assertRaises(ValueError):
            self.ffrife._chunk_ranges(10, 1)

    def test_auto_profile_preserves_upstream_defaults_for_short_single_run(self) -> None:
        config = dict(self.ffrife.DEFAULT_CONFIG)
        policy = self.ffrife.resolve_rife_policy(config, 300)
        self.assertEqual(policy["resolved_rife_profile"], "performance")
        self.assertEqual(policy["rife_threads"], "auto")
        self.assertEqual(policy["chunk_frames"], "0")
        self.assertEqual(policy["cooldown_seconds"], "0")

    def test_auto_profile_uses_balanced_policy_for_long_or_batch_work(self) -> None:
        config = dict(self.ffrife.DEFAULT_CONFIG)
        long_policy = self.ffrife.resolve_rife_policy(config, 3600)
        config["_batch_mode"] = True
        batch_policy = self.ffrife.resolve_rife_policy(config, 30)
        for policy in (long_policy, batch_policy):
            self.assertEqual(policy["resolved_rife_profile"], "balanced")
            self.assertEqual(policy["rife_threads"], "auto")
            self.assertEqual(policy["chunk_frames"], "1200")
            self.assertEqual(policy["cooldown_seconds"], "15")

    def test_low_level_settings_override_profile_independently(self) -> None:
        config = dict(self.ffrife.DEFAULT_CONFIG)
        config.update({"rife_profile": "cool", "rife_threads": "1:3:2", "cooldown_seconds": "2.5"})
        policy = self.ffrife.resolve_rife_policy(config, 10)
        self.assertEqual(policy["rife_threads"], "1:3:2")
        self.assertEqual(policy["chunk_frames"], "600")
        self.assertEqual(policy["cooldown_seconds"], "2.5")

    def test_cool_profile_rests_twice_as_often_as_balanced(self) -> None:
        # cool's whole point is thermal headroom - it should rest more
        # often than balanced, not just carry less parallel load per chunk.
        config = dict(self.ffrife.DEFAULT_CONFIG)
        config["rife_profile"] = "cool"
        cool_policy = self.ffrife.resolve_rife_policy(config, 10)
        config["rife_profile"] = "balanced"
        balanced_policy = self.ffrife.resolve_rife_policy(config, 10)
        self.assertEqual(cool_policy["cooldown_seconds"], balanced_policy["cooldown_seconds"])
        self.assertEqual(int(cool_policy["chunk_frames"]) * 2, int(balanced_policy["chunk_frames"]))

    def test_profile_convenience_flags(self) -> None:
        parser = self.ffrife.build_parser()
        self.assertEqual(parser.parse_args(["run", "in", "-o", "out", "--cool"]).rife_profile, "cool")
        self.assertEqual(parser.parse_args(["run", "in", "-o", "out", "--perf"]).rife_profile, "performance")

    def test_chunks_assemble_exact_target_and_resume(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming, outgoing = root / "in", root / "out"
            incoming.mkdir()
            for index in range(10):
                (incoming / f"{index:08d}.png").write_bytes(b"png")

            def fake_run(_binary, _input, output, target_count, **_kwargs):
                calls.append(target_count)
                for index in range(target_count):
                    (Path(output) / f"{index:08d}.png").write_bytes(b"png")

            config = {"chunk_frames": "4", "cooldown_seconds": "3", "rife_threads": "1:1:1", "rife_gpu": "auto"}
            with patch.object(self.ffrife, "run_rife", fake_run), patch.object(self.ffrife.time, "sleep") as sleep:
                self.ffrife._render_rife_chunks("rife", incoming, outgoing, 25, "model", config, root / "state.json")
                self.assertEqual(len(list(outgoing.glob("*.png"))), 25)
                self.assertEqual(sleep.call_count, 2)
                first_calls = list(calls)
                self.ffrife._render_rife_chunks("rife", incoming, outgoing, 25, "model", config, root / "state.json")
            self.assertEqual(calls, first_calls)

    def test_run_rife_passes_resource_controls(self) -> None:
        process = MagicMock()
        process.poll.side_effect = [0, 0]
        process.returncode = 0
        with patch.object(self.ffrife.subprocess, "Popen", return_value=process) as popen:
            self.ffrife.run_rife("rife", "in", "out", 12, threads="1:1:1", gpu="cpu")
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-j") + 1], "1:1:1")
        self.assertEqual(command[command.index("-g") + 1], "-1")

    def test_transition_detector_finds_an_isolated_hard_cut(self) -> None:
        # 6 static RGB frames, then a permanent jump to a very different
        # color that holds - an isolated, unaligned, non-reverting spike is
        # exactly a hard cut. Mocked rawvideo keeps this independent of an
        # ffmpeg installation.
        frames = [bytes([50] * (32 * 18 * 3)) for _ in range(6)]
        frames += [bytes([200] * (32 * 18 * 3)) for _ in range(4)]
        process = MagicMock(stdout=io.BytesIO(b"".join(frames)), returncode=0)
        process.wait.return_value = 0
        with patch.object(self.ffrife.subprocess, "Popen", return_value=process) as popen:
            cuts, transitions = self.ffrife.detect_transitions("frames", source_fps=24)
        self.assertEqual(cuts, [6])
        self.assertEqual(transitions, [])
        command = popen.call_args.args[0]
        self.assertIn("rgb24", command)

    def test_transition_detector_cut_floor_and_revert_fraction_are_tunable(self) -> None:
        # Same isolated-spike sequence as the hard-cut test above, but a
        # deliberately tiny jump (50 -> 60) that a default cut_floor=0.05
        # rejects outright. Raising cut_floor keeps it rejected everywhere;
        # lowering it below the spike's own magnitude reveals the cut - and
        # a revert_fraction of 0 (nothing ever "reverts enough") suppresses
        # it again regardless of floor, proving both knobs are load-bearing.
        frames = [bytes([50] * (32 * 18 * 3)) for _ in range(6)]
        frames += [bytes([60] * (32 * 18 * 3)) for _ in range(4)]
        raw = b"".join(frames)

        def run(**kwargs):
            process = MagicMock(stdout=io.BytesIO(raw), returncode=0)
            process.wait.return_value = 0
            with patch.object(self.ffrife.subprocess, "Popen", return_value=process):
                return self.ffrife.detect_transitions("frames", source_fps=24, **kwargs)

        cuts_default, _ = run()
        self.assertEqual(cuts_default, [])
        cuts_low_floor, _ = run(cut_floor=0.01)
        self.assertEqual(cuts_low_floor, [6])
        cuts_no_revert, _ = run(cut_floor=0.01, revert_fraction=0)
        self.assertEqual(cuts_no_revert, [])

    def test_transition_detector_does_not_flag_a_sustained_burst_as_a_cut(self) -> None:
        # Regression: a sustained run of large, poorly-aligned steps (e.g. a
        # whip pan or any other extreme-but-real motion) must not be
        # reported as a hard cut. Comparing each neighbor only to the
        # pre-spike baseline (the old design) flags every frame in a run
        # like this, since each one clears that baseline on its own; only
        # comparing each neighbor to the spike's *own* size - unchanged
        # here, since nothing settles back down - correctly rejects it.
        values = [50, 51, 52, 220, 40, 230, 30, 210, 60, 55, 56, 57]
        frames = [bytes([v] * (32 * 18 * 3)) for v in values]
        process = MagicMock(stdout=io.BytesIO(b"".join(frames)), returncode=0)
        process.wait.return_value = 0
        with patch.object(self.ffrife.subprocess, "Popen", return_value=process):
            cuts, transitions = self.ffrife.detect_transitions("frames", source_fps=24)
        self.assertEqual(cuts, [])

    def test_scene_cut_replacement_maps_arbitrary_target_rate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming, outgoing = root / "in", root / "out"
            incoming.mkdir(); outgoing.mkdir()
            for index in range(1, 4):
                (incoming / f"{index:08d}.png").write_text(f"source-{index}")
            for index in range(1, 6):
                (outgoing / f"{index:08d}.png").write_text(f"rife-{index}")
            replaced = self.ffrife.suppress_scene_cut_interpolation(
                incoming, outgoing, input_count=3, target_count=5, cuts=[1]
            )
            self.assertEqual(replaced, 1)
            # cut=1 is the zero-based index of the shot's first frame, so the
            # replacement must come from file 2 (source-2), not file 1.
            self.assertEqual((outgoing / "00000002.png").read_text(), "source-2")
            self.assertEqual((outgoing / "00000003.png").read_text(), "rife-3")

    def test_scene_detection_cli_defaults_and_overrides(self) -> None:
        parser = self.ffrife.build_parser()
        default = parser.parse_args(["run", "in", "-o", "out"])
        disabled = parser.parse_args(["run", "in", "-o", "out", "--no-scene-detection"])
        self.assertIsNone(default.scene_detection)
        self.assertEqual(disabled.scene_detection, "false")
        config = dict(self.ffrife.DEFAULT_CONFIG)
        self.ffrife.apply_run_overrides(disabled, config)
        self.assertEqual(config["scene_detection"], "false")

    def test_gradual_transition_detector_finds_aligned_elevated_changes(self) -> None:
        # 12 tiny RGB frames: still, then a linear fade. Mock rawvideo keeps
        # this unit test independent of an ffmpeg installation.
        frames = [bytes([20] * (32 * 18 * 3)) for _ in range(5)]
        frames += [bytes([value] * (32 * 18 * 3)) for value in (30, 40, 50, 60, 70, 80, 90)]
        process = MagicMock(stdout=io.BytesIO(b"".join(frames)), returncode=0)
        process.wait.return_value = 0
        with patch.object(self.ffrife.subprocess, "Popen", return_value=process):
            cuts, transitions = self.ffrife.detect_transitions(
                "frames", source_fps=10, min_duration=0.3, sensitivity=1.2, alignment=0.8
            )
        self.assertEqual(transitions, [(5, 11)])
        self.assertEqual(cuts, [])

    def test_gradual_transition_detector_protects_quick_dissolves(self) -> None:
        # Regression: a fast, aligned ramp shorter than transition_min_duration
        # (0.25s == 6 frames at 24fps here) used to be discarded outright by a
        # minimum-run-length gate, leaving quick dissolves unprotected. The
        # gate is gone - min_duration only sizes the baseline lookback now -
        # so this 4-frame ramp must still be reported.
        frames = [bytes([20] * (32 * 18 * 3)) for _ in range(6)]
        frames += [bytes([value] * (32 * 18 * 3)) for value in (30, 50, 70, 90)]
        frames += [bytes([90] * (32 * 18 * 3)) for _ in range(3)]
        process = MagicMock(stdout=io.BytesIO(b"".join(frames)), returncode=0)
        process.wait.return_value = 0
        with patch.object(self.ffrife.subprocess, "Popen", return_value=process):
            cuts, transitions = self.ffrife.detect_transitions(
                "frames", source_fps=24, min_duration=0.25, sensitivity=1.2, alignment=0.8
            )
        self.assertNotEqual(transitions, [])

    def test_scene_cut_replacement_uses_the_post_cut_frame(self) -> None:
        # Regression: the replacement source must be the shot that begins at
        # `cut` (zero-based), not the frame immediately before it - copying
        # the wrong side silently extends the outgoing shot instead of
        # cleanly starting the incoming one.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming, outgoing = root / "in", root / "out"
            incoming.mkdir(); outgoing.mkdir()
            (incoming / "00000001.png").write_text("old-shot")
            (incoming / "00000002.png").write_text("new-shot")
            (outgoing / "00000002.png").write_text("rife-hybrid")
            self.ffrife.suppress_scene_cut_interpolation(
                incoming, outgoing, input_count=2, target_count=3, cuts=[1]
            )
            self.assertEqual((outgoing / "00000002.png").read_text(), "new-shot")

    def test_explicit_transition_ranges_are_seconds(self) -> None:
        self.assertEqual(self.ffrife.parse_transition_ranges("1.0:1.5, 3:4", 30, 200),
                         [(30, 45), (90, 120)])
        with self.assertRaisesRegex(ValueError, "START < END"):
            self.ffrife.parse_transition_ranges("2:1", 30, 200)

    def test_batch_collects_folder_glob_and_list_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.mp4").write_bytes(b"")
            (root / "b.mkv").write_bytes(b"")
            (root / "ignore.txt").write_text("no")
            listing = root / "inputs.txt"
            listing.write_text("a.mp4\n# comment\nb.mkv\n")
            found = self.ffrife.collect_batch_inputs([str(root)], [str(root / "*.mp4")], [str(listing)])
            self.assertEqual([p.name for p in found], ["a.mp4", "b.mkv"])

    def test_batch_output_template_preserves_extension(self) -> None:
        result = self.ffrife.batch_output_path(Path("clip.mov"), "done", "{stem}_smooth{suffix}")
        self.assertEqual(result, Path("done/clip_smooth.mov"))


class FfrifeCmdBenchmarkSampleTrimTest(unittest.TestCase):
    """Regression coverage for a real bug hit while actually using this:
    passing a whole downloaded chapter (minutes long) as --sample multiplied
    every one of the crf sweep's ~15 encodes by its own full length instead
    of a few seconds, timing out. cmd_benchmark now trims a long --sample
    to a short slice first, the same way slverse's own sample-finder does
    for its cached content."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_long_sample_gets_trimmed_before_benchmarking(self) -> None:
        calls = []

        def fake_run(cmd, check=True, capture_output=False, timeout=None, text=False):
            calls.append(cmd)
            if cmd[0] == "ffprobe":
                return unittest.mock.Mock(stdout="391.144467\n")
            # the trim encode - just needs to produce a real (if tiny) file
            # so run_encoder_benchmark's own reference-encode step succeeds
            with open(cmd[-1], "wb") as f:
                f.write(b"\x00")
            return unittest.mock.Mock(stdout="")

        fake_benchmark_result = [{"hw": "cpu", "codec": "av1", "vcodec": "libsvtav1", "crf": "30", "ok": True, "seconds": 1.0, "size_bytes": 100, "ssim": 0.99, "error": None}]

        with patch.object(self.ffrife, "resolve_ffmpeg_binary", return_value="ffmpeg"), \
             patch.object(self.ffrife, "resolve_ffprobe_binary", return_value="ffprobe"), \
             patch.object(self.ffrife.subprocess, "run", fake_run), \
             patch.object(self.ffrife._jwkit_common, "run_encoder_benchmark", return_value=fake_benchmark_result) as run_bench:
            self.ffrife.cmd_benchmark(argparse.Namespace(sample="/fake/long_chapter.mp4", apply=False, quick=False), dict(self.ffrife.DEFAULT_CONFIG))

        # The sample path actually handed to run_encoder_benchmark must NOT
        # be the original long file - it should be the trimmed temp file.
        actual_sample = run_bench.call_args[0][1]
        self.assertNotEqual(actual_sample, "/fake/long_chapter.mp4")
        trim_cmd = next(c for c in calls if c[0] == "ffmpeg")
        self.assertIn("-t", trim_cmd)
        self.assertIn("8", trim_cmd)

    def test_short_sample_is_used_as_is(self) -> None:
        calls = []

        def fake_run(cmd, check=True, capture_output=False, timeout=None, text=False):
            calls.append(cmd)
            return unittest.mock.Mock(stdout="6.0\n")

        fake_benchmark_result = [{"hw": "cpu", "codec": "av1", "vcodec": "libsvtav1", "crf": "30", "ok": True, "seconds": 1.0, "size_bytes": 100, "ssim": 0.99, "error": None}]

        with patch.object(self.ffrife, "resolve_ffmpeg_binary", return_value="ffmpeg"), \
             patch.object(self.ffrife, "resolve_ffprobe_binary", return_value="ffprobe"), \
             patch.object(self.ffrife.subprocess, "run", fake_run), \
             patch.object(self.ffrife._jwkit_common, "run_encoder_benchmark", return_value=fake_benchmark_result) as run_bench:
            self.ffrife.cmd_benchmark(argparse.Namespace(sample="/fake/short_clip.mp4", apply=False, quick=False), dict(self.ffrife.DEFAULT_CONFIG))

        actual_sample = run_bench.call_args[0][1]
        self.assertEqual(actual_sample, "/fake/short_clip.mp4")  # used as-is, no trim encode was run
        self.assertFalse(any(c[0] == "ffmpeg" for c in calls))


class FfrifeResolveTargetFpsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_plain_literal(self) -> None:
        self.assertEqual(self.ffrife.resolve_target_fps("60", 24.0), 60.0)

    def test_multiplier_suffix(self) -> None:
        self.assertEqual(self.ffrife.resolve_target_fps("2x", 24.0), 48.0)
        self.assertEqual(self.ffrife.resolve_target_fps("2.5x", 24.0), 60.0)

    def test_percent_suffix(self) -> None:
        self.assertEqual(self.ffrife.resolve_target_fps("150%", 24.0), 36.0)

    def test_uppercase_x_suffix(self) -> None:
        self.assertEqual(self.ffrife.resolve_target_fps("2X", 24.0), 48.0)


class FfrifeInterpolateFpsResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_relative_fps_spec_probes_source_and_resolves_before_rife(self) -> None:
        config = {"rife_binary_path": "/fake/rife"}
        rife_calls = []

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"\x89PNG")

        def fake_run_rife(rife_path, in_frames, out_frames, target_count, model_path=None, slow_after=4.0):
            rife_calls.append(target_count)
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")

        with patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "run_rife", fake_run_rife), \
             patch.object(self.ffrife, "probe_source_fps", return_value=24.0), \
             patch.object(self.ffrife.subprocess, "run"):
            self.ffrife.interpolate("in.mp4", "out.mp4", config, fps="2x")

        # 1 input frame * (2x of 24 = 48fps) / 24fps source = target_count 2
        self.assertEqual(rife_calls, [2])


class FfrifeOldBinaryCapabilityProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_returns_true_when_binary_produces_expected_frame_count(self) -> None:
        def fake_run(cmd, check=False, capture_output=False, text=False, timeout=None):
            if cmd[0] == self.ffrife.FFMPEG_BIN:
                out_path = Path(cmd[-1])
                out_path.write_bytes(b"\x89PNG")
                return MagicMock(returncode=0)
            # the RIFE invocation itself - simulate 3 output frames written
            out_dir = Path(cmd[cmd.index("-o") + 1])
            for i in range(3):
                (out_dir / f"{i:08d}.png").write_bytes(b"\x89PNG")
            return MagicMock(returncode=0)

        with patch.object(self.ffrife.subprocess, "run", fake_run):
            self.assertTrue(self.ffrife.rife_supports_custom_frame_count("/fake/rife", "/fake/model"))

    def test_returns_false_on_nonzero_exit(self) -> None:
        def fake_run(cmd, check=False, capture_output=False, text=False, timeout=None):
            if cmd[0] == self.ffrife.FFMPEG_BIN:
                Path(cmd[-1]).write_bytes(b"\x89PNG")
                return MagicMock(returncode=0)
            return MagicMock(returncode=1, stdout="", stderr="only rife-v4 model support custom numframe and timestep")

        with patch.object(self.ffrife.subprocess, "run", fake_run):
            self.assertFalse(self.ffrife.rife_supports_custom_frame_count("/fake/rife", "/fake/model"))

    def test_returns_false_on_exception(self) -> None:
        with patch.object(self.ffrife.subprocess, "run", side_effect=OSError("boom")):
            self.assertFalse(self.ffrife.rife_supports_custom_frame_count("/fake/rife", "/fake/model"))


class FfrifeCmdSetupReinstallOfferTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_offers_reinstall_when_capability_probe_fails(self) -> None:
        config = {"rife_binary_path": "/fake/bin/old-release/rife-ncnn-vulkan", "rife_model": "rife-v4.6"}
        with patch.object(self.ffrife, "resolve_ffmpeg_binary", return_value="ffmpeg"), \
             patch.object(self.ffrife, "ffmpeg_has_filter", return_value=True), \
             patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "rife_supports_custom_frame_count", return_value=False), \
             patch.object(self.ffrife, "install_rife", return_value=None) as install_mock, \
             patch("builtins.input", return_value="y"):
            self.ffrife.cmd_setup(config)
        install_mock.assert_called_once()

    def test_skips_reinstall_when_declined(self) -> None:
        config = {"rife_binary_path": "/fake/bin/old-release/rife-ncnn-vulkan", "rife_model": "rife-v4.6"}
        with patch.object(self.ffrife, "resolve_ffmpeg_binary", return_value="ffmpeg"), \
             patch.object(self.ffrife, "ffmpeg_has_filter", return_value=True), \
             patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "rife_supports_custom_frame_count", return_value=False), \
             patch.object(self.ffrife, "install_rife") as install_mock, \
             patch("builtins.input", return_value="n"):
            self.ffrife.cmd_setup(config)
        install_mock.assert_not_called()

    def test_no_reinstall_offer_when_capability_probe_succeeds(self) -> None:
        config = {"rife_binary_path": "/fake/bin/rife-ncnn-vulkan", "rife_model": "rife-v4.6"}
        with patch.object(self.ffrife, "resolve_ffmpeg_binary", return_value="ffmpeg"), \
             patch.object(self.ffrife, "ffmpeg_has_filter", return_value=True), \
             patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "rife_supports_custom_frame_count", return_value=True), \
             patch.object(self.ffrife, "install_rife") as install_mock, \
             patch("builtins.input", side_effect=AssertionError("should not prompt")):
            self.ffrife.cmd_setup(config)
        install_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
