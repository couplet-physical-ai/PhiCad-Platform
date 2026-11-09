# Distribution boundaries

PhiCad Platform assembles exact external components without erasing their repository or license boundaries.

## Current boundaries

1. **Platform glue** — contracts, Python service, installer, docs, and release evidence in this repository. Original Platform glue is Apache-2.0; separate components keep their own terms.
2. **PhiCad / KiCad** — one GPL-3.0 native application family serving Studio and Verify roles. Preserve the exact selected source, KiCad attribution, file-specific notices, modification history, and corresponding-source obligations.
3. **tscircuit packages** — exact permissively licensed packages used by Circuit Engine. Preserve each package notice.
4. **Circuit JSON** — ISC interchange package/artifact conventions; preserve its identity and notice.
5. **Phi** — external sole AI harness; not copied into this archive.
6. **Circuit Preview** — planned thin MIT web surface; review separately if/when source is added.

## Archive behavior

The Platform review archive excludes external source trees, `.git`, credentials, `.env`, caches, generated sites, symlinked output, and developer transcripts. Its inventory names external components and exact pins rather than pretending they are vendored.

## Source and binary release

A PhiCad binary release must identify the exact source commit and provide whatever source/notice delivery the selected GPL/KiCad scope requires. Product branding does not replace upstream identity.

A combined installer must not be called a public release until Platform licensing, component review, source/notice delivery, signing/notarization, and clean-machine acceptance are complete.

## Hosted surfaces

The planned Circuit Preview must remain a thin review surface with no hidden native authority or model credentials. Review its source, dependencies, data handling, and license before deployment.

## Retired source boundary

OpenPCB and the separately licensed PhiCad-Studio tool are not current distribution inputs. The fork exists but is out of scope for this release. Do not clone it for product work, push to it, or vendor, copy, translate, or port OpenPCB source into PhiCad Platform. Historical evidence is not a current release component.

## Release evidence placeholders

| Evidence | Required value |
|---|---|
| Platform license decision | `Apache-2.0 (root LICENSE and NOTICE)` |
| PhiCad source pin | exact commit shared by Studio + Verify roles |
| GPL/KiCad notice/source delivery | `<PHICAD_SOURCE_AND_NOTICE_RECORD>` |
| tscircuit/Circuit JSON notices | exact package inventory |
| independent reviews | `<REVIEW_URLS>` |
| signed installer/notarization | `<SIGNING_EVIDENCE>` |
