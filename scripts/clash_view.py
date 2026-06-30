"""
PyMOL clash viewer — highlight where steric clashes are in a structure.

Non-bonded heavy-atom pairs closer than a threshold (default 2.0 Å) are treated
as clashes.  Clashing residues are drawn as red sticks, clashing atoms as red
spheres, dashed lines connect the clashing pairs, and a per-chain / per-residue
report is printed (and saved next to the structure).

Usage
-----
Headless (writes a report + a PNG):
    pymol -cq scripts/clash_view.py -- <structure.cif|pdb> [thresh] [png_out]

Interactive (in the PyMOL command line):
    run scripts/clash_view.py
    clash_view <structure.cif>, 2.0

Bonded pairs (same residue, or consecutive residues in the same chain) are
excluded so only true clashes are shown.
"""
from pymol import cmd
import sys
import os
from collections import Counter


def _resi_int(resi):
    try:
        return int(resi)
    except ValueError:
        return None


def clash_view(path, thresh=2.0, png_out=None, obj="struct"):
    thresh = float(thresh)
    cmd.delete("all")
    cmd.load(path, obj)

    # Base style: translucent grey cartoon + ligands as sticks.
    cmd.hide("everything", obj)
    cmd.show("cartoon", obj)
    cmd.color("grey80", obj)
    cmd.set("cartoon_transparency", 0.55, obj)
    cmd.show("sticks", f"{obj} and not polymer and not solvent")
    cmd.color("yellow", f"{obj} and not polymer and not solvent")
    cmd.bg_color("white")

    # atom index -> identity
    info = {}
    cmd.iterate(f"{obj} and not hydro",
                "info[index] = (chain, resi, resn, name, elem)",
                space={"info": info})

    # All heavy-atom pairs within the threshold.
    pairs = cmd.find_pairs(f"{obj} and not hydro",
                           f"{obj} and not hydro",
                           cutoff=thresh, mode=0)

    clash_atoms = set()
    clash_res = set()
    by_chain = Counter()
    by_res = Counter()
    seen = set()
    n_clash = 0
    for (m1, i1), (m2, i2) in pairs:
        if i1 == i2:
            continue
        key = (i1, i2) if i1 < i2 else (i2, i1)
        if key in seen:
            continue
        seen.add(key)
        a, b = info.get(i1), info.get(i2)
        if not a or not b:
            continue
        ch1, r1 = a[0], a[1]
        ch2, r2 = b[0], b[1]
        # exclude bonded: same residue, or adjacent residue in the same chain
        ri1, ri2 = _resi_int(r1), _resi_int(r2)
        if ch1 == ch2 and (r1 == r2 or
                           (ri1 is not None and ri2 is not None and abs(ri1 - ri2) <= 1)):
            continue
        n_clash += 1
        clash_atoms.add(i1)
        clash_atoms.add(i2)
        clash_res.add((ch1, r1))
        clash_res.add((ch2, r2))
        by_chain[ch1] += 1
        by_chain[ch2] += 1
        by_res[(ch1, r1)] += 1
        by_res[(ch2, r2)] += 1

    # ---- selections + styling ----
    if clash_atoms:
        idx = "+".join(str(i) for i in sorted(clash_atoms))
        cmd.select("clash_atoms", f"{obj} and index {idx}")
        cmd.select("clash_res", f"byres clash_atoms")
        cmd.show("sticks", "clash_res")
        cmd.show("spheres", "clash_atoms")
        cmd.set("sphere_scale", 0.30, "clash_atoms")
        cmd.color("red", "clash_res")
        cmd.color("firebrick", "clash_atoms")
        cmd.set("cartoon_transparency", 0.0, "clash_res")
        # dashed contacts between clashing atoms
        cmd.distance("clash_contacts", "clash_atoms", "clash_atoms", thresh, mode=0)
        cmd.color("red", "clash_contacts")
        cmd.hide("labels", "clash_contacts")
        cmd.orient("clash_res")
    cmd.deselect()

    # ---- report ----
    lines = []
    lines.append(f"# Clash report for {os.path.basename(path)}  (heavy-atom < {thresh} Å, non-bonded)")
    lines.append(f"total clashes          : {n_clash}")
    lines.append(f"clashing residues      : {len(clash_res)}")
    lines.append("")
    lines.append("clashes per chain (top 20):")
    for ch, c in by_chain.most_common(20):
        lines.append(f"  chain {ch:<4} : {c}")
    lines.append("")
    lines.append("worst residues (top 30):")
    for (ch, r), c in by_res.most_common(30):
        lines.append(f"  {ch}/{r:<5} : {c}")
    report = "\n".join(lines)
    print("\n" + report + "\n")
    rp = os.path.splitext(path)[0] + "_clashes.txt"
    try:
        with open(rp, "w") as f:
            f.write(report + "\n")
        print(f"[clash_view] report written: {rp}")
    except OSError:
        pass

    if png_out:
        cmd.set("ray_opaque_background", 0)
        cmd.ray(1600, 1200)
        cmd.png(png_out, dpi=150)
        print(f"[clash_view] image written: {png_out}")


cmd.extend("clash_view", clash_view)

# Headless entry point. PyMOL strips '--' and leaves the args in sys.argv[1:].
_args = [a for a in sys.argv[1:] if a != "--"]
if _args and os.path.exists(_args[0]):
    _path = _args[0]
    _thresh = _args[1] if len(_args) > 1 else 2.0
    _png = _args[2] if len(_args) > 2 else (os.path.splitext(_path)[0] + "_clashes.png")
    clash_view(_path, _thresh, _png)
