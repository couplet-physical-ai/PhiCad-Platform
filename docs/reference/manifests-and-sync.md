# Manifests and synchronization

PhiCad Platform coordinates views through one canonical, self-hashed design manifest. Views do not mutate each other directly.

## Manifest schema V3

`manifest_version: 3` identifies these fields:

| Field | Meaning |
|---|---|
| `design_id` | Stable project/design identity. |
| `source_hash` / `source_path` | Exact supplied source bytes and optional evidence pointer. |
| `circuit_json_hash` / `circuit_json_path` | Exact supplied Circuit JSON bytes and optional pointer. |
| `native_artifact` | Native evidence object: `path`, `revision`, `sha256`. |
| `native_revision` | Existing evidence revision identifier, **not** proof of a revision applied by Platform. |
| `native_artifact_hash` / `native_artifact_path` | Native evidence digest/pointer, matching the nested object. |
| `native_apply` | Required apply-state block, described below. |
| `artifacts` / `artifact_hashes` | Relative output paths and SHA-256 hashes of exact file bytes. |
| `tool_versions` | Exact scalar versions; one `phicad` role for the native application. Executable locations live in `configuration`. |
| `diagnostics` | Counts keyed by exactly `tscircuit` and `kicad`. |
| `diagnostic_status` | Independent per-origin run state. |
| `approval_state` | Review state; never inferred from checker counts or plan success. |

The self-hash omits `manifest_hash`, uses UTF-8, sorted keys, compact separators, and rejects non-finite JSON numbers. The entire `native_apply` block participates in this hash. Paths and duplicated evidence fields must agree with the canonical payload; unknown or contradictory fields fail closed.

Artifact paths stay relative to `configuration.artifact_root` (default: the manifest directory). Relative evidence pointers and a relative artifact root resolve from the manifest directory. Apply plan paths are always relative to the manifest directory, not the artifact root.

### Native apply state

```json
{
  "native_apply": {
    "status": "unavailable-v1",
    "plan_hash": null,
    "plan_path": null,
    "base_revision": null,
    "applied_revision": null,
    "undo_entries": 0,
    "rejections": []
  }
}
```

The closed status set is `unavailable-v1`, `planned`, `applied`, `rejected`. Unknown statuses, missing/extra block fields, malformed SHA-256 values, escaping plan paths, invalid revision types, negative/non-integer undo counts, and malformed rejection records fail validation. Rejections contain non-empty `code`, `element`, and `detail` strings.

`applied` requires a non-null `applied_revision` and exactly **one** undo entry. Non-applied statuses cannot claim either an applied revision or an undo entry. The schema can read externally supplied apply evidence, but **this Platform release never performs commit and never emits an applied state**. `planned` is a reviewable proposal, not native materialization or fabrication approval.

### V2 compatibility and the naming decision

V2 documents remain readable with their **original self-hash intact**. Their historical `studio`, `studio_hash`, `studio_path`, and `studio_revision` fields map to the native artifact in memory. The verifier returns a `compatibility_notes` entry recording that `native_apply` defaulted to `unavailable-v1`; its separate `native_apply` result contains that default. It does not insert unhashed fields into the original V2 wire document. A V3 document without the block is invalid.

V3 deliberately renames those wire fields: Studio is a mode of PhiCad, not a separate product or artifact. V3 collapses equal `phicad-studio` / `phicad-verify` version roles to one honest `phicad` entry; conflicting pins are rejected, not silently chosen. The locks use that same single role, while installer/release validators still read equal legacy roles for rollback.

Build-check flags are now `--native-artifact` (also `--native-artifact-path`), `--native-artifact-hash`, and `--native-revision`. `--studio`, `--studio-hash`, and `--studio-revision` remain documented aliases. Legacy Python build-check request constructors/accessors remain adapters, not V3 wire names.

## Diagnostic status is not a count

The only origins are `tscircuit` and `kicad`, with states `not-run`, `carried-input`, `reported`, `passed`, `failed`, `unavailable`. No third diagnostic origin is added for Preview, Studio, or apply.

`carried-input` means tscircuit findings traveled with supplied Circuit JSON and were not re-derived. `passed` means the named checker returned an explicit passing run verdict. Zero findings alone never imply either state. Apply-plan preserves diagnostic counts, run states, and approval state unchanged.

## Build/check and plan flow

1. Phi invokes the pinned Circuit Engine to build exact Circuit JSON bytes.
2. Platform invokes bounded PhiCad Verify on those bytes, without reevaluating TSX.
3. Platform validates paths, hashes, limits, versions, findings, and fresh output; it emits manifest V3.
4. Optionally, `apply-plan` / `design_apply_plan` reads that manifest and invokes `phicad core apply` **without `--commit`**.
5. A fresh directory outside the native project holds `plan.json` and a new `design.manifest.json`. Neither the input manifest nor project is overwritten.

See [Phi and MCP](phi-and-mcp.md) for arguments, limits, and the plan-only gate. A missing apply command returns `status: unavailable` with a reason and records `native_apply.status: unavailable-v1`, with an `apply_unavailable` rejection explaining why.

## Actual PhiCad apply protocol

Platform integrates against the PhiCad native apply protocol, rather than assuming the shared contract's illustrative prose is exact:

- `plan.json` uses `io.github.couplet-physical-ai.phicad.apply-plan/v1`, and only `planned` (exit 0) or `rejected` (exit 3) is accepted. Actual operation records use `op: create_footprint` (with `ref`, `layer`, `at_nm`, `rotation_deg`), `create_net` (with `name`, `pins`), or `ignore_element` / `ignore_field` (with `element`, `reason`); Platform validates those implemented shapes.
- Its `plan_hash` uses **pretty**, key-sorted UTF-8 JSON with `plan_hash: ""` and a final newline. This is deliberately different from the compact manifest self-hash.
- A plan-only run does **not** write `result.json`. Service failures may instead return a nested `io.github.couplet-physical-ai.phicad.apply-result/v1` unavailable result on stdout, with nullable revision/board fields and a reason. No stdout-only plan is accepted as a file deliverable.
- The current apply implementation limits Circuit JSON to **2 MiB**, stricter than the shared 32 MiB Circuit JSON ceiling. Platform enforces the stricter bound for this operation.
- Plan-only may work without KiCad CLI and report `kicad_cli: "unknown"`; that is not proof of native materialization capability. Platform requires an existing project directory, but never requires or invokes the commit path.
- `tool_versions.phicad` in the plan currently reports `native-apply-v1`, not a release version. Platform preserves it in the plan, not as a replacement for the manifest's pinned native tool version. The locks remain at the exact recorded native source commit. Apply acceptance may use a separately selected compatible PhiCad build; it does not silently advance the release pin.

## Stale state

Handoffs bind manifest-file hash, self-hash, identity, native revision/hash, source, Circuit JSON, and artifact hashes. Referenced plan evidence is revalidated too. A mismatch refuses the handoff as `stale_handoff` (CLI exit 3), rather than silently refreshing or picking a timestamp winner.

## Exported fixture evidence

The synthetic LED fixture includes a self-hashed manifest and plan. Tests verify its byte bindings; historical developer captures and brand-bearing media are omitted from this export. The V2 compatibility fixture was adapted from a historical run: its native revision fields were repointed to the public source pin and its manifest self-hash recalculated with `phicad_platform.manifest` canonical JSON and SHA-256 helpers. Its unchanged artifact hashes/checker observations are historical, **not evidence of a run at the public pin**. Re-run with separately installed, compatible tools before relying on a native result.
