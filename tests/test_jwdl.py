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


if __name__ == "__main__":
    unittest.main()
