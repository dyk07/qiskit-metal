# -*- coding: utf-8 -*-
"""Intermediate-representation dataclasses for DSL v3.

These data containers are standalone — they do not import from other
modules in this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "PrimitiveIR",
    "PinIR",
    "ComponentIR",
    "DesignIR",
]


@dataclass
class PrimitiveIR:
    """A resolved geometry primitive in Metal user units."""

    component: str
    name: str
    kind: str
    shape: str
    geometry: Any
    subtract: bool = False
    helper: bool = False
    layer: int = 1
    chip: str = "main"
    width: Optional[float] = None
    fillet: Optional[float] = None
    options: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class PinIR:
    """A resolved Metal pin."""

    component: str
    name: str
    points: list[list[float]]
    width: float
    gap: Optional[float] = None
    chip: str = "main"
    input_as_norm: bool = False
    normal_points: Optional[list[list[float]]] = None
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.normal_points is None:
            self.normal_points = self.points


@dataclass
class ComponentIR:
    """A component container made only from primitives and pins."""

    name: str
    primitives: list[PrimitiveIR] = field(default_factory=list)
    pins: list[PinIR] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    type: Optional[str] = None
    options: dict[str, Any] = field(default_factory=dict)
    template: Optional[str] = None
    inherited: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class DesignIR:
    """Resolved v3 design IR."""

    schema: str
    vars: dict[str, Any]
    hamiltonian: Any
    circuit: Any
    netlist: Any
    design: dict[str, Any]
    components: list[ComponentIR]
    geometry: dict[str, Any]
    derived: dict[str, Any]
    simulation: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Return a metadata-safe snapshot of the IR."""
        return {
            "schema": self.schema,
            "vars": self.vars,
            "hamiltonian": self.hamiltonian,
            "circuit": self.circuit,
            "netlist": self.netlist,
            "design": self.design,
            "geometry": self.geometry,
            "derived": self.derived,
            "simulation": self.simulation,
        }
