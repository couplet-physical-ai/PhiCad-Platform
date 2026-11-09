from __future__ import annotations

import unittest
from pathlib import Path

from release.inventory import build_inventory
from release.validate_versions import default_lock_path


class InventoryTests(unittest.TestCase):
    def test_inventory_is_machine_readable_and_external_only(self) -> None:
        inventory = build_inventory(Path.cwd(), "0.1.0-dev.1", default_lock_path(Path.cwd()))
        self.assertEqual(inventory["inventory_type"], "sbom-ish-component-inventory")
        names = {component["name"] for component in inventory["components"]}
        self.assertEqual(names, {"PhiCad", "tscircuit"})
        self.assertTrue(all(component["external"] for component in inventory["components"]))
        self.assertTrue(all(not component["vendored"] for component in inventory["components"]))
        by_name = {component["name"]: component for component in inventory["components"]}
        self.assertEqual(
            by_name["PhiCad"]["product_surfaces"],
            ["PhiCad Studio", "PhiCad Verify"],
        )
        self.assertEqual(by_name["tscircuit"]["product_surface"], "Circuit Engine")
        self.assertEqual(by_name["tscircuit"]["additional_packages"]["@tscircuit/eval"], "0.0.1407")


if __name__ == "__main__":
    unittest.main()
