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
from benchmark.generate_yaml import generate_yaml_content, _yaml_str


def _resolve_path(target: Path, output_dir: Path, use_absolute: bool) -> str:
    """Return a path string — absolute or relative to *output_dir*."""
    if use_absolute:
        return str(target.resolve())
    try:
        return str(target.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        return os.path.relpath(str(target.resolve()), str(output_dir.resolve()))


def generate_yaml(
    chain_ids: List[str],
    all_chains_data: Dict[str, Dict],
    cif_path: Path,
    output_dir: Path,
    inpainting_metadata_path: Path = None,
    use_absolute_path: bool = True,
) -> str:
    """Generate YAML configuration using benchmark generate_yaml_content.

    Args:
        use_absolute_path: If True (default), embed absolute paths for CIF and
            metadata so the YAML works regardless of working directory.  If
            False, paths are relative to *output_dir*.
    """
    chains = []
    label_ids = []  # label_asym_id (what goes into chain_id in YAML)

    for chain_id in chain_ids:
        d = all_chains_data[chain_id]
        # Use label_asym_id everywhere — it is guaranteed unique in mmCIF,
        # unlike auth_asym_id which can collide (e.g. a polymer chain and its
        # glycan fragments sharing author chain "A" in 8WLO).
        label_ids.append(chain_id)
        entry = {
            "id": chain_id,
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

    cif_path_str = _resolve_path(cif_path, output_dir, use_absolute_path)

    yaml_content = generate_yaml_content(
        chains=chains, cif_path=cif_path_str, use_absolute_path=False
    )

    # Always replace chain_id with label IDs (no query_id field).
    # For 6+ single-character IDs, use compact string notation (e.g. "ABCDEFGH").
    lines = yaml_content.split("\n")
    new_lines = []
    for line in lines:
        if line.strip().startswith("chain_id:"):
            # Always use explicit list notation to avoid ambiguity (e.g. "AA" vs ["A","A"])
            quoted = [_yaml_str(cid) for cid in label_ids]
            new_lines.append(f"    chain_id: [{', '.join(quoted)}]")
            # Add inpainting_metadata path right after chain_id (relative to output_dir)
            if inpainting_metadata_path is not None:
                meta_str = _resolve_path(inpainting_metadata_path, output_dir, use_absolute_path)
                new_lines.append(f"    inpainting_metadata: {meta_str}")
        else:
            new_lines.append(line)
    yaml_content = "\n".join(new_lines)

    return yaml_content
