"""Missing atom checks and inpainting region detection."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..constants import ref_atoms
from .log import info, detail, section


class ValidationMixin:
    def check_missing_atoms(self, atoms: List[Dict], residue_mapping: Dict[int, int], final_sequence: str):
        """
        Check for missing atoms in each residue and log them.

        Args:
            atoms: List of atom dictionaries
            residue_mapping: Mapping from sequential index to SEQRES position
            final_sequence: Final sequence to use
        """
        # Build reverse mapping: (auth_seq_id_base, ins_code) -> SEQRES position
        key_to_seqres = {}
        for seq_idx, seqres_pos in residue_mapping.items():
            if hasattr(self, '_residue_index_to_key'):
                key = self._residue_index_to_key[seq_idx]
                key_to_seqres[key] = seqres_pos

        # Group atoms by residue (using new numbering)
        # Use set to handle alternative locations
        residue_atoms = {}
        residue_types = {}

        for atom in atoms:
            # Extract residue key from atom
            auth_seq_id_str = str(atom['auth_seq_id']).strip()
            ins_code = atom.get('pdbx_PDB_ins_code', '?')
            if ins_code == '?':
                ins_code = ''

            # Parse base number
            import re
            match = re.match(r'^(-?\d+)', auth_seq_id_str)
            if not match:
                continue
            auth_seq_id_base = int(match.group(1))

            residue_key = (auth_seq_id_base, ins_code)

            # Skip residues that were removed (e.g., in UniProt mode)
            if residue_key not in key_to_seqres:
                continue

            new_seq_id = key_to_seqres[residue_key]

            if new_seq_id not in residue_atoms:
                residue_atoms[new_seq_id] = set()
                residue_types[new_seq_id] = atom['label_comp_id']

            # Add atom name to set (automatically handles duplicates from alt locs)
            residue_atoms[new_seq_id].add(atom['label_atom_id'])

        # Check for missing atoms
        missing_atoms_log = []
        total_missing = 0

        # Convert 1-letter to 3-letter codes
        aa_one_to_three = {
            'A': 'ALA', 'C': 'CYS', 'D': 'ASP', 'E': 'GLU',
            'F': 'PHE', 'G': 'GLY', 'H': 'HIS', 'I': 'ILE',
            'K': 'LYS', 'L': 'LEU', 'M': 'MET', 'N': 'ASN',
            'P': 'PRO', 'Q': 'GLN', 'R': 'ARG', 'S': 'SER',
            'T': 'THR', 'V': 'VAL', 'W': 'TRP', 'Y': 'TYR'
        }

        # Only check residues that exist in the structure
        for seq_pos in sorted(residue_atoms.keys()):
            # Get residue type from sequence (not from structure)
            if seq_pos <= len(final_sequence):
                aa_one = final_sequence[seq_pos - 1]  # 0-indexed
                aa_three_letter = aa_one_to_three.get(aa_one, 'UNK')
            else:
                aa_three_letter = 'UNK'

            expected_atoms = set(ref_atoms.get(aa_three_letter, ref_atoms.get("UNK", [])))
            actual_atoms = residue_atoms[seq_pos]  # Already a set
            missing_atoms = expected_atoms - actual_atoms

            if missing_atoms:
                missing_atoms_log.append({
                    'residue': seq_pos,
                    'type': aa_three_letter,
                    'missing': sorted(missing_atoms),
                    'expected_count': len(expected_atoms),
                    'actual_count': len(actual_atoms)
                })
                total_missing += len(missing_atoms)

        # Log missing atoms
        if missing_atoms_log and self.verbose:
            section("MISSING ATOMS IN RESIDUES")
            info(f"Total residues with missing atoms: {len(missing_atoms_log)}")
            info(f"Total missing atoms: {total_missing}")

            for entry in missing_atoms_log:
                detail(f"Residue {entry['residue']} ({entry['type']}): "
                       f"missing {len(entry['missing'])}/{entry['expected_count']} atoms")
                detail(f"  Missing atoms: {', '.join(entry['missing'])}")
                detail(f"  Present atoms: {entry['actual_count']}")
        elif not missing_atoms_log:
            if self.verbose:
                section("MISSING ATOMS CHECK")
                detail("No missing atoms found in residues with structure!")

    def determine_inpainting_region(self, atoms: List[Dict], residue_mapping: Dict[int, int], final_sequence: str) -> Tuple[Tuple[int, int], Dict[str, Any]]:
        """
        Determine the inpainting region (missing residues) by checking atom presence per residue.
        This matches the logic in boltz2.py _validate_and_prepare_inpainting.

        Args:
            atoms: List of atom dictionaries
            residue_mapping: Mapping from sequential index to SEQRES position
            final_sequence: Final sequence to use

        Returns:
            Tuple of:
              - (start, end) residue numbers of the largest inpainting gap
              - metadata dict with fully_fixed/partially_fixed/fully_inpainted residues
        """
        # Build reverse mapping: (auth_seq_id_base, ins_code) -> SEQRES position
        key_to_seqres = {}
        for seq_idx, seqres_pos in residue_mapping.items():
            if hasattr(self, '_residue_index_to_key'):
                key = self._residue_index_to_key[seq_idx]
                key_to_seqres[key] = seqres_pos

        # Group atoms by residue (using new numbering)
        residue_atoms = {}
        residue_types = {}

        for atom in atoms:
            # Extract residue key from atom
            auth_seq_id_str = str(atom['auth_seq_id']).strip()
            ins_code = atom.get('pdbx_PDB_ins_code', '?')
            if ins_code == '?':
                ins_code = ''

            # Parse base number
            import re
            match = re.match(r'^(-?\d+)', auth_seq_id_str)
            if not match:
                continue
            auth_seq_id_base = int(match.group(1))

            residue_key = (auth_seq_id_base, ins_code)

            # Skip residues that were removed (e.g., in UniProt mode)
            if residue_key not in key_to_seqres:
                continue

            new_seq_id = key_to_seqres[residue_key]

            if new_seq_id not in residue_atoms:
                residue_atoms[new_seq_id] = set()
                residue_types[new_seq_id] = atom['label_comp_id']

            residue_atoms[new_seq_id].add(atom['label_atom_id'])

        # Sequence length
        seq_length = len(final_sequence)

        # Convert 1-letter to 3-letter codes
        aa_one_to_three = {
            'A': 'ALA', 'C': 'CYS', 'D': 'ASP', 'E': 'GLU',
            'F': 'PHE', 'G': 'GLY', 'H': 'HIS', 'I': 'ILE',
            'K': 'LYS', 'L': 'LEU', 'M': 'MET', 'N': 'ASN',
            'P': 'PRO', 'Q': 'GLN', 'R': 'ARG', 'S': 'SER',
            'T': 'THR', 'V': 'VAL', 'W': 'TRP', 'Y': 'TYR'
        }

        # Classify each residue based on atom presence
        residues_fully_fixed = []
        residues_partially_fixed = []
        residues_fully_inpainted = []

        for seq_pos in range(1, seq_length + 1):
            # Get residue type from sequence (not from structure)
            if seq_pos <= len(final_sequence):
                aa_one = final_sequence[seq_pos - 1]  # 0-indexed
                aa_three_letter = aa_one_to_three.get(aa_one, 'UNK')
            else:
                aa_three_letter = 'UNK'

            # For non-standard residues (X), use actual structure atoms as expected set
            # since ref_atoms only covers standard amino acids (NAG, etc. have different atom names)
            if aa_three_letter == 'UNK' and seq_pos in residue_atoms:
                actual_type = residue_types.get(seq_pos, 'UNK')
                if actual_type not in ref_atoms:
                    # Non-standard residue (e.g. NAG): all structure atoms count as expected
                    expected_atoms = residue_atoms[seq_pos]
                else:
                    expected_atoms = set(ref_atoms.get(actual_type, ref_atoms.get("UNK", [])))
            else:
                expected_atoms = set(ref_atoms.get(aa_three_letter, ref_atoms.get("UNK", [])))

            if seq_pos in residue_atoms:
                # Residue has some structure - check if all atoms are present
                # Only count atoms that are in ref_atoms (exclude hydrogen and other non-standard atoms)
                all_actual_atoms = residue_atoms[seq_pos]
                actual_atoms = all_actual_atoms & expected_atoms  # Intersection: only ref_atoms

                if len(actual_atoms) == len(expected_atoms):
                    # All expected atoms present
                    residues_fully_fixed.append(seq_pos)
                elif len(actual_atoms) > 0:
                    # Some atoms missing
                    residues_partially_fixed.append((seq_pos, len(actual_atoms), len(expected_atoms)))
                else:
                    # No expected atoms present (only non-standard atoms like hydrogen)
                    residues_fully_inpainted.append(seq_pos)
            else:
                # No structure at all for this residue
                residues_fully_inpainted.append(seq_pos)

        # Format residue ranges for output (similar to boltz2.py _format_residue_ranges)
        def format_residue_ranges(residue_list):
            if not residue_list:
                return ""
            residue_list = sorted(residue_list)
            ranges = []
            start = residue_list[0]
            end = residue_list[0]

            for i in range(1, len(residue_list)):
                if residue_list[i] == end + 1:
                    end = residue_list[i]
                else:
                    if start == end:
                        ranges.append(str(start))
                    else:
                        ranges.append(f"{start} - {end}")
                    start = residue_list[i]
                    end = residue_list[i]

            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start} - {end}")

            return ", ".join(ranges)

        # Log inpainting regions (matching boltz2.py format)
        if self.verbose:
            section("INPAINTING REGIONS (residue-level analysis)")
            detail(f"Total residues: {seq_length}")
            detail(f"Residues FULLY FIXED (all atoms have structure): {len(residues_fully_fixed)}")
            if residues_fully_fixed:
                fully_fixed_ranges = format_residue_ranges(residues_fully_fixed)
                detail(f"  Residues: {fully_fixed_ranges}")
            else:
                detail("  Residues: (none)")

            detail(f"Residues PARTIALLY FIXED (some atoms have structure, some need inpainting): {len(residues_partially_fixed)}")
            if residues_partially_fixed:
                for res_idx, fixed_atoms, total_atoms in residues_partially_fixed:
                    detail(f"  Residue {res_idx}: {fixed_atoms}/{total_atoms} atoms fixed")
            else:
                detail("  Residues: (none)")

            detail(f"Residues FULLY INPAINTED (no atoms have structure): {len(residues_fully_inpainted)}")
            if residues_fully_inpainted:
                fully_inpainted_ranges = format_residue_ranges(residues_fully_inpainted)
                detail(f"  Residues: {fully_inpainted_ranges}")
            else:
                detail("  Residues: (none)")

        # Calculate total atoms (used below for return value; prints only when verbose)
        # Convert 1-letter to 3-letter codes
        aa_one_to_three = {
            'A': 'ALA', 'C': 'CYS', 'D': 'ASP', 'E': 'GLU',
            'F': 'PHE', 'G': 'GLY', 'H': 'HIS', 'I': 'ILE',
            'K': 'LYS', 'L': 'LEU', 'M': 'MET', 'N': 'ASN',
            'P': 'PRO', 'Q': 'GLN', 'R': 'ARG', 'S': 'SER',
            'T': 'THR', 'V': 'VAL', 'W': 'TRP', 'Y': 'TYR'
        }

        # Count only ref_atoms (exclude hydrogen and other non-standard atoms)
        total_atoms_with_structure = 0
        total_expected_atoms = 0
        for seq_pos in range(1, seq_length + 1):
            # Get residue type from sequence (1-indexed to 0-indexed)
            if seq_pos <= len(final_sequence):
                aa_one = final_sequence[seq_pos - 1]
                aa_three = aa_one_to_three.get(aa_one, 'UNK')

                # For non-standard residues (X/UNK), use actual structure atoms as expected set
                if aa_three == 'UNK' and seq_pos in residue_atoms:
                    actual_type = residue_types.get(seq_pos, 'UNK')
                    if actual_type not in ref_atoms:
                        expected_atoms = residue_atoms[seq_pos]
                    else:
                        expected_atoms = set(ref_atoms.get(actual_type, ref_atoms.get("UNK", [])))
                else:
                    expected_atoms = set(ref_atoms.get(aa_three, ref_atoms.get("UNK", [])))
                total_expected_atoms += len(expected_atoms)

                # Count only ref_atoms that are present in structure
                if seq_pos in residue_atoms:
                    all_actual_atoms = residue_atoms[seq_pos]
                    actual_ref_atoms = all_actual_atoms & expected_atoms  # Intersection: only ref_atoms
                    total_atoms_with_structure += len(actual_ref_atoms)

        if self.verbose:
            detail(f"Total atoms WITH template structure: {total_atoms_with_structure} / {total_expected_atoms}")
            detail(f"Total atoms to be INPAINTED: {total_expected_atoms - total_atoms_with_structure} / {total_expected_atoms}")

        # Build metadata dict (matching boltz2.py inpainting_metadata format)
        metadata = {
            "fully_fixed_residues": residues_fully_fixed,
            "partially_fixed_residues": [
                {"residue": r[0], "fixed_atoms": r[1], "total_atoms": r[2]}
                for r in residues_partially_fixed
            ],
            "fully_inpainted_residues": residues_fully_inpainted,
            "total_atoms_with_structure": total_atoms_with_structure,
            "total_expected_atoms": total_expected_atoms,
        }

        # Find contiguous inpainting regions
        # Include both FULLY INPAINTED and PARTIALLY FIXED residues (both need inpainting)
        residues_needing_inpainting = set(residues_fully_inpainted)
        residues_needing_inpainting.update([r[0] for r in residues_partially_fixed])

        if residues_needing_inpainting:
            missing_regions = []
            current_gap_start = None

            for seq_pos in sorted(residues_needing_inpainting):
                if current_gap_start is None:
                    current_gap_start = seq_pos
                elif seq_pos == current_gap_start + 1:
                    # Continue current gap
                    pass
                else:
                    # Gap ended, start new one
                    missing_regions.append((current_gap_start, seq_pos - 1))
                    current_gap_start = seq_pos

            # Add final gap
            if current_gap_start is not None:
                missing_regions.append((current_gap_start, max(residues_needing_inpainting)))

            if missing_regions:
                largest_gap = max(missing_regions, key=lambda x: x[1] - x[0] + 1)
                return largest_gap, metadata

        return (0, 0), metadata

    def save_inpainting_metadata(
        self,
        all_inpainting_metadata: Dict[str, Dict[str, Any]],
        output_path: Path,
        chain_mapping: Optional[Dict[str, str]] = None,
    ) -> None:
        """Save per-chain inpainting metadata as JSON (matching boltz2 format).

        Args:
            all_inpainting_metadata: chain_id(label) -> metadata dict
            output_path: Path to write the JSON file
            chain_mapping: label_asym_id -> author_asym_id mapping. Allows
                downstream tools to recover original author chain IDs even
                though the CIF / YAML use label_asym_id as the primary key.
        """
        import numpy as np

        class _NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, (np.integer,)):
                    return int(obj)
                if isinstance(obj, (np.floating,)):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super().default(obj)

        data: Dict[str, Any] = {"chains": all_inpainting_metadata}
        if chain_mapping:
            # Only store label_to_author. author_to_label is not a proper
            # inverse when author IDs collide (e.g. 1TON where polymer chain
            # "A" and its ZN ligand both have author_asym_id "A"); callers
            # that need the reverse should iterate over label_to_author.
            data["chain_mapping"] = {
                "label_to_author": dict(chain_mapping),
            }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=4, cls=_NumpyEncoder)
        info(f"Saved inpainting metadata: {output_path.absolute()}")
