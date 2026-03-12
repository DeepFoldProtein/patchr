"""Residue mapping, sequence alignment, and UniProt filtering."""
import re
import sys
from typing import Dict, List, Optional, Tuple

from Bio import Align

from ..constants import STANDARD_AA_THREE_LETTER


class AlignmentMixin:
    def get_residue_mapping_dna_rna(self, atoms: List[Dict], seqres_sequence: str, final_sequence: str = None) -> Dict[int, int]:
        """
        Get mapping for DNA/RNA chains using sequential mapping.
        DNA/RNA structures are typically more straightforward than proteins.

        Args:
            atoms: List of atom dictionaries
            seqres_sequence: SEQRES sequence (from structure)
            final_sequence: Final custom sequence (if provided, may be longer/shorter than seqres)

        Returns:
            Dict mapping sequential structure index to sequence position (1-based)
        """
        # Group atoms by residue
        residue_info = {}

        for atom in atoms:
            auth_seq_id_str = str(atom['auth_seq_id']).strip()
            ins_code = atom.get('pdbx_PDB_ins_code', '?')
            if ins_code == '?':
                ins_code = ''

            import re
            # Try to extract number and optional insertion code from auth_seq_id
            # Pattern: optional minus sign, digits, optional letter (insertion code)
            match = re.match(r'^(-?\d+)([A-Za-z]?)$', auth_seq_id_str)
            if not match:
                # Fallback: just extract number
                match = re.match(r'^(-?\d+)', auth_seq_id_str)
                if not match:
                    continue
                auth_seq_id_base = int(match.group(1))
            else:
                auth_seq_id_base = int(match.group(1))
                # If insertion code is in auth_seq_id and pdbx_PDB_ins_code is empty, use it
                if not ins_code and match.group(2):
                    ins_code = match.group(2).upper()

            residue_key = (auth_seq_id_base, ins_code)

            if residue_key not in residue_info:
                residue_info[residue_key] = {
                    'atoms': [],
                    'auth_seq_id_base': auth_seq_id_base
                }

            residue_info[residue_key]['atoms'].append(atom)

        # Sort residues by auth_seq_id
        residue_keys = sorted(residue_info.keys(), key=lambda x: (x[0], x[1]))
        
        # Map structure residues to sequence positions
        # For DNA/RNA, map sequentially to the corresponding sequence positions
        residue_mapping = {}
        
        # Store for later use
        self._residue_index_to_key = {idx: key for idx, key in enumerate(residue_keys)}
        self._residue_info = residue_info
        
        # Check if structure covers full sequence or is partial
        num_structure_residues = len(residue_keys)
        seq_length = len(seqres_sequence)
        
        # If final_sequence is provided and different from seqres, we need to adjust mapping
        if final_sequence and final_sequence != seqres_sequence:
            final_seq_length = len(final_sequence)
            print(f"DEBUG: Custom sequence detected for DNA/RNA:")
            print(f"  - SEQRES length: {seq_length}")
            print(f"  - Final sequence length: {final_seq_length}")
            print(f"  - Structure residues: {num_structure_residues}")
            
            # Try to find where the seqres matches in the final sequence
            # This handles cases where bases are added at the beginning or end
            seqres_upper = seqres_sequence.upper().replace('N', 'X')  # Treat N as wildcard
            final_upper = final_sequence.upper().replace('N', 'X')
            
            # Find best match position using simple substring search
            best_offset = 0
            max_matches = 0
            
            # Try different offsets
            for offset in range(max(0, final_seq_length - seq_length + 1)):
                matches = 0
                for i in range(min(seq_length, final_seq_length - offset)):
                    if seqres_upper[i] == final_upper[offset + i] or seqres_upper[i] == 'X' or final_upper[offset + i] == 'X':
                        matches += 1
                if matches > max_matches:
                    max_matches = matches
                    best_offset = offset
            
            print(f"DEBUG: Best alignment offset: {best_offset} (matches: {max_matches}/{min(seq_length, final_seq_length)})")
            
            # Map structure residues with offset
            for idx, key in enumerate(residue_keys):
                # Structure residue at index 'idx' (0-based) maps to:
                # sequence position = best_offset + idx + 1 (converting to 1-based)
                residue_mapping[idx] = best_offset + idx + 1
            
            print(f"Structure residues will be mapped to sequence positions {best_offset + 1} to {best_offset + num_structure_residues}")
            
            # Print final mapping for debugging
            if residue_mapping:
                mapped_positions = sorted(residue_mapping.values())
                print(f"Mapped to sequence positions: {min(mapped_positions)} to {max(mapped_positions)}")
            print()
            
            return residue_mapping
            
        elif num_structure_residues < seq_length:
            # Structure is incomplete - detect where the gap is
            # Check if residues are numbered sequentially starting from 1
            first_residue_num = residue_keys[0][0] if residue_keys else 1
            last_residue_num = residue_keys[-1][0] if residue_keys else 0
            
            # If residues are numbered 1, 2, 3, ..., N where N < seq_length
            # This means there's a gap at the end or middle
            if first_residue_num == 1 and last_residue_num <= seq_length:
                # Map structure residues to their corresponding sequence positions
                # based on their original numbering
                for idx, key in enumerate(residue_keys):
                    original_num = key[0]
                    # Map to sequence position based on original residue number
                    residue_mapping[idx] = original_num
                
                print(f"Found {num_structure_residues} residues in structure out of {seq_length} in sequence")
                print(f"Structure residues numbered {first_residue_num} to {last_residue_num}")
                
                # Check for gaps in the middle
                expected_residues = set(range(first_residue_num, last_residue_num + 1))
                actual_residues = set(key[0] for key in residue_keys)
                missing_in_range = expected_residues - actual_residues
                
                if missing_in_range:
                    print(f"WARNING: Missing residues in structure: {sorted(missing_in_range)}")
                
                if last_residue_num < seq_length:
                    print(f"NOTE: Residues {last_residue_num + 1} to {seq_length} will be inpainted")
            else:
                # Fallback: use simple sequential mapping
                for idx, key in enumerate(residue_keys):
                    residue_mapping[idx] = idx + 1
                print(f"Found {num_structure_residues} residues in structure out of {seq_length} in sequence")
                print(f"Using sequential mapping (structure residue numbering doesn't start from 1)")
        else:
            # Structure covers full sequence or more
            # Simple sequential mapping starting from 1
            for idx, key in enumerate(residue_keys):
                residue_mapping[idx] = idx + 1
            print(f"Found {num_structure_residues} residues in structure")
        
        if residue_mapping:
            mapped_positions = sorted(residue_mapping.values())
            print(f"Mapped to sequence positions: {min(mapped_positions)} to {max(mapped_positions)}")
        print()
        
        return residue_mapping
    
    def get_residue_mapping(self, atoms: List[Dict], seqres_sequence: str, final_sequence: str, chain_id: Optional[str] = None) -> Dict[int, int]:
        """
        Get mapping from original residue numbers to sequence-based numbering (1-based).
        
        This maps structure residues to their positions in SEQRES (or UniProt if in UniProt mode).
        Uses Cα coordinates to determine structural order, ignoring insertion codes.
        For non-standard residues (e.g. ACE, PTR, DIP), uses parent one-letter from non_standard_residues
        so alignment includes them (e.g. PTR->Y) and they are not dropped from the output CIF.
        
        Args:
            atoms: List of atom dictionaries
            seqres_sequence: SEQRES sequence (for alignment)
            final_sequence: Final sequence to use (SEQRES or UniProt)
            chain_id: Optional chain ID for non-standard parent-one lookup (modification-containing chains)
        
        Returns:
            Dict mapping sequential structure index to sequence position (1-based)
        """
        # First, extract residues with their Cα coordinates for structural ordering
        # Group by (auth_seq_id_base, ins_code) to handle insertion codes properly
        residue_info = {}  # key: (auth_seq_id_base, ins_code) -> {type, ca_coords, atoms, first_atom_index}
        residue_first_seen = {}  # key -> index of first atom for this residue (for ordering)
        
        for atom_idx, atom in enumerate(atoms):
            # Extract base residue number and insertion code
            auth_seq_id_str = str(atom['auth_seq_id']).strip()
            ins_code = atom.get('pdbx_PDB_ins_code', '?')
            if ins_code == '?':
                ins_code = ''
            
            # Parse base number and optional insertion code from auth_seq_id
            import re
            # Try to extract number and optional insertion code from auth_seq_id
            # Pattern: optional minus sign, digits, optional letter (insertion code)
            match = re.match(r'^(-?\d+)([A-Za-z]?)$', auth_seq_id_str)
            if not match:
                # Fallback: just extract number
                match = re.match(r'^(-?\d+)', auth_seq_id_str)
                if not match:
                    continue
                auth_seq_id_base = int(match.group(1))
            else:
                auth_seq_id_base = int(match.group(1))
                # If insertion code is in auth_seq_id and pdbx_PDB_ins_code is empty, use it
                if not ins_code and match.group(2):
                    ins_code = match.group(2).upper()
            
            # Create unique key for this residue (including insertion code)
            residue_key = (auth_seq_id_base, ins_code)
            
            if residue_key not in residue_info:
                residue_info[residue_key] = {
                    'type': atom['label_comp_id'],
                    'ca_coords': None,
                    'atoms': [],
                    'auth_seq_id_base': auth_seq_id_base,
                    'ins_code': ins_code
                }
                # Record the index of the first atom for this residue (for ordering)
                residue_first_seen[residue_key] = atom_idx
            
            residue_info[residue_key]['atoms'].append(atom)
            
            # Store Cα coordinates for structural ordering (preferred)
            if atom['label_atom_id'] == 'CA':
                try:
                    residue_info[residue_key]['ca_coords'] = (
                        float(atom['Cartn_x']),
                        float(atom['Cartn_y']),
                        float(atom['Cartn_z'])
                    )
                except:
                    pass
        
        # Calculate center coordinates for each residue (average of all atoms)
        # Use Cα if available, otherwise use average of all atoms
        for residue_key, info in residue_info.items():
            coords_list = []
            ca_coords = None
            
            for atom in info['atoms']:
                try:
                    coords = (
                        float(atom['Cartn_x']),
                        float(atom['Cartn_y']),
                        float(atom['Cartn_z'])
                    )
                    coords_list.append(coords)
                    
                    # Prefer Cα if available
                    if atom['label_atom_id'] == 'CA':
                        ca_coords = coords
                except:
                    pass
            
            # Use Cα if available, otherwise use average of all atoms
            if ca_coords:
                info['center_coords'] = ca_coords
            elif coords_list:
                avg_x = sum(c[0] for c in coords_list) / len(coords_list)
                avg_y = sum(c[1] for c in coords_list) / len(coords_list)
                avg_z = sum(c[2] for c in coords_list) / len(coords_list)
                info['center_coords'] = (avg_x, avg_y, avg_z)
            else:
                info['center_coords'] = None
        
        # Sort residues by structural continuity (atom center distances)
        # Use distance-based ordering instead of just auth_seq_id
        def calc_distance(coord1, coord2):
            """Calculate Euclidean distance between two coordinates"""
            if coord1 is None or coord2 is None:
                return float('inf')
            return ((coord1[0] - coord2[0])**2 + 
                    (coord1[1] - coord2[1])**2 + 
                    (coord1[2] - coord2[2])**2)**0.5
        
        # Sort residues by the order they appear in the atom list (using first_atom_index)
        # This correctly handles insertion codes in their actual structural order (e.g. D, C, B, A)
        residue_keys = sorted(residue_info.keys(), key=lambda x: residue_first_seen[x])
        
        struct_residue_order = []  # List of sequential indices (0, 1, 2, ...)
        struct_residue_types = {}   # Sequential index -> residue type
        struct_residue_center = {}  # Sequential index -> center coords
        key_to_index = {}           # (auth_seq_id_base, ins_code) -> sequential index
        
        for idx, key in enumerate(residue_keys):
            struct_residue_order.append(idx)
            struct_residue_types[idx] = residue_info[key]['type']
            struct_residue_center[idx] = residue_info[key]['center_coords']
            key_to_index[key] = idx
        
        # Store mapping from sequential index to original residue info for later use
        self._residue_index_to_key = {idx: key for idx, key in enumerate(residue_keys)}
        self._residue_info = residue_info
 
        # Convert to 1-letter sequence (use non-standard parent_one so modification positions are aligned, not dropped)
        aa_three_to_one = {
            'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E',
            'PHE': 'F', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
            'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
            'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S',
            'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
        }
        struct_seq_list = []
        for idx in struct_residue_order:
            comp_id = struct_residue_types[idx]
            one_letter = aa_three_to_one.get(comp_id)
            if one_letter is None and chain_id and chain_id in self.non_standard_residues:
                key = self._residue_index_to_key[idx]
                info = residue_info.get(key, {})
                atoms_list = info.get('atoms', [])
                label_seq_id = atoms_list[0].get('label_seq_id') if atoms_list else None
                if label_seq_id is not None:
                    try:
                        pos = int(label_seq_id)
                    except (TypeError, ValueError):
                        pos = None
                    if pos is not None and pos in self.non_standard_residues[chain_id]:
                        one_letter = self.non_standard_residues[chain_id][pos].get('parent_one')
            if one_letter is None:
                one_letter = 'X'
            struct_seq_list.append(one_letter)
        struct_seq = ''.join(struct_seq_list)
        
        # Always use alignment-based method to handle insertion codes and structural order properly
        # No longer try to use auth_seq_id directly as it may have insertion codes
        print(f"Aligning structure ({len(struct_residue_order)} residues) to SEQRES ({len(seqres_sequence)} residues)")

        # Short-circuit: if both sequences are entirely non-standard ('X') with same length,
        # alignment is meaningless (e.g. branched carbohydrate chains like NAG-NAG).
        # Use simple 1:1 sequential mapping.
        if (len(struct_residue_order) == len(seqres_sequence)
                and all(c == 'X' for c in struct_seq)
                and all(c == 'X' for c in seqres_sequence)):
            residue_mapping = {idx: idx + 1 for idx in struct_residue_order}
            print(f"Using 1:1 sequential mapping for all-non-standard chain ({len(residue_mapping)} residues)")
            if residue_mapping:
                mapped_positions = sorted(residue_mapping.values())
                print(f"Mapped to sequence positions: {min(mapped_positions)} to {max(mapped_positions)}")
                print(f"Original residue range: {struct_residue_order[0]} to {struct_residue_order[-1]}")
            print()
            return residue_mapping

        # Use Bio.Align.PairwiseAligner for local alignment (same as boltz2)
        aligner = Align.PairwiseAligner(scoring="blastp")
        aligner.mode = "local"

        alignments = list(aligner.align(struct_seq, seqres_sequence))
        window_offset = 0  # Track if window alignment was used

        if not alignments:
            print("ERROR: Alignment failed, cannot create mapping")
            return {}
        
        # Evaluate multiple alignment candidates using original PDB auth_seq_id as hint
        
        def evaluate_alignment(alignment, index):
            """Evaluate alignment quality using multiple criteria"""
            coords = alignment.coordinates
            struct_start = int(coords[0][0])
            struct_end = int(coords[0][-1])
            seqres_start = int(coords[1][0])
            seqres_end = int(coords[1][-1])
            
            # 1. Alignment score (from BioPython)
            align_score = alignment.score
            
            # 2. Coverage: how many structure residues are matched
            struct_matched = struct_end - struct_start
            coverage_ratio = struct_matched / len(struct_seq) if len(struct_seq) > 0 else 0
            
            # 3. Continuity: structure should be matched from start (0) to end (len)
            starts_from_beginning = (struct_start == 0)
            ends_at_end = (struct_end == len(struct_seq))
            
            # 4. Position hint: compare with original PDB auth_seq_id
            # First structure residue's auth_seq_id_base (from residue_keys ordered by file appearance)
            # Note: struct_residue_order is [0,1,2,...] (sequential indices), NOT auth_seq_ids
            first_auth_seq_id = residue_keys[0][0] if residue_keys else 0
            # Expected SEQRES position based on PDB numbering (as hint, may be unreliable)
            expected_seqres_pos = first_auth_seq_id - 1  # Convert to 0-based
            # How close is the alignment to the expected position?
            position_diff = abs(seqres_start - expected_seqres_pos)
            
            # 5. Verify residue type match
            type_matches = 0
            type_mismatches = 0
            for i in range(struct_start, min(struct_end, len(struct_seq))):
                struct_res = struct_seq[i]
                seqres_idx = seqres_start + (i - struct_start)
                if seqres_idx < len(seqres_sequence):
                    seqres_res = seqres_sequence[seqres_idx]
                    if struct_res == seqres_res:
                        type_matches += 1
                    else:
                        type_mismatches += 1
            
            match_ratio = type_matches / (type_matches + type_mismatches) if (type_matches + type_mismatches) > 0 else 0
            
            # Combined score calculation
            combined_score = align_score
            
            # Heavy bonus for full coverage
            if starts_from_beginning and ends_at_end:
                combined_score += 1000
            elif starts_from_beginning:
                combined_score += 500
            
            # Bonus for high match ratio
            combined_score += match_ratio * 100
            
            # Penalty for position difference
            # Use auth_seq_id as a strong hint - penalize ANY deviation
            # But scale it reasonably as PDB numbering can sometimes be off
            # For small deviations (< 10), apply moderate penalty
            # For larger deviations, apply stronger penalty
            if position_diff > 0:
                if position_diff <= 10:
                    combined_score -= position_diff * 10  # 10 points per residue difference
                else:
                    combined_score -= 100 + (position_diff - 10) * 5  # Stronger penalty for large deviations
            
            return {
                'index': index,
                'alignment': alignment,
                'align_score': align_score,
                'combined_score': combined_score,
                'coverage_ratio': coverage_ratio,
                'starts_from_beginning': starts_from_beginning,
                'ends_at_end': ends_at_end,
                'struct_start': struct_start,
                'struct_end': struct_end,
                'seqres_start': seqres_start,
                'seqres_end': seqres_end,
                'position_diff': position_diff,
                'type_matches': type_matches,
                'type_mismatches': type_mismatches,
                'match_ratio': match_ratio
            }
        
        # Evaluate top alignments (limit to top 10 to avoid excessive computation)
        top_n = min(10, len(alignments))
        evaluated = [evaluate_alignment(alignments[i], i) for i in range(top_n)]
        
        # Sort by combined score (higher is better)
        evaluated.sort(key=lambda x: x['combined_score'], reverse=True)
        
        
        # Select best alignment
        best = evaluated[0]
        result = best['alignment']
        coordinates = result.coordinates
        
        struct_start = best['struct_start']
        struct_end = best['struct_end']
        seqres_start = best['seqres_start']
        seqres_end = best['seqres_end']
        
        # Build aligned sequences from the alignment
        aligned_struct = result[0]
        aligned_seqres = result[1]
        score = result.score
        
        # Build mapping: structure position -> SEQRES position
        # Use coordinates from Bio.Align.PairwiseAligner for accurate mapping
        struct_to_seqres_map = {}
        debug_mappings = []
        
        # Use coordinates for accurate mapping
        # coordinates[0] = structure sequence positions (0-based)
        # coordinates[1] = SEQRES positions (0-based)
        struct_coords = coordinates[0]
        seqres_coords = coordinates[1]
        
        # Build mapping using coordinates
        # struct_coords are 0-based indices in struct_seq (sequential order)
        # Map sequential index (0-based in struct_residue_order) -> SEQRES position (1-based)
        struct_to_seqres_map = {}  # key: sequential index, value: SEQRES position (1-based)
        
        for i in range(len(struct_coords) - 1):
            struct_start_coord = struct_coords[i]
            struct_end_coord = struct_coords[i + 1]
            seqres_start_coord = seqres_coords[i] + window_offset
            seqres_end_coord = seqres_coords[i + 1] + window_offset
            
            # Map each position in this segment
            for j in range(struct_start_coord, struct_end_coord):
                if j < len(struct_residue_order):
                    seq_idx = struct_residue_order[j]  # Sequential index (0-based)
                    
                    # Calculate corresponding SEQRES position
                    if struct_end_coord > struct_start_coord:
                        seqres_pos_in_segment = j - struct_start_coord
                        seqres_pos_0based = seqres_start_coord + seqres_pos_in_segment
                    else:
                        seqres_pos_0based = seqres_start_coord
                    
                    seqres_position = seqres_pos_0based + 1  # Convert to 1-based
                    struct_to_seqres_map[seq_idx] = seqres_position
        
        # Modification chains (ACE, PTR, DIP): use 1:1 mapping when lengths match so all atoms are kept
        # For synthetic chains (e.g. A_op2), look up using the base chain ID
        _mods_lookup_id = self._base_chain_id(chain_id) if chain_id else chain_id
        if (chain_id and _mods_lookup_id in getattr(self, '_modifications_from_entity_poly', {}) and
                len(struct_residue_order) == len(seqres_sequence)):
            if len(struct_to_seqres_map) < len(struct_residue_order) or struct_seq == seqres_sequence:
                struct_to_seqres_map = {struct_residue_order[i]: i + 1 for i in range(len(struct_residue_order))}
                print(f"Using 1:1 sequential mapping for modification chain {chain_id} ({len(struct_to_seqres_map)} residues)")
        
        # Post-process mapping to fix issues with repetitive sequences
        # Use structural distance to validate and correct alignment results
        def calc_distance(coord1, coord2):
            """Calculate Euclidean distance between two coordinates"""
            if coord1 is None or coord2 is None:
                return float('inf')
            return ((coord1[0] - coord2[0])**2 + 
                    (coord1[1] - coord2[1])**2 + 
                    (coord1[2] - coord2[2])**2)**0.5
        
        continuity_issues = []
        sorted_indices = sorted(struct_to_seqres_map.keys())
        reverse_map = {v: k for k, v in struct_to_seqres_map.items()}
        
        # Typical Cα-Cα distance in proteins is ~3.8 Å
        # If two consecutive structure residues are close (< 6 Å), they should map to nearby SEQRES positions
        MAX_CONSECUTIVE_DISTANCE = 6.0
        
        for i in range(len(sorted_indices) - 1):
            idx_1 = sorted_indices[i]
            idx_2 = sorted_indices[i + 1]
            seqres_pos_1 = struct_to_seqres_map[idx_1]
            seqres_pos_2 = struct_to_seqres_map[idx_2]
            
            # Check structural distance
            coord_1 = struct_residue_center.get(idx_1)
            coord_2 = struct_residue_center.get(idx_2)
            struct_distance = calc_distance(coord_1, coord_2)
            
            # Sequential indices should be consecutive (idx_2 = idx_1 + 1)
            seqres_gap = seqres_pos_2 - seqres_pos_1
            
            # If structure residues are structurally close, they should map to consecutive SEQRES positions
            if struct_distance < MAX_CONSECUTIVE_DISTANCE and seqres_gap != 1:
                # These residues are structurally consecutive but not consecutive in SEQRES mapping
                struct_res_1 = aa_three_to_one.get(struct_residue_types[idx_1], 'X')
                struct_res_2 = aa_three_to_one.get(struct_residue_types[idx_2], 'X')
                
                # Priority 1: Try to place idx_2 immediately after idx_1 (consecutive)
                # Only if residue type matches
                next_pos = seqres_pos_1 + 1
                if next_pos <= len(seqres_sequence):
                    seqres_res_next = seqres_sequence[next_pos - 1]
                    if struct_res_2 == seqres_res_next and next_pos not in reverse_map:
                        # Perfect match at consecutive position
                        continuity_issues.append({
                            'seq_idx': idx_2,
                            'old_seqres': seqres_pos_2,
                            'new_seqres': next_pos,
                            'residue': struct_res_2,
                            'reason': f'Structurally consecutive residues (distance {struct_distance:.1f}Å) must map consecutively'
                        })
                        continue
                
                # Priority 2: If consecutive mapping is not possible, try nearby positions
                if seqres_gap > 1:
                    found_better = False
                    for nearby_pos in range(seqres_pos_1 + 1, min(seqres_pos_2, seqres_pos_1 + 10)):
                        if nearby_pos <= len(seqres_sequence):
                            seqres_res = seqres_sequence[nearby_pos - 1]
                            if struct_res_2 == seqres_res:
                                # Found a match closer to previous residue!
                                if nearby_pos not in reverse_map:  # Not already mapped
                                    continuity_issues.append({
                                        'seq_idx': idx_2,
                                        'old_seqres': seqres_pos_2,
                                        'new_seqres': nearby_pos,
                                        'residue': struct_res_2,
                                        'reason': f'Structurally consecutive residues (distance {struct_distance:.1f}Å, gap {seqres_gap}) should map closer'
                                    })
                                    found_better = True
                                    break
        
        # Apply fixes iteratively until no more issues found
        total_fixed = 0
        iteration = 0
        max_iterations = 5
        
        while continuity_issues and iteration < max_iterations:
            iteration += 1
            total_fixed += len(continuity_issues)
            
            if iteration == 1:
                print(f"Note: Fixing {len(continuity_issues)} mapping issue(s) caused by repetitive sequences")
            else:
                print(f"  Iteration {iteration}: Fixing {len(continuity_issues)} more issue(s)")
            
            for issue in continuity_issues:
                print(f"  - Seq idx {issue['seq_idx']} ({issue['residue']}): {issue['old_seqres']} -> {issue['new_seqres']} ({issue['reason']})")
            
            # Apply fixes
            for issue in continuity_issues:
                struct_to_seqres_map[issue['seq_idx']] = issue['new_seqres']
            
            # Rebuild reverse map
            reverse_map = {v: k for k, v in struct_to_seqres_map.items()}
            
            # Check again for more issues
            continuity_issues = []
            for i in range(len(sorted_indices) - 1):
                idx_1 = sorted_indices[i]
                idx_2 = sorted_indices[i + 1]
                seqres_pos_1 = struct_to_seqres_map[idx_1]
                seqres_pos_2 = struct_to_seqres_map[idx_2]
                
                # Check structural distance
                coord_1 = struct_residue_center.get(idx_1)
                coord_2 = struct_residue_center.get(idx_2)
                struct_distance = calc_distance(coord_1, coord_2)
                
                seqres_gap = seqres_pos_2 - seqres_pos_1
                
                if struct_distance < MAX_CONSECUTIVE_DISTANCE and seqres_gap > 1:
                    struct_res_2 = aa_three_to_one.get(struct_residue_types[idx_2], 'X')
                    
                    for nearby_pos in range(seqres_pos_1 + 1, min(seqres_pos_2, seqres_pos_1 + 10)):
                        if nearby_pos <= len(seqres_sequence):
                            seqres_res = seqres_sequence[nearby_pos - 1]
                            if struct_res_2 == seqres_res:
                                if nearby_pos not in reverse_map:
                                    continuity_issues.append({
                                        'seq_idx': idx_2,
                                        'old_seqres': seqres_pos_2,
                                        'new_seqres': nearby_pos,
                                        'residue': struct_res_2,
                                        'reason': f'Structurally consecutive residues (distance {struct_distance:.1f}Å, gap {seqres_gap}) should map closer'
                                    })
                                    break
        
        if total_fixed > 0:
            print(f"Total fixed: {total_fixed} mapping issue(s)")
            print()
        
        
        # If UniProt mode, interactive sequence, or custom sequence, map SEQRES positions to target sequence positions
        _has_custom_seq = chain_id and chain_id in getattr(self, 'manual_sequences', {})
        if (self.uniprot_mode or self.interactive_sequence or _has_custom_seq) and final_sequence != seqres_sequence:
            sequence_type = "custom sequence" if _has_custom_seq else ("manually entered sequence" if self.interactive_sequence else "UniProt sequence")
            
            # Check if SEQRES is an exact substring of target sequence
            # This is common when target is the full sequence and SEQRES is a fragment
            seqres_to_target_map = {}
            substring_match = False
            
            seqres_start_in_target = final_sequence.find(seqres_sequence)
            if seqres_start_in_target >= 0:
                # SEQRES is an exact substring! Use direct mapping
                print(f"Note: SEQRES is an exact substring of {sequence_type} (position {seqres_start_in_target + 1}-{seqres_start_in_target + len(seqres_sequence)})")
                for i in range(len(seqres_sequence)):
                    seqres_pos_1based = i + 1  # SEQRES position (1-based)
                    target_pos_1based = seqres_start_in_target + i + 1  # Target position (1-based)
                    seqres_to_target_map[seqres_pos_1based] = target_pos_1based
                substring_match = True
            else:
                # Not an exact substring, need alignment
                alignment = self.align_sequences(seqres_sequence, final_sequence)
                
                if alignment is None:
                    print(f"WARNING: Could not align SEQRES with {sequence_type}, using SEQRES positions")
                    return struct_to_seqres_map
                
                aligned_seqres, aligned_target, score, begin, end = alignment
                
                # Build mapping: SEQRES position -> target sequence position
                # Follow align_cif_to_uniprot.py approach exactly
                seqres_pos = 0  # 0-based index in seqres_sequence (original, not aligned)
                target_pos = 0  # 0-based index in final_sequence (target, original, not aligned)
            
            # Only do alignment-based mapping if not substring match
            if not substring_match:
                for seqres_aa, target_aa in zip(aligned_seqres, aligned_target):
                    # Follow align_cif_to_uniprot.py logic exactly:
                    # if target_aa != '-': increment target_pos, then check seqres_aa
                    if target_aa != '-':
                        target_pos += 1  # Increment target position first
                        if seqres_aa != '-':
                            # Both have amino acids - map SEQRES position to target position
                            seqres_pos += 1  # Increment SEQRES position
                            seqres_position = seqres_pos  # Already 1-based (we incremented before)
                            target_position = target_pos  # Already 1-based (we incremented before)
                            seqres_to_target_map[seqres_position] = target_position
                    elif seqres_aa != '-':
                        # Gap in target but not in SEQRES
                        seqres_pos += 1  # Increment SEQRES position only
            
            # Combine mappings: structure -> SEQRES -> target sequence
            residue_mapping = {}
            for auth_seq_id, seqres_pos in struct_to_seqres_map.items():
                if seqres_pos in seqres_to_target_map:
                    residue_mapping[auth_seq_id] = seqres_to_target_map[seqres_pos]
                # If SEQRES position not mapped to target, skip it (will be filtered later)
        else:
            # Not UniProt/interactive mode, or target == SEQRES, use SEQRES positions directly
            residue_mapping = struct_to_seqres_map
        
        print(f"Found {len(residue_mapping)} residues in structure")
        if residue_mapping:
            mapped_positions = sorted(residue_mapping.values())
            print(f"Mapped to sequence positions: {min(mapped_positions)} to {max(mapped_positions)}")
            print(f"Original residue range: {min(struct_residue_order)} to {max(struct_residue_order)}")
        print()
        
        return residue_mapping
    
    def align_sequences(self, seq1: str, seq2: str):
        """
        Align two sequences using Bio.Align.PairwiseAligner (semi-global alignment).
        Uses semi-global mode where end gaps are not penalized, which is appropriate
        when aligning a shorter sequence (SEQRES) to a longer sequence (full sequence).
        
        Returns:
            Tuple of (aligned_seq1, aligned_seq2, score, begin, end)
        """
        aligner = Align.PairwiseAligner(scoring="blastp")
        aligner.mode = "global"
        
        # Semi-global alignment: no penalty for end gaps in seq1 (SEQRES)
        # This allows SEQRES to align to the corresponding region in the full sequence
        # without being penalized for not covering the entire target sequence
        aligner.target_end_gap_score = 0.0  # No penalty for gaps at the end of target (seq2)
        aligner.target_internal_open_gap_score = -10.0  # Penalty for internal gaps
        aligner.target_internal_extend_gap_score = -0.5
        aligner.query_end_gap_score = 0.0  # No penalty for gaps at the end of query (seq1)
        aligner.query_internal_open_gap_score = -10.0
        aligner.query_internal_extend_gap_score = -0.5
        
        alignments = list(aligner.align(seq1, seq2))
        if not alignments:
            return None
        
        result = alignments[0]
        aligned_seq1 = result[0]
        aligned_seq2 = result[1]
        score = result.score
        
        # Get coordinates for begin/end
        coordinates = result.coordinates
        begin = (int(coordinates[0][0]), int(coordinates[1][0]))
        end = (int(coordinates[0][-1]), int(coordinates[1][-1]))
        
        return (aligned_seq1, aligned_seq2, score, begin, end)
    
    def filter_atoms_by_uniprot_sequence(self, atoms: List[Dict], residue_mapping: Dict[int, int], final_sequence: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Filter out atoms from residues that don't match target sequence (UniProt or manually entered).
        Uses sequence alignment to map structure residues to target sequence positions.
        
        Args:
            atoms: List of atom dictionaries
            residue_mapping: Mapping from sequential index to SEQRES/target position
            final_sequence: Final sequence to use (UniProt sequence or manually entered sequence)
            
        Returns:
            Tuple of (filtered_atoms, removed_residues_info)
        """
        # Skip filtering if not in UniProt mode, not using interactive sequence,
        # and no custom sequences provided (i.e., using SEQRES sequence directly)
        _has_any_custom = bool(getattr(self, 'manual_sequences', {}))
        if not (self.uniprot_mode or self.interactive_sequence or _has_any_custom) or not final_sequence:
            return atoms, []
        
        # 3-letter to 1-letter code mapping
        aa_three_to_one = {
            'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E',
            'PHE': 'F', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
            'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
            'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S',
            'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y',
            'UNK': 'X'
        }
        
        # Build reverse mapping: (auth_seq_id_base, ins_code) -> sequential_index -> SEQRES position
        key_to_index = {}
        index_to_seqres = {}
        for seq_idx, seqres_pos in residue_mapping.items():
            if hasattr(self, '_residue_index_to_key'):
                key = self._residue_index_to_key[seq_idx]
                key_to_index[key] = seq_idx
                index_to_seqres[seq_idx] = seqres_pos
        
        # Build structure sequence from atoms in order
        # First, collect all residues with their types
        # Only include residues that are in residue_mapping (successfully aligned)
        residue_types = {}  # sequential_index -> residue_type
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
            
            # Skip residues that weren't mapped (likely due to alignment issues)
            if residue_key not in key_to_index:
                continue
            
            seq_idx = key_to_index[residue_key]
            new_seq_id = index_to_seqres[seq_idx]
            if new_seq_id not in residue_types:
                residue_types[new_seq_id] = atom['label_comp_id']
        
        # Get ordered list of residues (sorted by new_seq_id)
        residue_order = sorted(residue_types.keys())
        
        # Convert to 1-letter sequence in order
        struct_seq = ''.join([aa_three_to_one.get(residue_types[pos], 'X') for pos in residue_order])
        
        # Target sequence (UniProt or manually entered) is ground truth
        target_seq = final_sequence
        
        sequence_type = "manually entered sequence" if self.interactive_sequence else "UniProt sequence"
        print(f"Structure sequence length: {len(struct_seq)}")
        print(f"Target sequence length: {len(target_seq)} ({sequence_type})")
        print("Aligning sequences...")
        
        # Align sequences
        alignment = self.align_sequences(struct_seq, target_seq)
        if not alignment:
            print("WARNING: Could not align sequences, skipping filtering")
            return atoms, []
        
        aligned_struct, aligned_target, score, begin, end = alignment
        
        print(f"Alignment score: {score}")
        print(f"Aligned length: {len(aligned_struct)}")
        
        # Count matches and mismatches for debugging
        matches = sum(1 for a, b in zip(aligned_struct, aligned_target) if a == b and a != '-')
        mismatches = sum(1 for a, b in zip(aligned_struct, aligned_target) if a != b and a != '-' and b != '-')
        print(f"Matches: {matches}, Mismatches: {mismatches}")
        
        # Build mapping: structure position -> target sequence position
        struct_to_target_map = {}
        target_to_struct_map = {}
        
        struct_pos_in_seq = 0  # 0-based index in struct_seq (original sequence, not aligned)
        target_pos_in_seq = 0  # 0-based index in target_seq (original sequence, not aligned)
        
        for i, (struct_aa, target_aa) in enumerate(zip(aligned_struct, aligned_target)):
            # Track positions in original sequences (before alignment)
            if struct_aa != '-':
                # This position corresponds to a structure residue
                if target_aa != '-':
                    # Both have amino acids - map them
                    # struct_pos_in_seq is the index in the original struct_seq
                    # residue_order[struct_pos_in_seq] gives the actual residue number
                    if struct_pos_in_seq < len(residue_order):
                        struct_residue_idx = residue_order[struct_pos_in_seq]  # Get residue number from ordered list
                        target_pos_1based = target_pos_in_seq + 1  # Convert to 1-based
                        struct_to_target_map[struct_residue_idx] = target_pos_1based
                        target_to_struct_map[target_pos_1based] = struct_residue_idx
                struct_pos_in_seq += 1
            
            if target_aa != '-':
                target_pos_in_seq += 1
        
        # Find mismatched residues
        mismatched_residues = []
        mismatched_seqres_positions = set()  # Track which SEQRES positions to remove
        filtered_atoms = []
        
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
            
            # Skip residues that weren't mapped (likely due to alignment issues)
            if residue_key not in key_to_index:
                # Mark as removed
                new_seq_id = None
                if new_seq_id not in mismatched_seqres_positions:
                    mismatched_seqres_positions.add(new_seq_id)
                    mismatched_residues.append({
                        'residue': f"{auth_seq_id_base}{ins_code if ins_code else ''}",
                        'uniprot_pos': None,
                        'struct_type': atom['label_comp_id'],
                        'struct_aa': aa_three_to_one.get(atom['label_comp_id'], 'X'),
                        'uniprot_aa': '-'
                    })
                continue
            
            seq_idx = key_to_index[residue_key]
            new_seq_id = index_to_seqres[seq_idx]
            
            # Get residue type from structure
            struct_residue_type = residue_types.get(new_seq_id, 'UNK')
            struct_aa = aa_three_to_one.get(struct_residue_type, 'X')
            
            # Map to target sequence position
            if new_seq_id in struct_to_target_map:
                target_pos = struct_to_target_map[new_seq_id]
                
                # Get expected amino acid from target sequence
                if 1 <= target_pos <= len(target_seq):
                    target_aa = target_seq[target_pos - 1]
                    
                    # Check if they match (case-insensitive)
                    if struct_aa.upper() == target_aa.upper():
                        # Match - keep this atom
                        filtered_atoms.append(atom)
                    else:
                        # Mismatch - mark this residue for removal
                        if new_seq_id not in mismatched_seqres_positions:
                            mismatched_seqres_positions.add(new_seq_id)
                            mismatched_residues.append({
                                'residue': new_seq_id,
                                'uniprot_pos': target_pos,  # Keep key name for compatibility
                                'struct_type': struct_residue_type,
                                'struct_aa': struct_aa,
                                'uniprot_aa': target_aa  # Keep key name for compatibility
                            })
                        # Skip this atom
                else:
                    # Target position out of range - remove
                    if new_seq_id not in mismatched_seqres_positions:
                        mismatched_seqres_positions.add(new_seq_id)
                        mismatched_residues.append({
                            'residue': new_seq_id,
                            'uniprot_pos': target_pos,  # Keep key name for compatibility
                            'struct_type': struct_residue_type,
                            'struct_aa': struct_aa,
                            'uniprot_aa': 'OUT_OF_RANGE'
                        })
            else:
                # Not mapped to target sequence (gap in alignment) - remove
                if new_seq_id not in mismatched_seqres_positions:
                    mismatched_seqres_positions.add(new_seq_id)
                    mismatched_residues.append({
                        'residue': new_seq_id,
                        'uniprot_pos': None,
                        'struct_type': struct_residue_type,
                        'struct_aa': struct_aa,
                        'uniprot_aa': '-'
                    })
                # Skip this atom
        
        return filtered_atoms, mismatched_residues
    
