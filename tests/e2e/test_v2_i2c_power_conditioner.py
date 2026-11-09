#!/usr/bin/env python3
"""Real-tool evidence check for the electrically complete V2 example.

Unlike the V1 harness plumbing test, this test never replaces the Circuit Engine or
KiCad with a fake. It skips when the pinned local tools are absent; a skip is not a
verification pass. The checked-in fixtures are observations from the real pinned run.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "demo-v2-i2c-power-conditioner.tsx"
DIAGNOSTICS = ROOT / "examples" / "fixtures" / "demo-v2-i2c-power-conditioner.expected-diagnostics.json"
MANIFEST = ROOT / "examples" / "fixtures" / "demo-v2-i2c-power-conditioner.expected-manifest.json"
DEFAULT_BUN = Path("/opt/homebrew/bin/bun")
DEFAULT_ENGINE = Path("/opt/phicad/core/cli.mjs")
DEFAULT_KICAD = Path(
    "/opt/phicad/"
    "kicad/PhiCad.app/Contents/MacOS/kicad-cli"
)


def finding_counts(findings: list[dict[str, object]]) -> tuple[int, int, Counter[str]]:
    """Return error/warning totals and warning/error code multiplicities."""
    errors = sum(finding["severity"] == "error" for finding in findings)
    warnings = sum(finding["severity"] == "warning" for finding in findings)
    codes = Counter(
        str(finding["code"])
        for finding in findings
        if finding["severity"] in {"error", "warning"}
    )
    return errors, warnings, codes


class V2I2cPowerConditionerRealToolTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.diagnostics = json.loads(DIAGNOSTICS.read_text())
        self.manifest = json.loads(MANIFEST.read_text())
        self.bun = Path(os.environ.get("PHICAD_BUN", DEFAULT_BUN))
        self.engine = Path(os.environ.get("PHICAD_CORE_CLI", DEFAULT_ENGINE))
        self.kicad = Path(os.environ.get("PHICAD_KICAD_CLI", DEFAULT_KICAD))

    def require_real_tools(self) -> None:
        missing = [
            str(path)
            for path in (self.bun, self.engine, self.kicad)
            if not path.is_file() or not os.access(path, os.X_OK)
        ]
        if missing:
            self.skipTest(
                "real V2 verification not run: missing pinned tool(s): "
                + ", ".join(missing)
            )

    def run_engine(self, command: str) -> tuple[int, dict[str, object]]:
        environment = os.environ.copy()
        environment["PHICAD_KICAD_CLI"] = str(self.kicad)
        result = subprocess.run(
            [str(self.bun), str(self.engine), command, str(EXAMPLE), "--json"],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        self.assertTrue(result.stdout, msg=result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_real_engine_and_kicad_match_v2_fixtures(self) -> None:
        self.require_real_tools()

        source_sha256 = hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
        self.assertEqual(source_sha256, self.manifest["source_sha256"])

        check_expected = self.diagnostics["expected"]["engine_check"]
        check_exit, check = self.run_engine("check")
        self.assertEqual(check_exit, check_expected["exit_code"])
        self.assertEqual(check["ok"], check_expected["ok"])
        self.assertEqual(check["circuit"], check_expected["circuit"])
        check_errors, check_warnings, check_codes = finding_counts(check["findings"])
        self.assertEqual(check_errors, check_expected["engine_errors"])
        self.assertEqual(check_warnings, check_expected["engine_warnings"])
        self.assertEqual(sorted(check_codes), check_expected["finding_codes"])

        build_expected = self.diagnostics["expected"]["build_and_verify_with_pinned_kicad"]
        build_exit, build = self.run_engine("build")
        self.assertEqual(build_exit, build_expected["exit_code"])
        self.assertEqual(build["ok"], build_expected["ok"])
        self.assertEqual(build["engine"]["ok"], build_expected["engine_ok"])
        engine_errors, engine_warnings, engine_codes = finding_counts(build["engine"]["findings"])
        self.assertEqual(engine_errors, build_expected["engine_errors"])
        self.assertEqual(engine_warnings, build_expected["engine_warnings"])
        self.assertEqual(sorted(engine_codes), build_expected["engine_finding_codes"])

        verification = build["verification"]
        self.assertEqual(verification["ok"], build_expected["verification_ok"])
        self.assertEqual(verification["skipped"], build_expected["verification_skipped"])
        drc_errors, drc_warnings, drc_codes = finding_counts(verification["findings"])
        self.assertEqual(drc_errors, build_expected["verification_errors"])
        self.assertEqual(drc_warnings, build_expected["verification_warnings"])
        self.assertEqual(dict(drc_codes), build_expected["verification_finding_codes"])

        for key, value in self.manifest["expected_circuit"].items():
            if key != "layers":
                self.assertEqual(build["circuit"][key], value)


if __name__ == "__main__":
    unittest.main()
