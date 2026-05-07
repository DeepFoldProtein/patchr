"""
Constants and path helpers for inpainting template generation.
"""

import os
from pathlib import Path


def get_boltz_cache() -> Path:
    """Default Boltz cache (same as main.py: BOLTZ_CACHE or ~/.boltz)."""
    return Path(os.environ.get("BOLTZ_CACHE", str(Path.home() / ".boltz")))


def get_default_ccd_path() -> Path:
    """Default CCD dictionary path (ccd.pkl, same as mmcif.py / main.py)."""
    return get_boltz_cache() / "ccd.pkl"


# Legacy: default molecules directory (individual .pkl per component)
DEFAULT_MOL_DIR = Path.home() / ".boltz" / "mols"

# Standard amino acid codes
STANDARD_AA_CODES = {
    'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E',
    'PHE': 'F', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
    'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
    'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S',
    'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
}
STANDARD_AA_THREE_LETTER = set(STANDARD_AA_CODES.keys())

# Standard nucleotide residue names (DNA and RNA) — not modifications
STANDARD_NUCLEOTIDE_CODES = {
    # DNA
    'DA', 'DC', 'DG', 'DT', 'DI',
    # RNA
    'A', 'C', 'G', 'U', 'I',
}

# 1-letter codes for DNA / RNA monomers.  Used when a non-standard nucleotide
# resolves to a standard parent and we need to fill `pdbx_seq_one_letter_code_can`
# or the YAML sequence with the parent's 1-letter form.
STANDARD_NUCLEOTIDE_ONE_LETTER = {
    # DNA
    'DA': 'A', 'DC': 'C', 'DG': 'G', 'DT': 'T', 'DI': 'I', 'DU': 'U',
    # RNA
    'A': 'A', 'C': 'C', 'G': 'G', 'U': 'U', 'I': 'I',
}

# Combined 3-letter -> 1-letter mapping (protein + DNA + RNA).
STANDARD_RES_ONE_LETTER = {**STANDARD_AA_CODES, **STANDARD_NUCLEOTIDE_ONE_LETTER}

# Combined "standard 3-letter code" set (protein + DNA + RNA). Use this for
# parent-acceptance checks instead of STANDARD_AA_THREE_LETTER, which is
# protein-only and incorrectly rejects DA/DT/DU/etc. as "unknown".
STANDARD_RES_THREE_LETTER = STANDARD_AA_THREE_LETTER | set(STANDARD_NUCLEOTIDE_ONE_LETTER)

# Hardcoded fallback for common non-standard residues → parent standard residue.
# Used when ccd.pkl lacks `_chem_comp.mon_nstd_parent_comp_id` (typical with
# pdbeccdutils-built mol pickles) AND the residue isn't in non_standard_residues
# (e.g. when atoms are missing for that position). Mirrors deepfold3's
# `_NONSTANDARD_TO_STANDARD` so PATCHR-generated templates and deepfold3 training
# agree on parent assignments.
NONSTANDARD_TO_STANDARD: dict[str, str] = {
    # Selenium / sulfur variants
    'MSE': 'MET',  # selenomethionine
    'SEC': 'CYS',  # selenocysteine
    'PYL': 'LYS',  # pyrrolysine
    'FME': 'MET',  # N-formylmethionine
    # Phosphorylation
    'SEP': 'SER',  # phosphoserine
    'TPO': 'THR',  # phosphothreonine
    'PTR': 'TYR',  # phosphotyrosine
    # Methylation
    'MLY': 'LYS',  # N-dimethyl-lysine
    'M3L': 'LYS',  # N-trimethyl-lysine
    'AGM': 'ARG',  # 5-methyl-arginine
    # Cysteine variants
    'CYX': 'CYS', 'CSD': 'CYS', 'CME': 'CYS', 'OCS': 'CYS', 'CSO': 'CYS',
    'CSS': 'CYS', 'SMC': 'CYS',
    # Histidine variants
    'HSD': 'HIS', 'HSE': 'HIS', 'HSP': 'HIS',
    'HIE': 'HIS', 'HID': 'HIS', 'HIP': 'HIS',
    # Hydroxylation / cyclization
    'HYP': 'PRO',  # 4-hydroxyproline
    'PCA': 'GLU',  # pyroglutamate
    '5HP': 'GLU',
    # Misc protein
    'ASX': 'ASP', 'GLX': 'GLU',
    'ABA': 'ALA', 'AIB': 'ALA',
    # Nucleic acid variants
    'DU': 'DT',
    'PSU': 'U', '5MU': 'U', 'OMU': 'U',
    'OMC': 'C',
    '1MA': 'A', '6MA': 'A',
    '7MG': 'G', 'OMG': 'G',
    # DNA modifications — analogues that substitute for one of the standard
    # DNA bases.  Mappings chosen to match RCSB convention (parent CCD code).
    'BRU': 'DU',  # 5-bromo-2'-deoxyuridine  (RCSB pdbx parent = DU; canonical 'U')
    '5BU': 'DU',  # alias of BRU in some PDB entries
    'IDU': 'DU',  # 5-iodo-2'-deoxyuridine
    'CBR': 'DC',  # 5-bromo-2'-deoxycytidine
    '5HU': 'DU',  # 5-hydroxy-2'-deoxyuridine
    'TFT': 'DT',  # alpha-trifluorothymidine
    '5MC': 'DC',  # 5-methyl-2'-deoxycytidine (DNA)
    '5CM': 'DC',
    '6MA': 'DA',
    '8OG': 'DG',  # 8-oxo-2'-deoxyguanosine
    'CFL': 'DC',
    # Additional protein modifications (RCSB CCD-confirmed parents).
    'NLE': 'LEU',  # norleucine                       → L
    'HIC': 'HIS',  # 4-methyl-histidine               → H
    # Additional RNA modifications (RCSB CCD-confirmed parents).
    '4AC': 'C',    # N4-acetylcytidine                → C
    'G7M': 'G',    # 7-methylguanosine                → G
    '2MG': 'G',    # 2N-methylguanosine               → G
    'UR3': 'U',    # 3-methyluridine                  → U
    '4OC': 'C',    # 4N,2'-O-dimethylcytidine         → C
}

# Reference atoms from boltz.data.const (used for missing-atom checks and inpainting region)
ref_atoms = {
    "ALA": ["N", "CA", "C", "O", "CB"],
    "ARG": ["N", "CA", "C", "O", "CB", "CG", "CD", "NE", "CZ", "NH1", "NH2"],
    "ASN": ["N", "CA", "C", "O", "CB", "CG", "OD1", "ND2"],
    "ASP": ["N", "CA", "C", "O", "CB", "CG", "OD1", "OD2"],
    "CYS": ["N", "CA", "C", "O", "CB", "SG"],
    "GLN": ["N", "CA", "C", "O", "CB", "CG", "CD", "OE1", "NE2"],
    "GLU": ["N", "CA", "C", "O", "CB", "CG", "CD", "OE1", "OE2"],
    "GLY": ["N", "CA", "C", "O"],
    "HIS": ["N", "CA", "C", "O", "CB", "CG", "ND1", "CD2", "CE1", "NE2"],
    "ILE": ["N", "CA", "C", "O", "CB", "CG1", "CG2", "CD1"],
    "LEU": ["N", "CA", "C", "O", "CB", "CG", "CD1", "CD2"],
    "LYS": ["N", "CA", "C", "O", "CB", "CG", "CD", "CE", "NZ"],
    "MET": ["N", "CA", "C", "O", "CB", "CG", "SD", "CE"],
    "PHE": ["N", "CA", "C", "O", "CB", "CG", "CD1", "CD2", "CE1", "CE2", "CZ"],
    "PRO": ["N", "CA", "C", "O", "CB", "CG", "CD"],
    "SER": ["N", "CA", "C", "O", "CB", "OG"],
    "THR": ["N", "CA", "C", "O", "CB", "OG1", "CG2"],
    "TRP": ["N", "CA", "C", "O", "CB", "CG", "CD1", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"],
    "TYR": ["N", "CA", "C", "O", "CB", "CG", "CD1", "CD2", "CE1", "CE2", "CZ", "OH"],
    "VAL": ["N", "CA", "C", "O", "CB", "CG1", "CG2"],
    "UNK": ["N", "CA", "C", "O", "CB"]
}
