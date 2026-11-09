# First project

The V1 developer preview demonstrates deterministic build and Verify evidence. It does not yet create a native PhiCad project from Circuit JSON.

## 1. Author and build

Create a small TSX design and run the exact pinned Circuit Engine. The engine emits Circuit JSON plus tscircuit diagnostics. Keep the exact source and output bytes; do not rebuild implicitly in Verify.

The committed example is intentionally incomplete electrically so warnings remain visible:

```bash
python3 scripts/demo/v1_demo.py \
  --run-dir /tmp/phicad-v1-demo \
  --engine-command '/absolute/path/to/bun /absolute/path/to/phicad/core/cli.mjs' \
  --strict
```

## 2. Verify exact Circuit JSON

Invoke Platform `design_build_check` or the corresponding CLI with:

- the exact Circuit JSON path;
- a fresh output directory;
- an explicit bounded service configuration;
- native evidence/revision only if it already exists; and
- expected tool versions.

PhiCad Verify must inspect the supplied bytes without reevaluating TSX. Platform validates result size, output count/bytes, symlink policy, artifact paths/hashes, diagnostics, and versions before writing manifest V3.

## 3. Read diagnostic status

A typical V1 result is:

```json
{
  "tscircuit": "carried-input",
  "kicad": "passed"
}
```

This means tscircuit findings were carried with the input and PhiCad/KiCad actually ran. Read counts and individual findings by origin; do not infer a pass from zero counts.

## 4. Open views

Use `platform_open_view` with the manifest path and expected manifest-file hash. Available targets are `phi`, `circuit-source`, `studio`, `verify`, `preview`, and `docs`. Preview is unavailable unless the operator configures `PHICAD_CIRCUIT_PREVIEW` as an absolute executable path.

`studio` and `verify` open the same installed PhiCad application and exact native artifact with different mode/focus intent. If no existing native artifact is bound, the native view is unavailable rather than fabricated.

## 5. Do not claim Apply

Native Circuit JSON-to-PhiCad materialization is plan-only in Platform. Use `apply-plan` / `design_apply_plan` to obtain a reviewed proposal; commit is refused at `platform_native_apply_plan_only`. A Verify result or plan is not an applied native revision. Missing apply builds return unavailable with a reason. See [Phi and MCP](../reference/phi-and-mcp.md).

## 6. Review before manufacturing

Even after native checks, independently review stackup, clearances, CAM, drills, slots, pours, keepouts, BOM identities, sourcing, PnP, stencil, mechanical fit, assembly, safety, and first article. Keep `DO-NOT-FABRICATE` on evaluation artifacts until those gates close.
