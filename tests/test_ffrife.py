from __future__ import annotations

import argparse
import io
import os
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

    def test_probe_source_fps_rejects_a_source_without_video_clearly(self) -> None:
        result = MagicMock(stdout='{"streams": []}')
        with patch.object(self.ffrife.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "No usable video frame rate.*no video stream"):
                self.ffrife.probe_source_fps("subtitle-only.mp4")

    def test_probe_source_fps_falls_back_to_average_rate(self) -> None:
        result = MagicMock(stdout='{"streams": [{"r_frame_rate": "0/0", "avg_frame_rate": "30000/1001"}]}')
        with patch.object(self.ffrife.subprocess, "run", return_value=result):
            self.assertAlmostEqual(self.ffrife.probe_source_fps("variable.mp4"), 30000 / 1001)

    def test_run_encoder_overrides_parse(self) -> None:
        args = self.ffrife.build_parser().parse_args([
            "run", "input.mp4", "-o", "output.mp4", "--encoder", "nvenc",
            "--codec", "hevc", "--crf", "24", "--preset", "fast",
        ])
        self.assertEqual((args.encoder, args.codec, args.crf, args.preset), ("nvenc", "hevc", "24", "fast"))

    def test_resumable_work_defaults_outside_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "synced" / "movie.mp4"
            with patch.object(self.ffrife.tempfile, "gettempdir", return_value=str(Path(td) / "local-temp")):
                work = self.ffrife._work_dir_for(output, "abc123", self.ffrife.DEFAULT_CONFIG)
            self.assertEqual(work, Path(td) / "local-temp" / "jwkit" / "ffrife" / "abc123")
            self.assertNotEqual(work.parent, output.parent)

    def test_resumable_work_dir_is_configurable_and_cli_overridable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            configured = Path(td) / "scratch"
            work = self.ffrife._work_dir_for("movie.mp4", "abc123", {"work_dir": str(configured)})
            self.assertEqual(work, configured / "abc123")
            args = self.ffrife.build_parser().parse_args([
                "run", "input.mp4", "-o", "output.mp4", "--work-dir", str(configured),
            ])
            config = dict(self.ffrife.DEFAULT_CONFIG)
            self.ffrife.apply_generic_config_overrides(args, config)
            self.assertEqual(config["work_dir"], str(configured))


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


class FfrifeTrimWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_window_parses_as_start_and_end(self) -> None:
        args = self.ffrife.build_parser().parse_args([
            "run", "input.mp4", "--window", "3.567:10.003",
        ])
        self.assertEqual(self.ffrife.resolve_processing_window(args), (3.567, 10.003))

    def test_window_requires_increasing_nonnegative_bounds(self) -> None:
        for value in ("not-a-window", "-1:2", "2:2", "3:2", "nan:8", "2:inf"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                with patch("sys.stderr", io.StringIO()):
                    self.ffrife.build_parser().parse_args(["run", "input.mp4", "--window", value])

    def test_window_cannot_be_combined_with_separate_bounds(self) -> None:
        for extra in (("--start", "1"), ("--end", "9")):
            with self.subTest(extra=extra):
                args = self.ffrife.build_parser().parse_args([
                    "run", "input.mp4", "--window", "2:8", *extra,
                ])
                with self.assertRaisesRegex(ValueError, "cannot be combined"):
                    self.ffrife.resolve_processing_window(args)

    def test_separate_bounds_still_work(self) -> None:
        args = self.ffrife.build_parser().parse_args([
            "run", "input.mp4", "--start", "2", "--end", "8",
        ])
        self.assertEqual(self.ffrife.resolve_processing_window(args), (2.0, 8.0))


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


class FfrifeTrimmedExtrasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_source_window_uses_duration_not_absolute_to(self) -> None:
        args = self.ffrife.source_window_args(179.446, 206.606)
        self.assertEqual(args[:2], ["-ss", "179.446"])
        self.assertEqual(args[2], "-t")
        self.assertAlmostEqual(float(args[3]), 27.16)
        self.assertNotIn("-to", args)

    def test_chapters_are_clipped_rebased_and_outside_rows_dropped(self) -> None:
        probe = MagicMock(stdout='''{"chapters":[
          {"start_time":"0", "end_time":"5", "tags":{"title":"Intro"}},
          {"start_time":"5", "end_time":"12", "tags":{"title":"Main"}},
          {"start_time":"12", "end_time":"20", "tags":{"title":"End"}}
        ]}''')
        with tempfile.TemporaryDirectory() as td, patch.object(self.ffrife.subprocess, "run", return_value=probe):
            path = self.ffrife.write_clipped_chapters("source.mkv", 3, 9, td)
            text = path.read_text()
        self.assertIn("START=0\nEND=2000\ntitle=Intro", text)
        self.assertIn("START=2000\nEND=6000\ntitle=Main", text)
        self.assertNotIn("title=End", text)

    def test_trimmed_stream_sidecar_rebases_and_bounds_extra_audio(self) -> None:
        extras = {"extra_audio_indices": [4], "subtitle_count": 0, "subtitle_indices": []}
        with tempfile.TemporaryDirectory() as td, patch.object(self.ffrife.subprocess, "run") as run:
            self.ffrife.prepare_clipped_stream_extras(
                "source.mkv", extras, 3, 9, td, want_subtitles=False, want_extra_audio=True,
            )
        cmd = run.call_args.args[0]
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-t") + 1], "6")
        self.assertIn("atrim=duration=6,asetpts=PTS-STARTPTS", cmd[cmd.index("-filter_complex") + 1])
        self.assertEqual(cmd[cmd.index("-map_chapters") + 1], "-1")

    def test_subtitle_cues_are_clipped_at_both_window_boundaries(self) -> None:
        source = """1\n00:00:01,000 --> 00:00:04,000\nIntro\n\n2\n00:00:06,000 --> 00:00:11,000\nMain\n"""
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "source.srt", Path(td) / "clipped.srt"
            src.write_text(source)
            self.assertTrue(self.ffrife.clip_srt_file(src, dst, 3, 9))
            result = dst.read_text()
        self.assertIn("00:00:00,000 --> 00:00:01,000", result)
        self.assertIn("00:00:03,000 --> 00:00:06,000", result)
        self.assertNotIn("00:00:08,000", result)


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
        self.assertEqual(cmd[cmd.index("-af") + 1], "asetpts=PTS-STARTPTS,atempo=0.5")
        self.assertNotIn("-c:a", cmd)  # -af and -c:a copy are mutually exclusive for the audio stream

    def test_trim_uses_duration_and_reencodes_zero_based_audio(self) -> None:
        config = {"rife_binary_path": "/fake/rife", "scene_detection": "false"}
        ffmpeg_calls = []
        subprocess_calls = []

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            ffmpeg_calls.append(cmd)
            if cmd and str(cmd[-1]).endswith("%08d.png"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"png")

        def fake_run_rife(_rife, _incoming, outgoing, target_count=None, **_kwargs):
            (Path(outgoing) / "00000001.png").write_bytes(b"png")

        def fake_subprocess_run(cmd, **_kwargs):
            subprocess_calls.append(cmd)
            if str(cmd[-1]).endswith("audio.m4a"):
                Path(cmd[-1]).write_bytes(b"audio")
            return MagicMock(returncode=0, stdout="")

        with patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "run_rife", fake_run_rife), \
             patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
             patch.object(self.ffrife.subprocess, "run", fake_subprocess_run):
            self.ffrife.interpolate("in.mp4", "out.mp4", config, start=179.446, end=206.606, fps=60)

        extract = ffmpeg_calls[0]
        self.assertIn("-t", extract)
        self.assertAlmostEqual(float(extract[extract.index("-t") + 1]), 27.16)
        self.assertNotIn("-to", extract)
        audio = next(c for c in subprocess_calls if str(c[-1]).endswith("audio.m4a"))
        self.assertIn("atrim=duration=27.16,asetpts=PTS-STARTPTS", audio)
        self.assertEqual(audio[audio.index("-map_chapters") + 1], "-1")
        merge = ffmpeg_calls[-1]
        self.assertEqual(merge[merge.index("-c:a") + 1], "copy")

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

    def test_workload_scale_lowers_the_effective_long_run_threshold(self) -> None:
        # A high-resolution clip (or one asking for a much higher target fps,
        # or slow-motion via --speed) can take as long to RIFE-process as a
        # much longer, plainer one - workload_scale rescales input_frame_count
        # against REFERENCE_PIXELS/REFERENCE_FPS_RATIO so auto profile
        # selection reflects that, not just a raw source frame count.
        config = dict(self.ffrife.DEFAULT_CONFIG)
        config["long_run_frames"] = "1000"
        small_frame_count = 400  # below threshold at reference resolution/fps-ratio
        reference_policy = self.ffrife.resolve_rife_policy(config, small_frame_count, workload_scale=1.0)
        self.assertEqual(reference_policy["resolved_rife_profile"], "performance")
        scaled_policy = self.ffrife.resolve_rife_policy(config, small_frame_count, workload_scale=4.0)
        self.assertEqual(scaled_policy["resolved_rife_profile"], "balanced")

    def test_workload_scale_shrinks_chunk_frames_proportionally(self) -> None:
        # A high-workload run (high resolution, a high --fps target, or
        # slow-motion --speed) should get smaller chunks too, not just an
        # earlier auto->balanced switch - otherwise each chunk does
        # proportionally more RIFE synthesis than the profile intended, and
        # an interruption loses more of it.
        config = dict(self.ffrife.DEFAULT_CONFIG)
        config["rife_profile"] = "balanced"
        baseline = self.ffrife.resolve_rife_policy(config, 10, workload_scale=1.0)
        self.assertEqual(baseline["chunk_frames"], "1200")
        scaled = self.ffrife.resolve_rife_policy(config, 10, workload_scale=4.0)
        self.assertEqual(scaled["chunk_frames"], "300")

    def test_workload_scale_leaves_performance_profile_unchunked(self) -> None:
        # performance's chunk_frames=0 means "no chunking at all" - a high
        # workload_scale must not turn that into chunking the profile never
        # asked for; the auto threshold (covered above) is what promotes a
        # high-workload run out of performance in the first place.
        config = dict(self.ffrife.DEFAULT_CONFIG)
        config["rife_profile"] = "performance"
        scaled = self.ffrife.resolve_rife_policy(config, 10, workload_scale=4.0)
        self.assertEqual(scaled["chunk_frames"], "0")

    def test_workload_scale_does_not_override_an_explicit_chunk_frames(self) -> None:
        # Matches every other profile-selected setting: an explicit value
        # always wins over the profile's own default, unscaled.
        config = dict(self.ffrife.DEFAULT_CONFIG)
        config["rife_profile"] = "balanced"
        config["chunk_frames"] = "500"
        scaled = self.ffrife.resolve_rife_policy(config, 10, workload_scale=4.0)
        self.assertEqual(scaled["chunk_frames"], "500")

    def test_workload_scale_of_zero_does_not_divide_by_zero(self) -> None:
        # Regression: a near-zero target frame count (e.g. a tiny clip at a
        # very low --fps) can make workload_scale compute to exactly 0 -
        # scaling chunk_frames by dividing by it must not crash.
        config = dict(self.ffrife.DEFAULT_CONFIG)
        config["rife_profile"] = "balanced"
        scaled = self.ffrife.resolve_rife_policy(config, 10, workload_scale=0.0)
        self.assertEqual(scaled["chunk_frames"], "1200")

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

    def test_render_rife_frames_reuses_complete_extraction_on_resume(self) -> None:
        config = {"rife_binary_path": "/fake/rife", "chunk_frames": "0",
                  "scene_detection": "false"}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming = root / "in"
            incoming.mkdir()
            for index in range(2):
                (incoming / f"{index:08d}.png").write_bytes(b"png")
            self.ffrife._write_json_atomic(root / "extract-complete.json", {"frame_count": 2})

            def fake_render(_binary, _input, output, target_count, **_kwargs):
                for index in range(target_count):
                    (Path(output) / f"{index:08d}.png").write_bytes(b"png")

            with patch.object(self.ffrife, "command_exists", return_value=True), \
                 patch.object(self.ffrife, "run_ffmpeg") as extract, \
                 patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
                 patch.object(self.ffrife, "probe_source_resolution", return_value=(1280, 720)), \
                 patch.object(self.ffrife, "run_rife", fake_render):
                self.ffrife.render_rife_frames("in.mp4", root, config, fps=60)

            extract.assert_not_called()

    def test_render_rife_frames_reextracts_incomplete_checkpoint(self) -> None:
        config = {"rife_binary_path": "/fake/rife", "chunk_frames": "0",
                  "scene_detection": "false"}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming = root / "in"
            incoming.mkdir()
            (incoming / "00000000.png").write_bytes(b"partial")
            self.ffrife._write_json_atomic(root / "extract-complete.json", {"frame_count": 2})

            def fake_extract(cmd, **_kwargs):
                output_dir = Path(cmd[-1]).parent
                for index in range(2):
                    (output_dir / f"{index:08d}.png").write_bytes(b"png")

            def fake_render(_binary, _input, output, target_count, **_kwargs):
                for index in range(target_count):
                    (Path(output) / f"{index:08d}.png").write_bytes(b"png")

            with patch.object(self.ffrife, "command_exists", return_value=True), \
                 patch.object(self.ffrife, "run_ffmpeg", side_effect=fake_extract) as extract, \
                 patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
                 patch.object(self.ffrife, "probe_source_resolution", return_value=(1280, 720)), \
                 patch.object(self.ffrife, "run_rife", fake_render):
                self.ffrife.render_rife_frames("in.mp4", root, config, fps=60)

            extract.assert_called_once()
            self.assertEqual(len(list(incoming.glob("*.png"))), 2)

    def test_render_rife_frames_scales_threshold_by_source_resolution(self) -> None:
        # render_rife_frames' chunked path probes the source's actual
        # resolution and turns it into resolve_rife_policy's workload_scale -
        # this pins that wiring, not resolve_rife_policy's own math (covered
        # above by test_workload_scale_lowers_the_effective_long_run_threshold).
        # fps=60 over a 30fps source matches REFERENCE_FPS_RATIO exactly, so
        # the fps/speed factor contributes 1.0 here and workload_scale reduces
        # to plain pixel_scale - the fps/speed contribution itself is pinned
        # separately by test_render_rife_frames_scales_threshold_by_speed.
        config = {"rife_binary_path": "/fake/rife", "chunk_frames": "auto", "cooldown_seconds": "auto",
                  "rife_threads": "auto", "scene_detection": "false"}
        captured = {}

        def fake_resolve_rife_policy(cfg, frame_count, workload_scale=1.0):
            captured["frame_count"] = frame_count
            captured["workload_scale"] = workload_scale
            return {**cfg, "resolved_rife_profile": "performance", "rife_threads": "auto",
                    "chunk_frames": "0", "cooldown_seconds": "0"}

        def fake_render_chunks(_rife_path, _in_frames, out_frames, _target_count, _model_path, _cfg, _state_path):
            Path(out_frames).mkdir(parents=True, exist_ok=True)
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"\x89PNG")

        with tempfile.TemporaryDirectory() as td, \
             patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
             patch.object(self.ffrife, "probe_source_resolution", return_value=(1280, 720)), \
             patch.object(self.ffrife, "resolve_rife_policy", fake_resolve_rife_policy), \
             patch.object(self.ffrife, "_render_rife_chunks", fake_render_chunks):
            self.ffrife.render_rife_frames("in.mp4", Path(td), config, fps=60)

        self.assertAlmostEqual(captured["workload_scale"], (1280 * 720) / self.ffrife.REFERENCE_PIXELS)

    def test_render_rife_frames_scales_threshold_by_speed(self) -> None:
        # Half-speed slow-motion doubles RIFE's target output frame count for
        # the same input/resolution - workload_scale must pick that up too,
        # not just resolution (test above) or a plain fps upscale ratio.
        config = {"rife_binary_path": "/fake/rife", "chunk_frames": "auto", "cooldown_seconds": "auto",
                  "rife_threads": "auto", "scene_detection": "false"}
        captured = {}

        def fake_resolve_rife_policy(cfg, frame_count, workload_scale=1.0):
            captured["workload_scale"] = workload_scale
            return {**cfg, "resolved_rife_profile": "performance", "rife_threads": "auto",
                    "chunk_frames": "0", "cooldown_seconds": "0"}

        def fake_render_chunks(_rife_path, _in_frames, out_frames, _target_count, _model_path, _cfg, _state_path):
            Path(out_frames).mkdir(parents=True, exist_ok=True)
            (Path(out_frames) / "00000001.png").write_bytes(b"\x89PNG")

        def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
            if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                (Path(cmd[-1]).parent / "00000001.png").write_bytes(b"\x89PNG")

        with tempfile.TemporaryDirectory() as td, \
             patch.object(self.ffrife, "command_exists", return_value=True), \
             patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
             patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
             patch.object(self.ffrife, "probe_source_resolution", return_value=(640, 360)), \
             patch.object(self.ffrife, "resolve_rife_policy", fake_resolve_rife_policy), \
             patch.object(self.ffrife, "_render_rife_chunks", fake_render_chunks):
            # fps=60 over a 30fps source is REFERENCE_FPS_RATIO's own 2.0x;
            # speed=0.5 doubles the target count again on top of that, so
            # workload_scale should come out to 2.0 (pixel_scale is 1.0 at
            # the reference resolution).
            self.ffrife.render_rife_frames("in.mp4", Path(td), config, fps=60, speed=0.5)

        self.assertAlmostEqual(captured["workload_scale"], 2.0)

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
            cuts, transitions, _ = self.ffrife.detect_transitions("frames", source_fps=24)
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

        cuts_default, _, _ = run()
        self.assertEqual(cuts_default, [])
        cuts_low_floor, _, _ = run(cut_floor=0.01)
        self.assertEqual(cuts_low_floor, [6])
        cuts_no_revert, _, _ = run(cut_floor=0.01, revert_fraction=0)
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
            cuts, transitions, _ = self.ffrife.detect_transitions("frames", source_fps=24)
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
            cuts, transitions, _ = self.ffrife.detect_transitions(
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
            cuts, transitions, _ = self.ffrife.detect_transitions(
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

    def test_batch_default_output_name_keeps_the_source_name_unsuffixed(self) -> None:
        # -O already separates outputs into their own directory, so the
        # default template shouldn't need a _rife suffix to avoid a
        # collision the way a bare single-file run does.
        parser = self.ffrife.build_parser()
        args = parser.parse_args(["batch", "in.mp4", "-O", "done"])
        self.assertEqual(args.output_name, "{name}")
        self.assertEqual(self.ffrife.batch_output_path(Path("clip.mov"), "done", args.output_name),
                         Path("done/clip.mov"))

    def test_run_output_flag_is_optional(self) -> None:
        args = self.ffrife.build_parser().parse_args(["run", "in.mp4"])
        self.assertIsNone(args.output)

    def test_default_output_path_for_a_local_source_sits_beside_it_with_rife_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "clip.mov"
            source.write_bytes(b"fake")
            self.assertEqual(self.ffrife.default_output_path(str(source)), Path(td) / "clip_rife.mov")

    def test_default_output_path_for_a_remote_source_uses_the_url_name_in_cwd(self) -> None:
        result = self.ffrife.default_output_path("https://example.com/videos/clip.mp4?token=abc123")
        self.assertEqual(result, Path("clip_rife.mp4"))


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


class FfrifePipelinePlannerTest(unittest.TestCase):
    """plan_pipeline picks the fastest extraction/encode pipeline whose peak
    temporary disk still fits the budget - see ffrife's own "Pipeline
    planning" block. The fast end of both axes is strictly better wherever
    it fits, so these assert that it is actually chosen when it fits, and
    only given up in the order that costs the least."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def plan(self, *, frames=1000, target=2000, avg=1_000_000, free=10 ** 12, chunk_frames=100, **config):
        return self.ffrife.plan_pipeline(
            dict({"pipeline_mode": "auto", "disk_budget_fraction": "0.70",
                  "extraction_mode": "auto", "stream_segment_chunks": "auto"}, **config),
            input_frame_count=frames, target_count=target, avg_bytes=avg,
            free_bytes=free, chunk_frames=chunk_frames)

    def test_small_job_on_a_big_disk_keeps_the_single_whole_clip_encode(self) -> None:
        # The point of the planner: a clip that fits should pay none of
        # streaming's per-segment startup cost or lookahead resets.
        plan = self.plan()
        self.assertEqual(plan.extraction, "full")
        self.assertFalse(plan.stream)

    def test_job_too_big_for_the_budget_streams_in_segments(self) -> None:
        plan = self.plan(free=4 * 10 ** 9)
        self.assertTrue(plan.stream)
        self.assertEqual(plan.extraction, "full")
        self.assertLess(plan.peak_bytes, plan.free_bytes)

    def test_segment_size_grows_with_available_disk(self) -> None:
        # Bigger segments mean fewer encoder restarts, so the planner should
        # spend spare disk on speed rather than bank it.
        tight = self.plan(free=4 * 10 ** 9)
        roomy = self.plan(free=8 * 10 ** 9)
        self.assertGreater(roomy.segment_chunks, tight.segment_chunks)

    def test_source_frames_dominating_the_budget_switches_to_windowed(self) -> None:
        # Source frames alone are a hard floor under full extraction, paid
        # before RIFE even starts - windowing is the only thing that bounds
        # them.
        plan = self.plan(free=2 * 10 ** 9)
        self.assertEqual(plan.extraction, "windowed")
        self.assertTrue(plan.stream)
        self.assertLess(plan.peak_bytes, plan.free_bytes)

    def test_peak_falls_as_the_pipeline_gets_more_bounded(self) -> None:
        fast = self.plan(pipeline_mode="fast")
        streamed = self.plan(free=4 * 10 ** 9)
        windowed = self.plan(free=2 * 10 ** 9)
        self.assertGreater(fast.peak_bytes, streamed.peak_bytes)
        self.assertGreater(streamed.peak_bytes, windowed.peak_bytes)

    def test_fast_mode_never_bounds_even_on_a_tiny_disk(self) -> None:
        plan = self.plan(pipeline_mode="fast", free=10 ** 8)
        self.assertFalse(plan.stream)
        self.assertEqual(plan.extraction, "full")

    def test_compact_mode_bounds_even_on_a_huge_disk(self) -> None:
        plan = self.plan(pipeline_mode="compact")
        self.assertTrue(plan.stream)

    def test_extraction_mode_full_never_windows(self) -> None:
        plan = self.plan(free=2 * 10 ** 9, extraction_mode="full")
        self.assertEqual(plan.extraction, "full")

    def test_extraction_mode_windowed_wins_over_a_job_that_would_fit(self) -> None:
        plan = self.plan(extraction_mode="windowed")
        self.assertEqual(plan.extraction, "windowed")
        self.assertTrue(plan.stream)

    def test_explicit_segment_chunks_pins_the_planner_choice(self) -> None:
        plan = self.plan(free=4 * 10 ** 9, stream_segment_chunks="3")
        self.assertEqual(plan.segment_chunks, 3)

    def test_chunking_is_forced_on_when_bounding_needs_it(self) -> None:
        # An unchunked profile (chunk_frames=0) is one chunk covering the
        # whole clip, so nothing can be encoded and freed early.
        plan = self.plan(free=2 * 10 ** 9, chunk_frames=0)
        self.assertGreaterEqual(plan.chunk_frames, 2)
        self.assertGreater(plan.chunk_count, 1)

    def test_rejects_unknown_modes(self) -> None:
        with self.assertRaises(ValueError):
            self.plan(pipeline_mode="turbo")
        with self.assertRaises(ValueError):
            self.plan(extraction_mode="sideways")


class FfrifeFrameProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_full_provider_materializes_the_requested_slice(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "in"; src.mkdir()
            for i in range(1, 11):
                (src / f"{i:08d}.png").write_bytes(f"frame{i}".encode())
            chunk = root / "chunk"; chunk.mkdir()
            provider = self.ffrife.FullFrameProvider(src)
            self.assertEqual(provider.count, 10)
            frames_dir, offset = provider.materialize(3, 6, chunk)
            self.assertEqual((frames_dir, offset), (src, 0))
            self.assertEqual([p.name for p in sorted(chunk.glob("*.png"))],
                             ["00000001.png", "00000002.png", "00000003.png"])
            self.assertEqual((chunk / "00000001.png").read_bytes(), b"frame4")

    def test_windowed_provider_rejects_a_short_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chunk = root / "chunk"; chunk.mkdir()
            provider = self.ffrife.WindowedFrameProvider("src.mp4", 100, 30.0)
            with patch.object(self.ffrife, "run_ffmpeg", lambda *a, **k: None), \
                 patch.object(self.ffrife, "passthrough_fps_args", lambda: []):
                with self.assertRaises(self.ffrife.WindowedExtractionError):
                    provider.materialize(0, 5, chunk)  # run_ffmpeg wrote nothing

    def test_windowed_provider_rejects_a_seam_that_does_not_line_up(self) -> None:
        # _chunk_ranges overlaps one source frame between neighbours, so a
        # chunk's first frame must be byte-identical to the previous
        # chunk's last. That overlap is what makes a misaligned seek
        # detectable rather than a silent one-frame shift in the output.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            provider = self.ffrife.WindowedFrameProvider("src.mp4", 100, 30.0)
            written = {}

            def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
                target = Path(cmd[-1]).parent
                for i in range(1, written["count"] + 1):
                    (target / f"{i:08d}.png").write_bytes(written["content"](i))

            with patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
                 patch.object(self.ffrife, "passthrough_fps_args", lambda: []):
                first = root / "c0"; first.mkdir()
                written.update(count=5, content=lambda i: f"global{i - 1}".encode())
                provider.materialize(0, 5, first)  # last frame is "global4"

                aligned = root / "c1"; aligned.mkdir()
                written.update(count=5, content=lambda i: f"global{i + 3}".encode())
                provider.materialize(4, 9, aligned)  # first frame is "global4" - continuous

                shifted = root / "c2"; shifted.mkdir()
                written.update(count=5, content=lambda i: f"global{i + 99}".encode())
                with self.assertRaises(self.ffrife.WindowedExtractionError):
                    provider.materialize(8, 13, shifted)

    def test_windowed_provider_seeks_half_a_frame_early_with_passthrough(self) -> None:
        # Both details are load-bearing: accurate seek keeps frames at or
        # after the seek time (so aim early), and without passthrough ffmpeg
        # conforms to a CFR grid starting at the seek point and duplicates a
        # frame to fill the gap, shifting the whole chunk by one.
        with tempfile.TemporaryDirectory() as td:
            chunk = Path(td) / "chunk"; chunk.mkdir()
            provider = self.ffrife.WindowedFrameProvider("src.mp4", 100, 30.0, window_start=2.0)
            seen = []

            def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
                seen.append(cmd)
                for i in range(1, 4):
                    (Path(cmd[-1]).parent / f"{i:08d}.png").write_bytes(b"x")

            with patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
                 patch.object(self.ffrife, "passthrough_fps_args", lambda: ["-fps_mode", "passthrough"]):
                provider.materialize(60, 63, chunk)
            cmd = seen[0]
            self.assertIn("-fps_mode", cmd)
            self.assertAlmostEqual(float(cmd[cmd.index("-ss") + 1]), 2.0 + 59.5 / 30.0, places=5)
            self.assertEqual(cmd[cmd.index("-frames:v") + 1], "3")

    def test_suppression_rebases_source_frames_for_a_windowed_chunk(self) -> None:
        # Under windowed extraction in_frames holds only this chunk's own
        # source frames, numbered from 1, so a cut's global source index has
        # to be rebased the same way the output index already is.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chunk_in = root / "in"; chunk_in.mkdir()
            # Local file N holds global zero-based frame N + 1 here
            # (source_offset=2), and the whole-clip convention names global
            # frame g's content "src{g+1}" - so local 1 is "src3".
            for local in range(1, 5):  # global zero-based 2..5
                (chunk_in / f"{local:08d}.png").write_bytes(f"src{local + 2}".encode())
            chunk_out = root / "out"; chunk_out.mkdir()
            for i in range(1, 5):
                (chunk_out / f"{i:08d}.png").write_bytes(b"interp")
            replaced = self.ffrife.suppress_scene_cut_interpolation_range(
                chunk_in, chunk_out, 5, 9, [2], range_start=2, range_end=6,
                index_offset=2, source_offset=2,
            )
            self.assertEqual(replaced, 1)
            self.assertEqual((chunk_out / "00000002.png").read_bytes(), b"src3")


class FfrifeDetectionInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_downscale_always_converts_to_rgb_first(self) -> None:
        # Without the explicit format=rgb24, ffmpeg scales a video source in
        # its native yuv420p (averaging already-subsampled chroma) while a
        # PNG sequence is scaled in full RGB - and detection then finds
        # different gradual transitions for the same clip depending only on
        # which input it read.
        cmd = self.ffrife._tiny_frame_stream(["-i", "src.mp4"], None, 32, 18)
        self.assertEqual(cmd[cmd.index("-vf") + 1], "format=rgb24,scale=32:18")

    def test_run_filter_chain_is_applied_before_the_downscale(self) -> None:
        cmd = self.ffrife._tiny_frame_stream(["-i", "src.mp4"], "crop=10:10:0:0", 32, 18)
        self.assertEqual(cmd[cmd.index("-vf") + 1], "crop=10:10:0:0,format=rgb24,scale=32:18")

    def test_frames_input_reads_the_extracted_sequence(self) -> None:
        args = self.ffrife.frames_input_args("/tmp/in", 24.0)
        self.assertEqual(args[:2], ["-framerate", "24"])
        self.assertTrue(args[-1].endswith("%08d.png"))


class FfrifeApplyRunOverridesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_previously_dropped_flags_now_apply_to_config(self) -> None:
        # Regression: --chunk-frames/--cooldown/--rife-gpu/--rife-threads/
        # --resume/--no-resume/--keep-work/--space-check/--segment-chunks
        # were all parsed by argparse but never merged into the effective
        # config anywhere, so they silently did nothing on a real run - see
        # apply_run_overrides.
        parser = self.ffrife.build_parser()
        args = parser.parse_args([
            "run", "in.mp4", "-o", "out.mp4",
            "--chunk-frames", "500", "--cooldown", "7", "--rife-gpu", "1",
            "--rife-threads", "1:2:2", "--no-resume", "--keep-work",
            "--no-space-check", "--segment-chunks", "3",
        ])
        config = dict(self.ffrife.DEFAULT_CONFIG)
        self.ffrife.apply_run_overrides(args, config)
        self.assertEqual(config["chunk_frames"], "500")
        self.assertEqual(config["cooldown_seconds"], "7")
        self.assertEqual(config["rife_gpu"], "1")
        self.assertEqual(config["rife_threads"], "1:2:2")
        self.assertEqual(config["resume"], "false")
        self.assertEqual(config["keep_work"], "true")
        self.assertEqual(config["space_check"], "false")
        self.assertEqual(config["stream_segment_chunks"], "3")


class FfrifeStreamingEncodeTest(unittest.TestCase):
    """Covers the "Streaming encode" mode of _render_rife_chunks - batching
    completed RIFE chunks into bounded encode segments instead of keeping
    every interpolated frame on disk until one final whole-clip encode - see
    docs/ffrife.md and the AGENTS.md-referenced discussion this came from."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ffrife = load_script_module("ffrife")

    def test_suppress_scene_cut_range_matches_whole_clip_content_with_offset(self) -> None:
        # 5 input frames -> 9 output frames is a 2x-ish ratio (scale=2.0),
        # so cut=2 (zero-based) replaces exactly output_zero_index=3 with
        # in_frames' post-cut frame (index 3, one-based). A chunk covering
        # global range [2, 6) with index_offset=2 should replace the SAME
        # source content, just at the chunk-local filename (3-2+1=2).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            in_frames = root / "in"; in_frames.mkdir()
            for i in range(1, 6):
                (in_frames / f"{i:08d}.png").write_bytes(f"src{i}".encode())

            whole_out = root / "whole"; whole_out.mkdir()
            for i in range(1, 10):
                (whole_out / f"{i:08d}.png").write_bytes(b"interp")
            whole_replaced = self.ffrife.suppress_scene_cut_interpolation(in_frames, whole_out, 5, 9, [2])
            self.assertEqual(whole_replaced, 1)
            self.assertEqual((whole_out / "00000004.png").read_bytes(), b"src3")

            chunk_out = root / "chunk"; chunk_out.mkdir()
            for i in range(1, 5):  # local frames covering global zero-indices 2..5
                (chunk_out / f"{i:08d}.png").write_bytes(b"interp")
            chunk_replaced = self.ffrife.suppress_scene_cut_interpolation_range(
                in_frames, chunk_out, 5, 9, [2], range_start=2, range_end=6, index_offset=2,
            )
            self.assertEqual(chunk_replaced, 1)
            self.assertEqual((chunk_out / "00000002.png").read_bytes(), b"src3")

    def test_suppress_scene_cut_range_ignores_cuts_outside_its_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            in_frames = root / "in"; in_frames.mkdir()
            for i in range(1, 6):
                (in_frames / f"{i:08d}.png").write_bytes(f"src{i}".encode())
            chunk_out = root / "chunk"; chunk_out.mkdir()
            for i in range(1, 3):
                (chunk_out / f"{i:08d}.png").write_bytes(b"interp")
            # Same cut=2 as above, but this chunk only covers global range
            # [6, 9) - well past output_zero_index=3 - so nothing replaces.
            replaced = self.ffrife.suppress_scene_cut_interpolation_range(
                in_frames, chunk_out, 5, 9, [2], range_start=6, range_end=9, index_offset=6,
            )
            self.assertEqual(replaced, 0)
            self.assertEqual((chunk_out / "00000001.png").read_bytes(), b"interp")

    def test_validate_media_file_checks_existence_size_and_decode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertFalse(self.ffrife._validate_media_file(root / "missing.mkv"))

            empty = root / "empty.mkv"; empty.write_bytes(b"")
            self.assertFalse(self.ffrife._validate_media_file(empty))

            good = root / "good.mkv"; good.write_bytes(b"data")
            with patch.object(self.ffrife.subprocess, "run", return_value=MagicMock(returncode=0)):
                self.assertTrue(self.ffrife._validate_media_file(good))

            bad = root / "bad.mkv"; bad.write_bytes(b"data")
            with patch.object(self.ffrife.subprocess, "run",
                              side_effect=self.ffrife.subprocess.CalledProcessError(1, ["ffmpeg"])):
                self.assertFalse(self.ffrife._validate_media_file(bad))

    def test_validate_timeout_scales_with_file_size(self) -> None:
        # A timeout reads as corruption to the caller, so a big-but-good
        # segment (or a whole-clip video.mkv) must never hit it just for
        # being slow to decode - that would discard reusable RIFE work on
        # exactly the long runs resume matters most for.
        with tempfile.TemporaryDirectory() as td:
            big = Path(td) / "big.mkv"
            big.write_bytes(b"x")
            os.truncate(big, 400_000_000)  # sparse: size without the bytes
            seen = {}

            def fake_run(cmd, **kwargs):
                seen.update(kwargs)
                return MagicMock(returncode=0)

            with patch.object(self.ffrife.subprocess, "run", fake_run):
                self.assertTrue(self.ffrife._validate_media_file(big))
            self.assertGreater(seen["timeout"], self.ffrife.VALIDATE_TIMEOUT_FLOOR)

            small = Path(td) / "small.mkv"
            small.write_bytes(b"x" * 10)
            with patch.object(self.ffrife.subprocess, "run", fake_run):
                self.assertTrue(self.ffrife._validate_media_file(small))
            self.assertEqual(seen["timeout"], self.ffrife.VALIDATE_TIMEOUT_FLOOR)

    def test_concat_single_segment_moves_it_into_place_with_no_ffmpeg_call(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seg = root / "seg.mkv"; seg.write_bytes(b"video")
            target = root / "out.mkv"
            with patch.object(self.ffrife, "run_ffmpeg", side_effect=AssertionError("should not run ffmpeg")):
                self.ffrife._concat_video_segments([seg], target)
            self.assertEqual(target.read_bytes(), b"video")
            self.assertFalse(seg.exists())

    def test_concat_multiple_segments_uses_ffmpeg_concat_demuxer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seg1, seg2 = root / "s1.mkv", root / "s2.mkv"
            seg1.write_bytes(b"a"); seg2.write_bytes(b"b")
            target = root / "out.mkv"
            calls = []

            def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
                calls.append(cmd)
                Path(cmd[-1]).write_bytes(b"joined")

            with patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg):
                self.ffrife._concat_video_segments([seg1, seg2], target)
            self.assertEqual(len(calls), 1)
            self.assertIn("concat", calls[0])
            self.assertIn("-c", calls[0])
            self.assertTrue(target.exists())
            self.assertFalse(seg1.exists())
            self.assertFalse(seg2.exists())

    def test_finalize_primary_target_renames_when_containers_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "encoded.mkv"; src.write_bytes(b"data")
            dest = root / "out.mkv"
            with patch.object(self.ffrife.subprocess, "run", side_effect=AssertionError("should not remux")):
                self.ffrife._finalize_primary_target(src, dest)
            self.assertEqual(dest.read_bytes(), b"data")
            self.assertFalse(src.exists())

    def test_finalize_primary_target_remuxes_when_containers_differ(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "encoded.mkv"; src.write_bytes(b"data")
            dest = root / "out.mp4"
            calls = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                Path(cmd[-1]).write_bytes(b"remuxed")
                return MagicMock(returncode=0)

            with patch.object(self.ffrife.subprocess, "run", fake_run):
                self.ffrife._finalize_primary_target(src, dest)
            self.assertEqual(len(calls), 1)
            self.assertIn("-c", calls[0])
            self.assertIn("copy", calls[0])
            self.assertTrue(dest.exists())
            self.assertFalse(src.exists())

    def test_streaming_mode_batches_chunks_into_segments_and_frees_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            in_frames = root / "in"; in_frames.mkdir()
            for i in range(12):
                (in_frames / f"{i:08d}.png").write_bytes(b"src")

            def fake_run_rife(_binary, _input, output, target_count, **_kwargs):
                for i in range(target_count):
                    (Path(output) / f"{i:08d}.png").write_bytes(b"interp")

            segment_calls = []

            def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
                segment_calls.append(cmd)
                flat_dir = Path(cmd[cmd.index("-i") + 1]).parent
                frame_count = len(list(flat_dir.glob("*.png")))
                Path(cmd[-1]).write_bytes(f"segment:{frame_count}".encode())

            config = {"chunk_frames": "4", "cooldown_seconds": "0", "rife_threads": "auto", "rife_gpu": "auto"}
            encode = {"segment_chunks": 2, "fps": 30, "output_vf": None, "encode_args": ["-c:v", "libsvtav1"]}
            state_path = root / "state.json"
            with patch.object(self.ffrife, "run_rife", fake_run_rife), \
                 patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg):
                segments = self.ffrife._render_rife_chunks(
                    "rife", in_frames, root / "out", 24, "model", config, state_path,
                    cuts=[], input_count=12, encode=encode,
                )

            self.assertEqual(len(segments), 2)  # 4 chunks / segment_chunks=2 -> 2 segments
            self.assertEqual(len(segment_calls), 2)
            self.assertIn("-c:v", segment_calls[0])
            # Every chunk's PNGs are freed once its segment is finalized -
            # nothing left under chunks/ after a clean run, unlike the
            # non-streaming default (which keeps them all until one final
            # whole-clip encode).
            self.assertEqual(list((state_path.parent / "chunks").glob("*/out/*.png")), [])
            state = self.ffrife.json.loads(state_path.read_text())
            self.assertEqual(len(state["completed_chunks"]), 4)
            self.assertEqual(len(state["segments"]), 2)

    def test_streaming_resume_reuses_valid_segments_and_rebuilds_only_the_invalid_one(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            in_frames = root / "in"; in_frames.mkdir()
            for i in range(8):
                (in_frames / f"{i:08d}.png").write_bytes(b"src")

            rife_calls = []

            def fake_run_rife(_binary, _input, output, target_count, **_kwargs):
                rife_calls.append(target_count)
                for i in range(target_count):
                    (Path(output) / f"{i:08d}.png").write_bytes(b"interp")

            def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
                flat_dir = Path(cmd[cmd.index("-i") + 1]).parent
                frame_count = len(list(flat_dir.glob("*.png")))
                Path(cmd[-1]).write_bytes(f"segment:{frame_count}".encode())

            config = {"chunk_frames": "4", "cooldown_seconds": "0", "rife_threads": "auto", "rife_gpu": "auto"}
            encode = {"segment_chunks": 1, "fps": 30, "output_vf": None, "encode_args": ["-c:v", "libsvtav1"]}
            state_path = root / "state.json"
            # Trust plain non-empty fake byte content as "valid" - this test
            # is about _render_rife_chunks' own resume/discard orchestration,
            # not _validate_media_file's real ffmpeg decode check (covered
            # separately above).
            fake_validate = lambda p: Path(p).exists() and Path(p).stat().st_size > 0

            with patch.object(self.ffrife, "run_rife", fake_run_rife), \
                 patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
                 patch.object(self.ffrife, "_validate_media_file", fake_validate):
                segments = self.ffrife._render_rife_chunks(
                    "rife", in_frames, root / "out", 16, "model", config, state_path,
                    cuts=[], input_count=8, encode=encode,
                )
            self.assertEqual(len(segments), 3)  # _chunk_ranges(8,4) -> 3 chunks, segment_chunks=1 -> 3 segments
            self.assertEqual(len(rife_calls), 3)

            # Simulate the LAST segment's file having been left corrupt/
            # truncated by an interruption mid-write.
            segments[-1].write_bytes(b"")

            with patch.object(self.ffrife, "run_rife", fake_run_rife), \
                 patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
                 patch.object(self.ffrife, "_validate_media_file", fake_validate):
                resumed = self.ffrife._render_rife_chunks(
                    "rife", in_frames, root / "out", 16, "model", config, state_path,
                    cuts=[], input_count=8, encode=encode,
                )
            self.assertEqual(len(resumed), 3)
            # Only the one chunk in the discarded segment needed rebuilding -
            # the other, still-valid segments' chunks were never touched again.
            self.assertEqual(len(rife_calls), 4)

    def test_interpolate_streams_multiple_segments_and_delivers_output(self) -> None:
        config = {"rife_binary_path": "/fake/rife", "chunk_frames": "3", "stream_segment_chunks": "1",
                  "cooldown_seconds": "0", "scene_detection": "false"}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "out.mkv"

            def fake_run_ffmpeg(cmd, duration=None, label="Encoding"):
                if cmd and str(cmd[-1]).endswith("%08d.png") and str(Path(cmd[-1]).parent).endswith("/in"):
                    for i in range(6):
                        (Path(cmd[-1]).parent / f"{i:08d}.png").write_bytes(b"\x89PNG")
                    return
                target = Path(cmd[-1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"video")

            def fake_run_rife(_binary, _input, output_dir, target_count, **_kwargs):
                for i in range(target_count):
                    (Path(output_dir) / f"{i:08d}.png").write_bytes(b"\x89PNG")

            with patch.object(self.ffrife, "command_exists", return_value=True), \
                 patch.object(self.ffrife, "run_ffmpeg", fake_run_ffmpeg), \
                 patch.object(self.ffrife, "run_rife", fake_run_rife), \
                 patch.object(self.ffrife, "probe_source_fps", return_value=30.0), \
                 patch.object(self.ffrife, "probe_source_resolution", return_value=(640, 360)), \
                 patch.object(self.ffrife.subprocess, "run", return_value=MagicMock(returncode=0, stdout="")):
                ok = self.ffrife.interpolate("in.mp4", output, config, fps=60)

            self.assertTrue(ok)
            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes(), b"video")


if __name__ == "__main__":
    unittest.main()
