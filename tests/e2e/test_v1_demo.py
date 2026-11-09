#!/usr/bin/env python3
"""End-to-end tests for the V1 demo capture surface.

These tests use the local fake core by default, so they do not require Bun, Circuit Engine, KiCad,
or PhiCad Verify.  A real tool run is a separate evidence capture, not a prerequisite for this
plumbing test.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "demo" / "v1_demo.py"
TERMINAL_DEMO = ROOT / "scripts" / "demo" / "terminal-demo.sh"
FAKE_CORE = Path(__file__).with_name("fake_phicad_core.py")
VIDEO_RENDERER = ROOT / "scripts" / "demo" / "render_video.py"


def load_video_renderer():
    spec = importlib.util.spec_from_file_location("phicad_demo_video", VIDEO_RENDERER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load video renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_command() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_CORE))}"


class V1DemoHarnessTests(unittest.TestCase):
    def run_harness(self, run_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HARNESS), "--run-dir", str(run_dir), "--engine-command", fake_command(), *extra],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_fake_engine_capture_has_complete_manifest_and_transcript(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phicad-v1-test-") as temp:
            run_dir = Path(temp) / "capture"
            completed = self.run_harness(run_dir)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("PHICAD / V1 SMALL-BOARD DEMO", completed.stdout)
            self.assertIn("build + PhiCad Verify: PASS", completed.stdout)

            required = read_json(ROOT / "examples/fixtures/demo-v1-led.expected-manifest.json")["required_paths"]
            for relative in required:
                self.assertTrue((run_dir / relative).is_file(), relative)

            commands = [json.loads(line) for line in (run_dir / "commands.jsonl").read_text().splitlines()]
            labels = [item["label"] for item in commands]
            for required_label in ("engine-version", "engine-check", "build-and-verify"):
                self.assertIn(required_label, labels)
            self.assertLess(labels.index("engine-version"), labels.index("engine-check"))
            self.assertLess(labels.index("engine-check"), labels.index("build-and-verify"))
            for item in commands:
                self.assertEqual(item["command"], shlex.join(item["argv"]))
                for stream in ("stdout", "stderr"):
                    capture = run_dir / item[f"{stream}_file"]
                    self.assertEqual(item[f"{stream}_bytes"], capture.stat().st_size)
                    self.assertEqual(item[f"{stream}_sha256"], file_sha256(capture))
                self.assertGreaterEqual(item["duration_ms"], 0)

            diagnostics = read_json(run_dir / "diagnostics.json")
            self.assertTrue(diagnostics["fabrication_ready"] is False)
            self.assertEqual(diagnostics["phicad_native_materialization"]["status"], "unavailable-v1")
            self.assertTrue(diagnostics["fixture_match"]["match"] is False)  # fake is intentionally a PASS
            self.assertEqual(diagnostics["observed"]["engine_check"]["finding_codes"], [])
            self.assertEqual(diagnostics["observed"]["build_and_verify"]["verification_skipped"], False)

            manifest = read_json(run_dir / "manifest.json")
            self.assertTrue(manifest["fixture_contract"]["match"])
            manifest_paths = {entry["path"] for entry in manifest["files"]}
            self.assertNotIn("manifest.json", manifest_paths)
            for entry in manifest["files"]:
                path = run_dir / entry["path"]
                self.assertTrue(path.is_file(), entry["path"])
                self.assertEqual(entry["bytes"], path.stat().st_size)
                self.assertEqual(entry["sha256"], file_sha256(path))

            versions = read_json(run_dir / "tool-versions.json")
            self.assertEqual(versions["engine"]["reported_version"], "fake-phicad-core 0.1.0")
            self.assertEqual(versions["harness"]["python"], f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    def test_existing_run_directory_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phicad-v1-test-") as temp:
            run_dir = Path(temp) / "capture"
            first = self.run_harness(run_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            marker = run_dir / "marker.txt"
            marker.write_text("do not overwrite", encoding="utf-8")
            second = self.run_harness(run_dir)
            self.assertEqual(second.returncode, 2)
            self.assertIn("refusing to overwrite", second.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "do not overwrite")

    def test_terminal_demo_can_use_the_same_fake_binary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phicad-v1-terminal-") as temp:
            run_dir = Path(temp) / "capture"
            env = os.environ.copy()
            env["PHICAD_ENGINE_CMD"] = fake_command()
            env["PHICAD_DEMO_RUN_DIR"] = str(run_dir)
            completed = subprocess.run(
                ["bash", str(TERMINAL_DEMO)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("capture sequence: source -> engine check -> build + PhiCad Verify", completed.stdout)
            self.assertIn("build + PhiCad Verify: PASS", completed.stdout)
            self.assertTrue((run_dir / "manifest.json").is_file())

    def test_video_frames_are_derived_from_checked_evidence(self) -> None:
        renderer = load_video_renderer()
        with tempfile.TemporaryDirectory(prefix="phicad-video-test-") as temp:
            run_dir = Path(temp)
            (run_dir / "diagnostics.json").write_text(json.dumps({
                "fixture_match": {"match": True},
                "observed": {
                    "engine_check": {"ok": True, "finding_codes": ["tsc.warning"]},
                    "build_and_verify": {
                        "ok": True,
                        "verification_errors": 0,
                        "verification_warnings": 1,
                        "verification_finding_codes": ["drc.warning"],
                    },
                },
            }))
            (run_dir / "tool-versions.json").write_text(json.dumps({"verifier": {"reported_version": "10.99.0"}}))
            (run_dir / "run.json").write_text(json.dumps({"run_id": "test-run", "duration_ms": 42}))
            (run_dir / "manifest.json").write_text(json.dumps({"fabrication_ready": False}))
            slides = renderer.frames(run_dir)
            self.assertEqual(len(slides), 6)
            rendered = "".join(svg for _, svg in slides)
            self.assertIn("tsc.warning", rendered)
            self.assertIn("drc.warning", rendered)
            self.assertIn("NOT CLAIMED", rendered)

    def test_reference_fixture_preserves_non_fabrication_claims(self) -> None:
        fixture = read_json(ROOT / "examples/fixtures/demo-v1-led.expected-diagnostics.json")
        self.assertEqual(fixture["expected"]["engine_check"]["finding_codes"], [
            "tsc.schematic_missing_sheet_warning",
            "tsc.source_pin_missing_trace_warning",
            "tsc.source_pin_missing_trace_warning",
            "tsc.supplier_footprint_mismatch_warning",
            "tsc.supplier_footprint_mismatch_warning",
        ])
        pinned = fixture["expected"]["build_and_verify_with_pinned_kicad"]
        self.assertTrue(pinned["ok"])
        self.assertEqual(pinned["verification_errors"], 0)
        self.assertIn("verify.kicad_cli_missing", {item["code"] for item in fixture["known_findings"]})
        self.assertTrue(any("not fabrication-ready" in claim for claim in fixture["claims_not_made"]))
        self.assertIn("Native PhiCad materialization is unavailable in V1", " ".join(fixture["claims_not_made"]))


if __name__ == "__main__":
    unittest.main()
