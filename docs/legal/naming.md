# Naming and attribution

Product-role names and upstream technology names must both remain clear.

| Name | Use | Do not imply |
|---|---|---|
| **PhiCad Platform** | The integrated workflow, contracts, installer, and release evidence | That Platform authored PhiCad, KiCad, tscircuit, or Circuit JSON |
| **PhiCad Studio** | The native editing mode of the PhiCad application | A separate engine, repository, or authority from Verify |
| **PhiCad Verify** | The deterministic checking mode/service of the same PhiCad application | A second native project or independent design owner |
| **PhiCad** | The GPL-3.0 KiCad fork/application family | That KiCad attribution or file-specific notices can be removed |
| **KiCad** | Upstream technology and canonical native diagnostic origin | Upstream endorsement of the product |
| **Circuit Engine** | Product role for the pinned tscircuit runtime | authorship of tscircuit packages |
| **Circuit JSON** | Interchange/build artifact and package identity | A lossless authored-TSX representation |
| **Phi** | Sole AI harness | That credentials belong in manifests or engine config |

The stable cross-view identifiers `studio` and `verify` are lowercase protocol values. They express target mode/focus, not separate binaries.

OpenPCB is not a current product component or branding basis. Do not use `PhiCad Studio` to refer to the separately licensed OpenPCB-derived tool; that repository exists but is out of scope for this release and is not a push target.

## Preferred release language

> PhiCad Studio and Verify are two views of one PhiCad/KiCad native application, integrated with the pinned tscircuit Circuit Engine through manifest-bound Platform contracts.

## Avoid

- “four independent native engines”;
- “OpenPCB-based Studio”;
- “independent Studio and Verify authorities”;
- “fabrication-ready” based only on DRC;
- any wording that turns an unmerged PR or discovered app bundle into an approved release.
