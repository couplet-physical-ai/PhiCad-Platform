# Repository map

PhiCad Platform is the integration repository, not a monorepo for engines.

| Concern | Product role | Source boundary |
|---|---|---|
| AI harness | Phi | External pinned harness; sole MCP client |
| Circuit build | Circuit Engine | Upstream tscircuit runtime pinned via npm: https://github.com/tscircuit/tscircuit |
| Browser review | Circuit Preview | Planned separate thin MIT web surface |
| Native editing | PhiCad Studio | Studio mode of `couplet-physical-ai/PhiCad` |
| Native checking | PhiCad Verify | Verify mode/service of the same `couplet-physical-ai/PhiCad` commit |
| Contracts/install/evidence | PhiCad Platform | This repository |

## Where changes belong

- Put manifest, orchestration, launch, installer, docs, compatibility, and release-evidence changes here.
- Put native project operations, transactions, Studio UI, Verify service, and KiCad integration in PhiCad.
- Put runtime changes in the isolated pinned tscircuit npm package environment; see upstream https://github.com/tscircuit/tscircuit.
- Put future web preview code in its own thin permissively licensed surface after scope/review.

## Guardrails

- Do not copy PhiCad, KiCad, tscircuit, or Phi into this repository.
- Do not push to the separately licensed `couplet-physical-ai/PhiCad-Studio` repository (it exists but is out of scope for this release) or any `OpenPCB-app/*` remote.
- Do not vendor, translate, or port OpenPCB code into any current product repository.
- Keep Studio and Verify pinned to one PhiCad source/commit.
- Preserve exact locks, upstream notices, and independent review.

## Current Platform paths

| Path | Responsibility |
|---|---|
| `src/phicad_platform/` | Manifest V3 (V2 readable), bounded check/apply-plan orchestration, six MCP tools, launch schema V3 |
| `scripts/install/` | Safe local installer/update/doctor |
| `scripts/demo/` | Reproducible evidence and media rendering |
| `release/` | Lock validation, inventory, package, secret scan, checklist |
| `docs/` | Version-matched product, security, legal, and decision docs |
| `tests/` | Unit, MCP, installer, e2e contracts |
