"""Non-standard residue and covalent modification parsing."""
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from ..ccd_utils import load_ccd_dict, get_non_standard_parent_from_ccd
from ..constants import (
    NONSTANDARD_TO_STANDARD,
    STANDARD_AA_CODES,
    STANDARD_AA_THREE_LETTER,
    STANDARD_NUCLEOTIDE_CODES,
    STANDARD_RES_ONE_LETTER,
    STANDARD_RES_THREE_LETTER,
)
from .log import info, warning


class ModificationsMixin:
    def parse_non_standard_residues(self, ccd: Optional[dict] = None, ccd_path: Optional[Path] = None) -> Dict[str, Dict[int, Dict]]:
        """Parse non-standard residue information from CIF file.

        Extracts non-standard residue info (e.g. modifications, non-std monomers) from:
        1. _pdbx_struct_mod_residue category (preferred, contains parent_comp_id)
        2. HETATM records with CCD codes that have a parent residue in CCD (ccd.pkl)

        Uses the CCD dictionary from ccd.pkl to resolve parent residues when possible.

        Parameters
        ----------
        ccd : Optional[dict]
            Pre-loaded CCD dict from ccd.pkl. If None, loaded from ccd_path or default.
        ccd_path : Optional[Path]
            Path to ccd.pkl. Used only if ccd is None (default: BOLTZ_CACHE or ~/.boltz/ccd.pkl).

        Returns
        -------
        Dict
            Mapping chain_id -> {seq_id: {'ccd': CCD_CODE, 'parent': PARENT_THREE_LETTER, 'parent_one': PARENT_ONE_LETTER}}
        """
        if not self.cif_content:
            raise ValueError("CIF content not loaded")

        if ccd is None:
            path = ccd_path or get_default_ccd_path()
            ccd = load_ccd_dict(path)
            if not ccd and path.exists():
                pass  # load failed
            elif not ccd:
                pass  # no ccd.pkl; non-standard parent resolution skipped

        non_standard_residues = {}
        try:
            cif_dict = self._get_cif_dict()

            # Method 1: Parse _pdbx_struct_mod_residue (most reliable - directly from CIF)
            if '_pdbx_struct_mod_residue.label_asym_id' in cif_dict:
                label_asym_ids = cif_dict.get('_pdbx_struct_mod_residue.label_asym_id', [])
                label_comp_ids = cif_dict.get('_pdbx_struct_mod_residue.label_comp_id', [])
                label_seq_ids = cif_dict.get('_pdbx_struct_mod_residue.label_seq_id', [])
                parent_comp_ids = cif_dict.get('_pdbx_struct_mod_residue.parent_comp_id', [])
                auth_asym_ids = cif_dict.get('_pdbx_struct_mod_residue.auth_asym_id', [])
                auth_seq_ids = cif_dict.get('_pdbx_struct_mod_residue.auth_seq_id', [])

                # Ensure all lists (convert single values to lists)
                if isinstance(label_asym_ids, str):
                    label_asym_ids = [label_asym_ids]
                    label_comp_ids = [label_comp_ids] if isinstance(label_comp_ids, str) else label_comp_ids
                    label_seq_ids = [label_seq_ids] if isinstance(label_seq_ids, str) else label_seq_ids
                    parent_comp_ids = [parent_comp_ids] if isinstance(parent_comp_ids, str) else parent_comp_ids
                    auth_asym_ids = [auth_asym_ids] if isinstance(auth_asym_ids, str) else auth_asym_ids
                    auth_seq_ids = [auth_seq_ids] if isinstance(auth_seq_ids, str) else auth_seq_ids

                for i, chain_id in enumerate(label_asym_ids):
                    if i < len(label_comp_ids) and i < len(label_seq_ids):
                        ccd_code = label_comp_ids[i]
                        try:
                            seq_id = int(label_seq_ids[i])
                        except (ValueError, TypeError):
                            continue

                        # Get parent from CIF (most reliable)
                        parent_code = parent_comp_ids[i] if i < len(parent_comp_ids) else None

                        # If parent not in CIF (or not a recognised standard
                        # protein/nucleic residue), resolve from CCD (ccd.pkl)
                        if not parent_code or parent_code not in STANDARD_RES_THREE_LETTER:
                            resolved = get_non_standard_parent_from_ccd(ccd, ccd_code)
                            if resolved:
                                parent_code = resolved[0]

                        # Last-ditch fallback: hardcoded NONSTANDARD_TO_STANDARD
                        # (covers cases where ccd.pkl was built without parent
                        #  properties — common with pdbeccdutils-generated mol pickles).
                        if not parent_code or parent_code not in STANDARD_RES_THREE_LETTER:
                            hard = NONSTANDARD_TO_STANDARD.get(ccd_code.upper())
                            if hard and hard in STANDARD_RES_THREE_LETTER:
                                parent_code = hard

                        # Get one-letter code for parent (covers protein + DNA + RNA).
                        parent_one = STANDARD_RES_ONE_LETTER.get(parent_code, 'X') if parent_code else 'X'

                        if chain_id not in non_standard_residues:
                            non_standard_residues[chain_id] = {}

                        non_standard_residues[chain_id][seq_id] = {
                            'ccd': ccd_code,
                            'parent': parent_code,
                            'parent_one': parent_one,
                            'auth_seq_id': auth_seq_ids[i] if i < len(auth_seq_ids) else str(seq_id)
                        }
                        info(f"Found non-standard from _pdbx_struct_mod_residue: Chain {chain_id}, Pos {seq_id}, {ccd_code} -> {parent_code} ({parent_one})")

            # Method 2: Scan HETATM for non-standard residues with parent in CCD
            if '_atom_site.group_PDB' in cif_dict:
                group_pdb = cif_dict['_atom_site.group_PDB']
                label_asym_ids = cif_dict.get('_atom_site.label_asym_id', [])
                label_comp_ids = cif_dict.get('_atom_site.label_comp_id', [])
                label_seq_ids = cif_dict.get('_atom_site.label_seq_id', [])

                seen_ns = set()  # (chain_id, seq_id, ccd) to avoid duplicates

                for i, group in enumerate(group_pdb):
                    if group == 'HETATM' and i < len(label_comp_ids):
                        ccd_code = label_comp_ids[i].upper()

                        resolved = get_non_standard_parent_from_ccd(ccd, ccd_code)
                        if resolved is None:
                            continue  # No parent in CCD (e.g. ligand)

                        parent_three, parent_one = resolved
                        chain_id = label_asym_ids[i] if i < len(label_asym_ids) else None
                        seq_id_str = label_seq_ids[i] if i < len(label_seq_ids) else None

                        if chain_id and seq_id_str:
                            try:
                                seq_id = int(seq_id_str)
                            except (ValueError, TypeError):
                                continue

                            ns_key = (chain_id, seq_id, ccd_code)
                            if ns_key in seen_ns:
                                continue
                            seen_ns.add(ns_key)

                            if chain_id in non_standard_residues and seq_id in non_standard_residues[chain_id]:
                                continue

                            if chain_id not in non_standard_residues:
                                non_standard_residues[chain_id] = {}

                            non_standard_residues[chain_id][seq_id] = {
                                'ccd': ccd_code,
                                'parent': parent_three,
                                'parent_one': parent_one,
                                'auth_seq_id': str(seq_id)
                            }
                            info(f"Found non-standard from HETATM (via CCD): Chain {chain_id}, Pos {seq_id}, {ccd_code} -> {parent_three} ({parent_one})")

            self.non_standard_residues = non_standard_residues

            if non_standard_residues:
                total_ns = sum(len(v) for v in non_standard_residues.values())
                info(f"Total non-standard residues found: {total_ns}")

            return non_standard_residues

        except Exception as e:
            warning(f"Error parsing non-standard residues: {e}")
            return {}


    def _get_modifications_from_entity_poly_seq(self) -> Dict[str, List[Dict[str, Any]]]:
        """Build chain_id -> modifications from _entity_poly_seq (same logic as generate_yaml.py).
        So YAML gets ACE, PTR, DIP etc. even when _pdbx_struct_mod_residue only lists PTR.
        """
        out = {}
        if not self.cif_content:
            return out
        try:
            cif_dict = self._get_cif_dict()
        except Exception:
            return out
        if '_entity_poly_seq.mon_id' not in cif_dict or '_struct_asym.id' not in cif_dict:
            return out
        eid = cif_dict['_entity_poly_seq.entity_id']
        num = cif_dict['_entity_poly_seq.num']
        mon_id = cif_dict['_entity_poly_seq.mon_id']
        if isinstance(eid, str):
            eid = [eid]
        if isinstance(num, str):
            num = [num]
        if isinstance(mon_id, str):
            mon_id = [mon_id]
        num = [int(n) for n in num]
        by_entity: Dict[int, List[Tuple[int, str]]] = {}
        for i, ent in enumerate(eid):
            ent_id = int(ent) if isinstance(ent, str) else ent
            if ent_id not in by_entity:
                by_entity[ent_id] = []
            by_entity[ent_id].append((num[i], mon_id[i]))
        entity_mods = {}
        for ent_id, items in by_entity.items():
            items.sort(key=lambda x: x[0])
            mods = []
            for actual_num, code in items:
                if code not in STANDARD_AA_THREE_LETTER and code not in STANDARD_NUCLEOTIDE_CODES:
                    mods.append({'position': actual_num, 'ccd': code})
            if mods:
                entity_mods[ent_id] = mods
        asym_ids = cif_dict['_struct_asym.id']
        asym_entity = cif_dict['_struct_asym.entity_id']
        if isinstance(asym_ids, str):
            asym_ids = [asym_ids]
        if isinstance(asym_entity, str):
            asym_entity = [asym_entity]
        for chain_id, eid in zip(asym_ids, asym_entity):
            ent_id = int(eid) if isinstance(eid, str) else eid
            if ent_id in entity_mods:
                out[chain_id] = entity_mods[ent_id]
        return out

    def _get_modifications_from_struct_conn(self) -> Dict[str, List[Dict[str, Any]]]:
        """Build chain_id -> modifications from _struct_conn (covale) for residues like NH2 at B 7.
        When a residue is linked by covalent bond and has a non-standard comp_id (e.g. NH2),
        include it so YAML modifications are complete even if _entity_poly_seq has UNK.
        """
        out: Dict[str, List[Dict[str, Any]]] = {}
        if not self.cif_content:
            return out
        try:
            cif_dict = self._get_cif_dict()
        except Exception:
            return out
        conn_type = cif_dict.get('_struct_conn.conn_type_id', [])
        if isinstance(conn_type, str):
            conn_type = [conn_type]
        ptnr2_asym = cif_dict.get('_struct_conn.ptnr2_label_asym_id', [])
        ptnr2_comp = cif_dict.get('_struct_conn.ptnr2_label_comp_id', [])
        ptnr2_seq = cif_dict.get('_struct_conn.ptnr2_label_seq_id', [])
        if isinstance(ptnr2_asym, str):
            ptnr2_asym = [ptnr2_asym]
        if isinstance(ptnr2_comp, str):
            ptnr2_comp = [ptnr2_comp]
        if isinstance(ptnr2_seq, str):
            ptnr2_seq = [ptnr2_seq]
        for i, ctype in enumerate(conn_type):
            if str(ctype).strip().lower() != 'covale':
                continue
            if i >= len(ptnr2_asym) or i >= len(ptnr2_comp) or i >= len(ptnr2_seq):
                continue
            comp = (ptnr2_comp[i] or '').strip().upper()
            if not comp or comp in STANDARD_AA_THREE_LETTER or comp in STANDARD_NUCLEOTIDE_CODES:
                continue
            try:
                seq_id = int(ptnr2_seq[i])
            except (ValueError, TypeError):
                continue
            chain_id = (ptnr2_asym[i] or '').strip()
            if not chain_id:
                continue
            pos_1based = seq_id
            if chain_id not in out:
                out[chain_id] = []
            # Avoid duplicate position
            if any(m['position'] == pos_1based for m in out[chain_id]):
                continue
            out[chain_id].append({'position': pos_1based, 'ccd': comp})
        for chain_id in out:
            out[chain_id].sort(key=lambda m: m['position'])
        return out
