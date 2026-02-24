#!/usr/bin/env python3
"""
Create Masked mmCIF for Boltz Inpainting

This script takes a PDB file and creates a masked mmCIF by:
1. Sampling missing residue segments based on real PDB statistics
2. Removing atoms from missing residues
3. Creating proper mmCIF with full sequence annotation but partial structure

Usage:
    python generate_dataset.py --input input.pdb --output output.cif
"""

import argparse
import os
import random
import numpy as np
from pathlib import Path
import logging
from collections import defaultdict
from Bio.PDB import PDBParser, PDBIO, Select
from Bio.PDB.PDBIO import PDBIO
from Bio.SeqUtils import seq1

# Statistics from AMAP analysis
SEGMENTS_MEAN = 1.82  # Average number of missing segments per structure
SEGMENT_LENGTH_MEAN = 20.6  # Average length of each missing segment
MISSING_RATIO_MIN = 0.05  # Minimum missing ratio (5% of structure length)
MISSING_RATIO_MAX = 0.20  # Maximum missing ratio (20% of structure length)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def sample_segments_count():
    """Sample number of missing segments using exponential distribution."""
    return max(1, int(np.random.exponential(SEGMENTS_MEAN)))

def sample_segment_length():
    """Sample segment length using log-normal distribution fitted to data."""
    # Fit log-normal to mean=20.6, assuming reasonable sigma
    mu = np.log(SEGMENT_LENGTH_MEAN) - 0.5 * 1.5**2  # sigma=1.5 for some spread
    sigma = 1.5
    length = int(np.random.lognormal(mu, sigma))
    return max(1, min(length, 500))  # Cap at 500 to avoid extremes

def get_structure_info(pdb_file):
    """Parse PDB file and get structure information."""
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure('protein', pdb_file)
    
    # Get all residues
    residues = []
    for model in structure:
        for chain in model:
            for residue in chain:
                if residue.id[0] == ' ':  # Standard residue
                    residues.append(residue)
    
    return structure, residues

def select_missing_segments(num_residues, min_ratio=MISSING_RATIO_MIN, max_ratio=MISSING_RATIO_MAX):
    """
    Select segments for missing residues based on statistical distributions.
    Returns list of (start, end) tuples (inclusive, 1-indexed).
    """
    num_segments = sample_segments_count()
    missing_positions = set()
    
    # Calculate max allowed missing residues
    max_missing = int(num_residues * max_ratio)
    min_missing = int(num_residues * min_ratio)
    
    logger.info(f"Sampling {num_segments} missing segments from {num_residues} residues")
    logger.info(f"Target missing residues: {min_missing}-{max_missing} ({min_ratio:.0%}-{max_ratio:.0%})")
    
    # Sample initial segments
    for seg_idx in range(num_segments):
        # Get remaining positions
        remaining = sorted(set(range(1, num_residues + 1)) - missing_positions)
        
        if len(remaining) < 5:
            logger.info(f"  Stopping early: only {len(remaining)} positions remaining")
            break
        
        # Calculate how many more residues we can add
        current_missing = len(missing_positions)
        max_additional = max_missing - current_missing
        
        if max_additional <= 0:
            logger.info(f"  Stopping: reached max ratio ({current_missing}/{num_residues} = {current_missing/num_residues:.1%})")
            break
        
        # Sample segment length
        seg_length = sample_segment_length()
        
        # Cap segment length to not exceed max_ratio
        seg_length = min(seg_length, max_additional, len(remaining))
        
        # Ensure reasonable minimum length (at least 5 residues)
        if seg_length < 5 and len(remaining) >= 5:
            seg_length = min(5, max_additional, len(remaining))
        
        # Select random contiguous segment from remaining positions
        max_start = len(remaining) - seg_length
        start_idx = random.randint(0, max_start)
        
        # Get consecutive positions
        segment_positions = remaining[start_idx:start_idx + seg_length]
        
        # Add to missing positions
        missing_positions.update(segment_positions)
        
        seg_start = segment_positions[0]
        seg_end = segment_positions[-1]
        logger.info(f"  Segment {seg_idx+1}: residues {seg_start}-{seg_end} (length={len(segment_positions)})")
    
    # Ensure minimum missing ratio by adding segments
    iteration = 0
    max_iterations = 20
    while len(missing_positions) < min_missing and iteration < max_iterations:
        iteration += 1
        remaining = sorted(set(range(1, num_residues + 1)) - missing_positions)
        
        if not remaining:
            logger.info("  No remaining positions to add")
            break
        
        # Calculate how many more we need
        current_missing = len(missing_positions)
        needed = min_missing - current_missing
        max_additional = max_missing - current_missing
        
        if max_additional <= 0:
            logger.info("  Cannot add more: would exceed max ratio")
            break
        
        # Sample segment length, but cap at what we can add
        seg_length = sample_segment_length()
        seg_length = min(seg_length, max_additional, len(remaining))
        
        # Prefer to get close to min_missing, but ensure at least some addition
        if needed > 0 and seg_length > needed:
            # Add exactly what we need (with small random variation)
            seg_length = max(1, min(needed + random.randint(-2, 5), max_additional, len(remaining)))
        
        # Ensure at least 1 residue is added per iteration
        seg_length = max(1, min(seg_length, len(remaining)))
        
        # Select random contiguous segment
        if seg_length >= len(remaining):
            segment_positions = remaining
        else:
            max_start = len(remaining) - seg_length
            start_idx = random.randint(0, max(0, max_start))
            segment_positions = remaining[start_idx:start_idx + seg_length]
        
        missing_positions.update(segment_positions)
        
        seg_start = segment_positions[0]
        seg_end = segment_positions[-1]
        logger.info(f"  Additional segment: residues {seg_start}-{seg_end} (length={len(segment_positions)})")
        
        if len(missing_positions) >= min_missing:
            logger.info(f"  Reached minimum threshold: {len(missing_positions)}/{num_residues} = {len(missing_positions)/num_residues:.1%}")
            break
    
    # Merge overlapping/adjacent segments and sort
    segments = []
    sorted_missing = sorted(missing_positions)
    
    if sorted_missing:
        current_start = sorted_missing[0]
        current_end = sorted_missing[0]
        
        for pos in sorted_missing[1:]:
            if pos == current_end + 1:
                # Extend current segment
                current_end = pos
            else:
                # Save current segment and start new one
                segments.append((current_start, current_end))
                current_start = pos
                current_end = pos
        
        # Add last segment
        segments.append((current_start, current_end))
    
    missing_ratio = len(missing_positions) / num_residues
    
    # Final check: ensure we meet minimum requirement
    if missing_ratio < min_ratio:
        logger.warning(f"  Missing ratio {missing_ratio:.1%} below minimum {min_ratio:.0%}, adding more residues...")
        iteration = 0
        max_final_iterations = 10
        while len(missing_positions) < min_missing and iteration < max_final_iterations:
            iteration += 1
            remaining = sorted(set(range(1, num_residues + 1)) - missing_positions)
            if not remaining:
                break
            
            needed = min_missing - len(missing_positions)
            max_additional = max_missing - len(missing_positions)
            
            # Add exactly what we need
            seg_length = min(needed, max_additional, len(remaining))
            seg_length = max(1, seg_length)
            
            if seg_length >= len(remaining):
                segment_positions = remaining
            else:
                start_idx = random.randint(0, max(0, len(remaining) - seg_length))
                segment_positions = remaining[start_idx:start_idx + seg_length]
            
            missing_positions.update(segment_positions)
            logger.info(f"  Final adjustment: added {len(segment_positions)} residues ({segment_positions[0]}-{segment_positions[-1]})")
            
            if len(missing_positions) >= min_missing:
                break
        
        # Recalculate merged segments after final adjustment
        segments = []
        sorted_missing = sorted(missing_positions)
        
        if sorted_missing:
            current_start = sorted_missing[0]
            current_end = sorted_missing[0]
            
            for pos in sorted_missing[1:]:
                if pos == current_end + 1:
                    current_end = pos
                else:
                    segments.append((current_start, current_end))
                    current_start = pos
                    current_end = pos
            
            segments.append((current_start, current_end))
        
        missing_ratio = len(missing_positions) / num_residues
    
    logger.info(f"Total missing: {len(missing_positions)}/{num_residues} residues ({missing_ratio:.1%})")
    logger.info(f"Total segments after merging: {len(segments)}")
    
    return sorted(segments), sorted(list(missing_positions))

def write_mmcif(structure, residues, missing_positions, output_file, pdb_id="protein"):
    """
    Write mmCIF file with full sequence annotation but partial atom coordinates.
    """
    # Get sequence information
    all_residues_info = []
    for idx, residue in enumerate(residues, 1):
        resname = residue.get_resname()
        all_residues_info.append((idx, resname))
    
    # Get present residues (not in missing)
    present_residues = [(idx, res) for idx, res in zip(range(1, len(residues)+1), residues) 
                        if idx not in missing_positions]
    
    logger.info(f"Writing mmCIF: {len(all_residues_info)} total residues, {len(present_residues)} present")
    
    with open(output_file, 'w') as f:
        # Header
        f.write("data_masked\n#\n#\n")
        
        # Entity information
        f.write("_entity.details                  ?\n")
        f.write("_entity.formula_weight           ?\n")
        f.write("_entity.id                       1\n")
        f.write(f"_entity.pdbx_description         \"{pdb_id}\"\n")
        f.write("_entity.pdbx_ec                  ?\n")
        f.write("_entity.pdbx_fragment            ?\n")
        f.write("_entity.pdbx_mutation            ?\n")
        f.write("_entity.pdbx_number_of_molecules 1\n")
        f.write("_entity.src_method               man\n")
        f.write("_entity.type                     polymer\n#\n")
        
        # Entity poly
        one_letter_seq = ''.join([seq1(resname) for _, resname in all_residues_info])
        f.write("_entity_poly.entity_id                    1\n")
        f.write("_entity_poly.nstd_linkage                 no\n")
        f.write("_entity_poly.nstd_monomer                 no\n")
        f.write("_entity_poly.pdbx_seq_one_letter_code     \n;\n")
        f.write(f"{one_letter_seq}\n;\n")
        f.write("_entity_poly.pdbx_seq_one_letter_code_can \n;\n")
        f.write(f"{one_letter_seq}\n;\n")
        f.write("_entity_poly.pdbx_strand_id               A\n")
        f.write("_entity_poly.type                         polypeptide(L)\n#\n")
        
        # Entity poly seq (full sequence)
        f.write("loop_\n")
        f.write("_entity_poly_seq.entity_id\n")
        f.write("_entity_poly_seq.hetero\n")
        f.write("_entity_poly_seq.mon_id\n")
        f.write("_entity_poly_seq.num\n")
        for seq_num, resname in all_residues_info:
            f.write(f"1 n {resname} {seq_num}\n")
        f.write("#\n")
        
        # Poly seq scheme (full sequence mapping)
        f.write("loop_\n")
        f.write("_pdbx_poly_seq_scheme.asym_id\n")
        f.write("_pdbx_poly_seq_scheme.auth_seq_num\n")
        f.write("_pdbx_poly_seq_scheme.entity_id\n")
        f.write("_pdbx_poly_seq_scheme.hetero\n")
        f.write("_pdbx_poly_seq_scheme.mon_id\n")
        f.write("_pdbx_poly_seq_scheme.pdb_ins_code\n")
        f.write("_pdbx_poly_seq_scheme.pdb_mon_id\n")
        f.write("_pdbx_poly_seq_scheme.pdb_seq_num\n")
        f.write("_pdbx_poly_seq_scheme.pdb_strand_id\n")
        f.write("_pdbx_poly_seq_scheme.seq_id\n")
        for seq_num, resname in all_residues_info:
            f.write(f"A {seq_num} 1 n {resname} . {resname} {seq_num} A {seq_num}\n")
        f.write("#\n")
        
        # Atom site (only present residues, renumbered)
        f.write("loop_\n")
        f.write("_atom_site.group_PDB\n")
        f.write("_atom_site.id\n")
        f.write("_atom_site.type_symbol\n")
        f.write("_atom_site.label_atom_id\n")
        f.write("_atom_site.label_alt_id\n")
        f.write("_atom_site.label_comp_id\n")
        f.write("_atom_site.label_asym_id\n")
        f.write("_atom_site.label_entity_id\n")
        f.write("_atom_site.label_seq_id\n")
        f.write("_atom_site.pdbx_PDB_ins_code\n")
        f.write("_atom_site.Cartn_x\n")
        f.write("_atom_site.Cartn_y\n")
        f.write("_atom_site.Cartn_z\n")
        f.write("_atom_site.occupancy\n")
        f.write("_atom_site.B_iso_or_equiv\n")
        f.write("_atom_site.auth_seq_id\n")
        f.write("_atom_site.auth_asym_id\n")
        f.write("_atom_site.pdbx_PDB_model_num\n")
        
        atom_id = 1
        for orig_seq_num, residue in present_residues:
            resname = residue.get_resname()
            for atom in residue:
                atom_name = atom.get_name()
                element = atom.element if hasattr(atom, 'element') and atom.element else atom_name[0]
                coord = atom.get_coord()
                bfactor = atom.get_bfactor()
                occupancy = atom.get_occupancy()
                
                f.write(f"ATOM {atom_id} {element} {atom_name} . {resname} A 1 {orig_seq_num} ? ")
                f.write(f"{coord[0]:.3f} {coord[1]:.3f} {coord[2]:.3f} ")
                f.write(f"{occupancy:.1f} {bfactor:.2f} {orig_seq_num} A 1\n")
                atom_id += 1
        
        f.write("#\n")
    
    logger.info(f"mmCIF file written: {output_file}")

def process_single_pdb(input_file, output_file, pdb_id=None):
    """
    Process a single PDB file and return statistics.
    Returns: dict with statistics or None if failed
    """
    try:
        # Derive PDB ID from filename if not provided
        if pdb_id is None:
            pdb_id = Path(input_file).stem
        
        # Load structure
        structure, residues = get_structure_info(input_file)
        num_residues = len(residues)
        
        if not (50 <= num_residues <= 1000):
            logger.warning(f"{pdb_id}: Structure length {num_residues} is outside recommended range (50-1000)")
            return None
        
        # Select missing segments
        segments, missing_positions = select_missing_segments(num_residues)
        
        # Write mmCIF
        write_mmcif(structure, residues, missing_positions, output_file, pdb_id)
        
        # Collect statistics
        stats = {
            'pdb_id': pdb_id,
            'num_residues': num_residues,
            'num_missing': len(missing_positions),
            'missing_ratio': len(missing_positions) / num_residues,
            'num_segments': len(segments),
            'segment_lengths': [end - start + 1 for start, end in segments],
            'segments': segments,
            'missing_positions': missing_positions
        }
        
        return stats
        
    except Exception as e:
        logger.error(f"Error processing {input_file}: {e}")
        return None

def process_directory(input_dir, output_dir, num_samples=1000, save_stats=False):
    """
    Process a directory of PDB files.
    Randomly samples num_samples files and creates masked CIFs.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find all PDB files
    pdb_files = list(input_path.glob("*.pdb"))
    logger.info(f"Found {len(pdb_files)} PDB files in {input_dir}")
    
    if len(pdb_files) == 0:
        logger.error("No PDB files found!")
        return
    
    # Sample random files
    if len(pdb_files) > num_samples:
        sampled_files = random.sample(pdb_files, num_samples)
        logger.info(f"Randomly sampled {num_samples} files")
    else:
        sampled_files = pdb_files
        logger.info(f"Using all {len(sampled_files)} files")
    
    # Process files
    all_stats = []
    successful = 0
    failed = 0
    
    logger.info(f"\nProcessing {len(sampled_files)} PDB files...")
    logger.info("="*60)
    
    for idx, pdb_file in enumerate(sampled_files, 1):
        pdb_id = pdb_file.stem
        output_file = output_path / f"{pdb_id}_masked.cif"
        
        logger.info(f"[{idx}/{len(sampled_files)}] Processing {pdb_id}...")
        
        stats = process_single_pdb(pdb_file, output_file, pdb_id)
        
        if stats:
            all_stats.append(stats)
            successful += 1
            logger.info(f"  ✓ Success: {stats['num_missing']}/{stats['num_residues']} missing ({stats['missing_ratio']:.1%}), {stats['num_segments']} segments")
        else:
            failed += 1
            logger.warning(f"  ✗ Failed")
    
    logger.info("="*60)
    logger.info(f"\nProcessing complete:")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Failed: {failed}")
    
    # Save statistics if requested
    if save_stats and all_stats:
        stats_file = output_path / "dataset_statistics.npz"
        
        # Aggregate statistics
        all_num_residues = [s['num_residues'] for s in all_stats]
        all_num_missing = [s['num_missing'] for s in all_stats]
        all_missing_ratios = [s['missing_ratio'] for s in all_stats]
        all_num_segments = [s['num_segments'] for s in all_stats]
        all_segment_lengths = [length for s in all_stats for length in s['segment_lengths']]
        
        # Save to npz
        np.savez(
            stats_file,
            pdb_ids=[s['pdb_id'] for s in all_stats],
            num_residues=np.array(all_num_residues),
            num_missing=np.array(all_num_missing),
            missing_ratios=np.array(all_missing_ratios),
            num_segments=np.array(all_num_segments),
            segment_lengths=np.array(all_segment_lengths),
        )
        
        logger.info(f"\nStatistics saved to {stats_file}")
        logger.info(f"\nDataset Statistics Summary:")
        logger.info(f"  Total structures: {len(all_stats)}")
        logger.info(f"  Residues - Mean: {np.mean(all_num_residues):.1f}, Range: [{np.min(all_num_residues)}, {np.max(all_num_residues)}]")
        logger.info(f"  Missing residues - Mean: {np.mean(all_num_missing):.1f}, Median: {np.median(all_num_missing):.1f}")
        logger.info(f"  Missing ratio - Mean: {np.mean(all_missing_ratios):.1%}, Range: [{np.min(all_missing_ratios):.1%}, {np.max(all_missing_ratios):.1%}]")
        logger.info(f"  Segments per structure - Mean: {np.mean(all_num_segments):.2f}, Median: {np.median(all_num_segments):.1f}")
        logger.info(f"  Segment lengths - Mean: {np.mean(all_segment_lengths):.1f}, Median: {np.median(all_segment_lengths):.1f}")
        logger.info(f"  Total segments: {len(all_segment_lengths)}")

def main():
    parser = argparse.ArgumentParser(
        description="Create masked mmCIF from PDB file(s)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file
  python generate_dataset.py --input protein.pdb --output masked.cif
  
  # Directory (1000 random samples)
  python generate_dataset.py --input /path/to/pdbs --output /path/to/output --num_samples 1000
  
  # Directory with statistics
  python generate_dataset.py --input /path/to/pdbs --output /path/to/output --save_stats
        """
    )
    parser.add_argument('--input', type=str, required=True,
                       help='Input PDB file or directory containing PDB files')
    parser.add_argument('--output', type=str, required=True,
                       help='Output mmCIF file (for single file) or output directory (for directory input)')
    parser.add_argument('--pdb_id', type=str, default=None,
                       help='PDB ID for annotation (single file only, default: derived from filename)')
    parser.add_argument('--num_samples', type=int, default=1000,
                       help='Number of random samples to process from directory (default: 1000)')
    parser.add_argument('--save_stats', action='store_true',
                       help='Save dataset statistics to NPZ file (directory mode only)')
    parser.add_argument('--seed', type=int, default=None,
                       help='Random seed for reproducibility')
    args = parser.parse_args()
    
    # Set random seed
    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)
        logger.info(f"Random seed set to {args.seed}")
    
    input_path = Path(args.input)
    
    # Check if input is directory or file
    if input_path.is_dir():
        logger.info(f"Input is directory: {args.input}")
        logger.info(f"Output directory: {args.output}")
        logger.info(f"Number of samples: {args.num_samples}")
        logger.info(f"Save statistics: {args.save_stats}")
        
        process_directory(args.input, args.output, args.num_samples, args.save_stats)
        
    elif input_path.is_file():
        logger.info(f"Input is file: {args.input}")
        logger.info(f"Output file: {args.output}")
        
        # Derive PDB ID from filename if not provided
        if args.pdb_id is None:
            args.pdb_id = input_path.stem
        
        logger.info(f"PDB ID: {args.pdb_id}")
        
        # Process single file
        stats = process_single_pdb(args.input, args.output, args.pdb_id)
        
        if stats:
            logger.info(f"\nMissing segments:")
            for i, (start, end) in enumerate(stats['segments'], 1):
                logger.info(f"  Segment {i}: {start}-{end} (length={end-start+1})")
            
            logger.info(f"\nDone! Output saved to {args.output}")
        else:
            logger.error("Failed to process file")
    else:
        logger.error(f"Input path does not exist: {args.input}")

if __name__ == "__main__":
    main()