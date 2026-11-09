# Third-party inventory

This is the human-readable companion to `release/versions.lock`. The lock and generated inventory are authoritative for exact pins.

| Component | Source | License evidence | Current role/pin |
|---|---|---|---|
| PhiCad / KiCad | <https://github.com/couplet-physical-ai/PhiCad.git> | Pinned root `LICENSE`: GNU GPL version 3; file-specific notices also apply | One source/commit for Studio + Verify; pinned PhiCad source commit exact lock pin |
| KiCad upstream | <https://gitlab.com/kicad/code/kicad.git> | GPL-family and file-specific upstream notices | Native technology basis and canonical `kicad` diagnostic origin |
| `tscircuit` | <https://www.npmjs.com/package/tscircuit> | MIT package notice | Circuit Engine aggregate `0.0.2561` |
| `@tscircuit/core` | <https://www.npmjs.com/package/@tscircuit/core> | MIT package notice | `0.0.1914` |
| `@tscircuit/eval` | <https://www.npmjs.com/package/@tscircuit/eval> | MIT package notice | `0.0.1407`, lazy worker only |
| `@tscircuit/cli` | <https://www.npmjs.com/package/@tscircuit/cli> | Inspect exact package scope at release | `0.1.2084` |
| `circuit-json` | <https://www.npmjs.com/package/circuit-json> | ISC metadata/notice | `0.0.491` |
| Phi | optional, separately installed agent harness | separate program, not distributed with Platform; see its repository | any Phi with stdio MCP support; not bundled |

## Included license copies

| Evidence | Repository copy |
|---|---|
| PhiCad root GPL-3.0 | [`GPL-3.0.txt`](licenses/GPL-3.0.txt) |
| tscircuit core MIT | [`MIT-tscircuit-core.txt`](licenses/MIT-tscircuit-core.txt) |
| tscircuit eval MIT | [`MIT-tscircuit-eval.txt`](licenses/MIT-tscircuit-eval.txt) |
| tscircuit runframe MIT (investigated but not a required lock component) | [`MIT-tscircuit-runframe.txt`](licenses/MIT-tscircuit-runframe.txt) |
| Circuit JSON ISC | [`ISC-circuit-json.txt`](licenses/ISC-circuit-json.txt) |

## Excluded retired dependency

OpenPCB and the separately licensed PhiCad-Studio tool are intentionally absent from current locks, inventory, and license payload. Historical research artifacts remain outside this release and do not authorize code reuse.

## Release requirement

Refresh this table, the exact lock, generated inventory, notices, and hashes whenever the PhiCad commit or any package version changes.
