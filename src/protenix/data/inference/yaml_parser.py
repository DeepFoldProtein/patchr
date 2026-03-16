"""Convert Boltz YAML input format to Protenix internal sample dict format.

Boltz YAML schema:
    version: 1
    sequences:
      - protein:
          id: A           # or [A, B] for multiple copies
          sequence: MADQ...
          msa: empty      # optional
          modifications:
            - position: 1
              ccd: TPO
      - ligand:
          id: C
          ccd: SAH        # or smiles: '...'
    constraints:          # optional
      - bond:
          atom1: [A, 1, CA]
          atom2: [B, 2, N]
    templates:            # optional → maps to inpainting
      - cif: path/to/template.cif
        chain_id: [A, B]
        inpainting_metadata: path/to/metadata.json

Protenix JSON schema:
    [{"name": "...",
      "sequences": [
        {"proteinChain": {"sequence": "...", "count": 1, "modifications": [...]}},
        {"ligand": {"ligand": "CCD_SAH", "count": 1}},
      ],
      "covalent_bonds": [...],
      "inpainting": {"template_cif": "...", "metadata": "...", "chain_id_mapping": {...}}
    }]
"""

import logging
from pathlib import Path
from typing import Any

import yaml

from protenix.data.utils import int_to_letters

logger = logging.getLogger(__name__)


def load_input(path: str) -> list[dict[str, Any]]:
    """Load YAML input file(s) and return Protenix sample dict list.

    Accepts either a single YAML file or a directory containing YAML files.
    When a directory is given, all ``*.yaml`` / ``*.yml`` files are collected
    (sorted by name) and each is converted to a sample.

    Args:
        path: Path to a YAML file or a directory of YAML files.

    Returns:
        List of sample dicts in Protenix JSON format.
    """
    p = Path(path)

    if p.is_dir():
        yaml_files = sorted(
            f for f in p.iterdir()
            if f.suffix.lower() in (".yaml", ".yml") and f.is_file()
        )
        if not yaml_files:
            raise FileNotFoundError(
                f"No YAML files (*.yaml, *.yml) found in directory: {path}"
            )
        samples: list[dict[str, Any]] = []
        for yf in yaml_files:
            samples.extend(boltz_yaml_to_protenix_samples(str(yf)))
        logger.info(
            "Loaded %d sample(s) from %d YAML file(s) in %s",
            len(samples), len(yaml_files), path,
        )
        return samples

    if p.suffix.lower() not in (".yaml", ".yml"):
        raise ValueError(
            f"Unsupported input format '{p.suffix}'. Only YAML files (.yaml/.yml) "
            f"or directories of YAML files are accepted."
        )
    return boltz_yaml_to_protenix_samples(path)


def boltz_yaml_to_protenix_samples(yaml_path: str) -> list[dict[str, Any]]:
    """Convert a Boltz YAML file to a list of Protenix sample dicts.

    Args:
        yaml_path: Path to the Boltz YAML file.

    Returns:
        List of sample dicts in Protenix JSON format.
    """
    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)

    sample = _convert_single(data, yaml_path)
    return [sample]


def _normalize_id(raw_id) -> list[str]:
    """Normalize the ``id`` field from a YAML sequence entry to a list of strings.

    In the Boltz YAML sequences section:
      - ``id: A``       → ["A"]       (single chain)
      - ``id: [A, B]``  → ["A", "B"]  (two chains / copies)
      - ``id: AA``      → ["AA"]      (single chain with multi-char name)
    """
    if isinstance(raw_id, list):
        return [str(i) for i in raw_id]
    return [str(raw_id)]


def _convert_single(data: dict, yaml_path: str) -> dict[str, Any]:
    """Convert one Boltz YAML dict to a Protenix sample dict."""
    name = Path(yaml_path).stem
    sequences: list[dict] = []
    yaml_chain_ids: list[str] = []  # ordered YAML IDs matching Protenix internal order

    # ── entity tracking for constraint conversion ────────────────────────
    # chain_id → (entity_1indexed, copy_1indexed)
    chain_to_entity: dict[str, tuple[int, int]] = {}

    for entity_idx, entry in enumerate(data.get("sequences", []), start=1):
        if "protein" in entry:
            info = entry["protein"]
            ids = _normalize_id(info.get("id", [f"chain_{entity_idx}"]))
            yaml_chain_ids.extend(ids)
            for copy_num, cid in enumerate(ids, start=1):
                chain_to_entity[cid] = (entity_idx, copy_num)

            prot: dict[str, Any] = {
                "sequence": info["sequence"],
                "count": len(ids),
            }
            if mods := info.get("modifications"):
                prot["modifications"] = [
                    {"ptmPosition": m["position"], "ptmType": f"CCD_{m['ccd']}"}
                    for m in mods
                ]
            sequences.append({"proteinChain": prot})

        elif "dna" in entry:
            info = entry["dna"]
            ids = _normalize_id(info.get("id", [f"chain_{entity_idx}"]))
            yaml_chain_ids.extend(ids)
            for copy_num, cid in enumerate(ids, start=1):
                chain_to_entity[cid] = (entity_idx, copy_num)

            dna: dict[str, Any] = {
                "sequence": info["sequence"],
                "count": len(ids),
            }
            if mods := info.get("modifications"):
                dna["modifications"] = [
                    {
                        "basePosition": m["position"],
                        "modificationType": f"CCD_{m['ccd']}",
                    }
                    for m in mods
                ]
            sequences.append({"dnaSequence": dna})

        elif "rna" in entry:
            info = entry["rna"]
            ids = _normalize_id(info.get("id", [f"chain_{entity_idx}"]))
            yaml_chain_ids.extend(ids)
            for copy_num, cid in enumerate(ids, start=1):
                chain_to_entity[cid] = (entity_idx, copy_num)

            rna: dict[str, Any] = {
                "sequence": info["sequence"],
                "count": len(ids),
            }
            if mods := info.get("modifications"):
                rna["modifications"] = [
                    {
                        "basePosition": m["position"],
                        "modificationType": f"CCD_{m['ccd']}",
                    }
                    for m in mods
                ]
            sequences.append({"rnaSequence": rna})

        elif "ligand" in entry:
            info = entry["ligand"]
            ids = _normalize_id(info.get("id", [f"chain_{entity_idx}"]))
            yaml_chain_ids.extend(ids)
            for copy_num, cid in enumerate(ids, start=1):
                chain_to_entity[cid] = (entity_idx, copy_num)

            if "ccd" in info:
                ligand_str = f"CCD_{info['ccd']}"
            elif "smiles" in info:
                ligand_str = info["smiles"]
            else:
                raise ValueError(f"Ligand entry must have 'ccd' or 'smiles': {info}")

            sequences.append(
                {"ligand": {"ligand": ligand_str, "count": len(ids)}}
            )

        else:
            raise ValueError(
                f"Unknown entity type in YAML sequences entry: {list(entry.keys())}"
            )

    sample: dict[str, Any] = {"name": name, "sequences": sequences}

    # ── templates → inpainting ───────────────────────────────────────────
    templates = data.get("templates", [])
    if templates:
        template = templates[0]
        cif_path = template.get("cif", template.get("pdb", ""))

        # Build chain_id_mapping: Protenix internal ID → YAML chain ID
        chain_id_mapping: dict[str, str] = {}
        for i, yaml_id in enumerate(yaml_chain_ids):
            protenix_id = int_to_letters(i + 1)
            chain_id_mapping[protenix_id] = yaml_id

        inpainting: dict[str, Any] = {
            "template_cif": cif_path,
            "chain_id_mapping": chain_id_mapping,
        }
        if "inpainting_metadata" in template:
            inpainting["metadata"] = template["inpainting_metadata"]

        sample["inpainting"] = inpainting

    # ── constraints → covalent_bonds ─────────────────────────────────────
    constraints = data.get("constraints", [])
    covalent_bonds: list[dict] = []
    for constraint in constraints:
        if "bond" not in constraint:
            continue
        bond = constraint["bond"]
        # atom1/atom2: [chain_id, residue_position, atom_name]
        a1 = bond["atom1"]
        a2 = bond["atom2"]

        cid1, cid2 = str(a1[0]), str(a2[0])
        if cid1 not in chain_to_entity:
            raise ValueError(
                f"Bond constraint references unknown chain '{cid1}'. "
                f"Known chains: {list(chain_to_entity.keys())}"
            )
        if cid2 not in chain_to_entity:
            raise ValueError(
                f"Bond constraint references unknown chain '{cid2}'. "
                f"Known chains: {list(chain_to_entity.keys())}"
            )

        ent1, copy1 = chain_to_entity[cid1]
        ent2, copy2 = chain_to_entity[cid2]

        covalent_bonds.append(
            {
                "entity1": ent1,
                "entity2": ent2,
                "position1": int(a1[1]),
                "position2": int(a2[1]),
                "atom1": str(a1[2]),
                "atom2": str(a2[2]),
                "copy1": copy1,
                "copy2": copy2,
            }
        )

    if covalent_bonds:
        sample["covalent_bonds"] = covalent_bonds

    return sample
