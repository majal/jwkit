from __future__ import annotations

import argparse
import glob
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import load_script_module

# The verse-end label crop is 240x50 grayscale, one byte per pixel.
FRAME_SIZE = 240 * 50
FSL_SEGMENT_GLOB = str(Path.home() / ".cache" / "slverse" / "FSL" / "19_119" / "seg-*-169779-204013-v3.mp4")


def _frames_raw(values):
    """Build rawvideo bytes: one uniform 240x50 frame per value."""
    return b"".join(bytes([v]) * FRAME_SIZE for v in values)


class SlverseDetectVerseEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        self.config = dict(self.slverse.DEFAULT_CONFIG)
        # 30 fps keeps the frame arithmetic exact: marker_end 10.0, search 1.5
        # scans 8.5..10.0, which is 45 frames.
        fps = mock.patch.object(self.slverse, "probe_video_fps", return_value=30.0)
        fps.start()
        self.addCleanup(fps.stop)

    def _run(self, values, *, marker_end=10.0, verse_start=0.0):
        raw = _frames_raw(values)
        with mock.patch.object(self.slverse.subprocess, "run", return_value=argparse.Namespace(stdout=raw)) as run:
            result = self.slverse.detect_verse_end(
                "source.mp4", verse_start=verse_start, marker_end=marker_end, local_offset=0.0, config=self.config,
            )
        return result, run

    def test_boundary_is_first_frame_after_label_change(self) -> None:
        values = [50] * 20 + [200] * 25
        result, _ = self._run(values)
        self.assertAlmostEqual(result["boundary"], 8.5 + 19.5 / 30.0)
        self.assertEqual(result["frames_cut"], 25)
        self.assertEqual(result["frames_scanned"], 45)

    def test_boundary_uses_real_frame_timestamps_when_logged(self) -> None:
        # Frames land 10 ms off the 1/30 s grid; the cut goes midway between the
        # last frame of the verse (index 19) and the first of the next (20).
        values = [50] * 20 + [200] * 25
        pts = [-0.001 + i / 30.0 for i in range(45)]  # a seek leaves the first frame just before 0
        stderr = "".join(f"[Parsed_showinfo_2 @ 0x1] n:{i:3d} pts:{i} pts_time:{t:.6f}\n" for i, t in enumerate(pts)).encode()
        raw = _frames_raw(values)
        with mock.patch.object(self.slverse.subprocess, "run", return_value=argparse.Namespace(stdout=raw, stderr=stderr)):
            result = self.slverse.detect_verse_end(
                "source.mp4", verse_start=0.0, marker_end=10.0, local_offset=0.0, config=self.config,
            )
        self.assertAlmostEqual(result["boundary"], 8.5 + (pts[19] + pts[20]) / 2)
        self.assertEqual(result["frames_cut"], 25)

    def test_change_on_the_last_frame_only_is_not_confirmed(self) -> None:
        result, _ = self._run([50] * 44 + [200])
        self.assertIsNone(result["boundary"])
        self.assertIn("only one frame", result["reason"])

    def test_change_on_the_last_two_frames_is_confirmed(self) -> None:
        result, _ = self._run([50] * 43 + [200] * 2)
        self.assertIsNotNone(result["boundary"])
        self.assertEqual(result["frames_cut"], 2)

    def test_no_label_change_keeps_marker(self) -> None:
        result, _ = self._run([50] * 45)
        self.assertIsNone(result["boundary"])
        self.assertIn("no label change", result["reason"])

    def test_uniform_label_throughout_keeps_marker(self) -> None:
        result, _ = self._run([200] * 45)
        self.assertIsNone(result["boundary"])
        self.assertIn("no label change", result["reason"])

    def test_unstable_tail_is_unconfirmed(self) -> None:
        # The label goes back to the old verse after a brief change, which is
        # a hand or occlusion, not a verse boundary.
        values = [50] * 20 + [200] * 10 + [50] * 15
        result, _ = self._run(values)
        self.assertIsNone(result["boundary"])
        self.assertIn("not clean", result["reason"])

    def test_decode_failure_keeps_marker_and_never_raises(self) -> None:
        with mock.patch.object(self.slverse.subprocess, "run", side_effect=OSError("ffmpeg missing")):
            result = self.slverse.detect_verse_end(
                "source.mp4", verse_start=0.0, marker_end=10.0, local_offset=0.0, config=self.config,
            )
        self.assertIsNone(result["boundary"])
        self.assertIn("marker kept", result["reason"])

    def test_remote_source_is_skipped_without_decoding(self) -> None:
        with mock.patch.object(self.slverse.subprocess, "run") as run:
            result = self.slverse.detect_verse_end(
                "https://example/verse.mp4", verse_start=0.0, marker_end=10.0, local_offset=0.0, config=self.config,
            )
        self.assertIsNone(result["boundary"])
        run.assert_not_called()

    def test_scan_never_starts_before_verse_start(self) -> None:
        # A verse only 1 s long: the scan must not reach into the previous verse.
        result, run = self._run([50] * 30, marker_end=10.0, verse_start=9.0)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("-ss") + 1], "9.000")
        self.assertEqual(cmd[cmd.index("-frames:v") + 1], "30")
        self.assertIsNone(result["boundary"])


def _stderr_for(pts):
    return "".join(f"[Parsed_showinfo_2 @ 0x1] n:{i:3d} pts:{i} pts_time:{t:.6f}\n" for i, t in enumerate(pts)).encode()


class SlverseLabelStepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def _frames(self, values):
        return [bytes([v]) * FRAME_SIZE for v in values]

    def test_small_one_digit_change_is_a_step(self) -> None:
        # 96 to 97 differs by about 6 grey levels on FSL 19_119, below the old
        # absolute threshold of 12.
        index, step = self.slverse._label_step(self._frames([100] * 10 + [106] * 10))
        self.assertEqual(index, 10)
        self.assertAlmostEqual(step, 6.0)

    def test_flat_label_has_no_step(self) -> None:
        index, reason = self.slverse._label_step(self._frames([100] * 20))
        self.assertIsNone(index)
        self.assertEqual(reason, "no label change")

    def test_compression_noise_is_not_a_step(self) -> None:
        index, _ = self.slverse._label_step(self._frames([100, 101, 100, 102, 101, 100, 101, 100]))
        self.assertIsNone(index)

    def test_occlusion_and_fade_are_not_clean(self) -> None:
        self.assertIsNone(self.slverse._label_step(self._frames([50] * 8 + [200] * 3 + [50] * 8))[0])
        self.assertIsNone(self.slverse._label_step(self._frames([50] * 8 + [100, 150] + [200] * 8))[0])


class SlverseDetectVerseStartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        self.config = dict(self.slverse.DEFAULT_CONFIG)
        fps = mock.patch.object(self.slverse, "probe_video_fps", return_value=30.0)
        fps.start()
        self.addCleanup(fps.stop)

    def _run(self, values, *, verse_start=10.0, scan_start=8.5):
        pts = [i / 30.0 for i in range(len(values))]  # relative to scan_start
        proc = argparse.Namespace(stdout=_frames_raw(values), stderr=_stderr_for(pts))
        with mock.patch.object(self.slverse.subprocess, "run", return_value=proc):
            return self.slverse.detect_verse_start(
                "source.mp4", verse_start=verse_start, scan_start=scan_start, local_offset=0.0, config=self.config,
            )

    def test_change_early_in_the_preroll_extends_back_to_it(self) -> None:
        # Frame 45 is the marker start (8.5 + 45/30 = 10.0); the label turned at frame 3.
        result = self._run([50] * 3 + [200] * 47)
        self.assertAlmostEqual(result["boundary"], 8.5 + 2.5 / 30.0, delta=1e-4)
        self.assertEqual(result["frames_added"], 42)

    def test_extends_to_midway_between_frames(self) -> None:
        result = self._run([50] * 40 + [200] * 10)  # label turns 5 frames before the marker start
        self.assertAlmostEqual(result["boundary"], 8.5 + 39.5 / 30.0, delta=1e-4)
        self.assertEqual(result["frames_added"], 5)
        self.assertLess(result["boundary"], 10.0)

    def test_no_change_in_preroll_keeps_marker_start(self) -> None:
        result = self._run([200] * 50)
        self.assertIsNone(result["boundary"])
        self.assertIn("already current", result["reason"])

    def test_change_exactly_at_marker_start_keeps_it(self) -> None:
        result = self._run([50] * 45 + [200] * 5)
        self.assertIsNone(result["boundary"])
        self.assertIn("already current", result["reason"])

    def test_without_timestamps_the_marker_start_is_kept(self) -> None:
        proc = argparse.Namespace(stdout=_frames_raw([50] * 40 + [200] * 10), stderr=b"")
        with mock.patch.object(self.slverse.subprocess, "run", return_value=proc):
            result = self.slverse.detect_verse_start(
                "source.mp4", verse_start=10.0, scan_start=8.5, local_offset=0.0, config=self.config,
            )
        self.assertIsNone(result["boundary"])

    def test_no_source_before_the_marker_start(self) -> None:
        with mock.patch.object(self.slverse.subprocess, "run") as run:
            result = self.slverse.detect_verse_start(
                "source.mp4", verse_start=0.0, scan_start=0.0, local_offset=0.0, config=self.config,
            )
        self.assertIsNone(result["boundary"])
        run.assert_not_called()

    def test_decode_failure_never_raises(self) -> None:
        with mock.patch.object(self.slverse.subprocess, "run", side_effect=OSError("ffmpeg missing")):
            result = self.slverse.detect_verse_start(
                "source.mp4", verse_start=10.0, scan_start=8.5, local_offset=0.0, config=self.config,
            )
        self.assertIsNone(result["boundary"])


class SlverseVerseEndWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        self.slverse.load_index = lambda lang: {
            "19_16": {
                "url": "http://example/vid.mp4",
                "checksum": "abc123",
                "markers": [
                    {"verseNumber": 11, "startTime": "00:02:29.415", "duration": "00:00:33.800", "endTransitionDuration": "00:00:06.940", "label": "Psalm 16:11"},
                ],
            }
        }
        self.config = dict(self.slverse.DEFAULT_CONFIG, trim_end_transition="false")

    def test_probe_boundary_shortens_the_window(self) -> None:
        probe = mock.Mock(return_value=180.0)
        start, end, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config, end_probe=probe)
        self.assertAlmostEqual(end, 180.0)
        probe.assert_called_once_with(149.415, 149.415 + 33.800, "http://example/vid.mp4", "abc123")

    def test_probe_never_extends_the_window(self) -> None:
        probe = mock.Mock(return_value=200.0)
        start, end, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config, end_probe=probe)
        self.assertAlmostEqual(end, 149.415 + 33.800)

    def test_unconfirmed_probe_keeps_marker_end(self) -> None:
        start, end, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config, end_probe=lambda *a: None)
        self.assertAlmostEqual(end, 149.415 + 33.800)

    def test_head_probe_moves_the_start_earlier_and_keeps_the_end(self) -> None:
        head = mock.Mock(return_value=148.9)
        start, end, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config, head_probe=head)
        self.assertAlmostEqual(start, 148.9)
        self.assertAlmostEqual(end, 149.415 + 33.800)
        head.assert_called_once_with(149.415, 149.415 + 33.800, "http://example/vid.mp4", "abc123")

    def test_head_probe_never_moves_the_start_later(self) -> None:
        start, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config, head_probe=lambda *a: 150.0)
        self.assertAlmostEqual(start, 149.415)

    def test_head_probe_is_skipped_when_the_caller_trims_the_start(self) -> None:
        head = mock.Mock(return_value=148.9)
        start, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config, trim_start=0.5, head_probe=head)
        head.assert_not_called()
        self.assertAlmostEqual(start, 149.415 + 0.5)

    def test_head_and_tail_probes_both_see_the_marker_times(self) -> None:
        tail = mock.Mock(return_value=180.0)
        start, end, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config, end_probe=tail, head_probe=lambda *a: 149.0)
        self.assertAlmostEqual((start, end), (149.0, 180.0))
        tail.assert_called_once_with(149.415, 149.415 + 33.800, "http://example/vid.mp4", "abc123")

    def test_no_probe_keeps_marker_end(self) -> None:
        start, end, *_ = self.slverse.resolve_verse_window("ASL", 19, 16, [11], self.config)
        self.assertAlmostEqual(end, 149.415 + 33.800)


class SlverseVerseEndProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_applied_reports_frames_cut_from_first_confirmed_result(self) -> None:
        probe = self.slverse.VerseEndProbe("FSL", 19, 119, dict(self.slverse.DEFAULT_CONFIG), {})
        probe.outcomes = [
            {"boundary": None, "marker_end": 5.0, "reason": "no label change", "fps": 29.97, "frames_scanned": 45},
            {"boundary": 181.4582, "marker_end": 181.757, "reason": "label changed", "fps": 29.97002997, "frames_scanned": 45, "frames_cut": 9},
        ]
        self.assertEqual(probe.applied(), (9, 29.97002997))

    def test_applied_is_none_when_nothing_confirmed(self) -> None:
        probe = self.slverse.VerseEndProbe("FSL", 19, 119, dict(self.slverse.DEFAULT_CONFIG), {})
        probe.outcomes = [{"boundary": None, "marker_end": 5.0, "reason": "x", "fps": 29.97, "frames_scanned": 45}]
        self.assertIsNone(probe.applied())


class SlverseResolveExtractModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def test_flags_beat_config(self) -> None:
        args = argparse.Namespace(onthefly=True, cache=False, segment=False)
        self.assertEqual(self.slverse.resolve_extract_mode(args, {"extract_mode": "segment"}), "onthefly")
        args = argparse.Namespace(onthefly=False, cache=True, segment=False)
        self.assertEqual(self.slverse.resolve_extract_mode(args, {"extract_mode": "segment"}), "cache")

    def test_config_used_without_flags(self) -> None:
        args = argparse.Namespace(onthefly=False, cache=False, segment=False)
        self.assertEqual(self.slverse.resolve_extract_mode(args, {"extract_mode": "segment"}), "segment")


class SlverseVerseEndRealSegmentTest(unittest.TestCase):
    """FSL 19_119 verse 97 on the cached segment: the label changes to 98
    9 frames before the marker end (see docs/reports/2026-11-19-verse-end-source-overrun.md).
    Skipped when the segment is not cached on this machine."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")
        matches = sorted(glob.glob(FSL_SEGMENT_GLOB))
        cls.segment = matches[0] if matches else None

    def setUp(self) -> None:
        if self.segment is None:
            self.skipTest("FSL 19_119 segment not cached locally")

    def test_label_boundary_matches_measured_switch(self) -> None:
        seg_start = 169.779
        result = self.slverse.detect_verse_end(
            self.segment, verse_start=seg_start, marker_end=seg_start + 11.978,
            local_offset=-seg_start, config=dict(self.slverse.DEFAULT_CONFIG),
        )
        self.assertIsNotNone(result["boundary"], result["reason"])
        self.assertEqual(result["frames_cut"], 9)
        # Segment frame 349 (11.645 s) still reads 97 and frame 350 (11.678 s) reads
        # 98, so the cut sits between them: the -t cut keeps 349 and drops 350.
        frame_len = 1001 / 30000
        local = result["boundary"] - seg_start
        self.assertGreater(local, 349 * frame_len)
        self.assertLess(local, 350 * frame_len)
        self.assertAlmostEqual(local, 349.5 * frame_len, delta=0.002)
        self.assertAlmostEqual(local, 349.5 * frame_len, delta=0.002)


class SlverseVerseEndLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.slverse = load_script_module("slverse")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger_path = Path(tmp.name) / "verse_end_ledger.json"
        patch = mock.patch.object(self.slverse, "VERSE_END_LEDGER_FILE", self.ledger_path)
        patch.start()
        self.addCleanup(patch.stop)
        self.config = dict(self.slverse.DEFAULT_CONFIG)
        self.confirmed = {"boundary": 181.4582, "reason": "label changed", "fps": 29.97002997, "frames_scanned": 45, "frames_cut": 9}

    def _record(self, checksum, result=None, url="http://example/fsl.mp4"):
        return self.slverse.record_verse_end_decision(
            "FSL", 19, 119, 169.779, 181.757, checksum, url, self.config, result or self.confirmed,
        )

    def _ledger(self):
        return json.loads(self.ledger_path.read_text())

    def test_records_decision_under_window_key(self) -> None:
        entry = self._record("abc")
        ledger = self._ledger()
        key = "FSL:19_119:169779-181757"
        self.assertEqual(list(ledger), [key])
        self.assertEqual(ledger[key]["checksum"], "abc")
        self.assertEqual(ledger[key]["url"], "http://example/fsl.mp4")
        self.assertEqual(ledger[key]["frames_cut"], 9)
        self.assertEqual(ledger[key]["settings"]["verse_end"], "label")
        self.assertFalse(entry["source_changed"])

    def test_unconfirmed_scan_records_marker_kept(self) -> None:
        self._record("abc", {"boundary": None, "reason": "no label change", "fps": 29.97, "frames_scanned": 45})
        entry = self._ledger()["FSL:19_119:169779-181757"]
        self.assertIsNone(entry["boundary"])
        self.assertEqual(entry["frames_cut"], 0)
        self.assertEqual(entry["reason"], "no label change")

    def test_same_checksum_is_not_a_source_change(self) -> None:
        self._record("abc")
        entry = self._record("abc")
        self.assertFalse(entry["source_changed"])
        self.assertNotIn("previous_checksum", entry)

    def test_new_checksum_flags_source_changed(self) -> None:
        self._record("abc")
        entry = self._record("def")
        self.assertTrue(entry["source_changed"])
        self.assertEqual(entry["previous_checksum"], "abc")
        self.assertEqual(self._ledger()["FSL:19_119:169779-181757"]["checksum"], "def")

    def test_changed_source_with_moved_markers_is_still_flagged(self) -> None:
        # A re-edited video usually moves its markers, so the window key differs.
        self._record("abc")
        entry = self.slverse.record_verse_end_decision(
            "FSL", 19, 119, 169.9, 181.9, "def", "http://example/fsl.mp4", self.config, self.confirmed,
        )
        self.assertTrue(entry["source_changed"])
        self.assertEqual(entry["previous_checksum"], "abc")

    def test_rescan_on_same_new_source_keeps_the_change_record(self) -> None:
        self._record("abc")
        self._record("def")
        entry = self._record("def")
        self.assertFalse(entry["source_changed"])
        self.assertEqual(entry["previous_checksum"], "abc")

    def test_new_window_on_unchanged_chapter_is_not_flagged(self) -> None:
        self._record("abc")
        entry = self.slverse.record_verse_end_decision(
            "FSL", 19, 119, 181.758, 193.770, "abc", "http://example/fsl.mp4", self.config, self.confirmed,
        )
        self.assertFalse(entry["source_changed"])

    def test_head_decision_is_recorded_with_the_window(self) -> None:
        head = {"boundary": 181.4407, "frames_added": 10, "reason": "label current 10 frames before the marker start"}
        entry = self.slverse.record_verse_end_decision(
            "FSL", 19, 119, 181.758, 193.77, "abc", "http://example/fsl.mp4", self.config, self.confirmed, head=head,
        )
        self.assertEqual(entry["head_boundary"], 181.4407)
        self.assertEqual(entry["head_frames_added"], 10)
        self.assertEqual(entry["marker_start"], 181.758)
        self.assertEqual(entry["algo"], self.slverse.VERSE_END_ALGO)

    def test_reuse_needs_same_checksum_settings_and_algorithm(self) -> None:
        self._record("abc")
        reuse = lambda checksum="abc", config=None: self.slverse.reusable_verse_end_decision(
            "FSL", 19, 119, 169.779, 181.757, checksum, config or self.config)
        self.assertIsNotNone(reuse())
        self.assertIsNone(reuse(checksum="def"))
        self.assertIsNone(reuse(config=dict(self.config, verse_end_search="2.0")))
        data = self._ledger()
        data["FSL:19_119:169779-181757"]["algo"] = self.slverse.VERSE_END_ALGO - 1
        self.ledger_path.write_text(json.dumps(data))
        self.assertIsNone(reuse())

    def test_unconfirmed_scans_are_never_reused(self) -> None:
        self._record("abc", {"boundary": None, "reason": "no label change", "fps": 29.97, "frames_scanned": 45})
        self.assertIsNone(self.slverse.reusable_verse_end_decision("FSL", 19, 119, 169.779, 181.757, "abc", self.config))

    def test_probe_reuses_a_recorded_decision_without_scanning(self) -> None:
        self._record("abc")
        probe = self.slverse.VerseEndProbe("FSL", 19, 119, self.config, {}, quiet=True)
        with mock.patch.object(self.slverse, "resolve_cached_source") as fetch, \
                mock.patch.object(self.slverse, "detect_verse_end") as scan:
            boundary = probe(169.779, 181.757, "http://example/fsl.mp4", "abc")
        self.assertAlmostEqual(boundary, 181.4582)
        fetch.assert_not_called()
        scan.assert_not_called()
        self.assertEqual(probe.applied(), (9, 29.97002997))

    def test_probe_rescans_when_the_source_checksum_changed(self) -> None:
        self._record("abc")
        probe = self.slverse.VerseEndProbe("FSL", 19, 119, self.config, {}, quiet=True)
        with mock.patch.object(self.slverse, "resolve_cached_source", return_value=("src.mp4", "cached", 0.0, 0.0)), \
                mock.patch.object(self.slverse, "cache_in_use"), \
                mock.patch.object(self.slverse, "detect_verse_end", return_value=dict(self.confirmed, marker_end=181.757)) as scan:
            probe(169.779, 181.757, "http://example/fsl.mp4", "def")
        scan.assert_called_once()
        self.assertTrue(self._ledger()["FSL:19_119:169779-181757"]["source_changed"])

    def test_corrupt_ledger_is_replaced_not_fatal(self) -> None:
        self.ledger_path.write_text("{not json")
        self._record("abc")
        self.assertEqual(len(self._ledger()), 1)

    def test_probe_records_only_real_scans(self) -> None:
        probe = self.slverse.VerseEndProbe("FSL", 19, 119, self.config, {})
        with mock.patch.object(self.slverse, "resolve_cached_source", return_value=("src.mp4", None, 0.0, 0.0)):
            probe(169.779, 181.757, "http://example/fsl.mp4", "abc")
        self.assertFalse(self.ledger_path.exists())

    def test_probe_records_cached_scan_with_checksum(self) -> None:
        probe = self.slverse.VerseEndProbe("FSL", 19, 119, self.config, {}, quiet=True)
        with mock.patch.object(self.slverse, "resolve_cached_source", return_value=("src.mp4", "cached", 0.0, 0.0)), \
                mock.patch.object(self.slverse, "cache_in_use"), \
                mock.patch.object(self.slverse, "detect_verse_end", return_value=self.confirmed):
            boundary = probe(169.779, 181.757, "http://example/fsl.mp4", "abc")
        self.assertAlmostEqual(boundary, 181.4582)
        entry = self._ledger()["FSL:19_119:169779-181757"]
        self.assertEqual(entry["checksum"], "abc")
        self.assertEqual(entry["frames_cut"], 9)

    def test_marker_mode_is_rejected(self) -> None:
        self.assertIsNone(self.slverse.validate_config_value("verse_end", "label"))
        self.assertIsNone(self.slverse.validate_config_value("verse_end", "off"))
        error = self.slverse.validate_config_value("verse_end", "marker")
        self.assertIsNotNone(error)
        self.assertIn("label, off", error)

    def test_ledger_write_failure_never_fails_the_scan(self) -> None:
        probe = self.slverse.VerseEndProbe("FSL", 19, 119, self.config, {}, quiet=True)
        with mock.patch.object(self.slverse, "resolve_cached_source", return_value=("src.mp4", "cached", 0.0, 0.0)), \
                mock.patch.object(self.slverse, "cache_in_use"), \
                mock.patch.object(self.slverse, "detect_verse_end", return_value=self.confirmed), \
                mock.patch.object(self.slverse, "record_verse_end_decision", side_effect=OSError("disk full")):
            boundary = probe(169.779, 181.757, "http://example/fsl.mp4", "abc")
        self.assertAlmostEqual(boundary, 181.4582)


if __name__ == "__main__":
    unittest.main()
