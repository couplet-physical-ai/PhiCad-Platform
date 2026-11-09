# Troubleshooting

| Symptom | Meaning | Action |
|---|---|---|
| `stale_handoff` | Manifest bytes, self-hash, project identity, native revision, or artifact hash changed | Rebuild/reopen the exact project and generate a new handoff; never bypass the check. |
| `target_unavailable` for `studio` or `verify` | The fixed PhiCad launcher or target artifact is absent | Install the exact pinned PhiCad build and verify `phicad` on PATH, a conventional sibling checkout, or installed `PhiCad.app`; do not pass an arbitrary executable. |
| Studio and Verify appear to open the same app | Expected architecture | They are two modes/focus intents of one native PhiCad authority. |
| `kicad` has zero findings but status is `not-run`/`unavailable` | No native checker pass occurred | Run PhiCad Verify; never relabel zero counts as passed. |
| `tscircuit` is `carried-input` | Findings came with supplied Circuit JSON | Re-run Circuit Engine if fresh tscircuit diagnostics are required. |
| Verify rejects an arbitrary input filename | Contract regression | The service must accept any regular caller-supplied filename and inspect exact bytes without TSX reevaluation. |
| Output rejected as stale or unsafe | Result/artifact paths or hashes do not match the declared run | Use a fresh empty output directory; do not reuse discovered files or symlinks. |
| Native Apply is unavailable | V1 boundary | This is intentional. Do not simulate an applied revision from preview/Verify output. |
| Installer finds no product engine | PhiCad and Circuit Engine are separate prerequisites | Run `./install.sh check --allow-non-macos`; install exact pins outside the Platform payload. |
| A document calls the separately licensed Studio fork deleted | Retired architecture residue | Correct the factual claim: the fork exists privately, out of scope for this release. Follow ADR 0002; do not push to that repository. |
| Release package is blocked | Legal/review gates remain | Verify component licenses and independent PhiCad review, then rebuild all evidence. |

## Bounded-process failures

Timeouts and output-limit failures terminate the entire process group, close inherited pipes after termination begins, and retain bounded diagnostic tails. Hosted CI has a five-minute job cap and verbose per-test progress so a hang is diagnosable.

## Security rule

Never fix a launch or verification problem by accepting shell strings, caller URLs, inherited credential environments, dynamic downloads, symlink inputs/outputs, or stale artifact discovery.
