# Third-party notices

This Platform repository contains original Apache-2.0 glue. Its current reviewed locks refer to **separate, unbundled** programs and packages; see [`versions.lock.json`](versions.lock.json), [`release/versions.lock`](release/versions.lock) and the actual release inventory for the version being distributed. License-text copies in [`LICENSES/`](LICENSES/) preserve notices, not redistribution authorization.

## PhiCad / KiCad

[PhiCad](https://github.com/couplet-physical-ai/PhiCad) is the native program used as both Studio and Verify authority. It is separately installed and executed by CLI/subprocess; it is not linked into Platform. PhiCad's KiCad-derived root is GPL-3.0-or-later; individual files may require other applicable notices. Any PhiCad binary distribution must supply its complete applicable notices, exact source and corresponding source in accordance with its GPL terms. KiCad upstream: <https://gitlab.com/kicad/code/kicad.git>. Repository copy: [`LICENSES/GPL-3.0.txt`](LICENSES/GPL-3.0.txt).

The lock's exact native commit is an integration pin, **not** evidence that a public compiled release artifact exists. No PhiCad executable is shipped in the Platform repository or installed by the Platform installer.

## tscircuit / Circuit Engine

The separately pinned tscircuit graph includes `tscircuit`, `@tscircuit/core`, `@tscircuit/eval` (lazy worker), `@tscircuit/cli`, and `circuit-json`. Inspected tscircuit package roots carry MIT notices; Circuit JSON package metadata identifies ISC. Preserve their notices for each actual release scope. Repository copies: [`LICENSES/MIT-tscircuit-core.txt`](LICENSES/MIT-tscircuit-core.txt), [`LICENSES/MIT-tscircuit-eval.txt`](LICENSES/MIT-tscircuit-eval.txt), [`LICENSES/MIT-tscircuit-runframe.txt`](LICENSES/MIT-tscircuit-runframe.txt) (investigated, not a required current lock), and [`LICENSES/ISC-circuit-json.txt`](LICENSES/ISC-circuit-json.txt).

The [upstream tscircuit runtime](https://github.com/tscircuit/tscircuit) is pinned via npm; no Circuit Engine fork or release artifact is required. [Circuit Preview](https://github.com/couplet-physical-ai/Circuit-Preview) is an optional separate viewer, not a locked Platform payload.

## External AI harness

Phi is an optional, separately installed agent harness. Any Phi with stdio MCP support can use Platform's credential-free MCP surface; no Phi executable, version or release artifact is bundled or required for the Platform contracts.

## Excluded AGPL component

The OpenPCB-derived [PhiCad-Studio](https://github.com/couplet-physical-ai/PhiCad-Studio) retains AGPL-3.0-or-later and is **not** in the current Platform lock, installer payload or release boundary. Its absence does not change the GPL terms of native PhiCad or the Apache terms of Platform's own glue. Adding AGPL Studio later needs a fresh release-boundary review.
