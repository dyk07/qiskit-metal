# Native Hamiltonian-Circuit-Netlist-Geometry DSL

This branch uses the v3 DSL:

```yaml
schema: qiskit-metal/design-dsl/3

vars: {}
hamiltonian: {}
circuit: {}
netlist:
  connections: [{from: Q1.bus, to: Q2.bus}]
geometry:
  design: {class: DesignPlanar, chip: {size: 6mm x 6mm}}
  components:
    Q1:
      primitives: [...]
      pins: [...]
```

The YAML no longer names qlibrary classes such as `TransmonPocket`,
`RouteMeander`, or `LineTee`.  `build_ir()` resolves the file into an
independent IR first.  `build_design()` then exports that IR to a normal Metal
`QDesign` by writing primitive shapely geometry, pins, and net connections.

## Python API

```python
from qiskit_metal.toolbox_metal.design_dsl import build_ir, build_design

ir = build_ir("examples/dsl/chain_2q_native.metal.yaml")
design = build_design("examples/dsl/chain_2q_native.metal.yaml")
```

`design` is still useful with Metal renderers because the exporter writes:

- primitive rows into `design.qgeometry.tables`
- pins into lightweight native components
- pin connections into `design.net_info`
- the full chain into `design.metadata["dsl_chain"]`

## Primitives

Supported first-pass primitive types:

```yaml
type: poly.rectangle
center: [0mm, 0mm]
size: [420um, 90um]

type: poly.polygon
points: [[0mm, 0mm], [1mm, 0mm], [0mm, 1mm]]

type: path.polyline
points: [[0mm, 0mm], [1mm, 0mm], [1mm, 1mm]]
width: 12um

type: junction.line
points: [[0mm, -45um], [0mm, 45um]]
width: 10um
```

Pins are explicit:

```yaml
pins:
  - name: bus
    points: [[-0.45mm, -6um], [-0.45mm, 6um]]
    width: 12um
    gap: 7um
```

## Data Flow

Downward references use dotted interpolation:

```yaml
circuit:
  Q1: {pad_width: 420um}

geometry:
  components:
    Q1:
      primitives:
        - {name: pad, type: poly.rectangle, size: ["${circuit.Q1.pad_width}", 90um]}
```

Derived upward data is stored at:

```python
ir.derived
design.metadata["dsl_chain"]["derived"]
```

It currently includes primitive bounds, path lengths, pin middle points, and
resolved netlist connections.

## Examples

- `native_2q_minimal.metal.yaml`: smallest native two-qubit sketch.
- `chain_2q_native.metal.yaml`: full Hamiltonian-Circuit-Netlist-Geometry chain.
- `run_chain_demo.py`: builds the chain example and prints qgeometry/netlist data.
