from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from release.verify_reproducibility import verify


class ReproducibilityTests(unittest.TestCase):
    def test_fixed_epoch_produces_identical_artifacts(self) -> None:
        # The helper owns its temporary output directories; this context makes the
        # test explicit about not leaving build products in the repository.
        with tempfile.TemporaryDirectory(prefix="phicad-repro-test-"):
            verify(Path.cwd(), "0.1.0-dev.1", epoch=789)


if __name__ == "__main__":
    unittest.main()
