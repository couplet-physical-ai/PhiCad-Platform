# Complete example board

`examples/demo-v2-i2c-power-conditioner.tsx` is the first electrically complete
end-to-end reference for the developer preview. It is a compact, two-layer,
**evaluation-only** 5 V-to-3.3 V I2C power-conditioner board: a regulated 5 V host
supply and I2C bus enter on J1; a protected 3.3 V rail plus pulled-up I2C bus leave on
J2 for an external sensor or module.

This deliberately chooses a host-supplied 5 V connector rather than USB-C. That keeps
the reference small while making its power role truthful: it does not implement USB-C
CC, USB Power Delivery, battery charging, or a USB data interface. It is not
mains-connected.

## Electrical intent

- **J1** exposes `VIN`, `GND`, `SDA`, and `SCL` from the host.
- **F1** is a 0.5 A resettable fuse and **D1** is a 5 V TVS clamp from the protected
  input rail to ground. They provide input fault/transient protection for the stated
  5 V use case; they are not reverse-polarity protection.
- **U1** is a 3.3 V MCP1700 LDO. Its specified 1 uF input (**C1**) and output
  (**C2**) capacitors are fitted at the regulator.
- **R1/R2** are 4.7 kOhm pull-ups from the locally generated 3.3 V rail to `SDA` and
  `SCL`, respectively. J2 carries `V3V`, `GND`, `SDA`, and `SCL` to the external
  sensor/module.
- **TP1** and **TP2** are V3V and GND test points. Both copper layers have a grounded
  thermal-relief pour. Two 2.7 mm mechanical mounting holes are included.
- The silkscreen is explicit: `5V IN / V3V I2C OUT / EVALUATION ONLY`.

`V3V` is the net identifier because this engine version does not permit a net name
starting with a number; it denotes the 3.3 V rail in the electrical description and
silkscreen.

## BOM and sourcing identities

All fitted items have a real manufacturer part number (MPN). The pinned engine's
supplier-footprint resolver accepts the `supplierPartNumbers` entries for J1/J2. It
does not resolve exact EasyEDA supplier footprints for the remaining manufacturer/
DigiKey identities, so their supplier IDs are recorded here rather than passed to the
resolver and creating a false footprint-resolution warning. That is a toolchain
limitation, not a substitution: use the listed MPN and supplier number together when
sourcing.

| Ref(s) | Function/value | MPN | Supplier number (DigiKey) |
| --- | --- | --- | --- |
| J1, J2 | 1x04, 2.54 mm host/output headers | Samtec `TSW-104-07-G-S` | `SAM8792-ND` |
| F1 | 0.5 A, 6 V resettable fuse | Bourns `MF-MSMF050-2` | `MF-MSMF050-2CT-ND` |
| D1 | 5 V TVS diode, SOD-323 | onsemi `ESD5Z5.0T1G` | `ESD5Z5.0T1GOSCT-ND` |
| U1 | 3.3 V LDO, SOT-23-3 | Microchip `MCP1700T-3302E/TT` | `MCP1700T-3302E/TTCT-ND` |
| C1, C2 | 1 uF, 10 V, 0603 ceramic | Murata `GRM188R61A105KA61D` | `490-5523-1-ND` |
| R1, R2 | 4.7 kOhm, 0603 | Yageo `RC0603FR-074K7L` | `311-4.70KHRCT-ND` |
| TP1, TP2 | SMD test point | Keystone `5016` | `36-5016-ND` |

## Verified real-tool result

The following was run on **2026-09-15**, not simulated, using:

```bash
ENGINE='/opt/homebrew/bin/bun /path/to/installed/tool'
KICAD='/path/to/installed/tool'

PHICAD_KICAD_CLI="$KICAD" $ENGINE check \
  examples/demo-v2-i2c-power-conditioner.tsx --json
PHICAD_KICAD_CLI="$KICAD" $ENGINE build \
  examples/demo-v2-i2c-power-conditioner.tsx --json
$ENGINE export examples/demo-v2-i2c-power-conditioner.tsx \
  -f kicad_pcb -o /tmp/phicad-v2-evidence/board.kicad_pcb
$KICAD pcb drc --format json --severity-all --refill-zones \
  -o /tmp/phicad-v2-evidence/drc.json /tmp/phicad-v2-evidence/board.kicad_pcb
```

| Gate | Result |
| --- | --- |
| Circuit Engine (`@phicad/core 0.1.0`, `tscircuit 0.0.2561`, `circuit-json 0.0.491`) | **0 errors, 0 warnings** |
| Pinned KiCad CLI `10.99.0` DRC | **0 errors**, 23 warnings retained below; 0 unconnected items |
| Board geometry | 45 mm x 25 mm, two copper layers |
| Circuit counts | 6 nets, 17 pads, 19 traces, 6 vias, 11 fitted components |
| Recorded board SHA-256 | `067d1adff5303d864d7b78448a6f8969e71be591f6aa1273d86bbe71c02de020` |

The whole-file board hash is evidence for that recorded export. Re-exporting currently
changes only generated UUIDs for the two mounting-hole footprints, so its SHA-256 is
not stable even when the source and circuit/DRC counts are unchanged. The source SHA
for the observed run is `06fda53f5aaa394341c6282c1f37d0df199f06b7f6bfb81e443f082442684597`.
The committed fixtures preserve these exact observations and the e2e test checks the
stable source, diagnostic, and circuit-count contract whenever both real tools exist.

## Retained KiCad warnings

The run does **not** suppress warnings. All 23 are produced by the generated
engine/export presentation rather than an electrical or copper-rule violation:

| Exact code | Count | Why it remains |
| --- | ---: | --- |
| `drc.lib_footprint_issues` | 13 | The pinned KiCad environment does not register the generated `tscircuit` footprint library, including generated mounting-hole footprints. Register/embed that library before interactive library editing. |
| `drc.text_height` | 9 | Generated reference text is 0.4 mm, 0.5 mm, or 0.7 mm but this KiCad profile requires 0.8 mm. The engine/export path must move or resize those reference fields. |
| `drc.silk_overlap` | 1 | The generated U1 reference field overlaps a generated C1 F.Silkscreen segment. The engine/export path must place the reference field differently. |

These warnings are deliberately documented rather than waived. The reference's
clean-sheet claim is limited to **zero DRC errors** and **zero Circuit Engine warnings**;
it does not claim a production-ready silkscreen/library presentation.

## What this does not establish

A passing DRC is not a fabrication approval, electrical qualification, safety review,
or manufacturing release. Before any build, review the actual footprint land patterns,
stackup, current/thermal limits, TVS and fuse response, I2C pull-up loading and bus
capacitance, enclosure clearances, assembly/PnP/stencil data, supply polarity, CAM,
and first article. Keep the evaluation-only marking until those independent gates pass.

The V1 developer-preview contract also remains in force: a TSX/Circuit Engine result
is verification evidence and does not create, apply, or synchronize a native PhiCad
revision.
