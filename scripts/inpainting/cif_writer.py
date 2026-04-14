"""
CIF output: struct_conn, chem_comp, crystallographic blocks, and full CIF generation.
"""

from io import StringIO
from typing import Dict, List, Optional, Set, Tuple

from Bio.PDB.MMCIF2Dict import MMCIF2Dict


def _cif_value(v: str) -> str:
    """Return a CIF-safe representation of a string value.

    Values that contain whitespace or start with CIF-special characters
    (_ $ ' " [ ;) are wrapped in single quotes.  Values that themselves
    contain single quotes are wrapped in double quotes instead.
    Plain tokens (including '?' and '.') are returned as-is.

    When both quote types are present, double quotes in the value are
    replaced with prime characters to avoid semicolon text blocks
    (which break CIF loop formatting).
    """
    s = str(v) if v is not None else '?'
    if not s:
        return '?'
    # Already a CIF null/unknown placeholder
    if s in ('?', '.'):
        return s
    # Check if quoting is needed
    needs_quote = (
        ' ' in s or '\t' in s or '\n' in s
        or s[0] in ('_', '$', '[', ';', '"', "'")
    )
    if not needs_quote:
        return s
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    # Both quote types present — strip double quotes so we can use
    # double-quote wrapping (semicolon text blocks break CIF loops)
    s = s.replace('"', "'")
    return f'"{s}"'


def format_sequence_for_cif(sequence: str, width: int = 80) -> str:
    """Format sequence for CIF file with specified line width."""
    lines = []
    for i in range(0, len(sequence), width):
        lines.append(sequence[i:i+width])
    return '\n'.join(lines)


def _atom_coord_lookup(atoms_by_chain: Optional[Dict[str, List[Dict]]]):
    """Build a lookup (label_asym_id, label_seq_id, label_atom_id) → (x, y, z).

    Returns a function that looks up atom coordinates by CIF struct_conn partner
    fields.  ``label_seq_id`` may be '?' or '.' for non-polymer entities; in that
    case the function also accepts auth_seq_id as a fallback.
    """
    if not atoms_by_chain:
        return lambda *_args, **_kw: None

    table: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}
    auth_table: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}
    for chain_id, atoms in atoms_by_chain.items():
        for atom in atoms:
            try:
                x = float(atom.get('Cartn_x'))
                y = float(atom.get('Cartn_y'))
                z = float(atom.get('Cartn_z'))
            except (TypeError, ValueError):
                continue
            label_seq = str(atom.get('label_seq_id', '?'))
            auth_seq = str(atom.get('auth_seq_id', '?'))
            atom_name = str(atom.get('label_atom_id', ''))
            label_asym = str(atom.get('label_asym_id', chain_id))
            table[(label_asym, label_seq, atom_name)] = (x, y, z)
            auth_table[(label_asym, auth_seq, atom_name)] = (x, y, z)

    def lookup(asym_id: str, seq_id: str, atom_name: str):
        key = (asym_id, str(seq_id), atom_name)
        if key in table:
            return table[key]
        if key in auth_table:
            return auth_table[key]
        return None

    return lookup


def parse_struct_conn(
    cif_content: Optional[str],
    chain_ids: Set[str],
    atoms_by_chain: Optional[Dict[str, List[Dict]]] = None,
    max_bond_distance: float = 3.5,
) -> Tuple[List[Dict[str, str]], Set[str]]:
    """Parse _struct_conn from source CIF; return rows for selected chains and conn_type_ids.

    When ``atoms_by_chain`` is provided, each bond's distance is recomputed from
    the actual (possibly regenerated) atom coordinates.  Bonds whose recomputed
    distance exceeds ``max_bond_distance`` are dropped — they would otherwise
    falsely claim an unbroken covalent link that the generated coordinates do
    not support.  The ``pdbx_dist_value`` field is rewritten with the new
    distance so downstream consumers see a value consistent with the output
    coordinates.
    """
    if not cif_content:
        return [], set()
    try:
        cif_dict = MMCIF2Dict(StringIO(cif_content))
    except Exception:
        return [], set()
    conn_keys = [k for k in cif_dict if k.startswith('_struct_conn.') and not k.startswith('_struct_conn_type')]
    if not conn_keys:
        return [], set()
    n = None
    for k in conn_keys:
        v = cif_dict[k]
        if isinstance(v, list):
            n = min(len(v), n) if n is not None else len(v)
        else:
            if n is None:
                n = 1
            cif_dict[k] = [v]
    if n is None or n == 0:
        return [], set()

    coord_lookup = _atom_coord_lookup(atoms_by_chain)
    rows = []
    dropped = 0
    for i in range(n):
        row = {k: (cif_dict[k][i] if i < len(cif_dict[k]) else '?') for k in conn_keys}
        p1 = row.get('_struct_conn.ptnr1_label_asym_id', '')
        p2 = row.get('_struct_conn.ptnr2_label_asym_id', '')
        if p1 not in chain_ids or p2 not in chain_ids:
            continue

        if atoms_by_chain:
            c1 = coord_lookup(
                p1,
                row.get('_struct_conn.ptnr1_label_seq_id', '?'),
                row.get('_struct_conn.ptnr1_label_atom_id', ''),
            )
            c2 = coord_lookup(
                p2,
                row.get('_struct_conn.ptnr2_label_seq_id', '?'),
                row.get('_struct_conn.ptnr2_label_atom_id', ''),
            )
            if c1 is not None and c2 is not None:
                dist = ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5
                if dist > max_bond_distance:
                    dropped += 1
                    continue
                row['_struct_conn.pdbx_dist_value'] = f"{dist:.3f}"

        rows.append(row)
    conn_type_ids = {row.get('_struct_conn.conn_type_id', 'covale') for row in rows}
    if dropped:
        # Inform the caller via a side-channel — parse_struct_conn is used in a
        # few places; logging here keeps the signature compatible.
        try:
            from .processor.log import warning
            warning(f"Dropped {dropped} _struct_conn record(s) whose recomputed "
                    f"distance exceeded {max_bond_distance}Å (likely broken by inpainting).")
        except Exception:
            pass
    return rows, conn_type_ids


def parse_chem_comp(cif_content: Optional[str], comp_ids: Set[str]) -> List[str]:
    """Parse _chem_comp from source CIF for given comp_ids. Returns list of data lines."""
    if not cif_content or not comp_ids:
        return []
    try:
        cif_dict = MMCIF2Dict(StringIO(cif_content))
    except Exception:
        return []
    if '_chem_comp.id' not in cif_dict:
        return []
    ids_ = cif_dict['_chem_comp.id']
    if isinstance(ids_, str):
        ids_ = [ids_]
    keys = ['_chem_comp.id', '_chem_comp.type', '_chem_comp.mon_nstd_flag', '_chem_comp.name',
            '_chem_comp.pdbx_synonyms', '_chem_comp.formula', '_chem_comp.formula_weight']
    for k in keys:
        if k not in cif_dict:
            return []
    n = len(ids_)
    for k in keys:
        v = cif_dict[k]
        if not isinstance(v, list):
            cif_dict[k] = [v] * n

    comp_id_set = {c.upper() for c in comp_ids}
    found_ids = set()
    lines = []
    for i, cid in enumerate(ids_):
        if cid.upper() not in comp_id_set:
            continue
        found_ids.add(cid.upper())
        parts = [
            _cif_value(str(cif_dict[k][i]).strip().replace('\n', ' ') if i < len(cif_dict[k]) else '?')
            for k in keys
        ]
        lines.append(' '.join(parts))
    for cid in comp_ids:
        if cid.upper() in found_ids:
            continue
        lines.append(f"{cid} ? ? ? ? ? ?")
    return lines


def parse_crystallographic_blocks(cif_content: Optional[str], pdb_id: str) -> Tuple[List[str], List[str], List[str]]:
    """Parse _cell, _symmetry, _atom_sites from source CIF."""
    cell_lines: List[str] = []
    symmetry_lines: List[str] = []
    atom_sites_lines: List[str] = []
    if not cif_content:
        return cell_lines, symmetry_lines, atom_sites_lines
    try:
        cif_dict = MMCIF2Dict(StringIO(cif_content))
    except Exception:
        return cell_lines, symmetry_lines, atom_sites_lines
    entry = pdb_id
    if '_cell.entry_id' in cif_dict:
        def g(k: str, default: str = '?') -> str:
            v = cif_dict.get(k, default)
            return v if isinstance(v, str) else (v[0] if v else default)
        cell_lines = [
            f"_cell.entry_id           {entry}",
            f"_cell.length_a           {g('_cell.length_a')}",
            f"_cell.length_b           {g('_cell.length_b')}",
            f"_cell.length_c           {g('_cell.length_c')}",
            f"_cell.angle_alpha        {g('_cell.angle_alpha')}",
            f"_cell.angle_beta         {g('_cell.angle_beta')}",
            f"_cell.angle_gamma        {g('_cell.angle_gamma')}",
            f"_cell.Z_PDB              {g('_cell.Z_PDB')}",
        ]
    if '_symmetry.entry_id' in cif_dict:
        def s(k: str, default: str = '?') -> str:
            v = cif_dict.get(k, default)
            v = v if isinstance(v, str) else (v[0] if v else default)
            if v and v != '?' and ' ' in v and not (v.startswith("'") or v.startswith('"')):
                v = f"'{v}'"
            return v
        symmetry_lines = [
            f"_symmetry.entry_id                         {entry}",
            f"_symmetry.space_group_name_H-M             {s('_symmetry.space_group_name_H-M')}",
            f"_symmetry.pdbx_full_space_group_name_H-M   {s('_symmetry.pdbx_full_space_group_name_H-M', '?')}",
            f"_symmetry.cell_setting                     {s('_symmetry.cell_setting', '?')}",
            f"_symmetry.Int_Tables_number                {s('_symmetry.Int_Tables_number', '?')}",
        ]
    if '_atom_sites.entry_id' in cif_dict:
        def a(k: str, default: str = '?') -> str:
            v = cif_dict.get(k, default)
            return v if isinstance(v, str) else (v[0] if v else default)
        atom_sites_lines = [
            f"_atom_sites.entry_id                    {entry}",
            f"_atom_sites.fract_transf_matrix[1][1]   {a('_atom_sites.fract_transf_matrix[1][1]')}",
            f"_atom_sites.fract_transf_matrix[1][2]   {a('_atom_sites.fract_transf_matrix[1][2]')}",
            f"_atom_sites.fract_transf_matrix[1][3]   {a('_atom_sites.fract_transf_matrix[1][3]')}",
            f"_atom_sites.fract_transf_matrix[2][1]   {a('_atom_sites.fract_transf_matrix[2][1]')}",
            f"_atom_sites.fract_transf_matrix[2][2]   {a('_atom_sites.fract_transf_matrix[2][2]')}",
            f"_atom_sites.fract_transf_matrix[2][3]   {a('_atom_sites.fract_transf_matrix[2][3]')}",
            f"_atom_sites.fract_transf_matrix[3][1]   {a('_atom_sites.fract_transf_matrix[3][1]')}",
            f"_atom_sites.fract_transf_matrix[3][2]   {a('_atom_sites.fract_transf_matrix[3][2]')}",
            f"_atom_sites.fract_transf_matrix[3][3]   {a('_atom_sites.fract_transf_matrix[3][3]')}",
            f"_atom_sites.fract_transf_vector[1]      {a('_atom_sites.fract_transf_vector[1]')}",
            f"_atom_sites.fract_transf_vector[2]      {a('_atom_sites.fract_transf_vector[2]')}",
            f"_atom_sites.fract_transf_vector[3]      {a('_atom_sites.fract_transf_vector[3]')}",
        ]
    return cell_lines, symmetry_lines, atom_sites_lines


def generate_cif(
    pdb_id: str,
    chain_ids: List[str],
    all_chains_data: Dict[str, Dict],
    solvent_atoms: Optional[List[Dict]],
    cif_content: Optional[str],
    modifications_from_entity_poly: Dict,
) -> str:
    """Generate complete CIF file for multiple chains."""
    lines = []
    solvent_atoms = solvent_atoms or []
    max_entity_id = max(d['entity_id'] for d in all_chains_data.values()) if all_chains_data else 0
    water_entity_id = max_entity_id + 1 if solvent_atoms else None

    lines.append(f"data_{pdb_id}")
    lines.append("#")
    lines.append(f"_entry.id                                {pdb_id}")
    lines.append("_audit_conform.dict_name                 mmcif_pdbx.dic")
    lines.append("_audit_conform.dict_version              5.397")
    lines.append("_audit_conform.dict_location             http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic")
    lines.append("_pdbx_database_status.status_code        REL")
    lines.append(f"_pdbx_database_status.entry_id           {pdb_id}")
    lines.append("#")

    lines.append("loop_")
    lines.append("_entity.id")
    lines.append("_entity.type")
    lines.append("_entity.src_method")
    lines.append("_entity.pdbx_description")
    lines.append("_entity.formula_weight")
    lines.append("_entity.pdbx_number_of_molecules")
    lines.append("_entity.pdbx_ec")
    lines.append("_entity.pdbx_mutation")
    lines.append("_entity.pdbx_fragment")
    lines.append("_entity.details")
    for chain_id in chain_ids:
        entity_id = all_chains_data[chain_id]['entity_id']
        entity_type = all_chains_data[chain_id].get('entity_type', 'protein')
        if entity_type == 'ligand':
            ccd = all_chains_data[chain_id].get('ccd', 'UNK')
            lines.append(f"{entity_id} non-polymer man 'Ligand {ccd}' ? 1 ? ? ? ?")
        else:
            lines.append(f"{entity_id} polymer man 'Protein chain' ? 1 ? ? ? ?")
    if water_entity_id is not None:
        lines.append(f"{water_entity_id} water man 'Water' ? ? ? ? ? ?")
    lines.append("#")

    lines.append("loop_")
    lines.append("_entity_name_com.entity_id")
    lines.append("_entity_name_com.name")
    for chain_id in chain_ids:
        entity_id = all_chains_data[chain_id]['entity_id']
        lines.append(f"{entity_id} 'Chain {chain_id}'")
    if water_entity_id is not None:
        lines.append(f"{water_entity_id} 'Water'")
    lines.append("#")

    polymer_chain_ids = [c for c in chain_ids if all_chains_data[c].get('entity_type') != 'ligand']
    aa_one = {'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F', 'GLY': 'G',
              'HIS': 'H', 'ILE': 'I', 'LYS': 'K', 'LEU': 'L', 'MET': 'M', 'ASN': 'N',
              'PRO': 'P', 'GLN': 'Q', 'ARG': 'R', 'SER': 'S', 'THR': 'T', 'VAL': 'V',
              'TRP': 'W', 'TYR': 'Y'}
    aa_codes = {'A': 'ALA', 'C': 'CYS', 'D': 'ASP', 'E': 'GLU', 'F': 'PHE', 'G': 'GLY', 'H': 'HIS', 'I': 'ILE',
                'K': 'LYS', 'L': 'LEU', 'M': 'MET', 'N': 'ASN', 'P': 'PRO', 'Q': 'GLN', 'R': 'ARG', 'S': 'SER',
                'T': 'THR', 'V': 'VAL', 'W': 'TRP', 'Y': 'TYR'}
    dna_codes = {'A': 'DA', 'C': 'DC', 'G': 'DG', 'T': 'DT', 'I': 'DI'}
    rna_codes = {'A': 'A', 'C': 'C', 'G': 'G', 'U': 'U', 'I': 'I'}
    aa_codes_3 = {'A': 'ALA', 'C': 'CYS', 'D': 'ASP', 'E': 'GLU', 'F': 'PHE', 'G': 'GLY', 'H': 'HIS', 'I': 'ILE',
                 'K': 'LYS', 'L': 'LEU', 'M': 'MET', 'N': 'ASN', 'P': 'PRO', 'Q': 'GLN', 'R': 'ARG', 'S': 'SER',
                 'T': 'THR', 'V': 'VAL', 'W': 'TRP', 'Y': 'TYR'}

    if polymer_chain_ids:
        lines.append("loop_")
        lines.append("_entity_poly.entity_id")
        lines.append("_entity_poly.type")
        lines.append("_entity_poly.nstd_linkage")
        lines.append("_entity_poly.nstd_monomer")
        lines.append("_entity_poly.pdbx_seq_one_letter_code")
        lines.append("_entity_poly.pdbx_seq_one_letter_code_can")
        lines.append("_entity_poly.pdbx_strand_id")
        lines.append("_entity_poly.pdbx_target_identifier")
        for chain_id in polymer_chain_ids:
            entity_id = all_chains_data[chain_id]['entity_id']
            sequence = all_chains_data[chain_id]['sequence']
            entity_type = all_chains_data[chain_id].get('entity_type', 'protein')
            if entity_type == 'dna':
                poly_type = 'polydeoxyribonucleotide'
            elif entity_type == 'rna':
                poly_type = 'polyribonucleotide'
            else:
                poly_type = 'polypeptide(L)'
            has_mods = bool(modifications_from_entity_poly.get(chain_id))
            nstd_monomer = 'yes' if has_mods else 'no'
            lines.append(f"{entity_id} {poly_type} no {nstd_monomer}")
            if has_mods and entity_type == 'protein':
                mod_positions = {m['position']: m['ccd'] for m in modifications_from_entity_poly.get(chain_id, [])}
                bracketed_seq = []
                for pos, aa in enumerate(sequence, 1):
                    if pos in mod_positions:
                        bracketed_seq.append(f"({mod_positions[pos]})")
                    else:
                        bracketed_seq.append(aa)
                formatted_seq = ''.join(bracketed_seq)
            else:
                formatted_seq = sequence
            lines.append(";")
            lines.append(format_sequence_for_cif(formatted_seq))
            lines.append(";")
            lines.append("")
            # Use bracketed form for second field when we have mods so gemmi's full_sequence
            # matches entity_poly_seq and atom_site (avoids Alignment mismatch! in boltz parse_polymer)
            lines.append(";")
            lines.append(format_sequence_for_cif(formatted_seq))
            lines.append(";")
            lines.append(f"{chain_id} ?")
        lines.append("#")

        lines.append("loop_")
        lines.append("_entity_poly_seq.entity_id")
        lines.append("_entity_poly_seq.num")
        lines.append("_entity_poly_seq.mon_id")
        lines.append("_entity_poly_seq.hetero")
        for chain_id in polymer_chain_ids:
            entity_id = all_chains_data[chain_id]['entity_id']
            sequence = all_chains_data[chain_id]['sequence']
            entity_type = all_chains_data[chain_id].get('entity_type', 'protein')
            monomer_ids = all_chains_data[chain_id].get('monomer_ids', {})
            mod_pos_to_ccd = {m['position']: m['ccd'] for m in modifications_from_entity_poly.get(chain_id, [])}
            if entity_type == 'dna':
                code_map = dna_codes
            elif entity_type == 'rna':
                code_map = rna_codes
            else:
                code_map = aa_codes
            for i, base in enumerate(sequence, 1):
                if i in monomer_ids:
                    three_letter = monomer_ids[i]
                elif i in mod_pos_to_ccd:
                    three_letter = mod_pos_to_ccd[i]
                else:
                    three_letter = code_map.get(base, 'UNK' if entity_type == 'protein' else base)
                lines.append(f"{entity_id} {i} {three_letter} n")
        lines.append("#")

    comp_ids_for_chem = set()
    for chain_id in chain_ids:
        for atom in all_chains_data[chain_id]['atoms']:
            comp_ids_for_chem.add(atom.get('label_comp_id', ''))
    for atom in solvent_atoms:
        comp_ids_for_chem.add(atom.get('label_comp_id', ''))
    for chain_id in chain_ids:
        seq = all_chains_data[chain_id].get('sequence', '')
        entity_type = all_chains_data[chain_id].get('entity_type', 'protein')
        mod_pos = {m['position']: m['ccd'] for m in modifications_from_entity_poly.get(chain_id, [])}
        monomer_ids = all_chains_data[chain_id].get('monomer_ids', {})
        if entity_type == 'rna':
            seq_code_map = rna_codes
        elif entity_type == 'dna':
            seq_code_map = dna_codes
        else:
            seq_code_map = aa_codes_3
        for i, base in enumerate(seq, 1):
            if i in monomer_ids:
                comp_ids_for_chem.add(monomer_ids[i])
            elif i in mod_pos:
                comp_ids_for_chem.add(mod_pos[i])
            else:
                comp_ids_for_chem.add(seq_code_map.get(base, ''))
    comp_ids_for_chem.discard('')
    chem_comp_lines = parse_chem_comp(cif_content, comp_ids_for_chem)
    if chem_comp_lines:
        lines.append("loop_")
        lines.append("_chem_comp.id")
        lines.append("_chem_comp.type")
        lines.append("_chem_comp.mon_nstd_flag")
        lines.append("_chem_comp.name")
        lines.append("_chem_comp.pdbx_synonyms")
        lines.append("_chem_comp.formula")
        lines.append("_chem_comp.formula_weight")
        lines.extend(chem_comp_lines)
        lines.append("#")

    lines.append("loop_")
    lines.append("_struct_asym.id")
    lines.append("_struct_asym.pdbx_blank_PDB_chainid_flag")
    lines.append("_struct_asym.pdbx_modified")
    lines.append("_struct_asym.entity_id")
    lines.append("_struct_asym.details")
    for chain_id in chain_ids:
        entity_id = all_chains_data[chain_id]['entity_id']
        lines.append(f"{chain_id} N N {entity_id} ?")
    if water_entity_id is not None:
        solvent_asym_ids = sorted({a['label_asym_id'] for a in solvent_atoms}) if solvent_atoms else []
        for asym_id in solvent_asym_ids:
            lines.append(f"{asym_id} N N {water_entity_id} ?")
        if not solvent_asym_ids:
            lines.append(f"W N N {water_entity_id} ?")
    lines.append("#")

    chain_id_set = set(chain_ids)
    # Build chain_id -> atoms mapping so parse_struct_conn can recompute bond
    # distances from actual (possibly regenerated) coordinates.
    atoms_by_chain = {
        cid: all_chains_data[cid].get('atoms', [])
        for cid in chain_ids
        if all_chains_data.get(cid)
    }
    struct_conn_rows, struct_conn_type_ids = parse_struct_conn(
        cif_content, chain_id_set, atoms_by_chain=atoms_by_chain
    )
    author_for_label = {cid: all_chains_data[cid].get('author_chain_id', cid) for cid in chain_ids}
    if struct_conn_rows:
        lines.append("loop_")
        lines.append("_struct_conn_type.id")
        lines.append("_struct_conn_type.criteria")
        lines.append("_struct_conn_type.reference")
        for ctid in sorted(struct_conn_type_ids):
            lines.append(f"{ctid} ? ?")
        lines.append("#")
        struct_conn_keys = [
            '_struct_conn.id', '_struct_conn.conn_type_id', '_struct_conn.pdbx_leaving_atom_flag',
            '_struct_conn.pdbx_PDB_id', '_struct_conn.ptnr1_label_asym_id', '_struct_conn.ptnr1_label_comp_id',
            '_struct_conn.ptnr1_label_seq_id', '_struct_conn.ptnr1_label_atom_id',
            '_struct_conn.pdbx_ptnr1_label_alt_id', '_struct_conn.pdbx_ptnr1_PDB_ins_code',
            '_struct_conn.pdbx_ptnr1_standard_comp_id', '_struct_conn.ptnr1_symmetry',
            '_struct_conn.ptnr2_label_asym_id', '_struct_conn.ptnr2_label_comp_id',
            '_struct_conn.ptnr2_label_seq_id', '_struct_conn.ptnr2_label_atom_id',
            '_struct_conn.pdbx_ptnr2_label_alt_id', '_struct_conn.pdbx_ptnr2_PDB_ins_code',
            '_struct_conn.ptnr1_auth_asym_id', '_struct_conn.ptnr1_auth_comp_id', '_struct_conn.ptnr1_auth_seq_id',
            '_struct_conn.ptnr2_auth_asym_id', '_struct_conn.ptnr2_auth_comp_id', '_struct_conn.ptnr2_auth_seq_id',
            '_struct_conn.ptnr2_symmetry',
            '_struct_conn.pdbx_ptnr3_label_atom_id', '_struct_conn.pdbx_ptnr3_label_seq_id',
            '_struct_conn.pdbx_ptnr3_label_comp_id', '_struct_conn.pdbx_ptnr3_label_asym_id',
            '_struct_conn.pdbx_ptnr3_label_alt_id', '_struct_conn.pdbx_ptnr3_PDB_ins_code',
            '_struct_conn.details', '_struct_conn.pdbx_dist_value', '_struct_conn.pdbx_value_order',
            '_struct_conn.pdbx_role',
        ]
        lines.append("loop_")
        for k in struct_conn_keys:
            lines.append(k)
        for row in struct_conn_rows:
            # label_asym_id: keep source CIF's label_asym_id (unique), which
            # matches the label_asym_id we now write in _atom_site / _struct_asym.
            # auth_asym_id: translate to our output author ID (may collide, but
            # preserved for PDB-format compatibility / viewer tooltips).
            p1_label = row.get('_struct_conn.ptnr1_label_asym_id', '?')
            p2_label = row.get('_struct_conn.ptnr2_label_asym_id', '?')
            out_p1_auth = author_for_label.get(p1_label, row.get('_struct_conn.ptnr1_auth_asym_id', '?'))
            out_p2_auth = author_for_label.get(p2_label, row.get('_struct_conn.ptnr2_auth_asym_id', '?'))
            vals = []
            for k in struct_conn_keys:
                if k == '_struct_conn.ptnr1_auth_asym_id':
                    vals.append(out_p1_auth)
                elif k == '_struct_conn.ptnr2_auth_asym_id':
                    vals.append(out_p2_auth)
                else:
                    vals.append(row.get(k, '?'))
            lines.append(' '.join(_cif_value(v) for v in vals))
        lines.append("#")

    cell_lines, symmetry_lines, atom_sites_lines = parse_crystallographic_blocks(cif_content, pdb_id)
    if cell_lines:
        lines.extend(cell_lines)
        lines.append("#")
    if symmetry_lines:
        lines.extend(symmetry_lines)
        lines.append("#")
    if atom_sites_lines:
        lines.extend(atom_sites_lines)
        lines.append("#")

    lines.append("loop_")
    lines.append("_atom_site.group_PDB")
    lines.append("_atom_site.id")
    lines.append("_atom_site.type_symbol")
    lines.append("_atom_site.label_atom_id")
    lines.append("_atom_site.label_alt_id")
    lines.append("_atom_site.label_comp_id")
    lines.append("_atom_site.label_asym_id")
    lines.append("_atom_site.label_entity_id")
    lines.append("_atom_site.label_seq_id")
    lines.append("_atom_site.pdbx_PDB_ins_code")
    lines.append("_atom_site.Cartn_x")
    lines.append("_atom_site.Cartn_y")
    lines.append("_atom_site.Cartn_z")
    lines.append("_atom_site.occupancy")
    lines.append("_atom_site.B_iso_or_equiv")
    lines.append("_atom_site.pdbx_formal_charge")
    lines.append("_atom_site.auth_seq_id")
    lines.append("_atom_site.auth_comp_id")
    lines.append("_atom_site.auth_asym_id")
    lines.append("_atom_site.auth_atom_id")
    lines.append("_atom_site.pdbx_PDB_model_num")

    # Collect all atom rows as tuples of field values, then column-align them.
    atom_rows: list[list[str]] = []
    next_atom_id = 1
    for chain_id in chain_ids:
        atoms = all_chains_data[chain_id]['atoms']
        # label_asym_id in the output CIF is the processor's chain_id (label).
        # auth_asym_id preserves the original author chain (may collide).
        author_chain_id = all_chains_data[chain_id].get('author_chain_id', chain_id)
        use_atom_for_chain = (
            bool(modifications_from_entity_poly.get(chain_id)) or
            any(a.get('group_PDB') == 'HETATM' for a in atoms)
        )
        for atom in atoms:
            atom_id = next_atom_id
            next_atom_id += 1
            group_pdb = 'ATOM' if use_atom_for_chain else atom['group_PDB']
            atom_rows.append([
                group_pdb, str(atom_id), atom['type_symbol'],
                atom['label_atom_id'], atom['label_alt_id'],
                atom['label_comp_id'], chain_id,
                str(atom['label_entity_id']), str(atom['label_seq_id']),
                atom['pdbx_PDB_ins_code'], atom['Cartn_x'],
                atom['Cartn_y'], atom['Cartn_z'],
                atom['occupancy'], atom['B_iso_or_equiv'],
                atom['pdbx_formal_charge'], str(atom['auth_seq_id']),
                atom['auth_comp_id'], author_chain_id,
                atom['auth_atom_id'], str(atom['pdbx_PDB_model_num']),
            ])
    for atom in solvent_atoms:
        atom_id = next_atom_id
        next_atom_id += 1
        atom_rows.append([
            atom['group_PDB'], str(atom_id), atom['type_symbol'],
            atom['label_atom_id'], atom['label_alt_id'],
            atom['label_comp_id'], atom['auth_asym_id'],
            str(water_entity_id), str(atom['label_seq_id']),
            atom['pdbx_PDB_ins_code'], atom['Cartn_x'],
            atom['Cartn_y'], atom['Cartn_z'],
            atom['occupancy'], atom['B_iso_or_equiv'],
            atom['pdbx_formal_charge'], str(atom['auth_seq_id']),
            atom['auth_comp_id'], atom['auth_asym_id'],
            atom['auth_atom_id'], str(atom['pdbx_PDB_model_num']),
        ])

    # Compute per-column max widths and write column-aligned rows.
    if atom_rows:
        ncols = len(atom_rows[0])
        col_widths = [max(len(row[c]) for row in atom_rows) for c in range(ncols)]
        for row in atom_rows:
            fields = [row[c].ljust(col_widths[c]) for c in range(ncols)]
            lines.append(' '.join(fields))
    lines.append("#")
    return '\n'.join(lines)
