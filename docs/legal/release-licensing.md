# Release licensing

Platform's original glue is licensed under [Apache-2.0](https://github.com/couplet-physical-ai/PhiCad-Platform/blob/main/LICENSE), with a [NOTICE](https://github.com/couplet-physical-ai/PhiCad-Platform/blob/main/NOTICE). The checked-in [third-party notice ledger](third-party-notices.md) and root `LICENSES/` texts are retained for separately licensed components.

PhiCad is a separately installed and executed KiCad-derived GPL-3.0-or-later program used for native Studio and Verify views. Platform drives its CLI across a process boundary and does not link it. Exact source identity, file-specific license notices, corresponding source and distribution requirements must be assessed for every binary actually packaged. The tscircuit libraries are MIT and Circuit JSON is ISC. OpenPCB-derived AGPL-3.0-or-later PhiCad-Studio is not in this lock or installer, nor is it a synonym for native PhiCad's Studio view.

Phi is an optional, separately installed agent harness; any Phi with stdio MCP support can use Platform. It is not a locked or distributed component. The exact PhiCad commit is a source pin and does not promise a public binary artifact. The local installer downloads neither PhiCad nor Phi.

Before redistributing a bundle, verify the precise component versions, sources and notices, whether any built executable is included, legal/trademark approval and release signing. A successful developer-preview test is not hardware/fabrication approval.
