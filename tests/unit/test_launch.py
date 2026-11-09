from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phicad_platform.contracts import DIAGNOSTIC_ORIGINS, ArtifactRecord, DiagnosticCounts
from phicad_platform.launch import (
    LAUNCH_SCHEMA,
    LaunchError,
    build_launch_plan,
    make_deep_link,
    open_view,
    parse_deep_link,
)
from phicad_platform.manifest import create_manifest, sha256_file, sha256_path, write_manifest


class LaunchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="phicad-launch-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "design.tsx"
        self.circuit = self.root / "circuit.json"
        self.studio = self.root / "studio.json"
        self.artifact = self.root / "board.kicad_pcb"
        self.source.write_text("export default {};\n", encoding="utf-8")
        self.circuit.write_text('{"elements":[]}\n', encoding="utf-8")
        self.studio.write_text('{"revision":7}\n', encoding="utf-8")
        self.artifact.write_text("(kicad_pcb)\n", encoding="utf-8")
        manifest = create_manifest(
            design_id="cross-view-demo",
            source_hash=sha256_path(self.source),
            circuit_json_hash=sha256_path(self.circuit),
            studio_revision="7",
            studio_hash=sha256_path(self.studio),
            artifacts=(ArtifactRecord("kicad", self.artifact.name, sha256_path(self.artifact)),),
            tool_versions={"phicad-platform": "0.1.0-dev.1"},
            diagnostics={origin: DiagnosticCounts() for origin in DIAGNOSTIC_ORIGINS},
            source_path=str(self.source),
            circuit_json_path=str(self.circuit),
            studio_path=str(self.studio),
            configuration={"artifact_root": str(self.root), "project_root": str(self.root)},
        )
        self.manifest_path = self.root / "phicad.design.json"
        write_manifest(manifest, self.manifest_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @patch("phicad_platform.launch._which_or_path", return_value="/usr/bin/true")
    def test_phi_plan_is_manifest_bound_and_contains_no_credentials(self, _which: object) -> None:
        plan = build_launch_plan(self.manifest_path, "phi", source_view="studio")
        self.assertTrue(plan.available)
        self.assertEqual(plan.request["schema"], LAUNCH_SCHEMA)
        self.assertEqual(plan.request["source_view"], "studio")
        self.assertEqual(plan.request["target_view"], "phi")
        self.assertEqual(plan.request["project"]["expected_manifest_sha256"], sha256_file(self.manifest_path))
        serialized = str(plan.to_dict()).lower()
        for forbidden in ("api_key", "password", "bearer", "oauth", "credential"):
            self.assertNotIn(forbidden, serialized)

    @patch("phicad_platform.launch._which_or_path", return_value="/usr/bin/true")
    def test_studio_and_verify_share_one_native_phicad_authority(self, _which: object) -> None:
        studio = build_launch_plan(self.manifest_path, "studio")
        verify = build_launch_plan(self.manifest_path, "verify")
        self.assertEqual(studio.command, verify.command)
        self.assertEqual(studio.request["expected"]["native_design_id"], "cross-view-demo")
        self.assertNotIn("studio_design_id", studio.request["expected"])
        self.assertEqual(LAUNCH_SCHEMA, "io.github.couplet-physical-ai.phicad.platform-launch/v3")

    @patch("phicad_platform.launch._which_or_path", return_value="/usr/bin/true")
    def test_dry_run_does_not_spawn(self, _which: object) -> None:
        with patch("phicad_platform.launch.subprocess.Popen") as popen:
            result = open_view(
                manifest_path=str(self.manifest_path),
                target_view="circuit-source",
                dry_run=True,
            )
        popen.assert_not_called()
        self.assertFalse(result["executed"])
        self.assertTrue(result["deep_link"].startswith("phicad://open?"))

    def test_stale_manifest_hash_is_rejected_before_resolution(self) -> None:
        with self.assertRaises(LaunchError) as raised:
            build_launch_plan(self.manifest_path, "docs", expected_manifest_sha256="0" * 64)
        self.assertEqual(raised.exception.code, "stale_handoff")

    @patch("phicad_platform.launch._which_or_path", return_value="/usr/bin/true")
    def test_deep_link_round_trip(self, _which: object) -> None:
        plan = build_launch_plan(self.manifest_path, "verify", source_view="phi", focus=False)
        parsed = parse_deep_link(make_deep_link(plan))
        self.assertEqual(parsed["target_view"], "verify")
        self.assertEqual(parsed["source_view"], "phi")
        self.assertEqual(parsed["expected_manifest_sha256"], sha256_file(self.manifest_path))

    def test_deep_link_rejects_commands_and_unknown_parameters(self) -> None:
        uri = "phicad://open?manifest=/tmp/x&sha256=%s&view=docs&command=rm" % ("0" * 64)
        with self.assertRaises(LaunchError) as raised:
            parse_deep_link(uri)
        self.assertEqual(raised.exception.code, "invalid_uri")


if __name__ == "__main__":
    unittest.main()
