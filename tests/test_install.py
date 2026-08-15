"""Regression coverage for the POSIX installer startup-file handling."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
UNINSTALLER = ROOT / "uninstall.sh"
MARKER = "# jwkit PATH (added by jwkit's install.sh)"


class InstallPathTests(unittest.TestCase):
    def run_installer(self, home: Path) -> subprocess.CompletedProcess[str]:
        install_dir = home / ".jwkit"
        (install_dir / ".git").mkdir(parents=True)
        for name in ("ffinpaint", "ffrife", "ffv", "jwdl", "jwvideo-mux", "slverse"):
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

    def test_install_state_file_does_not_block_an_upgrade(self) -> None:
        # Real bug: any install that added at least one dependency writes
        # .jwkit-install-state inside the git-tracked JWKIT_HOME. Before this
        # fix, that file wasn't excluded from the "any local changes?" check,
        # so it looked like an untracked local change forever after - the
        # installer would refuse to fast-forward on every subsequent run,
        # permanently breaking jwkit-update for exactly the users most
        # likely to have needed the installer's dependency step in the
        # first place.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            install_dir = home / ".jwkit"
            (install_dir / ".git").mkdir(parents=True)
            for name in ("ffinpaint", "ffrife", "ffv", "jwdl", "jwvideo-mux", "slverse"):
                (install_dir / name).touch()
            (install_dir / ".jwkit-install-state").write_text("dependency_manager=brew\ndependency=ffmpeg\n")

            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/bin/sh\n"
                "for arg in \"$@\"; do\n"
                "  [ \"$arg\" = ls-files ] && { echo .jwkit-install-state; exit 0; }\n"
                "done\n"
                "exit 0\n"
            )
            fake_git.chmod(0o755)

            result = subprocess.run(
                ["bash", str(INSTALLER)],
                check=True,
                env=os.environ | {
                    "HOME": str(home),
                    "JWKIT_HOME": str(install_dir),
                    "SHELL": "/bin/bash",
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotIn("Local changes found", result.stdout)
            self.assertEqual((install_dir / ".jwkit-install-state").read_text(), "dependency_manager=brew\ndependency=ffmpeg\n")

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

    def test_uninstaller_removes_only_default_install_and_path_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            install_dir = home / ".jwkit"
            install_dir.mkdir()
            (install_dir / "jwdl").touch()
            config = home / ".config" / "jwkit" / "config.toml"
            config.parent.mkdir(parents=True)
            config.write_text("auto_update = false\n")
            profile = home / ".profile"
            profile.write_text(f"before\n{MARKER}\nexport PATH=\"{install_dir}:$PATH\"\nafter\n")

            subprocess.run(
                ["bash", str(UNINSTALLER)],
                check=True,
                env=os.environ | {"HOME": str(home), "JWKIT_HOME": str(install_dir)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertFalse(install_dir.exists())
            self.assertEqual(config.read_text(), "auto_update = false\n")
            self.assertEqual(profile.read_text(), "before\nafter\n")

    def test_uninstaller_keeps_legacy_dependencies_without_a_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            install_dir = home / ".jwkit"
            install_dir.mkdir()

            result = subprocess.run(
                ["bash", str(UNINSTALLER)],
                check=True,
                env=os.environ | {"HOME": str(home), "JWKIT_HOME": str(install_dir)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Existing dependencies not recorded", result.stdout)
