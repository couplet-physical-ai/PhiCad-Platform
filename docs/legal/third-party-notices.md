# Third-party notices

This page is an engineering notice index for the developer-preview checkpoint. It does not grant a Platform-glue license or replace review of the exact source/binary scope.

| Component | Role | Notice evidence | Source/pin |
|---|---|---|---|
| PhiCad / KiCad | One native application family for Studio + Verify | GPL-3.0 root license plus file-specific KiCad/PhiCad notices | [PhiCad](https://github.com/couplet-physical-ai/PhiCad), pinned PhiCad source commit exact lock pin; [KiCad upstream](https://gitlab.com/kicad/code/kicad) |
| tscircuit packages | Circuit Engine | MIT notices for inspected package roots | Exact versions in `release/versions.lock` |
| Circuit JSON | Interchange/build format/package | ISC notice | `circuit-json@0.0.491` |
| Phi | Optional, separately installed agent harness | Separate program; not bundled by this repository | Any Phi with stdio MCP support |

License copies are indexed in the [third-party inventory](third-party-inventory.md), including the local [GPL-3.0 text](licenses/GPL-3.0.txt).

## Release rules

1. Pin exact sources and versions.
2. Preserve upstream names and file-specific notices.
3. Provide required corresponding source/notice access for the exact PhiCad/KiCad binary scope.
4. Keep tscircuit and Circuit JSON notices with distributed package content.
5. Do not treat product branding as upstream authorship or endorsement.
6. Platform-original glue is Apache-2.0; verify component-specific source and notice obligations.

## Retired architecture

OpenPCB and the separately licensed PhiCad-Studio tool are not current components and are not included in this notice payload. Historical experiments keep their own provenance outside this release. Do not copy or port their source into current product repositories.
