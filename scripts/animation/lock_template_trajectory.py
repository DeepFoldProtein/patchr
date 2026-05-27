"""
Post-process a Boltz `detailed_trajectory_*.npz` so the template atoms appear
fixed in space across all frames, and only the inpainted region visibly moves.

The diffusion loop runs in the model's centered/augmented frame, so the raw
trajectory arrays drift en bloc each step. We undo that drift by Procrustes-
aligning every frame's `template_coords[t]` back to `initial_template_coords`
(using `template_mask` atoms only) and applying the same rigid transform to
`atom_coords[t]`. The result is a multi-model PDB where the template region is
visually static and the inpainted atoms 'bubble up' over the schedule.

Usage:
    python scripts/animation/lock_template_trajectory.py \
        --npz outputs/4zlo_traj/.../detailed_trajectory_4zlo_model_0.npz \
        --cif outputs/4zlo_traj/.../4zlo_model_0.cif \
        --out outputs/4zlo_traj/locked_trajectory_4zlo_model_0.pdb
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def kabsch(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Best-fit rigid transform aligning ``src`` to ``dst``.

    Returns (R, c_src, c_dst) so that for any point set ``X``,
    ``aligned = (X - c_src) @ R + c_dst`` is in ``dst``'s frame.
    """
    c_src = src.mean(axis=0)
    c_dst = dst.mean(axis=0)
    H = (src - c_src).T @ (dst - c_dst)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = U @ D @ Vt
    return R, c_src, c_dst


def lock_template(
    atom_coords: np.ndarray,
    template_coords: np.ndarray,
    init_template: np.ndarray,
    template_mask: np.ndarray,
) -> np.ndarray:
    """Per-frame inverse-Kabsch so the template atoms align with their initial pose."""
    T = atom_coords.shape[0]
    locked = np.empty_like(atom_coords)
    src_t = template_coords[:, template_mask]   # (T, M, 3)
    dst = init_template[template_mask]          # (M, 3)
    for t in range(T):
        R, c_src, c_dst = kabsch(src_t[t], dst)
        locked[t] = (atom_coords[t] - c_src) @ R + c_dst
    return locked


def load_atom_table(cif_path: Path):
    """Return parallel arrays describing each atom from a Boltz mmCIF output."""
    from biotite.structure.io.pdbx import CIFFile, get_structure

    cif = CIFFile.read(str(cif_path))
    structure = get_structure(cif, model=1)
    return structure


def write_multi_model_pdb(
    structure,  # unused — kept for backwards compatibility
    locked_coords: np.ndarray,  # (T, N, 3)
    output_path: Path,
    reference_cif: Path = None,
) -> None:
    """Write a multi-state mmCIF by text-templating the reference CIF.

    PyMOL's ``cmd.save`` for multi-state mmCIF strips ``auth_seq_id`` /
    ``auth_comp_id`` (and reorders columns) which breaks downstream bond
    inference on the inpaint atoms. Instead of going through PyMOL we just
    rewrite the reference CIF's ``_atom_site`` loop, duplicating it T times
    with substituted coordinates and incremented ``pdbx_PDB_model_num``. Every
    other block (``_chem_comp``, ``_struct_conn``, …) is kept verbatim, so the
    resulting file behaves like the original CIF in any viewer.
    """
    if reference_cif is None:
        raise ValueError("Multi-state CIF write requires reference_cif.")
    suffix = output_path.suffix.lower()
    if suffix not in (".cif", ".mmcif"):
        raise ValueError(f"Only .cif/.mmcif output is supported (got {suffix})")

    # PyMOL infers bonds from the FIRST state of a multi-state mmCIF; the
    # first diffusion frame's coords are spread over thousands of Å (post σ_init
    # noise injection) so distance-based bond inference fails on ~600 inpaint
    # atoms. To get a standalone-loadable file, prepend the *final* (converged)
    # frame as state 1 so PyMOL has clean geometry to bond from, then put the
    # full trajectory as states 2..T+1. The render script can skip state 1 when
    # playing back.
    final_frame = locked_coords[-1:]
    locked_coords = np.concatenate([final_frame, locked_coords], axis=0)

    T, N, _ = locked_coords.shape
    ref_text = reference_cif.read_text()
    lines = ref_text.splitlines()

    # 1. Find _atom_site loop bounds.
    atom_header_start = atom_data_start = atom_data_end = None
    column_names: list[str] = []
    for i, line in enumerate(lines):
        if atom_header_start is None and line.strip().startswith("_atom_site."):
            atom_header_start = i
        if atom_header_start is not None and line.strip().startswith("_atom_site."):
            column_names.append(line.strip())
        if atom_header_start is not None and atom_data_start is None and not line.strip().startswith("_atom_site."):
            atom_data_start = i
        if atom_data_start is not None and atom_data_end is None and (
            line.strip() == "#" or line.strip().startswith("loop_") or line.strip().startswith("_")
        ):
            atom_data_end = i
            break
    if atom_header_start is None or atom_data_start is None:
        raise RuntimeError("Could not locate _atom_site loop in reference CIF.")
    if atom_data_end is None:
        atom_data_end = len(lines)

    # 2. Indices of the columns we need to touch.
    try:
        idx_x = column_names.index("_atom_site.Cartn_x")
        idx_y = column_names.index("_atom_site.Cartn_y")
        idx_z = column_names.index("_atom_site.Cartn_z")
        idx_model = column_names.index("_atom_site.pdbx_PDB_model_num")
        idx_id = column_names.index("_atom_site.id")
    except ValueError as exc:
        raise RuntimeError(f"_atom_site missing required column: {exc}")

    atom_lines_template = [lines[i].split() for i in range(atom_data_start, atom_data_end)]
    # Drop blank rows
    atom_lines_template = [r for r in atom_lines_template if r]
    if len(atom_lines_template) != N:
        raise RuntimeError(
            f"_atom_site has {len(atom_lines_template)} rows but NPZ expects {N}"
        )

    print(f"  Templating {N} atoms × {T} states from reference CIF…")

    new_atom_lines: list[str] = []
    for t in range(T):
        coords_t = locked_coords[t]
        for atom_idx, row in enumerate(atom_lines_template):
            row = list(row)
            row[idx_x] = f"{coords_t[atom_idx, 0]:.3f}"
            row[idx_y] = f"{coords_t[atom_idx, 1]:.3f}"
            row[idx_z] = f"{coords_t[atom_idx, 2]:.3f}"
            row[idx_model] = str(t + 1)
            row[idx_id] = str(t * N + atom_idx + 1)
            new_atom_lines.append(" ".join(row))

    # 3. Splice: keep [0..atom_data_start) header, replace atom data block.
    out_lines = lines[:atom_data_start] + new_atom_lines + lines[atom_data_end:]
    output_path.write_text("\n".join(out_lines) + "\n")


def _extract_cif_block(text: str, block_name: str) -> str:
    """Return the contiguous mmCIF block (header lines + loop body) whose first
    line is ``loop_`` followed by ``block_name.*`` items, or just the bare
    ``block_name.*`` lines for a single-row category. Returns empty string if
    the block isn't found.
    """
    lines = text.splitlines()
    out: list[str] = []
    in_block = False
    started_with_loop = False
    for i, line in enumerate(lines):
        if not in_block:
            if line.startswith(f"{block_name}."):
                # Check if previous non-blank line was 'loop_'
                j = i - 1
                while j >= 0 and lines[j].strip() == "":
                    j -= 1
                if j >= 0 and lines[j].strip() == "loop_":
                    out.append("loop_")
                    started_with_loop = True
                in_block = True
                out.append(line)
            continue
        # Inside the block.
        stripped = line.strip()
        if stripped == "#" or (
            stripped.startswith("_") and not stripped.startswith(f"{block_name}.")
        ) or stripped == "loop_":
            break
        out.append(line)
    return "\n".join(out)


def _inject_chem_comp_and_struct_conn(locked_cif: Path, reference_cif: Path) -> None:
    """Append _chem_comp and _struct_conn blocks from ``reference_cif`` into
    ``locked_cif`` so PyMOL/Mol*/ChimeraX can resolve bonds for the inpaint
    region (whose geometry is slightly off the CCD template)."""
    ref_text = reference_cif.read_text()
    blocks = []
    for name in ("_chem_comp", "_entity", "_entity_poly", "_entity_poly_seq",
                 "_struct_conn_type", "_struct_conn", "_pdbx_entity_nonpoly",
                 "_pdbx_poly_seq_scheme", "_pdbx_nonpoly_scheme", "_struct_asym"):
        b = _extract_cif_block(ref_text, name)
        if b:
            blocks.append(b)
    if not blocks:
        return

    appendix = "\n".join("\n#\n" + b for b in blocks) + "\n#\n"
    with locked_cif.open("a") as f:
        f.write(appendix)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--npz", required=True, type=Path, help="detailed_trajectory_*.npz")
    p.add_argument("--cif", required=True, type=Path,
                   help="Reference CIF (final structure) — provides atom names/residues for PDB output.")
    p.add_argument("--out", required=True, type=Path, help="Output multi-model PDB path.")
    p.add_argument("--include-initial", action="store_true",
                   help="Prepend the initial pure-noise frame (frame 0).")
    args = p.parse_args()

    data = np.load(args.npz)
    required = ("atom_coords", "template_coords", "initial_template_coords", "template_mask")
    missing = [k for k in required if k not in data.files]
    if missing:
        raise SystemExit(f"NPZ is missing required keys: {missing}")

    atom_coords = data["atom_coords"]                 # (T, N, 3)
    template_coords = data["template_coords"]         # (T, N, 3)
    init_template = data["initial_template_coords"]   # (N, 3)
    template_mask = data["template_mask"].astype(bool)  # (N,)

    print(
        f"Trajectory: T={atom_coords.shape[0]} frames, N={atom_coords.shape[1]} atoms, "
        f"M={int(template_mask.sum())} template atoms"
    )

    locked = lock_template(atom_coords, template_coords, init_template, template_mask)

    if args.include_initial:
        # Synthesize a "step 0" frame: template atoms at their pristine pose,
        # inpaint atoms at the σ_init noise scale around the inpaint centroid in
        # the original frame. (initial_coords in the NPZ is in the model's
        # centered frame, so we don't reuse it directly.)
        sigma_init = float(data["sigmas"][0])
        rng = np.random.default_rng(0)
        init_frame = np.empty_like(atom_coords[0])
        init_frame[template_mask] = init_template[template_mask]
        # Center the inpaint noise around the inpaint region's mean position in
        # the final locked structure (so the bubble appears in roughly the right
        # neighbourhood, not 2500 Å away).
        inpaint_anchor = locked[-1, ~template_mask].mean(axis=0)
        init_frame[~template_mask] = inpaint_anchor + sigma_init * rng.standard_normal(
            ((~template_mask).sum(), 3)
        )
        locked = np.concatenate([init_frame[None], locked], axis=0)

    # Diagnostics: how static is the template (stage 0 only — LRD intentionally
    # perturbs the "fixed" region up to a few Å) and how much does inpaint move?
    stages = data["stages"]
    stage0 = stages == 0
    tmpl_disp_s0 = np.linalg.norm(
        locked[-len(stages) :][stage0][:, template_mask] - init_template[template_mask],
        axis=-1,
    )
    print(f"Template displacement after lock (stage 0): mean={tmpl_disp_s0.mean():.4f}Å, "
          f"max={tmpl_disp_s0.max():.4f}Å (should be < 0.01)")
    if stage0.sum() < len(stages):
        tmpl_disp_s1 = np.linalg.norm(
            locked[-len(stages) :][~stage0][:, template_mask] - init_template[template_mask],
            axis=-1,
        )
        print(f"Template displacement after lock (LRD):     mean={tmpl_disp_s1.mean():.4f}Å, "
              f"max={tmpl_disp_s1.max():.2f}Å (LRD perturbs boundary residues)")
    inpaint_displacement = np.linalg.norm(
        locked[:, ~template_mask] - locked[-1, ~template_mask], axis=-1
    )
    print(f"Inpaint displacement vs final:    mean={inpaint_displacement.mean():.2f}Å, "
          f"max={inpaint_displacement.max():.2f}Å, final-step mean={inpaint_displacement[-1].mean():.4f}Å")

    write_multi_model_pdb(None, locked, args.out, reference_cif=args.cif)
    print(f"Wrote {locked.shape[0]} models → {args.out}  ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
