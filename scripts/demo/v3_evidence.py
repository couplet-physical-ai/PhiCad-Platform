#!/usr/bin/env python3
"""Capture real V3 service, stdio MCP, launch, and plan-only evidence.

Requires installed native tooling; no download or mock fallback. Outputs are fresh.
The older video/fresh-Phi receipts remain historical V2 evidence, not V3 acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from phicad_platform.contracts import ArtifactRecord, BuildCheckRequest, DiagnosticCounts  # noqa: E402
from phicad_platform.manifest import (  # noqa: E402
    create_manifest,
    load_manifest,
    sha256_file,
    sha256_path,
    verify_manifest,
    write_manifest,
)
from phicad_platform.orchestrator import build_check, design_apply_plan, load_platform_config  # noqa: E402


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def run(argv, *, env, input=None):
    return subprocess.run(argv, input=input, capture_output=True, text=True, env=env, timeout=65, check=False)


def summary(manifest):
    return {key: manifest.to_dict()[key] for key in (
        "manifest_version", "manifest_hash", "diagnostics", "diagnostic_status", "artifact_hashes", "native_apply",
    )}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--verify-core", type=Path, required=True)
    parser.add_argument("--kicad-cli", type=Path, required=True)
    parser.add_argument("--phicad", type=Path, required=True)
    parser.add_argument("--phicad-commit", required=True)
    parser.add_argument("--verify-commit", required=True)
    args = parser.parse_args()
    out = args.run_dir.resolve()
    out.mkdir(exist_ok=False)
    original = args.input_manifest.resolve()
    checked = verify_manifest(original)
    if not checked.valid:
        raise RuntimeError(checked.errors)
    prior = checked.manifest
    circuit = out / "circuit.json"
    source = out / "source.tsx"
    circuit.write_bytes(Path(prior.circuit_json_path).read_bytes())
    source.write_bytes(Path(prior.source_path).read_bytes())
    native = out / "native"
    native.mkdir()
    # Existing generated board is a plan target, not an applied native revision.
    board = native / "board.kicad_pcb"
    prior_board = next(a for a in prior.artifacts if a.kind == "kicad-pcb")
    board.write_bytes((Path(prior.configuration["artifact_root"]) / prior_board.path).read_bytes())
    (native / "board.kicad_pro").write_text("{}\n")
    native_before = sha256_path(native)
    bun = shutil.which("bun")
    if not bun:
        raise RuntimeError("installed Bun is required")
    config_path = out / "platform.json"
    save(config_path, {
        "versions_lock": str(ROOT / "versions.lock.json"),
        "verify_cli": {
            "command": [bun, str(args.verify_core.resolve()), "verify", "--circuit-json", "{circuit_json}",
                        "--output-dir", "{output_dir}", "--result", "{result}"],
            "env_allowlist": ["PATH", "HOME", "TMPDIR", "LANG", "PHICAD_KICAD_CLI"],
            "environment": {"PHICAD_KICAD_CLI": str(args.kicad_cli.resolve())},
        },
        "apply_cli": {"executable": str(args.phicad.resolve())},
    })
    config = load_platform_config(config_path)
    manifest_path = out / "check" / "design.manifest.json"
    result = asyncio.run(build_check(BuildCheckRequest(
        source=source, circuit_json=circuit, output_dir=manifest_path.parent, manifest_path=manifest_path,
        design_id=prior.design_id, studio_revision="unavailable-v1", studio_path=board,
    ), config))
    save(out / "build-check.json", result.to_dict())
    assert verify_manifest(manifest_path).valid
    applied = asyncio.run(design_apply_plan(manifest_path=manifest_path, project=native,
                                           output_dir=out / "apply", config=config))
    save(out / "apply.json", applied)
    assert applied["status"] in {"planned", "rejected"}, applied
    assert native_before == sha256_path(native)
    planned_manifest = load_manifest(Path(applied["manifest_path"]))
    assert verify_manifest(Path(applied["manifest_path"])).valid
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    env["PATH"] = str(args.phicad.resolve().parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = str(ROOT / "src")
    cli = [sys.executable, "-m", "phicad_platform.cli"]
    launches = {}
    for target in ("studio", "verify", "preview"):
        process = run(cli + ["open", target, "--manifest", str(manifest_path), "--dry-run"], env=env)
        save(out / (target + "-launch.json"), {"exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr})
        launches[target] = json.loads(process.stdout) if process.returncode == 0 else json.loads(process.stderr)
    assert launches["studio"]["command"] == launches["verify"]["command"]
    # Operator executable probe: do not claim the actual Preview surface rendered.
    probe_env = {**env, "PHICAD_CIRCUIT_PREVIEW": "/usr/bin/true"}
    probe = run(cli + ["open", "preview", "--manifest", str(manifest_path), "--dry-run"], env=probe_env)
    assert probe.returncode == 0, probe.stderr
    save(out / "preview-probe.json", json.loads(probe.stdout))
    stale = run(cli + ["open", "preview", "--manifest", str(manifest_path), "--dry-run",
                       "--expected-manifest-sha256", "0" * 64], env=env)
    assert stale.returncode == 3
    assert json.loads(stale.stderr)["error"]["code"] == "stale_handoff"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "design_manifest_verify", "arguments": {"manifest_path": str(manifest_path)}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "design_apply_plan", "arguments": {"manifest_path": str(manifest_path), "project": str(native),
                "output_dir": str(out / "mcp-apply"), "config_path": str(config_path)}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "design_apply_plan", "arguments": {"commit": True}}},
    ]
    stdio = run([sys.executable, "-m", "phicad_platform.mcp_server"], env=env,
                input="".join(json.dumps(r) + "\n" for r in requests))
    assert stdio.returncode == 0, stdio.stderr
    (out / "mcp-response.jsonl").write_text(stdio.stdout)
    responses = {r["id"]: r for r in map(json.loads, stdio.stdout.splitlines())}
    assert responses[3]["result"]["structuredContent"]["valid"]
    assert responses[4]["result"]["structuredContent"]["status"] == applied["status"]
    assert responses[5]["result"]["structuredContent"]["error"]["code"] == "commit_refused"
    assert sha256_path(native) == native_before
    captured = datetime.now(timezone.utc).isoformat()
    docs = ROOT / "docs/assets/demo"
    common = {"schema_version": 3, "captured_at": captured,
              "claims_not_made": ["No applied native revision or undo entry.", "No fabrication readiness or manufacturability verdict.",
                                  "No signed distributable or simulated GUI interaction."],
              "input_v2_manifest_sha256": sha256_file(original)}
    save(docs / "phicad-v1-platform-service-evidence.json", {
        **common, "evidence_kind": "platform-v3-real-verify-service", "manifest": summary(result.manifest),
        "phicad_verify_commit": args.verify_commit, "exit_code": result.returncode, "ok": result.ok,
        "source_evidence": {"manifest_file_sha256": sha256_file(manifest_path),
                            "build_check_output_sha256": sha256_file(out / "build-check.json")},
    })
    save(docs / "phicad-v1-platform-mcp-evidence.json", {
        **common, "evidence_kind": "platform-v3-six-tool-real-stdio", "manifest": summary(result.manifest),
        "tools": [tool["name"] for tool in responses[2]["result"]["tools"]],
        "exercised": ["initialize", "tools/list", "design_manifest_verify", "design_apply_plan", "commit_refused"],
        "apply_status": applied["status"], "native_project_unchanged": True,
        "transcript": {"committed": False, "sha256": sha256_file(out / "mcp-response.jsonl")},
        "statement": "Direct stdio client, not a fresh Phi model/client acceptance run.",
    })
    save(docs / "phicad-v1-cross-view-evidence.json", {
        **common, "evidence_kind": "platform-v3-real-cli-dry-run", "launch_schema": launches["studio"]["request"]["schema"],
        "manifest_file_sha256": sha256_file(manifest_path),
        "shared_resolution": {"same_command": True, "same_native_artifact": True,
                              "executable_sha256": sha256_file(args.phicad),
                              "studio_output_sha256": sha256_file(out / "studio-launch.json"),
                              "verify_output_sha256": sha256_file(out / "verify-launch.json")},
        "preview_unconfigured": launches["preview"],
        "preview_configured_probe": {"executable": "/usr/bin/true", "dry_run": True, "renderer_executed": False,
                                     "output_sha256": sha256_file(out / "preview-probe.json")},
        "stale_preview": {"exit_code": stale.returncode, "code": "stale_handoff"},
    })
    # Portable real-run fixture: copy exact artifacts, then reserialize with relative
    # evidence pointers. This is NOT another checker run; the new manifest self-hash
    # deliberately covers the relocated paths rather than impersonating original bytes.
    fixtures = ROOT / "examples/fixtures"
    prefix = "demo-v1-led"
    records = []
    for artifact in result.manifest.artifacts:
        source_path = manifest_path.parent / artifact.path
        name = prefix + {"kicad-pcb": ".kicad_pcb", "kicad-drc": ".drc.json", "kicad-local-settings": ".kicad_prl"}[artifact.kind]
        (fixtures / name).write_bytes(source_path.read_bytes())
        records.append(ArtifactRecord(artifact.kind, name, artifact.sha256))
    circuit_name = prefix + ".circuit.json"
    plan_name = prefix + ".apply-plan.json"
    (fixtures / circuit_name).write_bytes(circuit.read_bytes())
    (fixtures / plan_name).write_bytes(Path(applied["plan_path"]).read_bytes())
    portable = replace(planned_manifest, manifest_hash=None, artifacts=tuple(records),
        native_artifact=replace(planned_manifest.native_artifact, path=prefix + ".kicad_pcb"),
        circuit_json_path=circuit_name, source_path="../demo-v1-led.tsx",
        native_apply=replace(planned_manifest.native_apply, plan_path=plan_name),
        configuration={"artifact_root": ".", "evidence": "relocated real run; no checker rerun"})
    fixture_manifest = fixtures / (prefix + ".manifest-v3.json")
    write_manifest(portable, fixture_manifest)
    assert verify_manifest(fixture_manifest).valid
    # A separately authored empty-board intent is the supported planned probe. It
    # is not a geometry-stripped version of the rejected LED input.
    planned_native = out / "board-only-native"
    planned_native.mkdir()
    planned_circuit = ROOT / "tests/fixtures/apply-board.circuit.json"
    planned_input = out / "board-only-input.json"
    write_manifest(create_manifest(
        design_id="board-only-plan-probe", source_hash=sha256_path(planned_native),
        circuit_json_hash=sha256_file(planned_circuit), circuit_json_path=str(planned_circuit),
        native_revision="unavailable-v1", native_artifact_hash=sha256_path(planned_native),
        artifacts=(), tool_versions=result.manifest.tool_versions,
        diagnostics={origin: DiagnosticCounts() for origin in result.manifest.diagnostics},
    ), planned_input)
    empty_before = sha256_path(planned_native)
    planned_probe = asyncio.run(design_apply_plan(manifest_path=planned_input, project=planned_native,
                                                  output_dir=out / "board-only-plan", config=config))
    assert planned_probe["status"] == "planned", planned_probe
    assert empty_before == sha256_path(planned_native)
    save(out / "board-only-response.json", planned_probe)
    save(docs / "phicad-v3-apply-plan-evidence.json", {
        **common, "evidence_kind": "platform-v3-real-native-plan-only", "phicad_apply_commit": args.phicad_commit,
        "native_apply": applied["native_apply"], "input_circuit_json_sha256": sha256_file(circuit),
        "native_project_before_sha256": native_before, "native_project_after_sha256": sha256_path(native),
        "source_result_sha256": sha256_file(out / "apply.json"),
        "plan_file_sha256": sha256_file(Path(applied["plan_path"])),
        "fixture_manifest_sha256": sha256_file(fixture_manifest),
        "fixture_manifest_self_hash": portable.calculated_hash(),
        "statement": "Untouched 53-element LED Circuit JSON; rejected coverage is preserved, not removed to manufacture success.",
        "planned_probe": {"intent": "separately authored empty two-layer board; no components, routing or native build",
                          "status": planned_probe["status"], "native_apply": planned_probe["native_apply"],
                          "input_sha256": sha256_file(planned_circuit),
                          "plan_file_sha256": sha256_file(Path(planned_probe["plan_path"])),
                          "response_sha256": sha256_file(out / "board-only-response.json"),
                          "native_project_unchanged": empty_before == sha256_path(planned_native)},

    })
    print(json.dumps({"manifest": str(fixture_manifest), "sha256": sha256_file(fixture_manifest),
                      "status": applied["status"]}, indent=2))


if __name__ == "__main__":
    main()
