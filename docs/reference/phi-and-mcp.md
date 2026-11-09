# Phi and MCP

Phi is the only AI harness in PhiCad Platform. Circuit Engine, Circuit Preview, PhiCad Studio, PhiCad Verify, and Platform expose deterministic operations; they do not embed provider credentials or competing agent runtimes.

## Credential-free transport

The installed MCP entry is a local stdio launcher:

```json
{
  "command": "/Users/you/.local/bin/phicad-platform-mcp",
  "args": []
}
```

The launcher reads normal MCP JSON-RPC on stdin and writes protocol output on stdout. It does not contain a token and does not copy Phi credentials into engine configuration.

## Platform tools

The developer-preview server exposes six deterministic operations:

| Tool | Purpose |
|---|---|
| `platform_capabilities` | Report Platform schemas, limits, targets, and deterministic capabilities. |
| `platform_doctor` | Probe the installed local prerequisites without changing state. |
| `platform_open_view` | Validate and resolve a fixed cross-view launch request. |
| `design_build_check` | Run bounded Verify and emit a canonical self-hashed manifest. |
| `design_manifest_verify` | Revalidate manifest self-hash and referenced evidence. |
| `design_apply_plan` | Invoke fixed, bounded `phicad core apply` in plan-only mode and record a V3 manifest; refuse commit. |

Inputs are structured data. Launch and apply-plan accept no arbitrary shell text, executable argument, caller URL, environment dump, or credentials. Operator-managed configuration may select installed tools; do not accept untrusted configuration files. The legacy build-check configuration supports exact operator argv templates, not a sandbox for arbitrary callers.

## Engine responsibilities

- **Phi** decides when to call tools, explains findings, and requests approval.
- **Circuit Engine** deterministically builds TSX to Circuit JSON.
- **Circuit Preview** may display Circuit JSON and collect review intent; it is not an agent or native authority.
- **PhiCad Studio** edits the native KiCad/PhiCad project.
- **PhiCad Verify** checks exact supplied input or the exact native artifact.
- **Platform** binds all results to hashes, versions, and target views.

Studio and Verify share one installed PhiCad source and native authority. Their stable target identifiers express intent only.

## Bounded execution

Build/check processes run with explicit executable vectors, a minimal allowlisted environment, bounded files/output/time, cancellation through process-group termination, and no inherited secret/proxy variables. The approximately 17 MiB `@tscircuit/eval` worker is lazy-loaded outside any GUI main process.

## Plan-only apply

CLI example (all evidence output must be fresh and outside the native project):

```bash
phicad-platform apply-plan --manifest /absolute/design.manifest.json \
  --project /absolute/native-project --output-dir /absolute/new-plan-evidence \
  --expected-revision <native-git-revision> --config /absolute/phicad-platform.json
```

The MCP equivalent is `design_apply_plan` with `manifest_path`, `project`, `output_dir`, and optional `expected_revision`, `config_path`, `commit` (false only). Additional arguments are rejected. The operator configuration can contain:

```json
{"apply_cli": {"executable": "/absolute/path/to/phicad"}}
```

Without it, discovery uses native `phicad` on PATH or a conventional sibling checkout. The only child vector is `phicad core apply --circuit-json <manifest-input> --project <project> --plan <fresh-output/plan.json>`, plus optional `--expected-revision`. No `--commit` or caller-supplied flags are appended. An installed app without a usable CLI/apply command is unavailable with a reason.

The typed commit refusal is `commit_refused`, with `details.gate: platform_native_apply_plan_only`. CLI exits 3; MCP returns an `isError` tool result containing the typed error. This gate exists because a plan does not establish full supported geometry coverage, transaction safety, or independent review for a native write.

Plan-only results are `planned`, `rejected`, or `unavailable`, with a `native_apply` block and an output manifest path. Unavailable maps to manifest status `unavailable-v1` and an explanatory rejection. A malformed, stale, oversized, or contradictory plan is an error and does not produce a success manifest. Diagnostic origins/run states and approval are preserved; nothing claims an applied revision.

Apply bounds cannot be relaxed by configuration: 60 seconds per child, 2 seconds termination grace, 2 MiB source, **2 MiB Circuit JSON for current PhiCad PhiCad native apply protocol** (stricter than the general 32 MiB ceiling), 100,000 elements, 1 MiB per stdout/stderr/plan result, 256 retained output files, 512 MiB retained output. Inputs are regular and non-symlink; output symlinks are rejected. The inherited environment is only `PATH`, `HOME`, `TMPDIR`, `TMP`, `TEMP`, `LANG`, `LC_ALL`; no proxy or credential variables. MCP's configurable request timeout may terminate a child sooner than its 60-second limit. Cancellation terminates the process group.

The operation invokes only the installed deterministic planning code: no downloads, network client, model runtime, native synth build, or commit. It is not an OS sandbox for an untrusted executable. See [the manifest protocol](manifests-and-sync.md) for the actual plan hash and stdout failure shapes.

## Installed-client acceptance

Release acceptance must include both direct stdio protocol tests and a fresh Phi process discovering and calling the installed MCP launcher with built-in tools disabled. Committed evidence must be bounded and scrubbed; full Phi JSONL transcripts with absolute local paths or encrypted model-reasoning envelopes remain local and are represented only by hashes.
