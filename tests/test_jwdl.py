from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests.support import load_script_module


class JwdlTitleFormattingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_apostrophe_becomes_curly(self) -> None:
        self.assertEqual(self.jwdl.format_title("Don't Run So Fast"), "Don’t Run So Fast")

    def test_leading_and_trailing_quotes_become_curly(self) -> None:
        self.assertEqual(
            self.jwdl.format_title('"Fight the Fine Fight of the Faith"'),
            "“Fight the Fine Fight of the Faith”",
        )

    def test_mid_string_quote_after_period_becomes_curly(self) -> None:
        # Both the ". \"" mid-string rule and the trailing-quote rule fire here,
        # matching the original bash sed pipeline's sequential behavior.
        self.assertEqual(
            self.jwdl.format_title('Episode 2. "God\'s Declaration"'),
            "Episode 2. “God’s Declaration”",
        )

    def test_plain_title_is_unchanged(self) -> None:
        self.assertEqual(self.jwdl.format_title("Give You My All"), "Give You My All")


class JwdlSanitizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_illegal_filesystem_chars_become_underscore(self) -> None:
        self.assertEqual(self.jwdl.sanitize('Episode 2: "Foo"'), "Episode 2_ _Foo_")

    def test_safe_chars_are_left_alone(self) -> None:
        self.assertEqual(self.jwdl.sanitize("We Won’t Forget You"), "We Won’t Forget You")


class JwdlBuildFilenameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_matches_historical_naming_convention(self) -> None:
        filename = self.jwdl.build_filename(
            "https://cfp2.jw-cdn.org/a/f2a007/1/o/osg_E_516.mp3",
            "Imagine the Time",
        )
        self.assertEqual(filename, "osg_E_516 (Imagine the Time).mp3")

    def test_colon_in_title_is_sanitized(self) -> None:
        filename = self.jwdl.build_filename(
            "https://cfp2.jw-cdn.org/a/x/1/o/gnjst1_E_01.mp3",
            "Episode 1: “In the Beginning”",
        )
        self.assertEqual(filename, "gnjst1_E_01 (Episode 1_ “In the Beginning”).mp3")


class JwdlAudioDescriptionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_detects_audio_description_suffix(self) -> None:
        self.assertTrue(self.jwdl.is_audio_description("Imagine the Time (With Audio Descriptions)"))

    def test_plain_title_is_not_audio_description(self) -> None:
        self.assertFalse(self.jwdl.is_audio_description("Imagine the Time"))


class JwdlResolvePubsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_builtin_pubs_present(self) -> None:
        pubs = self.jwdl.resolve_pubs({"pubs": {}})
        self.assertEqual(pubs["imc"], "International Music")
        self.assertIn("osg", pubs)

    def test_config_pubs_extend_without_mutating_builtin(self) -> None:
        pubs = self.jwdl.resolve_pubs({"pubs": {"newcode": "New Collection"}})
        self.assertEqual(pubs["newcode"], "New Collection")
        self.assertNotIn("newcode", self.jwdl.PUBS)


class JwdlDownloadTrackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_audio_description_is_skipped_by_default(self) -> None:
        entry = {
            "title": "Imagine the Time (With Audio Descriptions)",
            "file": {"url": "https://example.com/osg_E_516.mp3"},
        }
        status, _ = self.jwdl.download_track(entry, mock.Mock(), dry_run=True, include_audio_descriptions=False)
        self.assertEqual(status, "skipped-ad")

    def test_audio_description_is_included_when_requested(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = False
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {
            "title": "Imagine the Time (With Audio Descriptions)",
            "file": {"url": "https://example.com/osg_E_516.mp3"},
            "filesize": 123,
        }
        status, _ = self.jwdl.download_track(entry, dest_dir, dry_run=True, include_audio_descriptions=True)
        self.assertEqual(status, "would-download")

    def test_non_mp3_url_is_skipped(self) -> None:
        entry = {"title": "Some Video", "file": {"url": "https://example.com/foo.mp4"}}
        status, _ = self.jwdl.download_track(entry, mock.Mock(), dry_run=True, include_audio_descriptions=False)
        self.assertEqual(status, "skipped-format")

    def test_existing_file_with_matching_size_is_skipped(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = True
        dest_path.stat.return_value = mock.Mock(st_size=42)
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {"title": "Foo", "file": {"url": "https://example.com/osg_E_1.mp3"}, "filesize": 42}
        status, _ = self.jwdl.download_track(entry, dest_dir, dry_run=True, include_audio_descriptions=False)
        self.assertEqual(status, "skipped-exists")

    def test_dry_run_reports_would_download_without_network(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = False
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {"title": "Foo", "file": {"url": "https://example.com/osg_E_1.mp3"}, "filesize": 42}
        with mock.patch.object(self.jwdl.urllib.request, "urlopen") as urlopen:
            status, detail = self.jwdl.download_track(entry, dest_dir, dry_run=True, include_audio_descriptions=False)
            urlopen.assert_not_called()
        self.assertEqual(status, "would-download")
        self.assertEqual(detail, "osg_E_1 (Foo).mp3")


class JwdlListCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_list_includes_all_marker_and_known_pub(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.jwdl.cmd_list(self.jwdl.resolve_pubs({"pubs": {}}))
        output = stdout.getvalue()
        self.assertIn("imc", output)
        self.assertIn("all", output)


class JwdlIssueRangeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_length_matches_months_requested(self) -> None:
        self.assertEqual(len(self.jwdl.issue_range(5)), 5)

    def test_each_issue_is_six_digit_yyyymm(self) -> None:
        for issue in self.jwdl.issue_range(3):
            self.assertRegex(issue, r"^\d{6}$")

    def test_issues_are_sequential_months_no_duplicates(self) -> None:
        issues = self.jwdl.issue_range(14)  # long enough to cross a year boundary
        self.assertEqual(issues, sorted(set(issues)))
        for prev, cur in zip(issues, issues[1:]):
            py, pm = int(prev[:4]), int(prev[4:])
            cy, cm = int(cur[:4]), int(cur[4:])
            expected = (py, pm + 1) if pm < 12 else (py + 1, 1)
            self.assertEqual((cy, cm), expected)


class JwdlPeriodicalsListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_list_includes_all_marker_and_known_codes(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.jwdl.cmd_periodicals_list()
        output = stdout.getvalue()
        self.assertIn("w", output)
        self.assertIn("mwb", output)
        self.assertIn("all", output)

    def test_discontinued_periodicals_are_not_offered(self) -> None:
        # jw.org's pub-media API 404s on both regardless of issue - they
        # were discontinued as separate monthly periodicals years ago, so
        # jwget's other two pub codes were deliberately not ported.
        self.assertNotIn("wp", self.jwdl.PERIODICALS)
        self.assertNotIn("g", self.jwdl.PERIODICALS)


class JwdlDownloadPeriodicalFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_large_print_is_skipped_by_default(self) -> None:
        entry = {"format": "lp", "editionDescr": "Large Print", "file": {"url": "https://example.com/w_lp_E_202601.pdf"}}
        status, _ = self.jwdl.download_periodical_file(entry, mock.Mock(), dry_run=True, include_large_print=False)
        self.assertEqual(status, "skipped-lp")

    def test_large_print_is_included_when_requested(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = False
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {"format": "lp", "file": {"url": "https://example.com/w_lp_E_202601.pdf"}, "filesize": 123}
        status, _ = self.jwdl.download_periodical_file(entry, dest_dir, dry_run=True, include_large_print=True)
        self.assertEqual(status, "would-download")

    def test_existing_file_with_matching_size_is_skipped(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = True
        dest_path.stat.return_value = mock.Mock(st_size=42)
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {"format": "", "file": {"url": "https://example.com/w_E_202601.pdf"}, "filesize": 42}
        status, _ = self.jwdl.download_periodical_file(entry, dest_dir, dry_run=True, include_large_print=False)
        self.assertEqual(status, "skipped-exists")

    def test_dry_run_reports_would_download_without_network(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = False
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {"format": "", "file": {"url": "https://example.com/w_E_202601.pdf"}, "filesize": 42}
        with mock.patch.object(self.jwdl.urllib.request, "urlopen") as urlopen:
            status, detail = self.jwdl.download_periodical_file(dest_dir=dest_dir, entry=entry, dry_run=True, include_large_print=False)
            urlopen.assert_not_called()
        self.assertEqual(status, "would-download")
        self.assertEqual(detail, "w_E_202601.pdf")


class JwdlFetchPeriodicalMediaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_list_response_is_treated_as_not_yet_published(self) -> None:
        # The API returns a JSON list (an error-shaped payload, same as the
        # music endpoint) for issues that don't exist yet, not a 4xx - this
        # must not be raised as an error, since 4 of 5 default months are
        # normally still unpublished at fetch time.
        response = mock.Mock()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(self.jwdl.json, "load", return_value=[{"title": "Not Found", "status": 404}]):
            with mock.patch.object(self.jwdl.urllib.request, "urlopen", return_value=response):
                files, reason = self.jwdl.fetch_periodical_media("w", "E", "209912")
        self.assertIsNone(files)
        self.assertEqual(reason, "Not Found")


class JwdlPickVideoRenditionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def setUp(self) -> None:
        # matches real jw-api.org shapes: a 3gp rendition is still labeled a
        # real resolution ("144p"), not "0p" - it's just a different mimetype
        self.files = [
            {"label": "144p", "mimetype": "video/3gpp", "progressiveDownloadURL": "https://example.com/144p.3gp"},
            {"label": "240p", "mimetype": "video/mp4", "progressiveDownloadURL": "https://example.com/240p.mp4"},
            {"label": "360p", "mimetype": "video/mp4", "progressiveDownloadURL": "https://example.com/360p.mp4"},
            {"label": "720p", "mimetype": "video/mp4", "progressiveDownloadURL": "https://example.com/720p.mp4"},
        ]

    def test_exact_match_is_preferred(self) -> None:
        picked = self.jwdl.pick_video_rendition(self.files, "360p")
        self.assertEqual(picked["label"], "360p")

    def test_falls_back_to_closest_below_when_exact_missing(self) -> None:
        picked = self.jwdl.pick_video_rendition(self.files, "480p")
        self.assertEqual(picked["label"], "360p")

    def test_falls_back_to_smallest_when_requested_is_below_everything(self) -> None:
        picked = self.jwdl.pick_video_rendition(self.files, "100p")
        self.assertEqual(picked["label"], "144p")

    def test_returns_none_when_no_video_files_present(self) -> None:
        audio_only = [{"label": "mp3", "mimetype": "audio/mpeg"}]
        self.assertIsNone(self.jwdl.pick_video_rendition(audio_only, "720p"))


class JwdlDownloadVideoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_dry_run_reports_would_download_without_network(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = False
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {
            "title": "Some Video",
            "files": [{"label": "720p", "mimetype": "video/mp4", "progressiveDownloadURL": "https://example.com/foo_r720P.mp4", "filesize": 42}],
        }
        with mock.patch.object(self.jwdl.urllib.request, "urlopen") as urlopen:
            status, detail = self.jwdl.download_video(entry, dest_dir, "720p", dry_run=True)
            urlopen.assert_not_called()
        self.assertEqual(status, "would-download")
        self.assertEqual(detail, "foo_r720P.mp4")

    def test_existing_file_with_matching_size_is_skipped(self) -> None:
        dest_dir = mock.Mock()
        dest_path = mock.Mock()
        dest_path.exists.return_value = True
        dest_path.stat.return_value = mock.Mock(st_size=42)
        dest_dir.__truediv__ = mock.Mock(return_value=dest_path)
        entry = {
            "title": "Some Video",
            "files": [{"label": "720p", "mimetype": "video/mp4", "progressiveDownloadURL": "https://example.com/foo_r720P.mp4", "filesize": 42}],
        }
        status, _ = self.jwdl.download_video(entry, dest_dir, "720p", dry_run=True)
        self.assertEqual(status, "skipped-exists")

    def test_no_matching_video_file_is_skipped(self) -> None:
        entry = {"title": "Audio Only", "files": [{"label": "mp3", "mimetype": "audio/mpeg"}]}
        status, _ = self.jwdl.download_video(entry, mock.Mock(), "720p", dry_run=True)
        self.assertEqual(status, "skipped-no-file")


class JwdlFetchVideoCategoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jwdl = load_script_module("jwdl")

    def test_404_http_error_returns_none_without_retrying(self) -> None:
        # Unlike the music/periodicals endpoints, this API 404s for real
        # instead of returning an error-shaped 200 - must be treated as
        # "unknown category" immediately, not retried 3x and crash.
        err = self.jwdl.urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        with mock.patch.object(self.jwdl.urllib.request, "urlopen", side_effect=err) as urlopen:
            result = self.jwdl.fetch_video_category("NotReal", "E")
        self.assertIsNone(result)
        urlopen.assert_called_once()

    def test_list_response_is_treated_as_not_found(self) -> None:
        response = mock.Mock()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(self.jwdl.json, "load", return_value=[{"title": "Not Found", "status": 404}]):
            with mock.patch.object(self.jwdl.urllib.request, "urlopen", return_value=response):
                result = self.jwdl.fetch_video_category("NotReal", "E")
        self.assertIsNone(result)

    def test_successful_response_returns_category_dict(self) -> None:
        response = mock.Mock()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        payload = {"category": {"key": "LatestVideos", "name": "Latest Videos", "media": []}}
        with mock.patch.object(self.jwdl.json, "load", return_value=payload):
            with mock.patch.object(self.jwdl.urllib.request, "urlopen", return_value=response):
                result = self.jwdl.fetch_video_category("LatestVideos", "E")
        self.assertEqual(result["name"], "Latest Videos")


if __name__ == "__main__":
    unittest.main()
