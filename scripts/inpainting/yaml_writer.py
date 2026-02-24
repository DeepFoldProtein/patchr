"""
YAML configuration generation for inpainting (delegates to benchmark.generate_yaml).
"""

import os
import sys
from pathlib import Path
from typing import Dict, List

# Ensure scripts/ is on path so we can import benchmark.generate_yaml
_scripts_dir = Path(__file__).resolve().parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
from benchmark.generate_yaml import generate_yaml_content


def generate_yaml(
    chain_ids: List[str],
    all_chains_data: Dict[str, Dict],
    cif_path: Path,
    output_dir: Path,
) -> str:
    """Generate YAML configuration using benchmark generate_yaml_content."""
    chains = []
    auth_ids = []  # author_asym_id (what goes into chain_id in YAML)

    for chain_id in chain_ids:
        d = all_chains_data[chain_id]
        auth_id = d.get("author_chain_id", chain_id)
        auth_ids.append(auth_id)
        # Use auth_id as sequence id so everything is consistent around auth chain IDs.
        entry = {
            "id": auth_id,
            "sequence": d.get("sequence", ""),
            "entity_type": d.get("entity_type", "protein"),
            "modifications": [
                {"position": m["position"], "ccd": m["ccd"]}
                for m in d.get("modifications", [])
            ],
        }
        if d.get("entity_type") == "ligand":
            entry["ccd"] = d.get("ccd", "UNK")
            if d.get("smiles"):
                entry["smiles"] = d["smiles"]
        chains.append(entry)

    try:
        cif_path_str = str(cif_path.resolve().relative_to(Path.cwd().resolve()))
    except (ValueError, RuntimeError):
        cif_path_str = os.path.relpath(
            str(cif_path.resolve()), str(Path.cwd().resolve())
        )

    yaml_content = generate_yaml_content(
        chains=chains, cif_path=cif_path_str, use_absolute_path=False
    )

    # Always replace chain_id with auth IDs (no query_id field).
    # For 6+ single-character IDs, use compact string notation (e.g. "ABCDEFGH").
    lines = yaml_content.split("\n")
    new_lines = []
    for line in lines:
        if line.strip().startswith("chain_id:"):
            if len(auth_ids) == 1:
                new_lines.append(f"    chain_id: {auth_ids[0]}")
            elif len(auth_ids) >= 6 and all(len(aid) == 1 for aid in auth_ids) and len(set(auth_ids)) == len(auth_ids):
                # Compact notation only when all IDs are unique single chars
                new_lines.append(f"    chain_id: {''.join(auth_ids)}")
            else:
                new_lines.append(f"    chain_id: {auth_ids}")
        else:
            new_lines.append(line)
    yaml_content = "\n".join(new_lines)

    return yaml_content
