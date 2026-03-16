"""Protenix JSON configuration generation for inpainting.

Generates a JSON file compatible with Protenix's inference input format,
including the inpainting fields (template_cif, metadata, chain_id_mapping).
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional


def _int_to_letters(n: int) -> str:
    """Convert integer to Excel-style column letters (1=A, 26=Z, 27=AA, ...)."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _resolve_path(target: Path, output_dir: Path, use_absolute: bool) -> str:
    """Return a path string — absolute or relative to *output_dir*."""
    if use_absolute:
        return str(target.resolve())
    try:
        return str(target.resolve().relative_to(output_dir.resolve()))
    except (ValueError, RuntimeError):
        return os.path.relpath(str(target.resolve()), str(output_dir.resolve()))


def generate_json(
    chain_ids: List[str],
    all_chains_data: Dict[str, Dict],
    cif_path: Path,
    output_dir: Path,
    inpainting_metadata_path: Optional[Path] = None,
    use_absolute_path: bool = True,
) -> str:
    """Generate Protenix-compatible JSON for inpainting.

    Args:
        chain_ids: Ordered list of chain IDs (patchr label/author IDs).
        all_chains_data: Per-chain data dict from StructureProcessor.
        cif_path: Path to the template CIF file.
        output_dir: Output directory.
        inpainting_metadata_path: Path to inpainting_metadata.json, or None.
        use_absolute_path: If True (default), embed absolute paths.

    Returns:
        JSON string ready to write to file.
    """
    sequences = []
    # Mapping: Protenix sequential label_asym_id → patchr author_chain_id (for CIF lookup)
    protenix_to_author: Dict[str, str] = {}

    for seq_idx, chain_id in enumerate(chain_ids):
        d = all_chains_data.get(chain_id)
        if d is None:
            continue

        protenix_chain_id = _int_to_letters(seq_idx + 1)
        author_chain_id = d.get("author_chain_id", chain_id)
        protenix_to_author[protenix_chain_id] = author_chain_id

        entity_type = d.get("entity_type", "protein")

        if entity_type == "protein":
            chain_entry: Dict = {
                "proteinChain": {
                    "sequence": d.get("sequence", ""),
                    "count": 1,
                }
            }
            modifications = d.get("modifications", [])
            if modifications:
                chain_entry["proteinChain"]["modifications"] = [
                    {
                        "ptmPosition": m["position"],
                        "ptmType": f"CCD_{m['ccd']}",
                    }
                    for m in modifications
                ]
        elif entity_type == "dna":
            chain_entry = {
                "dnaSequence": {
                    "sequence": d.get("sequence", ""),
                    "count": 1,
                }
            }
        elif entity_type == "rna":
            chain_entry = {
                "rnaSequence": {
                    "sequence": d.get("sequence", ""),
                    "count": 1,
                }
            }
        elif entity_type == "ligand":
            ccd_code = d.get("ccd", "UNK")
            smiles = d.get("smiles")
            if smiles:
                ligand_str = smiles
            else:
                ligand_str = f"CCD_{ccd_code}"
            chain_entry = {
                "ligand": {
                    "ligand": ligand_str,
                    "count": 1,
                }
            }
        else:
            continue

        sequences.append(chain_entry)

    cif_path_str = _resolve_path(cif_path, output_dir, use_absolute_path)

    name = cif_path.stem
    json_data: Dict = {
        "name": name,
        "sequences": sequences,
    }

    if inpainting_metadata_path is not None:
        meta_str = _resolve_path(inpainting_metadata_path, output_dir, use_absolute_path)
        json_data["inpainting"] = {
            "template_cif": cif_path_str,
            "metadata": meta_str,
            # chain_id_mapping: Protenix label_asym_id → author chain ID in CIF/metadata
            "chain_id_mapping": protenix_to_author,
        }

    return json.dumps([json_data], indent=2)
