from __future__ import annotations

import asyncio
import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from phicad_platform.contracts import (
    DIAGNOSTIC_ORIGINS,
    ArtifactRecord,
    BuildCheckRequest,
    DiagnosticCounts,
    PlatformConfig,
    VerifyCliConfig,
    VerifyLimits,
)
from phicad_platform.manifest import create_manifest, sha256_path, verify_manifest, write_manifest
from phicad_platform.orchestrator import BuildCheckError, build_check


def _write_executable(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _config(fake: Path, *args: str, **kwargs: object) -> PlatformConfig:
    command = (str(fake),) + tuple(args)
    limits = kwargs.pop("limits", None)
    if limits is not None:
        verify = VerifyCliConfig(command=command, limits=VerifyLimits(**limits), **kwargs)
    else:
        verify = VerifyCliConfig(command=command, **kwargs)
    return PlatformConfig(
        verify=verify,
        tool_versions={
            "phicad-verify": "0.1.0-dev",
            "circuit-engine": "0.1.0-dev",
            "phicad-studio": "0.1.0-dev",
            "tscircuit": "0.1.0-dev",
            "kicad": "9.0.0",
        },
        versions_lock_path="/explicit/versions.lock.json",
        config_path="/explicit/phicad-platform.json",
    )


def _request(tmp_path: Path, studio: bool = True) -> BuildCheckRequest:
    source = tmp_path / "design.tsx"
    circuit = tmp_path / "circuit.json"
    source.write_text("export default {};\n", encoding="utf-8")
    circuit.write_text('{"elements": []}\n', encoding="utf-8")
    studio_path = tmp_path / "studio.json"
    studio_path.write_text('{"revision": 7}\n', encoding="utf-8")
    output = tmp_path / "fresh-output"
    return BuildCheckRequest(
        source=source,
        circuit_json=circuit,
        output_dir=output,
        manifest_path=output / "design.manifest.json",
        design_id="test-design",
        studio_revision="studio-r7",
        studio_path=studio_path,
    )


class PlatformCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.mkdtemp(prefix="phicad-platform-test-")
        self.tmp_path = Path(self.temp_directory)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_directory, ignore_errors=True)

    def test_build_check_success_records_distinct_diagnostics_and_hashes(self) -> None:
        fake = _write_executable(
            self.tmp_path / "verify.py",
            """
import hashlib, json, pathlib, sys
output = pathlib.Path(sys.argv[1])
artifact = output / 'board.kicad_pcb'
artifact.write_text('(kicad_pcb (version 20240108))\\n', encoding='utf-8')
result = {
  'artifacts': [{'kind': 'kicad', 'path': 'board.kicad_pcb',
                 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}],
  'diagnostics': [
    {'origin': 'tscircuit', 'severity': 'info'},
    {'origin': 'PhiCad', 'severity': 'warning'},
    {'origin': 'KiCad', 'severity': 'info'}
  ],
}
(output / 'verify-result.json').write_text(json.dumps(result), encoding='utf-8')
""",
        )
        request = _request(self.tmp_path)
        config = _config(fake, "{output_dir}")

        result = asyncio.run(build_check(request, config))

        self.assertTrue(result.ok)
        self.assertTrue(result.manifest.source_hash)
        self.assertTrue(result.manifest.circuit_json_hash)
        self.assertEqual(result.manifest.studio.revision, "studio-r7")
        self.assertEqual(set(result.manifest.artifact_hashes), {"kicad"})
        self.assertEqual(result.manifest.diagnostics["tscircuit"].info, 1)
        self.assertEqual(result.manifest.diagnostics["kicad"].warnings, 1)
        self.assertEqual(result.manifest.diagnostics["kicad"].info, 1)
        checked = verify_manifest(request.manifest_path)
        self.assertTrue(checked.valid, checked.errors)

    def test_verify_service_path_keyed_artifacts_and_diagnostic_origins_are_accepted(self) -> None:
        fake = _write_executable(
            self.tmp_path / "service-shape.py",
            """
import hashlib, json, pathlib, sys
output = pathlib.Path(sys.argv[1])
files = {
  'board.kicad_pcb': 'board',
  'board.kicad_prl': 'settings',
  'drc.json': '{}',
}
for name, value in files.items():
    (output / name).write_text(value, encoding='utf-8')
result = {
  'artifacts': list(files),
  'artifact_hashes': {
    name: hashlib.sha256((output / name).read_bytes()).hexdigest()
    for name in files
  },
  'diagnostic_counts': {'error': 0, 'warning': 2, 'info': 0, 'by_origin': {'tscircuit': 1, 'kicad': 1}},
  'verdict': {'origin': 'kicad', 'ok': True},
  'diagnostics': [
    {'origin': 'tscircuit', 'severity': 'warning', 'code': 'tsc.warning'},
    {'origin': 'kicad', 'severity': 'warning', 'code': 'drc.warning'},
  ],
  'tool_versions': {'tscircuit': '0.1.0-dev', 'kicad-cli': '9.0.0', 'service-contract': 1},
}
(output / 'verify-result.json').write_text(json.dumps(result), encoding='utf-8')
""",
        )
        request = _request(self.tmp_path)
        result = asyncio.run(build_check(request, _config(fake, "{output_dir}")))
        self.assertTrue(result.ok)
        self.assertEqual(
            set(result.manifest.artifact_hashes),
            {"kicad-pcb", "kicad-local-settings", "kicad-drc"},
        )
        self.assertEqual(result.manifest.diagnostics["tscircuit"].warnings, 1)
        self.assertEqual(result.manifest.diagnostics["kicad"].warnings, 1)
        self.assertEqual(result.manifest.diagnostic_status["tscircuit"], "carried-input")
        self.assertEqual(result.manifest.diagnostic_status["kicad"], "passed")
        self.assertEqual(result.manifest.tool_versions["kicad-cli"], "9.0.0")

    def test_timeout_terminates_verifier(self) -> None:
        fake = _write_executable(self.tmp_path / "slow.py", "import time\ntime.sleep(30)\n")
        request = _request(self.tmp_path, studio=False)
        config = _config(fake, "{output_dir}", limits={"timeout_seconds": 0.1, "terminate_grace_seconds": 0.1})

        with self.assertRaises(BuildCheckError) as raised:
            asyncio.run(build_check(request, config))

        self.assertEqual(raised.exception.code, "timeout")
        self.assertTrue(request.output_dir.exists())

    def test_oversized_stdout_is_bounded_and_stopped(self) -> None:
        fake = _write_executable(
            self.tmp_path / "loud.py",
            "import sys\nsys.stdout.write('x' * 200000)\nsys.stdout.flush()\n",
        )
        request = _request(self.tmp_path, studio=False)
        config = _config(fake, "{output_dir}", limits={"max_stdout_bytes": 1024, "terminate_grace_seconds": 0.1})

        with self.assertRaises(BuildCheckError) as raised:
            asyncio.run(build_check(request, config))

        self.assertEqual(raised.exception.code, "output_limit")
        self.assertEqual(raised.exception.details["stream"], "stdout")

    def test_input_size_and_circuit_element_limits_are_enforced_before_spawn(self) -> None:
        fake = _write_executable(self.tmp_path / "unused.py", "raise SystemExit(99)\n")
        request = _request(self.tmp_path, studio=False)
        config = _config(fake, "{output_dir}", limits={"max_circuit_json_bytes": 4})
        with self.assertRaises(BuildCheckError) as size_error:
            asyncio.run(build_check(request, config))
        self.assertEqual(size_error.exception.code, "input_limit")
        self.assertFalse(request.output_dir.exists())

        request.circuit_json.write_text('{"elements": [{}, {}]}\n', encoding="utf-8")
        config = _config(fake, "{output_dir}", limits={"max_circuit_json_elements": 1})
        with self.assertRaises(BuildCheckError) as count_error:
            asyncio.run(build_check(request, config))
        self.assertEqual(count_error.exception.code, "input_limit")
        self.assertEqual(count_error.exception.details["actual_elements"], 2)

    def test_output_file_count_is_bounded(self) -> None:
        fake = _write_executable(
            self.tmp_path / "many-files.py",
            """
import json, pathlib, sys
output = pathlib.Path(sys.argv[1])
(output / 'board.kicad_pcb').write_text('board', encoding='utf-8')
(output / 'extra.txt').write_text('extra', encoding='utf-8')
(output / 'verify-result.json').write_text(json.dumps({'artifacts': {'kicad': 'board.kicad_pcb'}}), encoding='utf-8')
""",
        )
        request = _request(self.tmp_path, studio=False)
        config = _config(fake, "{output_dir}", limits={"max_output_files": 2})
        with self.assertRaises(BuildCheckError) as count_error:
            asyncio.run(build_check(request, config))
        self.assertEqual(count_error.exception.code, "output_limit")
        self.assertEqual(count_error.exception.details["actual_files"], 3)

    def test_oversized_result_is_rejected(self) -> None:
        fake = _write_executable(
            self.tmp_path / "large-result.py",
            """
import json, pathlib, sys
output = pathlib.Path(sys.argv[1])
(output / 'board.kicad_pcb').write_text('board', encoding='utf-8')
(output / 'verify-result.json').write_text('{' + 'x' * 10000, encoding='utf-8')
""",
        )
        request = _request(self.tmp_path, studio=False)
        config = _config(fake, "{output_dir}", limits={"max_result_bytes": 1024})

        with self.assertRaises(BuildCheckError) as raised:
            asyncio.run(build_check(request, config))

        self.assertEqual(raised.exception.code, "result_limit")

    def test_missing_configured_binary_is_rejected_without_path_fallback(self) -> None:
        request = _request(self.tmp_path, studio=False)
        config = _config(self.tmp_path / "does-not-exist", "{output_dir}")

        with self.assertRaises(BuildCheckError) as raised:
            asyncio.run(build_check(request, config))

        self.assertEqual(raised.exception.code, "missing_binary")

    def test_existing_output_is_rejected_as_stale(self) -> None:
        fake = _write_executable(self.tmp_path / "never.py", "raise SystemExit(0)\n")
        request = _request(self.tmp_path, studio=False)
        request.output_dir.mkdir()
        (request.output_dir / "old-board.kicad_pcb").write_text("old", encoding="utf-8")

        with self.assertRaises(BuildCheckError) as raised:
            asyncio.run(build_check(request, _config(fake, "{output_dir}")))

        self.assertEqual(raised.exception.code, "output_not_fresh")
        self.assertEqual((request.output_dir / "old-board.kicad_pcb").read_text(encoding="utf-8"), "old")

    def test_manifest_self_hash_and_artifact_hash_verification(self) -> None:
        source = self.tmp_path / "source.tsx"
        circuit = self.tmp_path / "circuit.json"
        studio = self.tmp_path / "studio.json"
        artifact = self.tmp_path / "board.kicad_pcb"
        for path, content in ((source, "source"), (circuit, "{}"), (studio, "studio"), (artifact, "board")):
            path.write_text(content, encoding="utf-8")

        manifest = create_manifest(
            design_id="manifest-test",
            source_hash=sha256_path(source),
            circuit_json_hash=sha256_path(circuit),
            studio_revision="r1",
            studio_hash=sha256_path(studio),
            artifacts=(ArtifactRecord("kicad", artifact.name, sha256_path(artifact)),),
            tool_versions={"phicad-verify": "0.1.0-dev"},
            diagnostics={origin: DiagnosticCounts() for origin in DIAGNOSTIC_ORIGINS},
            source_path=str(source),
            circuit_json_path=str(circuit),
            studio_path=str(studio),
            configuration={"artifact_root": str(self.tmp_path)},
        )
        path = self.tmp_path / "manifest.json"
        write_manifest(manifest, path)
        self.assertTrue(verify_manifest(path).valid)

        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["design_id"] = "tampered"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        self.assertFalse(verify_manifest(path).valid)
        write_manifest(manifest, path)

        artifact.write_text("changed", encoding="utf-8")
        checked = verify_manifest(path)
        self.assertFalse(checked.valid)
        self.assertTrue(any("stale" in error for error in checked.errors))


if __name__ == "__main__":
    unittest.main()
