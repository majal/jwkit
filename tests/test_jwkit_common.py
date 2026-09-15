from __future__ import annotations

import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
from unittest import mock

from tests.support import load_script_module


class JwkitCommonTimeParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_accepts_seconds_minutes_and_hours(self) -> None:
        self.assertEqual(self.common.parse_time_seconds("126.693"), 126.693)
        self.assertEqual(self.common.parse_time_seconds("2:06.693"), 126.693)
        self.assertEqual(self.common.parse_time_seconds("1:02:06.693"), 3726.693)

    def test_rejects_invalid_clock_fields(self) -> None:
        for value in ("", "1:60", "1:2:60", "-1", "nan", "1:2:3:4"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.common.parse_time_seconds(value)

    def test_ranges_use_hyphen_for_clock_endpoints(self) -> None:
        self.assertEqual(self.common.parse_time_range("2:06.693-3:26.696"), (126.693, 206.696))
        self.assertEqual(self.common.parse_time_range("3.567:10.003"), (3.567, 10.003))


class JwkitCommonConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_defaults_when_no_config_file(self) -> None:
        with mock.patch("pathlib.Path.exists", return_value=False):
            config = self.common.load_jwkit_config()
        self.assertTrue(config["auto_update"])
        self.assertEqual(config["auto_update_interval_hours"], 24)

    def test_parses_auto_update_false(self) -> None:
        text = "auto_update = false\nauto_update_interval_hours = 12\n"
        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("pathlib.Path.read_text", return_value=text):
            config = self.common.load_jwkit_config()
        self.assertFalse(config["auto_update"])
        self.assertEqual(config["auto_update_interval_hours"], 12)

    def test_ignores_comments_and_blank_lines(self) -> None:
        text = "# a comment\n\nauto_update = true\n"
        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("pathlib.Path.read_text", return_value=text):
            config = self.common.load_jwkit_config()
        self.assertTrue(config["auto_update"])

    def test_color_output_defaults_to_auto(self) -> None:
        with mock.patch("pathlib.Path.exists", return_value=False):
            config = self.common.load_jwkit_config()
        self.assertEqual(config["color_output"], "auto")

    def test_color_output_roundtrips(self) -> None:
        text = "auto_update = true\ncolor_output = never\n"
        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("pathlib.Path.read_text", return_value=text):
            config = self.common.load_jwkit_config()
        self.assertEqual(config["color_output"], "never")


class JwkitCommonConfigCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def setUp(self) -> None:
        self.defaults = {"name": "default", "count": 2, "enabled": False, "items": []}
        self.config = dict(self.defaults)
        self.saved = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_file = Path(self.tmp.name) / "config.toml"

    def run_config(self, action, key=None, value=None, **kwargs):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = self.common.run_config_command(
                tool="demo", args=Namespace(action=action, key=key, value=value),
                config=self.config, defaults=self.defaults, config_file=self.config_file,
                save_config=lambda config: self.saved.append(dict(config)), **kwargs,
            )
        return status, stdout.getvalue(), stderr.getvalue()

    def test_path_is_machine_readable(self) -> None:
        status, stdout, _ = self.run_config("path")
        self.assertEqual(status, 0)
        self.assertEqual(stdout.strip(), str(self.config_file))

    def test_set_parses_default_type_and_persists(self) -> None:
        status, _, _ = self.run_config("set", "count", "7")
        self.assertEqual(status, 0)
        self.assertEqual(self.config["count"], 7)
        self.assertEqual(self.saved[-1]["count"], 7)

    def test_reset_restores_default_and_persists(self) -> None:
        self.config["name"] = "changed"
        status, _, _ = self.run_config("reset", "name")
        self.assertEqual(status, 0)
        self.assertEqual(self.config["name"], "default")

    def test_diff_only_prints_nondefault_values(self) -> None:
        self.config["enabled"] = True
        status, stdout, _ = self.run_config("diff")
        self.assertEqual(status, 0)
        self.assertEqual(stdout.strip(), "enabled = true")

    def test_unknown_key_is_rejected_without_saving(self) -> None:
        status, _, stderr = self.run_config("set", "removed_key", "x")
        self.assertEqual(status, 2)
        self.assertIn("unknown config key", stderr)
        self.assertFalse(self.saved)

    def test_check_combines_domain_and_environment_validation(self) -> None:
        status, stdout, _ = self.run_config(
            "check", validate=lambda key, value: "must be positive" if key == "count" and value < 1 else None,
            check_extra=lambda config: ["missing helper"] if config["name"] == "default" else [],
        )
        self.assertEqual(status, 2)
        self.assertIn("ERROR: missing helper", stdout)

    def test_edit_prefers_visual_and_opens_canonical_file(self) -> None:
        self.config_file.write_text("name = default\n")
        with mock.patch.object(self.common.os, "environ", {"VISUAL": "code --wait", "EDITOR": "vi"}), \
             mock.patch.object(self.common.subprocess, "call", return_value=0) as call:
            status, _, _ = self.run_config("edit")
        self.assertEqual(status, 0)
        call.assert_called_once_with(["code", "--wait", str(self.config_file)])


class JwkitCommonColorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_colorizer_wraps_when_enabled(self) -> None:
        c = self.common.Colorizer(True)
        self.assertEqual(c.green("hi"), "\033[32mhi\033[0m")
        self.assertEqual(c.red("bad"), "\033[31mbad\033[0m")

    def test_colorizer_passthrough_when_disabled(self) -> None:
        c = self.common.Colorizer(False)
        self.assertEqual(c.green("hi"), "hi")
        self.assertEqual(c.bold(42), "42")  # non-string input still returns a plain string

    def test_colorizer_header_is_bold_cyan(self) -> None:
        c = self.common.Colorizer(True)
        self.assertEqual(c.header("Encoding..."), "\033[1m\033[36mEncoding...\033[0m\033[0m")
        self.assertEqual(self.common.Colorizer(False).header("Encoding..."), "Encoding...")

    def test_cli_override_wins_over_everything(self) -> None:
        with mock.patch.object(self.common.os, "environ", {"NO_COLOR": "1"}):
            self.assertTrue(self.common.resolve_color_enabled({"color_output": "never"}, cli_override=True))
            self.assertFalse(self.common.resolve_color_enabled({"color_output": "always"}, cli_override=False))

    def test_explicit_config_setting_wins_over_auto_detection(self) -> None:
        with mock.patch.object(self.common.sys.stdout, "isatty", return_value=False):
            self.assertTrue(self.common.resolve_color_enabled({"color_output": "always"}))
        with mock.patch.object(self.common.sys.stdout, "isatty", return_value=True):
            self.assertFalse(self.common.resolve_color_enabled({"color_output": "never"}))

    def test_auto_respects_no_color_env(self) -> None:
        with mock.patch.object(self.common.os, "environ", {"NO_COLOR": "1"}), \
             mock.patch.object(self.common.sys.stdout, "isatty", return_value=True):
            self.assertFalse(self.common.resolve_color_enabled({"color_output": "auto"}))

    def test_auto_follows_tty_detection(self) -> None:
        with mock.patch.object(self.common.os, "environ", {}), \
             mock.patch.object(self.common.sys.stdout, "isatty", return_value=True):
            self.assertTrue(self.common.resolve_color_enabled({"color_output": "auto"}))
        with mock.patch.object(self.common.os, "environ", {}), \
             mock.patch.object(self.common.sys.stdout, "isatty", return_value=False):
            self.assertFalse(self.common.resolve_color_enabled({"color_output": "auto"}))


class JwkitCommonMaybeAutoUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_skipped_entirely_when_auto_update_disabled(self) -> None:
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": False, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common, "_read_last_checked") as read_last:
            self.common.maybe_auto_update("/fake/root")
        read_last.assert_not_called()

    def test_skipped_when_checked_recently(self) -> None:
        now = 1_000_000.0
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common.time, "time", return_value=now), \
             mock.patch.object(self.common, "_read_last_checked", return_value=now - 60), \
             mock.patch.object(self.common, "_write_last_checked") as write_last, \
             mock.patch.object(self.common, "_git_fast_forward_update") as git_update:
            self.common.maybe_auto_update("/fake/root")
        write_last.assert_not_called()
        git_update.assert_not_called()

    def test_checks_and_resets_timer_when_interval_elapsed(self) -> None:
        now = 1_000_000.0
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common.time, "time", return_value=now), \
             mock.patch.object(self.common, "_read_last_checked", return_value=0.0), \
             mock.patch.object(self.common, "_write_last_checked") as write_last, \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(self.common, "_git_fast_forward_update", return_value=None) as git_update:
            self.common.maybe_auto_update("/fake/root")
        write_last.assert_called_once_with(now)
        git_update.assert_called_once()

    def test_never_raises_even_if_git_update_blows_up(self) -> None:
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common, "_read_last_checked", return_value=0.0), \
             mock.patch.object(self.common, "_write_last_checked"), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(self.common, "_git_fast_forward_update", side_effect=RuntimeError("boom")):
            self.common.maybe_auto_update("/fake/root")  # must not raise

    def test_skipped_when_no_git_dir_present(self) -> None:
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common, "_read_last_checked", return_value=0.0), \
             mock.patch.object(self.common, "_write_last_checked"), \
             mock.patch("pathlib.Path.exists", return_value=False), \
             mock.patch.object(self.common, "_git_fast_forward_update") as git_update:
            self.common.maybe_auto_update("/fake/root")
        git_update.assert_not_called()


class JwkitCommonFormatEtaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_drops_zero_minutes(self) -> None:
        self.assertEqual(self.common.format_eta(40), "40s")
        self.assertEqual(self.common.format_eta(0), "0s")

    def test_includes_minutes_once_nonzero(self) -> None:
        self.assertEqual(self.common.format_eta(65), "1m 05s")
        self.assertEqual(self.common.format_eta(125.7), "2m 05s")


class JwkitCommonPresetTranslationTest(unittest.TestCase):
    """`video_preset`/`--preset` is written in x264/x265's named ladder, but
    libsvtav1 (the DEFAULT codec) only accepts a number 0-13 and rejects
    every name outright, and libaom-av1 has no -preset option at all. Only
    the literal "slow" used to be translated, so any other name was a hard
    ffmpeg failure on the default codec rather than a different speed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_every_ladder_name_becomes_a_number_for_svtav1(self) -> None:
        for name in self.common.PRESET_LADDER:
            args = self.common.preset_args("libsvtav1", name, notice=False)
            self.assertEqual(args[0], "-preset", f"{name} did not produce a -preset")
            self.assertTrue(0 <= int(args[1]) <= 13, f"{name} -> {args[1]}")

    def test_svtav1_preset_order_matches_the_named_ladder(self) -> None:
        # Slowest name must map to the smallest (slowest/best) number, and
        # the mapping must stay monotonic across the whole ladder.
        numbers = [int(self.common.preset_args("libsvtav1", name, notice=False)[1])
                   for name in self.common.PRESET_LADDER]
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(self.common.preset_args("libsvtav1", "slow", notice=False), ["-preset", "6"])

    def test_libaom_uses_cpu_used_not_preset(self) -> None:
        for name in self.common.PRESET_LADDER:
            args = self.common.preset_args("libaom-av1", name, notice=False)
            self.assertEqual(args[0], "-cpu-used")
            self.assertTrue(0 <= int(args[1]) <= 8, f"{name} -> {args[1]}")

    def test_named_ladder_passes_through_for_x264_x265_nvenc_qsv(self) -> None:
        for vcodec in ("libx264", "libx265", "h264_nvenc", "av1_qsv"):
            self.assertEqual(self.common.preset_args(vcodec, "medium", notice=False), ["-preset", "medium"])

    def test_numeric_preset_normalizes_to_a_name_for_name_only_encoders(self) -> None:
        # nvenc accepts p1-p7 and the named ladder but not a bare number,
        # so an AV1-scale numeric setting reaching a fallback encoder has to
        # come back as the nearest name rather than pass straight through.
        self.assertEqual(self.common.preset_args("h264_nvenc", "6", notice=False), ["-preset", "slow"])
        self.assertEqual(self.common.preset_args("libx264", "8", notice=False), ["-preset", "medium"])

    def test_numeric_preset_is_clamped_to_each_av1_encoder_scale(self) -> None:
        self.assertEqual(self.common.preset_args("libsvtav1", "99", notice=False), ["-preset", "13"])
        self.assertEqual(self.common.preset_args("libaom-av1", "99", notice=False), ["-cpu-used", "8"])

    def test_videotoolbox_has_no_speed_preset(self) -> None:
        self.assertEqual(self.common.preset_args("hevc_videotoolbox", "slow", notice=False), [])

    def test_unknown_name_is_dropped_for_av1_but_kept_for_x264(self) -> None:
        # A bad video_preset should cost a default-speed encode, not the
        # whole run - but x264/x265 have their own extra names, so those
        # still pass through and let the encoder be the judge.
        self.assertEqual(self.common.preset_args("libsvtav1", "bogus", notice=False), [])
        self.assertEqual(self.common.preset_args("libx264", "bogus", notice=False), ["-preset", "bogus"])

    def test_encode_args_carry_the_translated_preset(self) -> None:
        args = self.common._encode_args_for("cpu", "av1", "libsvtav1", False, "30", "medium")
        self.assertEqual(args[args.index("-preset") + 1], "8")
        self.assertNotIn("medium", args)


class JwkitCommonBenchmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def setUp(self) -> None:
        # Same isolation reasoning as JwkitCommonEncodeArgsTest-equivalent
        # tests elsewhere (see test_slverse.py's SlverseEncodeArgsTest) -
        # this module is a real `import _jwkit_common`, shared process-wide,
        # so its resolution caches need clearing between tests.
        self._orig_has_encoder = self.common.ffmpeg_has_encoder
        self.addCleanup(setattr, self.common, "ffmpeg_has_encoder", self._orig_has_encoder)

    def test_benchmark_candidates_cpu_prefers_svtav1_over_aom(self) -> None:
        self.common.ffmpeg_has_encoder = lambda ffmpeg_bin, name: name in {"libx264", "libx265", "libsvtav1", "libaom-av1"}
        combos = self.common.benchmark_candidates("ffmpeg")
        av1_combos = [c for c in combos if c[0] == "cpu" and c[1] == "av1"]
        self.assertEqual(av1_combos, [("cpu", "av1", "libsvtav1", False)])

    def test_benchmark_candidates_only_includes_available_hardware(self) -> None:
        self.common.ffmpeg_has_encoder = lambda ffmpeg_bin, name: name in {"libx264", "h264_videotoolbox"}
        combos = self.common.benchmark_candidates("ffmpeg")
        hw_used = {c[0] for c in combos}
        self.assertIn("videotoolbox", hw_used)
        self.assertNotIn("nvenc", hw_used)
        self.assertNotIn("qsv", hw_used)
        # videotoolbox listed only for h264 (its own hevc/av1 encoders were
        # made unavailable above), not blanket-included for every codec.
        vt_codecs = {c[1] for c in combos if c[0] == "videotoolbox"}
        self.assertEqual(vt_codecs, {"h264"})

    def test_measure_ssim_parses_all_score(self) -> None:
        fake_result = mock.Mock(stderr="n:1 ... [Parsed_ssim_0] SSIM Y:... All:0.987654 (19.05)")
        with mock.patch.object(self.common.subprocess, "run", return_value=fake_result):
            self.assertAlmostEqual(self.common.measure_ssim("ffmpeg", "a.mp4", "b.mp4"), 0.987654)

    def test_measure_ssim_returns_none_on_no_match(self) -> None:
        fake_result = mock.Mock(stderr="no ssim here")
        with mock.patch.object(self.common.subprocess, "run", return_value=fake_result):
            self.assertIsNone(self.common.measure_ssim("ffmpeg", "a.mp4", "b.mp4"))

    def test_measure_ssim_returns_none_on_exception(self) -> None:
        with mock.patch.object(self.common.subprocess, "run", side_effect=TimeoutError("stuck")):
            self.assertIsNone(self.common.measure_ssim("ffmpeg", "a.mp4", "b.mp4"))

    def test_run_encoder_benchmark_records_success_and_failure(self) -> None:
        candidates = [("cpu", "h264", "libx264", False), ("nvenc", "h264", "h264_nvenc", True)]
        calls = []

        def fake_run(cmd, check=True, capture_output=False, timeout=None):
            calls.append(cmd)
            if "h264_nvenc" in cmd:
                raise self.common.subprocess.CalledProcessError(1, cmd)
            # Reference encode or the libx264 candidate encode - touch the
            # output file (last arg) so size_bytes/measure_ssim have
            # something to look at.
            output = cmd[-1]
            with open(output, "wb") as f:
                f.write(b"fake video bytes")
            return mock.Mock(stderr="")

        with mock.patch.object(self.common.subprocess, "run", fake_run), \
             mock.patch.object(self.common, "measure_ssim", return_value=0.99):
            results = self.common.run_encoder_benchmark("ffmpeg", "sample.mp4", candidates=candidates)

        self.assertEqual(len(results), 2)
        ok_result = next(r for r in results if r["hw"] == "cpu")
        self.assertTrue(ok_result["ok"])
        self.assertEqual(ok_result["ssim"], 0.99)
        self.assertGreater(ok_result["size_bytes"], 0)
        failed_result = next(r for r in results if r["hw"] == "nvenc")
        self.assertFalse(failed_result["ok"])
        self.assertIsNotNone(failed_result["error"])
        self.assertIsNone(failed_result["seconds"])

    def test_recommend_prefers_smallest_above_ssim_floor(self) -> None:
        results = [
            {"hw": "cpu", "codec": "h264", "ok": True, "ssim": 0.999, "size_bytes": 5_000_000, "vcodec": "libx264", "seconds": 1, "error": None},
            {"hw": "cpu", "codec": "av1", "ok": True, "ssim": 0.985, "size_bytes": 2_000_000, "vcodec": "libsvtav1", "seconds": 2, "error": None},
            {"hw": "cpu", "codec": "hevc", "ok": True, "ssim": 0.960, "size_bytes": 500_000, "vcodec": "libx265", "seconds": 3, "error": None},  # smallest, but below the floor
        ]
        best = self.common.recommend_from_benchmark(results, ssim_floor=0.98)
        self.assertEqual(best["codec"], "av1")  # smallest among those clearing 0.98, not the absolute smallest

    def test_recommend_prefers_faster_option_on_a_near_tie(self) -> None:
        # Real-world case this fixes: a crf sweep landed hevc barely
        # (12%) smaller than av1 but 3x slower to encode - picking hevc
        # anyway (the old "absolute smallest wins" behavior) trades a lot
        # of encode time for a noise-level size difference.
        results = [
            {"hw": "cpu", "codec": "hevc", "crf": "26", "ok": True, "ssim": 0.9961, "size_bytes": 400_000, "vcodec": "libx265", "seconds": 4.5, "error": None},
            {"hw": "cpu", "codec": "av1", "crf": "30", "ok": True, "ssim": 0.9963, "size_bytes": 450_000, "vcodec": "libsvtav1", "seconds": 1.5, "error": None},
        ]
        best = self.common.recommend_from_benchmark(results, ssim_floor=0.98)
        self.assertEqual(best["codec"], "av1")

    def test_recommend_still_picks_the_smaller_one_outside_tolerance(self) -> None:
        results = [
            {"hw": "cpu", "codec": "hevc", "crf": "20", "ok": True, "ssim": 0.998, "size_bytes": 400_000, "vcodec": "libx265", "seconds": 5.0, "error": None},
            {"hw": "cpu", "codec": "av1", "crf": "18", "ok": True, "ssim": 0.999, "size_bytes": 800_000, "vcodec": "libsvtav1", "seconds": 1.0, "error": None},  # 2x bigger, well outside 15% tolerance
        ]
        best = self.common.recommend_from_benchmark(results, ssim_floor=0.98)
        self.assertEqual(best["codec"], "hevc")

    def test_recommend_falls_back_to_highest_ssim_when_none_clear_floor(self) -> None:
        results = [
            {"hw": "cpu", "codec": "h264", "ok": True, "ssim": 0.90, "size_bytes": 5_000_000, "vcodec": "libx264", "seconds": 1, "error": None},
            {"hw": "cpu", "codec": "av1", "ok": True, "ssim": 0.95, "size_bytes": 2_000_000, "vcodec": "libsvtav1", "seconds": 2, "error": None},
        ]
        best = self.common.recommend_from_benchmark(results, ssim_floor=0.98)
        self.assertEqual(best["codec"], "av1")

    def test_recommend_returns_none_when_nothing_worked(self) -> None:
        results = [{"hw": "nvenc", "codec": "h264", "ok": False, "ssim": None, "size_bytes": None, "vcodec": "h264_nvenc", "seconds": None, "error": "boom"}]
        self.assertIsNone(self.common.recommend_from_benchmark(results))

    def test_format_benchmark_table_sorts_by_size_and_lists_failures(self) -> None:
        results = [
            {"hw": "cpu", "codec": "h264", "crf": "20", "ok": True, "ssim": 0.99, "size_bytes": 5_000_000, "vcodec": "libx264", "seconds": 1.0, "error": None},
            {"hw": "cpu", "codec": "av1", "crf": "30", "ok": True, "ssim": 0.98, "size_bytes": 2_000_000, "vcodec": "libsvtav1", "seconds": 2.0, "error": None},
            {"hw": "nvenc", "codec": "h264", "crf": "20", "ok": False, "ssim": None, "size_bytes": None, "vcodec": "h264_nvenc", "seconds": None, "error": "No such device\nmore detail"},
        ]
        table = self.common.format_benchmark_table(results)
        lines = [line for line in table.splitlines() if line.strip()]
        av1_line = next(line for line in lines if "av1" in line)
        h264_ok_line = next(line for line in lines if "cpu" in line and "h264" in line)
        self.assertLess(lines.index(av1_line), lines.index(h264_ok_line))
        self.assertIn("2.00MB", av1_line)
        self.assertIn("0.9800", av1_line)
        self.assertIn("5.00MB", h264_ok_line)
        self.assertIn("0.9900", h264_ok_line)
        self.assertIn("unavailable", table)
        self.assertIn("No such device", table)
        self.assertNotIn("more detail", table)  # only the first line of a multi-line error is shown

    def test_run_encoder_benchmark_sweeps_multiple_crf_values(self) -> None:
        candidates = [("cpu", "av1", "libsvtav1", False)]
        calls = []

        def fake_run(cmd, check=True, capture_output=False, timeout=None):
            calls.append(cmd)
            output = cmd[-1]
            with open(output, "wb") as f:
                f.write(b"fake")
            return mock.Mock(stderr="")

        with mock.patch.object(self.common.subprocess, "run", fake_run), \
             mock.patch.object(self.common, "measure_ssim", return_value=0.98):
            results = self.common.run_encoder_benchmark(
                "ffmpeg", "sample.mp4", candidates=candidates, crf_map={"av1": ["24", "27", "30"]},
            )
        self.assertEqual(sorted(r["crf"] for r in results), ["24", "27", "30"])
        self.assertTrue(all(r["ok"] for r in results))

    def test_run_encoder_benchmark_accepts_single_crf_string_for_backward_compat(self) -> None:
        candidates = [("cpu", "h264", "libx264", False)]

        def fake_run(cmd, check=True, capture_output=False, timeout=None):
            with open(cmd[-1], "wb") as f:
                f.write(b"fake")
            return mock.Mock(stderr="")

        with mock.patch.object(self.common.subprocess, "run", fake_run), \
             mock.patch.object(self.common, "measure_ssim", return_value=0.99):
            results = self.common.run_encoder_benchmark(
                "ffmpeg", "sample.mp4", candidates=candidates, crf_map={"h264": "20"},
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["crf"], "20")


class JwkitCommonParseSizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_bare_number_is_bytes(self) -> None:
        self.assertEqual(self.common.parse_size("100"), 100)

    def test_decimal_si_suffixes(self) -> None:
        self.assertEqual(self.common.parse_size("1K"), 1000)
        self.assertEqual(self.common.parse_size("1M"), 1000 ** 2)
        self.assertEqual(self.common.parse_size("1G"), 1000 ** 3)
        self.assertEqual(self.common.parse_size("1T"), 1000 ** 4)

    def test_binary_iec_suffixes(self) -> None:
        self.assertEqual(self.common.parse_size("1Ki"), 1024)
        self.assertEqual(self.common.parse_size("1Mi"), 1024 ** 2)
        self.assertEqual(self.common.parse_size("1Gi"), 1024 ** 3)

    def test_case_insensitive(self) -> None:
        self.assertEqual(self.common.parse_size("1g"), 1000 ** 3)
        self.assertEqual(self.common.parse_size("1gi"), 1024 ** 3)
        self.assertEqual(self.common.parse_size("1GI"), 1024 ** 3)

    def test_fractional_values(self) -> None:
        self.assertEqual(self.common.parse_size("2.5G"), int(2.5 * 1000 ** 3))

    def test_rejects_unknown_unit(self) -> None:
        with self.assertRaises(ValueError):
            self.common.parse_size("5X")

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(ValueError):
            self.common.parse_size("not-a-size")


class JwkitCommonOverwritePolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def _existing_file(self, tmp_path):
        from pathlib import Path
        p = Path(tmp_path) / "out.mp4"
        p.write_bytes(b"x")
        return p

    def test_nonexistent_path_returns_unchanged(self) -> None:
        with mock.patch("pathlib.Path.exists", return_value=False):
            result = self.common.resolve_output_conflict("/does/not/exist.mp4", {"on_output_exists": "overwrite"})
        self.assertEqual(str(result), "/does/not/exist.mp4")

    def test_overwrite_policy_returns_same_path(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            result = self.common.resolve_output_conflict(p, {"on_output_exists": "overwrite"})
        self.assertEqual(result, p)

    def test_rename_policy_returns_numbered_sibling(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            result = self.common.resolve_output_conflict(p, {"on_output_exists": "rename"})
        self.assertEqual(result.name, "out (1).mp4")
        self.assertFalse(result.exists())

    def test_rename_policy_skips_taken_numbers(self) -> None:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            (Path(td) / "out (1).mp4").write_bytes(b"x")
            result = self.common.resolve_output_conflict(p, {"on_output_exists": "rename"})
        self.assertEqual(result.name, "out (2).mp4")

    def test_fail_policy_returns_none(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            result = self.common.resolve_output_conflict(p, {"on_output_exists": "fail"})
        self.assertIsNone(result)

    def test_trash_policy_moves_existing_and_returns_same_path(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            with mock.patch.object(self.common, "_move_to_trash") as trash_mock:
                result = self.common.resolve_output_conflict(p, {"on_output_exists": "trash"})
        trash_mock.assert_called_once_with(p)
        self.assertEqual(result, p)

    def test_macos_trash_passes_absolute_path_as_argv(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home:
            p = self._existing_file(td)
            relative = p.relative_to(Path(td))
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch.object(self.common.Path, "home", return_value=Path(home)), \
                 mock.patch.object(self.common.subprocess, "run", return_value=completed) as run_mock, \
                 mock.patch.object(self.common.Path, "resolve", return_value=p):
                self.common._move_to_trash_macos(relative)
        command = run_mock.call_args.args[0]
        self.assertEqual(command[-1], str(p))
        self.assertIn("item 1 of argv", command[2])

    def test_macos_trash_falls_back_when_finder_is_unavailable(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home:
            p = self._existing_file(td)
            failed = mock.Mock(returncode=1, stdout="", stderr="Not authorized")
            with mock.patch.object(self.common.subprocess, "run", return_value=failed), \
                 mock.patch.object(self.common.Path, "home", return_value=Path(home)):
                self.common._move_to_trash_macos(p)
            self.assertFalse(p.exists())
            self.assertTrue((Path(home) / ".Trash" / p.name).exists())

    def test_linux_trash_falls_back_when_gio_is_unusable(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home:
            p = self._existing_file(td)
            failed = mock.Mock(returncode=1, stdout="", stderr="No D-Bus session")
            with mock.patch.object(self.common.shutil, "which", return_value="/usr/bin/gio"), \
                 mock.patch.object(self.common.subprocess, "run", return_value=failed), \
                 mock.patch.object(self.common.Path, "home", return_value=Path(home)):
                self.common._move_to_trash_linux(p)
            self.assertFalse(p.exists())
            self.assertTrue((Path(home) / ".local/share/Trash/files" / p.name).exists())

    def test_unrecognized_policy_raises(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            with self.assertRaises(ValueError):
                self.common.resolve_output_conflict(p, {"on_output_exists": "bogus"})

    def test_ask_without_tty_falls_back_to_unattended_policy(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            with mock.patch.object(self.common.sys.stdin, "isatty", return_value=False):
                result = self.common.resolve_output_conflict(p, {"on_output_exists": "ask", "on_output_exists_unattended": "overwrite"})
        self.assertEqual(result, p)

    def test_ask_with_tty_and_yes_answer_overwrites(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            with mock.patch.object(self.common.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(self.common, "_prompt_yes_no_with_timeout", return_value=True):
                result = self.common.resolve_output_conflict(p, {"on_output_exists": "ask"})
        self.assertEqual(result, p)

    def test_ask_with_tty_and_no_answer_falls_back_to_unattended(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            with mock.patch.object(self.common.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(self.common, "_prompt_yes_no_with_timeout", return_value=False):
                result = self.common.resolve_output_conflict(p, {"on_output_exists": "ask", "on_output_exists_unattended": "rename"})
        self.assertEqual(result.name, "out (1).mp4")

    def test_ask_timeout_falls_back_to_unattended(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = self._existing_file(td)
            with mock.patch.object(self.common.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(self.common, "_prompt_yes_no_with_timeout", return_value=None):
                result = self.common.resolve_output_conflict(p, {"on_output_exists": "ask", "on_output_exists_unattended": "fail"})
        self.assertIsNone(result)

    def test_numbered_alternative_helper(self) -> None:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "clip.mp4"
            p.write_bytes(b"x")
            result = self.common._numbered_alternative(p)
        self.assertEqual(result.name, "clip (1).mp4")

    def test_datetime_tagged_helper_preserves_stem_and_suffix(self) -> None:
        from pathlib import Path
        result = self.common._datetime_tagged(Path("/tmp/clip.mp4"))
        self.assertTrue(result.name.startswith("clip (trashed "))
        self.assertTrue(result.name.endswith(").mp4"))


if __name__ == "__main__":
    unittest.main()
