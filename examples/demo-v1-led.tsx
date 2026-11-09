// PhiCad V1 small-board demo: a resistor-driven status LED.
//
// This intentionally stays small so the complete design loop is easy to record and
// inspect. It is a workflow fixture, not a fabrication release. The demo harness
// runs the pinned Circuit Engine first and keeps PhiCad Verify's independent result
// separate from the engine result.
//
// The fixture is deliberately a one-net series fragment rather than a powered LED
// circuit. Its two free pins produce explicit Circuit Engine warnings while the
// manifest-matched KiCad DRC has no errors. That makes the demo useful without
// pretending the fragment is electrically complete or fabrication-ready.
//
// V1 does not materialize this Circuit JSON into a native PhiCad revision.
export default () => (
  <board width="18mm" height="12mm" defaultTraceWidth="0.25mm" minTraceWidth="0.2mm">
    <resistor name="R1" resistance="1k" footprint="0402" pcbX={-4} />
    <led name="D1" color="red" footprint="0603" pcbX={4} />
    <trace name="series" from=".R1 > .pin2" to=".D1 > .anode" thickness="0.25mm" />
  </board>
)
