"""
PyMOL inpainting-region viewer — colour the inpainted regions on the whole
structure and save an image.

Reads a PATCHR inpainting metadata JSON (per chain: fully_inpainted_residues,
partially_fixed_residues) and colours:
    * template / fixed region : grey cartoon
    * fully inpainted region  : red
    * partially fixed (sidechain-completed) : orange
    * ligands                 : yellow sticks

Usage
-----
    pymol -cq scripts/inpaint_view.py -- <structure.cif> <metadata.json> [out.png]

Interactive:
    run scripts/inpaint_view.py
    inpaint_view <structure.cif>, <metadata.json>
"""
from pymol import cmd
import sys
import os
import json


def _ranges(nums):
    """Compact PyMOL resi selection string from a list of ints."""
    return "+".join(str(n) for n in sorted(set(nums)))


def inpaint_view(path, meta_path, png_out=None, obj="struct"):
    cmd.delete("all")
    cmd.load(path, obj)
    cmd.bg_color("white")
    cmd.hide("everything", obj)
    cmd.show("cartoon", obj)
    cmd.color("grey75", obj)
    cmd.set("cartoon_transparency", 0.15, obj)

    # ligands
    cmd.show("sticks", f"{obj} and not polymer and not solvent")
    cmd.color("yellow", f"{obj} and not polymer and not solvent")

    meta = json.load(open(meta_path))
    full_sel, part_sel = [], []
    n_full = n_part = 0
    for ch, cd in meta.get("chains", {}).items():
        full = cd.get("fully_inpainted_residues", []) or []
        part = [e["residue"] for e in cd.get("partially_fixed_residues", []) or []]
        if full:
            full_sel.append(f"(chain {ch} and resi {_ranges(full)})")
            n_full += len(full)
        if part:
            part_sel.append(f"(chain {ch} and resi {_ranges(part)})")
            n_part += len(part)

    if part_sel:
        cmd.select("inpaint_partial", f"{obj} and (" + " or ".join(part_sel) + ")")
        cmd.color("orange", "inpaint_partial")
    if full_sel:
        cmd.select("inpaint_full", f"{obj} and (" + " or ".join(full_sel) + ")")
        cmd.color("red", "inpaint_full")
        cmd.set("cartoon_transparency", 0.0, "inpaint_full")
        # emphasise the inpainted regions
        cmd.show("sticks", "inpaint_full and not (name C+N+O)")
        cmd.set("cartoon_putty_scale_max", 4.0)

    print(f"[inpaint_view] fully inpainted residues : {n_full}")
    print(f"[inpaint_view] partially fixed residues : {n_part}")

    cmd.orient(obj)
    cmd.deselect()
    if png_out:
        cmd.set("ray_opaque_background", 0)
        cmd.ray(2000, 1500)
        cmd.png(png_out, dpi=150)
        print(f"[inpaint_view] image written: {png_out}")


cmd.extend("inpaint_view", inpaint_view)

_args = [a for a in sys.argv[1:] if a != "--"]
if len(_args) >= 2 and os.path.exists(_args[0]) and os.path.exists(_args[1]):
    _path, _meta = _args[0], _args[1]
    _png = _args[2] if len(_args) > 2 else (os.path.splitext(_path)[0] + "_inpaint.png")
    inpaint_view(_path, _meta, _png)
