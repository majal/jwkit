from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.support import load_script_module


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class JwkitProvenanceCliTest(unittest.TestCase):
    """`jwkit-provenance`: the entry point scripts in other repos call."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script_module("jwkit-provenance")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(self.cli._jwkit_common, "load_jwkit_config", return_value=dict(self.cli._jwkit_common.DEFAULT_JWKIT_CONFIG))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(self.cli._jwkit_common, "maybe_auto_update")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = self.dir / "kms22v_FSL_131_r720P.mp4"
        self.out = self.dir / "cut.mp4"
        for path in (self.source, self.out):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=1:s=64x36:r=10", "-c:v", "libx264", str(path)], check=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = self.cli.main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_record_embeds_source_window_command_and_settings(self) -> None:
        status, _, _ = self.run_cli("record", str(self.out), "--tool", "mytool", "--source", str(self.source), "--window", "1-2.5",
                                    "--command", "mytool in.mp4 1 2.5", "--set", "speed=0.5", "--settings-json", '{"codec": "h264"}', "--request", "cwd=/x")
        self.assertEqual(status, 0)
        record, where = self.cli._jwkit_common.locate_provenance(self.out)
        self.assertEqual(where, "embedded")
        self.assertEqual(record["tool"], "mytool")
        self.assertEqual(record["source"]["window_seconds"], [1.0, 2.5])
        self.assertEqual(record["source"]["jw_org"]["publication"], "kms22v")
        self.assertEqual(record["settings"], {"codec": "h264", "speed": 0.5})
        self.assertEqual(record["rebuild"]["command"], "mytool in.mp4 1 2.5")
        self.assertEqual(record["request"], {"cwd": "/x"})

    def test_several_inputs_become_a_roled_list(self) -> None:
        self.run_cli("record", str(self.out), "--tool", "t", "--input", f"video:FSL={self.source}", "--input", str(self.out.with_name("cut.mp4")))
        record = self.cli._jwkit_common.read_provenance(self.out)
        self.assertEqual([entry.get("roles") for entry in record["inputs"]], [["video:FSL"], None])

    def test_a_missing_output_or_failed_write_never_breaks_the_caller(self) -> None:
        self.assertEqual(self.run_cli("record", str(self.dir / "nope.mp4"), "--tool", "t")[0], 1)
        with mock.patch.object(self.cli._jwkit_common, "write_provenance", side_effect=RuntimeError("boom")):
            self.assertEqual(self.run_cli("record", str(self.out), "--tool", "t")[0], 0)
            self.assertEqual(self.run_cli("record", str(self.out), "--tool", "t", "--strict")[0], 1)

    def test_provenance_flag_chooses_where_it_goes(self) -> None:
        self.run_cli("record", str(self.out), "--tool", "t", "--provenance", "beside")
        self.assertTrue((self.dir / "cut.mp4.jwkit.json").exists())
        self.assertIsNone(self.cli._jwkit_common._embedded_text(self.out))

    def test_show_verify_and_move(self) -> None:
        self.run_cli("record", str(self.out), "--tool", "t")
        status, out, _ = self.run_cli("show", str(self.out), "--verify")
        self.assertEqual(status, 0)
        self.assertIn("[match]", out)
        self.assertEqual(json.loads(self.run_cli("show", "--json", str(self.out))[1])["record"]["tool"], "t")
        status, out, _ = self.run_cli("move", str(self.dir), "--to", "folder")
        self.assertIn("1 moved", out)
        self.assertTrue((self.dir / ".jwkit" / "cut.mp4.jwkit.json").exists())
        self.assertEqual(self.run_cli("verify", str(self.out))[0], 0)

    def test_verify_fails_for_a_file_without_a_record(self) -> None:
        status, out, _ = self.run_cli("verify", str(self.source))
        self.assertEqual(status, 1)
        self.assertIn("no record", out)
