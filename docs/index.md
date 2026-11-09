# PhiCad Platform

**Developer-preview documentation for one manifest-bound PCB workflow.**

PhiCad Platform combines separate, exactly pinned systems without inventing a second native authority:

| Product role | Implementation boundary | Authority |
|---|---|---|
| **Phi** | Sole AI harness and MCP client | Prompts, tool selection, permissions, explanations |
| **Circuit Engine** | tscircuit exact package graph | TSX build and Circuit JSON diagnostics |
| **Circuit Preview** | Planned thin MIT web surface | Preview and review intent only |
| **PhiCad Studio** | Studio view of the PhiCad/KiCad application | Native project editing and export |
| **PhiCad Verify** | Verify view of the same PhiCad application | Native checks and evidence |
| **PhiCad Platform** | This repository | Manifests, locks, launch, installer, docs, evidence |



## What is real in this checkpoint

- A bounded service verifies exact caller-supplied Circuit JSON bytes without TSX reevaluation.
- A canonical manifest binds source, Circuit JSON, native evidence, generated artifacts, tool versions, diagnostics, and approval state.
- The credential-free stdio MCP server exposes deterministic operations to Phi.
- Cross-view launch requests are manifest/hash-bound, data-only, and fail closed.
- `studio` and `verify` are stable modes that resolve to the same installed PhiCad native application.
- Locks and inventory pin one PhiCad commit for both roles.
- Installer, docs, demo, secret scan, package, and CI checks are reproducible and local-first.

## What is not claimed

- Native Circuit JSON-to-PhiCad materialization is **plan-only** in Platform; missing apply builds are `unavailable-v1`. No Platform surface commits a native revision.
- Verify success does not mean an applied native revision exists.
- No signed/notarized public desktop bundle is established.
- No automatic download or trust of an unpinned component occurs.
- No zero-error DRC result proves manufacturability or fabrication readiness.
- No Platform-glue distribution license has been authorized.

## Diagnostic model

Manifest schema V3 (with V2 read compatibility) names exactly two origins:

- `tscircuit`; and
- `kicad` for PhiCad/KiCad findings in both Studio and Verify views.

Every origin has a status such as `carried-input`, `passed`, `failed`, `not-run`, or `unavailable`. Zero findings without an executed checker are never labeled as a pass.

## Architecture pivot

The accepted architecture is documented in [ADR 0002](decisions/0002-phicad-native-studio-and-verify.md). OpenPCB and the separately licensed PhiCad-Studio tool (which exists, but is out of scope for the shipped release) are not current product components, dependencies, release evidence, or push targets. No OpenPCB code may be copied or ported into the Platform or PhiCad.

## Start here

- [Architecture and ownership](architecture/overview.md)
- [Install the developer preview](guides/install.md)
- [First project](guides/first-project.md)
- [Manifests and synchronization](reference/manifests-and-sync.md)
- [Cross-view links](reference/cross-view-links.md)
- [Phi and MCP](reference/phi-and-mcp.md)
- [Security and threat model](security/threat-model.md)
- [V1 limitations](reference/v1-limitations.md)
- [Release licensing](legal/release-licensing.md)

## Evidence semantics

| Label | Meaning |
|---|---|
| **Implemented** | Code and tests exist in this repository or in the exact pinned component commit. |
| **Verified** | A committed evidence record identifies the invocation and hashes. |
| **Planned** | Target behavior; not a release claim. |
| **Unavailable V1** | Explicitly outside V1 and must not be simulated or inferred. |
| **Blocked** | A named owner/review/legal/trust gate is open. |

The demo is intentionally incomplete electrically and explicitly non-fabrication-ready. It exists to exercise deterministic evidence, not to disguise missing native materialization.
