"""
CCD (Chemical Component Dictionary) loading and non-standard residue parent resolution.
"""

import pickle
from pathlib import Path
from typing import Optional, Tuple

from .constants import (
    STANDARD_AA_CODES,
    STANDARD_AA_THREE_LETTER,
    STANDARD_RES_ONE_LETTER,
    STANDARD_RES_THREE_LETTER,
    get_boltz_cache,
)


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


def is_ccd_available(ccd: Optional[dict], ccd_code: str,
                     mols_dir: Optional[Path] = None) -> bool:
    """Return True iff boltz can load this CCD code at inference time.

    boltz runtime loads individual ``mols/{CCD}.pkl`` files (not ccd.pkl), so the
    authoritative check is whether that file exists AND the molecule has at least
    one 3D conformer.  Falls back to the ccd.pkl dict when mols_dir is unavailable.
    """
    if not ccd_code:
        return False
    code = ccd_code.upper()

    # Primary: check the mols/ directory that boltz actually uses at runtime
    _mols_dir = mols_dir
    if _mols_dir is None:
        _mols_dir = get_boltz_cache() / "mols"
    mol_pkl = _mols_dir / f"{code}.pkl"
    if mol_pkl.exists():
        try:
            with mol_pkl.open("rb") as f:
                mol = pickle.load(f)  # noqa: S301
            return mol.GetNumConformers() > 0 and mol.GetNumAtoms() > 0
        except Exception:
            return False
    # mol file absent → not available
    if _mols_dir.exists():
        return False

    # Fallback: validate via the ccd.pkl dict (used when mols/ dir is missing)
    if not ccd:
        return False
    mol = ccd.get(code)
    if mol is None:
        return False
    try:
        return mol.GetNumConformers() > 0
    except Exception:
        return False


def get_non_standard_parent_from_ccd(ccd: Optional[dict], ccd_code: str) -> Optional[Tuple[str, str]]:
    """Get parent residue for a non-standard comp_id from CCD (ccd.pkl dict).

    Returns (parent_three_letter, parent_one_letter) or None.  Accepts both
    protein and nucleic-acid parents — previously this only recognised the
    20 standard amino acids and silently dropped DNA/RNA parents (e.g. BRU's
    CCD parent ``DU``).
    """
    if ccd_code in STANDARD_RES_THREE_LETTER:
        return None

    mol = load_ccd_molecule(ccd or {}, ccd_code)
    if mol is None:
        return None

    try:
        if mol.HasProp("_chem_comp.mon_nstd_parent_comp_id"):
            parent = mol.GetProp("_chem_comp.mon_nstd_parent_comp_id")
            if parent and parent in STANDARD_RES_THREE_LETTER:
                return (parent, STANDARD_RES_ONE_LETTER[parent])
    except Exception:
        pass

    return None
