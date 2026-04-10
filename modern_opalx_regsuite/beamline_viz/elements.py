"""Element type definitions and visual style registry for beamline visualization.

To add support for a new OPALX element type, add one entry to ELEMENT_STYLES
with the OPAL type name (lowercase) as the key.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BeamlineElement:
    """A single beamline element with its type and s-position extent."""

    name: str       # Element label as it appears in the OPAL input file (e.g. "GUN", "BF")
    elem_type: str  # OPAL element type (e.g. "RFCavity", "Solenoid", "Drift")
    start: float    # s-position of the element entrance (m)
    end: float      # s-position of the element exit (m)

    @property
    def length(self) -> float:
        return self.end - self.start


# Map from OPAL element type name (lowercase) to rendering properties.
# color: hex fill colour for the rectangle
# label: human-readable type label shown in the legend
ELEMENT_STYLES: dict[str, dict[str, str]] = {
    "rfcavity":             {"color": "#C0392B", "label": "RF Cavity"},
    "solenoid":             {"color": "#2980B9", "label": "Solenoid"},
    "drift":                {"color": "#D5D8DC", "label": "Drift"},
    "quadrupole":           {"color": "#27AE60", "label": "Quadrupole"},
    "dipole":               {"color": "#E67E22", "label": "Dipole"},
    "sbend":                {"color": "#E67E22", "label": "Dipole (SBend)"},
    "rbend":                {"color": "#E67E22", "label": "Dipole (RBend)"},
    "monitor":              {"color": "#8E44AD", "label": "Monitor"},
    "collimator":           {"color": "#16A085", "label": "Collimator"},
    "multipole":            {"color": "#F39C12", "label": "Multipole"},
    "trimcoil":             {"color": "#1ABC9C", "label": "Trim Coil"},
    "septum":               {"color": "#D35400", "label": "Septum"},
    "kicker":               {"color": "#884EA0", "label": "Kicker"},
    "hkicker":              {"color": "#884EA0", "label": "H-Kicker"},
    "vkicker":              {"color": "#884EA0", "label": "V-Kicker"},
    "cyclotron":            {"color": "#2471A3", "label": "Cyclotron"},
    "constantefieldcavity": {"color": "#fff154", "label": "E-Field"},
    "_default":             {"color": "#7F8C8D", "label": "Element"},
}
