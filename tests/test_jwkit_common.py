from __future__ import annotations

import unittest
from unittest import mock

from tests.support import load_script_module


class JwkitCommonConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_defaults_when_no_config_file(self) -> None:
        with mock.patch("pathlib.Path.exists", return_value=False):
            config = self.common.load_jwkit_config()
        self.assertTrue(config["auto_update"])
        self.assertEqual(config["auto_update_interval_hours"], 24)

    def test_parses_auto_update_false(self) -> None:
        text = "auto_update = false\nauto_update_interval_hours = 12\n"
        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("pathlib.Path.read_text", return_value=text):
            config = self.common.load_jwkit_config()
        self.assertFalse(config["auto_update"])
        self.assertEqual(config["auto_update_interval_hours"], 12)

    def test_ignores_comments_and_blank_lines(self) -> None:
        text = "# a comment\n\nauto_update = true\n"
        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("pathlib.Path.read_text", return_value=text):
            config = self.common.load_jwkit_config()
        self.assertTrue(config["auto_update"])


class JwkitCommonMaybeAutoUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.common = load_script_module("_jwkit_common.py")

    def test_skipped_entirely_when_auto_update_disabled(self) -> None:
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": False, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common, "_read_last_checked") as read_last:
            self.common.maybe_auto_update("/fake/root")
        read_last.assert_not_called()

    def test_skipped_when_checked_recently(self) -> None:
        now = 1_000_000.0
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common.time, "time", return_value=now), \
             mock.patch.object(self.common, "_read_last_checked", return_value=now - 60), \
             mock.patch.object(self.common, "_write_last_checked") as write_last, \
             mock.patch.object(self.common, "_git_fast_forward_update") as git_update:
            self.common.maybe_auto_update("/fake/root")
        write_last.assert_not_called()
        git_update.assert_not_called()

    def test_checks_and_resets_timer_when_interval_elapsed(self) -> None:
        now = 1_000_000.0
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common.time, "time", return_value=now), \
             mock.patch.object(self.common, "_read_last_checked", return_value=0.0), \
             mock.patch.object(self.common, "_write_last_checked") as write_last, \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(self.common, "_git_fast_forward_update", return_value=None) as git_update:
            self.common.maybe_auto_update("/fake/root")
        write_last.assert_called_once_with(now)
        git_update.assert_called_once()

    def test_never_raises_even_if_git_update_blows_up(self) -> None:
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common, "_read_last_checked", return_value=0.0), \
             mock.patch.object(self.common, "_write_last_checked"), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(self.common, "_git_fast_forward_update", side_effect=RuntimeError("boom")):
            self.common.maybe_auto_update("/fake/root")  # must not raise

    def test_skipped_when_no_git_dir_present(self) -> None:
        with mock.patch.object(self.common, "load_jwkit_config", return_value={"auto_update": True, "auto_update_interval_hours": 24}), \
             mock.patch.object(self.common, "_read_last_checked", return_value=0.0), \
             mock.patch.object(self.common, "_write_last_checked"), \
             mock.patch("pathlib.Path.exists", return_value=False), \
             mock.patch.object(self.common, "_git_fast_forward_update") as git_update:
            self.common.maybe_auto_update("/fake/root")
        git_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
