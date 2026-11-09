# Architecture and ownership

PhiCad Platform is one manifest-bound workflow over separate, pinned engines. It does not make every view a separate authority.

```text
User intent
  │
  ▼
Phi                    sole AI harness, MCP client, permissions
  │
  ▼
Circuit Engine         pinned tscircuit runtime, TSX → Circuit JSON
  │
  ├──► Circuit Preview         thin MIT web review surface; no native authority
  │
  ▼
PhiCad                 one GPL-3.0 KiCad-native application family
  ├── Studio view              native editing, save, history, fabrication export
  └── Verify view              deterministic checks and evidence
  │
  ▼
Manifest-bound review package
```

A Verify run stops before native materialization: it checks exact caller-supplied Circuit JSON and generated KiCad artifacts. The optional Platform `design_apply_plan` operation records a plan, not a durable native revision. `preview` is a separately configured review target, not a native authority.

## Ownership table

| Concern | Authority | Boundary |
|---|---|---|
| Prompting, model access, tool selection, approvals | Phi | Sole AI harness; credentials never travel in manifests or handoffs. |
| Authored TSX and deterministic build | Circuit Engine / tscircuit | Isolated exact package graph; Circuit JSON is the interchange artifact. |
| Browser preview and review intent | Circuit Preview | Thin MIT surface; no native persistence, DRC authority, or manufacturing export. |
| Native schematic and PCB project | PhiCad Studio view | KiCad/PhiCad project bytes and native revision. |
| Native checks and evidence | PhiCad Verify view | Same installed PhiCad source and native artifact, canonical origin `kicad`. |
| Compatibility, manifests, launch, installer, evidence | PhiCad Platform | Exact locks and fail-closed adapters; no copied engine source. |
| Manufacturing decision | Human review process | Never inferred from zero automated findings. |

## One native authority, two views

`studio` and `verify` remain stable target identifiers because users need different tasks and focus states. They are not separate executables or design owners. Both resolve to identical argv and native artifact through PATH, a conventional sibling checkout, or installed `PhiCad.app` discovery. Native launch discovery is not controlled by an environment override.

A manifest V3 (with V2 read compatibility) carries two diagnostic origins:

- `tscircuit` — build diagnostics, often `carried-input` when Verify receives existing Circuit JSON; and
- `kicad` — findings actually produced by PhiCad/KiCad.

Zero findings never prove that a checker ran; each origin also records a status.

## Authority modes

| Mode | Durable authority | Allowed operation |
|---|---|---|
| **Code-linked** | TS/TSX plus supported manual-edit data | Rebuild Circuit JSON; review exact generated artifacts. |
| **Native** | KiCad/PhiCad project plus native history | Edit in PhiCad Studio; run PhiCad Verify; export only from an explicitly reviewed native revision. |

Circuit JSON is not a lossless authored-TSX format. Unsupported structural edits require an explicit detach/copy decision rather than hidden reverse translation.

## Materialization boundary

Native materialization is **plan-only in Platform**. `apply-plan` / `design_apply_plan` invokes the implemented PhiCad PhiCad native apply protocol protocol without `--commit`, validates its real `plan.json`, and writes `native_apply.status: planned` or `rejected`. Unsupported installed builds are unavailable with a reason. Preview success, existing `native_revision` evidence, and an accepted plan never imply an applied revision.

The `platform_native_apply_plan_only` gate refuses commit because write authority requires more than a parsed plan. Future Platform commit support must:

1. validate schema, layer capabilities, geometry, provenance, hashes, and base revision;
2. reject unsupported required elements without approximation or silent dropping;
3. use one checked `round(mm * 1_000_000)` coordinate boundary;
4. execute asynchronously and cancellably inside one native transaction; and
5. create exactly one native revision and one undo entry, or make no persistent change.

Until that evidence exists, preview and Verify success are not evidence of an applied Studio revision.

## Repository and license boundaries

- PhiCad Platform owns orchestration and contracts.
- PhiCad owns both native product views and retains its GPL-3.0/KiCad notices.
- tscircuit/Circuit JSON packages retain their permissive notices.
- Web preview is a separate thin MIT surface, configured only through `PHICAD_CIRCUIT_PREVIEW`.
- The `couplet-physical-ai/PhiCad-Studio` fork exists as a **separately licensed tool**, out of scope for the shipped release. Neither it nor OpenPCB is a current product component or push target. Do not push to that repository or `OpenPCB-app/*`, or copy/port OpenPCB code.

See [ADR 0002](../decisions/0002-phicad-native-studio-and-verify.md).
