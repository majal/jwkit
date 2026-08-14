from __future__ import annotations

import argparse
import io
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tests.support import load_script_module


class SlverseTimeParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_parse_hms(self) -> None:
        self.assertAlmostEqual(self.slverse.parse_hms("00:00:12.212"), 12.212)
        self.assertAlmostEqual(self.slverse.parse_hms("00:01:07.267"), 67.267)
        self.assertAlmostEqual(self.slverse.parse_hms("01:00:00.000"), 3600.0)

    def test_markers_to_verse_times(self) -> None:
        markers = [
            {"verseNumber": 1, "startTime": "00:00:12.212", "duration": "00:00:25.592", "label": "Revelation 1:1"},
            {"verseNumber": 2, "startTime": "00:00:37.804", "duration": "00:00:07.707", "label": "Revelation 1:2"},
        ]
        times = self.slverse.markers_to_verse_times(markers)
        self.assertAlmostEqual(times[1]["start"], 12.212)
        self.assertAlmostEqual(times[1]["end"], 37.804)
        self.assertAlmostEqual(times[2]["start"], 37.804)

    def test_markers_to_verse_times_skips_malformed_entries(self) -> None:
        times = self.slverse.markers_to_verse_times([{"verseNumber": "not-a-number"}, None])
        self.assertEqual(times, {})

    def test_markers_to_verse_times_parses_end_transition(self) -> None:
        # endTransitionDuration is 0 mid-paragraph and nonzero on a
        # paragraph's/chapter's last verse - the fade-out + copyright
        # endscreen tail (see resolve_verse_window / DEFAULT_CONFIG
        # trim_end_transition).
        markers = [
            {"verseNumber": 10, "startTime": "00:02:13.633", "duration": "00:00:15.782", "endTransitionDuration": "00:00:00.000"},
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:06.940"},
        ]
        times = self.slverse.markers_to_verse_times(markers)
        self.assertAlmostEqual(times[10]["end_transition"], 0.0)
        self.assertAlmostEqual(times[11]["end_transition"], 6.940)

    def test_markers_to_verse_times_defaults_missing_end_transition_to_zero(self) -> None:
        times = self.slverse.markers_to_verse_times([{"verseNumber": 1, "startTime": "00:00:00.000", "duration": "00:00:05.000"}])
        self.assertAlmostEqual(times[1]["end_transition"], 0.0)


class SlverseClampOffsetWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_in_bounds_offsets_pass_through_unclamped(self) -> None:
        with mock.patch("builtins.print") as p:
            result = self.slverse.clamp_offset_window(100.0, 112.0, 3.567, -1.997)
        self.assertAlmostEqual(result[0], 103.567)
        self.assertAlmostEqual(result[1], 110.003)
        p.assert_not_called()

    def test_start_overshoot_past_natural_end_clamps(self) -> None:
        with mock.patch("builtins.print") as p:
            result = self.slverse.clamp_offset_window(100.0, 112.0, 20.0, 0.0)
        self.assertEqual(result, (100.0, 112.0))
        p.assert_called_once()

    def test_end_undershoot_before_natural_start_clamps(self) -> None:
        result = self.slverse.clamp_offset_window(100.0, 112.0, 0.0, -20.0)
        self.assertEqual(result, (100.0, 112.0))

    def test_start_never_goes_negative(self) -> None:
        result = self.slverse.clamp_offset_window(2.0, 14.0, -10.0, 0.0)
        self.assertEqual(result[0], 0.0)

    def test_combined_collapse_falls_back_to_natural_window(self) -> None:
        result = self.slverse.clamp_offset_window(100.0, 112.0, 8.0, -8.0)
        self.assertEqual(result, (100.0, 112.0))


class SlverseResolveVerseWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def config(self, **overrides):
        cfg = dict(self.slverse.DEFAULT_CONFIG)
        cfg.update(overrides)
        return cfg

    def _stub_index(self, markers) -> None:
        self.slverse.load_index = lambda lang: {
            "19_16": {
                "url": "http://example/vid.mp4",
                "checksum": "abc123",
                "markers": markers,
            }
        }

    def test_trims_trailing_end_transition_by_default(self) -> None:
        self._stub_index([
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:06.940", "label": "Psalm 16:11"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config())
        self.assertAlmostEqual(end, 149.415 + 33.800 - 6.940)
        self.assertEqual(source_labels, ["Psalm 16:11"])
        self.assertEqual(kept_segments, [(0.0, end - start)])

    def test_trim_end_transition_false_keeps_full_marker_duration(self) -> None:
        self._stub_index([
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:06.940", "label": "Psalm 16:11"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [11], self.config(trim_end_transition="false"),
        )
        self.assertAlmostEqual(end, 149.415 + 33.800)

    def test_keep_end_transition_override_beats_config_default(self) -> None:
        self._stub_index([
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:06.940", "label": "Psalm 16:11"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [11], self.config(), keep_end_transition=True,
        )
        self.assertAlmostEqual(end, 149.415 + 33.800)

    def test_offset_start_nudges_the_computed_start(self) -> None:
        self._stub_index([
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:11"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [11], self.config(), offset_start=5.302,
        )
        self.assertAlmostEqual(start, 149.415 + 5.302)
        self.assertAlmostEqual(end, 149.415 + 33.800)

    def test_offset_end_nudges_the_computed_end_negative_to_end_early(self) -> None:
        self._stub_index([
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:11"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [11], self.config(), offset_end=-3.0,
        )
        self.assertAlmostEqual(end, 149.415 + 33.800 - 3.0)

    def test_offset_start_never_goes_negative(self) -> None:
        self._stub_index([
            {"verseNumber": 1, "startTime": "00:00:02.000", "duration": "00:00:05.000", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:1"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [1], self.config(), offset_start=-10.0,
        )
        self.assertEqual(start, 0.0)

    def test_offsets_stack_with_end_transition_trim(self) -> None:
        self._stub_index([
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:06.940", "label": "Psalm 16:11"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [11], self.config(), offset_end=-1.0,
        )
        self.assertAlmostEqual(end, 149.415 + 33.800 - 6.940 - 1.0)

    def test_no_trim_when_end_transition_is_zero(self) -> None:
        self._stub_index([
            {"verseNumber": 10, "startTime": "00:02:13.633", "duration": "00:00:15.782", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:10"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window("ASL", 19, 16, [10], self.config())
        self.assertAlmostEqual(end, 133.633 + 15.782)

    def test_mid_transition_default_keeps_continuous_range(self) -> None:
        # A range spanning multiple paragraphs plays through a mid-range
        # transition untouched by default - only the LAST selected verse's
        # own trailing transition (trim_end_transition) is ever cut.
        self._stub_index([
            {"verseNumber": 8, "startTime": "00:01:00.000", "duration": "00:00:10.000", "endTransitionDuration": "00:00:02.000", "label": "Psalm 16:8"},
            {"verseNumber": 9, "startTime": "00:01:10.000", "duration": "00:00:08.000", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:9"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [8, 9], self.config(),
        )
        self.assertEqual(kept_segments, [(0.0, end - start)])

    def test_trim_mid_transitions_cuts_the_paragraph_boundary(self) -> None:
        self._stub_index([
            {"verseNumber": 8, "startTime": "00:01:00.000", "duration": "00:00:10.000", "endTransitionDuration": "00:00:02.000", "label": "Psalm 16:8"},
            {"verseNumber": 9, "startTime": "00:01:10.000", "duration": "00:00:08.000", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:9"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [8, 9], self.config(trim_mid_transitions="true"),
        )
        # verse 8 spans [0, 10) of the window, transition is its last 2s -> drop [8, 10)
        self.assertEqual(kept_segments, [(0.0, 8.0), (10.0, 18.0)])

    def test_trim_mid_transitions_cli_override(self) -> None:
        self._stub_index([
            {"verseNumber": 8, "startTime": "00:01:00.000", "duration": "00:00:10.000", "endTransitionDuration": "00:00:02.000", "label": "Psalm 16:8"},
            {"verseNumber": 9, "startTime": "00:01:10.000", "duration": "00:00:08.000", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:9"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [8, 9], self.config(), trim_mid_transitions=True,
        )
        self.assertEqual(kept_segments, [(0.0, 8.0), (10.0, 18.0)])

    def test_verse_markers_unwraps_api_shape(self) -> None:
        # GETPUBMEDIALINKS wraps the marker list: file['markers'] = {..., 'markers': [...]}
        file = {"markers": {"bibleBookNumber": 66, "markers": [{"verseNumber": 1}]}}
        self.assertEqual(self.slverse.verse_markers(file), [{"verseNumber": 1}])

    def test_verse_markers_handles_missing_field(self) -> None:
        self.assertEqual(self.slverse.verse_markers({}), [])


class SlverseLangListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_single_code_passthrough(self) -> None:
        config = {"languages": "ASL,FSL,BVL,INI,SPE"}
        self.assertEqual(self.slverse.get_lang_list(config, "fsl"), ["FSL"])

    def test_comma_list_splits_and_uppercases(self) -> None:
        config = {"languages": "ASL,FSL"}
        self.assertEqual(self.slverse.get_lang_list(config, "asl,bvl"), ["ASL", "BVL"])

    def test_all_uses_configured_languages(self) -> None:
        config = {"languages": "ASL,FSL,BVL,INI,SPE"}
        self.assertEqual(self.slverse.get_lang_list(config, "all"), ["ASL", "FSL", "BVL", "INI", "SPE"])

    def test_none_defaults_to_configured_languages(self) -> None:
        config = {"languages": "ASL,FSL"}
        self.assertEqual(self.slverse.get_lang_list(config), ["ASL", "FSL"])


class SlverseEncodeArgsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_default_cpu_matches_legacy_proven_settings(self) -> None:
        config = {"hardware_encoder": "cpu", "video_codec": "h264", "video_crf": "20", "video_preset": "slow"}
        args = self.slverse.build_encode_args(config)
        self.assertIn("libx264", args)
        self.assertIn("-crf", args)
        self.assertIn("20", args)
        self.assertIn("-preset", args)
        self.assertIn("slow", args)
        self.assertIn("-pix_fmt", args)
        self.assertIn("+faststart", args)

    def test_videotoolbox_uses_quality_not_crf(self) -> None:
        config = {"hardware_encoder": "videotoolbox", "video_codec": "h264", "video_crf": "20", "video_preset": "slow"}
        args = self.slverse.build_encode_args(config)
        self.assertIn("h264_videotoolbox", args)
        self.assertIn("-q:v", args)
        self.assertNotIn("-crf", args)

    def test_hevc_codec_selects_libx265_on_cpu(self) -> None:
        config = {"hardware_encoder": "cpu", "video_codec": "hevc", "video_crf": "20", "video_preset": "slow"}
        args = self.slverse.build_encode_args(config)
        self.assertIn("libx265", args)


class SlverseCacheBudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_lru_eviction_keeps_most_recently_used(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache" / "ASL"
            cache_dir.mkdir(parents=True)
            state: dict = {}
            for name in ("oldest.mp4", "middle.mp4", "newest.mp4"):
                p = cache_dir / name
                p.write_bytes(b"0" * (1024 * 1024))
                self.slverse.note_cache_use(state, p)
                time.sleep(0.01)

            config = {
                "cache_dir": str(cache_dir.parent),
                "cache_policy": "lru",
                "cache_max_gb": str(2 * 1024 * 1024 / (1024 ** 3)),
            }
            self.slverse.enforce_cache_budget(config, state)

            remaining = sorted(p.name for p in cache_dir.iterdir())
            self.assertEqual(remaining, ["middle.mp4", "newest.mp4"])

    def test_keep_all_policy_never_evicts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache" / "ASL"
            cache_dir.mkdir(parents=True)
            p = cache_dir / "a.mp4"
            p.write_bytes(b"0" * (1024 * 1024))
            state: dict = {}
            config = {"cache_dir": str(cache_dir.parent), "cache_policy": "keep_all", "cache_max_gb": "0"}
            self.slverse.enforce_cache_budget(config, state)
            self.assertTrue(p.exists())

    def test_never_writes_the_real_state_file_itself(self) -> None:
        # Regression guard: enforce_cache_budget used to call save_state()
        # internally, which always writes to the one real on-disk
        # state.json regardless of what throwaway `state` dict a caller (or
        # a test) passed in — silently clobbering real user data. It must
        # only mutate the dict in memory; persisting is the caller's job.
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache" / "ASL"
            cache_dir.mkdir(parents=True)
            p = cache_dir / "a.mp4"
            p.write_bytes(b"0" * (2 * 1024 * 1024))
            state: dict = {}
            config = {"cache_dir": str(cache_dir.parent), "cache_policy": "lru", "cache_max_gb": str(1 / 1024)}

            fake_state_file = Path(td) / "should-never-be-created.json"
            original_state_file = self.slverse.STATE_FILE
            self.slverse.STATE_FILE = fake_state_file
            try:
                self.slverse.enforce_cache_budget(config, state)
            finally:
                self.slverse.STATE_FILE = original_state_file

            self.assertFalse(fake_state_file.exists(), "enforce_cache_budget must not call save_state() itself")


class SlverseInternetAvailableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_http_error_still_counts_as_online(self) -> None:
        # Regression guard: b.jw-cdn.org 403s a bare root HEAD request, but
        # that's a real HTTP response — proof the network path works, not
        # evidence of being offline. Previously any exception (including
        # HTTPError) was treated as "offline", so the daily check silently
        # never ran despite a working connection.
        def raise_http_error(*args, **kwargs):
            raise urllib.error.HTTPError("https://b.jw-cdn.org", 403, "Forbidden", {}, io.BytesIO(b""))

        with mock.patch.object(self.slverse.urllib.request, "urlopen", raise_http_error):
            self.assertTrue(self.slverse.internet_available())

    def test_connection_failure_counts_as_offline(self) -> None:
        def raise_url_error(*args, **kwargs):
            raise urllib.error.URLError("no route to host")

        with mock.patch.object(self.slverse.urllib.request, "urlopen", raise_url_error):
            self.assertFalse(self.slverse.internet_available())

    def test_success_counts_as_online(self) -> None:
        with mock.patch.object(self.slverse.urllib.request, "urlopen", mock.MagicMock()):
            self.assertTrue(self.slverse.internet_available())


class SlverseAutoSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        # Fresh module + isolated state/config paths per test, so this never
        # touches the real ~/.config/maj-scripts/slverse — same lesson as
        # test_never_writes_the_real_state_file_itself above.
        self.slverse = load_script_module("slverse")
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self.slverse.CONFIG_DIR = tmp_dir
        self.slverse.STATE_FILE = tmp_dir / "state.json"
        self.slverse.INDEX_DIR = tmp_dir / "index"
        self.sync_calls: list = []
        self.slverse.sync_languages = lambda langs, config, state, quiet=False: self.sync_calls.append(langs)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def base_config(self, **overrides):
        config = {"languages": "ASL,FSL", "auto_sync": "true", "auto_sync_interval_hours": "24", "auto_sync_background": "false"}
        config.update(overrides)
        return config

    def test_skips_when_disabled_via_flag(self) -> None:
        args = argparse.Namespace(no_auto_sync=True)
        self.slverse.maybe_auto_sync(args, self.base_config())
        self.assertFalse(self.slverse.STATE_FILE.exists())
        self.assertEqual(self.sync_calls, [])

    def test_skips_when_disabled_via_config(self) -> None:
        args = argparse.Namespace(no_auto_sync=False)
        self.slverse.maybe_auto_sync(args, self.base_config(auto_sync="false"))
        self.assertFalse(self.slverse.STATE_FILE.exists())
        self.assertEqual(self.sync_calls, [])

    def test_skips_within_interval_no_network_check(self) -> None:
        args = argparse.Namespace(no_auto_sync=False)
        recent = time.time() - 3600  # 1 hour ago, well under the 24h default
        self.slverse.save_state({"_auto_sync": {"last_attempt": recent}})
        self.slverse.internet_available = lambda: (_ for _ in ()).throw(AssertionError("should not check connectivity when not due"))

        self.slverse.maybe_auto_sync(args, self.base_config())

        self.assertEqual(self.slverse.get_state()["_auto_sync"]["last_attempt"], recent)
        self.assertEqual(self.sync_calls, [])

    def test_marks_attempt_even_when_offline(self) -> None:
        args = argparse.Namespace(no_auto_sync=False)
        self.slverse.save_state({"_auto_sync": {"last_attempt": 0}})
        self.slverse.internet_available = lambda: False

        self.slverse.maybe_auto_sync(args, self.base_config())

        self.assertGreater(self.slverse.get_state()["_auto_sync"]["last_attempt"], time.time() - 10)
        self.assertEqual(self.sync_calls, [])

    def test_syncs_configured_languages_when_due_and_online(self) -> None:
        args = argparse.Namespace(no_auto_sync=False)
        self.slverse.save_state({"_auto_sync": {"last_attempt": 0}})
        self.slverse.internet_available = lambda: True

        self.slverse.maybe_auto_sync(args, self.base_config(languages="ASL,FSL,BVL"))

        self.assertEqual(self.sync_calls, [["ASL", "FSL", "BVL"]])
        self.assertGreater(self.slverse.get_state()["_auto_sync"]["last_attempt"], time.time() - 10)

    def test_background_default_spawns_detached_subprocess_instead_of_blocking(self) -> None:
        # Swap only this loaded module's `subprocess` name for a proxy that
        # records Popen calls and forwards everything else (DEVNULL, etc) to
        # the real module - never touch the shared real `subprocess` module
        # itself, or every later test's real subprocess calls (ffmpeg, ...)
        # would silently get this stub too.
        import subprocess as real_subprocess

        popen_calls: list = []

        class _RecordingSubprocessProxy:
            def Popen(self, argv, **kwargs):
                popen_calls.append((argv, kwargs))
            def __getattr__(self, name):
                return getattr(real_subprocess, name)

        args = argparse.Namespace(no_auto_sync=False)
        self.slverse.save_state({"_auto_sync": {"last_attempt": 0}})
        self.slverse.internet_available = lambda: True
        self.slverse.subprocess = _RecordingSubprocessProxy()

        config = self.base_config(languages="ASL,FSL,BVL")
        del config["auto_sync_background"]  # unset -> falls back to DEFAULT_CONFIG's "true"
        self.slverse.maybe_auto_sync(args, config)

        # Spawned out-of-process, not run inline - so sync_languages (patched
        # onto this module) never gets called from maybe_auto_sync itself.
        self.assertEqual(self.sync_calls, [])
        self.assertEqual(len(popen_calls), 1)
        argv, kwargs = popen_calls[0]
        self.assertEqual(argv[1:], [str(Path(self.slverse.__file__).resolve()), "sync", "--quiet"])
        self.assertTrue(kwargs.get("start_new_session"))
        self.assertGreater(self.slverse.get_state()["_auto_sync"]["last_attempt"], time.time() - 10)


class SlverseFormatVersesLabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_single_verse(self) -> None:
        self.assertEqual(self.slverse.format_verses_label([11]), "11")

    def test_contiguous_range_collapses_to_a_dash(self) -> None:
        self.assertEqual(self.slverse.format_verses_label([11, 12, 13]), "11-13")

    def test_non_contiguous_list_stays_comma_separated(self) -> None:
        self.assertEqual(self.slverse.format_verses_label([11, 13, 15]), "11,13,15")

    def test_empty_list(self) -> None:
        self.assertEqual(self.slverse.format_verses_label([]), "")


class SlverseVideotoolboxQualityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_crf20_maps_to_high_quality(self) -> None:
        # Regression guard: the old "100 - crf*3" curve put crf 20 (a fairly
        # high-quality x264 setting) at q:v 40 - visibly blocky on
        # videotoolbox's 0-100 higher-is-better scale.
        self.assertEqual(self.slverse.videotoolbox_quality_from_crf("20"), 80)

    def test_clamped_to_1_100(self) -> None:
        self.assertEqual(self.slverse.videotoolbox_quality_from_crf("0"), 100)
        self.assertEqual(self.slverse.videotoolbox_quality_from_crf("120"), 1)


class SlverseMeasureTextSizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_falls_back_to_heuristic_without_imagemagick(self) -> None:
        original = self.slverse.command_exists
        self.slverse.command_exists = lambda cmd: False
        try:
            w, h = self.slverse.measure_text_size("Psalm 16:11", None, 34)
        finally:
            self.slverse.command_exists = original
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)


class SlverseOverlayFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        # Font resolution/measurement hit the network and shell out to
        # ImageMagick respectively - stub both so these tests are fast,
        # deterministic, and never touch the real CONFIG_DIR or network.
        self.slverse.resolve_font_paths = lambda config: (None, None)
        self.slverse.measure_text_size = lambda text, font_path, fontsize: (100, 30)

    def config(self, **overrides):
        cfg = dict(self.slverse.DEFAULT_CONFIG)
        cfg.update(overrides)
        return cfg

    def test_skips_overlay_for_configured_target_lang(self) -> None:
        # The whole point of default_target_lang: requesting the SL whose
        # own burned-in caption is already correct should cut clean, not
        # draw a second caption on top of the first.
        result = self.slverse.build_overlay_filter("FSL", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False)
        self.assertIsNone(result)

    def test_target_lang_match_is_case_insensitive(self) -> None:
        result = self.slverse.build_overlay_filter("fsl", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False)
        self.assertIsNone(result)

    def test_builds_overlay_for_non_target_lang(self) -> None:
        # BVL (es) -> FSL (en): different reference languages, so the full
        # delogo+drawtext still applies - unlike ASL->FSL below, which now
        # share "en" and skip the reference swap (see sign_lang_ref_language).
        result = self.slverse.build_overlay_filter("BVL", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False)
        self.assertIsNotNone(result)
        self.assertIn("delogo=", result)
        self.assertIn("drawtext=", result)
        self.assertIn("show=0", result)

    def test_show_box_true_uses_delogo_show_1(self) -> None:
        # Preview mode: draw the box, don't actually blur anything.
        result = self.slverse.build_overlay_filter("BVL", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=True)
        self.assertIn("show=1", result)

    def test_source_lang_label_included(self) -> None:
        result = self.slverse.build_overlay_filter("bvl", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False)
        self.assertIn("text='BVL'", result)

    def test_skips_reference_when_ref_languages_match(self) -> None:
        # ASL and FSL are different sign languages but both caption in
        # English (sign_lang_ref_language default), so the verse-reference
        # swap itself is unnecessary - only the small source-SL label draws.
        result = self.slverse.build_overlay_filter("ASL", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False)
        self.assertIsNotNone(result)
        self.assertNotIn("delogo=", result)
        self.assertIn("text='ASL'", result)

    def test_skips_reference_and_label_returns_none(self) -> None:
        result = self.slverse.build_overlay_filter(
            "ASL", "Psalm", 16, "11", self.config(default_target_lang="FSL", show_source_lang_label="false"), show_box=False,
        )
        self.assertIsNone(result)

    def test_unmapped_lang_falls_back_to_full_overlay(self) -> None:
        # A sign language with no sign_lang_ref_language entry can't be
        # proven to share a reference language with the target, so it gets
        # the full (safe) overlay rather than being assumed to match.
        result = self.slverse.build_overlay_filter(
            "XSL", "Psalm", 16, "11", self.config(default_target_lang="FSL", sign_lang_ref_language="FSL=en"), show_box=False,
        )
        self.assertIn("delogo=", result)

    def test_delogo_sized_from_source_label_not_replacement_text(self) -> None:
        # The real bug this fixes: a source caption ("Mazmur 16:11") in a
        # language whose words render wider than the replacement text
        # ("Psalm 16:11") must size the delogo box off its OWN width, not
        # the replacement's.
        seen = []

        def fake_measure(text, font_path, fontsize):
            seen.append(text)
            return (200, 30) if text == "Mazmur 16:11" else (100, 30)

        self.slverse.measure_text_size = fake_measure
        result = self.slverse.build_overlay_filter(
            "INI", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False,
            source_labels=["Mazmur 16:11"],
        )
        self.assertIn("Mazmur 16:11", seen)
        self.assertNotIn("Psalm 16:11", seen)
        self.assertIn("w=220", result)  # 200 + 10 + delogo_width_pad(10)

    def test_mid_transition_fade_dips_and_recovers(self) -> None:
        # A mid-range transition (source plays on into the next verse) isn't
        # a fade to black - the source's own caption fades out, holds blank,
        # then fades back in for the next verse (confirmed by sampling real
        # frames around a Revelation 13:2->3 transition). Our overlay has to
        # follow that same down/hold/up shape, not fade out and then snap
        # straight back to full opacity.
        result = self.slverse.build_overlay_filter(
            "ASL", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False,
            fade_outs=[(10.0, 13.0, False)],
        )
        self.assertIn("if(between(t\\,10.000\\,13.000)", result)
        self.assertIn("if(lt(t\\,11.000)", result)  # end of the down-ramp (first third)
        self.assertIn("if(lt(t\\,12.000)", result)  # start of the up-ramp (last third)

    def test_final_transition_fade_is_one_way(self) -> None:
        # The extracted range's own trailing transition (only present with
        # --keep-end-transition / trim_end_transition=false) has nothing to
        # recover into - the clip just ends - so it stays a plain fade-out.
        result = self.slverse.build_overlay_filter(
            "ASL", "Psalm", 16, "11", self.config(default_target_lang="FSL"), show_box=False,
            fade_outs=[(10.0, 13.0, True)],
        )
        self.assertIn("if(between(t\\,10.000\\,13.000)", result)
        self.assertNotIn("if(lt(t", result)


class SlverseOverlayFadeOutsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def config(self, **overrides):
        cfg = dict(self.slverse.DEFAULT_CONFIG)
        cfg.update(overrides)
        return cfg

    def _stub_index(self, key, markers) -> None:
        self.slverse.load_index = lambda lang: {key: {"markers": markers}}

    def test_mid_verse_transition_tagged_not_final(self) -> None:
        # Real Revelation 13:2-3 marker data (see docs/proposals/delogo-inpainting.md's
        # empirical Rev 13:2->3 sampling and the fix this backs).
        self._stub_index("66_13", [
            {"verseNumber": 2, "startTime": "00:00:45.979", "duration": "00:00:30.897", "endTransitionDuration": "00:00:01.134", "label": "Revelation 13:2"},
            {"verseNumber": 3, "startTime": "00:01:16.876", "duration": "00:00:19.519", "endTransitionDuration": "00:00:00.000", "label": "Revelation 13:3"},
        ])
        fades = self.slverse.overlay_fade_outs("ASL", 66, 13, [2, 3], 45.979, 96.395, self.config())
        self.assertEqual(len(fades), 1)
        left, right, is_final = fades[0]
        self.assertAlmostEqual(left, 29.763, places=3)
        self.assertAlmostEqual(right, 30.897, places=3)
        self.assertFalse(is_final)

    def test_trailing_transition_tagged_final_when_kept(self) -> None:
        self._stub_index("19_16", [
            {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:06.940", "label": "Psalm 16:11"},
        ])
        fades = self.slverse.overlay_fade_outs(
            "ASL", 19, 16, [11], 149.415, 149.415 + 33.800, self.config(trim_end_transition="false"),
        )
        self.assertEqual(len(fades), 1)
        self.assertTrue(fades[0][2])


class SlverseExtractPreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        self.slverse.resolve_verse_window = lambda lang, book_num, chapter, verses, config, **kw: (
            10.0, 20.0, "http://example/vid.mp4", "abc123", [11], ["Psalm 16:11"], [(0.0, 10.0)],
        )
        # Preview's default preview_source=cache downloads/reuses a local
        # chapter file - isolate cache_dir to a throwaway temp dir and stub
        # download_file so tests never touch ~/.cache/slverse or the real
        # network (a real download_file call against a fake host would
        # actually retry 3x with backoff before giving up, which is both
        # slow and a filesystem side effect neither test should have).
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)
        self.download_calls: list = []
        self.slverse.download_file = lambda url, path, expected_checksum=None: (
            self.download_calls.append((url, path)), True
        )[1]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def base_config(self, **overrides):
        config = {"extract_mode": "onthefly", "cache_dir": str(self.cache_dir)}
        config.update(overrides)
        return config

    def test_default_no_write_previews_and_writes_nothing(self) -> None:
        preview_calls = []
        extract_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        self.slverse.extract_verse = lambda *a, **k: extract_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False)

        lang, filename, error = self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertIsNone(filename)
        self.assertIsNone(error)
        self.assertEqual(len(preview_calls), 1)
        self.assertEqual(len(extract_calls), 0)

    def test_preview_source_cache_default_downloads_once_and_plays_local_path(self) -> None:
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertEqual(len(self.download_calls), 1)
        self.assertEqual(self.download_calls[0][0], "http://example/vid.mp4")
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, str(self.cache_dir / "FSL" / "vid.mp4"))
        self.assertEqual(preview_calls[0][1].get("source_url"), "http://example/vid.mp4")

    def test_preview_source_remote_streams_url_and_never_downloads(self) -> None:
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(preview_source="remote"), {})

        self.assertEqual(self.download_calls, [])
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, "http://example/vid.mp4")

    def test_preview_source_cache_reuses_already_downloaded_file(self) -> None:
        lang_dir = self.cache_dir / "FSL"
        lang_dir.mkdir(parents=True)
        (lang_dir / "vid.mp4").write_bytes(b"fake video")
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertEqual(self.download_calls, [])  # already cached - no download needed
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, str(lang_dir / "vid.mp4"))

    def test_write_flag_encodes_and_returns_a_filename(self) -> None:
        extract_calls = []
        self.slverse.extract_verse = lambda *a, **k: extract_calls.append((a, k))
        args = argparse.Namespace(write=True, play=False, onthefly=True, cache=False)

        lang, filename, error = self.slverse.extract_one_lang("ASL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertIsNone(error)
        self.assertIsNotNone(filename)
        self.assertEqual(len(extract_calls), 1)


class SlverseParseSpeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_plain_decimal(self) -> None:
        self.assertEqual(self.slverse.parse_speed("0.5"), 0.5)

    def test_fraction(self) -> None:
        self.assertAlmostEqual(self.slverse.parse_speed("1/3"), 1 / 3)

    def test_percent(self) -> None:
        self.assertEqual(self.slverse.parse_speed("150%"), 1.5)


class SlverseResolveRetimeArgsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_neither_flag_returns_all_none(self) -> None:
        args = argparse.Namespace(slow=None, fast=None, speed=None)
        self.assertEqual(self.slverse.resolve_retime_args(args, 10.0), (None, None, None, None))

    def test_slow_defaults_to_half_speed(self) -> None:
        args = argparse.Namespace(slow=["2", "5"], fast=None, speed=None)
        mode, boundaries, speed, error = self.slverse.resolve_retime_args(args, 10.0)
        self.assertIsNone(error)
        self.assertEqual(mode, "slow")
        self.assertEqual(boundaries, [2.0, 5.0])
        self.assertEqual(speed, 0.5)

    def test_fast_defaults_to_3x(self) -> None:
        args = argparse.Namespace(slow=None, fast=["2", "5"], speed=None)
        mode, boundaries, speed, error = self.slverse.resolve_retime_args(args, 10.0)
        self.assertIsNone(error)
        self.assertEqual(mode, "fast")
        self.assertEqual(speed, 3.0)

    def test_explicit_speed_overrides_default(self) -> None:
        args = argparse.Namespace(slow=["2"], fast=None, speed=0.25)
        _, _, speed, error = self.slverse.resolve_retime_args(args, 10.0)
        self.assertIsNone(error)
        self.assertEqual(speed, 0.25)

    def test_accepts_hms_boundary_times(self) -> None:
        args = argparse.Namespace(slow=["0:02", "0:05"], fast=None, speed=None)
        _, boundaries, _, error = self.slverse.resolve_retime_args(args, 10.0)
        self.assertIsNone(error)
        self.assertEqual(boundaries, [2.0, 5.0])

    def test_boundary_at_or_past_duration_is_rejected(self) -> None:
        args = argparse.Namespace(slow=["2", "10"], fast=None, speed=None)
        _, _, _, error = self.slverse.resolve_retime_args(args, 10.0)
        self.assertIsNotNone(error)

    def test_non_increasing_boundaries_are_rejected(self) -> None:
        args = argparse.Namespace(slow=["5", "2"], fast=None, speed=None)
        _, _, _, error = self.slverse.resolve_retime_args(args, 10.0)
        self.assertIsNotNone(error)


class SlverseResolveKeptSegmentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_trim_mid_false_returns_single_segment(self) -> None:
        chapters_meta = {8: {"end": 70.0, "end_transition": 2.0}, 9: {"end": 78.0, "end_transition": 0.0}}
        segments = self.slverse.resolve_kept_segments(chapters_meta, [8, 9], 60.0, 78.0, trim_mid=False)
        self.assertEqual(segments, [(0.0, 18.0)])

    def test_ignores_last_verses_own_transition(self) -> None:
        # Only verses BEFORE the last selected one are candidates for a mid
        # cut - the last verse's own transition is trim_end_transition's
        # call, made by the caller before this function ever runs.
        chapters_meta = {8: {"end": 70.0, "end_transition": 0.0}, 9: {"end": 78.0, "end_transition": 5.0}}
        segments = self.slverse.resolve_kept_segments(chapters_meta, [8, 9], 60.0, 78.0, trim_mid=True)
        self.assertEqual(segments, [(0.0, 18.0)])

    def test_cuts_a_mid_range_paragraph_boundary(self) -> None:
        chapters_meta = {8: {"end": 70.0, "end_transition": 2.0}, 9: {"end": 78.0, "end_transition": 0.0}}
        segments = self.slverse.resolve_kept_segments(chapters_meta, [8, 9], 60.0, 78.0, trim_mid=True)
        self.assertEqual(segments, [(0.0, 8.0), (10.0, 18.0)])

    def test_cuts_multiple_mid_range_boundaries(self) -> None:
        chapters_meta = {
            1: {"end": 20.0, "end_transition": 1.0},
            2: {"end": 40.0, "end_transition": 2.0},
            3: {"end": 50.0, "end_transition": 0.0},
        }
        segments = self.slverse.resolve_kept_segments(chapters_meta, [1, 2, 3], 0.0, 50.0, trim_mid=True)
        self.assertEqual(segments, [(0.0, 19.0), (20.0, 38.0), (40.0, 50.0)])

    def test_single_verse_returns_single_segment(self) -> None:
        chapters_meta = {11: {"end": 20.0, "end_transition": 5.0}}
        segments = self.slverse.resolve_kept_segments(chapters_meta, [11], 10.0, 20.0, trim_mid=True)
        self.assertEqual(segments, [(0.0, 10.0)])


class SlverseTrimConcatFilterComplexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_video_only_by_default(self) -> None:
        fc = self.slverse.build_trim_concat_filter_complex([(0.0, 8.0), (10.0, 18.0)])
        self.assertIn("[0:v]trim=0.0:8.0,setpts=PTS-STARTPTS[v1];", fc)
        self.assertIn("[0:v]trim=10.0:18.0,setpts=PTS-STARTPTS[v2];", fc)
        self.assertIn("[v1][v2]concat=n=2:v=1[vout]", fc)
        self.assertNotIn("atrim", fc)
        self.assertNotIn("[aout]", fc)

    def test_includes_audio_when_requested(self) -> None:
        fc = self.slverse.build_trim_concat_filter_complex([(0.0, 8.0), (10.0, 18.0)], audio=True)
        self.assertIn("[0:a]atrim=0.0:8.0,asetpts=PTS-STARTPTS[a1];", fc)
        self.assertIn("[v1][a1][v2][a2]concat=n=2:v=1:a=1[vout][aout]", fc)


class SlverseExtractVerseTrimMidTest(unittest.TestCase):
    # Locks in the real bug this caught during live testing: JW's own Sign
    # Language source videos carry no audio stream, so a filter_complex
    # referencing [0:a] unconditionally fails with "Error binding
    # filtergraph inputs/outputs" - extract_verse must probe first.
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        self.slverse.build_overlay_filter = lambda *a, **k: None
        self.run_calls = []
        self.slverse.run_ffmpeg = lambda cmd, duration=None: self.run_calls.append(cmd)

    def test_no_audio_stream_omits_audio_mapping(self) -> None:
        self.slverse.has_audio_stream = lambda source: False
        config = {"interpolation_engine": "none"}
        self.slverse.extract_verse(
            "http://example/vid.mp4", "out.mp4", 0.0, 18.0, "Psalm", 16, "8-9", "ASL", config,
            kept_segments=[(0.0, 8.0), (10.0, 18.0)],
        )
        cmd = self.run_calls[0]
        self.assertNotIn("-c:a", cmd)
        self.assertNotIn("[aout]", " ".join(cmd))

    def test_audio_stream_present_maps_audio(self) -> None:
        self.slverse.has_audio_stream = lambda source: True
        config = {"interpolation_engine": "none"}
        self.slverse.extract_verse(
            "http://example/vid.mp4", "out.mp4", 0.0, 18.0, "Psalm", 16, "8-9", "ASL", config,
            kept_segments=[(0.0, 8.0), (10.0, 18.0)],
        )
        cmd = self.run_calls[0]
        self.assertIn("[aout]", cmd)
        self.assertIn("aac", cmd)


class SlverseBuildSectionedFilterComplexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_slow_retimes_even_sections(self) -> None:
        fc, out_label = self.slverse.build_sectioned_filter_complex([10, 20], 0.5, "slow", "[0:v]")
        self.assertEqual(out_label, "[out]")
        self.assertIn("[v2]setpts=PTS/0.5[r2];", fc)
        self.assertNotIn("[v1]setpts=PTS/0.5", fc)
        self.assertNotIn("[v3]setpts=PTS/0.5", fc)
        self.assertIn("[v1][r2][v3]concat=n=3:v=1:a=0[out]", fc)

    def test_fast_retimes_odd_sections(self) -> None:
        fc, out_label = self.slverse.build_sectioned_filter_complex([10, 20], 3, "fast", "[0:v]")
        self.assertIn("[v1]setpts=PTS/3[r1];", fc)
        self.assertIn("[v3]setpts=PTS/3[r3];", fc)
        self.assertNotIn("[v2]setpts=PTS/3", fc)
        self.assertIn("[r1][v2][r3]concat=n=3:v=1:a=0[out]", fc)

    def test_first_and_last_section_trims(self) -> None:
        fc, _ = self.slverse.build_sectioned_filter_complex([10, 20], 0.5, "slow", "[0:v]")
        self.assertIn("[0:v]trim=0:10,setpts=PTS-STARTPTS[v1];", fc)
        self.assertIn("[0:v]trim=10:20,setpts=PTS-STARTPTS[v2];", fc)
        self.assertIn("[0:v]trim=start=20,setpts=PTS-STARTPTS[v3];", fc)

    def test_honors_custom_base_label(self) -> None:
        # Used when an ffmpeg-filter interpolation engine (minterpolate/
        # framerate) already ran and sections trim from [base] instead.
        fc, _ = self.slverse.build_sectioned_filter_complex([10], 0.5, "slow", "[base]")
        self.assertIn("[base]trim=0:10,setpts=PTS-STARTPTS[v1];", fc)
        self.assertNotIn("[0:v]", fc)


class SlverseExtractVerseSectionsTest(unittest.TestCase):
    # Fresh module per test - monkeypatches load_ffrife/build_overlay_filter/
    # run_ffmpeg on the module object, same reasoning as SlverseFfrifeIntegrationTest.
    def setUp(self) -> None:
        self.slverse = load_script_module("slverse")
        self.slverse.build_overlay_filter = lambda *a, **k: None  # overlay covered elsewhere

    def test_fast_mode_uses_single_pass_filter_complex(self) -> None:
        calls = []
        self.slverse.run_ffmpeg = lambda cmd, duration=None: calls.append(cmd)
        config = {"interpolation_engine": "none"}

        self.slverse.extract_verse_sections(
            "http://example/vid.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config,
            "fast", [3.0, 6.0], 3,
        )

        self.assertEqual(len(calls), 1)  # exactly one ffmpeg pass, no per-section temp files
        cmd = calls[0]
        self.assertEqual(cmd[cmd.index("-ss") + 1], "10.0")
        self.assertEqual(cmd[cmd.index("-to") + 1], "20.0")
        fc = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("setpts=PTS/3", fc)

    def test_slow_mode_with_non_rife_engine_uses_single_pass_filter_complex(self) -> None:
        calls = []
        self.slverse.run_ffmpeg = lambda cmd, duration=None: calls.append(cmd)
        config = {"interpolation_engine": "none"}

        self.slverse.extract_verse_sections(
            "http://example/vid.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config,
            "slow", [5.0], 0.5,
        )

        self.assertEqual(len(calls), 1)
        fc = calls[0][calls[0].index("-filter_complex") + 1]
        self.assertIn("setpts=PTS/0.5", fc)

    def test_slow_mode_with_rife_engine_delegates_per_section_to_ffrife(self) -> None:
        ffrife_calls = []
        piece_ffmpeg_calls = []
        fake_ffrife = argparse.Namespace(
            interpolate=lambda *a, **k: ffrife_calls.append((a, k)),
            load_config=lambda: {},
        )
        self.slverse.load_ffrife = lambda: fake_ffrife
        self.slverse.probe_source_fps = lambda source: 30.0
        self.slverse.run_ffmpeg = lambda cmd, duration=None: piece_ffmpeg_calls.append(cmd)
        config = {"interpolation_engine": "rife", "default_target_lang": "FSL"}

        self.slverse.extract_verse_sections(
            "http://example/vid.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config,
            "slow", [5.0], 0.5,
        )

        # 2 sections: section 1 (normal, plain ffmpeg trim) then section 2
        # (slow, delegated to ffrife.interpolate) - plus the final concat
        # pass, all via run_ffmpeg.
        self.assertEqual(len(ffrife_calls), 1)
        args, kwargs = ffrife_calls[0]
        self.assertEqual(kwargs["start"], 15.0)  # 10.0 + boundary 5.0
        self.assertEqual(kwargs["end"], 20.0)
        self.assertEqual(kwargs["speed"], 0.5)
        self.assertEqual(kwargs["fps"], 60.0)  # probe_source_fps() * 2
        self.assertEqual(len(piece_ffmpeg_calls), 2)  # normal-section piece + final concat


class SlverseFfrifeIntegrationTest(unittest.TestCase):
    # Fresh module per test (not setUpClass) - some tests monkeypatch
    # slverse.load_ffrife/build_overlay_filter on the module object itself,
    # which would otherwise leak into later tests sharing one instance.
    def setUp(self) -> None:
        self.slverse = load_script_module("slverse")

    def test_load_ffrife_finds_sibling_script(self) -> None:
        ffrife = self.slverse.load_ffrife()
        self.assertTrue(hasattr(ffrife, "interpolate"))
        self.assertTrue(hasattr(ffrife, "install_rife"))

    def test_delogo_box_and_drawtext_split(self) -> None:
        overlay = "delogo=x=88:y=49:w=240:h=60:show=0,drawtext=text='Psalm'"
        self.assertEqual(self.slverse.delogo_box_from_filter(overlay), (88, 49, 240, 60))
        self.assertEqual(self.slverse.without_delogo(overlay), "drawtext=text='Psalm'")

    def test_load_ffrife_is_cached(self) -> None:
        first = self.slverse.load_ffrife()
        second = self.slverse.load_ffrife()
        self.assertIs(first, second)

    def test_ffrife_config_bridges_slverse_encode_settings(self) -> None:
        # Encode quality stays a single source of truth in slverse's own
        # config - ffrife shouldn't need its own separately-tuned copy
        # that could drift out of sync.
        slverse_config = {"hardware_encoder": "videotoolbox", "video_codec": "hevc", "video_crf": "18", "video_preset": "medium"}
        bridged = self.slverse.ffrife_config_for(slverse_config)
        self.assertEqual(bridged["hardware_encoder"], "videotoolbox")
        self.assertEqual(bridged["video_codec"], "hevc")
        self.assertEqual(bridged["video_crf"], "18")
        self.assertEqual(bridged["video_preset"], "medium")
        # rife-specific keys still come from ffrife's own config file, not slverse's
        self.assertIn("rife_binary_path", bridged)
        self.assertIn("rife_fallback_engine", bridged)

    def test_extract_verse_rife_engine_delegates_to_ffrife(self) -> None:
        calls = []
        fake_ffrife = argparse.Namespace(
            interpolate=lambda *a, **k: calls.append((a, k)),
            load_config=lambda: {},
        )
        self.slverse.load_ffrife = lambda: fake_ffrife
        self.slverse.build_overlay_filter = lambda *a, **k: "drawtext=text='stub'"  # font/measure logic covered elsewhere
        # RIFE exactly doubles frame count, so the merge fps has to be 2x
        # the *source's own* fps to preserve duration (a fixed 60 silently
        # drifts whenever the source isn't exactly 30fps) - see extract_verse's
        # own comment. Stubbed here rather than hitting real ffprobe.
        self.slverse.probe_source_fps = lambda source: 25.0
        config = {"interpolation_engine": "rife", "default_target_lang": "FSL"}

        self.slverse.extract_verse("http://example/vid.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config, remote=True)

        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], "http://example/vid.mp4")
        self.assertEqual(args[1], "out.mp4")
        self.assertEqual(kwargs["start"], 10.0)
        self.assertEqual(kwargs["end"], 20.0)
        self.assertEqual(kwargs["vf"], "drawtext=text='stub'")
        self.assertEqual(kwargs["fps"], 50.0)


class SlverseLaunchMpvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        # self.slverse.subprocess IS the real, process-wide stdlib subprocess
        # module (slverse does a plain `import subprocess`) - patching
        # .Popen directly without restoring it would break every other
        # test's real subprocess calls for the rest of the process (this
        # broke tests/test_smoke.py's CLI smoke tests when first written).
        # mock.patch.object via addCleanup guarantees it's undone even if a
        # test fails partway through.
        self.captured_cmd = []
        fake_proc = argparse.Namespace(pid=1234, wait=lambda: None)

        def fake_popen(cmd):
            self.captured_cmd.append(cmd)
            return fake_proc

        patcher = mock.patch.object(self.slverse.subprocess, "Popen", fake_popen)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.slverse.focus_process = lambda pid: None

    def test_osc_flag_omitted_by_default(self) -> None:
        self.slverse.launch_mpv(["file.mp4"], config={"mpv_show_osc": "true"})
        self.assertNotIn("--osc=no", self.captured_cmd[0])

    def test_osc_flag_omitted_without_config(self) -> None:
        # No config passed (e.g. some call sites don't have one in scope):
        # must not crash, and must default to mpv's normal OSC behavior.
        self.slverse.launch_mpv(["file.mp4"])
        self.assertNotIn("--osc=no", self.captured_cmd[0])

    def test_osc_flag_added_when_disabled(self) -> None:
        self.slverse.launch_mpv(["file.mp4"], config={"mpv_show_osc": "false"})
        self.assertIn("--osc=no", self.captured_cmd[0])


class SlverseConfigCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_every_default_config_key_is_documented(self) -> None:
        # CONFIG_HELP backs both 'slverse config list' and the docs claim
        # that the whole config surface is discoverable from the CLI - a
        # key added to DEFAULT_CONFIG without a matching entry here would
        # silently go undocumented.
        missing = set(self.slverse.DEFAULT_CONFIG) - set(self.slverse.CONFIG_HELP)
        self.assertEqual(missing, set())

    def test_config_get_prints_value_and_help(self) -> None:
        args = argparse.Namespace(key="cache_max_gb", value=None)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.slverse.cmd_config(args, dict(self.slverse.DEFAULT_CONFIG))
        output = out.getvalue()
        self.assertIn("cache_max_gb = 5", output)
        self.assertIn("Cache size cap", output)

    def test_config_set_updates_and_saves(self) -> None:
        args = argparse.Namespace(key="cache_max_gb", value="10")
        saved = {}
        self.slverse.save_config = lambda config: saved.update(config)
        config = dict(self.slverse.DEFAULT_CONFIG)
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.slverse.cmd_config(args, config)
        self.assertEqual(config["cache_max_gb"], "10")
        self.assertEqual(saved["cache_max_gb"], "10")


if __name__ == "__main__":
    unittest.main()
