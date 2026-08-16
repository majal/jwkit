from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.support import load_script_module


class RegisterJwplayLauncherMacosTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script_module("register-jwplay-launcher")

    def test_declares_uti_conforming_to_apples_terminal_shell_script(self) -> None:
        # This is the actual load-bearing detail: a UTI conforming to
        # something generic like public.data does not reliably resolve to
        # Terminal.app via duti - only conforming to Apple's own
        # com.apple.terminal.shell-script (the same UTI .command files
        # use) does, confirmed by testing against a real macOS session.
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(self.module.shutil, "which", return_value="/opt/homebrew/bin/duti"), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)), \
                 mock.patch.object(self.module.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="Terminal.app\n", stderr="")
                ok = self.module.register_macos()

            self.assertTrue(ok)
            plist_path = Path(home) / "Applications" / f"{self.module.MACOS_DECLARER_APP_NAME}.app" / "Contents" / "Info.plist"
            self.assertTrue(plist_path.exists())
            import plistlib
            with open(plist_path, "rb") as f:
                plist = plistlib.load(f)
            uti = plist["UTExportedTypeDeclarations"][0]
            self.assertEqual(uti["UTTypeConformsTo"], ["com.apple.terminal.shell-script"])
            self.assertEqual(uti["UTTypeTagSpecification"]["public.filename-extension"], [self.module.JWPLAY_EXTENSION])
            self.assertEqual(plist["CFBundleIdentifier"], self.module.MACOS_DECLARER_BUNDLE_ID)

    def test_duti_invoked_with_terminal_as_the_handler(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(self.module.shutil, "which", return_value="/opt/homebrew/bin/duti"), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)), \
                 mock.patch.object(self.module.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="Terminal.app\n", stderr="")
                self.module.register_macos()

            duti_set_calls = [c for c in run.call_args_list if c.args[0][:2] == ["duti", "-s"]]
            self.assertEqual(len(duti_set_calls), 1)
            self.assertEqual(duti_set_calls[0].args[0], ["duti", "-s", "com.apple.Terminal", f".{self.module.JWPLAY_EXTENSION}", "all"])

    def test_missing_duti_fails_cleanly_without_touching_the_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(self.module.shutil, "which", return_value=None), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)):
                ok = self.module.register_macos()
            self.assertFalse(ok)
            self.assertFalse((Path(home) / "Applications").exists())

    def test_duti_failure_is_reported_and_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(self.module.shutil, "which", return_value="/opt/homebrew/bin/duti"), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)), \
                 mock.patch.object(self.module.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=1, stdout="", stderr="error -50")
                ok = self.module.register_macos()
            self.assertFalse(ok)


class RegisterJwplayLauncherLinuxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script_module("register-jwplay-launcher")

    def test_exec_line_is_a_real_executable_not_a_bare_field_code(self) -> None:
        # GNOME's gio-based resolver (what Nautilus/Files actually uses)
        # silently rejects "Exec=%f" - the first token must be a real,
        # resolvable executable - even though xdg-mime/update-desktop-
        # database both tolerate it. Confirmed against a real GNOME session.
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/xdg-mime"), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)), \
                 mock.patch.object(self.module.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="jwplay.desktop\n", stderr="")
                ok = self.module.register_linux()

            self.assertTrue(ok)
            desktop_path = Path(home) / ".local" / "share" / "applications" / self.module.LINUX_DESKTOP_NAME
            content = desktop_path.read_text()
            exec_line = next(line for line in content.splitlines() if line.startswith("Exec="))
            first_token = exec_line[len("Exec="):].split()[0]
            self.assertTrue(Path(first_token).is_absolute(), f"Exec's first token must be a real executable path, got: {first_token!r}")
            self.assertNotIn("%f", first_token)

    def test_terminal_is_false(self) -> None:
        # Terminal=true relies on the desktop's default terminal supporting
        # a legacy -e-style invocation, which not every terminal emulator
        # does (Warp does not, confirmed by testing) - and it isn't needed
        # anyway since the launcher's own job is opening mpv's GUI window.
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/xdg-mime"), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)), \
                 mock.patch.object(self.module.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="jwplay.desktop\n", stderr="")
                self.module.register_linux()

            desktop_path = Path(home) / ".local" / "share" / "applications" / self.module.LINUX_DESKTOP_NAME
            self.assertIn("Terminal=false", desktop_path.read_text())

    def test_missing_xdg_tools_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(self.module.shutil, "which", return_value=None), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)):
                ok = self.module.register_linux()
            self.assertFalse(ok)
            self.assertFalse((Path(home) / ".local").exists())

    def test_gio_verification_preferred_over_xdg_mime_query(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            def which(cmd):
                return f"/usr/bin/{cmd}"
            with mock.patch.object(self.module.shutil, "which", side_effect=which), \
                 mock.patch.object(self.module.Path, "home", return_value=Path(home)), \
                 mock.patch.object(self.module.subprocess, "run") as run, \
                 mock.patch("builtins.print") as printed:
                run.return_value = mock.Mock(
                    returncode=0,
                    stdout=f"Default application for “{self.module.LINUX_MIME_TYPE}”: {self.module.LINUX_DESKTOP_NAME}\n",
                    stderr="",
                )
                self.module.register_linux()
            gio_calls = [c for c in run.call_args_list if c.args[0][:2] == ["gio", "mime"]]
            self.assertEqual(len(gio_calls), 1)


class RegisterJwplayLauncherWindowsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script_module("register-jwplay-launcher")

    def _fake_winreg(self):
        created = {}

        class FakeKey:
            def __init__(self, path):
                self.path = path
                self.value = None

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        fake = types.SimpleNamespace()
        fake.HKEY_CURRENT_USER = "HKCU"
        fake.REG_SZ = "REG_SZ"

        def create_key(hive, path):
            key = created.setdefault(path, FakeKey(path))
            return key

        def set_value(key, _sub, _type, value):
            key.value = value

        fake.CreateKey = create_key
        fake.SetValue = set_value
        fake._created = created
        return fake

    def test_registers_extension_progid_and_command(self) -> None:
        fake_winreg = self._fake_winreg()
        with mock.patch.dict(sys.modules, {"winreg": fake_winreg}):
            ok = self.module.register_windows()

        self.assertTrue(ok)
        ext_key = fake_winreg._created[rf"Software\Classes\.{self.module.JWPLAY_EXTENSION}"]
        self.assertEqual(ext_key.value, "jwkit.jwplay")
        command_key = fake_winreg._created[r"Software\Classes\jwkit.jwplay\shell\open\command"]
        self.assertIn("cmd.exe", command_key.value)
        self.assertIn("%1", command_key.value)

    def test_registry_failure_is_reported_and_returns_false(self) -> None:
        fake_winreg = self._fake_winreg()

        def failing_create_key(hive, path):
            raise OSError("access denied")

        fake_winreg.CreateKey = failing_create_key
        with mock.patch.dict(sys.modules, {"winreg": fake_winreg}):
            ok = self.module.register_windows()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
