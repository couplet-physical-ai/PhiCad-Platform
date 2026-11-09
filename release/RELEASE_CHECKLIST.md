# Developer-preview release checklist

The current archive is review evidence. Do not mark it public/usable until every required gate closes.

## Architecture and locks

- [ ] `release/versions.lock`, root `versions.lock.json`, and installer lock validate.
- [ ] One `phicad` tool role pins the native source, version, and commit. Legacy duplicate-role locks remain readable only when their pins agree.
- [ ] tscircuit, core, eval, CLI, Circuit JSON, KiCad CLI, Bun, and Phi versions are exact.
- [ ] No current lock, package, installer, diagram, screenshot, or claim depends on OpenPCB or the separately licensed `couplet-physical-ai/PhiCad-Studio` tool (which exists but is out of scope).
- [ ] No worker recreated or pushed to `couplet-physical-ai/PhiCad-Studio` or any `OpenPCB-app/*` remote.

## Contracts

- [ ] Manifest V3 uses `native_artifact*` / `native_revision`, with a self-hashed `native_apply` block; V2 remains readable with a recorded default note.
- [ ] Exactly `tscircuit` and `kicad` diagnostic origins; unknown apply status and invalid one-revision/one-undo accounting are rejected.
- [ ] Every origin has explicit status; zero findings never imply a run.
- [ ] `studio` and `verify` launch targets resolve to one PhiCad native application and exact artifact.
- [ ] Launch handoffs contain only manifest/project identity, expected hashes/revision, target/source view, and focus intent.
- [ ] Stale/unsafe launch state fails closed.
- [ ] Verify inspects exact caller-supplied Circuit JSON bytes without TSX reevaluation and accepts arbitrary regular filenames.
- [ ] Native materialization is plan-only: CLI `apply-plan` and MCP `design_apply_plan` never pass `--commit` or claim an applied revision; `commit_refused` names `platform_native_apply_plan_only`.
- [ ] Real `plan.json` fixtures verify with PhiCad's pretty-JSON self-hash; unsupported apply builds return unavailable with a reason.
- [ ] `preview` uses only an absolute executable configured by `PHICAD_CIRCUIT_PREVIEW`; otherwise unavailable with a reason. Stale preview handoffs exit 3.
- [ ] Apply enforces section-7 ceilings and the current PhiCad 2 MiB Circuit JSON cap; process-group cancellation, symlink rejection, and no inherited proxies/secrets are tested.

## Tests and evidence

- [ ] Python unit, MCP, installer, and e2e tests pass.
- [ ] Ruff, strict MkDocs, Shellcheck, lock validation, and secret scan pass.
- [ ] Python 3.9–3.13 matrix jobs have five-minute caps and verbose progress.
- [ ] Real service, direct stdio MCP, and fresh Phi installed-client calls pass.
- [ ] Evidence records contain no full local transcript, credentials, or unbounded absolute-path dumps.
- [ ] Demo media is regenerated from post-pivot evidence and contains no retired architecture claims.
- [ ] Archive builds twice with identical bytes and recorded SHA-256.
- [ ] Clean temporary-HOME install, update, doctor, Phi-config merge, and uninstall pass.

## Legal and distribution

- [ ] Platform-original glue is licensed Apache-2.0 in LICENSE and NOTICE.
- [ ] Exact PhiCad/KiCad source scope, notices, modification history, and corresponding-source delivery are reviewed.
- [ ] tscircuit and Circuit JSON notices match exact package scope.
- [ ] Planned web preview source/dependencies/license are reviewed if included.
- [ ] Product naming preserves PhiCad, KiCad, tscircuit, Circuit JSON, and Phi attribution.
- [ ] Independent human review of PhiCad PRs #113/#114 and the Platform PR is complete.
- [ ] Signed/notarized installer and clean-machine security acceptance exist.

## Manufacturing

- [ ] No automated DRC result is represented as fabricator approval.
- [ ] Manufacturing export comes only from an explicitly saved and reviewed native PhiCad revision.
- [ ] Evaluation artifacts retain `DO-NOT-FABRICATE` until CAM, drill, BOM, sourcing, PnP, stencil, mechanical, assembly, safety, and first-article gates close.

## Current blockers

- Platform Apache-2.0 license and third-party notices.
- Independent review/merge decision for PhiCad native source pin.
- Platform native materialization/commit (plan-only here; required for prompt-to-native acceptance).
- Public signing/notarization and clean-machine review.
