# Authority modes

PhiCad Platform exposes two explicit authority modes. It never resolves conflicts with hidden peer-to-peer synchronization or last-writer-wins behavior.

## Native

**Canonical source:** the KiCad/PhiCad project and its native revision/history.

Use the PhiCad **Studio** view for supported native edits and manufacturing-oriented export. Use the **Verify** view of the same installed application for deterministic checks. Both views refer to one native authority and one `kicad` diagnostic origin.

A manufacturing export is eligible only from an explicitly saved and reviewed native revision.

## Code-linked

**Canonical source:** TS/TSX plus supported manual-edit data.

The pinned Circuit Engine rebuilds Circuit JSON deterministically. Circuit JSON is an interchange/build artifact, not a lossless source representation. Review surfaces may annotate or propose supported edits, but they do not silently rewrite native state.

## Detach to native copy

An unsupported structural edit requires an explicit detach operation. Detach creates a separate Native project with new identity and provenance; it does not pretend to preserve a reversible TSX mapping.

Platform native materialization remains **plan-only**. `apply-plan` / `design_apply_plan` can record `planned` or `rejected` from PhiCad, but cannot create a native revision or undo entry. A missing apply capability is recorded as `unavailable-v1` with a reason. Commit requests are refused at `platform_native_apply_plan_only`, even when the installed PhiCad supports commit.

V3 uses `native_artifact` / `native_revision` for existing evidence and a separate `native_apply` block for apply state. Reading an existing evidence revision or approving preview intent does not mean Platform applied it. Future detach/materialization support must be transactional and create exactly one native revision plus one undo entry, or no persistent change.

## Conflict behavior

When expected hashes, native revision, or project identity disagree, the target refuses the operation and reports stale state. The user must rebuild, reopen the correct project, or deliberately detach. The Platform never chooses a winner by timestamp.
