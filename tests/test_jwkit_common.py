from __future__ import annotations

import unittest
from unittest import mock

from tests.support import load_script_module


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


if __name__ == "__main__":
    unittest.main()
