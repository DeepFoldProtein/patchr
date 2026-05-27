"""
Render a "denoising bubble-up" animation from a locked trajectory CIF/PDB.

Reads ``inpainting_metadata_*.json`` to identify the inpaint residues per chain
and the per-step sigma schedule from the NPZ to skip the initial blow-out
frames. Styles:

  - Template (fixed PDB region) → static grey cartoon, always
  - Inpaint region, early frames → spacefill spheres (no cartoon — the random
    point cloud "bubbles" around)
  - Inpaint region, last N frames → spheres fade out and cartoon fades in,
    so the structure visibly emerges from the cloud at the end

Designed to run inside the visualization venv that ships PyMOL:

    .venv_viz/bin/python scripts/animation/render_pymol.py \\
        --cif outputs/4zlo_traj/locked_trajectory_4zlo_model_0.cif \\
        --metadata outputs/4zlo_traj/patchr_results_4zlo/predictions/4zlo/inpainting_metadata_4zlo.json \\
        --npz outputs/4zlo_traj/patchr_results_4zlo/predictions/4zlo/detailed_trajectory_4zlo_model_0.npz \\
        --out-dir outputs/4zlo_traj/frames \\
        --width 800 --height 600

Frame stitching to MP4/GIF is delegated to ffmpeg in a separate step.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from pymol import cmd


def build_boundary_selection_from_mask(
    boundary_mask: np.ndarray,
    structure_atom_order,  # biotite AtomArray annotations from the locked CIF
) -> str:
    """Build a PyMOL selection covering the atoms flagged as LRD-active.

    `boundary_mask` is a per-atom boolean from the NPZ aligned with the locked
    trajectory's atom order. We translate it into ``(chain X and resi Y and name Z)``
    fragments grouped into a single PyMOL selection expression.
    """
    if boundary_mask is None or not boundary_mask.any():
        return "none"
    chain_ids = structure_atom_order.chain_id
    res_ids = structure_atom_order.res_id
    atom_names = structure_atom_order.atom_name

    # Group atoms by (chain, residue) to keep selection compact.
    from collections import defaultdict

    by_chain_res: dict = defaultdict(set)
    for i, in_mask in enumerate(boundary_mask):
        if in_mask:
            # biotite returns np.str_; cast to Python str so repr doesn't emit
            # "np.str_('A')" which PyMOL can't parse.
            by_chain_res[(str(chain_ids[i]), int(res_ids[i]))].add(str(atom_names[i]))

    # Selection: per residue, list all flagged atoms by name (in case it's a
    # subset of the residue's atoms). repr-quote the chain so non-alphanumeric
    # chain IDs (e.g. "B-2") survive PyMOL's selection parser.
    parts = []
    for (chain, resi), names in by_chain_res.items():
        names_pat = "+".join(sorted(names))
        parts.append(f"(chain {chain!r} and resi {resi} and name {names_pat})")
    return " or ".join(parts) if parts else "none"


def build_inpaint_selection(metadata_path: Path) -> str:
    """Translate the inpainting metadata JSON into a single PyMOL selection
    expression covering both fully-inpainted and partially-fixed residues."""
    meta = json.loads(metadata_path.read_text())
    parts = []
    for chain, info in meta.get("chains", {}).items():
        inp = set(info.get("fully_inpainted_residues", []) or [])
        for entry in info.get("partially_fixed_residues", []) or []:
            if isinstance(entry, dict) and "residue" in entry:
                inp.add(entry["residue"])
            elif isinstance(entry, int):
                inp.add(entry)
        if not inp:
            continue
        # PyMOL accepts comma-separated resi lists.
        resi_list = "+".join(str(r) for r in sorted(inp))
        # Quote chain because it may contain non-alphanumerics like "-".
        parts.append(f"(chain {chain!r} and resi {resi_list})")
    if not parts:
        return "none"
    return " or ".join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cif", required=True, type=Path,
                   help="Reference CIF — either the locked multi-model CIF, or (recommended) "
                        "the prediction's final 4zlo_model_0.cif so PyMOL can keep full bonds.")
    p.add_argument("--metadata", required=True, type=Path,
                   help="inpainting_metadata_<id>.json next to the prediction.")
    p.add_argument("--npz", required=False, type=Path, default=None,
                   help="detailed_trajectory_*.npz — read to (a) skip early σ-blow-out frames "
                        "and (b) when --cif points at a single-state result CIF, build the "
                        "multi-state locked trajectory in-memory (avoids biotite's bond loss).")
    p.add_argument("--sigma-cutoff", type=float, default=30.0,
                   help="Skip frames whose schedule sigma exceeds this (default 30). "
                        "Requires --npz; ignored if not supplied.")
    p.add_argument("--morph-frames", type=int, default=25,
                   help="Last N rendered frames cross-fade: inpaint spheres → cartoon.")
    p.add_argument("--out-dir", required=True, type=Path,
                   help="Directory to write per-frame PNGs.")
    p.add_argument("--width", type=int, default=800)
    p.add_argument("--height", type=int, default=600)
    p.add_argument("--ray", action="store_true",
                   help="Ray-trace each frame (paper quality, ~10x slower).")
    p.add_argument("--every", type=int, default=1,
                   help="Render every Nth main-diffusion state (default 1).")
    p.add_argument("--lrd-every", type=int, default=None,
                   help="Stride for LRD (boundary refinement) frames; defaults to "
                        "--every. Set lower (e.g. 1) to spend more screen-time on "
                        "the wiggle.")
    p.add_argument("--intro-frames", type=int, default=0,
                   help="Number of intro frames to prepend (held by ffmpeg "
                        "afterwards). Only used when --input-template-cif is set.")
    p.add_argument("--input-template-cif", type=Path, default=None,
                   help="Path to the original input template CIF (the file from "
                        "examples/inpainting/, before prediction). Rendered as "
                        "the intro: just the existing residues with DSSP-assigned "
                        "cartoon, gaps left as real chain breaks. No ghost cartoon, "
                        "no placeholder dots.")
    p.add_argument("--orient-state", type=int, default=None,
                   help="State to use for camera orientation (default = last).")
    p.add_argument("--rotate-x", type=float, default=0.0,
                   help="Rotate around X (screen horizontal) after orient. "
                        "E.g. 90 to look down the assembly's principal axis "
                        "(nucleosome top-down view).")
    p.add_argument("--rotate-y", type=float, default=0.0,
                   help="Rotate around Y (screen vertical) after orient.")
    p.add_argument("--rotate-z", type=float, default=0.0,
                   help="Rotate around Z (out of screen) after orient.")
    p.add_argument("--zoom-buffer", type=float, default=6.0,
                   help="Zoom buffer in Å after orient/rotate. Increase for "
                        "large complexes that get clipped after rotation.")
    p.add_argument("--show-drift", action="store_true",
                   help="Skip the Kabsch template-lock so the template drifts "
                        "with the model's diffusion frame. Useful to visualize "
                        "that the template is tracking the denoised output, "
                        "not held fixed.")
    p.add_argument("--hide-inpaint", action="store_true",
                   help="Hide the inpaint atoms entirely. Pairs well with "
                        "--show-drift: only the rigid template is drawn, "
                        "making translation+rotation drift cleanly visible.")
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    cmd.feedback("disable", "all", "actions")
    cmd.feedback("disable", "all", "results")
    cmd.bg_color("white")
    cmd.set("ray_shadows", 0)
    cmd.set("ambient", 0.3)
    cmd.set("specular", 0.2)
    cmd.set("cartoon_transparency", 0.0)
    # Set the OpenGL viewport explicitly — cmd.draw() ignores the width/height
    # args otherwise and falls back to the default 640×480 viewport, which makes
    # semi-transparent cartoons (the intro ghost) look muddy because the alpha
    # blending samples too few pixels.
    cmd.viewport(args.width, args.height)
    cmd.set("antialias", 2)

    print(f"Loading {args.cif} ...")
    cmd.load(str(args.cif), "traj")
    n_states = cmd.count_states("traj")
    n_atoms = cmd.count_atoms("traj")
    print(f"  {n_states} states, {n_atoms} atoms, bonded={cmd.count_atoms('traj and bound_to traj')}")

    # If the CIF is single-state and a trajectory NPZ is supplied, run the
    # text-template lock script to materialize a multi-state CIF on disk and
    # reload it. (We don't lock via cmd.alter_state because PyMOL reorders
    # atoms into CCD-canonical order on load, scrambling coords against the
    # NPZ's row order — ligand atoms end up at chain-B-2 positions and look
    # like they're moving during the trajectory.)
    if n_states == 1 and args.npz is not None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lock_template_trajectory",
            str(Path(__file__).parent / "lock_template_trajectory.py"),
        )
        ltt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ltt)

        npz_lock = np.load(args.npz)
        if npz_lock["atom_coords"].shape[1] != n_atoms:
            raise SystemExit(
                f"NPZ has {npz_lock['atom_coords'].shape[1]} atoms but CIF has "
                f"{n_atoms}; --cif and --npz must come from the same prediction."
            )
        suffix = "_drift" if args.show_drift else "_locked"
        locked_path = args.out_dir.parent / f"{suffix}_{args.cif.stem}.cif"
        locked_path.parent.mkdir(parents=True, exist_ok=True)
        if args.show_drift:
            print(f"  --show-drift: skipping Kabsch lock; using raw atom_coords")
            print(f"  Materializing drift trajectory at {locked_path} …")
            locked = npz_lock["atom_coords"]
        else:
            print(f"  Materializing locked trajectory at {locked_path} …")
            locked = ltt.lock_template(
                npz_lock["atom_coords"], npz_lock["template_coords"],
                npz_lock["initial_template_coords"], npz_lock["template_mask"].astype(bool),
            )
        ltt.write_multi_model_pdb(None, locked, locked_path, reference_cif=args.cif)

        cmd.delete("traj")
        cmd.load(str(locked_path), "traj")
        n_states = cmd.count_states("traj")
        n_atoms = cmd.count_atoms("traj")
        bonded = cmd.count_atoms("traj and bound_to traj")
        print(f"  Locked CIF reloaded: states={n_states}, atoms={n_atoms}, bonded={bonded}")

    # Assign secondary structure on the final state so the cartoon rep has
    # something sensible to draw for the inpainted backbone too. cmd.dss
    # WITHOUT an explicit state= silently averages/picks across all states,
    # which corrupts SS assignment in multi-state objects whose early states
    # have noisy geometry (helices drop helix=260→233, sheets drop 92→44).
    cmd.set("state", n_states)
    cmd.dss("traj", state=n_states)

    # Build inpaint selection. Prefer the NPZ's template_mask (atom-level,
    # includes RNA/DNA inpaint atoms that the metadata JSON doesn't track —
    # e.g. 8GZR's chain C RNA). Fall back to the metadata JSON otherwise.
    inpaint_from_npz = False
    if args.npz is not None:
        _npz_full = np.load(args.npz)
        if "template_mask" in _npz_full.files:
            tmask = _npz_full["template_mask"].astype(bool)
            # Get atom order from PyMOL — needs CCD-canonical, so we read it
            # back via iterate and match by index against the NPZ order. PyMOL
            # may have reordered atoms within residues; we match (chain, resi,
            # name) tuples. The NPZ atom order matches the prediction CIF order
            # (= biotite/result CIF row order).
            from biotite.structure.io.pdbx import CIFFile, get_structure
            struct = get_structure(CIFFile.read(str(args.cif)), model=1)
            if struct.array_length() == len(tmask):
                pymol_atoms = []
                cmd.iterate("traj", "pymol_atoms.append((chain, int(resi), name))",
                            space={"pymol_atoms": pymol_atoms})
                biotite_keys = list(zip(
                    [str(c) for c in struct.chain_id],
                    [int(r) for r in struct.res_id],
                    [str(n) for n in struct.atom_name],
                ))
                # PyMOL→biotite index map
                biotite_to_pymol: dict = {}
                for pi, key in enumerate(pymol_atoms):
                    biotite_to_pymol[key] = pi
                inpaint_pymol_indices = []
                for bi, key in enumerate(biotite_keys):
                    if not tmask[bi] and key in biotite_to_pymol:
                        inpaint_pymol_indices.append(biotite_to_pymol[key])
                if inpaint_pymol_indices:
                    # PyMOL "index" is 1-based per object; iterate yields the
                    # ordering we used, so its position in pymol_atoms+1 is the
                    # `index` selector for that atom.
                    idx_pat = "+".join(str(i + 1) for i in inpaint_pymol_indices)
                    inpaint_sel = f"traj and index {idx_pat}"
                    inpaint_from_npz = True
    if not inpaint_from_npz:
        inpaint_sel = build_inpaint_selection(args.metadata)
        print(f"Inpaint selection (from metadata JSON): {inpaint_sel[:120]}…")
    else:
        print(f"Inpaint selection: from NPZ template_mask "
              f"({len(inpaint_pymol_indices)} atoms)")
    cmd.select("inpaint", inpaint_sel)
    cmd.select("template", "(not inpaint) and polymer")
    print(f"  template atoms: {cmd.count_atoms('template')}")
    print(f"  inpaint atoms:  {cmd.count_atoms('inpaint')}")

    # Identify nucleic-acid chains so we can color them distinctly for emphasis.
    cmd.select("nucleic_chains", "polymer.nucleic")
    n_nuc = cmd.count_atoms("nucleic_chains")
    if n_nuc > 0:
        print(f"  Nucleic-acid atoms: {n_nuc} (will be highlighted)")

    # Optional: LRD boundary atoms — get highlighted during stage-1 frames.
    # We use a NARROWER set than the model's ±3-residue boundary for clarity:
    # only the residues immediately adjacent to a template↔inpaint flip (±1).
    boundary_mask_np = None
    if args.npz is not None:
        _npz = np.load(args.npz)
        if "boundary_mask" in _npz.files and "template_mask" in _npz.files:
            try:
                from biotite.structure.io.pdbx import CIFFile, get_structure
                cif_atoms = get_structure(CIFFile.read(str(args.cif)), model=1)
                model_boundary = _npz["boundary_mask"].astype(bool)
                tmpl_mask_atoms = _npz["template_mask"].astype(bool)

                if cif_atoms.array_length() != len(model_boundary):
                    print(f"[WARN] boundary_mask size {len(model_boundary)} "
                          f"!= structure size {cif_atoms.array_length()} — skipping LRD highlight")
                else:
                    # Reduce to per-residue template membership, then find
                    # template↔inpaint flips along each chain. Highlighted set =
                    # residues at the flip ± 1.
                    chain_ids = cif_atoms.chain_id
                    res_ids = cif_atoms.res_id
                    from collections import defaultdict
                    res_is_template: dict = {}
                    for i in range(len(tmpl_mask_atoms)):
                        key = (str(chain_ids[i]), int(res_ids[i]))
                        # A residue is "template" if any of its atoms are.
                        res_is_template[key] = res_is_template.get(key, False) or bool(tmpl_mask_atoms[i])
                    # Group residue keys by chain, sorted by residue id.
                    by_chain: dict = defaultdict(list)
                    for (chain, resi) in res_is_template:
                        by_chain[chain].append(resi)
                    transition_residues = set()
                    for chain, resis in by_chain.items():
                        resis_sorted = sorted(resis)
                        flags = [res_is_template[(chain, r)] for r in resis_sorted]
                        for k in range(len(resis_sorted) - 1):
                            if flags[k] != flags[k + 1]:
                                # Just the two residues sitting at the flip
                                # (the actual template↔inpaint adjacency).
                                for offset in (0, 1):
                                    idx = k + offset
                                    if 0 <= idx < len(resis_sorted):
                                        transition_residues.add(
                                            (chain, resis_sorted[idx])
                                        )
                    # Build PyMOL selection.
                    by_chain_resi: dict = defaultdict(list)
                    for chain, resi in transition_residues:
                        by_chain_resi[chain].append(resi)
                    if by_chain_resi:
                        parts = []
                        for chain, resis in by_chain_resi.items():
                            resi_pat = "+".join(str(r) for r in sorted(resis))
                            parts.append(f"(chain {str(chain)!r} and resi {resi_pat})")
                        narrow_sel = " or ".join(parts)
                        cmd.select("lrd_boundary", narrow_sel)
                        n_bnd = cmd.count_atoms("lrd_boundary")
                        n_res = len(transition_residues)
                        print(f"  LRD boundary highlight: {n_res} residues "
                              f"({n_bnd} atoms) at template↔inpaint flip residues")
                        if n_bnd > 0:
                            boundary_mask_np = True  # flag — actual mask not used directly
            except Exception as exc:
                print(f"[WARN] Could not build narrow LRD selection: {exc}")
                boundary_mask_np = None

    # Base style: template = grey cartoon, always visible.
    # Inpaint: spheres (full spacefill) early, then in the morph phase the
    # spheres shrink to small CA markers while the cartoon is revealed beneath.
    # Both representations use solid opacity throughout — no cross-fade — so the
    # morph doesn't go through a muddy half-transparent state.
    cmd.hide("everything")
    cmd.show("cartoon", "template")
    if args.hide_inpaint:
        # In drift-vis mode we only want to see the rigid template moving.
        # Make it darker so it doesn't read as "ghost" against the background.
        cmd.color("grey50", "template and polymer.protein")
        cmd.color("forest", "template and polymer.nucleic")
    else:
        cmd.color("grey80", "template")
    cmd.color("orange", "inpaint and polymer.protein")
    cmd.color("magenta", "inpaint and polymer.nucleic")
    if not args.hide_inpaint:
        cmd.show("spheres", "inpaint")
    cmd.set("sphere_scale", 1.0, "inpaint")  # spacefill, fully opaque
    cmd.set("sphere_transparency", 0.0, "inpaint")
    # Cartoon for the inpaint region is enabled but the rep is hidden initially;
    # we toggle it on at the morph_start frame (no transparency tricks).
    cmd.set("cartoon_transparency", 0.0, "inpaint")
    cmd.hide("cartoon", "inpaint")
    # Cartoon settings to make sheets / helices read cleanly even when the
    # inpaint backbone hasn't fully tightened.
    cmd.set("cartoon_smooth_loops", 1)
    cmd.set("cartoon_fancy_helices", 1)
    cmd.set("cartoon_flat_sheets", 1)
    cmd.set("cartoon_rect_length", 1.5)
    cmd.set("cartoon_rect_width", 0.4)
    # Nucleic acid styling: distinct color from protein. Template RNA/DNA in
    # pale green so it reads as "existing nucleic backbone", inpaint RNA/DNA in
    # bright magenta so the reconstructed nucleotides pop visually.
    cmd.set("cartoon_ring_mode", 3)   # show ring bases as flat shapes
    cmd.set("cartoon_ring_finder", 1)
    cmd.set("cartoon_nucleic_acid_mode", 4)  # smoothed backbone + rings
    cmd.color("palegreen", "template and polymer.nucleic")
    cmd.color("magenta", "inpaint and polymer.nucleic")

    # Ligands (non-polymer, non-solvent): always-visible sticks with element
    # colours plus a tinted carbon. 4ZLO has 4PV (kinase inhibitor) and GOL
    # (glycerol) — both render the same way unless the user picks specific
    # residue names to omit.
    cmd.select("ligands", "organic and not resn HOH")
    n_lig = cmd.count_atoms("ligands")
    if n_lig > 0:
        cmd.show("sticks", "ligands")
        cmd.color("cyan", "ligands and elem C")
        cmd.set("stick_radius", 0.18, "ligands")
        # Avoid auto-zoom triggering on ligand show.
        print(f"  Ligand atoms: {n_lig}")

    # Camera: orient on the full polymer (both chains) using the FINAL state
    # only. orient/zoom without an explicit state= argument averages bounding
    # boxes across all states, which blows the camera out because early-
    # diffusion frames have atoms ±1000 Å away. The state= kwarg restricts to
    # one frame.
    orient_state = args.orient_state if args.orient_state is not None else n_states
    cmd.set("state", orient_state)
    cmd.orient("polymer", state=orient_state)
    if args.rotate_x:
        cmd.turn("x", args.rotate_x)
    if args.rotate_y:
        cmd.turn("y", args.rotate_y)
    if args.rotate_z:
        cmd.turn("z", args.rotate_z)
    cmd.zoom("polymer", buffer=args.zoom_buffer, state=orient_state)
    cmd.set("auto_zoom", 0)

    # Decide which states to render. If an NPZ + sigma cutoff is provided, drop
    # the early σ-blow-out frames where atoms sit hundreds of Å outside the
    # camera. The σ schedule has length 200 (main) + ~25 (LRD) = 225 — the
    # locked CIF has 226 if --include-initial was used (extra synthesized frame
    # 0). We map by index from the end.
    skip_until = 0
    state_stage = {}  # state_index → 0 (main) | 1 (LRD), used to switch styling
    state_step = {}   # state_index → step number within its stage (for label)
    if args.npz is not None:
        npz = np.load(args.npz)
        sigmas = npz["sigmas"]
        stages = npz["stages"] if "stages" in npz.files else np.zeros(len(sigmas), dtype=np.int8)
        # Locked CIF state numbering: states 1..n_states. If n_states > len(sigmas),
        # there's a synthetic step-0 frame at the front (--include-initial).
        offset = n_states - len(sigmas)
        # First state with σ ≤ cutoff:
        for j, s in enumerate(sigmas):
            if s <= args.sigma_cutoff:
                skip_until = j + offset  # 1-based state index right before keep
                break
        else:
            skip_until = n_states - 1
        print(f"σ schedule: first index ≤ {args.sigma_cutoff} is "
              f"sigmas[{skip_until - offset}]={sigmas[max(0, skip_until - offset)]:.3f}; "
              f"skipping states 1..{skip_until} ({skip_until} early frames dropped)")
        # Map state index → stage/step (1-based state numbering in the CIF).
        # state = j + offset + 1 for sigmas[j].
        main_step_count = int((stages == 0).sum())
        lrd_step_count = int((stages == 1).sum())
        for j, s in enumerate(stages):
            state = j + offset + 1
            state_stage[state] = int(s)
            if s == 0:
                state_step[state] = (j + 1, main_step_count)
            else:
                state_step[state] = (j + 1 - main_step_count, lrd_step_count)
        if lrd_step_count > 0:
            print(f"  stages: main={main_step_count}, LRD={lrd_step_count}")

    # Use separate strides for main vs LRD so the LRD wiggle can get more
    # screen time without bloating the main-diffusion section.
    lrd_every = args.lrd_every if args.lrd_every is not None else args.every
    main_candidates = [
        s for s in range(skip_until + 1, n_states + 1, args.every)
        if state_stage.get(s, 0) == 0
    ]
    lrd_candidates = [
        s for s in range(skip_until + 1, n_states + 1, lrd_every)
        if state_stage.get(s, 0) == 1
    ]
    states_to_render = sorted(set(main_candidates + lrd_candidates))
    if not states_to_render or states_to_render[-1] != n_states:
        states_to_render.append(n_states)
    n_render = len(states_to_render)
    print(f"Rendering {n_render} frames at {args.width}x{args.height} "
          f"({'ray' if args.ray else 'draw'})")

    # The morph (spheres → cartoon) is timed to finish at the LAST main-diffusion
    # frame, so the cartoon is fully formed by the time LRD takes over. If
    # there's no LRD in this run, morph still completes at the final frame.
    main_frames_rendered = [
        i for i, st in enumerate(states_to_render, start=1)
        if state_stage.get(st, 0) == 0
    ]
    last_main_out_idx = main_frames_rendered[-1] if main_frames_rendered else n_render
    morph_start = max(0, last_main_out_idx - args.morph_frames)
    print(f"  morph: frames {morph_start + 1}..{last_main_out_idx} "
          f"(spheres→cartoon over main diffusion's tail)")
    if last_main_out_idx < n_render:
        print(f"  LRD frames: {last_main_out_idx + 1}..{n_render} "
              f"(boundary atoms highlighted)")

    # Intro frames (optional): show the template alone with gaps highlighted,
    # before any noise. The template-flanking residues at each gap (lrd_boundary,
    # which is the template↔inpaint flip set) get a red highlight so the viewer
    # can see WHERE the inpainting will happen.
    intro_count = max(0, int(args.intro_frames))
    if intro_count > 0 and args.input_template_cif is not None:
        print(f"  Intro: {intro_count} frames from input template CIF "
              f"({args.input_template_cif.name})")
        # Load the actual input template (with real missing residues — gaps
        # have no atoms, so PyMOL's cartoon naturally shows chain breaks
        # instead of bridging across them).
        cmd.load(str(args.input_template_cif), "intro_obj")
        cmd.dss("intro_obj")
        # Boltz centers the template's coords (subtracts centroid) before
        # processing, so the locked trajectory ends up at the origin while the
        # raw input CIF still has its original offset. align intro_obj onto the
        # trajectory's final state using common template residues so the camera
        # stays consistent across the intro→noise transition.
        # `cycles=0` forces a one-shot alignment with no outlier rejection,
        # since the inpaint residues are missing from intro_obj.
        cmd.align("intro_obj", "traj", target_state=orient_state, cycles=0)
        # Hide the trajectory object for the intro shot.
        cmd.disable("traj")
        cmd.show("cartoon", "intro_obj")
        cmd.color("grey80", "intro_obj and polymer.protein")
        cmd.color("palegreen", "intro_obj and polymer.nucleic")
        # Ligands inside intro_obj — match the styling used elsewhere.
        cmd.show("sticks", "intro_obj and organic and not resn HOH")
        cmd.color("cyan", "intro_obj and organic and elem C")
        cmd.set("stick_radius", 0.18, "intro_obj and organic")

        for intro_idx in range(1, intro_count + 1):
            png_path = args.out_dir / f"frame_{intro_idx:04d}.png"
            if args.ray:
                cmd.ray(args.width, args.height)
                cmd.png(str(png_path))
            else:
                cmd.draw(args.width, args.height, antialias=2)
                cmd.png(str(png_path))

        cmd.delete("intro_obj")
        cmd.enable("traj")
    elif intro_count > 0:
        print(f"  [WARN] --intro-frames={intro_count} but no --input-template-cif "
              f"provided; skipping intro.")
        intro_count = 0

    if args.hide_inpaint:
        cmd.hide("everything", "inpaint")

    for out_idx, state in enumerate(states_to_render, start=1):
        cmd.set("state", state)
        stage = state_stage.get(state, 0)

        if args.hide_inpaint:
            # Drift-vis mode: skip all per-frame inpaint styling.
            pass
        elif stage == 0:
            # Stage 0 — main diffusion.
            if out_idx <= morph_start:
                # Pre-morph: spheres only (spacefill), no cartoon on inpaint.
                cmd.hide("cartoon", "inpaint")
                cmd.set("sphere_scale", 1.0, "inpaint")
                cmd.show("spheres", "inpaint")
                cmd.color("orange", "inpaint and polymer.protein")
                cmd.color("magenta", "inpaint and polymer.nucleic")
            else:
                # Morph: shrink spheres while cartoon emerges underneath.
                t = (out_idx - morph_start) / max(1, last_main_out_idx - morph_start)
                t = min(1.0, max(0.0, t))
                ts = t * t * (3 - 2 * t)  # smoothstep
                cmd.show("cartoon", "inpaint")
                sphere_scale = 1.0 - 0.75 * ts  # 1.0 → 0.25
                cmd.set("sphere_scale", sphere_scale, "inpaint")
                if t > 0.5:
                    cmd.hide("spheres", "inpaint and not name CA")
                else:
                    cmd.show("spheres", "inpaint")
                cmd.color("orange", "inpaint and polymer.protein")
                cmd.color("magenta", "inpaint and polymer.nucleic")
        else:
            # Stage 1 — LRD (boundary refinement).
            # Cartoon ribbon at boundary residues stays red (subtle wiggle as
            # backbone shifts 1-2 Å each step). We overlay red spacefill on the
            # boundary residues during most of LRD so the per-atom motion is
            # obvious, then shrink the spheres back to zero over the final
            # ~25% of the LRD section so the closing frame is pure cartoon.
            cmd.show("cartoon", "inpaint")
            cmd.hide("spheres", "inpaint")
            cmd.color("orange", "inpaint and polymer.protein")
            cmd.color("magenta", "inpaint and polymer.nucleic")
            if boundary_mask_np is not None and cmd.count_atoms("lrd_boundary") > 0:
                cmd.color("red", "byres lrd_boundary")
                # Position within the LRD block (1-based step).
                lrd_step = out_idx - last_main_out_idx
                lrd_total = n_render - last_main_out_idx
                fade_window = max(1, lrd_total // 4)
                fade_start = lrd_total - fade_window  # last 25% fades
                if lrd_step <= fade_start:
                    scale = 0.7
                else:
                    # Linear shrink 0.7 → 0 over the fade window.
                    t = (lrd_step - fade_start) / fade_window
                    t = min(1.0, max(0.0, t))
                    scale = 0.7 * (1.0 - t)
                if scale > 0.02:
                    cmd.show("spheres", "byres lrd_boundary")
                    cmd.set("sphere_scale", scale, "byres lrd_boundary")
                    cmd.set("sphere_transparency", 0.0, "byres lrd_boundary")
                else:
                    cmd.hide("spheres", "byres lrd_boundary")

        frame_no = out_idx + intro_count  # shift past intro files
        png_path = args.out_dir / f"frame_{frame_no:04d}.png"
        if args.ray:
            cmd.ray(args.width, args.height)
            cmd.png(str(png_path))
        else:
            cmd.draw(args.width, args.height, antialias=2)
            cmd.png(str(png_path))
        if out_idx % 25 == 0 or out_idx == n_render:
            print(f"  frame {frame_no}/{n_render + intro_count} (state {state})")

    print(f"Done. Stitch with:")
    print(f"  ffmpeg -framerate 24 -i {args.out_dir}/frame_%04d.png "
          f"-c:v libx264 -pix_fmt yuv420p -crf 18 {args.out_dir.parent / 'animation.mp4'}")


if __name__ == "__main__":
    main()
