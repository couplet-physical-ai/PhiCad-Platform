# PhiCad Platform

A local, deterministic orchestration and review layer for Circuit JSON builds and PhiCad verification.

![Status: experimental](https://img.shields.io/badge/status-experimental-orange) ![License: Apache--2.0](https://img.shields.io/badge/license-Apache--2.0-blue)

Created at [Exowatt](https://exowatt.com). Published under the vendor-neutral [couplet-physical-ai](https://github.com/couplet-physical-ai) organization.

## Status and boundary

Experimental developer preview, **not** a fabrication approval or signed desktop release. Native Circuit JSON-to-PhiCad materialization is unavailable in V1. A checker reporting no findings is not proof of manufacturability. The separate [Circuit Preview](https://github.com/couplet-physical-ai/Circuit-Preview) viewer is optional.

Platform's installer installs its own Python glue, launcher, notices and lock locally; it does **not** download or bundle PhiCad. Install [GPL-3.0-or-later PhiCad](https://github.com/couplet-physical-ai/PhiCad) separately as a program and point the Platform at its CLI executable using `PHICAD_BIN` or an explicit verifier path. Platform **drives PhiCad across a process boundary**, through fixed CLI/exec argument vectors, bounded subprocess output and files; it does **not link** PhiCad code into this Apache-licensed glue. PhiCad retains its own GPL-3.0-or-later license and file-specific KiCad notices. Redistributors of PhiCad binaries must satisfy the applicable GPL source and notice obligations; Platform's Apache license does not relicense PhiCad.

The upstream [tscircuit runtime](https://github.com/tscircuit/tscircuit), pinned via npm, carries MIT notices; Circuit JSON is ISC. They remain separately pinned components, not relicensed by Platform. The OpenPCB-derived [PhiCad-Studio](https://github.com/couplet-physical-ai/PhiCad-Studio) is AGPL-3.0-or-later and **not part of the current Platform release boundary**: it is neither a lock component nor an installer payload. Here “Studio” and “Verify” refer to roles/views of the *same GPL PhiCad* native authority, not to that separate AGPL application.

## Install and quickstart

Requires Python 3.9+, `uv`, and macOS for the supported desktop integration. The Python package has no runtime dependency on Exowatt services. From a checkout:

```bash
uv run release/validate_versions.py --repo-root .
uv run -m pytest -q release/tests tests/unit tests/install tests/e2e
uv run python scripts/demo/v1_demo.py --help
./install.sh check --allow-non-macos
./install.sh install --allow-non-macos --yes
./install.sh doctor --allow-non-macos
```

The install script stages only local Platform files. The demo's **real** build/verify lane needs the separately installed [upstream tscircuit runtime](https://github.com/tscircuit/tscircuit) pinned via npm (`bun` + tscircuit) and a PhiCad executable; it is not a zero-download demo. For a self-contained Python contract demo without those programs, run the fake-engine integration test:

```bash
uv run -m pytest -q tests/e2e/test_v1_demo.py
```

For a real run, supply an explicit installed engine command and fresh output directory:

```bash
PHICAD_BIN=/path/to/phicad-cli \
  uv run python scripts/demo/v1_demo.py \
  --run-dir /tmp/phicad-platform-demo \
  --engine-command '/path/to/bun /path/to/phicad/core/cli.mjs' --strict
```

The sample `examples/demo-v1-led.tsx` is a synthetic, deliberately incomplete resistor–LED trace, not a product board or fabrication reference. The V2 I2C conditioner is an evaluation-only example. Neither establishes real-hardware qualification.

## Configuration and locks

`versions.lock.json` and `release/versions.lock` record immutable reviewed native and npm component versions. Phi is optional, separately installed and not version-pinned: any Phi with stdio MCP support can use Platform's MCP server. An exact PhiCad commit pin is **not** a promise that a compatible public release artifact or package exists. Check the target repository for the actual commit and build it according to its GPL instructions; the Platform installer never fetches it. Set `PHICAD_BIN` for the native executable and `PHICAD_CORE_CLI` / `PHICAD_BUN` / `PHICAD_KICAD_CLI` when running optional real-tool tests. No credentials, hosted API or Exowatt services are required. See [installation](docs/guides/install.md), [manifest and sync](docs/reference/manifests-and-sync.md), and [security limits](docs/security/threat-model.md).

## License and attribution

Platform-original glue is [Apache-2.0](LICENSE), copyright Exowatt, Inc.; see [NOTICE](NOTICE). Upstream programs and libraries retain their own terms. The existing [`LICENSES/`](LICENSES/) copies and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) identify GPL, MIT and ISC terms for exact release components; they are not permission to relicense or bundle those programs under Apache. The separately licensed PhiCad native application must retain its GPL terms. Consult the component lock and the actual artifacts before redistributing a combined archive.

## Contributing

Follow [the organization contributing guide](https://github.com/couplet-physical-ai/.github/blob/main/CONTRIBUTING.md). Commit with DCO sign-off (`git commit -s`); no CLA required.

## Security

Report vulnerabilities privately via [GitHub private vulnerability reporting](https://github.com/couplet-physical-ai/PhiCad-Platform/security/advisories/new), or contact software@exowatt.com. Do not publish an exploit as a public issue.
