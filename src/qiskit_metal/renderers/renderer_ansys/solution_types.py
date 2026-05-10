# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2017, 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
"""HFSS / Q3D solution-type name handling.

HFSS 2024.1 introduced new solution-type identifiers alongside the legacy
ones. ``pinfo.design.solution_type`` (and the underlying COM
``GetSolutionType()``) returns whatever the running HFSS version reports,
so call-site code that compares against a single string silently breaks
when a user upgrades. This module centralises the name aliases and the
predicates so a future rename is a one-file change.

Aliases tracked here mirror the set merged into pyEPR (PRs #172 and
#176) for HFSS 2024.1 support; if HFSS introduces another alias, add it
to the relevant ``frozenset`` below — every call site picks it up
automatically.

This module is pure Python: no Ansys, no Windows, no pyEPR. It's safe to
import on any platform.
"""

from typing import Optional

#: HFSS Eigenmode solver. The legacy name is unchanged in HFSS 2024.1+.
EIGENMODE_NAMES = frozenset({
    'Eigenmode',
})

#: HFSS Driven Modal solver. HFSS 2024.1+ exposes the same solver under
#: two additional identifiers depending on whether the design is "Hybrid".
DRIVENMODAL_NAMES = frozenset({
    'DrivenModal',  # HFSS <= 2023
    'HFSS Modal Network',  # HFSS 2024.1+
    'HFSS Hybrid Modal Network',  # HFSS 2024.1+
})

#: HFSS Driven Terminal solver. Renamed in HFSS 2024.1+ alongside Driven Modal.
#: qiskit-metal does not currently ship a renderer for this solver, but the
#: helper is provided so future renderer code can use the same pattern.
DRIVENTERMINAL_NAMES = frozenset({
    'DrivenTerminal',  # HFSS <= 2023
    'HFSS Terminal Network',  # HFSS 2024.1+
    'HFSS Hybrid Terminal Network',  # HFSS 2024.1+
})

#: Q3D Extractor capacitive/inductive solver. Unaffected by the HFSS
#: 2024.1 rename, but tracked here for symmetry.
Q3D_NAMES = frozenset({
    'Q3D',
})


def is_eigenmode(solution_type: Optional[str]) -> bool:
    """True if ``solution_type`` names the HFSS Eigenmode solver."""
    return solution_type in EIGENMODE_NAMES


def is_drivenmodal(solution_type: Optional[str]) -> bool:
    """True if ``solution_type`` names any alias of the HFSS Driven Modal
    solver, including the post-2024.1 ``HFSS Modal Network`` and
    ``HFSS Hybrid Modal Network`` identifiers."""
    return solution_type in DRIVENMODAL_NAMES


def is_driventerminal(solution_type: Optional[str]) -> bool:
    """True if ``solution_type`` names any alias of the HFSS Driven
    Terminal solver."""
    return solution_type in DRIVENTERMINAL_NAMES


def is_q3d(solution_type: Optional[str]) -> bool:
    """True if ``solution_type`` names the Q3D Extractor solver."""
    return solution_type in Q3D_NAMES


def canonical_kind(solution_type: Optional[str]) -> Optional[str]:
    """Map a raw HFSS / Q3D ``solution_type`` string to its canonical
    metal-internal kind.

    Returns one of ``'eigenmode'``, ``'drivenmodal'``,
    ``'driventerminal'``, ``'q3d'``, or ``None`` if the string is not a
    recognised solver identifier.

    The metal-internal kinds are stable across HFSS versions; downstream
    metal code (renderer dispatch, design-creation guards) should compare
    against these rather than the raw HFSS strings.
    """
    if is_eigenmode(solution_type):
        return 'eigenmode'
    if is_drivenmodal(solution_type):
        return 'drivenmodal'
    if is_driventerminal(solution_type):
        return 'driventerminal'
    if is_q3d(solution_type):
        return 'q3d'
    return None
