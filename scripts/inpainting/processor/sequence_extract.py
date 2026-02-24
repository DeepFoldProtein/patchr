"""SEQRES and atom-based sequence extraction from CIF."""
import sys
from typing import Dict, List, Optional

from ..constants import STANDARD_AA_THREE_LETTER


class SequenceExtractMixin:
    def extract_seqres_from_cif(self, chain_id: str) -> str:
        """Extract SEQRES sequence from CIF file for the specified chain using BioPython."""
        if not self.cif_content:
            raise ValueError("CIF content not loaded")

        # Synthetic chains share the same sequence as their original chain
        lookup_id = self._base_chain_id(chain_id)

        try:
            # Parse CIF file using BioPython
            cif_dict = self._get_cif_dict()

            # Get entity_poly_seq information
            if '_entity_poly_seq.mon_id' in cif_dict:
                mon_ids = cif_dict['_entity_poly_seq.mon_id']
                entity_ids = cif_dict['_entity_poly_seq.entity_id']

                # Get struct_asym to map chain to entity
                if '_struct_asym.id' in cif_dict and '_struct_asym.entity_id' in cif_dict:
                    asym_ids = cif_dict['_struct_asym.id']
                    asym_entity_ids = cif_dict['_struct_asym.entity_id']

                    # Find entity_id for our chain (use base ID for synthetic chains)
                    target_entity_id = None
                    for asym_id, entity_id in zip(asym_ids, asym_entity_ids):
                        if asym_id.upper() == lookup_id.upper():
                            target_entity_id = entity_id
                            break

                    if target_entity_id is None:
                        print(f"ERROR: Could not find entity mapping for chain {chain_id}", file=sys.stderr)
                        print(f"ERROR: Available chains: {asym_ids}", file=sys.stderr)
                        sys.exit(1)
                    
                    # Determine entity type for this chain
                    # First try to get from chain_entity_types (if already set)
                    # Otherwise, determine from actual atoms
                    entity_type = self.chain_entity_types.get(chain_id)
                    if entity_type is None:
                        # Determine from actual atoms for this chain
                        if '_atom_site.label_asym_id' in cif_dict and '_atom_site.label_comp_id' in cif_dict:
                            label_asym_ids = cif_dict['_atom_site.label_asym_id']
                            label_comp_ids = cif_dict['_atom_site.label_comp_id']
                            group_pdb = cif_dict.get('_atom_site.group_PDB', [])
                            
                            chain_residues = set()
                            for i, chain in enumerate(label_asym_ids):
                                if chain.upper() == chain_id.upper() and (i >= len(group_pdb) or group_pdb[i] == 'ATOM'):
                                    if i < len(label_comp_ids):
                                        chain_residues.add(label_comp_ids[i])
                            
                            dna_rna_residues = {'DA', 'DC', 'DG', 'DT', 'DI', 'A', 'C', 'G', 'T', 'U', 'I'}
                            protein_residues = {'ALA', 'CYS', 'ASP', 'GLU', 'PHE', 'GLY', 'HIS', 'ILE', 
                                                'LYS', 'LEU', 'MET', 'ASN', 'PRO', 'GLN', 'ARG', 'SER', 
                                                'THR', 'VAL', 'TRP', 'TYR'}
                            has_dna_rna = bool(chain_residues & dna_rna_residues)
                            has_protein = bool(chain_residues & protein_residues) or bool(
                                chain_residues - STANDARD_AA_THREE_LETTER - dna_rna_residues - {'HOH', 'H2O', 'WAT'}
                            )
                            if has_dna_rna and not has_protein:
                                if 'U' in chain_residues or any('R' in r for r in chain_residues if len(r) > 1 and 'R' in r):
                                    entity_type = 'rna'
                                else:
                                    entity_type = 'dna'
                            elif has_protein and not has_dna_rna:
                                entity_type = 'protein'
                            else:
                                entity_type = 'protein'  # Default
                        else:
                            entity_type = 'protein'  # Default
                    
                    # Extract sequence for this entity
                    # Protein codes
                    aa_codes = {
                        'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E',
                        'PHE': 'F', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
                        'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
                        'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S',
                        'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
                    }
                    
                    # DNA codes (3-letter to 1-letter)
                    dna_codes = {
                        'DA': 'A', 'DC': 'C', 'DG': 'G', 'DT': 'T',
                        'DI': 'I',  # Inosine
                        'A': 'A', 'C': 'C', 'G': 'G', 'T': 'T'  # Sometimes just single letter
                    }
                    
                    # RNA codes
                    rna_codes = {
                        'A': 'A', 'C': 'C', 'G': 'G', 'U': 'U',
                        'I': 'I'  # Inosine
                    }
                    
                    # Select appropriate code mapping
                    if entity_type == 'dna':
                        code_map = dna_codes
                    elif entity_type == 'rna':
                        code_map = rna_codes
                    else:
                        code_map = aa_codes
                    
                    sequence = []
                    seqres_entity_type = None  # Detect entity type from SEQRES residues
                    
                    # First pass: collect all mon_ids for this entity to detect type
                    entity_mon_ids = []
                    for mon_id, entity_id in zip(mon_ids, entity_ids):
                        if entity_id == target_entity_id:
                            entity_mon_ids.append(mon_id.upper())
                    
                    # Detect entity type from all residues (not just first)
                    # Check for RNA first (U is definitive)
                    has_u = any(mon_id == 'U' for mon_id in entity_mon_ids)
                    has_da_dt = any(mon_id in ['DA', 'DT'] for mon_id in entity_mon_ids)
                    has_protein = any(mon_id in ['ALA', 'CYS', 'ASP', 'GLU', 'PHE', 'GLY', 'HIS', 'ILE', 
                                                  'LYS', 'LEU', 'MET', 'ASN', 'PRO', 'GLN', 'ARG', 'SER', 
                                                  'THR', 'VAL', 'TRP', 'TYR'] for mon_id in entity_mon_ids)
                    
                    if has_protein:
                        seqres_entity_type = 'protein'
                    elif has_u:
                        seqres_entity_type = 'rna'  # U is definitive for RNA
                    elif has_da_dt:
                        seqres_entity_type = 'dna'  # DA/DT is definitive for DNA
                    elif any(mon_id in ['A', 'C', 'G', 'T', 'U', 'I'] and len(mon_id) == 1 for mon_id in entity_mon_ids):
                        # Single letter nucleic acids - check if U exists
                        if has_u:
                            seqres_entity_type = 'rna'
                        else:
                            seqres_entity_type = 'dna'  # Default to DNA if no U
                    else:
                        seqres_entity_type = 'protein'  # Default
                    
                    # Second pass: convert to sequence
                    # Also track non-standard residues with their sequence positions
                    seq_num = 0  # 1-based position in sequence
                    for mon_id, entity_id in zip(mon_ids, entity_ids):
                        if entity_id == target_entity_id:
                            seq_num += 1
                            mon_id_upper = mon_id.upper()
                            
                            # Convert 3-letter to 1-letter code
                            if seqres_entity_type == 'dna':
                                # DNA: DA, DC, DG, DT or sometimes just A, C, G, T
                                base = dna_codes.get(mon_id_upper, 'N')
                            elif seqres_entity_type == 'rna':
                                # RNA: A, C, G, U
                                base = rna_codes.get(mon_id_upper, 'N')
                            else:
                                # Protein: non-standard residues use X (parent from CCD in parse_non_standard_residues)
                                base = aa_codes.get(mon_id, 'X')
                            sequence.append(base)
                    
                    sequence_str = ''.join(sequence)
                    
                    # If SEQRES entity type doesn't match actual atom entity type, 
                    # we need to extract from atoms instead
                    # EXCEPTION: DNA/RNA mismatch is OK (they're both nucleic acids, just T vs U difference)
                    if seqres_entity_type and seqres_entity_type != entity_type:
                        # Allow DNA/RNA mismatch
                        both_nucleic_acids = (
                            {seqres_entity_type, entity_type} <= {'dna', 'rna'}
                        )
                        if not both_nucleic_acids:
                            print(f"WARNING: SEQRES entity type ({seqres_entity_type}) doesn't match atom entity type ({entity_type}) for chain {chain_id}")
                            print(f"Extracting sequence from atoms instead")
                            return self.extract_sequence_from_atoms(chain_id)
                        else:
                            print(f"INFO: SEQRES entity type ({seqres_entity_type}) and atom entity type ({entity_type}) are both nucleic acids, using SEQRES")
                    
                    print(f"Found SEQRES sequence for chain {chain_id} (entity {target_entity_id}, type: {entity_type}, length: {len(sequence_str)})")
                    return sequence_str
            
            # Fallback: extract from atoms if entity_poly_seq is not available
            print(f"WARNING: Could not extract SEQRES from entity_poly_seq for chain {chain_id}, extracting from atoms")
            return self.extract_sequence_from_atoms(chain_id)
            
        except Exception as e:
            print(f"ERROR: Error parsing CIF file: {e}", file=sys.stderr)
            sys.exit(1)
    
    def extract_sequence_from_atoms(self, chain_id: str) -> str:
        """Extract sequence from actual atom records when SEQRES is unavailable or incorrect."""
        if not self.cif_content:
            raise ValueError("CIF content not loaded")
        
        try:
            cif_dict = self._get_cif_dict()
            
            # Get atom records for this chain
            # Use label_asym_id (not auth_asym_id) to match with struct_asym.id
            if '_atom_site.label_asym_id' not in cif_dict or '_atom_site.label_comp_id' not in cif_dict:
                print(f"ERROR: Could not find atom records for chain {chain_id}", file=sys.stderr)
                sys.exit(1)
            
            label_asym_ids = cif_dict['_atom_site.label_asym_id']
            label_comp_ids = cif_dict['_atom_site.label_comp_id']
            label_seq_ids = cif_dict.get('_atom_site.label_seq_id', [])
            auth_seq_ids = cif_dict.get('_atom_site.auth_seq_id', [])
            group_pdb = cif_dict.get('_atom_site.group_PDB', [])
            
            # Collect residues for this chain
            # Include ATOM records AND HETATM that are non-standard residues (part of polymer sequence)
            residue_dict = {}  # seq_id -> comp_id
            
            for i, chain in enumerate(label_asym_ids):
                # Match case-insensitively
                if chain.upper() == chain_id.upper():
                    if i < len(label_comp_ids):
                        comp_id = label_comp_ids[i]
                        record_type = group_pdb[i] if i < len(group_pdb) else 'ATOM'
                        
                        # Include ATOM records OR HETATM that are non-standard (e.g. modifications)
                        is_non_standard = comp_id.upper() not in STANDARD_AA_THREE_LETTER
                        if record_type == 'ATOM' or (record_type == 'HETATM' and is_non_standard):
                            # Try label_seq_id first, fall back to auth_seq_id if label_seq_id is '?', '.', or missing
                            seq_id = None
                            if i < len(label_seq_ids):
                                label_seq_id = label_seq_ids[i]
                                label_seq_str = str(label_seq_id).strip()
                                if label_seq_str and label_seq_str not in ['?', '.', '']:
                                    seq_id = label_seq_id
                            
                            # If label_seq_id is not available, try auth_seq_id
                            if seq_id is None and i < len(auth_seq_ids):
                                auth_seq_id = auth_seq_ids[i]
                                auth_seq_str = str(auth_seq_id).strip()
                                if auth_seq_str and auth_seq_str not in ['?', '.', '']:
                                    seq_id = auth_seq_id
                            
                            if seq_id is not None:
                                try:
                                    seq_id_int = int(str(seq_id).strip())
                                    # Use the first occurrence of each residue
                                    if seq_id_int not in residue_dict:
                                        residue_dict[seq_id_int] = comp_id
                                except (ValueError, AttributeError):
                                    # Skip if seq_id cannot be converted to int
                                    pass
            
            # Determine entity type from actual residues found
            # Check what types of residues are present
            residue_types = set(residue_dict.values())
            dna_rna_residues = {'DA', 'DC', 'DG', 'DT', 'DI', 'A', 'C', 'G', 'T', 'U', 'I'}
            protein_residues = {'ALA', 'CYS', 'ASP', 'GLU', 'PHE', 'GLY', 'HIS', 'ILE', 
                                'LYS', 'LEU', 'MET', 'ASN', 'PRO', 'GLN', 'ARG', 'SER', 
                                'THR', 'VAL', 'TRP', 'TYR'}
            has_dna_rna = bool(residue_types & dna_rna_residues)
            has_protein = bool(residue_types & protein_residues) or bool(
                residue_types - STANDARD_AA_THREE_LETTER - dna_rna_residues - {'HOH', 'H2O', 'WAT'}
            )
            if has_dna_rna and not has_protein:
                # Check if DNA or RNA
                if 'U' in residue_types or any('R' in r for r in residue_types if len(r) > 1 and 'R' in r):
                    entity_type = 'rna'
                else:
                    entity_type = 'dna'
            elif has_protein and not has_dna_rna:
                entity_type = 'protein'
            else:
                # Fall back to chain_entity_types if available, otherwise default to protein
                entity_type = self.chain_entity_types.get(chain_id, 'protein')
            
            # Protein codes
            aa_codes = {
                'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E',
                'PHE': 'F', 'GLY': 'G', 'HIS': 'H', 'ILE': 'I',
                'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
                'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S',
                'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
            }
            
            # DNA codes
            dna_codes = {
                'DA': 'A', 'DC': 'C', 'DG': 'G', 'DT': 'T',
                'DI': 'I', 'A': 'A', 'C': 'C', 'G': 'G', 'T': 'T'
            }
            
            # RNA codes
            rna_codes = {
                'A': 'A', 'C': 'C', 'G': 'G', 'U': 'U', 'I': 'I'
            }
            
            # Select appropriate code mapping
            if entity_type == 'dna':
                code_map = dna_codes
            elif entity_type == 'rna':
                code_map = rna_codes
            else:
                code_map = aa_codes
            
            # Build sequence
            sequence = []
            for seq_id in sorted(residue_dict.keys()):
                comp_id = residue_dict[seq_id]
                comp_id_upper = comp_id.upper()
                
                one_letter = code_map.get(comp_id, 'X' if entity_type == 'protein' else 'N')
                sequence.append(one_letter)
            
            sequence_str = ''.join(sequence)
            print(f"Extracted sequence from atoms for chain {chain_id} (type: {entity_type}, length: {len(sequence_str)})")
            return sequence_str
            
        except Exception as e:
            print(f"ERROR: Error extracting sequence from atoms: {e}", file=sys.stderr)
            sys.exit(1)
    
