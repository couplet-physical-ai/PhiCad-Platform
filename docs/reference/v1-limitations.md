# V1 limitations

The developer preview is an integration-review checkpoint, not a usable signed public release.

## Native editing and materialization

- PhiCad is the selected native Studio + Verify authority. the release locks identify couplet-physical-ai/PhiCad at `b1d0d05cd8d699325d3ea04ee40855774097ef84` as a source-build pin. No native acceptance run or public binary artifact is claimed for this recut.
- Platform Circuit JSON-to-native materialization is **plan-only**: `apply-plan` / `design_apply_plan` never pass `--commit`, create an applied revision, or add an undo entry. Commit is refused at `platform_native_apply_plan_only`.
- PhiCad PhiCad native apply protocol supplies the plan protocol; an older installed build may lack it. That returns unavailable with a reason, not a fabricated plan.
- Verify does not create a native project, revision, history entry, or manufacturing-authoritative export.
- The stable `studio` and `verify` targets share one PhiCad executable; complete mode-specific focus behavior depends on a fixed reviewed launcher.
- The `preview` target needs a separately installed MIT review surface configured with `PHICAD_CIRCUIT_PREVIEW`. Without it, Preview is unavailable with a reason. Platform does not bundle or claim a mature preview editor.

## Installation and distribution

- The installer is local-only, no-network, no-`sudo`, and stages Platform files only.
- PhiCad, tscircuit, Phi, and KiCad tooling remain separately installed prerequisites.
- There is no signed/notarized public desktop installer or clean-machine security approval.
- OS-level deep-link registration is not enabled; CLI/MCP adapters are the fallback.
- Platform-original glue is Apache-2.0; verify separately licensed component distribution obligations.

## Verification semantics

- Manifest V3 has `tscircuit` and `kicad` origins only. V2 remains readable with a recorded `unavailable-v1` native-apply compatibility note.
- Carried tscircuit findings are not re-derived findings.
- Zero findings never imply a checker ran.
- PhiCad/KiCad DRC is an independent CAD check, not a fabricator review.
- `drc.json` may include run-volatile metadata even when board bytes are deterministic.
- Verify must inspect exact supplied Circuit JSON bytes; it must not discover stale output or reevaluate TSX.

## Manufacturing

- No demo artifact is fabrication-ready.
- Automated checks do not replace stackup, CAM, drill, stencil, BOM, sourcing, assembly, mechanical, DFM, safety, or first-article review.
- Manufacturing export is authoritative only from an explicitly saved and reviewed native PhiCad revision.
- Existing evaluation artifacts marked `DO-NOT-FABRICATE` remain review-only.

## Retired architecture

The `couplet-physical-ai/PhiCad-Studio` fork exists as a **separately licensed tool**; it is not deleted. That tool and OpenPCB are out of scope for this shipped release, not product dependencies, release artifacts, or push targets. Historical evaluation evidence must not be used to claim current Studio behavior, and no OpenPCB code may be copied or ported into the product.
