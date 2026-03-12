"""Atom record parsing, solvent extraction, and renumbering."""
import re
from typing import Dict, List, Optional

from .log import info, fatal


class AtomParseMixin:
    def parse_atom_records(self, chain_id: str) -> List[Dict]:
        """Parse ATOM records from CIF file using BioPython."""
        # Synthetic chains (created by non-identity assembly symmetry ops) are pre-computed
        if chain_id in self._synthetic_atoms:
            return self._synthetic_atoms[chain_id]

        if not self.cif_content:
            raise ValueError("CIF content not loaded")

        try:
            # Parse using BioPython
            cif_dict = self._get_cif_dict()

            # Get all atom_site fields
            if '_atom_site.group_PDB' not in cif_dict:
                fatal("No atom_site information found in CIF file")

            # Extract atoms for our chain
            atoms = []
            n_atoms = len(cif_dict['_atom_site.group_PDB'])

            # For NMR or multi-model structures, use only model 1
            model_nums = cif_dict.get('_atom_site.pdbx_PDB_model_num', [])
            if isinstance(model_nums, str):
                model_nums = [model_nums] * n_atoms
            if model_nums:
                all_models = sorted({m for m in model_nums if m not in ('?', '.')}, key=lambda x: int(x) if x.isdigit() else 0)
                first_model = all_models[0] if all_models else None
                if first_model and len(all_models) > 1:
                    info(f"Multi-model structure detected ({len(all_models)} models); using model {first_model} only")
            else:
                first_model = None

            for i in range(n_atoms):
                # Skip atoms not belonging to model 1 in multi-model structures
                if first_model is not None and i < len(model_nums) and model_nums[i] != first_model:
                    continue

                # Check if this is an ATOM record for our chain
                # Use label_asym_id (not auth_asym_id) to match with struct_asym.id
                group_pdb = cif_dict['_atom_site.group_PDB'][i]
                label_asym_id = cif_dict['_atom_site.label_asym_id'][i]

                # Match chain_id case-insensitively (CIF files may have different case)
                if group_pdb == 'ATOM' and label_asym_id.upper() == chain_id.upper():
                    # Helper function to safely get field value with fallback
                    def get_field(field_name, fallback_value=None, fallback_from_label=None):
                        if field_name in cif_dict:
                            field_list = cif_dict[field_name]
                            if i < len(field_list):
                                return field_list[i]
                        # If field not found, use fallback
                        if fallback_from_label and fallback_from_label in cif_dict:
                            fallback_list = cif_dict[fallback_from_label]
                            if i < len(fallback_list):
                                return fallback_list[i]
                        return fallback_value if fallback_value is not None else '?'

                    atom = {
                        'group_PDB': cif_dict['_atom_site.group_PDB'][i],
                        'id': cif_dict['_atom_site.id'][i],
                        'type_symbol': cif_dict['_atom_site.type_symbol'][i],
                        'label_atom_id': cif_dict['_atom_site.label_atom_id'][i],
                        'label_alt_id': get_field('_atom_site.label_alt_id', '?'),
                        'label_comp_id': cif_dict['_atom_site.label_comp_id'][i],
                        'label_asym_id': cif_dict['_atom_site.label_asym_id'][i],
                        'label_entity_id': cif_dict['_atom_site.label_entity_id'][i],
                        'label_seq_id': get_field('_atom_site.label_seq_id', '?'),
                        'pdbx_PDB_ins_code': get_field('_atom_site.pdbx_PDB_ins_code', '?'),
                        'Cartn_x': cif_dict['_atom_site.Cartn_x'][i],
                        'Cartn_y': cif_dict['_atom_site.Cartn_y'][i],
                        'Cartn_z': cif_dict['_atom_site.Cartn_z'][i],
                        'occupancy': get_field('_atom_site.occupancy', '1.00'),
                        'B_iso_or_equiv': get_field('_atom_site.B_iso_or_equiv', '?'),
                        'pdbx_formal_charge': get_field('_atom_site.pdbx_formal_charge', '?'),
                        'auth_seq_id': get_field('_atom_site.auth_seq_id', '?', '_atom_site.label_seq_id'),
                        'auth_comp_id': get_field('_atom_site.auth_comp_id', cif_dict['_atom_site.label_comp_id'][i], '_atom_site.label_comp_id'),
                        'auth_asym_id': get_field('_atom_site.auth_asym_id', cif_dict['_atom_site.label_asym_id'][i], '_atom_site.label_asym_id'),
                        'auth_atom_id': get_field('_atom_site.auth_atom_id', cif_dict['_atom_site.label_atom_id'][i], '_atom_site.label_atom_id'),
                        'pdbx_PDB_model_num': get_field('_atom_site.pdbx_PDB_model_num', '1')
                    }
                    atoms.append(atom)
                elif group_pdb == 'HETATM' and label_asym_id.upper() == chain_id.upper():
                    # Include ligand atoms (HETATM) for the chain
                    def get_field(field_name, fallback_value=None, fallback_from_label=None):
                        if field_name in cif_dict:
                            field_list = cif_dict[field_name]
                            if i < len(field_list):
                                return field_list[i]
                        if fallback_from_label and fallback_from_label in cif_dict:
                            fallback_list = cif_dict[fallback_from_label]
                            if i < len(fallback_list):
                                return fallback_list[i]
                        return fallback_value if fallback_value is not None else '?'

                    atom = {
                        'group_PDB': cif_dict['_atom_site.group_PDB'][i],
                        'id': cif_dict['_atom_site.id'][i],
                        'type_symbol': cif_dict['_atom_site.type_symbol'][i],
                        'label_atom_id': cif_dict['_atom_site.label_atom_id'][i],
                        'label_alt_id': get_field('_atom_site.label_alt_id', '?'),
                        'label_comp_id': cif_dict['_atom_site.label_comp_id'][i],
                        'label_asym_id': cif_dict['_atom_site.label_asym_id'][i],
                        'label_entity_id': cif_dict['_atom_site.label_entity_id'][i],
                        'label_seq_id': get_field('_atom_site.label_seq_id', '?'),
                        'pdbx_PDB_ins_code': get_field('_atom_site.pdbx_PDB_ins_code', '?'),
                        'Cartn_x': cif_dict['_atom_site.Cartn_x'][i],
                        'Cartn_y': cif_dict['_atom_site.Cartn_y'][i],
                        'Cartn_z': cif_dict['_atom_site.Cartn_z'][i],
                        'occupancy': get_field('_atom_site.occupancy', '1.00'),
                        'B_iso_or_equiv': get_field('_atom_site.B_iso_or_equiv', '?'),
                        'pdbx_formal_charge': get_field('_atom_site.pdbx_formal_charge', '?'),
                        'auth_seq_id': get_field('_atom_site.auth_seq_id', '?', '_atom_site.label_seq_id'),
                        'auth_comp_id': get_field('_atom_site.auth_comp_id', cif_dict['_atom_site.label_comp_id'][i], '_atom_site.label_comp_id'),
                        'auth_asym_id': get_field('_atom_site.auth_asym_id', cif_dict['_atom_site.label_asym_id'][i], '_atom_site.label_asym_id'),
                        'auth_atom_id': get_field('_atom_site.auth_atom_id', cif_dict['_atom_site.label_atom_id'][i], '_atom_site.label_atom_id'),
                        'pdbx_PDB_model_num': get_field('_atom_site.pdbx_PDB_model_num', '1')
                    }
                    atoms.append(atom)

            info(f"Parsed {len(atoms)} atoms for chain {chain_id}")
            return atoms

        except Exception as e:
            fatal(f"Error parsing atom records: {e}")


    def _extract_solvent_atoms(self) -> List[Dict]:
        """Extract water (and other solvent) atoms from CIF for --include-solvent."""
        if not self.cif_content:
            return []
        try:
            cif_dict = self._get_cif_dict()
        except Exception:
            return []
        if '_entity.type' not in cif_dict or '_struct_asym.id' not in cif_dict or '_atom_site.label_asym_id' not in cif_dict:
            return []
        entity_ids = cif_dict['_entity.id']
        entity_types = cif_dict['_entity.type']
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        if isinstance(entity_types, str):
            entity_types = [entity_types]
        water_entity_ids = set()
        for eid, etype in zip(entity_ids, entity_types):
            if etype and 'water' in str(etype).lower():
                water_entity_ids.add(int(eid) if isinstance(eid, str) else eid)
        if not water_entity_ids:
            return []
        asym_ids = cif_dict['_struct_asym.id']
        asym_entity = cif_dict['_struct_asym.entity_id']
        if isinstance(asym_ids, str):
            asym_ids = [asym_ids]
        if isinstance(asym_entity, str):
            asym_entity = [asym_entity]
        solvent_asym_ids = set()
        for aid, eid in zip(asym_ids, asym_entity):
            if (int(eid) if isinstance(eid, str) else eid) in water_entity_ids:
                solvent_asym_ids.add(aid)
        if not solvent_asym_ids:
            return []
        n_atoms = len(cif_dict['_atom_site.group_PDB'])
        atoms = []
        for i in range(n_atoms):
            label_asym = cif_dict['_atom_site.label_asym_id'][i]
            if label_asym not in solvent_asym_ids:
                continue
            def get_f(field: str, default: str = '?'):
                if field not in cif_dict:
                    return default
                lst = cif_dict[field]
                if isinstance(lst, str):
                    lst = [lst]
                return lst[i] if i < len(lst) else default
            atoms.append({
                'group_PDB': get_f('_atom_site.group_PDB', 'HETATM'),
                'id': get_f('_atom_site.id'),
                'type_symbol': get_f('_atom_site.type_symbol'),
                'label_atom_id': get_f('_atom_site.label_atom_id'),
                'label_alt_id': get_f('_atom_site.label_alt_id', '?'),
                'label_comp_id': get_f('_atom_site.label_comp_id'),
                'label_asym_id': label_asym,
                'label_entity_id': get_f('_atom_site.label_entity_id'),
                'label_seq_id': get_f('_atom_site.label_seq_id', '?'),
                'pdbx_PDB_ins_code': get_f('_atom_site.pdbx_PDB_ins_code', '?'),
                'Cartn_x': get_f('_atom_site.Cartn_x'),
                'Cartn_y': get_f('_atom_site.Cartn_y'),
                'Cartn_z': get_f('_atom_site.Cartn_z'),
                'occupancy': get_f('_atom_site.occupancy', '1.00'),
                'B_iso_or_equiv': get_f('_atom_site.B_iso_or_equiv', '?'),
                'pdbx_formal_charge': get_f('_atom_site.pdbx_formal_charge', '?'),
                'auth_seq_id': get_f('_atom_site.auth_seq_id', '?'),
                'auth_comp_id': get_f('_atom_site.auth_comp_id', '?'),
                'auth_asym_id': get_f('_atom_site.auth_asym_id', '?'),
                'auth_atom_id': get_f('_atom_site.auth_atom_id', '?'),
                'pdbx_PDB_model_num': get_f('_atom_site.pdbx_PDB_model_num', '1'),
            })
        info(f"Included {len(atoms)} solvent (water) atoms from {len(solvent_asym_ids)} chain(s): {sorted(solvent_asym_ids)}")
        return atoms

    def renumber_atoms(self, atoms: List[Dict], residue_mapping: Dict[int, int]) -> List[Dict]:
        """Renumber atoms with new residue numbering starting from 1.

        residue_mapping: Dict[sequential_index, SEQRES_position]
        """
        renumbered_atoms = []

        # Build reverse mapping: (auth_seq_id_base, ins_code) -> sequential_index -> SEQRES position
        key_to_seqres = {}
        for seq_idx, seqres_pos in residue_mapping.items():
            if hasattr(self, '_residue_index_to_key'):
                key = self._residue_index_to_key[seq_idx]
                key_to_seqres[key] = seqres_pos
        for atom in atoms:
            # Extract residue key from atom
            auth_seq_id_str = str(atom['auth_seq_id']).strip()
            ins_code = atom.get('pdbx_PDB_ins_code', '?')
            if ins_code == '?':
                ins_code = ''

            # Parse base number
            match = re.match(r'^(-?\d+)', auth_seq_id_str)
            if not match:
                continue
            auth_seq_id_base = int(match.group(1))

            residue_key = (auth_seq_id_base, ins_code)

            # Skip residues that were removed (e.g., in UniProt mode)
            if residue_key not in key_to_seqres:
                continue

            new_seq_id = key_to_seqres[residue_key]

            new_atom = atom.copy()
            # Update both label_seq_id and auth_seq_id - remove insertion codes
            new_atom['label_seq_id'] = str(new_seq_id)
            new_atom['auth_seq_id'] = str(new_seq_id)
            new_atom['pdbx_PDB_ins_code'] = '?'  # Remove insertion code

            renumbered_atoms.append(new_atom)

        info(f"Renumbered {len(renumbered_atoms)} atoms")
        return renumbered_atoms


    # ------------------------------------------------------------------
    # Assembly selection methods
    # ------------------------------------------------------------------
