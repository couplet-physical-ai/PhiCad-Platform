# Upstream attribution

Product names describe project roles; they do not replace upstream identities or licenses.

## Current components

- **PhiCad / KiCad** — PhiCad is the GPL-3.0 KiCad fork used for both native Studio and Verify views. Preserve the exact root license, KiCad attribution, and file-specific notices selected by a release.
- **tscircuit** — the basis of Circuit Engine. The exact `tscircuit`, `@tscircuit/core`, `@tscircuit/eval`, and `@tscircuit/cli` package versions remain visible in locks and notices.
- **Circuit JSON** — the versioned interchange/build artifact. Preserve its package name and ISC notice where distributed.
- **Phi** — the sole AI harness. It is pinned as an external prerequisite and is not bundled by this repository.

## Retired component path

OpenPCB was investigated in an earlier experiment but is not part of the current product architecture, lock, installer, inventory, or release. The PhiCad-Studio fork exists as a separately licensed tool, out of scope for the shipped release, and must not be used as a push target, and no OpenPCB code may be copied or ported into the current product.

Historical OpenPCB artifacts retain their original provenance and license terms outside this release. This page does not reinterpret those terms or authorize reuse.

## Rule

Every release inventory must identify exact source, version/commit, product role, vendoring state, and required notice. Product branding never turns upstream work into Platform-authored work.
