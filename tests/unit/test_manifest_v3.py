from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from phicad_platform.cli import _parser
from phicad_platform.contracts import DIAGNOSTIC_ORIGINS, DiagnosticCounts
from phicad_platform.manifest import (
    MANIFEST_SCHEMA_VERSION,
    ManifestError,
    NativeApply,
    canonical_json_bytes,
    create_manifest,
    load_manifest,
    sha256_bytes,
    verify_manifest,
    write_manifest,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def sample(**kwargs):
    return create_manifest(
        design_id="v3", source_hash="a" * 64, circuit_json_hash="b" * 64,
        native_revision="existing-revision", native_artifact_hash="c" * 64,
        artifacts=(), tool_versions={"phicad-studio": "0.1.0", "phicad-verify": "0.1.0"},
        diagnostics={origin: DiagnosticCounts() for origin in DIAGNOSTIC_ORIGINS},
        diagnostic_status={"tscircuit": "not-run", "kicad": "unavailable"}, **kwargs,
    )


def test_v3_roundtrip_self_hash_and_native_names(tmp_path):
    manifest = sample()
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    loaded = load_manifest(path)
    assert loaded.to_dict() == manifest.to_dict()
    assert MANIFEST_SCHEMA_VERSION == loaded.manifest_version == 3
    assert loaded.native_artifact is loaded.studio
    data = loaded.to_dict()
    assert data["native_revision"] == "existing-revision"
    assert data["native_artifact_hash"] == "c" * 64
    assert data["tool_versions"] == {"phicad": "0.1.0"}
    assert not {"studio", "studio_hash", "studio_path", "studio_revision"} & data.keys()
    # Insertion order and file whitespace do not enter the self-hash.
    path.write_text(json.dumps(dict(reversed(list(data.items())))))
    assert load_manifest(path).calculated_hash() == loaded.manifest_hash
    assert loaded.diagnostic_status == {"tscircuit": "not-run", "kicad": "unavailable"}
    changed = replace(loaded, native_apply=NativeApply(status="rejected"), manifest_hash=None)
    assert changed.calculated_hash() != loaded.calculated_hash()


def test_v2_read_keeps_original_hash_and_records_default_note():
    path = FIXTURES / "manifest-v2.json"
    loaded = load_manifest(path)
    assert loaded.manifest_version == 2
    assert loaded.native_apply.status == "unavailable-v1"
    assert loaded.to_dict() == json.loads(path.read_text())
    assert loaded.native_artifact.sha256 == loaded.to_dict()["studio_hash"]
    verified = verify_manifest(path, verify_files=False).to_dict()
    assert verified["valid"]
    assert "defaulted to unavailable-v1" in verified["compatibility_notes"][0]
    assert verified["native_apply"]["applied_revision"] is None
    assert loaded.diagnostics["kicad"].warnings == 4
    assert loaded.diagnostics["tscircuit"].warnings == 5


@pytest.mark.parametrize("changes", [
    {"status": "unknown"}, {"status": None},
    {"status": "applied"}, {"status": "applied", "undo_entries": 1},
    {"status": "applied", "applied_revision": "abc"},
    {"status": "applied", "applied_revision": "abc", "undo_entries": 2},
    {"undo_entries": True}, {"undo_entries": -1}, {"undo_entries": 1.0},
    {"undo_entries": 1}, {"applied_revision": "abc"},
    {"base_revision": ""}, {"base_revision": 1}, {"applied_revision": ""},
    {"plan_hash": "bad"}, {"plan_hash": "A" * 64}, {"plan_hash": 1},
    {"plan_path": "/absolute"}, {"plan_path": "../escape"}, {"plan_path": ""},
    {"plan_path": 1}, {"rejections": {}}, {"rejections": ["bad"]},
    {"rejections": [{"code": "bad"}]},
    {"rejections": [{"code": "bad", "element": "pcb_cutout", "detail": 1}]},
])
def test_native_apply_fails_closed(changes):
    with pytest.raises(ManifestError):
        NativeApply.from_mapping({**NativeApply().to_dict(), **changes})


def test_applied_schema_accounting_is_valid_but_not_a_platform_capability(tmp_path):
    state = NativeApply(status="applied", applied_revision="f" * 40, undo_entries=1)
    path = tmp_path / "manifest.json"
    write_manifest(sample(native_apply=state), path)
    assert load_manifest(path).native_apply == state


@pytest.mark.parametrize("mutation", [
    lambda d: d.pop("native_apply"),
    lambda d: d["native_apply"].pop("undo_entries"),
    lambda d: d["native_apply"].update(extra=True),
    lambda d: d["diagnostics"].update(openpcb={"errors": 0}),
    lambda d: d["diagnostics"].pop("kicad"),
    lambda d: d["diagnostic_status"].update(openpcb="passed"),
    lambda d: d["diagnostic_status"].update(kicad="guessed"),
    lambda d: d.update(studio_hash="c" * 64),
    lambda d: d["native_artifact"].update(revision="different"),
])
def test_invalid_v3_remains_invalid_even_if_rehashed(tmp_path, mutation):
    data = sample().to_dict()
    mutation(data)
    data.pop("manifest_hash")
    data["manifest_hash"] = sha256_bytes(canonical_json_bytes(data))
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    assert not verify_manifest(path, verify_files=False).valid


def test_legacy_create_names_and_conflicting_tool_roles():
    old = create_manifest(
        design_id="old-call", source_hash="a" * 64, circuit_json_hash="b" * 64,
        studio_revision="r1", studio_hash="c" * 64, studio_path="board.kicad_pcb",
        artifacts=(), tool_versions={"phicad-verify": "0.1.0"},
        diagnostics={origin: DiagnosticCounts() for origin in DIAGNOSTIC_ORIGINS},
    )
    assert old.to_dict()["native_artifact_path"] == "board.kicad_pcb"
    with pytest.raises(ManifestError, match="conflicting"):
        replace(old, tool_versions={"phicad-studio": "0.1", "phicad-verify": "0.2"})
    with pytest.raises(ManifestError, match="conflicting"):
        sample(studio_hash="d" * 64)


@pytest.mark.parametrize("flags", [
    ["--studio", "board.kicad_pcb", "--studio-revision", "r1"],
    ["--native-artifact", "board.kicad_pcb", "--native-revision", "r1"],
    ["--native-artifact-path", "board.kicad_pcb", "--native-revision", "r1"],
    ["--native-artifact-hash", "c" * 64, "--native-revision", "r1"],
    ["--studio-hash", "c" * 64, "--studio-revision", "r1"],
])
def test_native_cli_flags_and_legacy_aliases(flags):
    args = _parser().parse_args(["build-check", "--source", "s.tsx", "--circuit-json", "c.json",
                                 "--output-dir", "out", *flags])
    assert args.studio_revision == "r1"
    assert args.studio == Path("board.kicad_pcb") or args.studio_hash == "c" * 64


def test_committed_real_led_fixture_verifies_every_file():
    path = Path(__file__).parents[2] / "examples/fixtures/demo-v1-led.manifest-v3.json"
    checked = verify_manifest(path)
    assert checked.valid, checked.errors
    manifest = checked.manifest
    assert manifest.native_apply.status == "rejected"
    assert manifest.native_apply.applied_revision is None
    assert manifest.native_apply.undo_entries == 0
    assert manifest.artifact_hashes["kicad-pcb"] == "8e6067d5f987b8639ec80015cea94e5ae5b755846e2754af9f50e5c4cd447bdb"
    assert manifest.diagnostics["kicad"].warnings == 4
    assert manifest.diagnostics["tscircuit"].warnings == 5
    assert {r["element"] for r in manifest.native_apply.rejections} == {
        "pcb_trace", "schematic_component", "schematic_group", "schematic_port", "schematic_trace",
    }
