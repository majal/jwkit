from __future__ import annotations

import py_compile
import subprocess
import sys
import tempfile
import unittest

from tests.support import REPO_ROOT


class SmokeTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_scripts_compile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            py_compile.compile(str(REPO_ROOT / "jwvideo-mux"), cfile=f"{tmpdir}/jwvideo_mux.pyc", doraise=True)
            py_compile.compile(str(REPO_ROOT / "slverse"), cfile=f"{tmpdir}/slverse.pyc", doraise=True)
            py_compile.compile(str(REPO_ROOT / "ffrife"), cfile=f"{tmpdir}/ffrife.pyc", doraise=True)
            py_compile.compile(str(REPO_ROOT / "jwdl"), cfile=f"{tmpdir}/jwdl.pyc", doraise=True)

    def test_jwvideo_mux_help(self) -> None:
        result = self.run_script("jwvideo-mux", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--analyze-video-variants", result.stdout)
        self.assertIn("--dedupe-identical-video", result.stdout)

    def test_slverse_help(self) -> None:
        result = self.run_script("slverse", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("setup", result.stdout)
        self.assertIn("sync", result.stdout)
        self.assertIn("extract", result.stdout)
        self.assertIn("find", result.stdout)
        self.assertIn("cache", result.stdout)
        self.assertIn("bulk", result.stdout)

    def test_slverse_config_defaults(self) -> None:
        result = self.run_script("slverse", "config", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cache_max_gb", result.stdout)
        self.assertIn("languages", result.stdout)
        self.assertIn("video_crf", result.stdout)

    def test_jwdl_music_list_unchanged_by_periodicals_merge(self) -> None:
        result = self.run_script("jwdl", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("osg", result.stdout)
        self.assertIn("all", result.stdout)

    def test_jwdl_periodicals_list(self) -> None:
        result = self.run_script("jwdl", "periodicals", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("w", result.stdout)
        self.assertIn("mwb", result.stdout)

    def test_jwdl_video_browse_root(self) -> None:
        result = self.run_script("jwdl", "video")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VODStudio", result.stdout)

    def test_jwdl_video_unknown_category_is_clean_error(self) -> None:
        result = self.run_script("jwdl", "video", "DefinitelyNotARealCategory")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Unknown video category", result.stdout)
