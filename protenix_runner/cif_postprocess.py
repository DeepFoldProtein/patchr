# Copyright 2024 ByteDance and/or its affiliates.
# Licensed under the Apache License, Version 2.0.
"""
Post-prediction enrichment of Protenix mmCIF output.

Protenix's `save_structure_cif()` writes a minimal mmCIF (`_atom_site`,
`_entity_poly`, `_entity_poly_seq`, `_chem_comp`, possibly `_struct_conn`).
The `_entity_poly` block carries only ``(entity_id, strand_id, type)`` —
it omits ``pdbx_seq_one_letter_code``, ``pdbx_seq_one_letter_code_can``,
``nstd_monomer``.  ``_pdbx_struct_mod_residue`` is also missing entirely.

This module enriches the prediction CIF with metadata from the template
CIF (which carries the full entity_poly + mod_residue + struct_conn /
chem_comp / cell / symmetry).  Mirrors the merge step we apply to the
Boltz-2 backend, ensuring output parity between the two backends.
"""
from __future__ import annotations

import logging
import re
from io import StringIO
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_ENTITY_POLY_LOOP_RE = re.compile(
    r"\nloop_\s*\n(?:_entity_poly\.[^\n]*\n)+"        # header block
    r"(?:[^#_][^\n]*\n)+"                              # data rows
    r"#",
    re.DOTALL,
)

# A multi-line entity_poly block can include semicolon-delimited text
# blocks (e.g. for long sequences).  This more permissive regex captures
# the body as everything up to the first lone "#".
_ENTITY_POLY_FULL_RE = re.compile(
    r"\nloop_\s*\n((?:_entity_poly\.[^\n]*\n)+(?:.*?))\n#",
    re.DOTALL,
)


def _extract_entity_poly_loop(cif_text: str) -> Optional[str]:
    """Return the verbatim ``loop_ ... _entity_poly.* ... #`` block, or None."""
    m = _ENTITY_POLY_FULL_RE.search(cif_text)
    if not m:
        return None
    body = m.group(0)
    # Trim the leading "\n" and ensure trailing "#"
    return body.strip("\n")


def _strip_entity_poly_loop(cif_text: str) -> str:
    """Remove the existing ``loop_ ... _entity_poly.* ... #`` block."""
    return _ENTITY_POLY_FULL_RE.sub("\n#", cif_text, count=1)


def _replace_entity_poly_with_template(pred_text: str, template_text: str) -> str:
    """Replace prediction's `_entity_poly` loop with template's richer one."""
    template_block = _extract_entity_poly_loop(template_text)
    if not template_block:
        return pred_text
    if _extract_entity_poly_loop(pred_text) is None:
        # Nothing to replace; just append.
        return pred_text.rstrip() + "\n" + template_block + "\n"
    stripped = _strip_entity_poly_loop(pred_text)
    return stripped.rstrip() + "\n" + template_block + "\n"


def enrich_with_template_metadata(
    pred_cif_path: str | Path,
    template_cif_path: str | Path,
    entry_id: Optional[str] = None,
) -> bool:
    """Merge template metadata into a Protenix prediction mmCIF in place.

    Steps:
      1. Boltz-style merge of struct_conn, chem_comp, cell, symmetry,
         atom_sites, pdbx_struct_mod_residue.
      2. Replace minimal _entity_poly loop with template's full version
         (so pdbx_seq_one_letter_code and _can are present).

    Returns True on success, False if either file is missing.
    """
    pred_cif_path = Path(pred_cif_path)
    template_cif_path = Path(template_cif_path)
    if not pred_cif_path.is_file():
        logger.warning(f"enrich: prediction CIF not found: {pred_cif_path}")
        return False
    if not template_cif_path.is_file():
        logger.warning(f"enrich: template CIF not found: {template_cif_path}")
        return False

    # Late import to keep this module importable even without boltz on path
    # at config time.
    from boltz.data.write.merge_cif_blocks import merge_template_blocks_into_cif

    cif_text = pred_cif_path.read_text()
    template_text = template_cif_path.read_text()

    # Step 1 — boltz merge (adds mod_residue + struct_conn + chem_comp + cell
    # + symmetry + atom_sites).
    cif_text = merge_template_blocks_into_cif(
        cif_text, str(template_cif_path), entry_id=entry_id
    )

    # Step 2 — replace _entity_poly with template's richer version.
    cif_text = _replace_entity_poly_with_template(cif_text, template_text)

    pred_cif_path.write_text(cif_text)
    return True
