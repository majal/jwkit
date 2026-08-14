import importlib.util
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "jwpl"
SPEC = importlib.util.spec_from_loader("jwpl_under_test", SourceFileLoader("jwpl_under_test", str(MODULE_PATH)))
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class JwplTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_discover_media_natural_sort_and_filters(self):
        for name in ("10.jpg", "2.jpg", "1.jpg", "ignore.png", ".DS_Store"):
            (self.root / name).write_bytes(b"x")
        settings = {**module.DEFAULTS, "include": ["*.jpg"], "exclude": ["ignore*"]}
        self.assertEqual([p.name for p in module.discover_media(self.root, settings)], ["1.jpg", "2.jpg", "10.jpg"])

    def test_create_archive_has_valid_manifest_schema_and_order(self):
        for name in ("02 second.jpg", "01 first.jpg"):
            (self.root / name).write_bytes(b"image")
        output = self.root / "test.jwlplaylist"
        settings = {**module.DEFAULTS, "include": ["*.jpg"]}
        with mock.patch.object(module, "_make_thumbnail", side_effect=lambda source, destination, settings: destination.write_bytes(module.DEFAULT_THUMBNAIL)):
            module.create_playlist(self.root, output, "Test Playlist", settings)
        with zipfile.ZipFile(output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertLessEqual({"manifest.json", "userData.db", "default_thumbnail.png"}, set(archive.namelist()))
            archive.extract("userData.db", self.root / "unpacked")
        db = sqlite3.connect(self.root / "unpacked" / "userData.db")
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 16)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(db.execute("SELECT Name FROM Tag WHERE Type=2").fetchone()[0], "Test Playlist")
        labels = [r[0] for r in db.execute("SELECT Label FROM PlaylistItem JOIN TagMap USING(PlaylistItemId) ORDER BY Position")]
        self.assertEqual(labels, ["01 first.jpg", "02 second.jpg"])
        self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0], 23)
        db.close()
        inspected = module.inspect_playlist(output)
        self.assertTrue(inspected["manifest_database_hash_matches"])
        self.assertTrue(all(item["hash_matches"] for item in inspected["items"]))

    def test_thumbnail_fallback_is_png_in_database(self):
        (self.root / "01 image.jpg").write_bytes(b"image")
        output = self.root / "fallback.jwlplaylist"
        with mock.patch.object(module, "_make_thumbnail", side_effect=OSError("no ffmpeg")):
            module.create_playlist(self.root, output, "Fallback", {**module.DEFAULTS, "include": ["*.jpg"]})
        with zipfile.ZipFile(output) as archive:
            archive.extract("userData.db", self.root / "fallback-unpacked")
            self.assertTrue(any(name.endswith(".png") and name != "default_thumbnail.png" for name in archive.namelist()))
        db = sqlite3.connect(self.root / "fallback-unpacked" / "userData.db")
        mime = db.execute("SELECT MimeType FROM IndependentMedia WHERE FilePath=(SELECT ThumbnailFilePath FROM PlaylistItem)").fetchone()[0]
        self.assertEqual(mime, "image/png")
        db.close()

    def test_every_default_has_a_create_flag(self):
        create_parser = next(action for action in module.build_parser()._subparsers._group_actions).choices["create"]
        options = {option for action in create_parser._actions for option in action.option_strings}
        for key in module.DEFAULTS:
            self.assertIn("--" + key.replace("_", "-"), options)

    def test_metadata_video_titles_and_filename_picture_titles_are_numbered(self):
        media = [self.root / "1 Opening image.jpg", self.root / "2 opaque-video-code.mp4", self.root / "10 Closing image.png"]
        settings = {**module.DEFAULTS, "video_title_source": "metadata", "number_titles": True}
        with mock.patch.object(module, "_embedded_title", return_value="A Good Video Title"):
            labels = module.presentation_labels(media, settings)
        self.assertEqual(labels, ["01 Opening image", "02 A Good Video Title", "10 Closing image"])

    def test_numbering_does_not_duplicate_existing_title_number(self):
        settings = {**module.DEFAULTS, "video_title_source": "metadata", "number_titles": True}
        with mock.patch.object(module, "_embedded_title", return_value="7 Finished Title"):
            labels = module.presentation_labels([self.root / "007 source.mp4"], settings)
        self.assertEqual(labels, ["7 Finished Title"])

    def test_number_width_follows_largest_item_number(self):
        media = [self.root / "1 first.jpg", self.root / "101 last.jpg"]
        settings = {**module.DEFAULTS, "number_titles": True}
        self.assertEqual(module.presentation_labels(media, settings), ["001 first", "101 last"])


if __name__ == "__main__":
    unittest.main()
