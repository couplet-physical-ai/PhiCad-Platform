# ADR 0001: Separate repositories, one tested bundle

- **Status:** Superseded by [ADR 0002](0002-phicad-native-studio-and-verify.md)
- **Date:** 2026-09-14
- **Corrected:** 2026-09-15

## Context

The original V1 proposal combined Phi, a tscircuit-based Circuit Engine, an OpenPCB-based visual application, and a KiCad/PhiCad verification lane. These systems had different ownership, languages, dependency graphs, release cadences, and licenses.

One premise in the original text was wrong: **OpenPCB is not KiCad-derived**. It is an independent AGPL-3.0-or-later application. The proposal also treated an OpenPCB-derived Studio and PhiCad Verify as separate native authorities. That product direction was retired on 2026-09-15.

## Decision retained

Keep mature engines in their own repositories and assemble reviewed, compatible commits through one thin Platform repository. The Platform owns contracts, exact locks, compatibility tests, installation metadata, cross-view launch behavior, documentation, rollback, and release evidence. It does not copy engine source into a monorepo.

## Decision retired

The Platform will not ship an OpenPCB-derived Studio, include the separately licensed `couplet-physical-ai/PhiCad-Studio` tool (which exists but is out of scope), or push work to any `OpenPCB-app/*` remote. It will not copy, vendor, translate, or port OpenPCB code into PhiCad or another product.

OpenPCB research and historical evaluation evidence remain subject to their original licenses and provenance, but they are not part of the current product architecture, lock, installer, or release inventory.

## Consequences

- A single bundle can still present one workflow without erasing repository or license boundaries.
- Exact component pins, compatibility evidence, and rollback remain mandatory.
- Cross-view handoffs stay manifest-bound and fail closed.
- Native Studio and Verify ownership is redefined by ADR 0002.
- Any future dependency requires fresh technical and license review; no prior OpenPCB experiment is an implementation shortcut.
