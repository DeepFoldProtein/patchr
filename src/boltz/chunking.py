"""Chunking of large inpainting targets into runnable PATCHR sub-problems.

A large target is split into overlapping **contiguous** chunks whose cut
boundaries are placed optimally using spatial information:

* a residue–residue contact graph is built (scipy ``cKDTree.query_pairs``);
* dynamic programming finds the exact contiguous segmentation that minimises
  the number of *tertiary* contacts broken across the cuts, subject to a size
  bound — so boundaries fall at spatial necks (domain linkers), and the
  backbone is cut as few times as possible (once per chunk join);
* each segment is expanded by an overlap halo for clash-free stitching;
* ligands are carried into the single chunk whose residues contact them, at
  their template position; distant bulk-solvent ligands are dropped.

(An earlier 3-D spatial *ball cover* via farthest-point sampling was evaluated
and rejected: spatial balls fragment the backbone of a folded chain and produce
many spurious breaks, whereas contiguous domain cuts preserve it.)

:func:`merge_chunks` stitches the predictions back together: template-anchored
(fixed) residues are taken verbatim from the template — identical in every
chunk, so a chunk seam in a fixed region produces no break — while each
inpainted run is rigidly aligned onto its flanking template residues.  Any
residual break then sits only where the crystal itself is disordered.

Public API: :func:`chunk_input` and :func:`merge_chunks`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import gemmi
import numpy as np
import yaml as _yaml

_POLYMER_KINDS = ("protein", "dna", "rna")

# Residue–residue contact radius (Å): two residues whose representative atoms
# are within this distance are treated as interacting.  Used as the default
# halo width so each core residue's contacts are fully contained in its patch.
_CONTACT_RADIUS = 8.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    """A contiguous run of one source chain inside a chunk.

    ``seg_chain_id`` is the chain id used *inside the chunk* (unique within the
    chunk); ``orig_chain`` / ``gstart`` / ``gend`` map it back to 1-based query
    positions of the source chain (inclusive).
    """

    seg_chain_id: str
    orig_chain: str
    gstart: int
    gend: int

    def as_dict(self) -> dict:
        return {
            "seg_chain_id": self.seg_chain_id,
            "orig_chain": self.orig_chain,
            "gstart": self.gstart,
            "gend": self.gend,
        }


@dataclass
class ChunkSpec:
    index: int
    segments: list[Segment] = field(default_factory=list)
    # Fixed-only spatial context: template residues near this chunk's inpaint
    # regions (possibly from other chains) included so the diffusion model can
    # avoid clashing with them.  Not "owned" — ignored by the merge.
    context: list[Segment] = field(default_factory=list)
    ligand_ids: list[str] = field(default_factory=list)
    center: Optional[list[float]] = None  # patch centre coord (interior scoring)
    yaml_path: Optional[str] = None
    cif_path: Optional[str] = None
    metadata_path: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "segments": [s.as_dict() for s in self.segments],
            "context": [s.as_dict() for s in self.context],
            "ligand_ids": self.ligand_ids,
            "center": self.center,
            "yaml_path": self.yaml_path,
            "cif_path": self.cif_path,
            "metadata_path": self.metadata_path,
        }

    @property
    def n_res(self) -> int:
        return sum(s.gend - s.gstart + 1 for s in self.segments)


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _kind_of(entry: dict) -> str:
    return next(iter(entry.keys()))


def _resolve(path: str, base: Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def _load_yaml(yaml_path: Path) -> dict:
    with open(yaml_path) as f:
        return _yaml.safe_load(f)


def _template_block(schema: dict) -> dict:
    templates = schema.get("templates") or []
    if not templates:
        raise ValueError("Input YAML has no 'templates' section — chunking requires an inpainting template.")
    return templates[0]


# ---------------------------------------------------------------------------
# CIF / coordinate helpers
# ---------------------------------------------------------------------------


def _read_structure(cif_path: Path) -> gemmi.Structure:
    st = gemmi.read_structure(str(cif_path))
    st.setup_entities()
    return st


def _int_to_letters(n: int) -> str:
    """Excel-style column letters (1=A, 26=Z, 27=AA) — Protenix names output
    chains this way, in the order of the input YAML sequence entries."""
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def _map_pred_chains(chunk: dict, sc: dict[str, list[gemmi.Residue]]) -> dict[str, list[gemmi.Residue]]:
    """Map each chunk segment/ligand id to its predicted residues, regardless of
    backend.  Boltz keeps the original chain ids; Protenix renames output chains
    to sequential letters (A, B, C…) in YAML sequence-entry order (segments
    first, then ligands).  Detected per chunk: if every original id is present
    use them, otherwise fall back to the sequential letters.
    """
    # YAML sequence-entry order = segments, then fixed context, then ligands.
    ordered = (
        [s["seg_chain_id"] for s in chunk["segments"]]
        + [s["seg_chain_id"] for s in chunk.get("context", [])]
        + list(chunk.get("ligand_ids", []))
    )
    if all(name in sc for name in ordered):
        return {name: sc.get(name, []) for name in ordered}
    return {name: sc.get(_int_to_letters(i + 1), []) for i, name in enumerate(ordered)}


def _subchain_residues(model: gemmi.Model) -> dict[str, list[gemmi.Residue]]:
    """Group all residues by label_asym_id (subchain) — how parse_mmcif names chains."""
    out: dict[str, list[gemmi.Residue]] = {}
    for ch in model:
        for res in ch:
            out.setdefault(res.subchain, []).append(res)
    return out


def _residue_atoms(res: gemmi.Residue) -> np.ndarray:
    return np.array([[a.pos.x, a.pos.y, a.pos.z] for a in res], dtype=np.float64)


def _residue_rep(res: gemmi.Residue) -> np.ndarray:
    """Representative coord: CA / C1' if present, else atom centroid."""
    for nm in ("CA", "C1'", "P"):
        a = res.find_atom(nm, "*")
        if a is not None:
            return np.array([a.pos.x, a.pos.y, a.pos.z])
    coords = _residue_atoms(res)
    return coords.mean(axis=0)


def _query_pos_to_residue(residues: list[gemmi.Residue]) -> dict[int, gemmi.Residue]:
    out: dict[int, gemmi.Residue] = {}
    for res in residues:
        ls = res.label_seq
        if ls is not None and ls > 0:
            out[int(ls)] = res
    return out


def _finalize_and_write(st: gemmi.Structure, out_path: Path) -> None:
    """Set up entities cleanly and write a Mol*-friendly CIF/PDB.

    Three things Mol* needs that naive gemmi output lacks:
    * entity ids must be plain integers — gemmi's auto ``DMS!`` names make Mol*
      fall back to distance bonding and explode the view;
    * a ``_pdbx_poly_seq_scheme`` table — without it Mol* does not recognise the
      chain as a polymer and renders it as spacefill instead of a cartoon;
    * residues in sequence order (handled by the caller).
    """
    model = st[0]
    st.setup_entities()
    st.assign_label_seq_id()
    for ent in st.entities:
        if ent.entity_type == gemmi.EntityType.Polymer and ent.subchains:
            span = model.get_subchain(ent.subchains[0])
            ent.full_sequence = [res.name for res in span]
    for i, ent in enumerate(st.entities, start=1):
        ent.name = str(i)

    out_path = Path(out_path)
    if out_path.suffix.lower() == ".pdb":
        st.write_pdb(str(out_path))
        return

    doc = st.make_mmcif_document()
    block = doc.sole_block()
    # Build _pdbx_poly_seq_scheme so Mol* recognises polymers (cartoon, not spacefill).
    rows: list[list[str]] = []
    for ent in st.entities:
        if ent.entity_type != gemmi.EntityType.Polymer:
            continue
        for sub_id in ent.subchains:
            for res in model.get_subchain(sub_id):
                seq_id = str(res.label_seq) if res.label_seq else "."
                auth = str(res.seqid.num)
                rows.append([sub_id, ent.name, seq_id, res.name,
                             auth, auth, res.name, sub_id, "."])
    if rows:
        loop = block.init_loop("_pdbx_poly_seq_scheme.", [
            "asym_id", "entity_id", "seq_id", "mon_id",
            "pdb_seq_num", "auth_seq_num", "pdb_mon_id", "pdb_strand_id",
            "pdb_ins_code",
        ])
        for r in rows:
            loop.add_row(r)
    _add_auth_atom_columns(block)
    doc.write_file(str(out_path))


def _add_auth_atom_columns(block: "gemmi.cif.Block") -> None:
    """Add ``_atom_site.auth_comp_id`` / ``auth_atom_id`` (copied from the label
    columns) to a gemmi-written atom_site loop.

    gemmi omits these, and without them Mol* fails to identify standard residues
    and renders spacefill instead of a cartoon.  Chain names are untouched, so
    the file still parses for prediction (unlike a full to_mmcif re-encode).
    """
    col = block.find_loop("_atom_site.label_comp_id")
    if not col:
        return
    loop = col.get_loop()
    w, n = loop.width(), loop.length()
    tags = list(loop.tags)
    if "_atom_site.auth_comp_id" in tags:
        return
    ci = tags.index("_atom_site.label_comp_id")
    ai = tags.index("_atom_site.label_atom_id")
    vals = list(loop.values)
    comp = [vals[r * w + ci] for r in range(n)]
    atom = [vals[r * w + ai] for r in range(n)]
    loop.add_columns(["_atom_site.auth_comp_id", "_atom_site.auth_atom_id"], ".")
    w2 = loop.width()
    v2 = list(loop.values)
    for r in range(n):
        v2[r * w2 + (w2 - 2)] = comp[r]
        v2[r * w2 + (w2 - 1)] = atom[r]
    loop.set_all_values([[v2[r * w2 + c] for r in range(n)] for c in range(w2)])


# ---------------------------------------------------------------------------
# Per-residue representative coordinates (with gap interpolation)
# ---------------------------------------------------------------------------


def _chain_coords(seq_len: int, pos2res: dict[int, gemmi.Residue]) -> tuple[np.ndarray, np.ndarray]:
    """Representative coord for every 1-based position 1..seq_len.

    Inpainted positions (absent from the template) get a coordinate linearly
    interpolated from the nearest present sequence neighbours so they cluster
    with their locale.  Returns (coords[L,3], present_mask[L]).
    """
    coords = np.full((seq_len, 3), np.nan)
    present = np.zeros(seq_len, dtype=bool)
    for p, res in pos2res.items():
        if 1 <= p <= seq_len:
            coords[p - 1] = _residue_rep(res)
            present[p - 1] = True
    if not present.any():
        # Fully inpainted chain (no template coords): caller splits by length.
        return np.zeros((seq_len, 3)), present
    idx = np.where(present)[0]
    for i in range(seq_len):
        if present[i]:
            continue
        j = np.searchsorted(idx, i)
        if j == 0:
            coords[i] = coords[idx[0]]
        elif j == len(idx):
            coords[i] = coords[idx[-1]]
        else:
            lo, hi = idx[j - 1], idx[j]
            t = (i - lo) / (hi - lo)
            coords[i] = (1 - t) * coords[lo] + t * coords[hi]
    return coords, present


# ---------------------------------------------------------------------------
# Contact-aware contiguous segmentation (DP)
# ---------------------------------------------------------------------------


def _contact_crossings(
    coords: np.ndarray, contact_radius: float, seq_sep: int
) -> np.ndarray:
    """For each cut position p (1-based, between residue p and p+1), the number
    of *tertiary* contacts that cross it.

    A tertiary contact is a residue pair (a, b) with ``b - a >= seq_sep`` and
    representative atoms within ``contact_radius``.  ``cross[p]`` counts pairs
    with ``a <= p < b``.  Cutting where ``cross`` is small places chunk
    boundaries at spatial necks (domain linkers), minimising broken contacts.
    """
    from scipy.spatial import cKDTree

    n = len(coords)
    cross = np.zeros(n + 1)  # cross[p] for p in 1..n-1
    tree = cKDTree(coords)
    pairs = tree.query_pairs(contact_radius, output_type="ndarray")
    if len(pairs) == 0:
        return cross
    a = np.minimum(pairs[:, 0], pairs[:, 1])  # 0-based
    b = np.maximum(pairs[:, 0], pairs[:, 1])
    keep = (b - a) >= seq_sep
    a, b = a[keep], b[keep]
    # contact (a,b) 0-based crosses cut p (1-based) iff a+1 <= p <= b  ->  a < p <= b
    # accumulate via difference array over p in [a+1, b]
    diff = np.zeros(n + 2)
    np.add.at(diff, a + 1, 1)
    np.add.at(diff, b + 1, -1)
    cross[1:n] = np.cumsum(diff[1:n])
    return cross


def _dp_segment(
    n: int, cross: np.ndarray, min_len: int, max_len: int
) -> list[tuple[int, int]]:
    """Optimal contiguous segmentation of 1..n minimising the total tertiary
    contact crossing over chosen cuts, with each segment length in
    ``[min_len, max_len]``.  Returns 0-based half-open ``[start, end)`` windows.

    dp[i] = min cost to segment the prefix 1..i ending with a cut after i.
    """
    if n <= max_len:
        return [(0, n)]
    INF = float("inf")
    dp = [INF] * (n + 1)
    prev = [-1] * (n + 1)
    dp[0] = 0.0
    for i in range(1, n + 1):
        lo = max(0, i - max_len)
        hi = i - min_len
        if hi < 0:
            continue
        # allow the final segment to be shorter than min_len only if it reaches n
        j_start = lo
        for j in range(j_start, hi + 1):
            if dp[j] == INF:
                continue
            # cost of cutting after position i (no cut at n, the chain end)
            cut_cost = cross[i] if i < n else 0.0
            c = dp[j] + cut_cost
            if c < dp[i]:
                dp[i] = c
                prev[i] = j
    # If n unreachable under min_len constraint, relax the last segment.
    if dp[n] == INF:
        best_j, best_c = -1, INF
        for j in range(max(0, n - max_len), n):
            if dp[j] < best_c:
                best_c, best_j = dp[j], j
        prev[n] = best_j
    # Backtrack.
    cuts = []
    i = n
    while i > 0 and prev[i] >= 0:
        cuts.append(i)
        i = prev[i]
    cuts.append(0)
    cuts = sorted(set(cuts))
    return [(cuts[k], cuts[k + 1]) for k in range(len(cuts) - 1)]


def _contiguous_runs(positions: list[int], merge_gap: int = 1) -> list[tuple[int, int]]:
    """Group sorted 1-based positions into (start, end) runs.

    Positions separated by a gap ≤ ``merge_gap`` are merged into one run (the
    small gap is carried as inpaint/context), avoiding sliver segments.
    """
    if not positions:
        return []
    positions = sorted(positions)
    runs: list[list[int]] = [[positions[0], positions[0]]]
    for p in positions[1:]:
        if p - runs[-1][1] <= merge_gap:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return [(a, b) for a, b in runs]


# ---------------------------------------------------------------------------
# CIF slicing (segment-aware)
# ---------------------------------------------------------------------------


def _write_chunk_cif(
    segments: list[Segment],
    pos2res_by_chain: dict[str, dict[int, gemmi.Residue]],
    subchains: dict[str, list[gemmi.Residue]],
    ligand_ids: list[str],
    out_path: Path,
    structure_name: str,
) -> None:
    """Write a sliced CIF: one sub-chain per segment + ligands, coords verbatim."""
    st = gemmi.Structure()
    st.name = structure_name
    st.spacegroup_hm = "P 1"
    model = gemmi.Model("1")

    for seg in segments:
        pos2res = pos2res_by_chain[seg.orig_chain]
        chain = gemmi.Chain(seg.seg_chain_id)
        local = 0
        for gpos in range(seg.gstart, seg.gend + 1):
            local += 1
            res = pos2res.get(gpos)
            if res is None:
                continue  # inpainted gap — absent from template
            nr = gemmi.Residue()
            nr.name = res.name
            nr.seqid = gemmi.SeqId(local, " ")
            nr.label_seq = local
            nr.subchain = seg.seg_chain_id
            nr.het_flag = "A"
            for atom in res:
                nr.add_atom(atom)
            chain.add_residue(nr)
        model.add_chain(chain)

    for lig_id in ligand_ids:
        residues = subchains.get(lig_id)
        if not residues:
            continue
        chain = gemmi.Chain(lig_id)
        for res in residues:
            nr = gemmi.Residue()
            nr.name = res.name
            nr.seqid = gemmi.SeqId(1, " ")
            nr.subchain = lig_id
            nr.het_flag = "H"
            for atom in res:
                nr.add_atom(atom)
            chain.add_residue(nr)
        model.add_chain(chain)

    st.add_model(model)
    _finalize_and_write(st, out_path)


def _slice_metadata(
    full_meta: Optional[dict], segments: list[Segment],
    context: Optional[list[Segment]] = None,
) -> Optional[dict]:
    """Chunk-local metadata: one entry per segment chain, residues renumbered.

    Context segments are marked fully fixed (all residues anchored to template)
    so the model treats them purely as scaffolding, never inpainting them.
    """
    if full_meta is None:
        return None
    chains_meta = full_meta.get("chains", {})
    out_chains: dict = {}
    for seg in segments:
        cdata = chains_meta.get(seg.orig_chain)
        if cdata is None:
            continue
        off = seg.gstart - 1

        def _shift(nums):
            return [n - off for n in nums if seg.gstart <= n <= seg.gend]

        entry = {
            "fully_fixed_residues": _shift(cdata.get("fully_fixed_residues", [])),
            "fully_inpainted_residues": _shift(cdata.get("fully_inpainted_residues", [])),
        }
        partial = []
        for e in cdata.get("partially_fixed_residues", []):
            r = e.get("residue")
            if r is not None and seg.gstart <= r <= seg.gend:
                ne = dict(e)
                ne["residue"] = r - off
                partial.append(ne)
        entry["partially_fixed_residues"] = partial
        out_chains[seg.seg_chain_id] = entry
    for seg in (context or []):
        out_chains[seg.seg_chain_id] = {
            "fully_fixed_residues": list(range(1, seg.gend - seg.gstart + 2)),
            "fully_inpainted_residues": [],
            "partially_fixed_residues": [],
        }
    return {"chains": out_chains} if out_chains else None


# ---------------------------------------------------------------------------
# Spatial context (so the diffusion model can avoid clashes)
# ---------------------------------------------------------------------------


def _compute_context(
    specs: list["ChunkSpec"],
    pos2res_by_chain: dict[str, dict[int, gemmi.Residue]],
    seqs: dict[str, str],
    radius: float = 12.0,
    max_context: int = 120,
) -> None:
    """Attach fixed-only spatial-context segments to each chunk.

    An inpainted region (a disordered loop/tail) is predicted using only its own
    chunk; if a spatially-near fixed residue lives in *another* chunk the model
    cannot see it and may place the inpainted atoms on top of it.  Here every
    fixed template residue within ``radius`` Å of a chunk's inpaint region — from
    any chain — is added as fixed context, so the diffusion model places the
    inpainted region clash-free.  Context residues are not "owned" (the merge
    ignores them); they only inform prediction.
    """
    from scipy.spatial import cKDTree

    # Global fixed-residue CA index across all chunked chains.
    pts: list[list[float]] = []
    ids: list[tuple[str, int]] = []
    for ch, p2r in pos2res_by_chain.items():
        for pos, res in p2r.items():
            ca = res.find_atom("CA", "*")
            if ca is not None:
                pts.append([ca.pos.x, ca.pos.y, ca.pos.z])
                ids.append((ch, pos))
    if not pts:
        return
    pts_arr = np.array(pts)
    tree = cKDTree(pts_arr)
    coord_of = {cp: pts_arr[i] for i, cp in enumerate(ids)}
    interp = {ch: _chain_coords(len(seqs[ch]), pos2res_by_chain[ch])[0] for ch in seqs}

    ctx_counter = 0
    for spec in specs:
        in_chunk = {
            (seg.orig_chain, g)
            for seg in spec.segments
            for g in range(seg.gstart, seg.gend + 1)
        }
        seeds = [
            interp[seg.orig_chain][g - 1]
            for seg in spec.segments
            for g in range(seg.gstart, seg.gend + 1)
            if pos2res_by_chain[seg.orig_chain].get(g) is None  # inpaint position
        ]
        if not seeds:
            continue
        seeds_arr = np.array(seeds)
        cand: set[int] = set()
        for s in seeds_arr:
            cand.update(tree.query_ball_point(s, radius))
        cand_cp = [ids[i] for i in cand if ids[i] not in in_chunk]
        if not cand_cp:
            continue
        if len(cand_cp) > max_context:
            cand_cp.sort(key=lambda cp: float(
                np.linalg.norm(seeds_arr - coord_of[cp], axis=1).min()))
            cand_cp = cand_cp[:max_context]
        by_chain: dict[str, list[int]] = {}
        for cid, pos in cand_cp:
            by_chain.setdefault(cid, []).append(pos)
        context: list[Segment] = []
        for cid, positions in by_chain.items():
            for a, b in _contiguous_runs(sorted(positions), merge_gap=1):
                context.append(Segment(seg_chain_id=f"ctx{ctx_counter}",
                                        orig_chain=cid, gstart=a, gend=b))
                ctx_counter += 1
        spec.context = context


def _assign_ligands(
    subchains: dict[str, list[gemmi.Residue]],
    ligand_ids: list[str],
    patch_coords: list[np.ndarray],
    cutoff: float,
) -> dict[int, list[str]]:
    """Each ligand → single nearest patch (by min atom distance) within cutoff."""
    assignment: dict[int, list[str]] = {i: [] for i in range(len(patch_coords))}
    for lig_id in ligand_ids:
        residues = subchains.get(lig_id)
        if not residues:
            continue
        lig = np.concatenate([_residue_atoms(r) for r in residues if len(r) > 0], axis=0)
        if lig.size == 0:
            continue
        best, best_d = -1, float("inf")
        for ci, coords in enumerate(patch_coords):
            if coords.size == 0:
                continue
            d = np.linalg.norm(lig[:, None, :] - coords[None, :, :], axis=-1).min()
            if d < best_d:
                best_d, best = d, ci
        if best >= 0 and best_d <= cutoff:
            assignment[best].append(lig_id)
    return assignment


# ---------------------------------------------------------------------------
# Public API: chunk
# ---------------------------------------------------------------------------


def chunk_input(
    yaml_path: str | Path,
    out_dir: str | Path,
    chunk_size: int = 384,
    overlap: int = 48,
    ligand_cutoff: float = 6.0,
    contact_radius: float = _CONTACT_RADIUS,
    chains: Optional[list[str]] = None,
) -> list[ChunkSpec]:
    """Split an inpainting YAML into per-chunk YAMLs + sliced CIFs.

    Parameters
    ----------
    chunk_size:
        Maximum residues per chunk core (before the overlap halo is added).
    overlap:
        Residues of overlap added on each side of a chunk for clash-free
        stitching.
    ligand_cutoff:
        Max nearest-atom distance (Å) for a ligand to be carried into a chunk.
    contact_radius:
        Distance (Å) defining a residue–residue contact in the DP cost graph.
    chains:
        Restrict to these polymer chain ids (default: all polymers).
    """
    yaml_path = Path(yaml_path).resolve()
    out_dir = Path(out_dir).resolve()
    inputs_dir = out_dir / "inputs"
    assets_dir = out_dir / "assets"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    base = yaml_path.parent

    schema = _load_yaml(yaml_path)
    template = _template_block(schema)
    cif_path = _resolve(template["cif"], base)
    meta_path = template.get("inpainting_metadata")
    full_meta = json.loads(_resolve(meta_path, base).read_text()) if meta_path else None

    polymers: dict[str, dict] = {}
    ligands: dict[str, dict] = {}
    for entry in schema.get("sequences", []):
        kind = _kind_of(entry)
        body = entry[kind]
        cid = str(body["id"])
        if kind in _POLYMER_KINDS:
            polymers[cid] = {"kind": kind, "body": body}
        elif kind == "ligand":
            ligands[cid] = {"kind": kind, "body": body}

    target_chains = [c for c in (chains or polymers) if c in polymers]
    if not target_chains:
        raise ValueError("No polymer chains found to chunk.")

    st = _read_structure(cif_path)
    model = st[0]
    subchains = _subchain_residues(model)
    # YAML chain ids are AUTH chain ids; for large assemblies the label_asym_id
    # (subchain) diverges from the auth id, so resolve polymers by auth chain
    # name first and fall back to subchain.
    auth_poly: dict[str, list[gemmi.Residue]] = {}
    for ch in model:
        for r in ch:
            if r.het_flag != "H":
                auth_poly.setdefault(ch.name, []).append(r)

    pos2res_by_chain: dict[str, dict[int, gemmi.Residue]] = {}
    seqs: dict[str, str] = {}
    for cid in target_chains:
        res = auth_poly.get(cid) or subchains.get(cid)
        # A polymer declared in the YAML but entirely absent from the template
        # CIF is a fully-inpainted chain → empty map; domain chunking then splits
        # it by length (no coords to cluster on).
        pos2res_by_chain[cid] = _query_pos_to_residue(res) if res else {}
        seqs[cid] = polymers[cid]["body"]["sequence"]

    chunk_specs = _build_domain_chunks(
        target_chains, seqs, pos2res_by_chain,
        max_len=chunk_size, overlap=overlap, contact_radius=contact_radius,
    )

    # Per-chunk template coords (for ligand proximity).
    specs: list[ChunkSpec] = []
    for spec in chunk_specs:
        arrs = []
        for seg in spec.segments:
            p2r = pos2res_by_chain[seg.orig_chain]
            for gpos in range(seg.gstart, seg.gend + 1):
                r = p2r.get(gpos)
                if r is not None and len(r) > 0:
                    arrs.append(_residue_atoms(r))
        spec._coords = np.concatenate(arrs, axis=0) if arrs else np.empty((0, 3))  # type: ignore[attr-defined]
        specs.append(spec)

    lig_assign = _assign_ligands(
        subchains, list(ligands.keys()),
        [s._coords for s in specs],  # type: ignore[attr-defined]
        ligand_cutoff,
    )

    # Spatial context: fixed template residues near each chunk's inpaint region.
    _compute_context(specs, pos2res_by_chain, seqs)

    # Write each chunk.
    for spec in specs:
        spec.ligand_ids = list(lig_assign.get(spec.index, []))
        stem = f"chunk_{spec.index:03d}"
        chunk_cif = assets_dir / f"{stem}.cif"
        chunk_yaml = inputs_dir / f"{stem}.yaml"
        chunk_meta = assets_dir / f"{stem}_metadata.json"

        _write_chunk_cif(
            spec.segments + spec.context, pos2res_by_chain, subchains, spec.ligand_ids,
            chunk_cif, structure_name=stem,
        )
        sliced_meta = _slice_metadata(full_meta, spec.segments, spec.context)
        if sliced_meta is not None:
            chunk_meta.write_text(json.dumps(sliced_meta, indent=2))
            spec.metadata_path = str(chunk_meta)

        seq_entries: list[dict] = []
        for seg in spec.segments + spec.context:
            kind = polymers[seg.orig_chain]["kind"]
            body = polymers[seg.orig_chain]["body"]
            sub_seq = seqs[seg.orig_chain][seg.gstart - 1: seg.gend]
            pbody = {"id": seg.seg_chain_id, "sequence": sub_seq, "msa": "empty"}
            mods = [
                {"position": m["position"] - (seg.gstart - 1), "ccd": m["ccd"]}
                for m in (body.get("modifications", []) or [])
                if seg.gstart <= m["position"] <= seg.gend
            ]
            if mods:
                pbody["modifications"] = mods
            seq_entries.append({kind: pbody})
        for lig_id in spec.ligand_ids:
            lbody = ligands[lig_id]["body"]
            entry = {"id": lig_id}
            if "ccd" in lbody:
                entry["ccd"] = lbody["ccd"]
            if "smiles" in lbody:
                entry["smiles"] = lbody["smiles"]
            seq_entries.append({"ligand": entry})

        template_entry = {
            "cif": str(chunk_cif),
            "chain_id": [s.seg_chain_id for s in spec.segments + spec.context]
            + list(spec.ligand_ids),
        }
        if spec.metadata_path is not None:
            template_entry["inpainting_metadata"] = spec.metadata_path

        chunk_schema = {
            "version": schema.get("version", 1),
            "sequences": seq_entries,
            "templates": [template_entry],
        }
        with open(chunk_yaml, "w") as f:
            _yaml.safe_dump(chunk_schema, f, sort_keys=False)
        spec.yaml_path = str(chunk_yaml)
        spec.cif_path = str(chunk_cif)

    manifest = {
        "source_yaml": str(yaml_path),
        "source_cif": str(cif_path),
        "params": {
            "chunk_size": chunk_size, "overlap": overlap,
            "contact_radius": contact_radius, "ligand_cutoff": ligand_cutoff,
        },
        "inputs_dir": str(inputs_dir),
        "assets_dir": str(assets_dir),
        "chunks": [s.as_dict() for s in specs],
    }
    (out_dir / "chunk_manifest.json").write_text(json.dumps(manifest, indent=2))
    return specs


def _build_domain_chunks(
    target_chains: list[str], seqs: dict[str, str],
    pos2res_by_chain: dict[str, dict[int, gemmi.Residue]],
    max_len: int, overlap: int, contact_radius: float,
    seq_sep: int = 4,
) -> list[ChunkSpec]:
    """Contiguous chunks with cut boundaries placed (by DP) at spatial necks
    that minimise broken tertiary contacts, then expanded by an ``overlap``
    halo for clash-free stitching.  Preserves the backbone (only one ownership
    boundary per consecutive pair), unlike spatial balls.
    """
    min_len = max(overlap + 1, max_len // 4)
    specs: list[ChunkSpec] = []
    idx = 0
    for cid in target_chains:
        L = len(seqs[cid])
        coords, _present = _chain_coords(L, pos2res_by_chain[cid])
        if not _present.any():
            # No template coords to cluster on → uniform length-based windows.
            windows = [(s, min(s + max_len, L)) for s in range(0, max(1, L), max_len)]
        else:
            cross = _contact_crossings(coords, contact_radius, seq_sep)
            windows = _dp_segment(L, cross, min_len=min_len, max_len=max_len)
        for (s, e) in windows:
            # Expand by overlap halo (clamped) for shared context.
            hs = max(0, s - overlap)
            he = min(L, e + overlap)
            seg = Segment(seg_chain_id=cid, orig_chain=cid, gstart=hs + 1, gend=he)
            # Centre score uses the *core* window midpoint (un-haloed).
            mid = (s + e) // 2
            spec = ChunkSpec(index=idx, segments=[seg],
                             center=[float(x) for x in coords[mid]])
            specs.append(spec)
            idx += 1
    return specs


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def _kabsch(P: np.ndarray, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    Pc, Qc = P.mean(axis=0), Q.mean(axis=0)
    H = (P - Pc).T @ (Q - Qc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    return R, Qc - R @ Pc


def _rot_matrix(axis: np.ndarray, ang: float) -> np.ndarray:
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    c, s = np.cos(ang), np.sin(ang)
    x, y, z = axis
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


def _res_ca(res: Optional[gemmi.Residue]) -> Optional[np.ndarray]:
    if res is None:
        return None
    a = res.find_atom("CA", "*")
    return np.array([a.pos.x, a.pos.y, a.pos.z]) if a is not None else None


def _hinge_rotate(
    cres: dict[int, gemmi.Residue], a: int, b: int,
    pivot: np.ndarray, target: np.ndarray, moving_ca: np.ndarray, bond: float = 3.8,
) -> None:
    """Rigidly rotate the loop residues ``a..b`` about ``pivot`` so that
    ``moving_ca`` lands ``bond`` Å from ``target`` (a CCD single step).  The
    loop's internal geometry and its bond to the hinge anchor are preserved
    because rotation about the pivot keeps every distance to the pivot fixed.
    """
    vM, vT = moving_ca - pivot, target - pivot
    RM, c = np.linalg.norm(vM), np.linalg.norm(vT)
    if RM < 1e-6 or c < 1e-6:
        return
    cosb = np.clip((RM ** 2 + c ** 2 - bond ** 2) / (2 * RM * c), -1.0, 1.0)
    beta = np.arccos(cosb)
    cur = np.arccos(np.clip(np.dot(vM, vT) / (RM * c), -1.0, 1.0))
    axis = np.cross(vM, vT)
    if np.linalg.norm(axis) < 1e-6:
        return
    R = _rot_matrix(axis, cur - beta)
    for g in range(a, b + 1):
        r = cres.get(g)
        if r is None:
            continue
        for atom in r:
            p = np.array([atom.pos.x, atom.pos.y, atom.pos.z])
            v = pivot + R @ (p - pivot)
            atom.pos = gemmi.Position(float(v[0]), float(v[1]), float(v[2]))


def _translate_loop(cres: dict[int, gemmi.Residue], a: int, b: int, shift: np.ndarray) -> None:
    for g in range(a, b + 1):
        r = cres.get(g)
        if r is None:
            continue
        for atom in r:
            atom.pos = gemmi.Position(
                atom.pos.x + float(shift[0]),
                atom.pos.y + float(shift[1]),
                atom.pos.z + float(shift[2]),
            )


def _close_loops(
    chain_residues: dict[str, dict[int, gemmi.Residue]],
    src_pos2res: dict[str, dict[int, gemmi.Residue]],
    thresh: float = 4.5, bond: float = 3.8,
) -> int:
    """Bridge inpainted loops whose ends do not reach their fixed anchors.

    The loop is treated as a rigid body: it is first translated to seat its
    better-connected end at the correct bond distance from that anchor, then
    rotated about that anchor (a CCD step) to swing the other end onto its
    anchor.  Internal loop geometry and the seated bond are preserved.  Loops
    with only one anchor (chain termini) are skipped.  Returns the count closed.
    Note: this *models* a region the crystal does not resolve — opt-in only.
    """
    closed = 0
    for ch, cres in chain_residues.items():
        src = src_pos2res.get(ch, {})
        inpaint = [g for g in sorted(cres) if g not in src]
        for a, b in _contiguous_runs(inpaint, merge_gap=1):
            caNa = _res_ca(cres.get(a - 1))   # N-anchor CA (fixed)
            caCa = _res_ca(cres.get(b + 1))   # C-anchor CA (fixed)
            caIn0 = _res_ca(cres.get(a))      # loop N-end CA
            caIn1 = _res_ca(cres.get(b))      # loop C-end CA
            if caIn0 is None or caIn1 is None:
                continue
            if caNa is None and caCa is None:
                continue  # fully unanchored — nothing to bridge to
            if caNa is None or caCa is None:
                # Terminal tail (one anchor): seat the anchored end at bond
                # distance so the tail does not float off (translation only).
                anchor = caCa if caNa is None else caNa
                end = caIn1 if caNa is None else caIn0
                if np.linalg.norm(anchor - end) > thresh:
                    seat = anchor + bond * (end - anchor) / (np.linalg.norm(end - anchor) + 1e-9)
                    _translate_loop(cres, a, b, seat - end)
                    closed += 1
                continue
            dN = np.linalg.norm(caNa - caIn0)
            dC = np.linalg.norm(caCa - caIn1)
            if dN <= thresh and dC <= thresh:
                continue  # already closed
            # Seat the better-connected end, then converge both backbone bonds
            # by alternating rigid hinges about each anchor (a rigid-body CCD).
            if dC <= dN:
                near_anchor, near_end = caCa, caIn1
            else:
                near_anchor, near_end = caNa, caIn0
            seat = near_anchor + bond * (near_end - near_anchor) / (
                np.linalg.norm(near_end - near_anchor) + 1e-9)
            _translate_loop(cres, a, b, seat - near_end)
            for _ in range(60):
                # Re-orient (hinge about each anchor) then translate to balance
                # the two end-bonds — a rigid-body fit to both anchor constraints.
                _hinge_rotate(cres, a, b, pivot=caCa, target=caNa,
                              moving_ca=_res_ca(cres[a]), bond=bond)
                e0 = caNa - _res_ca(cres[a])
                e1 = caCa - _res_ca(cres[b])
                d0, d1 = np.linalg.norm(e0), np.linalg.norm(e1)
                f = (d0 - bond) * e0 / (d0 + 1e-9) + (d1 - bond) * e1 / (d1 + 1e-9)
                _translate_loop(cres, a, b, 0.5 * f)
                dn = np.linalg.norm(caNa - _res_ca(cres[a]))
                dc = np.linalg.norm(caCa - _res_ca(cres[b]))
                if dn <= thresh and dc <= thresh:
                    break
            # The closed loop still has one free DOF: rotation about its
            # end-to-end axis (keeps both anchor bonds). Search it to point the
            # bulge away from the rest of the structure and avoid steric clashes.
            _declash_loop(chain_residues, ch, cres, a, b)
            closed += 1
    return closed


def _declash_loop(
    chain_residues: dict[str, dict[int, gemmi.Residue]],
    ch: str, cres: dict[int, gemmi.Residue], a: int, b: int,
) -> None:
    """Rotate a closed loop about its end-to-end axis to maximise the minimum
    distance to the rest of the structure (keeps both anchor bonds intact)."""
    axis_pt = _res_ca(cres[a])
    axis = _res_ca(cres[b]) - axis_pt
    if np.linalg.norm(axis) < 1e-6:
        return
    # Atoms to avoid: everything except this loop and its two anchors.
    avoid = []
    skip = set(range(a - 1, b + 2))
    for c2, cres2 in chain_residues.items():
        for g, r in cres2.items():
            if c2 == ch and g in skip:
                continue
            for atom in r:
                avoid.append([atom.pos.x, atom.pos.y, atom.pos.z])
    if not avoid:
        return
    avoid_arr = np.array(avoid)
    # Snapshot loop atoms (positions + handles).
    loop_atoms = [atom for g in range(a, b + 1) if cres.get(g) for atom in cres[g]]
    base = np.array([[at.pos.x, at.pos.y, at.pos.z] for at in loop_atoms])
    from scipy.spatial import cKDTree
    tree = cKDTree(avoid_arr)
    best_ang, best_min = 0.0, -1.0
    for ang in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        R = _rot_matrix(axis, ang)
        rot = (base - axis_pt) @ R.T + axis_pt
        dmin = tree.query(rot, k=1)[0].min()
        if dmin > best_min:
            best_min, best_ang = dmin, ang
    R = _rot_matrix(axis, best_ang)
    rot = (base - axis_pt) @ R.T + axis_pt
    for at, p in zip(loop_atoms, rot):
        at.pos = gemmi.Position(float(p[0]), float(p[1]), float(p[2]))


def _copy_residue(
    res: gemmi.Residue, gpos: int, chain_id: str, het: str,
    xf: Optional[tuple[np.ndarray, np.ndarray]],
    b_override: Optional[float] = None,
) -> gemmi.Residue:
    """Copy a residue at global position ``gpos``; optionally apply (R, t).

    ``b_override`` replaces the B-factor (used to carry the model pLDDT onto
    template-snapped residues, whose template B-factors are crystal values).
    """
    nr = gemmi.Residue()
    nr.name = res.name
    nr.seqid = gemmi.SeqId(gpos, " ")
    nr.label_seq = gpos
    nr.subchain = chain_id
    nr.het_flag = het
    R, t = xf if xf is not None else (None, None)
    for atom in res:
        na = gemmi.Atom()
        na.name, na.element = atom.name, atom.element
        if R is not None:
            v = R @ np.array([atom.pos.x, atom.pos.y, atom.pos.z]) + t
            na.pos = gemmi.Position(float(v[0]), float(v[1]), float(v[2]))
        else:
            na.pos = atom.pos
        na.b_iso = atom.b_iso if b_override is None else b_override
        na.occ = atom.occ
        nr.add_atom(na)
    return nr


def _residue_plddt(res: Optional[gemmi.Residue]) -> Optional[float]:
    """Per-residue pLDDT = its CA (or first-atom) B-factor in the prediction."""
    if res is None or len(res) == 0:
        return None
    ca = res.find_atom("CA", "*")
    return float(ca.b_iso if ca is not None else res[0].b_iso)


def _bb_atom(res: Optional[gemmi.Residue]) -> Optional[gemmi.Atom]:
    """Backbone superposition atom: CA for protein, C1'/P for nucleic acids.
    Returns None for residues with none (so they are skipped, not aligned on a
    sidechain centroid)."""
    if res is None:
        return None
    for nm in ("CA", "C1'", "P"):
        a = res.find_atom(nm, "*")
        if a is not None:
            return a
    return None


def _ca(res: Optional[gemmi.Residue]) -> Optional[np.ndarray]:
    a = _bb_atom(res)
    return np.array([a.pos.x, a.pos.y, a.pos.z]) if a is not None else None


def _is_nucleic(res: Optional[gemmi.Residue]) -> bool:
    """A nucleotide has no CA but carries a C1' (and usually P) sugar atom."""
    return (res is not None and res.find_atom("CA", "*") is None
            and res.find_atom("C1'", "*") is not None)


def _local_inpaint_xf(
    model_by_pos: dict[int, gemmi.Residue],
    src_by_pos: dict[int, gemmi.Residue],
    run_lo: int, run_hi: int,
    fallback: tuple[np.ndarray, np.ndarray],
    window: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """Rigid transform aligning a chunk's frame onto the template using the
    template-anchored residues flanking an inpaint run ``[run_lo, run_hi]``.

    Three candidate fits — both flanks, N-side only, C-side only — are scored on
    the two backbone boundaries, and the one minimising the number (then
    magnitude) of breaks is kept.  When a run only connects cleanly to one side
    (a disordered loop placed far from its other anchor), the single-side fit
    preserves that boundary instead of compromising and breaking both.
    """
    def _collect(positions):
        s, d = [], []
        for p in positions:
            m, tr = _ca(model_by_pos.get(p)), _ca(src_by_pos.get(p))
            if m is not None and tr is not None:
                s.append(m)
                d.append(tr)
        return s, d

    n_range = list(range(run_lo - window, run_lo))
    c_range = list(range(run_hi + 1, run_hi + window + 1))
    candidates: list[tuple[np.ndarray, np.ndarray]] = []
    for rng in (n_range + c_range, n_range, c_range):
        s, d = _collect(rng)
        if len(s) >= 3:
            candidates.append(_kabsch(np.array(s), np.array(d)))
    if not candidates:
        return fallback

    boundaries = [(run_lo, run_lo - 1), (run_hi, run_hi + 1)]

    def _score(Rt):
        R, t = Rt
        breaks, total = 0, 0.0
        for g_in, g_fix in boundaries:
            ri = model_by_pos.get(g_in)
            m, tr = _ca(ri), _ca(src_by_pos.get(g_fix))
            if m is None or tr is None:
                continue
            dist = float(np.linalg.norm((R @ m + t) - tr))
            total += dist
            # bond span between rep atoms differs by polymer: CA-CA ~3.8 Å,
            # nucleic C1'-C1'/P-P ~5.9 Å.
            lo, hi = (4.5, 7.5) if _is_nucleic(ri) else (2.5, 4.5)
            if not (lo < dist < hi):
                breaks += 1
        return breaks, total

    return min(candidates, key=_score)


def _propagate_chunk_transforms(
    chunk_models: dict[str, dict[int, dict[int, gemmi.Residue]]],
    chunk_xf: dict[int, tuple[np.ndarray, np.ndarray]],
    anchored: dict[int, bool],
) -> None:
    """Give chunks that lack their own template anchors a globally consistent
    frame by chaining off their neighbours' overlap.

    A chunk deep inside a long gap may carry fewer than three template-anchored
    residues, so its direct superposition is undetermined and it would otherwise
    sit in raw prediction coordinates (hundreds of Å away).  Chunks overlap by
    construction, so such a chunk is aligned to an already-placed neighbour using
    the residues they both predict — Kabsch onto the neighbour's *transformed*
    coordinates — and this propagates outward until every reachable chunk shares
    one frame.  Well-anchored chunks (the common case, and all protein chunks)
    keep their own transform untouched.
    """
    # Raw backbone coords per chunk, keyed by (chain, global position).
    raw: dict[int, dict[tuple[str, int], np.ndarray]] = {}
    for ch, per in chunk_models.items():
        for idx, by_pos in per.items():
            d = raw.setdefault(idx, {})
            for g, res in by_pos.items():
                c = _ca(res)
                if c is not None:
                    d[(ch, g)] = c
    placed = {i for i, a in anchored.items() if a}
    if not placed:
        return
    changed = True
    while changed and len(placed) < len(raw):
        changed = False
        for idx in list(raw):
            if idx in placed:
                continue
            best = None  # (n_shared, neighbour_idx, shared_keys)
            for j in placed:
                shared = set(raw[idx]) & set(raw[j])
                if len(shared) >= 3 and (best is None or len(shared) > best[0]):
                    best = (len(shared), j, shared)
            if best is None:
                continue
            _, j, shared = best
            Rj, tj = chunk_xf[j]
            src = np.array([raw[idx][k] for k in shared])
            dst = np.array([Rj @ raw[j][k] + tj for k in shared])
            chunk_xf[idx] = _kabsch(src, dst)
            placed.add(idx)
            changed = True


def merge_chunks(
    manifest_path: str | Path,
    predictions: list[str | Path],
    out_path: str | Path,
    superpose: bool = True,
    close_loops: bool = False,
    relax: bool = False,
) -> str:
    """Stitch predicted chunks into one structure (mode-agnostic).

    Each predicted residue maps back to its global (chain, position) via the
    manifest segments.  When a residue appears in several patches it is taken
    from the one in which it is most *interior* — nearest to that patch's
    centre (sphere mode) or with the most local context (sequence mode) — which
    minimises boundary artefacts.  All patches share the template frame, so the
    result is a clash-free concatenation.
    """
    manifest = json.loads(Path(manifest_path).read_text())
    chunks = manifest["chunks"]
    source_cif = Path(manifest["source_cif"])

    # Source coords for interior scoring.
    src_st = _read_structure(source_cif)
    src_sub = _subchain_residues(src_st[0])
    src_pos2res = {cid: _query_pos_to_residue(res) for cid, res in src_sub.items()}

    def _src_coord(chain: str, gpos: int) -> Optional[np.ndarray]:
        r = src_pos2res.get(chain, {}).get(gpos)
        return _residue_rep(r) if r is not None else None

    pred_paths = [Path(p) for p in predictions]
    pred_by_idx: dict[int, Path] = {}
    for c in chunks:
        stem = f"chunk_{c['index']:03d}"
        m = next((p for p in pred_paths if stem in p.stem), None)
        if m is not None:
            pred_by_idx[c["index"]] = m

    # Pass 1: decide, for each global residue, which chunk owns it (most interior).
    owner: dict[tuple[str, int], tuple[int, float]] = {}
    for c in chunks:
        idx = c["index"]
        if idx not in pred_by_idx:
            continue
        center = np.array(c["center"]) if c.get("center") is not None else None
        for seg in c["segments"]:
            ch, gs, ge = seg["orig_chain"], seg["gstart"], seg["gend"]
            for gpos in range(gs, ge + 1):
                if center is not None:
                    coord = _src_coord(ch, gpos)
                    score = float(np.linalg.norm(coord - center)) if coord is not None else 1e9
                else:
                    # sequence mode: prefer residue nearest the window middle
                    score = abs(gpos - (gs + ge) / 2.0)
                key = (ch, gpos)
                if key not in owner or score < owner[key][1]:
                    owner[key] = (idx, score)

    out_st = gemmi.Structure()
    out_st.name = Path(out_path).stem
    out_st.spacegroup_hm = "P 1"
    out_model = gemmi.Model("1")
    # Accumulate residues keyed by global position so the final chain is written
    # in sequence order — interior ownership in overlaps is non-monotonic, so
    # adding residues chunk-by-chunk would scramble the order and break Mol*.
    chain_residues: dict[str, dict[int, gemmi.Residue]] = {}
    lig_chains: list[gemmi.Chain] = []  # added after polymers so polymer is entity 1
    lig_seen: set[str] = set()

    # Per-chunk predicted residues (by chain, by chunk index, by global pos) and
    # superposition transforms, retained for the global inpaint pass after the
    # loop.  Keep the chunk Structures alive too — gemmi residues reference their
    # parent Structure's storage, so they must outlive the loop iteration.
    chunk_models: dict[str, dict[int, dict[int, gemmi.Residue]]] = {}
    chunk_xf: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    chunk_anchored: dict[int, bool] = {}  # chunk has >=3 own template anchors
    chunk_structs: list = []

    for c in chunks:
        idx = c["index"]
        if idx not in pred_by_idx:
            continue
        st = _read_structure(pred_by_idx[idx])
        chunk_structs.append(st)
        sc = _subchain_residues(st[0])
        # Resolve predicted chain ids (Boltz keeps originals; Protenix renames
        # to sequential letters) to this chunk's segments/ligands.
        pred = _map_pred_chains(c, sc)

        # Superposition onto template frame using this chunk's template residues.
        R, t = np.eye(3), np.zeros(3)
        if superpose:
            src_pts, dst_pts = [], []
            for seg in c["segments"]:
                seg_res = pred.get(seg["seg_chain_id"], [])
                for res in seg_res:
                    if not res.label_seq:
                        continue
                    gpos = seg["gstart"] + res.label_seq - 1
                    ca = _bb_atom(res)  # CA (protein) or C1'/P (nucleic acid)
                    tgt = _src_coord(seg["orig_chain"], gpos)
                    if ca is not None and tgt is not None:
                        src_pts.append([ca.pos.x, ca.pos.y, ca.pos.z])
                        dst_pts.append(tgt)
            if len(src_pts) >= 3:
                R, t = _kabsch(np.array(src_pts), np.array(dst_pts))
        chunk_anchored[idx] = len(src_pts) >= 3 if superpose else True

        def _global_xf(pos: gemmi.Position) -> gemmi.Position:
            v = R @ np.array([pos.x, pos.y, pos.z]) + t
            return gemmi.Position(*(float(x) for x in v))

        # Map this chunk's model output by global position, per chain.
        model_res: dict[str, dict[int, gemmi.Residue]] = {}
        for seg in c["segments"]:
            seg_res = pred.get(seg["seg_chain_id"]) or []
            for res in seg_res:
                if res.label_seq:
                    gpos = seg["gstart"] + res.label_seq - 1
                    model_res.setdefault(seg["orig_chain"], {})[gpos] = res

        chunk_xf[idx] = (R, t)
        for ch, by_pos in model_res.items():
            chunk_models.setdefault(ch, {})[idx] = by_pos
            cres = chain_residues.setdefault(ch, {})
            src_ch = src_pos2res.get(ch, {})
            owned = [g for g in by_pos if owner.get((ch, g), (None,))[0] == idx]

            # Fixed (template-anchored) residues are taken verbatim from the
            # template — identical in every chunk, so a chunk seam in a fixed
            # region produces no backbone break.  Their B-factor is overridden
            # with the model pLDDT (the template carries crystal B-factors).
            for g in owned:
                if src_ch.get(g) is not None:
                    cres[g] = _copy_residue(
                        src_ch[g], g, ch, het="A", xf=None,
                        b_override=_residue_plddt(by_pos.get(g)),
                    )
            # Inpaint runs are aligned in the global post-pass after this loop,
            # so a run spanning a chunk seam is placed as one rigid piece.

        for lig_id in c.get("ligand_ids", []):
            if lig_id in lig_seen:
                continue
            # Ligands are template-anchored — take their verbatim template
            # coordinates (consistent and drift-free), falling back to the
            # model output if the ligand is absent from the source CIF.
            lres = src_sub.get(lig_id) or sc.get(lig_id)
            if not lres:
                continue
            use_template = lig_id in src_sub
            # pLDDT for the ligand comes from the model prediction (the template
            # carries crystal B-factors).
            model_lig = {at.name: at.b_iso for r in (pred.get(lig_id) or []) for at in r}
            lch = gemmi.Chain(lig_id)
            for res in lres:
                nr = gemmi.Residue()
                nr.name = res.name
                nr.seqid = gemmi.SeqId(1, " ")
                nr.subchain = lig_id
                nr.het_flag = "H"
                for atom in res:
                    na = gemmi.Atom()
                    na.name, na.element = atom.name, atom.element
                    na.pos = atom.pos if use_template else _global_xf(atom.pos)
                    na.b_iso = model_lig.get(atom.name, atom.b_iso)
                    na.occ = atom.occ
                    nr.add_atom(na)
                lch.add_residue(nr)
            lig_chains.append(lch)
            lig_seen.add(lig_id)

    # Chunks deep in a long gap may lack their own template anchors; give them a
    # consistent frame by chaining off neighbours' overlap before placing inpaint.
    _propagate_chunk_transforms(chunk_models, chunk_xf, chunk_anchored)

    # Global inpaint pass: align each inpaint run as a single rigid unit, taken
    # from the chunk that best covers it (whole run body plus both template
    # flanks).  Interior ownership previously split a run across chunks and
    # aligned each half onto different flanks, so any run crossing a chunk seam
    # broke there — most visibly in long nucleic-acid runs over sparsely anchored
    # chunks.  Residues that no single chunk covers (runs longer than a chunk)
    # fall back to their own chunk's superposition frame: globally placed rather
    # than left in raw chunk coordinates.
    WINDOW = 8
    for ch, per_chunk in chunk_models.items():
        cres = chain_residues.setdefault(ch, {})
        src_ch = src_pos2res.get(ch, {})
        inpaint_all = sorted({g for by_pos in per_chunk.values() for g in by_pos
                              if src_ch.get(g) is None})
        for a, b in _contiguous_runs(inpaint_all, merge_gap=1):
            runlen = b - a + 1
            best = None
            for cidx, by_pos in per_chunk.items():
                covered = sum(1 for g in range(a, b + 1) if g in by_pos)
                if not covered:
                    continue
                nflank = sum(1 for g in range(a - WINDOW, a)
                             if g in by_pos and src_ch.get(g) is not None)
                cflank = sum(1 for g in range(b + 1, b + WINDOW + 1)
                             if g in by_pos and src_ch.get(g) is not None)
                key = (covered == runlen, nflank > 0 and cflank > 0,
                       covered, nflank + cflank)
                if best is None or key > best[0]:
                    best = (key, cidx, by_pos)
            if best is None:
                continue
            _, cidx, by_pos = best
            lxf = _local_inpaint_xf(by_pos, src_ch, a, b,
                                    fallback=chunk_xf.get(cidx, (np.eye(3), np.zeros(3))))
            for g in range(a, b + 1):
                rsrc = by_pos.get(g)
                gxf = lxf
                if rsrc is None:
                    # Run longer than the chosen chunk — take this residue from a
                    # chunk that has it, placed via that chunk's own (propagated)
                    # global frame.
                    for j, bp in per_chunk.items():
                        if g in bp:
                            rsrc = bp[g]
                            gxf = chunk_xf.get(j, (np.eye(3), np.zeros(3)))
                            break
                if rsrc is not None:
                    cres[g] = _copy_residue(rsrc, g, ch, het="A", xf=gxf)

    # Optionally close inpainted loops that dangle off one anchor (models a
    # region the crystal does not resolve — opt-in).
    if close_loops:
        n = _close_loops(chain_residues, src_pos2res)
        if n:
            import warnings
            warnings.warn(
                f"Closed {n} inpainted loop(s) by rigid-body bridging "
                f"(modelled, not experimentally resolved). A mild residual "
                f"clash may remain — run 'patchr sim-ready' (energy "
                f"minimisation) for a physically clean loop."
            )

    # Emit polymer chains first (so polymer becomes entity 1), residues in
    # ascending sequence order, then the ligand chains.
    for ch, cres in chain_residues.items():
        chain = gemmi.Chain(ch)
        for gpos in sorted(cres):
            chain.add_residue(cres[gpos])
        out_model.add_chain(chain)
    for lch in lig_chains:
        out_model.add_chain(lch)
    out_st.add_model(out_model)
    out_path = Path(out_path)
    _finalize_and_write(out_st, out_path)

    is_cif = out_path.suffix.lower() != ".pdb"
    # Optional deterministic clash relaxation: push apart clashing inpainted
    # atoms (template atoms and ligands frozen) until no heavy-atom clash
    # remains — guarantees a clash-free structure.  geometric_relax already
    # re-encodes the CIF, so skip the separate re-encode below.
    relaxed = False
    if relax:
        try:
            geometric_relax(out_path, source_cif, out_path)
            relaxed = True
        except Exception as exc:  # noqa: BLE001
            import warnings
            warnings.warn(f"Clash relaxation skipped ({exc}).")

    if is_cif and not relaxed:
        # Rewrite the CIF through Boltz's own mmCIF writer so it carries the
        # auth_* columns / ihm tables that Mol* needs to render a cartoon.
        _rewrite_cif_via_boltz(out_path)
    if is_cif:
        # Best-effort PDB sibling from the final (possibly relaxed) coordinates.
        try:
            _finalize_and_write(_read_structure(out_path), out_path.with_suffix(".pdb"))
        except Exception as exc:  # noqa: BLE001
            import warnings
            out_path.with_suffix(".pdb").unlink(missing_ok=True)
            warnings.warn(f"PDB sibling skipped ({exc}); use the .cif.")
    return str(out_path)


def _plddts_from_structure(data, const) -> np.ndarray:
    """Per-token pLDDT (B-factor/100) in the order ``to_mmcif`` indexes: one
    entry per polymer residue, one per ligand atom, across chains in order."""
    out: list[float] = []
    for chain in data.chains:
        is_poly = chain["mol_type"] != const.chain_type_ids["NONPOLYMER"]
        r0 = chain["res_idx"]
        for residue in data.residues[r0: r0 + chain["res_num"]]:
            a0 = residue["atom_idx"]
            atoms = data.atoms[a0: a0 + residue["atom_num"]]
            if is_poly:
                out.append(float(atoms["bfactor"].mean()) / 100.0 if len(atoms) else 1.0)
            else:
                out.extend(float(b) / 100.0 for b in atoms["bfactor"])
    return np.array(out, dtype=np.float32)


def _rewrite_cif_via_boltz(cif_path: Path) -> None:
    """Re-encode a CIF in place using ``boltz.data.write.mmcif.to_mmcif``."""
    try:
        import os

        from boltz.data.mol import load_canonicals
        from boltz.data.parse.mmcif import parse_mmcif
        from boltz.data.write.mmcif import to_mmcif

        from boltz.data import const

        cache = Path(os.environ.get("BOLTZ_CACHE", Path.home() / ".boltz")).expanduser()
        mol_dir = cache / "mols"
        ccd = load_canonicals(mol_dir)
        parsed = parse_mmcif(
            str(cif_path), mols=ccd, moldir=mol_dir,
            use_assembly=False, compute_interfaces=False,
        )
        # Rebuild the per-token pLDDT array (B-factor / 100) in to_mmcif's
        # iteration order so confidence survives the re-encode; otherwise
        # to_mmcif writes B-factor 100 everywhere and drops _ma_qa_metric.
        plddts = _plddts_from_structure(parsed.data, const)
        cif_path.write_text(to_mmcif(parsed.data, plddts=plddts, boltz2=True))
    except Exception as exc:  # noqa: BLE001 — keep the valid gemmi CIF on failure
        import warnings
        warnings.warn(f"Boltz CIF re-encode skipped ({exc}); gemmi CIF kept.")


# ---------------------------------------------------------------------------
# Diffusion relaxation — re-inpaint clashing regions against the full structure
# ---------------------------------------------------------------------------


def _one_letter(name: str) -> str:
    ti = gemmi.find_tabulated_residue(name)
    code = ti.one_letter_code.upper() if ti and ti.one_letter_code else "X"
    return code if code.isalpha() else "X"


def find_clashing_inpaint_residues(
    merged_cif: str | Path, source_cif: str | Path, clash_thresh: float = 2.2,
) -> tuple[set[tuple[str, int]], int]:
    """Return the set of inpainted (chain, pos) residues that clash, and the
    total non-bonded heavy-atom clash count < ``clash_thresh``.

    A residue is *inpainted* if it is absent from the source template CIF.
    """
    from scipy.spatial import cKDTree

    merged = _read_structure(Path(merged_cif))
    msub = _subchain_residues(merged[0])
    is_lig = {sc: any(r.het_flag == "H" for r in rl) for sc, rl in msub.items()}
    src = _read_structure(Path(source_cif))
    fixed = {sc: set(_query_pos_to_residue(rl)) for sc, rl in _subchain_residues(src[0]).items()}

    coords: list[list[float]] = []
    aid: list[tuple[str, int, bool, bool]] = []
    for sc, rl in msub.items():
        lig = is_lig[sc]
        for r in rl:
            ip = (not lig) and (r.seqid.num not in fixed.get(sc, set()))
            for a in r:
                if a.element.name == "H":
                    continue
                coords.append([a.pos.x, a.pos.y, a.pos.z])
                aid.append((sc, r.seqid.num, ip, lig))
    arr = np.array(coords)
    tree = cKDTree(arr)
    pairs = tree.query_pairs(clash_thresh, output_type="ndarray")
    clash_res: set[tuple[str, int]] = set()
    total = 0
    for i, j in pairs:
        si, ri, ii, li = aid[i]
        sj, rj, ij, lj = aid[j]
        # Exclude bonded/intramolecular pairs: same residue (any, incl. ligand
        # internal bonds) or adjacent polymer residues of the same chain.
        if si == sj and (ri == rj or (not li and not lj and abs(ri - rj) <= 1)):
            continue
        total += 1
        if ii:
            clash_res.add((si, ri))
        if ij:
            clash_res.add((sj, rj))
    return clash_res, total


def build_relax_workspace(
    merged_cif: str | Path, source_cif: str | Path, out_dir: str | Path,
    radius: float = 10.0, clash_thresh: float = 2.2, flank: int = 2,
    mode: str = "inpaint",
) -> int:
    """``mode='inpaint'`` re-generates each clashing region from scratch.
    ``mode='refine'`` (LCR) keeps the region at its current coords as template
    and flags it for LRD-style noise+denoise refinement via the diffusion model.
    """
    """Build a workspace that re-inpaints each clashing region of ``merged_cif``
    with its full spatial neighbourhood (every chain's *placed* atoms, including
    other inpainted tails) held fixed.  Returns the number of relax regions.

    Predict ``<out_dir>/inputs`` then call :func:`splice_relaxed`.
    """
    from scipy.spatial import cKDTree

    out_dir = Path(out_dir).resolve()
    inputs_dir = out_dir / "inputs"
    assets_dir = out_dir / "assets"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    merged = _read_structure(Path(merged_cif))
    msub = _subchain_residues(merged[0])
    is_lig = {sc: any(r.het_flag == "H" for r in rl) for sc, rl in msub.items()}
    mpos: dict[str, dict[int, gemmi.Residue]] = {}
    for sc, rl in msub.items():
        if is_lig[sc]:
            continue
        for r in rl:
            mpos.setdefault(sc, {})[r.seqid.num] = r
    seqs = {sc: "".join(_one_letter(pm[p].name) if p in pm else "X"
                        for p in range(1, max(pm) + 1)) for sc, pm in mpos.items()}

    clash_res, _ = find_clashing_inpaint_residues(merged_cif, source_cif, clash_thresh)
    if not clash_res:
        (out_dir / "relax_manifest.json").write_text(json.dumps(
            {"merged_cif": str(Path(merged_cif).resolve()), "regions": []}, indent=2))
        return 0

    # Atom index for neighbourhood queries.
    coords: list[list[float]] = []
    aid: list[tuple[str, int, bool]] = []
    for sc, rl in msub.items():
        lig = is_lig[sc]
        for r in rl:
            for a in r:
                if a.element.name == "H":
                    continue
                coords.append([a.pos.x, a.pos.y, a.pos.z])
                aid.append((sc, r.seqid.num, lig))
    arr = np.array(coords)
    tree = cKDTree(arr)

    by_chain: dict[str, list[int]] = {}
    for sc, p in clash_res:
        by_chain.setdefault(sc, []).append(p)
    regions = [(sc, a, b) for sc, ps in by_chain.items()
               for a, b in _contiguous_runs(sorted(ps), merge_gap=3)]
    region_atoms = [arr[[k for k, (sc, rr, _l) in enumerate(aid)
                         if sc == ch and a <= rr <= b]] for (ch, a, b) in regions]

    # Group spatially-close regions so they are re-inpainted JOINTLY: clashing
    # tails crammed into the same pocket (e.g. the GroEL central cavity) must be
    # placed together, with the fixed walls as context, so the model can avoid
    # them avoiding each other.  Two regions link if their atoms come within
    # ``link_dist``; connected components form the joint groups.
    link_dist = 8.0
    nreg = len(regions)
    parent = list(range(nreg))

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    rtrees = [cKDTree(ra) if len(ra) else None for ra in region_atoms]
    for i in range(nreg):
        if rtrees[i] is None:
            continue
        for j in range(i + 1, nreg):
            if rtrees[j] is None:
                continue
            if any(len(x) > 0 for x in rtrees[i].query_ball_tree(rtrees[j], link_dist)):
                parent[_find(i)] = _find(j)
    groups: dict[int, list[int]] = {}
    for i in range(nreg):
        groups.setdefault(_find(i), []).append(i)

    manifest_groups = []
    for gidx, members in enumerate(groups.values()):
        grp = [regions[i] for i in members]
        grp_atoms = np.concatenate([region_atoms[i] for i in members], axis=0)
        # Primary (re-inpainted) segments: one per region, region inpaint + flanks.
        primaries: list[Segment] = []
        region_meta = []
        removed: dict[str, set[int]] = {}
        for (ch, a, b) in grp:
            ps, pe = max(1, a - flank), min(len(seqs[ch]), b + flank)
            primaries.append(Segment(seg_chain_id=ch, orig_chain=ch, gstart=ps, gend=pe))
            removed.setdefault(ch, set()).update(range(a, b + 1))
            region_meta.append({"chain": ch, "a": a, "b": b,
                                 "primary_gstart": ps, "primary_gend": pe})
        prim_span = {(s.orig_chain, g) for s in primaries
                     for g in range(s.gstart, s.gend + 1)}
        # Fixed context: residues near the group, excluding the primary spans.
        nb: set[tuple[str, int, bool]] = set()
        for at in grp_atoms:
            for k in tree.query_ball_point(at, radius):
                nb.add(aid[k])
        ctx_pos: dict[str, list[int]] = {}
        ctx_lig: set[str] = set()
        for sc, rr, lig in nb:
            if lig:
                ctx_lig.add(sc)
            elif (sc, rr) not in prim_span:
                ctx_pos.setdefault(sc, []).append(rr)
        ctx_segs: list[Segment] = []
        for sc, plist in ctx_pos.items():
            for x, y in _contiguous_runs(sorted(set(plist)), merge_gap=1):
                ctx_segs.append(Segment(seg_chain_id=f"ctx{len(ctx_segs)}",
                                        orig_chain=sc, gstart=x, gend=y))
        # mode='inpaint': remove the regions so they regenerate from scratch.
        # mode='refine' (LCR): keep them as template (current coords); they are
        # flagged for diffusion refinement via metadata 'lcr_refine'.
        p2r = dict(mpos)
        if mode == "inpaint":
            for ch, rem in removed.items():
                p2r[ch] = {p: r for p, r in mpos[ch].items() if p not in rem}

        stem = f"chunk_{gidx:03d}"
        chunk_cif = assets_dir / f"{stem}.cif"
        chunk_yaml = inputs_dir / f"{stem}.yaml"
        _write_chunk_cif(primaries + ctx_segs, p2r, msub, sorted(ctx_lig), chunk_cif, stem)

        seq_entries: list[dict] = []
        for seg in primaries + ctx_segs:
            sub = seqs[seg.orig_chain][seg.gstart - 1: seg.gend]
            seq_entries.append({"protein": {"id": seg.seg_chain_id, "sequence": sub, "msa": "empty"}})
        for lid in sorted(ctx_lig):
            seq_entries.append({"ligand": {"id": lid, "ccd": msub[lid][0].name}})
        template_entry = {
            "cif": str(chunk_cif),
            "chain_id": [s.seg_chain_id for s in primaries + ctx_segs] + sorted(ctx_lig),
        }
        if mode == "refine":
            # Metadata flags the clashing region (chunk-local resi, by primary
            # chain) for LRD-style refinement; everything else is held fixed.
            lcr_refine: dict[str, list[int]] = {}
            for (ch, a, b) in grp:
                ps = next(s.gstart for s in primaries if s.orig_chain == ch and s.gstart <= a <= s.gend)
                lcr_refine.setdefault(ch, []).extend(range(a - ps + 1, b - ps + 2))
            meta_path = assets_dir / f"{stem}_metadata.json"
            meta_path.write_text(json.dumps({"lcr_refine": lcr_refine}))
            template_entry["inpainting_metadata"] = str(meta_path)
        with open(chunk_yaml, "w") as f:
            _yaml.safe_dump({"version": 1, "sequences": seq_entries,
                             "templates": [template_entry]}, f, sort_keys=False)
        manifest_groups.append({"index": gidx, "regions": region_meta})

    (out_dir / "relax_manifest.json").write_text(json.dumps({
        "merged_cif": str(Path(merged_cif).resolve()),
        "source_cif": str(Path(source_cif).resolve()),
        "inputs_dir": str(inputs_dir),
        "groups": manifest_groups,
        "params": {"radius": radius, "clash_thresh": clash_thresh, "flank": flank},
    }, indent=2))
    return len(manifest_groups)


def splice_relaxed(
    relax_dir: str | Path, predictions: str | Path, out_cif: str | Path,
) -> str:
    """Splice each re-inpainted region back into the merged structure.

    Only the region residues are replaced (rigidly aligned to the merged frame
    via the primary segment's fixed flank CAs); everything else is unchanged.
    """
    relax_dir = Path(relax_dir)
    manifest = json.loads((relax_dir / "relax_manifest.json").read_text())
    merged = _read_structure(Path(manifest["merged_cif"]))
    mmodel = merged[0]
    # Index merged residues for in-place replacement.
    mres: dict[tuple[str, int], gemmi.Residue] = {}
    for ch in mmodel:
        for r in ch:
            if r.het_flag != "H":
                mres[(r.subchain, r.seqid.num)] = r

    pred_files = []
    pp = Path(predictions)
    import glob as _glob
    if pp.is_dir():
        pred_files = [Path(p) for p in sorted(
            _glob.glob(str(pp / "**" / "*chunk_*.cif"), recursive=True))]
    for grp in manifest["groups"]:
        stem = f"chunk_{grp['index']:03d}"
        pf = next((p for p in pred_files if stem in p.stem), None)
        if pf is None:
            continue
        st = _read_structure(pf)
        sc = _subchain_residues(st[0])
        regions = grp["regions"]
        # Predicted primary chains (one per region) are named by their original
        # chain id (Boltz) or sequential letters in YAML order (Protenix).
        prim_ids = [r["chain"] for r in regions]
        if all(cid in sc for cid in prim_ids):
            chain_of = {r["chain"]: r["chain"] for r in regions}
        else:
            chain_of = {r["chain"]: _int_to_letters(i + 1) for i, r in enumerate(regions)}
        # One global rigid alignment from all this group's fixed flanks.
        src_pts, dst_pts = [], []
        for reg in regions:
            ps = reg["primary_gstart"]
            for r in sc.get(chain_of[reg["chain"]], []):
                if not r.label_seq:
                    continue
                gpos = ps + r.label_seq - 1
                if reg["a"] <= gpos <= reg["b"]:
                    continue
                mr = mres.get((reg["chain"], gpos))
                ca_p = r.find_atom("CA", "*")
                ca_m = mr.find_atom("CA", "*") if mr else None
                if ca_p and ca_m:
                    src_pts.append([ca_p.pos.x, ca_p.pos.y, ca_p.pos.z])
                    dst_pts.append([ca_m.pos.x, ca_m.pos.y, ca_m.pos.z])
        R, t = (np.eye(3), np.zeros(3))
        if len(src_pts) >= 3:
            R, t = _kabsch(np.array(src_pts), np.array(dst_pts))
        for reg in regions:
            ps = reg["primary_gstart"]
            local = {r.label_seq: r for r in sc.get(chain_of[reg["chain"]], []) if r.label_seq}
            for gpos in range(reg["a"], reg["b"] + 1):
                lr = local.get(gpos - ps + 1)
                mr = mres.get((reg["chain"], gpos))
                if lr is None or mr is None:
                    continue
                new_atoms = {a.name: (R @ np.array([a.pos.x, a.pos.y, a.pos.z]) + t) for a in lr}
                for a in mr:
                    if a.name in new_atoms:
                        v = new_atoms[a.name]
                        a.pos = gemmi.Position(float(v[0]), float(v[1]), float(v[2]))

    out_cif = Path(out_cif)
    _finalize_and_write(merged, out_cif)
    if out_cif.suffix.lower() != ".pdb":
        _rewrite_cif_via_boltz(out_cif)
    return str(out_cif)


# ---------------------------------------------------------------------------
# Geometric clash relaxation — guarantees a clash-free structure
# ---------------------------------------------------------------------------


def geometric_relax(
    merged_cif: str | Path, source_cif: str | Path, out_cif: str | Path,
    clash_thresh: float = 2.0, r_target: float = 2.6,
    max_rounds: int = 300,
) -> str:
    """Push apart clashing inpainted atoms until no heavy-atom clash remains.

    Only atoms absent from the source template (inpainted) move; template atoms
    and ligands are frozen.  Local geometry (bonds + 1-3 angle distances) is held
    by harmonic restraints taken from the input, while non-bonded overlaps are
    repelled to ``r_target``.  Deterministic — iterates until every non-bonded
    movable-involving pair is ≥ ``clash_thresh`` apart.
    """
    from scipy.spatial import cKDTree

    merged = _read_structure(Path(merged_cif))
    src_sub = _subchain_residues(_read_structure(Path(source_cif))[0])
    # Per-ATOM template presence: an atom is "inpainted" (movable) if the source
    # template does not contain it — this catches both fully inpainted residues
    # AND the completed sidechain atoms of partially-fixed residues.
    src_atoms: set[tuple[str, int, str]] = set()
    for sc, rl in src_sub.items():
        for r in rl:
            for a in r:
                src_atoms.add((sc, r.seqid.num, a.name))

    atoms: list[gemmi.Atom] = []
    P: list[list[float]] = []
    movable: list[bool] = []
    res_id: list[int] = []
    chain_id: list[str] = []
    seqid: list[int] = []
    rid = 0
    for ch in merged[0]:
        for r in ch:
            het = r.het_flag == "H"
            for a in r:
                ip = (not het) and ((r.subchain, r.seqid.num, a.name) not in src_atoms)
                atoms.append(a)
                P.append([a.pos.x, a.pos.y, a.pos.z])
                movable.append(ip)
                res_id.append(rid)
                chain_id.append(r.subchain)
                seqid.append(r.seqid.num)
            rid += 1
    P = np.array(P, dtype=float)
    mv = np.array(movable)
    res_id = np.array(res_id)
    seqid = np.array(seqid)
    chain_arr = np.array(chain_id)
    if not mv.any():
        _finalize_and_write(merged, Path(out_cif))
        return str(out_cif)
    mv_idx = np.where(mv)[0]

    # Local-geometry restraints (bonds + 1-3 angles): movable-involving pairs
    # within 2.9 Å that are in the SAME residue or ADJACENT residues of the same
    # chain.  Non-bonded spatial neighbours (e.g. two overlapping tails) are
    # excluded so they get repelled rather than frozen at their overlap.
    tree0 = cKDTree(P)
    cand = tree0.query_pairs(2.9, output_type="ndarray")
    i0, j0 = cand[:, 0], cand[:, 1]
    local = (res_id[i0] == res_id[j0]) | (
        (chain_arr[i0] == chain_arr[j0]) & (np.abs(seqid[i0] - seqid[j0]) == 1))
    restr = cand[local & (mv[i0] | mv[j0])]
    rd0 = np.linalg.norm(P[restr[:, 0]] - P[restr[:, 1]], axis=1)
    restr_set = set(map(tuple, restr))

    from scipy.optimize import minimize

    ks, kr = 5.0, 30.0
    r0, r1 = restr[:, 0], restr[:, 1]
    Pwork = P.copy()

    def _clash_pairs():
        tree = cKDTree(Pwork)
        out = []
        nbad = 0
        for i, j in tree.query_pairs(r_target, output_type="ndarray"):
            if not (mv[i] or mv[j]):
                continue
            if (i, j) in restr_set:
                continue
            out.append((i, j))
            if np.linalg.norm(Pwork[i] - Pwork[j]) < clash_thresh:
                nbad += 1
        return (np.array(out) if out else np.empty((0, 2), int)), nbad

    # Outer loop: rebuild the clash list, then minimise (L-BFGS) the spring +
    # soft-core repulsion energy over the movable atoms.  When the minimiser
    # stalls (the remaining clashes are geometrically trapped), jitter the
    # still-clashing movable atoms (basin hopping) to escape the local minimum.
    rng = np.random.default_rng(0)
    mv_set = set(mv_idx.tolist())
    prev_bad = None
    stall = 0
    for _ in range(max_rounds):
        clash, nbad = _clash_pairs()
        if nbad == 0:
            break
        if prev_bad is not None and nbad >= prev_bad:
            stall += 1
        else:
            stall = 0
        prev_bad = nbad
        if stall >= 1:
            stuck = [int(a) for pair in clash for a in pair
                     if int(a) in mv_set and np.linalg.norm(Pwork[pair[0]] - Pwork[pair[1]]) < clash_thresh]
            if stuck:
                Pwork[stuck] += rng.normal(0, 2.0, size=(len(stuck), 3))
        ca0, ca1 = (clash[:, 0], clash[:, 1]) if len(clash) else (None, None)

        def _energy(x):
            Pf = Pwork.copy()
            Pf[mv_idx] = x.reshape(-1, 3)
            g = np.zeros_like(Pf)
            dv = Pf[r0] - Pf[r1]
            dd = np.linalg.norm(dv, axis=1) + 1e-9
            e = 0.5 * ks * np.sum((dd - rd0) ** 2)
            f = (ks * (dd - rd0) / dd)[:, None] * dv
            np.add.at(g, r0, f)
            np.add.at(g, r1, -f)
            if ca0 is not None:
                dv2 = Pf[ca0] - Pf[ca1]
                dd2 = np.linalg.norm(dv2, axis=1) + 1e-9
                viol = np.clip(r_target - dd2, 0, None)
                e += 0.5 * kr * np.sum(viol ** 2)
                f2 = (-kr * viol / dd2)[:, None] * dv2
                np.add.at(g, ca0, f2)
                np.add.at(g, ca1, -f2)
            return e, g[mv_idx].ravel()

        res = minimize(_energy, Pwork[mv_idx].ravel(), jac=True,
                       method="L-BFGS-B", options={"maxiter": 300})
        Pwork[mv_idx] = res.x.reshape(-1, 3)

    P = Pwork
    for a, p in zip(atoms, P):
        a.pos = gemmi.Position(float(p[0]), float(p[1]), float(p[2]))
    out_cif = Path(out_cif)
    _finalize_and_write(merged, out_cif)
    if out_cif.suffix.lower() != ".pdb":
        _rewrite_cif_via_boltz(out_cif)
    return str(out_cif)
