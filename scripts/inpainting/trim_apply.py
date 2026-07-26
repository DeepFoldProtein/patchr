"""Apply --skip-terminal trim at predict time.

The template YAML/CIF store the FULL canonical sequence with original SEQRES numbering
(label_seq_id) and a per-chain ``trim: {kept_start, kept_end}`` marking the observed
range. Boltz would otherwise try to generate the trimmed terminal residues, so before
prediction we slice the sequence, template structure and inpainting metadata to the kept
range and renumber to 1..N — exactly the artifact the old inline --skip-terminal produced,
but reconstructed from the full-numbered template. Boltz internals are untouched.

Entry point: ``apply_trim(yaml_path, work_dir) -> Path`` returns a path to a
prediction-ready YAML (a new sliced copy when any chain is trimmed, else the original).
"""

import json
import shutil
from pathlib import Path

import gemmi
import yaml as _yaml


def _load_yaml(p: Path):
    with open(p) as f:
        return _yaml.safe_load(f)


def _chain_entities(cif_block):
    """label_asym_id -> entity_id from _struct_asym."""
    cat = cif_block.get_mmcif_category("_struct_asym.")
    if not cat:
        return {}
    return {a: e for a, e in zip(cat["id"], cat["entity_id"])}


def _slice_atom_site(block, trims):
    """Keep atoms whose (chain) label_seq_id is in that chain's kept range; renumber.

    trims: label_asym_id -> (kept_start, kept_end). Chains not in trims are untouched.
    """
    cat = block.get_mmcif_category("_atom_site.", raw=False)
    if not cat:
        return
    n = len(cat["id"])
    keep = [True] * n
    for i in range(n):
        ch = cat["label_asym_id"][i]
        tr = trims.get(ch)
        if tr is None:
            continue
        ks, ke = tr
        sid = cat["label_seq_id"][i]
        if sid in (".", "?", None):
            continue  # non-polymer atom (ligand) — keep as-is
        try:
            pos = int(sid)
        except (TypeError, ValueError):
            continue
        if pos < ks or pos > ke:
            keep[i] = False
        else:
            new = str(pos - (ks - 1))
            cat["label_seq_id"][i] = new
            # auth_seq_id mirrors label_seq_id in patchr output
            if "auth_seq_id" in cat:
                cat["auth_seq_id"][i] = new
    new_cat = {k: [v[i] for i in range(n) if keep[i]] for k, v in cat.items()}
    block.set_mmcif_category("_atom_site.", new_cat)


def _slice_entity_poly_seq(block, entity_trims):
    """Slice _entity_poly_seq per entity to its kept range and renumber num from 1."""
    cat = block.get_mmcif_category("_entity_poly_seq.")
    if not cat:
        return
    n = len(cat["num"])
    keep = [True] * n
    for i in range(n):
        eid = cat["entity_id"][i]
        tr = entity_trims.get(eid)
        if tr is None:
            continue
        ks, ke = tr
        try:
            num = int(cat["num"][i])
        except (TypeError, ValueError):
            continue
        if num < ks or num > ke:
            keep[i] = False
        else:
            cat["num"][i] = str(num - (ks - 1))
    new_cat = {k: [v[i] for i in range(n) if keep[i]] for k, v in cat.items()}
    block.set_mmcif_category("_entity_poly_seq.", new_cat)


def _slice_entity_poly_can(block, entity_trims):
    """Slice _entity_poly one-letter sequences to the kept range."""
    cat = block.get_mmcif_category("_entity_poly.")
    if not cat:
        return
    for i in range(len(cat.get("entity_id", []))):
        eid = cat["entity_id"][i]
        tr = entity_trims.get(eid)
        if tr is None:
            continue
        ks, ke = tr
        for key in ("pdbx_seq_one_letter_code_can", "pdbx_seq_one_letter_code"):
            if key in cat and cat[key][i] not in (None, ".", "?"):
                s = "".join(cat[key][i].split())
                # only safe for canonical (1 char/residue); the non-canonical
                # code may contain (XXX) tokens, so slice only the canonical field
                if key == "pdbx_seq_one_letter_code_can" and len(s) >= ke:
                    cat[key][i] = s[ks - 1:ke]
    block.set_mmcif_category("_entity_poly.", cat)


def _slice_metadata(meta, chain_trims):
    """Shift/filter inpainting metadata residue lists to the kept range (renumber to 1)."""
    chains = meta.get("chains", {})
    for ch, block in chains.items():
        tr = chain_trims.get(ch)
        if tr is None:
            continue
        ks, ke = tr

        def _sf(residues):
            return [r - (ks - 1) for r in residues if ks <= r <= ke]

        for key in ("fully_fixed_residues", "fully_inpainted_residues"):
            if key in block:
                block[key] = _sf(block[key])
        if "partially_fixed_residues" in block:
            block["partially_fixed_residues"] = [
                {**e, "residue": e["residue"] - (ks - 1)}
                for e in block["partially_fixed_residues"]
                if ks <= e.get("residue", -1) <= ke
            ]
    return meta


def _apply_one(doc, assets: Path):
    """Slice a single YAML dict; sliced CIF/metadata written under `assets`. -> dict or None."""
    seqs = doc.get("sequences", [])
    # chain_id -> (kept_start, kept_end)
    chain_trims = {}
    for item in seqs:
        for etype in ("protein", "dna", "rna"):
            if etype in item:
                c = item[etype]
                tr = c.get("trim")
                if tr:
                    chain_trims[str(c["id"])] = (int(tr["kept_start"]), int(tr["kept_end"]))
    if not chain_trims:
        return None  # nothing to do

    # Slice sequences + modifications; drop trim field
    for item in seqs:
        for etype in ("protein", "dna", "rna"):
            if etype not in item:
                continue
            c = item[etype]
            tr = chain_trims.get(str(c["id"]))
            if not tr:
                continue
            ks, ke = tr
            c["sequence"] = c["sequence"][ks - 1:ke]
            if c.get("modifications"):
                c["modifications"] = [
                    {**m, "position": m["position"] - (ks - 1)}
                    for m in c["modifications"]
                    if ks <= m["position"] <= ke
                ]
            c.pop("trim", None)

    # Sliced CIF/metadata are written under `assets` (a dir OUTSIDE the data dir the
    # backend scans — boltz rejects any non-YAML/FASTA entry, including subdirs). The
    # YAML references them by absolute path so their location is free.
    assets.mkdir(parents=True, exist_ok=True)

    for tmpl in doc.get("templates", []):
        cif_p = Path(tmpl["cif"])
        cids = tmpl.get("chain_id")
        cids = [cids] if isinstance(cids, str) else list(cids or [])
        cdoc = gemmi.cif.read(str(cif_p))
        block = cdoc.sole_block()
        ce = _chain_entities(block)
        # only trim the chains this template references
        tmpl_trims = {c: chain_trims[c] for c in cids if c in chain_trims}
        entity_trims = {}
        for c, tr in tmpl_trims.items():
            eid = ce.get(c)
            if eid is not None:
                entity_trims[eid] = tr  # copies of a homo-entity share the trim
        _slice_atom_site(block, tmpl_trims)
        _slice_entity_poly_seq(block, entity_trims)
        _slice_entity_poly_can(block, entity_trims)
        new_cif = assets / cif_p.name
        cdoc.write_file(str(new_cif))
        tmpl["cif"] = str(new_cif.resolve())

        meta_p = tmpl.get("inpainting_metadata")
        if meta_p and Path(meta_p).exists():
            meta = json.load(open(meta_p))
            meta = _slice_metadata(meta, tmpl_trims)
            new_meta = assets / Path(meta_p).name
            json.dump(meta, open(new_meta, "w"), indent=2)
            tmpl["inpainting_metadata"] = str(new_meta.resolve())

    return doc


def apply_trim(yaml_path: Path, yaml_out_dir: Path, assets_dir: Path) -> Path:
    """Return a prediction-ready YAML: sliced when any chain has a trim, else original.

    The rewritten YAML goes in `yaml_out_dir` (must contain ONLY YAMLs — the backend
    scans it); sliced CIF/metadata go in `assets_dir` (referenced by absolute path).
    """
    yaml_path = Path(yaml_path)
    doc = _load_yaml(yaml_path)
    yaml_out_dir = Path(yaml_out_dir)
    yaml_out_dir.mkdir(parents=True, exist_ok=True)
    new_doc = _apply_one(doc, Path(assets_dir))
    if new_doc is None:
        return yaml_path  # no trim → use as-is
    out = yaml_out_dir / yaml_path.name
    with open(out, "w") as f:
        _yaml.safe_dump(new_doc, f, sort_keys=False, default_flow_style=False)
    return out


def apply_trim_to_data(data: str, work_dir: Path) -> str:
    """Preprocess a YAML file or a directory of YAMLs; return the path to feed predict.

    Layout: sliced YAMLs → <work_dir>/yaml/ (backend scans this; YAMLs only),
    sliced CIF/metadata → <work_dir>/assets/. Returns the yaml dir/file, or the
    original `data` when nothing was trimmed.
    """
    p = Path(data)
    work_dir = Path(work_dir)
    yaml_dir = work_dir / "yaml"
    assets_dir = work_dir / "assets"
    if p.is_dir():
        yaml_dir.mkdir(parents=True, exist_ok=True)
        any_trim = False
        for y in sorted(list(p.glob("*.yaml")) + list(p.glob("*.yml"))):
            res = apply_trim(y, yaml_dir, assets_dir)
            if res != y:
                any_trim = True
            else:
                shutil.copy(y, yaml_dir / y.name)
        return str(yaml_dir) if any_trim else data
    else:
        res = apply_trim(p, yaml_dir, assets_dir)
        return str(res)
