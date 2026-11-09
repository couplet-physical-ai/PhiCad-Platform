# ADR 0002: PhiCad is the native Studio and Verify authority

- **Status:** Accepted
- **Date:** 2026-09-15
- **Decision owner:** PhiCad Platform

## Context

The first developer-preview checkpoint used an OpenPCB-derived Studio experiment and a separate PhiCad Verify lane. That split created two native authorities, an AGPL product dependency, duplicate editor work, and a materialization boundary that did not exist. The Studio fork became a separately licensed tool, and the adopted product direction is to exclude it from this shipped release. (V3 factual correction: it exists; the earlier description of deletion was incorrect.)

PhiCad is a GPL-3.0 KiCad fork with native board editing, transactions, save/refresh behavior, and fabrication-oriented checks. It can provide both the interactive Studio view and the deterministic Verify view over the same native project.

## Decision

1. **Phi remains the sole AI harness and MCP client.** It conducts deterministic tools; no other component embeds a competing agent runtime or credentials.
2. **PhiCad is one native application family with two product views:**
   - **Studio** opens and edits the native KiCad/PhiCad project.
   - **Verify** runs or presents deterministic checks against that same project and its exact artifacts.
3. **There is one native authority and one native diagnostic origin.** Canonical manifests use `kicad` for PhiCad/KiCad findings. They do not create separate `studio`, `verify`, or `openpcb` checker lanes for one engine.
4. **Circuit JSON remains the versioned interchange/build artifact.** V1 Verify inspects the caller-supplied bytes without reevaluating TSX.
5. **A thin, separate MIT web surface may preview Circuit JSON and collect review intent.** It is not a second native editor, does not own manufacturing export, and does not import OpenPCB code.
6. **Cross-view handoffs stay data-only and fail closed.** A request contains project/manifest identity, expected hashes and native revision, target view, and focus intent. Targets revalidate the manifest bytes and local project before opening.
7. **Native materialization is explicitly unavailable in V1.** A future Circuit JSON-to-native operation must be planned, validated, transactional, cancellable, and create exactly one native revision plus one undo entry. Until then, no surface may claim Apply succeeded.
8. **OpenPCB is not a product dependency.** Do not push to the separately licensed `couplet-physical-ai/PhiCad-Studio` fork or any `OpenPCB-app/*` remote. Do not vendor, copy, or port OpenPCB code.

## Launch contract

The stable target identifiers remain `studio` and `verify`. Both resolve to the same installed PhiCad application and exact native artifact; the identifier expresses mode/focus intent, not a different executable or authority. An unavailable fixed launcher returns a reason rather than accepting a caller-supplied command or URL.

## Consequences

- The release lock has one PhiCad source and commit for both Studio and Verify roles.
- Platform manifest schema V2 has diagnostic origins `tscircuit` and `kicad` only.
- OpenPCB and the separately licensed Studio tool remain outside the current installer, release, legal inventory, diagrams, screenshots, and product claims.
- GPL-3.0 obligations for PhiCad/KiCad and permissive tscircuit/Circuit JSON notices remain explicit.
- Historical OpenPCB evaluation artifacts remain historical, separately licensed evidence and are not current release evidence.
- The web preview surface must be scoped and reviewed independently before it is shipped.
- The executable Circuit Engine role uses the upstream tscircuit runtime pinned via npm (https://github.com/tscircuit/tscircuit), not a separately published fork.
