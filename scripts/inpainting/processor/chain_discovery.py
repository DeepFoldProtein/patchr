"""Polymer and ligand chain discovery from CIF struct_asym / entity tables."""
import sys
from typing import Dict, List, Tuple

from ..constants import STANDARD_AA_THREE_LETTER


class ChainDiscoveryMixin:
    def get_all_polymer_chains(self, include_all_copies: bool = True) -> Tuple[List[str], Dict[str, str]]:
        """Get all polymer chains (protein/DNA/RNA) from CIF file, excluding water.
        
        When include_all_copies is True (default for ALL/ALL-COPIES), returns every polymer
        chain (e.g. 1A1B → A, B, C, D). When False, returns only one chain per entity.
        
        Args:
            include_all_copies: If True (default), include all chains. If False, one per entity.
        
        Returns:
            Tuple of (chain_ids, chain_entity_types) where chain_entity_types maps chain_id to 'protein', 'dna', or 'rna'
        """
        if not self.cif_content:
            raise ValueError("CIF content not loaded")
        
        try:
            # Parse CIF file using BioPython
            cif_dict = self._get_cif_dict()
            
            # Get struct_asym to map chain to entity
            if '_struct_asym.id' not in cif_dict or '_struct_asym.entity_id' not in cif_dict:
                print("ERROR: Could not find struct_asym information", file=sys.stderr)
                sys.exit(1)
            
            asym_ids = cif_dict['_struct_asym.id']
            asym_entity_ids = cif_dict['_struct_asym.entity_id']
            
            # Get entity types to filter out water
            entity_types = {}
            if '_entity.type' in cif_dict and '_entity.id' in cif_dict:
                entity_ids_list = cif_dict['_entity.id']
                entity_types_list = cif_dict['_entity.type']
                
                # Handle both list and single value cases
                if isinstance(entity_ids_list, str):
                    entity_ids_list = [entity_ids_list]
                if isinstance(entity_types_list, str):
                    entity_types_list = [entity_types_list]
                
                for entity_id, entity_type in zip(entity_ids_list, entity_types_list):
                    entity_types[entity_id] = entity_type
            
            # Get entity_poly types and nstd_monomer (non-standard/modification-containing chains, e.g. 1A1B C,D)
            entity_poly_types = {}
            entity_nstd_monomer = {}  # entity_id -> True if nstd_monomer=yes (modification-containing protein)
            if '_entity_poly.entity_id' in cif_dict and '_entity_poly.type' in cif_dict:
                poly_entity_ids = cif_dict['_entity_poly.entity_id']
                poly_types = cif_dict['_entity_poly.type']
                nstd_monomer_list = cif_dict.get('_entity_poly.nstd_monomer', [])
                if isinstance(poly_entity_ids, str):
                    poly_entity_ids = [poly_entity_ids]
                if isinstance(poly_types, str):
                    poly_types = [poly_types]
                if isinstance(nstd_monomer_list, str):
                    nstd_monomer_list = [nstd_monomer_list]
                for i, entity_id in enumerate(poly_entity_ids):
                    entity_poly_types[entity_id] = poly_types[i].lower() if i < len(poly_types) else ''
                    entity_nstd_monomer[entity_id] = (i < len(nstd_monomer_list) and
                                                     str(nstd_monomer_list[i]).strip().lower() == 'yes')
            
            # Also check entity_poly to identify polymer chains
            polymer_entity_ids = set()
            if '_entity_poly.entity_id' in cif_dict:
                poly_entity_ids = cif_dict['_entity_poly.entity_id']
                if isinstance(poly_entity_ids, str):
                    poly_entity_ids = [poly_entity_ids]
                polymer_entity_ids = set(poly_entity_ids)
            
            # Collect polymer chains (protein/DNA/RNA, exclude water)
            polymer_chains = []
            chain_entity_types = {}
            
            # First, determine entity type from actual atoms (more reliable than entity_poly.type)
            # Check atom_site to see what residues are actually present
            # Use label_asym_id (not auth_asym_id) to match with struct_asym.id
            chain_atom_residues = {}  # chain_id -> set of residue types
            if '_atom_site.label_asym_id' in cif_dict and '_atom_site.label_comp_id' in cif_dict:
                label_asym_ids_atom = cif_dict['_atom_site.label_asym_id']
                label_comp_ids_atom = cif_dict['_atom_site.label_comp_id']
                group_pdb_atom = cif_dict.get('_atom_site.group_PDB', [])
                
                for i, chain in enumerate(label_asym_ids_atom):
                    if i >= len(group_pdb_atom) or group_pdb_atom[i] == 'ATOM':
                        if chain not in chain_atom_residues:
                            chain_atom_residues[chain] = set()
                        if i < len(label_comp_ids_atom):
                            chain_atom_residues[chain].add(label_comp_ids_atom[i])
            
            # Track which entity_ids have already been included
            # Used to select only one chain per entity when include_all_copies=False
            seen_entity_ids = set()
            skipped_chains = []  # For logging
            
            for asym_id, entity_id in zip(asym_ids, asym_entity_ids):
                # Check if entity is polymer (protein/nucleic acid)
                is_polymer = entity_id in polymer_entity_ids
                
                # Check entity type (exclude water)
                entity_type = entity_types.get(entity_id, '').lower()
                is_water = 'water' in entity_type
                
                if is_polymer and not is_water:
                    # Skip duplicate entities unless include_all_copies is True
                    if not include_all_copies and entity_id in seen_entity_ids:
                        skipped_chains.append((asym_id, entity_id))
                        continue
                    
                    seen_entity_ids.add(entity_id)
                    
                    if asym_id not in polymer_chains:
                        polymer_chains.append(asym_id)
                        
                        # Determine entity type from actual atoms (preferred) or entity_poly.type
                        entity_type_from_atoms = None
                        if asym_id in chain_atom_residues:
                            atom_residues = chain_atom_residues[asym_id]
                            # Check if DNA/RNA residues are present
                            dna_rna_residues = {'DA', 'DC', 'DG', 'DT', 'DI', 'A', 'C', 'G', 'T', 'U', 'I'}
                            protein_residues = {'ALA', 'CYS', 'ASP', 'GLU', 'PHE', 'GLY', 'HIS', 'ILE', 
                                                'LYS', 'LEU', 'MET', 'ASN', 'PRO', 'GLN', 'ARG', 'SER', 
                                                'THR', 'VAL', 'TRP', 'TYR'}
                            # Include non-standard residues so chains with ACE/PTR/DIP etc. are classified as protein
                            has_dna_rna = bool(atom_residues & dna_rna_residues)
                            has_protein = bool(atom_residues & protein_residues) or bool(
                                atom_residues - STANDARD_AA_THREE_LETTER - dna_rna_residues - {'HOH', 'H2O', 'WAT'}
                            )
                            
                            if has_dna_rna and not has_protein:
                                # Check if DNA or RNA
                                if 'U' in atom_residues or any('R' in r for r in atom_residues if len(r) > 1):
                                    entity_type_from_atoms = 'rna'
                                else:
                                    entity_type_from_atoms = 'dna'
                            elif has_protein and not has_dna_rna:
                                entity_type_from_atoms = 'protein'
                        
                        # Use atom-based type if available, otherwise fall back to entity_poly.type
                        if entity_type_from_atoms:
                            chain_entity_types[asym_id] = entity_type_from_atoms
                        else:
                            # Fall back to entity_poly.type
                            poly_type = entity_poly_types.get(entity_id, '')
                            if 'polydeoxyribonucleotide' in poly_type or 'dna' in poly_type:
                                chain_entity_types[asym_id] = 'dna'
                            elif 'polyribonucleotide' in poly_type or 'rna' in poly_type:
                                chain_entity_types[asym_id] = 'rna'
                            elif 'polypeptide' in poly_type or 'protein' in poly_type:
                                chain_entity_types[asym_id] = 'protein'
                            else:
                                # Default to protein if unclear
                                chain_entity_types[asym_id] = 'protein'
                        # Log when chain is modification-containing protein (e.g. 1A1B C,D)
                        if chain_entity_types.get(asym_id) == 'protein' and entity_nstd_monomer.get(entity_id):
                            print(f"INFO: Chain {asym_id} treated as protein with modifications (entity_poly.nstd_monomer=yes)")
            
            # Sort chains for consistent output
            polymer_chains = sorted(polymer_chains)
            
            # Log skipped chains if any
            if skipped_chains and not include_all_copies:
                skipped_info = ', '.join([f"{c}(entity {e})" for c, e in skipped_chains])
                print(f"INFO: Skipped duplicate entity chains: {skipped_info}")
                print(f"      (Use 'all-copies' instead of 'all' to include all copies)")
            
            if not polymer_chains:
                print("WARNING: No polymer chains found in structure", file=sys.stderr)
            
            return polymer_chains, chain_entity_types
            
        except Exception as e:
            print(f"ERROR: Error parsing CIF file to find chains: {e}", file=sys.stderr)
            sys.exit(1)

    def _build_entity_type_map(self) -> Dict[str, str]:
        """Build a label_asym_id -> entity_type map from CIF entity tables.

        Uses _entity_poly.type as the authoritative source (polyribonucleotide → 'rna',
        polydeoxyribonucleotide → 'dna', polypeptide → 'protein'), with _entity.type as
        fallback for non-polymer (ligand) and water chains.

        Returns entity_type in {'protein', 'rna', 'dna', 'ligand', 'water'}.
        """
        if not self.cif_content:
            return {}
        try:
            cif_dict = self._get_cif_dict()
        except Exception:
            return {}

        # entity_id -> poly_type from _entity_poly
        entity_poly_types: Dict[str, str] = {}
        if '_entity_poly.entity_id' in cif_dict and '_entity_poly.type' in cif_dict:
            poly_eids = cif_dict['_entity_poly.entity_id']
            poly_types = cif_dict['_entity_poly.type']
            if isinstance(poly_eids, str):
                poly_eids = [poly_eids]
            if isinstance(poly_types, str):
                poly_types = [poly_types]
            for eid, ptype in zip(poly_eids, poly_types):
                pt = ptype.lower()
                if 'polydeoxyribonucleotide' in pt or ('dna' in pt and 'rna' not in pt):
                    entity_poly_types[eid] = 'dna'
                elif 'polyribonucleotide' in pt or 'rna' in pt:
                    entity_poly_types[eid] = 'rna'
                elif 'polypeptide' in pt or 'protein' in pt:
                    entity_poly_types[eid] = 'protein'

        # entity_id -> raw type string from _entity
        entity_types_raw: Dict[str, str] = {}
        if '_entity.id' in cif_dict and '_entity.type' in cif_dict:
            eids = cif_dict['_entity.id']
            etypes = cif_dict['_entity.type']
            if isinstance(eids, str):
                eids = [eids]
            if isinstance(etypes, str):
                etypes = [etypes]
            for eid, etype in zip(eids, etypes):
                entity_types_raw[eid] = etype.lower()

        # label_asym_id -> entity_type
        result: Dict[str, str] = {}
        if '_struct_asym.id' not in cif_dict or '_struct_asym.entity_id' not in cif_dict:
            return result
        asym_ids = cif_dict['_struct_asym.id']
        asym_eids = cif_dict['_struct_asym.entity_id']
        if isinstance(asym_ids, str):
            asym_ids = [asym_ids]
        if isinstance(asym_eids, str):
            asym_eids = [asym_eids]
        for asym_id, eid in zip(asym_ids, asym_eids):
            if eid in entity_poly_types:
                result[asym_id] = entity_poly_types[eid]
            else:
                raw = entity_types_raw.get(eid, '')
                if 'water' in raw:
                    result[asym_id] = 'water'
                elif 'non-polymer' in raw:
                    result[asym_id] = 'ligand'
        return result

    def get_ligand_chain_ids(self) -> List[str]:
        """Return list of chain IDs that are non-polymer (ligands), excluding water."""
        if not self.cif_content:
            return []
        try:
            cif_dict = self._get_cif_dict()
            if '_struct_asym.id' not in cif_dict or '_struct_asym.entity_id' not in cif_dict:
                return []
            asym_ids = cif_dict['_struct_asym.id']
            asym_entity = cif_dict['_struct_asym.entity_id']
            if isinstance(asym_ids, str):
                asym_ids = [asym_ids]
            if isinstance(asym_entity, str):
                asym_entity = [asym_entity]
            entity_types = {}
            if '_entity.id' in cif_dict and '_entity.type' in cif_dict:
                eid = cif_dict['_entity.id']
                etype = cif_dict['_entity.type']
                if isinstance(eid, str):
                    eid = [eid]
                if isinstance(etype, str):
                    etype = [etype]
                for i, ent in enumerate(eid):
                    entity_types[ent] = etype[i] if i < len(etype) else 'polymer'
            ligand_chains = []
            for asym_id, eid in zip(asym_ids, asym_entity):
                if entity_types.get(eid, 'polymer').strip().lower() == 'non-polymer':
                    ligand_chains.append(asym_id)
            return sorted(ligand_chains)
        except Exception:
            return []

