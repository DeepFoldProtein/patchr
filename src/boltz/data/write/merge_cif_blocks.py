"""
Merge struct_conn, chem_comp, cell, symmetry, atom_sites from template CIF into prediction CIF.

Used for inpainting so that the output CIF retains connectivity and crystallographic metadata
from the template (see scripts/inpainting/cif_writer.py).
"""

from io import StringIO
from pathlib import Path
from typing import Optional, Set, Tuple

from Bio.PDB.MMCIF2Dict import MMCIF2Dict


def _get_output_cif_tags(cif_str: str) -> Tuple[Set[str], Set[str]]:
    """Parse prediction CIF string; return set of label_asym_id and set of label_comp_id."""
    chain_ids: Set[str] = set()
    comp_ids: Set[str] = set()
    try:
        d = MMCIF2Dict(StringIO(cif_str))
    except Exception:
        return chain_ids, comp_ids
    if "_atom_site.label_asym_id" in d:
        asym = d["_atom_site.label_asym_id"]
        chain_ids = set(asym) if isinstance(asym, list) else {asym}
    if "_atom_site.label_comp_id" in d:
        comp = d["_atom_site.label_comp_id"]
        comp_ids = set(comp) if isinstance(comp, list) else {comp}
    return chain_ids, comp_ids


def _parse_struct_conn(cif_content: str, chain_ids: Set[str]) -> Tuple[list, set]:
    """Parse _struct_conn from CIF; return rows for selected chains and conn_type_ids."""
    if not cif_content or not chain_ids:
        return [], set()
    try:
        cif_dict = MMCIF2Dict(StringIO(cif_content))
    except Exception:
        return [], set()
    conn_keys = [
        k
        for k in cif_dict
        if k.startswith("_struct_conn.") and not k.startswith("_struct_conn_type")
    ]
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
    rows = []
    for i in range(n):
        row = {k: (cif_dict[k][i] if i < len(cif_dict[k]) else "?") for k in conn_keys}
        p1 = row.get("_struct_conn.ptnr1_label_asym_id", "")
        p2 = row.get("_struct_conn.ptnr2_label_asym_id", "")
        if p1 in chain_ids and p2 in chain_ids:
            rows.append(row)
    conn_type_ids = {row.get("_struct_conn.conn_type_id", "covale") for row in rows}
    return rows, conn_type_ids


def _parse_chem_comp(cif_content: str, comp_ids: Set[str]) -> list:
    """Parse _chem_comp from CIF for given comp_ids. Returns list of data lines."""
    if not cif_content or not comp_ids:
        return []
    try:
        cif_dict = MMCIF2Dict(StringIO(cif_content))
    except Exception:
        return []
    if "_chem_comp.id" not in cif_dict:
        return []
    ids_ = cif_dict["_chem_comp.id"]
    if isinstance(ids_, str):
        ids_ = [ids_]
    keys = [
        "_chem_comp.id",
        "_chem_comp.type",
        "_chem_comp.mon_nstd_flag",
        "_chem_comp.name",
        "_chem_comp.pdbx_synonyms",
        "_chem_comp.formula",
        "_chem_comp.formula_weight",
    ]
    for k in keys:
        if k not in cif_dict:
            return []
    n = len(ids_)
    for k in keys:
        v = cif_dict[k]
        if not isinstance(v, list):
            cif_dict[k] = [v] * n

    def _quote(s: str) -> str:
        s = str(s).strip() if s not in (None, "") else "?"
        if s == "?" or s == ".":
            return s
        if " " in s or s.startswith("'") or s.startswith('"'):
            return s if s.startswith("'") else f"'{s}'"
        return s

    comp_id_set = {c.upper() for c in comp_ids}
    found_ids = set()
    lines = []
    for i, cid in enumerate(ids_):
        if cid.upper() not in comp_id_set:
            continue
        found_ids.add(cid.upper())
        parts = [_quote(cif_dict[k][i] if i < len(cif_dict[k]) else "?") for k in keys]
        lines.append(" ".join(parts))
    for cid in comp_ids:
        if cid.upper() in found_ids:
            continue
        lines.append(f"{cid} ? ? ? ? ? ? ?")
    return lines


def _parse_crystallographic(
    cif_content: str, entry_id: str
) -> Tuple[list, list, list]:
    """Parse _cell, _symmetry, _atom_sites from CIF."""
    cell_lines = []
    symmetry_lines = []
    atom_sites_lines = []
    if not cif_content:
        return cell_lines, symmetry_lines, atom_sites_lines
    try:
        cif_dict = MMCIF2Dict(StringIO(cif_content))
    except Exception:
        return cell_lines, symmetry_lines, atom_sites_lines
    entry = entry_id
    if "_cell.entry_id" in cif_dict:
        def g(k: str, default: str = "?") -> str:
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
    if "_symmetry.entry_id" in cif_dict:
        def s(k: str, default: str = "?") -> str:
            v = cif_dict.get(k, default)
            v = v if isinstance(v, str) else (v[0] if v else default)
            if v and v != "?" and " " in v and not (v.startswith("'") or v.startswith('"')):
                v = f"'{v}'"
            return v

        symmetry_lines = [
            f"_symmetry.entry_id                         {entry}",
            f"_symmetry.space_group_name_H-M             {s('_symmetry.space_group_name_H-M')}",
            f"_symmetry.pdbx_full_space_group_name_H-M   {s('_symmetry.pdbx_full_space_group_name_H-M', '?')}",
            f"_symmetry.cell_setting                     {s('_symmetry.cell_setting', '?')}",
            f"_symmetry.Int_Tables_number                {s('_symmetry.Int_Tables_number', '?')}",
        ]
    if "_atom_sites.entry_id" in cif_dict:
        def a(k: str, default: str = "?") -> str:
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


def _quote_cif(v: str) -> str:
    """Quote an mmCIF value if it contains whitespace (required by the mmCIF spec)."""
    s = str(v) if v is not None else "?"
    if s in ("?", "."):
        return s
    if " " in s or "\t" in s:
        # prefer single-quote wrapping; escape internal single quotes if needed
        if "'" not in s:
            return f"'{s}'"
        if '"' not in s:
            return f'"{s}"'
        # both quote types present — escape single quotes
        return "'" + s.replace("'", "\\'") + "'"
    return s


_STRUCT_CONN_KEYS = [
    "_struct_conn.id",
    "_struct_conn.conn_type_id",
    "_struct_conn.pdbx_leaving_atom_flag",
    "_struct_conn.pdbx_PDB_id",
    "_struct_conn.ptnr1_label_asym_id",
    "_struct_conn.ptnr1_label_comp_id",
    "_struct_conn.ptnr1_label_seq_id",
    "_struct_conn.ptnr1_label_atom_id",
    "_struct_conn.pdbx_ptnr1_label_alt_id",
    "_struct_conn.pdbx_ptnr1_PDB_ins_code",
    "_struct_conn.pdbx_ptnr1_standard_comp_id",
    "_struct_conn.ptnr1_symmetry",
    "_struct_conn.ptnr2_label_asym_id",
    "_struct_conn.ptnr2_label_comp_id",
    "_struct_conn.ptnr2_label_seq_id",
    "_struct_conn.ptnr2_label_atom_id",
    "_struct_conn.pdbx_ptnr2_label_alt_id",
    "_struct_conn.pdbx_ptnr2_PDB_ins_code",
    "_struct_conn.ptnr1_auth_asym_id",
    "_struct_conn.ptnr1_auth_comp_id",
    "_struct_conn.ptnr1_auth_seq_id",
    "_struct_conn.ptnr2_auth_asym_id",
    "_struct_conn.ptnr2_auth_comp_id",
    "_struct_conn.ptnr2_auth_seq_id",
    "_struct_conn.ptnr2_symmetry",
    "_struct_conn.pdbx_ptnr3_label_atom_id",
    "_struct_conn.pdbx_ptnr3_label_seq_id",
    "_struct_conn.pdbx_ptnr3_label_comp_id",
    "_struct_conn.pdbx_ptnr3_label_asym_id",
    "_struct_conn.pdbx_ptnr3_label_alt_id",
    "_struct_conn.pdbx_ptnr3_PDB_ins_code",
    "_struct_conn.details",
    "_struct_conn.pdbx_dist_value",
    "_struct_conn.pdbx_value_order",
    "_struct_conn.pdbx_role",
]


def merge_template_blocks_into_cif(
    output_cif_str: str,
    template_cif_path: str,
    entry_id: Optional[str] = None,
) -> str:
    """Append struct_conn, chem_comp, cell, symmetry, atom_sites from template CIF to prediction CIF.

    Parameters
    ----------
    output_cif_str : str
        The prediction CIF string (from to_mmcif).
    template_cif_path : str
        Path to the template/structure CIF file.
    entry_id : str, optional
        Entry id for cell/symmetry/atom_sites (default: from first data_ in output CIF).

    Returns
    -------
    str
        output_cif_str with template blocks appended (only chains/comp_ids present in output are kept).
    """
    path = Path(template_cif_path)
    if not path.is_file():
        return output_cif_str
    try:
        template_content = path.read_text()
    except Exception:
        return output_cif_str

    chain_ids, comp_ids = _get_output_cif_tags(output_cif_str)

    if entry_id is None:
        for line in output_cif_str.splitlines():
            if line.startswith("data_"):
                entry_id = line.split("data_")[-1].strip()
                break
        if not entry_id:
            entry_id = "prediction"

    # Collect comp_ids from template so we can include chem_comp even when output uses different tags
    try:
        td = MMCIF2Dict(StringIO(template_content))
        if "_atom_site.label_comp_id" in td:
            tc = td["_atom_site.label_comp_id"]
            comp_ids = comp_ids | (set(tc) if isinstance(tc, list) else {tc})
    except Exception:
        pass

    extra: list[str] = []

    struct_conn_rows, struct_conn_type_ids = _parse_struct_conn(
        template_content, chain_ids
    )
    if struct_conn_rows:
        extra.append("loop_")
        extra.append("_struct_conn_type.id")
        extra.append("_struct_conn_type.criteria")
        extra.append("_struct_conn_type.reference")
        for ctid in sorted(struct_conn_type_ids):
            extra.append(f"{ctid} ? ?")
        extra.append("#")
        extra.append("loop_")
        for k in _STRUCT_CONN_KEYS:
            extra.append(k)
        for row in struct_conn_rows:
            vals = [row.get(k, "?") for k in _STRUCT_CONN_KEYS]
            extra.append(" ".join(_quote_cif(v) for v in vals))
        extra.append("#")

    chem_comp_lines = _parse_chem_comp(template_content, comp_ids)
    if chem_comp_lines:
        extra.append("loop_")
        extra.append("_chem_comp.id")
        extra.append("_chem_comp.type")
        extra.append("_chem_comp.mon_nstd_flag")
        extra.append("_chem_comp.name")
        extra.append("_chem_comp.pdbx_synonyms")
        extra.append("_chem_comp.formula")
        extra.append("_chem_comp.formula_weight")
        extra.extend(chem_comp_lines)
        extra.append("#")

    cell_lines, symmetry_lines, atom_sites_lines = _parse_crystallographic(
        template_content, entry_id
    )
    if cell_lines:
        extra.extend(cell_lines)
        extra.append("#")
    if symmetry_lines:
        extra.extend(symmetry_lines)
        extra.append("#")
    if atom_sites_lines:
        extra.extend(atom_sites_lines)
        extra.append("#")

    if not extra:
        return output_cif_str
    return output_cif_str.rstrip() + "\n" + "\n".join(extra) + "\n"
