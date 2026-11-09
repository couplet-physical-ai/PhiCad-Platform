# Updates and rollback

PhiCad Platform updates components by exact lock and compatibility evidence, never by floating branches or runtime downloads.

## Lock sources

- `versions.lock.json` and `scripts/install/versions.lock.json` pin the installed Platform view.
- `release/versions.lock` pins external release components and product roles.
- `release/validate_versions.py` rejects ranges, branches, missing components, and mismatched Studio/Verify PhiCad pins.

One PhiCad source/commit must serve both `PhiCad Studio` and `PhiCad Verify` roles.

## Update procedure

1. Update the exact PhiCad or tscircuit pin on a branch.
2. For PhiCad, update both Studio and Verify role records together.
3. Run unit, MCP, installer, e2e, docs, lock, lint, secret-scan, and package checks.
4. Repeat the real Verify service and fresh Phi MCP-client acceptance.
5. Refresh manifest/evidence hashes and any deterministic media derived from them.
6. Build the review archive twice and prove byte-for-byte reproducibility.
7. Install/update/uninstall under a clean temporary HOME.
8. Obtain independent review; workers do not self-merge.

## Rollback

The installer writes a versioned release directory and updates `current` only after validation. Retain the prior exact lock and release archive so `current` can be restored without rewriting components.

Never repair a failed update by weakening manifest validation, accepting a caller executable, force-installing incompatible package graphs, bypassing signatures, or discovering stale artifacts.

## Architecture rule

The separately licensed PhiCad-Studio tool and any `OpenPCB-app/*` remote are not update sources for this release. The fork exists but is out of scope; do not push to them. Current native updates come only from the reviewed PhiCad source.
