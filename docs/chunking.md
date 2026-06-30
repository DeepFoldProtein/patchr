# Chunking large targets

Large inpainting targets (long chains, or assemblies with many chains) can be
split into smaller, independently-predictable sub-problems and stitched back
together. This is implemented in [`src/boltz/chunking.py`](../src/boltz/chunking.py)
and exposed as two CLI subcommands:

```bash
patchr chunk  <input.yaml> -o <workspace>      # split into chunks
patchr predict <workspace>/inputs --out_dir <workspace>/predictions
patchr merge  <workspace>/chunk_manifest.json <workspace>/predictions   # stitch
```

`scripts/slurm-chunk-test.sh <workspace> [steps]` runs the predict + merge steps
on the cluster.

Both prediction backends are supported. The chunk YAMLs are valid input for
either `patchr predict --backend boltz2` (default) or `--backend protenix`, and
`patchr merge` reads the output of either — it maps the predicted chains back to
each chunk's segments/ligands automatically, whether the backend preserves the
chain ids (Boltz) or renames them to sequential letters (Protenix).

## Workspace layout

`patchr chunk -o <workspace>` writes:

```
<workspace>/
  inputs/              # chunk_000.yaml … — ONLY YAMLs (what `patchr predict` consumes)
  assets/              # chunk_000.cif + chunk_000_metadata.json — sliced templates
  chunk_manifest.json  # how chunks map back to the source (used by `patchr merge`)
  predictions/         # created by `patchr predict`; the merged structure also
                       # lands here as <source>_merged.cif (+ .pdb)
```

`inputs/` is kept YAML-only because `patchr predict <dir>` rejects any non-YAML
file or sub-directory. The merged structure is written **inside `predictions/`**
so all outputs live together.

## How chunks are chosen — `domain` decomposition

Each polymer chain is cut into **contiguous** chunks, with cut **boundaries
placed optimally using spatial information** so the backbone is preserved:

1. A residue–residue contact graph is built from the template coordinates
   (`scipy.spatial.cKDTree.query_pairs`, contacts = CA–CA within
   `--contact_radius`, default 8 Å, sequence separation ≥ 4).
2. For each cut position, count the *tertiary* contacts that cross it.
3. **Dynamic programming** finds the exact contiguous segmentation, with each
   chunk ≤ `--chunk_size` residues, that **minimises the total crossed
   contacts** — so boundaries land at spatial necks (domain linkers) and the
   backbone is cut as few times as possible (once per chunk join).
4. Each segment is expanded by an `--overlap` halo on each side for clash-free
   stitching.

For a chain shorter than `--chunk_size` (e.g. each 155-residue capsid subunit),
the whole chain is a single chunk. Multi-chain inputs are chunked per chain.

### Ligands

Each ligand is carried into the **single** chunk whose residues contact it
(nearest-atom distance ≤ `--ligand_cutoff`, default 6 Å), placed at its template
position. Distant bulk-solvent ligands are dropped so they cannot float into an
inpainted region.

## How chunks are stitched — `patchr merge`

All chunks share the original template coordinate frame, so the merge is a
clash-free reassembly:

- **Ownership.** Each global residue is taken from the chunk where it is most
  *interior* (nearest the chunk centre), so a residue in an overlap comes from
  one chunk only.
- **Fixed (template-anchored) residues** are copied **verbatim from the
  template** — identical in every chunk, so a chunk seam in a fixed region
  produces *no* backbone break. Their B-factor is overwritten with the model
  pLDDT (the template carries crystal B-factors).
- **Inpainted residues** come from the model output, with each contiguous
  inpaint run rigidly aligned onto its flanking template residues (best of
  both / N-only / C-only flank fits). Any residual break then sits only where
  the crystal itself is disordered.
- **Residue order.** Residues are emitted in ascending sequence order.

### Optional loop closure — `--close_loops`

A disordered inpaint loop is sometimes placed as a "tail" dangling off one
anchor. `--close_loops` bridges such a loop by treating it as a rigid body:

1. seat its better-connected end at the correct bond distance from that anchor;
2. converge both backbone bonds by alternating rigid hinges about each anchor
   plus a translation that balances the two end-bonds (a rigid-body CCD);
3. rotate the loop about its end-to-end axis to point the bulge away from the
   structure and avoid steric clashes.

Single-anchor terminal tails are simply seated at bond distance. This **models**
a region the crystal does not resolve, so it is **opt-in**. A mild residual
clash may remain — run `patchr sim-ready <merged.cif>` (energy minimisation) for
a physically clean loop.

## Confidence (pLDDT)

Per-residue pLDDT from the chunk predictions is preserved through the merge
(B-factor column + `_ma_qa_metric_local`), so Mol\*'s *Color → Quality / pLDDT*
works. Inpainted regions show low pLDDT, template-anchored regions high.

## Output format

All structures are written as standard mmCIF that viewers render as a cartoon
(full `_entity_poly` / `_pdbx_poly_seq_scheme` / `auth_*` records). The merged
structure is encoded through Boltz's `to_mmcif`, with per-residue pLDDT carried
into both the B-factor column and `_ma_qa_metric_local`. A `.pdb` sibling is
written alongside it when the chain naming fits the PDB format.

## Scale

The protocol runs end-to-end on large assemblies — e.g. a 60-chain viral capsid
(1C2Y assembly 2, 9,360 residues + 60 ligands): 60 chunks predicted in ~2.4 min
on one GPU and merged in ~5 s into a viewer-ready CIF.

## CLI reference

`patchr chunk`:

| option | default | meaning |
|--------|---------|---------|
| `--chunk_size` | 384 | max residues per chunk core (before overlap) |
| `--overlap` | 48 | overlap halo added each side |
| `--contact_radius` | 8.0 | Å defining a residue–residue contact in the DP cost |
| `--ligand_cutoff` | 6.0 | Å max distance to carry a ligand into a chunk |
| `--chain` | all | restrict to comma-separated polymer chain ids |

`patchr merge`:

| option | default | meaning |
|--------|---------|---------|
| `-o, --out` | `<predictions>/<source>_merged.cif` | output path |
| `--close_loops` | off | bridge dangling inpainted loops/termini (models unresolved structure) |
| `--relax` | off | deterministically remove all heavy-atom clashes (see below) |
| `--no_superpose` | off | skip overlap-CA superposition |

## Guaranteed clash-free output — `--relax`

Inpainted regions can clash with parts of the structure that were not in their
chunk (e.g. long disordered tails crammed into a pocket clashing with each
other across chains).  The diffusion model cannot always pack such regions
clash-free.  `patchr merge --relax` adds a deterministic final step that pushes
apart clashing **inpainted** atoms — template atoms and ligands are frozen
(their experimental / anchored coordinates do not move at all), local
geometry (bonds + 1-3 angles) is restrained, and a soft-core repulsion with
L-BFGS minimisation plus basin-hopping drives every non-bonded heavy-atom pair
above the clash threshold.  Movability is per-atom, so completed side-chain
atoms of partially-fixed residues are relaxed too.  The result is a structure
with **zero heavy-atom clashes** and no backbone breaks; only the inpainted
atoms move.
