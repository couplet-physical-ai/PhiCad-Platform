from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.sh"
LOCK = REPO / "scripts" / "install" / "versions.lock.json"


class InstallerHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.config_home = self.root / "config"
        self.prefix = self.root / "prefix"
        self.bin_dir = self.home / ".local" / "bin"
        self.home.mkdir()
        self.config_home.mkdir()
        self.phi_config = self.config_home / "phi" / "config.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_installer(self, *args: str, script: Path = INSTALL, check: bool = True) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.config_home),
                "PHI_CONFIG": str(self.phi_config),
                "PYTHONNOUSERSITE": "1",
            }
        )
        completed = subprocess.run(
            [str(script), *args],
            cwd=REPO,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if check and completed.returncode:
            self.fail(f"installer failed ({completed.returncode}):\n{completed.stdout}")
        return completed

    def install(self, *extra: str) -> None:
        self.run_installer(
            "--prefix",
            str(self.prefix),
            "--bin-dir",
            str(self.bin_dir),
            "--lockfile",
            str(LOCK),
            "--allow-non-macos",
            "--no-config",
            *extra,
        )

    def test_dry_run_does_not_create_home_prefix_or_config(self) -> None:
        result = self.run_installer(
            "--prefix",
            str(self.prefix),
            "--bin-dir",
            str(self.bin_dir),
            "--lockfile",
            str(LOCK),
            "--allow-non-macos",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.prefix.exists())
        self.assertFalse(self.bin_dir.exists())
        self.assertFalse(self.phi_config.exists())
        self.assertIn("DRY-RUN", result.stdout)
        checked = self.run_installer(
            "--check",
            "--lockfile",
            str(LOCK),
            "--allow-non-macos",
        )
        self.assertEqual(checked.returncode, 0)
        self.assertFalse(self.prefix.exists())

    def test_prerequisite_check_detects_native_phicad_app(self) -> None:
        studio = self.home / "Applications" / "PhiCad.app"
        studio.mkdir(parents=True)
        result = self.run_installer(
            "--check",
            "--lockfile",
            str(LOCK),
            "--allow-non-macos",
        )
        self.assertIn(f"[ok]   PhiCad Studio + Verify: {studio}", result.stdout)

    def test_opt_in_config_merge_preserves_entries_and_mode(self) -> None:
        self.phi_config.parent.mkdir(parents=True)
        original = {"unrelated": {"keep": True}, "mcpServers": {"other": {"command": "other"}}}
        self.phi_config.write_text(json.dumps(original) + "\n", encoding="utf-8")
        os.chmod(self.phi_config, 0o640)
        self.run_installer(
            "--prefix",
            str(self.prefix),
            "--bin-dir",
            str(self.bin_dir),
            "--lockfile",
            str(LOCK),
            "--allow-non-macos",
            "--yes",
        )
        merged = json.loads(self.phi_config.read_text(encoding="utf-8"))
        self.assertEqual(merged["unrelated"], original["unrelated"])
        self.assertEqual(merged["mcpServers"]["other"], original["mcpServers"]["other"])
        entry = merged["mcpServers"]["phicad-platform"]
        self.assertEqual(Path(entry["command"]).name, "phicad-platform-mcp")
        self.assertEqual(entry["args"], [])
        self.assertNotIn("env", entry)
        self.assertEqual(stat.S_IMODE(self.phi_config.stat().st_mode), 0o640)
        backups = list(self.phi_config.parent.glob("config.json.phicad-platform.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o640)

    def test_release_is_versioned_and_update_is_lockfile_driven(self) -> None:
        self.install()
        manifest = json.loads((self.prefix / "install-manifest.json").read_text())
        self.assertTrue((self.prefix / "releases" / "0.1.0-dev.1").is_dir())
        self.assertTrue((self.prefix / "current").is_symlink())
        self.assertIn(str(self.prefix / "current"), manifest["files"])
        self.assertTrue((self.prefix / "current" / "docs" / "index.md").is_file())
        self.assertTrue((self.prefix / "current" / "THIRD_PARTY_NOTICES.md").is_file())
        for launcher in ("phicad-platform", "phicad-platform-mcp", "phicad-doctor", "phicad-update"):
            self.assertTrue((self.bin_dir / launcher).is_file(), launcher)
        version = subprocess.run(
            [str(self.bin_dir / "phicad-platform"), "--version"],
            env={**os.environ, "HOME": str(self.home), "PYTHONNOUSERSITE": "1"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
        )
        self.assertIn("0.1.0.dev1", version.stdout)

        updated_root = self.root / "updated-source"
        (updated_root / "scripts" / "install").mkdir(parents=True)
        for item in ("installer.py", "platform_server.py", "install.sh", "update.sh", "doctor.sh", "versions.lock.json"):
            source = REPO / "scripts" / "install" / item
            if item == "install.sh":
                # The source directory is enough for --source; this wrapper is
                # copied only to make the fixture look like a checkout.
                continue
            shutil.copy2(source, updated_root / "scripts" / "install" / item)
        lock = json.loads((updated_root / "scripts" / "install" / "versions.lock.json").read_text())
        lock["platform_version"] = "0.1.0-dev.2"
        (updated_root / "scripts" / "install" / "versions.lock.json").write_text(json.dumps(lock) + "\n")
        self.run_installer(
            "update",
            "--source",
            str(updated_root),
            "--prefix",
            str(self.prefix),
            "--bin-dir",
            str(self.bin_dir),
            "--lockfile",
            str(updated_root / "scripts" / "install" / "versions.lock.json"),
            "--allow-non-macos",
            "--no-config",
        )
        self.assertTrue((self.prefix / "releases" / "0.1.0-dev.2").is_dir())
        self.assertTrue((self.prefix / "releases" / "0.1.0-dev.1").is_dir())
        current = json.loads((self.prefix / "install-manifest.json").read_text())
        self.assertEqual(current["current_version"], "0.1.0-dev.2")

    def test_bad_update_does_not_move_current_release(self) -> None:
        self.install()
        before = os.readlink(self.prefix / "current")
        bad_lock = self.root / "bad-lock.json"
        bad_lock.write_text('{"schema_version": 1, "platform": {"version": "0.1.0-dev.2"}}\n')
        result = self.run_installer(
            "update",
            "--prefix",
            str(self.prefix),
            "--bin-dir",
            str(self.bin_dir),
            "--lockfile",
            str(bad_lock),
            "--allow-non-macos",
            "--no-config",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.prefix / "current"), before)
        self.assertFalse((self.prefix / "releases" / "0.1.0-dev.2").exists())

    def test_uninstall_only_removes_manifest_files(self) -> None:
        self.install()
        sentinel_prefix = self.prefix / "user-kept.txt"
        sentinel_bin = self.bin_dir / "user-kept"
        sentinel_prefix.write_text("do not remove")
        sentinel_bin.write_text("do not remove")
        sentinel_config = self.config_home / "unrelated.json"
        sentinel_config.write_text('{"keep": true}\n')
        self.run_installer(
            "uninstall",
            "--prefix",
            str(self.prefix),
            "--yes",
        )
        self.assertTrue(sentinel_prefix.exists())
        self.assertTrue(sentinel_bin.exists())
        self.assertTrue(sentinel_config.exists())
        self.assertFalse((self.bin_dir / "phicad-platform").exists())
        self.assertFalse((self.bin_dir / "phicad-platform-mcp").exists())
        self.assertFalse((self.prefix / "install-manifest.json").exists())

    def test_credential_directories_are_not_touched(self) -> None:
        credentials = self.home / ".claude" / "credentials.json"
        credentials.parent.mkdir()
        credentials.write_text('{"do_not_copy": true}\n')
        self.install()
        installed_files = [path for path in self.prefix.rglob("*") if path.is_file()]
        self.assertTrue(credentials.exists())
        self.assertFalse(any("credentials" in str(path).lower() for path in installed_files))


if __name__ == "__main__":
    unittest.main()
