# Release process

> **Status: developer-preview review process**

A candidate is an exact compatibility set, not a collection of latest dependencies. Engine repositories remain separate; Platform records one tested bundle contract.

## Inputs

Every candidate identifies:

- Platform version and source commit;
- Phi version;
- one exact PhiCad source/commit shared by Studio and Verify roles;
- exact tscircuit, core, eval, CLI, Circuit JSON, Bun, and KiCad CLI versions;
- manifest and launch schema versions;
- fixture/evidence changes;
- required notices/source delivery; and
- a rollback target.

## Gate sequence

### 1. Architecture and dependency boundary

- Validate all locks without `--force` or `--legacy-peer-deps`.
- Confirm Studio and Verify role records match exactly.
- Keep the tscircuit Zod 3 package graph isolated and `@tscircuit/eval` lazy-worker-only.
- Confirm no current dependency, package, screenshot, or claim relies on the retired OpenPCB path.

### 2. Bounded Verify contract

- Accept arbitrary regular Circuit JSON filenames.
- Inspect exact supplied bytes without TSX reevaluation.
- Reject symlinks, stale output, unsafe paths, malformed results, missing binaries, timeout, oversized source/JSON/output, and excessive files/elements.
- Preserve path-keyed artifact hashes and scalar tool versions.
- Preserve exact diagnostic origin and status for `tscircuit` and `kicad` only.

### 3. Manifest and launch

- Verify manifest V3 canonical self-hash, V2 read compatibility and every referenced hash.
- Test valid and stale handoffs for all stable targets.
- Confirm `studio` and `verify` use one fixed PhiCad application/target artifact.
- Confirm requests carry only identity, expected hashes/revision, view, and focus intent.
- Confirm fixed argument vectors, minimal environment, no shell, and no caller command/URL.

### 4. Installer and MCP

- Run direct stdio MCP protocol tests and a fresh Phi installed-client call.
- Confirm no credentials are copied and full model transcripts stay local.
- Run clean temporary-HOME install, update, doctor, config merge, and uninstall.
- Confirm no network or `sudo` use and preserve user-modified files.

### 5. Demo and media

- Run the committed TSX fixture against exact tools.
- Match all expected diagnostic codes/counts.
- Regenerate video/poster only from the checked run.
- State native materialization is plan-only (missing apply builds: `unavailable-v1`) and fabrication readiness false.
- Do not use retired screenshots or simulate an applied native revision.

### 6. Package and review

- Run Python 3.9–3.13 CI, Ruff, strict docs, Shellcheck, lock validation, and secret scan.
- Build twice with one `SOURCE_DATE_EPOCH` and compare bytes/hashes.
- Review inventory, notices, licenses, excluded paths, and archive contents.
- Obtain independent human review; workers never self-merge.
- Keep PR/release draft until legal, source/notice, signing, and clean-machine gates close.

## Native materialization (future gate)

Native materialization is outside V1. When implemented, add hard gates for full-plan validation, coordinate/layer semantics, unsupported geometry, expected revision, cancellation, one native transaction, exactly one revision and one undo entry, rollback, restart/reload, and manufacturing-export provenance.

## Version bumps

For a tscircuit update, change exact package pins, rebuild fixtures, review Circuit JSON differences, rerun bounded/security checks, and refresh evidence/notices.

For a PhiCad update, change both Studio and Verify role pins together; rerun native/project, service, MCP, launch, artifact, DRC, docs, package, and installed-client acceptance.

## Promotion language

- **Developer preview:** review-only; behavior may change.
- **Implemented:** exact code and evidence exist for the declared contract.
- **Planned:** design exists, implementation/evidence does not.
- **Unavailable V1:** explicitly outside V1; never simulate it.
- **Fabrication-ready:** never granted by Platform alone; requires an explicitly reviewed native revision plus manufacturing and human gates.
