# Cross-view links

A cross-view link is a validated local **open request**, not synchronization, a mutation command, or an authentication channel.

## Stable targets

| Target | Meaning |
|---|---|
| `phi` | Open the project in the sole AI harness. |
| `circuit-source` | Open the TSX source. |
| `preview` | Open the separately installed thin Circuit Preview/review surface; no native authority. |
| `studio` | Open the native project in PhiCad with Studio/editing intent. |
| `verify` | Open the same native project in PhiCad with Verify/checking intent. |
| `docs` | Open version-matched local Platform documentation. |

`studio` and `verify` resolve to the same installed PhiCad application family and exact native artifact. They are mode/focus identifiers, not separate authorities.

## Schema V3

`io.github.couplet-physical-ai.phicad.platform-launch/v3` carries only:

- request ID and schema;
- source and target view;
- focus intent;
- project/design ID;
- absolute local manifest path;
- expected manifest-file SHA-256 and canonical manifest self-hash;
- expected source, Circuit JSON, native revision/native evidence, and artifact hashes.

It never carries credentials, environment dumps, shell text, executable paths, caller commands, or caller URLs.

## Validation

Before resolving a launcher, Platform:

1. requires a regular, non-symlink manifest file;
2. validates its schema and canonical self-hash;
3. compares the expected manifest-file SHA-256;
4. resolves the project root from validated manifest data;
5. rechecks every referenced source, Circuit JSON, native artifact, output artifact, and apply-plan hash;
6. constrains source and artifacts to their expected roots; and
7. resolves a fixed installed adapter, rechecking identity again before execution.

Any manifest bytes, self-hash, project identity, native revision/hash, or artifact mismatch returns `stale_handoff` (CLI exit 3), including for Preview. An absent fixed launcher returns `target_unavailable` with a reason. Targets must revalidate the same identity rather than trusting the caller.

## Fixed adapters

Platform uses argument vectors, a minimal allowlisted environment, and no shell. Callers cannot substitute an executable or URL. The native adapter looks for `phicad` on PATH, then a conventional sibling `PhiCad/phicad/bin/phicad` checkout, then `/Applications/PhiCad.app` or `~/Applications/PhiCad.app`. Both Studio and Verify resolve to **identical argv and native artifact**. Native launch discovery does not use `PHICAD_BIN` or another environment override.

Preview resolves **only** from `PHICAD_CIRCUIT_PREVIEW`, an operator-configured absolute executable path. It never guesses a PATH command or accepts a caller URL. Unset, relative, nonexistent, or non-executable values produce an unavailable plan with a reason. A configured adapter receives:

```text
<configured-executable> --manifest <absolute-manifest-path> --expected-manifest-sha256 <file-hash>
```

The executable belongs to the local launch plan, never the serialized handoff request. The preview process must independently validate the manifest and references; a successful launch is not proof of rendering or review. Preview/review intent applies nothing and approves no fabrication.

OS deep-link registration remains gated on signed clean-machine security review. CLI/MCP launch calls are the developer-preview fallback.
