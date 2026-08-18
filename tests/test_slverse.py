from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
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

    def test_start_clamps_to_natural_start_not_zero(self) -> None:
        # natural_start=2.0 sits well inside a longer chapter file; an
        # overshoot must not splice in footage before the verse's own start.
        result = self.slverse.clamp_offset_window(2.0, 14.0, -10.0, 0.0)
        self.assertEqual(result[0], 2.0)

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

    def test_offset_start_clamps_to_verse_own_start(self) -> None:
        # verse 1 starts 2.000s into the chapter file; an overshooting
        # offset_start must clamp there, not to the file's absolute 0.0 -
        # otherwise it would splice in whatever precedes this verse.
        self._stub_index([
            {"verseNumber": 1, "startTime": "00:00:02.000", "duration": "00:00:05.000", "endTransitionDuration": "00:00:00.000", "label": "Psalm 16:1"},
        ])
        start, end, url, checksum, valid_verses, source_labels, kept_segments = self.slverse.resolve_verse_window(
            "ASL", 19, 16, [1], self.config(), offset_start=-10.0,
        )
        self.assertEqual(start, 2.0)

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


class SlverseBookNameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def metadata(self, name="Phục truyền luật lệ", abbreviation="Phục"):
        return {"editionData": {"books": {"5": {
            "standardSingularBookName": name,
            "officialAbbreviation": abbreviation,
        }}}}

    def test_vietnamese_lookup_ignores_case_and_tone_marks(self) -> None:
        state = {"_book_metadata": {"VT": self.metadata()}}
        self.assertEqual(self.slverse.resolve_book_number("PHUC TRUYEN LUAT LE", "VT", state), 5)

    def test_book_language_priority_falls_back(self) -> None:
        state = {"_book_metadata": {
            "VT": self.metadata(),
            "E": self.metadata("Deuteronomy", "Deut."),
        }}
        self.assertEqual(self.slverse.resolve_book_number("Deuteronomy", "VT,E", state), 5)

    def test_plural_book_name_and_abbreviation_resolve(self) -> None:
        # Real JW.org study-bible metadata carries 9 name/abbreviation
        # fields per book (standard/official x singular/plural, plus a
        # plain standardName/standardAbbreviation) - only 2 were checked
        # before, so "Psalms" (the plural form) silently failed to resolve
        # even though "Psalm" (singular) did.
        state = {"_book_metadata": {"E": {"editionData": {"books": {"19": {
            "standardName": "Psalms",
            "standardAbbreviation": "Ps.",
            "standardSingularBookName": "Psalm",
            "standardSingularAbbreviation": "Ps.",
            "standardPluralBookName": "Psalms",
            "standardPluralAbbreviation": "Pss.",
            "officialAbbreviation": "Ps",
            "officialSingularAbbreviation": "Ps",
            "officialPluralAbbreviation": "Pss",
        }}}}}}
        self.assertEqual(self.slverse.resolve_book_number("Psalms", "E", state), 19)
        self.assertEqual(self.slverse.resolve_book_number("Pss", "E", state), 19)
        self.assertEqual(self.slverse.resolve_book_number("psalm", "E", state), 19)

    def test_every_supported_alias_resolves_to_standard_name(self) -> None:
        book = {
            "standardName": "Khải huyền", "standardAbbreviation": "Kh", "officialAbbreviation": "Kh.",
            "standardSingularBookName": "Khải huyền singular", "standardSingularAbbreviation": "Khs", "officialSingularAbbreviation": "Khs.",
            "standardPluralBookName": "Khải huyền plural", "standardPluralAbbreviation": "Khp", "officialPluralAbbreviation": "Khp.",
            "bookDisplayTitle": "Sách Khải huyền",
        }
        state = {"_book_metadata": {"VT": {"editionData": {"books": {"66": book}}}}}
        for value in list(book.values()) + ["66"]:
            with self.subTest(value=value):
                self.assertEqual(self.slverse.resolve_book(value, "VT", state), (66, "Khải huyền"))


class SlverseBibleMetadataUrlTest(unittest.TestCase):
    """get_bible_metadata's URL isn't a simple locale-prefix swap - jw.org
    translates the whole Study Bible 'Books' page path per language (e.g.
    Vietnamese lives at .../vi/thu-vien/kinh-thanh/nwt/cac-sach/json/, not
    .../vi/library/bible/study-bible/books/json/, which 404s). The real
    path is auto-discovered from a data-bible_data_api attribute every
    jw.org locale homepage embeds (same mechanism jw.org's own frontend
    uses, and how the community jw-api project resolves this too). These
    tests stub the network entirely and check the URL-building logic only."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    VI_HOMEPAGE_HTML = (
        '<div id="pageConfig" data-wt_lang="VT" '
        'data-bible_data_api="/vi/thu-vien/kinh-thanh/nwt/cac-sach/json/data/"></div>'
    )
    KO_HOMEPAGE_HTML = (
        '<div id="pageConfig" data-wt_lang="KO" '
        'data-bible_data_api="/ko/%EB%9D%BC%EC%9D%B4%EB%B8%8C/json/data/"></div>'
    )

    def test_english_never_triggers_the_homepage_scrape(self) -> None:
        text_calls = []
        json_calls = []
        self.slverse.fetch_text = lambda url: text_calls.append(url) or self.VI_HOMEPAGE_HTML
        self.slverse.fetch_json = lambda url: json_calls.append(url) or {"editionData": {}}

        self.slverse.get_bible_metadata("E", state={}, config={})

        self.assertEqual(text_calls, [])
        self.assertEqual(json_calls, ["https://www.jw.org/en/library/bible/study-bible/books/json/"])

    def test_non_english_language_resolved_from_its_own_homepage(self) -> None:
        # Vietnamese isn't in jw.org's hreflang alternate-language list
        # (confirmed against the real page) even though its Study Bible
        # edition exists - the homepage-scrape approach doesn't depend on
        # that list at all, so it resolves Vietnamese with zero config.
        text_calls = []
        json_calls = []
        self.slverse.fetch_text = lambda url: text_calls.append(url) or self.VI_HOMEPAGE_HTML
        self.slverse.fetch_json = lambda url: json_calls.append(url) or {"editionData": {}}
        state = {}

        self.slverse.get_bible_metadata("VT", state=state, config={})

        self.assertEqual(text_calls, ["https://www.jw.org/vi/"])
        self.assertEqual(json_calls, ["https://www.jw.org/vi/thu-vien/kinh-thanh/nwt/cac-sach/json/"])
        # Cached in state - a second lookup for the same locale must not re-scrape.
        self.slverse.fetch_text = lambda url: (_ for _ in ()).throw(AssertionError("should not re-fetch"))
        self.slverse.get_bible_metadata("VT", state=state, config={})

    def test_different_locales_resolved_independently(self) -> None:
        html_by_locale = {"vi": self.VI_HOMEPAGE_HTML, "ko": self.KO_HOMEPAGE_HTML}
        self.slverse.fetch_text = lambda url: html_by_locale[url.rstrip("/").rsplit("/", 1)[-1]]
        json_calls = []
        self.slverse.fetch_json = lambda url: json_calls.append(url) or {"editionData": {}}

        self.slverse.get_bible_metadata("KO", state={}, config={})

        self.assertEqual(json_calls, ["https://www.jw.org/ko/%EB%9D%BC%EC%9D%B4%EB%B8%8C/json/"])

    def test_config_override_skips_the_homepage_scrape_entirely(self) -> None:
        text_calls = []
        json_calls = []
        self.slverse.fetch_text = lambda url: text_calls.append(url) or self.VI_HOMEPAGE_HTML
        self.slverse.fetch_json = lambda url: json_calls.append(url) or {"editionData": {}}
        config = {"bible_book_path_overrides": "VT=some/manual/path"}

        self.slverse.get_bible_metadata("VT", state={}, config=config)

        self.assertEqual(text_calls, [])
        self.assertEqual(json_calls, ["https://www.jw.org/vi/some/manual/path/json/"])

    def test_language_with_no_bible_data_api_attribute_returns_none(self) -> None:
        json_calls = []
        self.slverse.fetch_text = lambda url: "<html>no pageConfig here</html>"
        self.slverse.fetch_json = lambda url: json_calls.append(url) or {"editionData": {}}

        result = self.slverse.get_bible_metadata("ZZZ", state={}, config={})

        self.assertIsNone(result)
        self.assertEqual(json_calls, [])


class SlverseEncodeArgsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        # build_encode_args now probes real `ffmpeg -encoders` (via the
        # shared _jwkit_common.resolve_video_encoder) to decide whether the
        # requested codec/hardware combo is actually available - stub that
        # probe rather than depending on whatever ffmpeg happens to be
        # installed on the machine running the tests. Also clear its
        # resolution cache: it's keyed on (ffmpeg_bin, hw, codec) and shared
        # module-wide (real `import _jwkit_common`, not a fresh load per
        # test), so a stale entry from a different fake availability set
        # would otherwise leak across tests.
        common = self.slverse._jwkit_common
        self._orig_has_encoder = common.ffmpeg_has_encoder
        self._orig_resolved_cache = dict(common._RESOLVED_ENCODER_CACHE)
        self._orig_warned = set(common._ENCODER_FALLBACK_WARNED)
        common._RESOLVED_ENCODER_CACHE.clear()
        common._ENCODER_FALLBACK_WARNED.clear()
        self.available_encoders = {
            "libx264", "libx265", "libsvtav1", "h264_videotoolbox", "hevc_videotoolbox",
        }  # everything the "current default hardware" tests below expect - no av1_videotoolbox, matching real VideoToolbox before M5 Pro/Max
        common.ffmpeg_has_encoder = lambda ffmpeg_bin, name: name in self.available_encoders
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        common = self.slverse._jwkit_common
        common.ffmpeg_has_encoder = self._orig_has_encoder
        common._RESOLVED_ENCODER_CACHE.clear()
        common._RESOLVED_ENCODER_CACHE.update(self._orig_resolved_cache)
        common._ENCODER_FALLBACK_WARNED.clear()
        common._ENCODER_FALLBACK_WARNED.update(self._orig_warned)

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

    def test_av1_selects_libsvtav1_on_cpu(self) -> None:
        config = {"hardware_encoder": "cpu", "video_codec": "av1", "video_crf": "auto", "video_preset": "slow"}
        args = self.slverse.build_encode_args(config)
        self.assertIn("libsvtav1", args)
        self.assertIn("30", args)  # av1's own auto-crf default

    def test_av1_on_videotoolbox_falls_back_to_software_av1(self) -> None:
        # No av1_videotoolbox in self.available_encoders (matches real
        # VideoToolbox before the 2026 M5 Pro/Max) - av1 is still achievable
        # via software, so this must NOT silently downgrade to h264 (the
        # pre-fix behavior) or hevc; it should stay av1 via libsvtav1.
        config = {"hardware_encoder": "videotoolbox", "video_codec": "av1", "video_crf": "auto", "video_preset": "slow"}
        args = self.slverse.build_encode_args(config, notice=False)
        self.assertIn("libsvtav1", args)
        self.assertIn("-crf", args)  # software path, not videotoolbox's -q:v

    def test_av1_unavailable_anywhere_falls_back_to_hevc_then_h264(self) -> None:
        common = self.slverse._jwkit_common
        common.ffmpeg_has_encoder = lambda ffmpeg_bin, name: name == "libx265"
        config = {"hardware_encoder": "cpu", "video_codec": "av1", "video_crf": "auto", "video_preset": "slow"}
        args = self.slverse.build_encode_args(config, notice=False)
        self.assertIn("libx265", args)
        self.assertIn("23", args)  # hevc's own auto-crf default, not av1's

        common.ffmpeg_has_encoder = lambda ffmpeg_bin, name: name == "libx264"
        common._RESOLVED_ENCODER_CACHE.clear()
        args = self.slverse.build_encode_args(config, notice=False)
        self.assertIn("libx264", args)
        self.assertIn("20", args)

    def test_hevc_never_falls_back_upward_to_av1(self) -> None:
        config = {"hardware_encoder": "cpu", "video_codec": "hevc", "video_crf": "auto", "video_preset": "slow"}
        args = self.slverse.build_encode_args(config, notice=False)
        self.assertIn("libx265", args)
        self.assertNotIn("libsvtav1", args)


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
                "cache_max_size": "2Mi",
            }
            self.slverse.enforce_cache_budget(config, state)

            remaining = sorted(p.name for p in cache_dir.iterdir())
            self.assertEqual(remaining, ["middle.mp4", "newest.mp4"])

    def test_in_use_file_is_never_evicted_even_if_lru_oldest(self) -> None:
        # 'extract all'/'bulk' run each language's download+use in its own
        # thread against one shared cache dir (extract_workers, default 3;
        # cache_policy defaults to lru) - a concurrent thread's own
        # enforce_cache_budget call must not delete a file THIS thread is
        # still actively playing/encoding from, even though `protect=`
        # there only ever names that OTHER thread's own file.
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
                "cache_max_size": "2Mi",
            }
            oldest = cache_dir / "oldest.mp4"
            with self.slverse.cache_in_use(oldest):
                self.slverse.enforce_cache_budget(config, state)
                remaining = sorted(p.name for p in cache_dir.iterdir())

            self.assertIn("oldest.mp4", remaining)
            self.assertNotIn("middle.mp4", remaining)  # next-oldest evicted instead

    def test_cache_in_use_clears_even_on_exception(self) -> None:
        p = Path("/tmp/does-not-need-to-exist-for-this-check.mp4")
        with self.assertRaises(ValueError):
            with self.slverse.cache_in_use(p):
                raise ValueError("boom")
        self.assertNotIn(str(p.resolve()), self.slverse._CACHE_INUSE)

    def test_keep_all_policy_never_evicts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache" / "ASL"
            cache_dir.mkdir(parents=True)
            p = cache_dir / "a.mp4"
            p.write_bytes(b"0" * (1024 * 1024))
            state: dict = {}
            config = {"cache_dir": str(cache_dir.parent), "cache_policy": "keep_all", "cache_max_size": "0"}
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
            config = {"cache_dir": str(cache_dir.parent), "cache_policy": "lru", "cache_max_size": "1Mi"}

            fake_state_file = Path(td) / "should-never-be-created.json"
            original_state_file = self.slverse.STATE_FILE
            self.slverse.STATE_FILE = fake_state_file
            try:
                self.slverse.enforce_cache_budget(config, state)
            finally:
                self.slverse.STATE_FILE = original_state_file

            self.assertFalse(fake_state_file.exists(), "enforce_cache_budget must not call save_state() itself")

    def test_second_call_trusts_the_running_total_instead_of_rescanning(self) -> None:
        # The whole point of tracking state["_cache_bytes"]: once a total is
        # known and we're under budget, a repeat call (e.g. after every
        # single segment download in a session) must be O(1), not another
        # full directory walk.
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache" / "ASL"
            cache_dir.mkdir(parents=True)
            (cache_dir / "a.mp4").write_bytes(b"0" * (1024 * 1024))
            state: dict = {}
            config = {"cache_dir": str(cache_dir.parent), "cache_policy": "lru", "cache_max_size": "10Mi"}

            self.slverse.enforce_cache_budget(config, state)  # first call: unknown total, must scan
            root = str(cache_dir.parent)
            self.assertEqual(state["_cache_bytes"][root], 1024 * 1024)

            def scan_should_not_run(*a, **k):
                raise AssertionError("enforce_cache_budget rescanned despite already knowing the total")
            self.slverse._scan_cache_dir = scan_should_not_run

            self.slverse.enforce_cache_budget(config, state, added_bytes=2 * 1024 * 1024)

            self.assertEqual(state["_cache_bytes"][root], 3 * 1024 * 1024)

    def test_eviction_falls_back_to_a_real_scan_once_the_running_total_goes_over_budget(self) -> None:
        # A known running total avoids a scan only while it says we're
        # under budget (see the previous test) - the moment added_bytes
        # pushes it over, eviction needs real file sizes/ages to pick
        # candidates, which the total alone can't provide, so this must
        # fall back to an actual directory walk rather than e.g. evicting
        # nothing or picking an arbitrary file.
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache" / "ASL"
            cache_dir.mkdir(parents=True)
            state: dict = {}
            for name in ("oldest.mp4", "newest.mp4"):
                p = cache_dir / name
                p.write_bytes(b"0" * (1024 * 1024))
                self.slverse.note_cache_use(state, p)
                time.sleep(0.01)
            config = {"cache_dir": str(cache_dir.parent), "cache_policy": "lru", "cache_max_size": "1Mi"}
            state["_cache_bytes"] = {str(cache_dir.parent): 0}  # known, currently under budget

            self.slverse.enforce_cache_budget(config, state, added_bytes=2 * 1024 * 1024)

            remaining = sorted(p.name for p in cache_dir.iterdir())
            self.assertEqual(remaining, ["newest.mp4"])

    def test_invalidate_cache_totals_clears_tracked_value(self) -> None:
        state = {"_cache_bytes": {"/a": 100, "/b": 200}}
        self.slverse.invalidate_cache_totals(state, "/a")
        self.assertEqual(state["_cache_bytes"], {"/b": 200})

    def test_invalidate_cache_totals_with_no_arg_clears_everything(self) -> None:
        state = {"_cache_bytes": {"/a": 100, "/b": 200}}
        self.slverse.invalidate_cache_totals(state)
        self.assertEqual(state["_cache_bytes"], {})

    def test_invalidate_cache_totals_is_a_noop_without_a_prior_total(self) -> None:
        state: dict = {}
        self.slverse.invalidate_cache_totals(state, "/a")  # must not raise
        self.assertEqual(state, {})

    def test_cmd_cache_clean_invalidates_and_persists_the_running_total(self) -> None:
        # A 'cache clean' changes cache_dir out from under enforce_cache_
        # budget without going through it - the tracked total has to be
        # invalidated (and that invalidation actually saved to state.json,
        # not just held in a throwaway in-memory dict) or the next lru
        # check would trust a number that no longer means anything.
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            (cache_dir / "ASL").mkdir(parents=True)
            (cache_dir / "ASL" / "a.mp4").write_bytes(b"0" * 1024)
            state_file = Path(td) / "state.json"
            state_file.write_text(json.dumps({"_cache_bytes": {str(cache_dir): 999999}}))
            original_state_file = self.slverse.STATE_FILE
            self.slverse.STATE_FILE = state_file
            try:
                args = argparse.Namespace(action="clean", lang=None)
                config = {"cache_dir": str(cache_dir)}
                self.slverse.cmd_cache(args, config)
            finally:
                self.slverse.STATE_FILE = original_state_file

            persisted = json.loads(state_file.read_text())
            self.assertEqual(persisted.get("_cache_bytes", {}), {})


class SlverseSegmentCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_segment_cache_path_is_stable_and_scoped_by_lang_book_chapter_window(self) -> None:
        config = {"cache_dir": "/cache"}
        a = self.slverse.segment_cache_path(config, "ASL", 54, 1, 221.788, 236.336)
        b = self.slverse.segment_cache_path(config, "ASL", 54, 1, 221.788, 236.336)
        different_window = self.slverse.segment_cache_path(config, "ASL", 54, 1, 221.788, 240.0)
        different_lang = self.slverse.segment_cache_path(config, "FSL", 54, 1, 221.788, 236.336)
        self.assertEqual(a, b)
        self.assertNotEqual(a, different_window)
        self.assertNotEqual(a, different_lang)
        self.assertEqual(a.parent, Path("/cache/ASL/segments"))

    def test_download_segment_uses_zero_based_output_seek_and_retries_on_failure(self) -> None:
        calls = []

        def fake_run_ffmpeg(args, duration=None, label="Encoding"):
            calls.append(args)
            if len(calls) == 1:
                raise self.slverse.subprocess.CalledProcessError(1, args)
            Path(args[-1]).write_bytes(b"fake ffmpeg output")  # real ffmpeg writes to its last arg on success

        self.slverse.run_ffmpeg = fake_run_ffmpeg
        self.slverse.MAX_ATTEMPTS = 3
        self.slverse.RETRY_BACKOFF = 2
        # self.slverse.time IS the real, process-wide stdlib time module (see
        # SlverseLaunchMpvTest's own note on subprocess.Popen) - patch just
        # .sleep via mock.patch.object so it's guaranteed restored even if
        # this test fails partway through, instead of leaking a stubbed
        # sleep to every test that runs after this one.
        sleep_patcher = mock.patch.object(self.slverse.time, "sleep", lambda seconds: None)
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "seg.mp4"
            ok = self.slverse.download_segment("http://example/vid.mp4", out, 10.0, 20.0)

        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)  # first attempt failed, second succeeded
        for args in calls:
            self.assertNotIn("-copyts", args)
            self.assertEqual(args[args.index("-c") + 1], "copy")
            self.assertEqual(args[0:2], ["-ss", "10.0"])
            self.assertEqual(args[args.index("-ss") + 1], "10.0")
            self.assertEqual(args[args.index("-to") + 1], "20.0")
            self.assertEqual(args[args.index("-reset_timestamps") + 1], "1")

    def test_resolve_segment_source_reuses_cached_file_without_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = {"cache_dir": td}
            cached = self.slverse.segment_cache_path(config, "ASL", 54, 1, 10.0, 20.0)
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"already here")
            self.slverse.download_segment = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch"))

            source, cached_path = self.slverse.resolve_segment_source("http://example/vid.mp4", "ASL", 54, 1, 10.0, 20.0, config, {})

            self.assertEqual(source, str(cached))
            self.assertEqual(cached_path, cached)

    def test_resolve_segment_source_falls_back_to_url_when_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = {"cache_dir": td}
            self.slverse.download_segment = lambda *a, **k: False

            source, cached_path = self.slverse.resolve_segment_source("http://example/vid.mp4", "ASL", 54, 1, 10.0, 20.0, config, {})

            self.assertEqual(source, "http://example/vid.mp4")
            self.assertIsNone(cached_path)

    def test_download_segment_against_a_real_local_file_produces_a_playable_trim(self) -> None:
        # Runs real ffmpeg (no network - a synthetic local source stands in
        # for the remote URL) instead of mocking run_ffmpeg, specifically to
        # catch muxer/container-format issues a mocked call can't: ffmpeg
        # guesses the output container from the FILENAME's extension, and
        # the .part suffix download_segment writes to (for the same atomic
        # write-then-rename download_file already uses) isn't a recognized
        # one on its own - this caught a real "Unable to choose an output
        # format for ...mp4.part" failure during development, fixed by
        # passing -f mp4 explicitly rather than relying on the extension.
        ffmpeg_bin = self.slverse.resolve_ffmpeg_binary(self.slverse.DEFAULT_CONFIG)
        if not self.slverse.command_exists(ffmpeg_bin):
            self.skipTest(f"{ffmpeg_bin} not available on this machine")
        self.slverse.FFMPEG_BIN = ffmpeg_bin

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            subprocess.run(
                [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                 "-i", "testsrc2=size=320x240:rate=30:duration=6",
                 "-c:v", "libx264", "-preset", "ultrafast", str(source)],
                check=True, timeout=60,
            )
            out = Path(td) / "seg.mp4"
            ok = self.slverse.download_segment(str(source), out, 2.0, 4.0)

            self.assertTrue(ok)
            self.assertTrue(out.exists())
            self.assertLess(out.stat().st_size, source.stat().st_size)
            probe = subprocess.run(
                [self.slverse.resolve_ffprobe_binary(self.slverse.DEFAULT_CONFIG), "-v", "error",
                 "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
                check=True, capture_output=True, text=True, timeout=30,
            )
            self.assertGreater(float(probe.stdout.strip()), 0)


class SlverseDetectCaptionBoxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def make_frame(self, crop, glyph_box, rgb=(235, 235, 235), background=(70, 70, 70)):
        left, top, width, height = crop
        gx, gy, gw, gh = glyph_box
        buf = bytearray(background * (width * height))
        # Synthetic separated strokes exercise normal spaces without making
        # the fixture depend on Pillow/OpenCV or an installed font.
        for x in range(gx, gx + gw, 12):
            for yy in range(gy, gy + gh):
                for xx in range(x, min(x + 7, gx + gw)):
                    offset = ((yy - top) * width + (xx - left)) * 3
                    buf[offset:offset + 3] = bytes(rgb)
        return bytes(buf)

    def test_detects_near_white_static_caption_from_majority_vote(self) -> None:
        config = {"overlay_x": "93", "overlay_y": "54"}
        crop = (48, 19, 500, 105)
        frames = [self.make_frame(crop, (95, 56, 205, 24)) for _ in range(3)]
        with mock.patch.object(self.slverse.subprocess, "run", side_effect=[argparse.Namespace(stdout=f) for f in frames]):
            box = self.slverse.detect_caption_box("source.mp4", 0.0, 12.0, config)
        self.assertEqual(box, (95, 56, 205, 24))

    def test_colored_bright_foreground_is_not_mistaken_for_caption(self) -> None:
        config = {"overlay_x": "93", "overlay_y": "54"}
        crop = (48, 19, 500, 105)
        frames = [self.make_frame(crop, (95, 56, 205, 24), rgb=(245, 175, 140)) for _ in range(3)]
        with mock.patch.object(self.slverse.subprocess, "run", side_effect=[argparse.Namespace(stdout=f) for f in frames]):
            self.assertIsNone(self.slverse.detect_caption_box("source.mp4", 0.0, 12.0, config))

    def test_disagreement_falls_back_instead_of_guessing(self) -> None:
        config = {"overlay_x": "93", "overlay_y": "54"}
        crop = (48, 19, 500, 105)
        frames = [self.make_frame(crop, box) for box in ((95, 56, 205, 24), (95, 75, 150, 15), (95, 35, 280, 35))]
        with mock.patch.object(self.slverse.subprocess, "run", side_effect=[argparse.Namespace(stdout=f) for f in frames]):
            self.assertIsNone(self.slverse.detect_caption_box("source.mp4", 0.0, 12.0, config))

    def test_remote_source_uses_proxy_fallback_without_three_network_seeks(self) -> None:
        with mock.patch.object(self.slverse.subprocess, "run") as run:
            self.assertIsNone(self.slverse.detect_caption_box("https://example/verse.mp4", 0.0, 12.0, {}))
        run.assert_not_called()


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
        self.assertIn("w=212", result)  # measured 200 + built-in 10 + configured 2px margin

    def test_exact_source_caption_automatically_skips_reference_replacement(self) -> None:
        result = self.slverse.build_overlay_filter(
            "XSL", "Psalm", 16, "11",
            self.config(default_target_lang="FSL", sign_lang_ref_language="", show_source_lang_label="true"),
            show_box=False, source_labels=["  PSALM 16:11  "],
        )
        self.assertNotIn("delogo=", result)
        self.assertIn("drawtext=text='XSL'", result)

    def test_confident_pixel_box_replaces_proxy_dimensions(self) -> None:
        result = self.slverse.build_overlay_filter(
            "BVL", "Psalm", 16, "11", self.config(default_target_lang="FSL"),
            show_box=False, source_labels=["Salmos 16:11"], detected_caption_box=(100, 57, 200, 24),
        )
        self.assertIn("delogo=x=98:y=55:w=204:h=28", result)
        self.assertIn("drawtext=text='BVL'", result)
        # Label offset is a fixed line-height (fontsize*1.3 - 5 = 44 at the
        # default fontsize 34) below the detected caption's top (57), not
        # the caption's own tight glyph height (24) - see build_overlay_filter.
        self.assertIn(":y=96:alpha=", result)

    def test_source_label_spacing_is_unaffected_by_caption_detection(self) -> None:
        # Regression test: a confident pixel-detected box's *tight* glyph
        # height must not be substituted into the label's vertical gap - it
        # used to crowd the label right up against the caption's descenders
        # once caption_detection replaced the old, generous proxy-font
        # height for `h`. With the detected box's top pinned to the same
        # position build_overlay_filter would otherwise assume (overlay_x/y),
        # the label must land at the exact same y whether or not a confident
        # box was detected - only the *source* of the height (tight glyph vs
        # font-metric estimate) should differ, not the label's own spacing.
        config = self.config(default_target_lang="FSL", sign_lang_ref_language="", show_source_lang_label="true")
        without_detection = self.slverse.build_overlay_filter(
            "XSL", "Psalm", 16, "11", config, show_box=False, source_labels=["  PSALM 16:11  "],
        )
        overlay_y = int(config["overlay_y"])
        with_detection = self.slverse.build_overlay_filter(
            "XSL", "Psalm", 16, "11", config, show_box=False, source_labels=["  PSALM 16:11  "],
            detected_caption_box=(int(config["overlay_x"]), overlay_y, 200, 24),
        )
        label_y_without = re.search(r"drawtext=text='XSL'.*?:y=(\d+):", without_detection).group(1)
        label_y_with = re.search(r"drawtext=text='XSL'.*?:y=(\d+):", with_detection).group(1)
        self.assertEqual(label_y_without, label_y_with)

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

        def fake_download_file(url, path, expected_checksum=None):
            self.download_calls.append((url, path))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"fake video")  # real download_file leaves a real file behind too
            return True

        self.slverse.download_file = fake_download_file
        # Same idea for segment-level caching (preview_source/extract_mode=
        # segment) - stub download_segment so these tests never shell out to
        # a real ffmpeg against a fake URL.
        self.segment_download_calls: list = []

        def fake_download_segment(url, path, start_time, end_time):
            self.segment_download_calls.append((url, path, start_time, end_time))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"fake segment")
            return True

        self.slverse.download_segment = fake_download_segment

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
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        lang, filename, error = self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertIsNone(filename)
        self.assertIsNone(error)
        self.assertEqual(len(preview_calls), 1)
        self.assertEqual(len(extract_calls), 0)

    def test_preview_source_segment_is_default_and_downloads_only_the_window(self) -> None:
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertEqual(self.download_calls, [])  # never the whole chapter
        self.assertEqual(len(self.segment_download_calls), 1)
        url, path, start, end = self.segment_download_calls[0]
        self.assertEqual(url, "http://example/vid.mp4")
        self.assertEqual((start, end), (10.0, 20.0))
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, str(path))
        self.assertEqual(preview_calls[0][1].get("source_url"), "http://example/vid.mp4")

    def test_preview_source_segment_reuses_already_cached_segment(self) -> None:
        seg_path = self.slverse.segment_cache_path(self.base_config(), "FSL", 19, 16, 10.0, 20.0)
        seg_path.parent.mkdir(parents=True)
        seg_path.write_bytes(b"fake segment")
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertEqual(self.segment_download_calls, [])  # already cached - no fetch needed
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, str(seg_path))
        self.assertEqual(preview_calls[0][0][1:3], (0.0, 10.0))

    def test_preview_source_cache_downloads_whole_chapter_once_and_plays_local_path(self) -> None:
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(preview_source="cache"), {})

        self.assertEqual(self.segment_download_calls, [])
        self.assertEqual(len(self.download_calls), 1)
        self.assertEqual(self.download_calls[0][0], "http://example/vid.mp4")
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, str(self.cache_dir / "FSL" / "vid.mp4"))
        self.assertEqual(preview_calls[0][1].get("source_url"), "http://example/vid.mp4")

    def test_preview_source_remote_streams_url_and_never_downloads(self) -> None:
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(preview_source="remote"), {})

        self.assertEqual(self.download_calls, [])
        self.assertEqual(self.segment_download_calls, [])
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, "http://example/vid.mp4")

    def test_preview_source_cache_reuses_already_downloaded_whole_chapter(self) -> None:
        lang_dir = self.cache_dir / "FSL"
        lang_dir.mkdir(parents=True)
        (lang_dir / "vid.mp4").write_bytes(b"fake video")
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11], args, self.base_config(preview_source="cache"), {})

        self.assertEqual(self.download_calls, [])  # already cached - no download needed
        played_source = preview_calls[0][0][0]
        self.assertEqual(played_source, str(lang_dir / "vid.mp4"))

    def test_write_flag_encodes_and_returns_a_filename(self) -> None:
        extract_calls = []
        self.slverse.extract_verse = lambda *a, **k: extract_calls.append((a, k))
        args = argparse.Namespace(write=True, play=False, onthefly=True, cache=False, segment=False)

        lang, filename, error = self.slverse.extract_one_lang("ASL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertIsNone(error)
        self.assertIsNotNone(filename)
        self.assertEqual(len(extract_calls), 1)

    def test_write_flag_with_segment_mode_caches_only_the_window(self) -> None:
        extract_calls = []
        self.slverse.extract_verse = lambda *a, **k: extract_calls.append((a, k))
        args = argparse.Namespace(write=True, play=False, onthefly=False, cache=False, segment=True)

        lang, filename, error = self.slverse.extract_one_lang("ASL", "Psalm", 19, 16, [11], args, self.base_config(), {})

        self.assertIsNone(error)
        self.assertIsNotNone(filename)
        self.assertEqual(self.download_calls, [])  # never the whole chapter
        self.assertEqual(len(self.segment_download_calls), 1)
        url, path, start, end = self.segment_download_calls[0]
        self.assertEqual((url, start, end), ("http://example/vid.mp4", 10.0, 20.0))
        self.assertEqual(extract_calls[0][0][0], str(path))  # extract_verse's source is the cached segment
        self.assertEqual(extract_calls[0][0][2:4], (0.0, 10.0))
        self.assertEqual(extract_calls[0][1].get("remote"), False)

    def test_partial_range_is_accepted_by_default(self) -> None:
        # Requesting verses 11-12 but the language only actually has 11
        # (resolve_verse_window's valid_verses reflects that) is accepted
        # as-is outside 'any' mode - existing single/all-language behavior.
        self.slverse.resolve_verse_window = lambda lang, book_num, chapter, verses, config, **kw: (
            10.0, 20.0, "http://example/vid.mp4", "abc123", [11], ["Psalm 16:11"], [(0.0, 10.0)],
        )
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        lang, filename, error = self.slverse.extract_one_lang("FSL", "Psalm", 19, 16, [11, 12], args, self.base_config(), {})

        self.assertIsNone(error)
        self.assertEqual(len(preview_calls), 1)

    def test_partial_range_is_rejected_when_full_range_required(self) -> None:
        # 'any' mode's whole point is picking a language that has the FULL
        # requested range, not silently truncating to whatever one language
        # happens to have - so require_full_range=True must fail here
        # instead of previewing/extracting a partial clip.
        self.slverse.resolve_verse_window = lambda lang, book_num, chapter, verses, config, **kw: (
            10.0, 20.0, "http://example/vid.mp4", "abc123", [11], ["Psalm 16:11"], [(0.0, 10.0)],
        )
        preview_calls = []
        self.slverse.preview_verse = lambda *a, **k: preview_calls.append((a, k))
        args = argparse.Namespace(write=False, play=False, onthefly=False, cache=False, segment=False)

        lang, filename, error = self.slverse.extract_one_lang(
            "FSL", "Psalm", 19, 16, [11, 12], args, self.base_config(), {}, require_full_range=True,
        )

        self.assertIsNotNone(error)
        self.assertIn("12", error)
        self.assertEqual(len(preview_calls), 0)


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


class SlverseDetectDelogoOcclusionTest(unittest.TestCase):
    """Standalone coverage for the cheap occlusion detector (delogo_engine
    auto) - previously untested. Builds a synthetic raw RGB24 crop buffer
    matching the exact dimensions detect_delogo_occlusion requests, rather
    than depending on a real video."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        self.raw_frames = []  # queue of raw bytes to hand back, one per call

        def fake_run(cmd, check=True, capture_output=True, timeout=None):
            payload = self.raw_frames.pop(0)
            return argparse.Namespace(stdout=payload)

        patcher = mock.patch.object(self.slverse.subprocess, "run", fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def crop_dims(self, box, pad=8):
        x, y, w, h = box
        left, top = max(0, x - pad), max(0, y - pad)
        return w + (x - left) + pad, h + (y - top) + pad

    def make_frame(self, box, inside_rgb, border_rgb, pad=8):
        x, y, w, h = box
        left, top = max(0, x - pad), max(0, y - pad)
        cw, ch = self.crop_dims(box, pad)
        ix, iy = x - left, y - top
        buf = bytearray()
        for py in range(ch):
            for px in range(cw):
                buf += bytes(inside_rgb if (ix <= px < ix + w and iy <= py < iy + h) else border_rgb)
        return bytes(buf)

    def test_uniform_frame_is_no_occlusion(self) -> None:
        box = (10, 10, 20, 20)
        self.raw_frames = [self.make_frame(box, (100, 100, 100), (100, 100, 100))]
        result = self.slverse.detect_delogo_occlusion("source.mp4", box, 0.0, 10.0, samples=1)
        self.assertIsNone(result)

    def test_strongly_deviating_inside_is_occlusion(self) -> None:
        box = (10, 10, 20, 20)
        self.raw_frames = [self.make_frame(box, (220, 180, 150), (100, 100, 100))]
        result = self.slverse.detect_delogo_occlusion("source.mp4", box, 0.0, 10.0, samples=1)
        self.assertIsNotNone(result)
        occ_start, occ_end = result
        self.assertGreaterEqual(occ_start, 0.0)
        self.assertLessEqual(occ_end, 10.0)
        self.assertLess(occ_start, occ_end)

    def test_localizes_to_the_hit_samples_not_the_whole_window(self) -> None:
        # 10 samples over a 20s window (2s apart); only samples 4-6
        # (centered ~9s, ~11s, ~13s - enough to clear the samples//3 hit
        # threshold) show the deviation - the returned range should bracket
        # just those, padded by one sample step, not the full 0..20 window.
        box = (10, 10, 20, 20)
        border, inside = (100, 100, 100), (220, 180, 150)
        self.raw_frames = [
            self.make_frame(box, inside if i in (4, 5, 6) else border, border)
            for i in range(10)
        ]
        occ_start, occ_end = self.slverse.detect_delogo_occlusion("source.mp4", box, 0.0, 20.0, samples=10)
        self.assertGreater(occ_start, 0.0)
        self.assertLess(occ_end, 20.0)
        self.assertLess(occ_end - occ_start, 20.0)

    def test_end_before_start_returns_none_without_probing(self) -> None:
        self.raw_frames = []  # a probe call here would raise IndexError - proving none happened
        result = self.slverse.detect_delogo_occlusion("source.mp4", (10, 10, 20, 20), 10.0, 5.0)
        self.assertIsNone(result)

    def test_subprocess_failure_returns_none(self) -> None:
        def raising_run(cmd, check=True, capture_output=True, timeout=None):
            raise TimeoutError("ffmpeg hung")
        with mock.patch.object(self.slverse.subprocess, "run", raising_run):
            result = self.slverse.detect_delogo_occlusion("source.mp4", (10, 10, 20, 20), 0.0, 10.0, samples=1)
        self.assertIsNone(result)

    def test_wrong_sized_payload_is_skipped_not_crashed(self) -> None:
        self.raw_frames = [b"\x00" * 3]  # far too short for the requested crop
        result = self.slverse.detect_delogo_occlusion("source.mp4", (10, 10, 20, 20), 0.0, 10.0, samples=1)
        self.assertIsNone(result)


class SlverseShrinkBoxForInpaintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_shrinks_by_configured_padding_around_center(self) -> None:
        box = (88, 49, 240, 60)
        config = {"delogo_width_pad": "10", "delogo_height_pad": "10"}
        self.assertEqual(self.slverse.shrink_box_for_inpaint(box, config), (93, 54, 230, 50))

    def test_never_shrinks_below_one_pixel(self) -> None:
        box = (10, 10, 4, 4)
        config = {"delogo_width_pad": "50", "delogo_height_pad": "50"}
        x, y, w, h = self.slverse.shrink_box_for_inpaint(box, config)
        self.assertGreaterEqual(w, 1)
        self.assertGreaterEqual(h, 1)


class SlverseExtractVerseInpaintTest(unittest.TestCase):
    """extract_verse's delogo_engine=auto/inpaint branch, delegating to the
    sibling ffinpaint tool - previously untested (only ffinpaint's own
    mask/config were covered). Also locks in two fixes: only the detected
    occlusion sub-range (not the whole verse window) goes to the AI
    backend, composited back over a cheap full-window blur; and the final
    encode pulls audio from the original source (input 0 here, not the
    inpainted intermediate, which is video-only) rather than dropping it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        self.run_calls = []
        self.slverse.run_ffmpeg = lambda cmd, duration=None: self.run_calls.append(cmd)
        self.slverse.build_overlay_filter = lambda *a, **k: "delogo=x=88:y=49:w=240:h=60:show=0,drawtext=text='Psalm'"
        # No localized sub-range by default (forced delogo_engine=inpaint
        # falls back to the full window) - individual tests override this
        # to exercise auto-mode's detect-then-narrow path.
        self.slverse.detect_delogo_occlusion = lambda source, box, start, end: None

    def config(self, **overrides):
        cfg = {"interpolation_engine": "none", "delogo_engine": "inpaint", "delogo_inpaint_fallback": "blur",
               "delogo_width_pad": "10", "delogo_height_pad": "10"}
        cfg.update(overrides)
        return cfg

    def fake_ffinpaint(self, inpaint_result=True, calls=None):
        calls = self.inpaint_calls if calls is None else calls
        def fake_inpaint(source, output, box, cfg, start=None, end=None):
            calls.append((source, output, box, start, end))
            return inpaint_result
        return argparse.Namespace(inpaint=fake_inpaint, load_config=lambda: {})

    def extract(self, **config_overrides):
        self.slverse.extract_verse(
            "http://example/vid.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL",
            self.config(**config_overrides),
        )

    def test_inpaint_uses_shrunk_box_and_full_window_when_unlocalized(self) -> None:
        self.inpaint_calls = []
        self.slverse.load_ffinpaint = lambda: self.fake_ffinpaint(True)
        self.slverse.has_audio_stream = lambda source: False
        self.extract()
        self.assertEqual(len(self.inpaint_calls), 1)
        source, output, box, start, end = self.inpaint_calls[0]
        self.assertEqual(box, (93, 54, 230, 50))  # shrunk from (88,49,240,60) by delogo_width/height_pad
        self.assertEqual((start, end), (10.0, 20.0))  # no localized range - full window

    def test_auto_engine_narrows_to_the_occlusion_sub_range(self) -> None:
        self.inpaint_calls = []
        self.slverse.load_ffinpaint = lambda: self.fake_ffinpaint(True)
        self.slverse.has_audio_stream = lambda source: False
        self.slverse.detect_delogo_occlusion = lambda source, box, start, end: (13.0, 15.0)
        self.extract(delogo_engine="auto")
        self.assertEqual(len(self.inpaint_calls), 1)
        _, _, _, start, end = self.inpaint_calls[0]
        self.assertEqual((start, end), (13.0, 15.0))  # only the sub-range, not 10.0..20.0

    def test_composite_filtergraph_shape(self) -> None:
        self.inpaint_calls = []
        self.slverse.load_ffinpaint = lambda: self.fake_ffinpaint(True)
        self.slverse.has_audio_stream = lambda source: True
        self.slverse.detect_delogo_occlusion = lambda source, box, start, end: (13.0, 15.0)
        self.extract(delogo_engine="auto")
        cmd = self.run_calls[0]
        # Input 0 is the plain trimmed source (also where audio comes from -
        # the inpainted intermediate is video-only); input 1 is the short
        # inpainted patch.
        self.assertEqual(cmd[:6], ["-ss", "10.0", "-to", "20.0", "-i", "http://example/vid.mp4"])
        self.assertIn("-filter_complex", cmd)
        fc = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[1:v]setpts=PTS+3.000/TB[patch]", fc)  # 13.0 - 10.0 (start_time)
        self.assertIn("delogo=x=88:y=49:w=240:h=60:show=0", fc)  # blur uses the ORIGINAL (un-shrunk) box
        self.assertIn("between(t\\,3.000\\,5.000)", fc)  # rel_start=3, rel_end=5
        self.assertIn("drawtext=text='Psalm'", fc)  # replacement label still drawn on top
        self.assertIn("-map", cmd)
        self.assertIn("0:a", cmd)
        self.assertIn("-c:a", cmd)
        self.assertIn("copy", cmd)

    def test_inpaint_failure_falls_back_to_blur(self) -> None:
        self.inpaint_calls = []
        self.slverse.load_ffinpaint = lambda: self.fake_ffinpaint(False)
        self.slverse.has_audio_stream = lambda source: False
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.extract()
        self.assertIn("using the normal delogo blur", out.getvalue())
        self.assertEqual(len(self.run_calls), 1)
        self.assertIn("delogo=", " ".join(self.run_calls[0]))  # fell through to the plain overlay path
        self.assertNotIn("-filter_complex", self.run_calls[0])

    def test_inpaint_fallback_error_raises(self) -> None:
        self.inpaint_calls = []
        self.slverse.load_ffinpaint = lambda: self.fake_ffinpaint(False)
        self.slverse.has_audio_stream = lambda source: False
        with self.assertRaises(RuntimeError):
            self.extract(delogo_inpaint_fallback="error")

    def test_blur_engine_never_loads_ffinpaint_or_detects(self) -> None:
        loaded = []
        self.slverse.load_ffinpaint = lambda: loaded.append(True)
        self.slverse.detect_delogo_occlusion = lambda *a: loaded.append("detect")
        self.slverse.has_audio_stream = lambda source: False
        self.extract(delogo_engine="blur")
        self.assertEqual(loaded, [])

    def test_auto_engine_only_inpaints_when_occlusion_detected(self) -> None:
        self.inpaint_calls = []
        self.slverse.load_ffinpaint = lambda: self.fake_ffinpaint(True)
        self.slverse.has_audio_stream = lambda source: False
        self.slverse.detect_delogo_occlusion = lambda source, box, start, end: None
        self.extract(delogo_engine="auto")
        self.assertEqual(self.inpaint_calls, [])
        self.assertIn("delogo=", " ".join(self.run_calls[0]))  # blur, not inpaint

        self.slverse.detect_delogo_occlusion = lambda source, box, start, end: (13.0, 15.0)
        self.extract(delogo_engine="auto")
        self.assertEqual(len(self.inpaint_calls), 1)


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
        def render(source, root, config, **kwargs):
            frames = Path(root) / "out"
            frames.mkdir(parents=True)
            ffrife_calls.append((source, kwargs))
            return frames, kwargs["fps"], 5.0
        fake_ffrife = argparse.Namespace(
            render_rife_frames=render,
            load_config=lambda: {"rife_binary_path": "/fake/rife"},
            command_exists=lambda path: True,
            probe_source_fps=lambda source: 30.0,
        )
        self.slverse.load_ffrife = lambda: fake_ffrife
        self.slverse.run_ffmpeg = lambda cmd, duration=None: piece_ffmpeg_calls.append(cmd)
        config = {"interpolation_engine": "rife", "default_target_lang": "FSL", "interpolation_target_fps": "60"}

        self.slverse.extract_verse_sections(
            "http://example/vid.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config,
            "slow", [5.0], 0.5,
        )

        # With whole-clip RIFE enabled, both pieces are interpolated so the
        # final concat has one real 60fps cadence; only piece 2 is retimed.
        self.assertEqual(len(ffrife_calls), 2)
        _, kwargs = ffrife_calls[1]
        self.assertEqual(kwargs["start"], 15.0)  # 10.0 + boundary 5.0
        self.assertEqual(kwargs["end"], 20.0)
        self.assertEqual(kwargs["speed"], 0.5)
        self.assertEqual(kwargs["fps"], 60.0)  # the flat configured interpolation_target_fps, not a source-fps multiple
        self.assertEqual(len(piece_ffmpeg_calls), 1)  # one final encode only
        fc = piece_ffmpeg_calls[0][piece_ffmpeg_calls[0].index("-filter_complex") + 1]
        self.assertIn("settb=AVTB,setpts=PTS-STARTPTS", fc)
        self.assertNotIn("fps=", fc)

    def test_slow_smoothing_uses_rife_without_whole_clip_interpolation(self) -> None:
        ffrife_calls = []
        ffmpeg_calls = []
        def render(source, root, config, **kwargs):
            frames = Path(root) / "out"
            frames.mkdir(parents=True)
            ffrife_calls.append((source, kwargs))
            return frames, kwargs["fps"], 10.0
        fake_ffrife = argparse.Namespace(
            render_rife_frames=render,
            load_config=lambda: {"rife_binary_path": "/fake/rife"},
            command_exists=lambda path: True,
            probe_source_fps=lambda source: 30000 / 1001,
        )
        self.slverse.load_ffrife = lambda: fake_ffrife
        self.slverse.run_ffmpeg = lambda cmd, duration=None: ffmpeg_calls.append(cmd)
        config = {"interpolation_engine": "none", "_interpolation_engine_preference": "rife", "smooth_slow_motion": "true"}

        self.slverse.extract_verse_sections(
            "source.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config,
            "slow", [5.0], 0.5,
        )

        self.assertEqual(len(ffrife_calls), 1)
        self.assertAlmostEqual(ffrife_calls[0][1]["fps"], 30000 / 1001)
        self.assertEqual(ffrife_calls[0][1]["speed"], 0.5)
        self.assertEqual(len(ffmpeg_calls), 1)  # normal section is a direct input to the final encode
        final_fc = ffmpeg_calls[-1][ffmpeg_calls[-1].index("-filter_complex") + 1]
        self.assertIn("settb=AVTB", final_fc)
        self.assertIn("fps=29.97", final_fc)


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

    def test_load_ffrife_syncs_color_so_its_headers_are_not_silently_plain(self) -> None:
        # ffrife.COLOR is only ever set by ffrife's own main(), which this
        # library usage never calls - without this sync it stays permanently
        # disabled and every header/progress bar ffrife prints (even the
        # ones already existing before this test, like the "Done" checkmark)
        # would come out uncolored regardless of slverse's own setting.
        sentinel = self.slverse._jwkit_common.Colorizer(True)
        self.slverse.COLOR = sentinel
        ffrife = self.slverse.load_ffrife()
        self.assertIs(ffrife.COLOR, sentinel)

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
        self.assertEqual(bridged["scene_detection"], "false")

    def test_slverse_can_enable_rife_scene_detection_for_one_run(self) -> None:
        self.assertIn("rife_scene_detection", self.slverse.BOOLEAN_CONFIG_KEYS)
        parser = argparse.ArgumentParser()
        self.slverse.add_generic_config_overrides(parser)
        args = parser.parse_args(["--rife-scene-detection"])
        config = dict(self.slverse.DEFAULT_CONFIG)
        self.slverse.apply_generic_config_overrides(args, config)
        self.assertEqual(config["rife_scene_detection"], "true")
        bridged = self.slverse.ffrife_config_for({"rife_scene_detection": "true"})
        self.assertEqual(bridged["scene_detection"], "true")

    def test_extract_verse_rife_engine_delegates_to_ffrife(self) -> None:
        calls = []
        fake_ffrife = argparse.Namespace(
            interpolate=lambda *a, **k: calls.append((a, k)),
            load_config=lambda: {},
        )
        self.slverse.load_ffrife = lambda: fake_ffrife
        self.slverse.build_overlay_filter = lambda *a, **k: "drawtext=text='stub'"  # font/measure logic covered elsewhere
        # ffrife.interpolate() now probes the source's own fps itself and
        # computes the exact frame count to hit the flat configured target -
        # extract_verse just passes interpolation_target_fps straight through.
        config = {"interpolation_engine": "rife", "default_target_lang": "FSL", "interpolation_target_fps": "50"}

        self.slverse.extract_verse("http://example/vid.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config, remote=True)

        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], "http://example/vid.mp4")
        self.assertEqual(args[1], "out.mp4")
        self.assertEqual(kwargs["start"], 10.0)
        self.assertEqual(kwargs["end"], 20.0)
        self.assertEqual(kwargs["output_vf"], "drawtext=text='stub'")
        self.assertNotIn("vf", kwargs)
        self.assertEqual(kwargs["fps"], 50.0)

    def test_rife_mid_transition_cuts_use_lossless_section_pipeline(self) -> None:
        calls = []
        fake_ffrife = argparse.Namespace(load_config=lambda: {})
        self.slverse.load_ffrife = lambda: fake_ffrife
        self.slverse.ffrife_config_for = lambda config: {"rife_binary_path": "/fake/rife"}
        self.slverse.build_overlay_filter = lambda *a, **k: None
        self.slverse.encode_rife_frame_sections = lambda *a, **k: calls.append((a, k))
        config = {"interpolation_engine": "rife", "interpolation_target_fps": "60"}

        self.slverse.extract_verse(
            "source.mp4", "out.mp4", 10.0, 20.0, "Psalm", 16, "11", "ASL", config,
            kept_segments=[(0.0, 4.0), (6.0, 10.0)],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][2], [(10.0, 14.0, None, True), (16.0, 20.0, None, True)])
        self.assertEqual(calls[0][0][3], 60.0)


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

    def test_configured_mpv_options_are_split_into_individual_flags(self) -> None:
        options = "--no-config --speed=1.0 --no-native-fs --fs --no-border --ontop --no-keep-open --screen=1"
        self.slverse.launch_mpv(["file.mp4"], config={"mpv_options": options})
        cmd = self.captured_cmd[0]
        self.assertEqual(cmd[-9:-1], options.split())
        self.assertEqual(cmd[-1], "file.mp4")

    def test_mpv_options_loaded_from_config_file_reach_mpv_unchanged(self) -> None:
        options = "--no-config --speed=1.0 --no-native-fs --fs --no-border --ontop --no-keep-open --screen=1"
        with tempfile.TemporaryDirectory() as td:
            self.slverse.CONFIG_FILE = Path(td) / "config.toml"
            self.slverse.CONFIG_FILE.write_text(f'mpv_options = "{options}"\n')
            self.slverse.launch_mpv(["file.mp4"], config=self.slverse.load_config())
        self.assertEqual(self.captured_cmd[0][-9:-1], options.split())

    def test_rich_text_outer_quotes_do_not_become_part_of_mpv_flags(self) -> None:
        self.assertEqual(self.slverse.parse_mpv_options("“--fs --screen=1”"), ["--fs", "--screen=1"])

    def test_overlay_free_preview_plays_source_without_temp_encode(self) -> None:
        self.slverse.command_exists = lambda name: True
        self.slverse.detect_caption_box = lambda *a, **k: None
        self.slverse.build_overlay_filter = lambda *a, **k: None
        self.slverse.run_ffmpeg = lambda *a, **k: self.fail("overlay-free preview must not encode")

        self.slverse.preview_verse("source.mp4", 10.0, 15.0, "Psalm", 16, "11", "FSL", {}, use_mpv=True)

        cmd = self.captured_cmd[0]
        self.assertIn("--start=10.0", cmd)
        self.assertIn("--length=5.0", cmd)
        self.assertEqual(cmd[-1], "source.mp4")

    def test_overlay_preview_keeps_compatible_external_ffmpeg_encode(self) -> None:
        self.slverse.command_exists = lambda name: True
        self.slverse.detect_caption_box = lambda *a, **k: None
        self.slverse.build_overlay_filter = lambda *a, **k: "drawtext=text='ASL'"
        ffmpeg_calls = []
        self.slverse.run_ffmpeg = lambda cmd, duration=None: ffmpeg_calls.append(cmd)

        self.slverse.preview_verse("source.mp4", 10.0, 15.0, "Psalm", 16, "11", "ASL", {}, use_mpv=True)

        self.assertEqual(len(ffmpeg_calls), 1)
        self.assertEqual(ffmpeg_calls[0][ffmpeg_calls[0].index("-vf") + 1], "drawtext=text='ASL'")
        self.assertIn("ultrafast", ffmpeg_calls[0])

class SlverseAddToPathProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_windows_skips_writing_dot_profile(self) -> None:
        # ~/.profile isn't sourced by cmd.exe/PowerShell - writing it there
        # used to silently claim success with no real effect on Windows.
        with tempfile.TemporaryDirectory() as home_dir:
            with mock.patch.object(self.slverse.platform, "system", return_value="Windows"), \
                 mock.patch.object(self.slverse.Path, "home", return_value=Path(home_dir)), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.slverse.add_to_path_profile()
            self.assertFalse((Path(home_dir) / ".profile").exists())
            self.assertIn("install.ps1", out.getvalue())

    def test_macos_still_writes_dot_profile(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            with mock.patch.object(self.slverse.platform, "system", return_value="Darwin"), \
                 mock.patch.object(self.slverse.Path, "home", return_value=Path(home_dir)), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                self.slverse.add_to_path_profile()
            profile = Path(home_dir) / ".profile"
            self.assertTrue(profile.exists())
            self.assertIn("PATH", profile.read_text())


class SlverseCacheMaxSizeMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.slverse = load_script_module("slverse")

    def test_migrates_old_gb_value_to_binary_gi(self) -> None:
        # cache_max_gb's old semantics were binary GiB (max_gb * 1024**3),
        # not decimal - the migrated value must stay byte-equivalent.
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "config.toml"
            cfg_file.write_text('cache_max_gb = "10"\n')
            self.slverse.CONFIG_FILE = cfg_file
            config = self.slverse.load_config()
        self.assertEqual(config["cache_max_size"], "10Gi")
        self.assertNotIn("cache_max_gb", config)

    def test_migration_persists_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "config.toml"
            cfg_file.write_text('cache_max_gb = "5"\n')
            self.slverse.CONFIG_FILE = cfg_file
            self.slverse.load_config()
            self.assertIn('cache_max_size = "5Gi"', cfg_file.read_text())
            self.assertNotIn("cache_max_gb", cfg_file.read_text())

    def test_explicit_cache_max_size_in_file_wins_over_migration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "config.toml"
            cfg_file.write_text('cache_max_gb = "10"\ncache_max_size = "2G"\n')
            self.slverse.CONFIG_FILE = cfg_file
            config = self.slverse.load_config()
        self.assertEqual(config["cache_max_size"], "2G")

    def test_no_migration_when_no_legacy_key_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "config.toml"
            cfg_file.write_text('languages = "ASL,FSL"\n')
            self.slverse.CONFIG_FILE = cfg_file
            config = self.slverse.load_config()
        self.assertEqual(config["cache_max_size"], self.slverse.DEFAULT_CONFIG["cache_max_size"])


class SlverseEnforceCacheBudgetSizeUnitsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_respects_decimal_and_binary_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache" / "ASL"
            cache_dir.mkdir(parents=True)
            p = cache_dir / "a.mp4"
            p.write_bytes(b"0" * (2 * 1000 * 1000))  # 2,000,000 bytes
            state: dict = {}
            # 2M (decimal, 2,000,000 bytes) - exactly at budget, nothing evicted
            config = {"cache_dir": str(cache_dir.parent), "cache_policy": "lru", "cache_max_size": "2M"}
            self.slverse.enforce_cache_budget(config, state)
            self.assertTrue(p.exists())

            # 1900000 bytes (bare number) - under the file's actual size, evicted
            config["cache_max_size"] = "1900000"
            self.slverse.enforce_cache_budget(config, state)
            self.assertFalse(p.exists())


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
        args = argparse.Namespace(key="cache_max_size", value=None)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.slverse.cmd_config(args, dict(self.slverse.DEFAULT_CONFIG))
        output = out.getvalue()
        self.assertIn("cache_max_size = 1G", output)
        self.assertIn("Cache size cap", output)

    def test_config_set_updates_and_saves(self) -> None:
        args = argparse.Namespace(key="cache_max_size", value="10G")
        saved = {}
        self.slverse.save_config = lambda config: saved.update(config)
        config = dict(self.slverse.DEFAULT_CONFIG)
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.slverse.cmd_config(args, config)
        self.assertEqual(config["cache_max_size"], "10G")
        self.assertEqual(saved["cache_max_size"], "10G")

    def test_config_set_rejects_a_typo_in_a_closed_set_key(self) -> None:
        # cache_policy is compared against exact strings elsewhere
        # (config.get("cache_policy") == "lru") - a typo used to be
        # accepted and saved silently, then just never matched anything.
        args = argparse.Namespace(key="cache_policy", value="lur")
        saved = {}
        self.slverse.save_config = lambda config: saved.update(config)
        config = dict(self.slverse.DEFAULT_CONFIG)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.slverse.cmd_config(args, config)
        self.assertEqual(config["cache_policy"], "lru")  # unchanged
        self.assertEqual(saved, {})  # never persisted
        self.assertIn("must be one of", out.getvalue())

    def test_config_set_accepts_a_closed_set_value_case_insensitively(self) -> None:
        args = argparse.Namespace(key="delogo_engine", value="INPAINT")
        self.slverse.save_config = lambda config: None
        config = dict(self.slverse.DEFAULT_CONFIG)
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            self.slverse.cmd_config(args, config)
        self.assertEqual(config["delogo_engine"], "INPAINT")


class SlverseGenericConfigOverrideValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_free_form_key_accepts_anything(self) -> None:
        self.assertIsNone(self.slverse.validate_config_value("cache_max_size", "not-a-number-but-not-this-functions-job"))

    def test_closed_set_key_rejects_unknown_value(self) -> None:
        error = self.slverse.validate_config_value("cache_policy", "lur")
        self.assertIsNotNone(error)
        self.assertIn("cache_policy", error)

    def test_generic_cli_override_of_a_closed_set_key_with_a_typo_exits_cleanly(self) -> None:
        args = argparse.Namespace(delogo_engine="blurr")
        config = dict(self.slverse.DEFAULT_CONFIG)
        with self.assertRaises(SystemExit) as ctx:
            self.slverse.apply_generic_config_overrides(args, config)
        self.assertIn("delogo-engine", str(ctx.exception))
        self.assertEqual(config["delogo_engine"], "blur")  # untouched by the rejected override

    def test_generic_cli_override_of_a_closed_set_key_with_a_valid_value_applies(self) -> None:
        args = argparse.Namespace(delogo_engine="inpaint")
        config = dict(self.slverse.DEFAULT_CONFIG)
        self.slverse.apply_generic_config_overrides(args, config)
        self.assertEqual(config["delogo_engine"], "inpaint")


class SlverseEditDescriptionTest(unittest.TestCase):
    """Output metadata titles need to actually distinguish different edits
    of the same verse (see extract_one_lang/output_metadata_args) - a
    controller looking at a pile of clips by title alone can't tell two
    different --window cuts apart if both just say '(custom cut)'."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def args(self, **overrides):
        base = dict(clip_window=None, offset_start=None, offset_end=None, keep_end_transition=False, trim_mid_transitions=False)
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_no_edit_produces_no_bits(self) -> None:
        self.assertEqual(self.slverse.describe_cut_edit(self.args()), [])

    def test_different_windows_produce_different_bits(self) -> None:
        a = self.slverse.describe_cut_edit(self.args(clip_window=(3.567, 10.003)))
        b = self.slverse.describe_cut_edit(self.args(clip_window=(2.0, 8.0)))
        self.assertNotEqual(a, b)
        self.assertEqual(a, ["cut 3.567-10.003s"])
        self.assertEqual(b, ["cut 2-8s"])

    def test_different_offsets_produce_different_bits(self) -> None:
        a = self.slverse.describe_cut_edit(self.args(offset_start=5.302))
        b = self.slverse.describe_cut_edit(self.args(offset_start=-2))
        c = self.slverse.describe_cut_edit(self.args(offset_end=-3))
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(a, ["cut s+5.302s"])
        self.assertEqual(c, ["cut e-3s"])

    def test_window_takes_precedence_over_offsets_if_both_present(self) -> None:
        bits = self.slverse.describe_cut_edit(self.args(clip_window=(3.0, 9.0), offset_start=99))
        self.assertEqual(bits, ["cut 3-9s"])

    def test_transition_edit_bit_still_present_for_the_editing_metadata_field(self) -> None:
        bits = self.slverse.describe_cut_edit(self.args(keep_end_transition=True))
        self.assertIn("transition edit", bits)

    def test_different_retime_boundaries_produce_different_descriptions(self) -> None:
        a = self.slverse.describe_retime_edit("slow", [3, 5], 0.5)
        b = self.slverse.describe_retime_edit("slow", [2, 8], 0.5)
        self.assertNotEqual(a, b)
        self.assertEqual(a, "slow motion 0.5x@3-5s")

    def test_no_mode_returns_none(self) -> None:
        self.assertIsNone(self.slverse.describe_retime_edit(None, None, None))

    def test_full_title_omits_transition_edit_but_keeps_it_in_editing_field(self) -> None:
        # Mirrors extract_one_lang's own title_edit/edit_note split.
        bits = self.slverse.describe_cut_edit(self.args(clip_window=(3.0, 9.0), keep_end_transition=True))
        title_edit = "; ".join(b for b in bits if b != "transition edit")
        edit_note = "; ".join(bits)
        self.assertEqual(title_edit, "cut 3-9s")
        self.assertIn("transition edit", edit_note)


class SlverseGenericConfigOverrideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_every_non_excluded_key_gets_a_flag(self) -> None:
        parser = argparse.ArgumentParser()
        self.slverse.add_generic_config_overrides(parser)
        dests = {action.dest for action in parser._actions}
        expected = set(self.slverse.DEFAULT_CONFIG) - self.slverse.GENERIC_OVERRIDE_EXCLUDED_KEYS
        self.assertTrue(expected.issubset(dests))

    def test_excluded_keys_have_no_generic_flag(self) -> None:
        # These already have a dedicated, differently-shaped flag
        # (--encoder/--codec/--keep-end-transition/etc.) - a second one
        # would be a confusing duplicate, not a bug fix.
        parser = argparse.ArgumentParser()
        self.slverse.add_generic_config_overrides(parser)
        dests = {action.dest for action in parser._actions}
        self.assertEqual(dests & self.slverse.GENERIC_OVERRIDE_EXCLUDED_KEYS, set())

    def test_apply_overrides_only_provided_values(self) -> None:
        parser = argparse.ArgumentParser()
        self.slverse.add_generic_config_overrides(parser)
        args = parser.parse_args(["--delogo-engine", "inpaint", "--overlay-x", "100"])
        config = dict(self.slverse.DEFAULT_CONFIG)
        original_alpha = config["overlay_alpha"]
        self.slverse.apply_generic_config_overrides(args, config)
        self.assertEqual(config["delogo_engine"], "inpaint")
        self.assertEqual(config["overlay_x"], "100")
        self.assertEqual(config["overlay_alpha"], original_alpha)  # untouched: not passed

    def test_apply_overrides_is_a_noop_for_args_without_the_dest(self) -> None:
        # Every real caller (main()) applies this once, unconditionally,
        # before command dispatch - including for subcommands (setup,
        # config, langs, sync, find, cache, inspect) whose own parsers never
        # call add_generic_config_overrides, so their args simply lack these
        # attributes. Must not raise.
        config = dict(self.slverse.DEFAULT_CONFIG)
        self.slverse.apply_generic_config_overrides(argparse.Namespace(), config)
        self.assertEqual(config, self.slverse.DEFAULT_CONFIG)


class SlverseExtractCliParsingTest(unittest.TestCase):
    """Interpolation enablement and engine selection stay independent."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def parse_extract_args(self, argv):
        captured = {}
        self.slverse.cmd_extract = lambda args, config: captured.update(vars(args))
        self.slverse.maybe_auto_sync = lambda args, config: None  # no real sync/network for a CLI-parsing test
        original_argv = sys.argv
        self.addCleanup(setattr, sys, "argv", original_argv)
        sys.argv = ["slverse", "extract"] + argv
        self.slverse.main()
        return captured

    def test_short_I_flag_sets_interpolation_engine(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "-I", "none"])
        self.assertEqual(args["interpolation_engine"], "none")
        self.assertIsNone(args["interpolate"])  # use saved preference

    def test_long_interpolation_engine_flag_still_works(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "--interpolation-engine", "rife"])
        self.assertEqual(args["interpolation_engine"], "rife")

    def test_lowercase_i_flag_is_the_unrelated_boolean(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "-i"])
        self.assertTrue(args["interpolate"])
        self.assertIsNone(args["interpolation_engine"])

    def test_no_interpolate_forces_boolean_off(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "--no-interpolate"])
        self.assertFalse(args["interpolate"])

    def test_short_trim_flags_take_unsigned_amounts(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "-s", "2.5", "-e", "8.909"])
        self.assertEqual(args["trim_start"], 2.5)
        self.assertEqual(args["trim_end"], 8.909)

    def test_old_negative_short_end_trim_still_parses(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "-e", "-8.909"])
        self.assertEqual(args["trim_end"], -8.909)

    def test_smooth_slow_motion_has_per_run_boolean_override(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "--no-smooth-slow-motion"])
        self.assertFalse(args["smooth_slow_motion"])

    def test_output_implies_write(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "-o", "clip.mp4"])
        self.assertTrue(args["write"])

    def test_source_modes_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            self.parse_extract_args(["asl", "1", "Timothy", "1:11", "--cache", "--segment"])

    def test_saved_false_disables_rife_without_persisting(self) -> None:
        config = {"interpolate": "false", "interpolation_engine": "rife"}
        enabled = self.slverse.apply_interpolation_overrides(
            argparse.Namespace(interpolate=None, interpolation_engine=None), config,
        )
        self.assertFalse(enabled)
        self.assertEqual(config["interpolation_engine"], "none")

    def test_cli_interpolate_enables_saved_rife(self) -> None:
        config = {"interpolate": "false", "interpolation_engine": "rife"}
        enabled = self.slverse.apply_interpolation_overrides(
            argparse.Namespace(interpolate=True, interpolation_engine=None), config,
        )
        self.assertTrue(enabled)
        self.assertEqual(config["interpolation_engine"], "rife")

    def test_main_passes_none_engine_to_extract_when_saved_toggle_is_false(self) -> None:
        effective = {}
        config = dict(self.slverse.DEFAULT_CONFIG, interpolate="false", interpolation_engine="rife")
        original_argv = sys.argv
        self.addCleanup(setattr, sys, "argv", original_argv)
        sys.argv = ["slverse", "extract", "ASL", "1", "Timothy", "1:11", "-f"]
        with mock.patch.object(self.slverse, "load_config", return_value=config), \
             mock.patch.object(self.slverse, "maybe_auto_sync"), \
             mock.patch.object(self.slverse, "cmd_extract", side_effect=lambda args, cfg: effective.update(cfg)):
            self.slverse.main()
        self.assertEqual(effective["interpolate"], "false")
        self.assertEqual(effective["interpolation_engine"], "none")

    def test_segment_flag_is_parsed(self) -> None:
        args = self.parse_extract_args(["asl", "1", "Timothy", "1:11", "--segment"])
        self.assertTrue(args["segment"])


if __name__ == "__main__":
    unittest.main()
