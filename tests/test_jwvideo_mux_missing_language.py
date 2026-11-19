from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import load_script_module

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
JWVIDEOMUX = str(Path(__file__).resolve().parents[1] / "jwvideo-mux")


class InferMediaParamsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mux = load_script_module("jwvideo-mux")

    def test_issue_and_track(self) -> None:
        self.assertEqual(
            self.mux.infer_media_params_from_filename("mwbv_FSL_202311_02_r720P_rife.mp4", "FSL"),
            {"pub": "mwbv", "issue": "202311", "track": "2"},
        )

    def test_track_only(self) -> None:
        self.assertEqual(
            self.mux.infer_media_params_from_filename("sjjm_E_003_r720P.mp4", "E"),
            {"pub": "sjjm", "track": "3"},
        )

    def test_unrecognised_names_give_none(self) -> None:
        self.assertIsNone(self.mux.infer_media_params_from_filename("My Talk.mp4", "FSL"))
        self.assertIsNone(self.mux.infer_media_params_from_filename("mwbv_E_202311_02_r720P.mp4", "FSL"))
        self.assertIsNone(self.mux.infer_media_params_from_filename("mwbv_FSL_r720P.mp4", "FSL"))


class DownloadMissingLanguageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mux = load_script_module("jwvideo-mux")

    def test_audio_language_prefers_mp3_then_low_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(self.mux, "download_file", return_value=True) as dl:
            links = {"mp4": "https://x/mwbv_CV_202311_02_r720P.mp4", "mp4_low": "https://x/mwbv_CV_202311_02_r240P.mp4"}
            with mock.patch.object(self.mux, "get_media_links", return_value=links):
                entry, url = self.mux.download_missing_language({"pub": "mwbv"}, "CV", "720p", False, Path(tmp))
            self.assertEqual(entry, {"audio": Path(tmp) / "mwbv_CV_202311_02_r240P.mp4"})
            self.assertEqual(url, links["mp4_low"])
            dl.assert_called_once()

    def test_video_language_uses_requested_resolution_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(self.mux, "download_file", return_value=True):
            links = {"mp4": "https://x/mwbv_FSL_202311_02_r720P.mp4"}
            with mock.patch.object(self.mux, "get_media_links", return_value=links):
                entry, _ = self.mux.download_missing_language({"pub": "mwbv"}, "FSL", "720p", True, Path(tmp))
            self.assertEqual(entry, {"video": Path(tmp) / "mwbv_FSL_202311_02_r720P.mp4"})

    def test_nothing_on_jworg_or_failed_download_gives_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(self.mux, "get_media_links", return_value={}):
                self.assertEqual(self.mux.download_missing_language({}, "CV", "720p", True, Path(tmp)), ({}, None))
            with mock.patch.object(self.mux, "get_media_links", return_value={"mp4": "https://x/a.mp4"}), \
                    mock.patch.object(self.mux, "download_file", return_value=False):
                self.assertEqual(self.mux.download_missing_language({}, "CV", "720p", True, Path(tmp)), ({}, None))

    def test_download_file_leaves_no_truncated_file_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.mp4"
            with mock.patch.object(self.mux.urllib.request, "urlopen", side_effect=OSError("boom")):
                self.assertFalse(self.mux.download_file("https://x/a.mp4", dest))
            self.assertEqual(list(Path(tmp).iterdir()), [])


@unittest.skipUnless(FFMPEG_AVAILABLE, "ffmpeg not installed")
class InputIsNeverClobberedTest(unittest.TestCase):
    """Real incident: `-v FSL -a CV in_FSL_..._rife.mp4` with no CV file kept the output name equal to
    the input name, so on_output_exists=trash moved the input to the Trash before ffmpeg opened it."""

    def _clip(self, path: Path) -> None:
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ], check=True)

    def _run(self, root: Path, *argv: str) -> subprocess.CompletedProcess:
        cfg = root / "cfg"
        (cfg / ".config" / "jwkit").mkdir(parents=True)
        (cfg / ".config" / "jwkit" / "config.toml").write_text('on_output_exists = "trash"\nauto_update = false\n')
        return subprocess.run(
            [sys.executable, JWVIDEOMUX, *argv], cwd=root, capture_output=True, text=True, timeout=120,
            env={"PATH": __import__("os").environ["PATH"], "HOME": str(cfg)},
        )

    def test_missing_requested_language_fails_without_touching_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jwvideo-mux-miss-") as tmp:
            root = Path(tmp)
            src = root / "mwbv_FSL_202311_02_r720P_rife.mp4"
            self._clip(src)
            before = src.read_bytes()
            result = self._run(root, "-v", "FSL", "-a", "CV", "-s", "NONE", "-c", "mp4",
                               "--no-download-missing", str(src))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CV", result.stdout)
            self.assertEqual(src.read_bytes(), before)

    def test_output_equal_to_input_is_refused_not_trashed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jwvideo-mux-same-") as tmp:
            root = Path(tmp)
            src = root / "prefix_TG_test.mp4"
            self._clip(src)
            before = src.read_bytes()
            result = self._run(root, "-v", "TG", "-a", "NONE", "-s", "NONE", "-c", "mp4", str(src))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("would replace one of its own inputs", result.stdout)
            self.assertEqual(src.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
