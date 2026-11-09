from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from release.package import build_release
from release.validate_versions import default_lock_path, load_lock


class PackageTests(unittest.TestCase):
    def test_lock_contains_required_external_components(self) -> None:
        lock = load_lock(default_lock_path(Path.cwd()))
        self.assertEqual(
            {item["name"].lower() for item in lock["components"]},
            {"phicad", "tscircuit"},
        )
        self.assertTrue(all(item["vendored"] is False for item in lock["components"]))

    def test_package_has_manifest_checksum_and_no_upstream_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phicad-package-test-") as temporary:
            result = build_release(Path.cwd(), Path(temporary), "0.1.0-dev.1", epoch=123)
            archive = result["archive"]
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest = json.loads(result["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["archive"]["sha256"], digest)
            self.assertEqual(result["checksum"].read_text(encoding="utf-8"), "%s  %s\n" % (digest, archive.name))
            components = {item["name"]: item for item in manifest["external_components"]}
            self.assertEqual(
                components["PhiCad"]["product_surfaces"],
                ["PhiCad Studio", "PhiCad Verify"],
            )

            with tarfile.open(archive, mode="r:gz") as tar:
                names = tar.getnames()
            self.assertTrue(any(name.endswith("/release/release-manifest.json") for name in names))
            self.assertTrue(any(name.endswith("/release/component-inventory.json") for name in names))
            self.assertTrue(any(name.endswith("/release/versions.lock") for name in names))
            self.assertFalse(any("PhiCad/" in name or "tscircuit/" in name for name in names))

    def test_package_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phicad-package-test-") as temporary:
            root = Path(temporary)
            first = build_release(Path.cwd(), root / "first", "0.1.0-dev.1", epoch=456)
            second = build_release(Path.cwd(), root / "second", "0.1.0-dev.1", epoch=456)
            self.assertEqual(first["archive"].read_bytes(), second["archive"].read_bytes())
            self.assertEqual(first["manifest"].read_bytes(), second["manifest"].read_bytes())
            self.assertEqual(first["inventory"].read_bytes(), second["inventory"].read_bytes())


if __name__ == "__main__":
    unittest.main()
