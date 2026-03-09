#!/usr/bin/env python3
"""
Generate Boltz inpainting YAML files from masked CIF structures.

This script takes masked CIF files (with missing residues) and generates
YAML configuration files for Boltz inpainting. The YAML includes:
- Full sequence (including missing residues) from _entity_poly_seq
- Template pointing to the masked CIF structure

Usage:
    # Single file
    python generate_yaml.py --input masked.cif --output config.yaml
    
    # Directory mode
    python generate_yaml.py --input /path/to/masked_cifs --output /path/to/yamls
"""

import argparse
import logging
from pathlib import Path
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from typing import Optional, Tuple, List, Dict, Any
import random


# Standard 20 amino acids three-letter -> one-letter
AA_MAP = {
    'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F',
    'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LYS': 'K', 'LEU': 'L',
    'MET': 'M', 'ASN': 'N', 'PRO': 'P', 'GLN': 'Q', 'ARG': 'R',
    'SER': 'S', 'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
}

# Non-standard residues that may appear in _entity_poly_seq (keep as modification, use X in sequence)
NON_STD_CCD = frozenset({'PTR', 'SEP', 'TPO', 'ACE', 'DIP', 'MSE', 'HYP', 'PCA', 'PYL', 'SEC'})


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _entity_seqs_from_mmcif(mmcif_dict: dict) -> Dict[int, Tuple[str, List[Dict[str, Any]]]]:
    """
    Build entity_id -> (sequence, modifications) from _entity_poly_seq.
    """
    if '_entity_poly_seq.mon_id' not in mmcif_dict:
        return {}
    eid = mmcif_dict['_entity_poly_seq.entity_id']
    num = mmcif_dict['_entity_poly_seq.num']
    mon_id = mmcif_dict['_entity_poly_seq.mon_id']
    # Ensure lists (MMCIF2Dict sometimes returns single str for one-row)
    if isinstance(eid, str):
        eid = [eid]
    if isinstance(num, str):
        num = [num]
    if isinstance(mon_id, str):
        mon_id = [mon_id]
    num = [int(n) for n in num]
    # Group by entity_id, sort by num
    by_entity: Dict[int, List[Tuple[int, str]]] = {}
    for i, ent in enumerate(eid):
        ent_id = int(ent) if isinstance(ent, str) else ent
        if ent_id not in by_entity:
            by_entity[ent_id] = []
        by_entity[ent_id].append((num[i], mon_id[i]))
    out = {}
    for ent_id, items in by_entity.items():
        items.sort(key=lambda x: x[0])
        seq_parts = []
        mods = []
        for pos_1based, (_, code) in enumerate(items, 1):
            one = AA_MAP.get(code, 'X')
            seq_parts.append(one)
            if code in NON_STD_CCD:
                mods.append({'position': pos_1based, 'ccd': code})
        out[ent_id] = (''.join(seq_parts), mods if mods else [])
    return out


def extract_all_chains_from_cif(cif_file: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Extract all polymer chains and their sequences from a CIF file.

    Uses _entity_poly_seq for full sequence per entity and _struct_asym to map
    chain IDs to entities. Returns one entry per chain (A, B, C, D, ...) with
    sequence and optional modifications (e.g. PTR).

    Returns:
        List of dicts with keys: id (chain_id), sequence, modifications (list or empty).
        None if parsing fails.
    """
    try:
        mmcif_dict = MMCIF2Dict(str(cif_file))
        entity_seqs = _entity_seqs_from_mmcif(mmcif_dict)
        if not entity_seqs:
            logger.error(f"No _entity_poly_seq data in {cif_file}")
            return None

        # entity_id -> entity_type (protein, dna, rna) from _entity_poly
        entity_type_map: Dict[int, str] = {}
        if '_entity_poly.entity_id' in mmcif_dict and '_entity_poly.type' in mmcif_dict:
            eids = mmcif_dict['_entity_poly.entity_id']
            ptypes = mmcif_dict['_entity_poly.type']
            if isinstance(eids, str):
                eids = [eids]
            if isinstance(ptypes, str):
                ptypes = [ptypes]
            for i, eid in enumerate(eids):
                ent_id = int(eid) if isinstance(eid, str) else eid
                pt = ptypes[i] if i < len(ptypes) else ""
                if "polypeptide" in str(pt).lower():
                    entity_type_map[ent_id] = "protein"
                elif "polydeoxyribonucleotide" in str(pt).lower() or "poly(dna)" in str(pt).lower():
                    entity_type_map[ent_id] = "dna"
                elif "polyribonucleotide" in str(pt).lower() or "poly(rna)" in str(pt).lower():
                    entity_type_map[ent_id] = "rna"
                else:
                    entity_type_map[ent_id] = "protein"

        # struct_asym: id -> chain id, entity_id -> entity (filter polymer only)
        if '_struct_asym.id' not in mmcif_dict or '_struct_asym.entity_id' not in mmcif_dict:
            logger.error(f"No _struct_asym in {cif_file}")
            return None
        asym_ids = mmcif_dict['_struct_asym.id']
        asym_entity = mmcif_dict['_struct_asym.entity_id']
        if isinstance(asym_ids, str):
            asym_ids = [asym_ids]
        if isinstance(asym_entity, str):
            asym_entity = [asym_entity]
        polymer_entity_ids = set(entity_seqs.keys())
        chains = []
        for chain_id, eid in zip(asym_ids, asym_entity):
            ent_id = int(eid) if isinstance(eid, str) else eid
            if ent_id not in polymer_entity_ids:
                continue
            seq, mods = entity_seqs[ent_id]
            entity_type = entity_type_map.get(ent_id, "protein")
            chains.append({
                'id': chain_id,
                'sequence': seq,
                'entity_type': entity_type,
                'modifications': mods,
            })
        if not chains:
            logger.error(f"No polymer chains found in {cif_file}")
            return None
        return chains
    except Exception as e:
        logger.error(f"Error extracting chains from {cif_file}: {e}")
        return None


def extract_sequence_from_cif(cif_file: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract the full sequence and chain ID from a CIF file (first chain only).
    Prefer extract_all_chains_from_cif() for multi-chain CIFs.

    Returns:
        Tuple of (sequence, chain_id) or (None, None) if extraction fails
    """
    chains = extract_all_chains_from_cif(cif_file)
    if not chains:
        return None, None
    c = chains[0]
    return c['sequence'], c['id']


def _yaml_ccd_value(ccd: Any) -> str:
    """Format CCD code for YAML: always quoted so it is never parsed as number, bool, or null."""
    s = str(ccd).strip() if ccd is not None else ""
    # Always quote so YAML never interprets as int, float, octal, bool, yes/no, null, etc.
    return repr(s)


def _yaml_str(value: Any) -> str:
    """Single-quote a chain ID or arbitrary string for safe YAML output.

    Single-quoted YAML scalars treat backslash as literal (no escape processing).
    Single quotes inside the value are escaped by doubling them: ' -> ''.
    This handles numeric-looking IDs ('2'), IDs with special chars ('A\\', 'A['), etc.
    """
    s = str(value) if value is not None else ""
    return "'" + s.replace("'", "''") + "'"


def generate_yaml_content(
    chains: List[Dict[str, Any]],
    cif_path: str,
    use_absolute_path: bool = True,
) -> str:
    """
    Generate YAML content for Boltz inpainting (all chains).

    Args:
        chains: List of dicts with id, sequence, modifications (optional)
        cif_path: Path to the CIF file
        use_absolute_path: If True, use absolute path for CIF file

    Returns:
        YAML content as string
    """
    if use_absolute_path:
        cif_path = str(Path(cif_path).resolve())

    lines = ["version: 1", "", "sequences:"]
    for c in chains:
        entity_type = c.get("entity_type", "protein")
        if entity_type == "ligand":
            lines.append("  - ligand:")
            lines.append(f"      id: {_yaml_str(c['id'])}")
            if c.get("ccd"):
                lines.append(f"      ccd: {_yaml_ccd_value(c['ccd'])}")
            elif c.get("smiles"):
                lines.append(f"      smiles: {repr(c['smiles'])}")
            else:
                lines.append(f"      ccd: {_yaml_ccd_value(c.get('ccd', 'UNK'))}")
        else:
            if entity_type not in ("protein", "dna", "rna"):
                entity_type = "protein"
            lines.append(f"  - {entity_type}:")
            lines.append(f"      id: {_yaml_str(c['id'])}")
            lines.append(f"      sequence: {c['sequence']}")
            if entity_type == "protein":
                lines.append("      msa: empty")
            if c.get("modifications"):
                lines.append("      modifications:")
                for m in c["modifications"]:
                    lines.append(f"        - position: {m['position']}")
                    lines.append(f"          ccd: {_yaml_ccd_value(m['ccd'])}")
        lines.append("")
    lines.append("templates:")
    lines.append(f"  - cif: {cif_path}")
    chain_ids_for_template = [c["id"] for c in chains]
    if len(chain_ids_for_template) == 1:
        lines.append(f"    chain_id: {_yaml_str(chain_ids_for_template[0])}")
    else:
        quoted = [_yaml_str(cid) for cid in chain_ids_for_template]
        lines.append(f"    chain_id: [{', '.join(quoted)}]")
    return "\n".join(lines).rstrip() + "\n"


def process_single_cif(input_file: Path, output_file: Path,
                       use_absolute_path: bool = True) -> bool:
    """
    Process a single CIF file and generate YAML for all polymer chains.

    Args:
        input_file: Path to input CIF file
        output_file: Path to output YAML file
        use_absolute_path: If True, use absolute path for CIF in YAML

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Processing {input_file.name}...")

    chains = extract_all_chains_from_cif(input_file)
    if not chains:
        logger.error(f"Failed to extract chains from {input_file}")
        return False

    yaml_content = generate_yaml_content(
        chains=chains,
        cif_path=str(input_file),
        use_absolute_path=use_absolute_path,
    )

    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(yaml_content)

        logger.info(f"  Generated: {output_file}")
        logger.info(f"  Chains: {[c['id'] for c in chains]}")
        for c in chains:
            logger.info(f"    Chain {c['id']}: length {len(c['sequence'])}")
        return True

    except Exception as e:
        logger.error(f"Error writing YAML file {output_file}: {e}")
        return False


def process_directory(input_dir: Path, output_dir: Path, 
                      num_samples: Optional[int] = None,
                      use_absolute_path: bool = True,
                      seed: Optional[int] = None) -> Tuple[int, int]:
    """
    Process all CIF files in a directory.
    
    Args:
        input_dir: Directory containing CIF files
        output_dir: Directory to save YAML files
        num_samples: If specified, randomly sample this many files
        use_absolute_path: If True, use absolute paths for CIF files in YAML
        seed: Random seed for reproducibility
        
    Returns:
        Tuple of (num_success, num_total)
    """
    # Find all CIF files
    cif_files = sorted(input_dir.glob("*.cif"))
    
    if len(cif_files) == 0:
        logger.error(f"No CIF files found in {input_dir}")
        return 0, 0
    
    logger.info(f"Found {len(cif_files)} CIF files in {input_dir}")
    
    # Random sampling if requested
    if num_samples is not None and num_samples < len(cif_files):
        if seed is not None:
            random.seed(seed)
        cif_files = random.sample(cif_files, num_samples)
        logger.info(f"Randomly sampled {num_samples} files (seed={seed})")
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each file
    num_success = 0
    num_total = len(cif_files)
    
    for idx, cif_file in enumerate(cif_files, 1):
        logger.info(f"[{idx}/{num_total}] Processing {cif_file.name}")
        
        # Generate output filename (replace .cif with .yaml)
        output_file = output_dir / cif_file.name.replace('.cif', '.yaml')
        
        success = process_single_cif(cif_file, output_file, use_absolute_path)
        if success:
            num_success += 1
    
    return num_success, num_total


def main():
    parser = argparse.ArgumentParser(
        description='Generate Boltz inpainting YAML files from masked CIF structures',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file mode
  python generate_yaml.py --input masked.cif --output config.yaml
  
  # Directory mode (process all)
  python generate_yaml.py --input /path/to/masked_cifs --output /path/to/yamls
  
  # Directory mode (sample 100 files)
  python generate_yaml.py --input /path/to/masked_cifs --output /path/to/yamls --num_samples 100 --seed 42
  
  # Use relative paths in YAML
  python generate_yaml.py --input masked.cif --output config.yaml --relative_path
        """
    )
    
    parser.add_argument('--input', type=str, required=True,
                        help='Input CIF file or directory containing CIF files')
    parser.add_argument('--output', type=str, required=True,
                        help='Output YAML file or directory for YAML files')
    parser.add_argument('--num_samples', type=int, default=None,
                        help='Number of files to randomly sample (directory mode only)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility')
    parser.add_argument('--relative_path', action='store_true',
                        help='Use relative paths for CIF files in YAML (default: absolute)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    # Check if input exists
    if not input_path.exists():
        logger.error(f"Input path does not exist: {input_path}")
        return 1
    
    # Determine mode: single file or directory
    if input_path.is_file():
        # Single file mode
        if not input_path.suffix == '.cif':
            logger.error(f"Input file must be a CIF file: {input_path}")
            return 1
        
        if output_path.is_dir():
            logger.error(f"Output must be a file when input is a file")
            return 1
        
        success = process_single_cif(
            input_path, 
            output_path,
            use_absolute_path=not args.relative_path
        )
        
        if success:
            logger.info("✓ YAML generation completed successfully")
            return 0
        else:
            logger.error("✗ YAML generation failed")
            return 1
    
    elif input_path.is_dir():
        # Directory mode
        if output_path.exists() and output_path.is_file():
            logger.error(f"Output must be a directory when input is a directory")
            return 1
        
        num_success, num_total = process_directory(
            input_path,
            output_path,
            num_samples=args.num_samples,
            use_absolute_path=not args.relative_path,
            seed=args.seed
        )
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing Summary:")
        logger.info(f"{'='*60}")
        logger.info(f"Total files processed: {num_total}")
        logger.info(f"Successful: {num_success}")
        logger.info(f"Failed: {num_total - num_success}")
        logger.info(f"Success rate: {num_success/num_total*100:.1f}%")
        
        if num_success == num_total:
            logger.info("✓ All YAML files generated successfully")
            return 0
        else:
            logger.warning(f"⚠ {num_total - num_success} files failed")
            return 1
    
    else:
        logger.error(f"Input path is neither a file nor a directory: {input_path}")
        return 1


if __name__ == '__main__':
    exit(main())
