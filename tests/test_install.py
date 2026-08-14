"""Regression coverage for the POSIX installer startup-file handling."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
MARKER = "# jwkit PATH (added by jwkit's install.sh)"


class InstallPathTests(unittest.TestCase):
    def run_installer(self, home: Path) -> subprocess.CompletedProcess[str]:
        install_dir = home / ".jwkit"
        (install_dir / ".git").mkdir(parents=True)
        for name in ("ffrife", "jwdl", "jwvideo-mux", "slverse"):
            (install_dir / name).touch()

        fake_bin = home / "fake-bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        fake_git.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "  [ \"$arg\" = ls-files ] && { echo jwkit-update; exit 0; }\n"
            "done\n"
            "exit 0\n"
        )
        fake_git.chmod(0o755)

        env = os.environ | {
            "HOME": str(home),
            "JWKIT_HOME": str(install_dir),
            "SHELL": "/bin/bash",
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        }
        return subprocess.run(
            ["bash", str(INSTALLER)],
            check=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_bash_uses_existing_profile_without_creating_bash_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".profile").write_text("export EXISTING_PROFILE=1\n")

            self.run_installer(home)

            self.assertIn(MARKER, (home / ".profile").read_text())
            self.assertIn(MARKER, (home / ".bashrc").read_text())
            self.assertFalse((home / ".bash_profile").exists())

    def test_bash_uses_existing_bash_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".profile").write_text("export EXISTING_PROFILE=1\n")
            (home / ".bash_profile").write_text("export EXISTING_BASH_PROFILE=1\n")

            self.run_installer(home)

            self.assertIn(MARKER, (home / ".bash_profile").read_text())
            self.assertIn(MARKER, (home / ".bashrc").read_text())
            self.assertNotIn(MARKER, (home / ".profile").read_text())

    def test_generated_update_command_does_not_block_an_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".profile").touch()
            update_command = home / ".jwkit" / "jwkit-update"
            update_command.parent.mkdir()
            update_command.write_text("#!/usr/bin/env bash\n")

            result = self.run_installer(home)

            self.assertNotIn("Local changes found", result.stdout)

    def test_rejects_filesystem_root_as_install_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(INSTALLER)],
                env=os.environ | {"HOME": tmp, "JWKIT_HOME": "/"},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing unsafe JWKIT_HOME", result.stderr)
