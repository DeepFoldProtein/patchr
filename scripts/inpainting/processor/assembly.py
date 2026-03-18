"""Biological assembly parsing, selection, and symmetry operations."""
import re
from typing import Dict, List, Optional, Tuple

from .log import info, warning, section


class AssemblyMixin:
    def _parse_oper_expression(self, expr: str) -> List[str]:
        """Parse _pdbx_struct_assembly_gen.oper_expression into a flat list of oper IDs.

        Handles:
          "1"       -> ['1']
          "1,2"     -> ['1', '2']
          "(1-6)"   -> ['1','2','3','4','5','6']
          "(1-3)(4-6)" -> Cartesian product (warns, returns union for now)
        """
        expr = expr.strip()
        # Simple comma-separated (no parentheses)
        if '(' not in expr:
            return [x.strip() for x in expr.split(',') if x.strip()]

        import re
        # Extract all parenthesised groups
        groups = re.findall(r'\(([^)]+)\)', expr)
        if not groups:
            return [x.strip() for x in expr.split(',') if x.strip()]

        if len(groups) > 1:
            warning(f"Complex oper_expression '{expr}' (Cartesian product) — "
                    "treating as union of all IDs")

        result: List[str] = []
        for group in groups:
            for token in group.split(','):
                token = token.strip()
                if '-' in token:
                    parts = token.split('-')
                    try:
                        start, end = int(parts[0].strip()), int(parts[1].strip())
                        result.extend(str(i) for i in range(start, end + 1))
                    except ValueError:
                        result.append(token)
                elif token:
                    result.append(token)
        return result

    def parse_assembly_info(self) -> Dict:
        """Parse _pdbx_struct_assembly, _pdbx_struct_assembly_gen, _pdbx_struct_oper_list.

        Returns a dict:
          {
            'assemblies': { id_str: {'details': str, 'oligomeric_details': str, 'count': int} },
            'assembly_gen': [ {'assembly_id': str, 'oper_ids': [str], 'chain_ids': [str]} ],
            'operations': { id_str: {'type': str, 'matrix': [[float]*3]*3, 'vector': [float]*3} },
          }
        """
        cif_dict = self._get_cif_dict()
        result: Dict = {'assemblies': {}, 'assembly_gen': [], 'operations': {}}

        # --- assemblies ---
        if '_pdbx_struct_assembly.id' in cif_dict:
            ids = cif_dict['_pdbx_struct_assembly.id']
            details_list = cif_dict.get('_pdbx_struct_assembly.details', [])
            oligo_details = cif_dict.get('_pdbx_struct_assembly.oligomeric_details', [])
            oligo_count = cif_dict.get('_pdbx_struct_assembly.oligomeric_count', [])
            if isinstance(ids, str):
                ids = [ids]
            for i, aid in enumerate(ids):
                result['assemblies'][str(aid)] = {
                    'details': details_list[i] if i < len(details_list) else '?',
                    'oligomeric_details': oligo_details[i] if i < len(oligo_details) else '?',
                    'count': oligo_count[i] if i < len(oligo_count) else '?',
                }

        # --- assembly_gen ---
        if '_pdbx_struct_assembly_gen.assembly_id' in cif_dict:
            gen_ids = cif_dict['_pdbx_struct_assembly_gen.assembly_id']
            oper_exprs = cif_dict.get('_pdbx_struct_assembly_gen.oper_expression', [])
            asym_lists = cif_dict.get('_pdbx_struct_assembly_gen.asym_id_list', [])
            if isinstance(gen_ids, str):
                gen_ids = [gen_ids]
            for i, aid in enumerate(gen_ids):
                expr = oper_exprs[i] if i < len(oper_exprs) else '1'
                asym_raw = asym_lists[i] if i < len(asym_lists) else ''
                # Strip CIF multi-line delimiters (leading/trailing ';' and newlines)
                asym_raw = asym_raw.strip().strip(';').strip()
                chain_ids_in_gen = [c.strip() for c in asym_raw.split(',') if c.strip()]
                oper_ids = self._parse_oper_expression(str(expr))
                result['assembly_gen'].append({
                    'assembly_id': str(aid),
                    'oper_ids': oper_ids,
                    'chain_ids': chain_ids_in_gen,
                })

        # --- operations ---
        if '_pdbx_struct_oper_list.id' in cif_dict:
            op_ids = cif_dict['_pdbx_struct_oper_list.id']
            op_types = cif_dict.get('_pdbx_struct_oper_list.type', [])
            if isinstance(op_ids, str):
                op_ids = [op_ids]
            # Matrix/vector fields
            m = {}
            for r in range(1, 4):
                for c in range(1, 4):
                    key = f'_pdbx_struct_oper_list.matrix[{r}][{c}]'
                    m[(r, c)] = cif_dict.get(key, [])
            v = {}
            for r in range(1, 4):
                key = f'_pdbx_struct_oper_list.vector[{r}]'
                v[r] = cif_dict.get(key, [])

            for i, oid in enumerate(op_ids):
                try:
                    matrix = [
                        [float(m[(r, c)][i]) if i < len(m[(r, c)]) else (1.0 if r == c else 0.0)
                         for c in range(1, 4)]
                        for r in range(1, 4)
                    ]
                    vector = [
                        float(v[r][i]) if i < len(v[r]) else 0.0
                        for r in range(1, 4)
                    ]
                except (ValueError, IndexError):
                    matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
                    vector = [0.0, 0.0, 0.0]
                result['operations'][str(oid)] = {
                    'type': op_types[i] if i < len(op_types) else '?',
                    'matrix': matrix,
                    'vector': vector,
                }

        return result

    def select_best_assembly(self, assembly_info: Dict) -> Optional[str]:
        """Return the ID of the best biological assembly.

        Priority:
          1. First 'author_and_software_defined_assembly'
          2. First 'software_defined_assembly'
          3. First assembly in list
        """
        assemblies = assembly_info.get('assemblies', {})
        if not assemblies:
            return None

        for aid, info_val in assemblies.items():
            if 'author_and_software_defined' in info_val.get('details', '').lower():
                return aid
        for aid, info_val in assemblies.items():
            if 'software_defined' in info_val.get('details', '').lower():
                return aid
        return next(iter(assemblies))

    def apply_oper_to_atoms(self, atoms: List[Dict], oper: Dict) -> List[Dict]:
        """Apply a symmetry operation (rotation matrix + translation) to atom coordinates.

        Args:
            atoms: list of atom dicts with 'Cartn_x', 'Cartn_y', 'Cartn_z' keys.
            oper:  dict with 'matrix' ([[float]*3]*3) and 'vector' ([float]*3).

        Returns:
            New list of atom dicts with transformed coordinates (deep-copied).
        """
        import copy
        R = oper['matrix']
        t = oper['vector']
        transformed = []
        for atom in atoms:
            new_atom = copy.copy(atom)
            try:
                x = float(atom.get('Cartn_x', 0))
                y = float(atom.get('Cartn_y', 0))
                z = float(atom.get('Cartn_z', 0))
                new_atom['Cartn_x'] = f"{R[0][0]*x + R[0][1]*y + R[0][2]*z + t[0]:.3f}"
                new_atom['Cartn_y'] = f"{R[1][0]*x + R[1][1]*y + R[1][2]*z + t[1]:.3f}"
                new_atom['Cartn_z'] = f"{R[2][0]*x + R[2][1]*y + R[2][2]*z + t[2]:.3f}"
            except (TypeError, ValueError):
                pass
            transformed.append(new_atom)
        return transformed

    def _print_assembly_info(self, assembly_info: Dict) -> None:
        """Print a summary table of available assemblies."""
        assemblies = assembly_info.get('assemblies', {})
        assembly_gen = assembly_info.get('assembly_gen', [])
        if not assemblies:
            info("No biological assembly information found in CIF.")
            return

        # Build per-assembly chain summary
        chain_summary: Dict[str, List[str]] = {}
        for row in assembly_gen:
            aid = row['assembly_id']
            n_opers = len(row['oper_ids'])
            chains_str = ','.join(row['chain_ids'])
            if n_opers > 1:
                chains_str += f" (x{n_opers} ops)"
            chain_summary.setdefault(aid, []).append(chains_str)

        section(f"Available biological assemblies for {self.pdb_id}")
        info(f"  {'ID':<4}  {'Details':<38}  {'Oligomer':<12}  Chains")
        info(f"  {'-'*4}  {'-'*38}  {'-'*12}  {'-'*20}")
        for aid, info_val in assemblies.items():
            details = info_val.get('details', '?')
            oligo = info_val.get('oligomeric_details', '?')
            chains_col = '; '.join(chain_summary.get(aid, ['?']))
            marker = ' *' if 'author_and_software_defined' in details.lower() else ''
            info(f"  {aid:<4}  {details+marker:<38}  {oligo:<12}  {chains_col}")

    def get_assembly_chains(
        self,
        assembly_id: str,
        assembly_info: Dict,
    ) -> Tuple[List[str], Dict[str, List[Dict]]]:
        """Get chains for a given assembly, applying symmetry operations where needed.

        For identity operations: chains are included as-is.
        For non-identity operations: atom coordinates are transformed and stored in
        a synthetic-atom cache under a new chain ID ("<original>-<oper_id>").

        Returns:
            (chain_id_list, synthetic_atom_cache)
            - chain_id_list: ordered list of label_asym_ids to process
            - synthetic_atom_cache: {new_chain_id: [transformed atom dicts]}
        """
        assembly_gen = assembly_info.get('assembly_gen', [])
        operations = assembly_info.get('operations', {})

        # Build a map of label_asym_id -> entity type to filter out water chains
        cif_dict = self._get_cif_dict()
        chain_entity_type_map: Dict[str, str] = {}
        if '_struct_asym.id' in cif_dict and '_struct_asym.entity_id' in cif_dict:
            asym_ids_list = cif_dict['_struct_asym.id']
            asym_eid_list = cif_dict['_struct_asym.entity_id']
            entity_type_map: Dict[str, str] = {}
            if '_entity.id' in cif_dict and '_entity.type' in cif_dict:
                for eid, etype in zip(cif_dict['_entity.id'], cif_dict['_entity.type']):
                    entity_type_map[str(eid)] = str(etype).strip().lower()
            if isinstance(asym_ids_list, str):
                asym_ids_list = [asym_ids_list]
            if isinstance(asym_eid_list, str):
                asym_eid_list = [asym_eid_list]
            for aid, eid in zip(asym_ids_list, asym_eid_list):
                chain_entity_type_map[str(aid)] = entity_type_map.get(str(eid), 'polymer')

        # Collect all rows for this assembly
        rows = [r for r in assembly_gen if r['assembly_id'] == str(assembly_id)]
        if not rows:
            warning(f"Assembly {assembly_id} not found in assembly_gen table.")
            return [], {}

        chain_id_list: List[str] = []
        synthetic_cache: Dict[str, List[Dict]] = {}
        seen: set = set()

        for row in rows:
            gen_chains = row['chain_ids']
            oper_ids = row['oper_ids']
            for oper_id in oper_ids:
                oper = operations.get(str(oper_id))
                if oper is None:
                    warning(f"Operation {oper_id} not found; skipping.")
                    continue
                is_identity = 'identity' in oper.get('type', '').lower()
                for orig_chain in gen_chains:
                    # Skip water chains (unless --include-solvent is set)
                    chain_etype = chain_entity_type_map.get(orig_chain, 'polymer')
                    if 'water' in chain_etype and not self.include_solvent:
                        continue
                    if is_identity:
                        if orig_chain not in seen:
                            chain_id_list.append(orig_chain)
                            seen.add(orig_chain)
                    else:
                        # Create a synthetic chain with transformed coordinates
                        new_chain_id = f"{orig_chain}-{oper_id}"
                        if new_chain_id not in seen:
                            # Parse and transform atoms for this chain
                            orig_atoms = self.parse_atom_records(orig_chain)
                            if orig_atoms:
                                transformed = self.apply_oper_to_atoms(orig_atoms, oper)
                                # Update chain identifiers in each atom
                                for atom in transformed:
                                    atom['label_asym_id'] = new_chain_id
                                    atom['auth_asym_id'] = new_chain_id
                                synthetic_cache[new_chain_id] = transformed
                                chain_id_list.append(new_chain_id)
                                # Propagate entity type if known
                                et = self._assembly_entity_types.get(orig_chain, '')
                                if et:
                                    self._assembly_entity_types[new_chain_id] = et
                                seen.add(new_chain_id)
                            else:
                                warning(f"No atoms for chain {orig_chain}; "
                                        f"skipping synthetic chain {new_chain_id}.")

        return chain_id_list, synthetic_cache
