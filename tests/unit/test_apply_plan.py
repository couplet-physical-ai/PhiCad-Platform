from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from phicad_platform.cli import main
from phicad_platform.contracts import (
    DIAGNOSTIC_ORIGINS,
    DiagnosticCounts,
    PlatformConfig,
    VerifyCliConfig,
    VerifyLimits,
)
from phicad_platform.manifest import create_manifest, load_manifest, sha256_file, verify_manifest, write_manifest
from phicad_platform.orchestrator import (
    APPLY_COMMIT_GATE,
    BuildCheckError,
    _parse_apply_plan,
    _run_process,
    design_apply_plan,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def setup(tmp_path, body=None):
    project = tmp_path / "native"
    project.mkdir()
    (project / "board.kicad_pro").write_text("{}\n")
    circuit = tmp_path / "circuit.json"
    circuit.write_bytes((FIXTURES / "apply-board.circuit.json").read_bytes())
    manifest = create_manifest(
        design_id="apply-test", source_hash="a" * 64, circuit_json_hash=sha256_file(circuit),
        native_revision="existing-evidence", native_artifact_hash="b" * 64, artifacts=(),
        tool_versions={"phicad": "0.1.0"},
        diagnostics={o: DiagnosticCounts() for o in DIAGNOSTIC_ORIGINS},
        diagnostic_status={o: "not-run" for o in DIAGNOSTIC_ORIGINS}, circuit_json_path=str(circuit),
    )
    manifest_path = tmp_path / "input.json"
    write_manifest(manifest, manifest_path)
    executable = tmp_path / "phicad"
    executable.write_text(f"#!{sys.executable}\n" + (body if body is not None else f'''
import hashlib, json, os, pathlib, sys
assert sys.argv[1:3] == ['core', 'apply']
assert '--commit' not in sys.argv
assert not any(k.lower().endswith('_proxy') or k == 'PROVIDER_SECRET' for k in os.environ)
plan = json.loads(pathlib.Path({str(FIXTURES / 'apply-board.plan.json')!r}).read_text())
plan['project']['path'] = str(pathlib.Path(sys.argv[sys.argv.index('--project') + 1]).resolve())
plan['plan_hash'] = ''
plan['plan_hash'] = hashlib.sha256((json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + '\\n').encode()).hexdigest()
pathlib.Path(sys.argv[sys.argv.index('--plan') + 1]).write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + '\\n')
'''))
    executable.chmod(0o755)
    config = PlatformConfig(verify=VerifyCliConfig(command=("unused",)), tool_versions={"phicad": "0.1.0"},
                            apply_executable=str(executable))
    return dict(manifest_path=manifest_path, project=project, output_dir=tmp_path / "evidence", config=config)


def run(arguments):
    return asyncio.run(design_apply_plan(**arguments))


def test_recorded_real_plan_hash_contract():
    path = FIXTURES / "apply-board.plan.json"
    raw = json.loads(path.read_text())
    plan = _parse_apply_plan(path, sha256_file(FIXTURES / "apply-board.circuit.json"),
                             Path(raw["project"]["path"]), 0)
    assert plan["plan_hash"] == "f9cc1f693b8b909763deb5a4e5bb20b6e38f92817129ebb6b2f5e07035a320bc"


def test_plan_only_fixed_argv_environment_and_native_accounting(tmp_path, monkeypatch):
    args = setup(tmp_path)
    args["config"] = replace(args["config"], verify=VerifyCliConfig(
        command=("unused",), limits=VerifyLimits(timeout_seconds=600, max_output_files=999)))
    before = {p.name: p.read_bytes() for p in args["project"].iterdir()}
    input_hash = sha256_file(args["manifest_path"])
    monkeypatch.setenv("PROVIDER_SECRET", "must-not-be-inherited")
    monkeypatch.setenv("HTTPS_PROXY", "must-not-be-inherited")
    result = run(args)
    assert result["status"] == "planned"
    assert result["native_apply"]["undo_entries"] == 0
    assert result["native_apply"]["applied_revision"] is None
    assert result["command"][1:3] == ["core", "apply"]
    assert "--commit" not in result["command"]
    assert sha256_file(args["manifest_path"]) == input_hash
    assert {p.name: p.read_bytes() for p in args["project"].iterdir()} == before
    checked = verify_manifest(Path(result["manifest_path"]))
    assert checked.valid, checked.errors
    assert checked.manifest.diagnostic_status == {o: "not-run" for o in DIAGNOSTIC_ORIGINS}
    limits = checked.manifest.configuration["apply_plan"]["limits"]
    assert limits == VerifyLimits().to_dict()
    assert not (args["output_dir"] / "result.json").exists()
    Path(result["plan_path"]).write_text('{}\n')
    assert not verify_manifest(Path(result["manifest_path"])).valid


def test_commit_refused_before_read_or_spawn(tmp_path):
    args = setup(tmp_path)
    with patch("phicad_platform.orchestrator._run_process") as child:
        with pytest.raises(BuildCheckError) as caught:
            run({**args, "commit": True})
    child.assert_not_called()
    assert caught.value.code == "commit_refused"
    assert caught.value.details == {"gate": APPLY_COMMIT_GATE}
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("body,reason", [
    ("print('unknown command apply'); raise SystemExit(1)", "may be unsupported"),
    ("print('old build usage'); raise SystemExit(0)", "may be unsupported"),
    ("import json; print(json.dumps({'result': {'schema':'io.github.couplet-physical-ai.phicad.apply-result/v1', 'status':'unavailable', 'reason':'Python unavailable'}})); raise SystemExit(3)", "Python unavailable"),
])
def test_apply_unavailable_never_fabricates_success(tmp_path, body, reason):
    args = setup(tmp_path, body)
    result = run(args)
    assert result["status"] == "unavailable"
    assert reason in result["reason"]
    assert result["plan_path"] is None
    manifest = load_manifest(Path(result["manifest_path"]))
    assert manifest.native_apply.status == "unavailable-v1"
    assert manifest.native_apply.plan_hash is None


def test_missing_executable_unavailable(tmp_path):
    args = setup(tmp_path)
    args["config"] = replace(args["config"], apply_executable=str(tmp_path / "absent"))
    result = run(args)
    assert result["status"] == "unavailable"
    assert result["reason"]
    assert result["command"] == []


def test_rejected_plan_is_preserved_not_treated_as_process_failure(tmp_path):
    args = setup(tmp_path)
    executable = Path(args["config"].apply_executable)
    body = executable.read_text().replace("plan['plan_hash'] = ''", """plan['status'] = 'rejected'
plan['rejections'] = [{'code':'unsupported_required_geometry','element':'pcb_cutout','detail':'not representable'}]
plan['coverage']['rejected'] = ['pcb_cutout']
plan['plan_hash'] = ''""")
    executable.write_text(body + "\nraise SystemExit(3)\n")
    result = run(args)
    assert result["status"] == "rejected"
    assert result["returncode"] == 3
    assert result["native_apply"]["rejections"][0]["code"] == "unsupported_required_geometry"
    assert verify_manifest(Path(result["manifest_path"])).valid


@pytest.mark.parametrize("mutation", [
    "plan['status'] = 'applied'", "plan['schema'] = 'wrong'", "plan['plan_hash'] = 'a'*64",
    "plan['circuit_json_hash'] = 'a'*64", "plan['project']['path'] = '/wrong'",
    "plan['counts']['pads'] = True", "plan['rejections'] = ['bad']",
    "plan['coverage']['rejected'] = ['pcb_cutout']",
])
def test_bad_child_plan_is_never_recorded(tmp_path, mutation):
    args = setup(tmp_path)
    executable = Path(args["config"].apply_executable)
    # Mutate after the producer hash has been computed, except integrity-only testing
    # already exercises the stronger shape paths in _parse_apply_plan separately.
    body = executable.read_text().replace("pathlib.Path(sys.argv[sys.argv.index('--plan') + 1])", mutation + "\npathlib.Path(sys.argv[sys.argv.index('--plan') + 1])")
    executable.write_text(body)
    with pytest.raises(BuildCheckError):
        run(args)
    assert not (args["output_dir"] / "design.manifest.json").exists()


@pytest.mark.parametrize("kind", ["circuit-symlink", "project-symlink", "output-symlink", "inside-project", "oversized", "too-many-elements", "stale-input"])
def test_input_and_output_gates_precede_spawn(tmp_path, kind):
    args = setup(tmp_path)
    circuit = tmp_path / "circuit.json"
    if kind == "circuit-symlink":
        circuit.rename(tmp_path / "real.json")
        circuit.symlink_to(tmp_path / "real.json")
    elif kind == "project-symlink":
        link = tmp_path / "link"
        link.symlink_to(args["project"], target_is_directory=True)
        args["project"] = link
    elif kind == "output-symlink":
        args["output_dir"].symlink_to(args["project"], target_is_directory=True)
    elif kind == "inside-project":
        args["output_dir"] = args["project"] / "out"
    elif kind == "oversized":
        circuit.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    elif kind == "too-many-elements":
        circuit.write_text(json.dumps([{}] * 100001))
    else:
        circuit.write_text('[]')
    with patch("phicad_platform.orchestrator._run_process") as child:
        with pytest.raises(BuildCheckError):
            run(args)
    child.assert_not_called()


@pytest.mark.parametrize("body,code", [
    ("import pathlib,sys; p=pathlib.Path(sys.argv[-1]); p.symlink_to('/dev/null')", "unsafe_output"),
    ("import pathlib,sys; p=pathlib.Path(sys.argv[-1]); p.write_text('x'*1048577)", "result_limit"),
    ("print('x'*1048577)", "output_limit"),
    ("import pathlib,sys; p=pathlib.Path(sys.argv[-1]); f=p.open('wb'); f.truncate(512*1024*1024+1); f.close()", "output_limit"),
    ("import pathlib,sys; p=pathlib.Path(sys.argv[-1]).parent; [(p/str(i)).write_text('') for i in range(257)]", "output_limit"),
])
def test_child_output_bounds(tmp_path, body, code):
    args = setup(tmp_path, body)
    with pytest.raises(BuildCheckError) as caught:
        run(args)
    assert caught.value.code == code
    assert not (args["output_dir"] / "design.manifest.json").exists()


def test_cli_commit_refusal_is_typed(capsys):
    assert main(["apply-plan", "--manifest", "/missing", "--project", "/missing",
                 "--output-dir", "/missing", "--commit"]) == 3
    assert json.loads(capsys.readouterr().err)["error"]["details"]["gate"] == APPLY_COMMIT_GATE


def test_process_cancellation_terminates_group(tmp_path):
    pid_file = tmp_path / "pid"
    command = (sys.executable, "-c", f"import os,time,pathlib; pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)")

    async def cancel():
        task = asyncio.create_task(_run_process(command, VerifyCliConfig(command=command)))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_expected_revision_is_fixed_argument_and_rechecked(tmp_path):
    args = setup(tmp_path)
    with pytest.raises(BuildCheckError) as caught:
        run({**args, "expected_revision": "a" * 40})
    assert caught.value.code == "stale_apply_plan"
    assert not (args["output_dir"] / "design.manifest.json").exists()
