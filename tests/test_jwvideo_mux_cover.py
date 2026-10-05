from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, load_script_module

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


class JwvideoMuxBinaryConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mux = load_script_module("jwvideo-mux")

    def test_ffmpeg_binaries_are_configurable_with_empty_defaults(self) -> None:
        for key in ("ffmpeg_binary", "ffprobe_binary"):
            self.assertEqual(self.mux.DEFAULT_CONFIG[key], "")
            self.assertIn(key, self.mux.CONFIG_HELP)

    def test_no_subprocess_hardcodes_a_bare_ffmpeg_or_ffprobe(self) -> None:
        source = (REPO_ROOT / "jwvideo-mux").read_text()
        for bare in ('"ffmpeg", "-', '"ffprobe", "-', 'which("ffmpeg")'):
            self.assertNotIn(bare, source)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe not installed")
class JwvideoMuxCoverArtTest(unittest.TestCase):
    def mux_with_cover(self, tmp: Path, out_name: str, wrapper: Path | None = None) -> Path:
        source = tmp / "S-100_E_01_r720P.mp4"
        if not source.exists():
            cover, plain = tmp / "cov.png", tmp / "plain.mp4"
            subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(cover)], check=True)
            subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=160x90:r=12", "-f", "lavfi", "-i", "sine=d=1",
                            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(plain)], check=True)
            subprocess.run([FFMPEG, "-v", "error", "-i", str(plain), "-i", str(cover), "-map", "0", "-map", "1", "-c", "copy",
                            "-disposition:v:1", "attached_pic", str(source)], check=True)
        home = tmp / "home"
        (home / ".config" / "jwkit").mkdir(parents=True, exist_ok=True)
        (home / ".config" / "jwkit" / "config.toml").write_text("auto_update = false\n")
        command = [str(REPO_ROOT / "jwvideo-mux"), str(source), "-v", "E", "-a", "E", "-c", "mkv", "-o", str(tmp / out_name),
                   "-f", "--provenance", "none"]
        if wrapper:
            command += ["--ffmpeg-binary", str(wrapper)]
        subprocess.run(command, check=True, cwd=tmp, env={**os.environ, "HOME": str(home)}, capture_output=True)
        return next((tmp / out_name).glob("*.mkv"))

    def attachment_tags(self, path: Path) -> list[dict]:
        probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream_tags=filename,mimetype", "-of", "json", str(path)],
                               capture_output=True, text=True, check=True)
        return [s["tags"] for s in json.loads(probe.stdout)["streams"] if s.get("tags", {}).get("filename")]

    def test_mkv_cover_attachment_has_a_stable_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = self.attachment_tags(self.mux_with_cover(Path(tmp), "one"))
            second = self.attachment_tags(self.mux_with_cover(Path(tmp), "two"))
        self.assertEqual(first, [{"filename": "cover.png", "mimetype": "image/png"}])
        self.assertEqual(first, second)

    def test_configured_ffmpeg_binary_is_the_one_that_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log = tmp_path / "calls.log"
            wrapper = tmp_path / "ffmpeg-wrapper"
            wrapper.write_text(f'#!/bin/sh\necho x >> "{log}"\nexec "{FFMPEG}" "$@"\n')
            wrapper.chmod(0o755)
            self.mux_with_cover(tmp_path, "out", wrapper)
            self.assertTrue(log.exists() and log.read_text().strip())


if __name__ == "__main__":
    unittest.main()
