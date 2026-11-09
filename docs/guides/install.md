# Install the developer preview

> This installer stages Platform CLI/MCP code, local docs, locks, and notices. It performs no network downloads and does not bundle PhiCad, tscircuit, Phi, or KiCad tooling.

## Prerequisites

- macOS for the current supported developer path;
- Python 3.9 or newer;
- optionally, a separately installed Phi with stdio MCP support for the AI/MCP workflow;
- the exact pinned Circuit Engine package graph;
- one installed PhiCad application matching both Studio and Verify role pins;
- pinned `kicad-cli 10.99.0` where independent CLI DRC is required.

Run the non-mutating check:

```bash
./install.sh check --allow-non-macos
```

`PHICAD_BIN` may point to an existing executable for prerequisite probing. The installer does not accept caller executables through a manifest or handoff.

## Install

```bash
./install.sh install --allow-non-macos --yes
```

Default locations:

```text
~/.local/share/phicad-platform/releases/<version>/
~/.local/share/phicad-platform/current
~/.local/bin/phicad-platform
~/.local/bin/phicad-platform-mcp
~/.local/bin/phicad-doctor
~/.local/bin/phicad-update
```

The optional Phi configuration merge adds only the `phicad-platform` MCP entry, preserves unrelated entries, writes atomically, and enforces mode `0600`. It never copies a token or model credential.

## Verify

```bash
./install.sh doctor --allow-non-macos
phicad-platform --help
```

The doctor reports optional missing engines honestly. Discovering `PhiCad.app` only means the app exists; it does not assert signing, commit identity, independent review, or release approval.

## Update and uninstall

```bash
./install.sh update --allow-non-macos
./uninstall.sh
```

Updates are lock-driven and preserve the previous release until the new one is validated. Uninstall removes only manifest-listed files whose content has not been modified by the user.

## Not included

- no automatic dependency downloads;
- no public signed/notarized app bundle;
- no OS deep-link registration;
- no native materialization;
- no Platform-glue distribution license approval.
