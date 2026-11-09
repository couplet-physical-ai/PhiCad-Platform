# Security and threat model

The developer preview handles local source, generated CAD artifacts, and cross-view launch requests. Inputs are untrusted until validated.

## Trust boundaries

- Phi owns model credentials and permissions.
- Platform receives structured MCP/CLI data but never model credentials.
- Circuit Engine executes authored TSX only inside the bounded, isolated build path.
- PhiCad Verify receives exact Circuit JSON bytes plus fixed installed configuration.
- PhiCad Studio owns native project mutation and manufacturing-oriented export.
- Circuit Preview is display/review only and has no native-write authority.

## Cross-view handoffs

Launch schema V3 permits only project/manifest identity, expected hashes and native revision, source/target view, request ID, and focus intent. It rejects caller executables, commands, URLs, arbitrary shell text, credentials, environment dumps, repeated/unknown URI parameters, and oversized URIs.

Platform validates the regular manifest file, file SHA-256, canonical self-hash, project root, source/artifact containment, and target availability before launch. It uses argument vectors, a minimal allowlisted environment, and no shell. Targets must revalidate the same state. Mismatch fails closed as stale state.

## Build/check limits

- 60-second wall time;
- two-second termination grace;
- 2 MiB source;
- 32 MiB and 100,000 elements for Circuit JSON;
- 1 MiB each for stdout, stderr, and result JSON;
- 256 output files and 512 MiB retained output;
- regular, non-symlink inputs;
- no output symlinks;
- fresh caller-declared output roots;
- process-group termination and explicit pipe closing.

Do not use `spawnSync`, dynamic `bunx`, CDN execution, product-time downloads, inherited secrets/proxies, unrestricted network, Node exposure in a GUI renderer, or stale artifact discovery.

## Native mutation

Native materialization is plan-only in Platform. Generated geometry remains untrusted: Platform verifies the implemented PhiCad planner's schema, self-hash, input hash, project, counts, coverage and rejection structure, but never upgrades that report to native write authority. Commit requests fail at `platform_native_apply_plan_only`. Any future write path must independently validate supported elements, layers, coordinate range, geometry, connectivity, provenance, base revision, and artifact hashes.

Use one checked `round(mm * 1_000_000)` conversion. Reject NaN, infinity, overflow, invalid layers, and unsupported required geometry. Never silently approximate or discard copper, pours, keepouts, slots, cutouts, courtyards, stackups, or connectivity.

The mutation must execute inside one native PhiCad transaction and yield one revision plus one undo entry, or no persistent change.

## Diagnostic integrity

Canonical origins are `tscircuit` and `kicad`. Preserve finding origin and run status. Do not copy findings between origins, relabel carried findings as rerun, or infer a pass from zero counts.

## Supply chain

Exact locks are mandatory. Keep the tscircuit Zod 3 graph isolated from unrelated Zod 4 hosts and lazy-load `@tscircuit/eval` in a worker. Never use `--force` or `--legacy-peer-deps` to hide an incompatible graph.

OpenPCB and the separately licensed PhiCad-Studio tool are outside the current supply chain. They are not approved sources or push targets, and their code may not be copied into the product.
