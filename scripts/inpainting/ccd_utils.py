"""
CCD (Chemical Component Dictionary) loading and non-standard residue parent resolution.
"""

import pickle
from pathlib import Path
from typing import Optional, Tuple

from .constants import STANDARD_AA_CODES, STANDARD_AA_THREE_LETTER


def load_ccd_dict(ccd_path: Path) -> dict:
    """Load the CCD dictionary from ccd.pkl (same as main.py / mmcif.py mols)."""
    if not ccd_path.exists():
        return {}
    try:
        with ccd_path.open("rb") as f:
            return pickle.load(f)  # noqa: S301
    except Exception:
        return {}


def load_ccd_molecule(ccd: dict, ccd_code: str):
    """Get a CCD molecule from the pre-loaded ccd dict (from ccd.pkl)."""
    return ccd.get(ccd_code.upper()) if ccd else None


def get_non_standard_parent_from_ccd(ccd: Optional[dict], ccd_code: str) -> Optional[Tuple[str, str]]:
    """Get parent residue for a non-standard comp_id from CCD (ccd.pkl dict). Returns (parent_three_letter, parent_one_letter) or None."""
    if ccd_code in STANDARD_AA_THREE_LETTER:
        return None

    mol = load_ccd_molecule(ccd or {}, ccd_code)
    if mol is None:
        return None

    try:
        if mol.HasProp("_chem_comp.mon_nstd_parent_comp_id"):
            parent = mol.GetProp("_chem_comp.mon_nstd_parent_comp_id")
            if parent and parent in STANDARD_AA_THREE_LETTER:
                return (parent, STANDARD_AA_CODES[parent])

        atom_names = set()
        for atom in mol.GetAtoms():
            if atom.HasProp("name"):
                atom_names.add(atom.GetProp("name"))

        backbone_atoms = {"N", "CA", "C", "O"}
        if backbone_atoms.issubset(atom_names):
            if "CB" in atom_names or ccd_code in ['GLY']:
                pass
    except Exception:
        pass

    return None
