from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from phicad_platform.cli import main
from phicad_platform.contracts import DIAGNOSTIC_ORIGINS, ArtifactRecord, DiagnosticCounts
from phicad_platform.launch import LaunchError, build_launch_plan, execute_launch
from phicad_platform.manifest import create_manifest, sha256_file, write_manifest


@pytest.fixture
def manifest_path(tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)\n")
    manifest = create_manifest(
        design_id="preview", source_hash="a" * 64, circuit_json_hash="b" * 64,
        native_revision="r1", native_artifact_hash=sha256_file(board), native_artifact_path=str(board),
        artifacts=(ArtifactRecord("kicad-pcb", board.name, sha256_file(board)),),
        tool_versions={"phicad": "0.1.0"}, diagnostics={o: DiagnosticCounts() for o in DIAGNOSTIC_ORIGINS},
    )
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    return path


def test_preview_is_only_operator_configured(manifest_path, monkeypatch, tmp_path):
    executable = tmp_path / "preview with spaces"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PHICAD_CIRCUIT_PREVIEW", str(executable))
    plan = build_launch_plan(manifest_path, "preview")
    assert plan.available
    assert plan.command == (str(executable), "--manifest", str(manifest_path),
                            "--expected-manifest-sha256", sha256_file(manifest_path))
    assert plan.request["schema"] == "io.github.couplet-physical-ai.phicad.platform-launch/v3"
    assert str(executable) not in json.dumps(plan.request)
    with patch("phicad_platform.launch.subprocess.Popen") as spawn:
        execute_launch(plan, dry_run=True)
    spawn.assert_not_called()


@pytest.mark.parametrize("configured", [None, "preview", "/no/such/executable", "https://example.com", "/usr/bin/true --extra"])
def test_preview_unavailable_has_reason(manifest_path, monkeypatch, configured):
    monkeypatch.delenv("PHICAD_CIRCUIT_PREVIEW", raising=False)
    if configured is not None:
        monkeypatch.setenv("PHICAD_CIRCUIT_PREVIEW", configured)
    plan = build_launch_plan(manifest_path, "preview")
    assert not plan.available
    assert plan.unavailable_reason
    assert not plan.command


def test_preview_stale_manifest_exits_three(manifest_path, capsys):
    assert main(["open", "preview", "--manifest", str(manifest_path),
                 "--expected-manifest-sha256", "0" * 64, "--dry-run"]) == 3
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "stale_handoff"


def test_preview_stale_artifact_precedes_executable_resolution(manifest_path):
    (manifest_path.parent / "board.kicad_pcb").write_text("changed")
    with pytest.raises(LaunchError) as caught:
        build_launch_plan(manifest_path, "preview")
    assert caught.value.code == "stale_handoff"


@pytest.mark.parametrize("field", ["native_revision", "native_design_id", "native_sha256"])
def test_execute_rechecks_expected_identity(manifest_path, field):
    plan = build_launch_plan(manifest_path, "docs")
    request = dict(plan.request)
    request["expected"] = {**request["expected"], field: "stale"}
    with pytest.raises(LaunchError) as caught:
        execute_launch(replace(plan, request=request), dry_run=True)
    assert caught.value.code == "stale_handoff"


def test_native_path_discovery_ignores_environment_override(manifest_path, monkeypatch, tmp_path):
    executable = tmp_path / "phicad"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("PHICAD_BIN", "/wrong/never-used")
    studio = build_launch_plan(manifest_path, "studio")
    verify = build_launch_plan(manifest_path, "verify")
    assert studio.command == verify.command == (str(executable), "open", str(tmp_path / "board.kicad_pcb"))
