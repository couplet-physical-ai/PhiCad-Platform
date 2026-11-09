// PhiCad V2 reference: a 5 V to 3.3 V I2C power-conditioner board.
//
// J1 accepts a regulated 5 V host supply and I2C signals. F1 limits sustained input
// fault current; D1 clamps positive input transients to GND; U1 produces V3V. C1 and C2
// are the MCP1700 input/output capacitors. R1/R2 provide the I2C pull-ups, while J2 makes
// the conditioned supply and bus available to an external sensor/module. TP1/TP2 probe V3V
// and GND. It is deliberately evaluation-only, not a fabrication or safety release.
//
// The routing constraints deliberately match the exported KiCad rules: 0.25 mm clearance
// around pads/tracks and 0.5/0.3 mm via pad/drill geometry. They make the toolchain's
// routed output independently checkable without weakening KiCad's 0.2 mm DRC clearance.
export default () => (
  <board width="45mm" height="25mm" layers={2} defaultTraceWidth="0.25mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.5mm" minViaEdgeToPadEdgeClearance="0.25mm" minTraceToPadEdgeClearance="0.25mm" minPadEdgeToPadEdgeClearance="0.25mm" minViaHoleEdgeToViaHoleEdgeClearance="0.25mm" title="Evaluation-only 5V-to-V3V I2C conditioner">
    <schematicsheet name="Power and I2C" />

    {/* Named nets make the electrical intent, especially the protected input rail, explicit. */}
    <net name="VIN" />
    <net name="GND" isGroundNet />
    <net name="V3V" />
    <net name="SDA" />
    <net name="SCL" />
    {/* Host connector: 5 V, return, SDA and SCL. */}
    <pinheader name="J1" pinCount={4} pitch="2.54mm" pcbX={-17} pcbY={0}
      pinLabels={{pin1:"VIN",pin2:"GND",pin3:"SDA",pin4:"SCL"}}
      connections={{VIN:"net.VIN",GND:"net.GND",SDA:"net.SDA",SCL:"net.SCL"}}
      manufacturerPartNumber="TSW-104-07-G-S" supplierPartNumbers={{digikey:["SAM8792-ND"]}} />
    {/* Input protection and the 3.3 V LDO, with its required 1 uF input/output capacitors. */}
    <fuse name="F1" currentRating="0.5A" voltageRating="6V" footprint="1206" pcbX={-11} pcbY={5}
      connections={{pin1:"net.VIN",pin2:"net.VIN_PROTECTED"}}
      manufacturerPartNumber="MF-MSMF050-2" />
    <net name="VIN_PROTECTED" />
    <diode name="D1" variant="tvs" footprint="SOD323" pcbX={-6} pcbY={5}
      connections={{anode:"net.VIN_PROTECTED",cathode:"net.GND"}}
      manufacturerPartNumber="ESD5Z5.0T1G" />
    <chip name="U1" footprint="sot23_3" pcbX={-1} pcbY={5}
      connections={{VIN:"net.VIN_PROTECTED",GND:"net.GND",VOUT:"net.V3V"}}
      manufacturerPartNumber="MCP1700T-3302E/TT"
      pinLabels={{pin1:"VIN",pin2:"GND",pin3:"VOUT"}}
      pinAttributes={{VIN:{requiresPower:true,mustBeConnected:true},GND:{requiresGround:true,mustBeConnected:true},VOUT:{providesPower:true,mustBeConnected:true}}} />
    <capacitor name="C1" capacitance="1uF" maxVoltageRating="10V" footprint="0603" pcbX={-2} pcbY={8}
      connections={{pos:"net.VIN_PROTECTED",neg:"net.GND"}}
      manufacturerPartNumber="GRM188R61A105KA61D" />
    <capacitor name="C2" capacitance="1uF" maxVoltageRating="10V" footprint="0603" pcbX={3} pcbY={8}
      connections={{pos:"net.V3V",neg:"net.GND"}}
      manufacturerPartNumber="GRM188R61A105KA61D" />
    {/* I2C is open drain: pull both lines up to the locally regulated V3V rail. */}
    <resistor name="R1" resistance="4.7k" footprint="0603" pcbX={5} pcbY={4}
      connections={{pin1:"net.V3V",pin2:"net.SDA"}}
      manufacturerPartNumber="RC0603FR-074K7L" />
    <resistor name="R2" resistance="4.7k" footprint="0603" pcbX={9} pcbY={4}
      connections={{pin1:"net.V3V",pin2:"net.SCL"}}
      manufacturerPartNumber="RC0603FR-074K7L" />
    {/* Conditioned output connector and accessible rail test points. */}
    <pinheader name="J2" pinCount={4} pitch="2.54mm" pcbX={16} pcbY={0}
      pinLabels={{pin1:"V3V",pin2:"GND",pin3:"SDA",pin4:"SCL"}}
      connections={{"V3V":"net.V3V",GND:"net.GND",SDA:"net.SDA",SCL:"net.SCL"}}
      manufacturerPartNumber="TSW-104-07-G-S" supplierPartNumbers={{digikey:["SAM8792-ND"]}} />
    <testpoint name="TP1" pcbX={2} pcbY={-5} connections={{pin1:"net.V3V"}}
      manufacturerPartNumber="5016"
      footprint={<footprint><smtpad shape="circle" radius="0.75mm" portHints={["pin1"]} /><courtyardrect width="2mm" height="2mm" /></footprint>} />
    <testpoint name="TP2" pcbX={7} pcbY={-5} connections={{pin1:"net.GND"}}
      manufacturerPartNumber="5016"
      footprint={<footprint><smtpad shape="circle" radius="0.75mm" portHints={["pin1"]} /><courtyardrect width="2mm" height="2mm" /></footprint>} />
    {/* A ground pour on both copper layers and two mechanical mounting holes. */}
    <copperpour name="F.GND" layer="top" connectsTo="net.GND" clearance="0.25mm" boardEdgeMargin="0.3mm" useThermalReliefs />
    <copperpour name="B.GND" layer="bottom" connectsTo="net.GND" clearance="0.25mm" boardEdgeMargin="0.3mm" useThermalReliefs />
    <hole name="MH1" pcbX={-19} pcbY={-9} diameter="2.7mm" />
    <hole name="MH2" pcbX={19} pcbY={-9} diameter="2.7mm" />
    <pcbnotetext text="5V IN / V3V I2C OUT / EVALUATION ONLY" pcbX={0} pcbY={-10} fontSize="0.7mm" />
  </board>
)
