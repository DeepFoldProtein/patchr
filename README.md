<div align="center">
  <div>&nbsp;</div>

<img src="docs/e2e_demo.gif" width="480"/>

[Website](https://patchr.deepfold.org/) | [Atlas](https://patchr.deepfold.org/atlas) | [Paper](#cite) | [PATCHR-Studio](#patchr-studio)

</div>

<br/>

## Why PATCHR?

Most experimental structures in the PDB have **missing regions** -- flexible loops, disordered terminals, unresolved sidechains. These gaps block molecular dynamics simulations, drug design pipelines, and structural analysis.

PATCHR fills them in. It is a **model-agnostic inpainting method** that plugs into diffusion-based structure prediction models as a backend. Generate physically plausible coordinates for missing segments while keeping your existing experimental structure **exactly as-is**.

- **Backend-agnostic** -- currently supports [Boltz-2](https://github.com/jwohlwend/boltz) and [Protenix](https://github.com/bytedance/protenix), with more models coming
- Works with **proteins, DNA, RNA**, and multi-chain complexes
- Preserves all original atomic coordinates -- zero drift
- 99.4% of reconstructed structures have **no connectivity issues**
- Handles everything from short loops to 600+ residue extensions

## Quick Start

```bash
git clone https://github.com/DeepFoldProtein/patchr.git
cd patchr
pip install -e .
```

**Step 1.** Generate a template from a PDB structure:

```bash
patchr template 4ZLO A,B
```

This auto-detects missing regions and writes a YAML + template CIF to `examples/inpainting/`.

**Step 2.** Run inpainting:

```bash
patchr predict examples/inpainting/4zlo_AB.yaml --out_dir results
```

The first run downloads the model checkpoint automatically to `~/.boltz/`.

<details>
<summary><b>Template generation options</b></summary>

```bash
# With UniProt sequence (for terminal extensions)
patchr template 4ZLO A,B --uniprot

# From a local CIF file
patchr template --input structure.cif A,B

# All polymer chains (one per entity)
patchr template 1CK4 all

# All chains including duplicate copies
patchr template 1CK4 all-copies

# Custom output directory
patchr template 1CK4 A,B -o my_templates/

# Include solvent atoms
patchr template 7EOQ A --include-solvent

# Use biological assembly
patchr template 1CK4 all --assembly best
```

</details>

<details>
<summary><b>Prediction backends</b></summary>

PATCHR works as a plugin on top of supported structure prediction models. Choose your backend with `--backend`:

```bash
# Boltz-2 (default)
patchr predict input.yaml --out_dir results --backend boltz2

# Protenix (AlphaFold 3-based)
patchr predict input.yaml --out_dir results --backend protenix --seed 42

# Protenix with multiple seeds
patchr predict input.yaml --out_dir results --backend protenix --seeds 42,101,202
```


</details>

<details>
<summary><b>Prediction options</b></summary>

```bash
# Multiple diffusion samples
patchr predict input.yaml --out_dir results --diffusion_samples 5

# With MSA server
patchr predict input.yaml --out_dir results --use_msa_server

# With potentials
patchr predict input.yaml --out_dir results --use_potentials

# Disable boundary refinement
patchr predict input.yaml --out_dir results --disable_boundary_refinement

# Custom seed
patchr predict input.yaml --out_dir results --seed 42
```

</details>

<details>
<summary><b>Mac installation</b></summary>

```bash
conda create --name patchr python=3.12 llvmlite==0.44.0 numba==0.61.0 numpy==1.26.3
conda activate patchr
git clone https://github.com/DeepFoldProtein/patchr.git
cd patchr && pip install -e .
export KMP_DUPLICATE_LIB_OK=TRUE
```

</details>

## Output Format

All backends produce the same output structure:

```
results/patchr_results_{input_name}/
├── predictions/
│   └── {input_name}/
│       ├── {input_name}_model_0.cif          # Predicted structure
│       ├── confidence_{input_name}_model_0.json  # Confidence scores
│       ├── pae_{input_name}_model_0.npz      # PAE matrix (optional)
│       └── pde_{input_name}_model_0.npz      # PDE matrix (optional)
└── processed/                                 # Preprocessed data (Boltz only)
```


## Simulation-Ready Output

Add `--sim-ready` to `patchr predict` to go directly from structure completion to MD simulation input -- no manual steps.

```bash
# Predict + prepare GROMACS input
patchr predict input.yaml --out_dir results --sim-ready gromacs

# Predict + prepare AMBER input with AMBER ff
patchr predict input.yaml --out_dir results --sim-ready amber --ff amber14sb
```

Automatically adds hydrogens, solvates, and neutralizes with counter ions. Generates CHARMM-GUI-style output with topology (`toppar/` directory), coordinates, index file, MDP files for minimization/equilibration/production, and a run script.

<details>
<summary><b>Standalone sim-ready command</b></summary>

You can also run this on any existing CIF file:

```bash
patchr sim-ready prediction.cif --engine gromacs --ff charmm36m
patchr sim-ready prediction.cif --engine openmm --padding 1.2 --ion-conc 0.15
```

</details>

## How It Works

PATCHR uses diffusion-based generation conditioned on your experimental structure as a rigid template. Three key techniques make this work:

| | Technique | What it does |
|---|---|---|
| 1 | **Template Conditioning** | Anchors known coordinates at every diffusion step so the experimental structure is never modified |
| 2 | **Synchronized Rigid Template Tracking** | Keeps the template aligned with the evolving generation -- no frame drift |
| 3 | **Local Refinement Denoising** | Cleans up bond geometry at the junction between template and generated regions |

The result: seamless, chemically valid reconstructions that integrate perfectly with the original structure.

## PATCHR-Studio

A desktop app with a visual interface for the full workflow -- no command line needed.

Available at [patchr.deepfold.org](https://patchr.deepfold.org/).

**No GPU?** Run the server on Google Colab for free and connect from PATCHR-Studio:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/DeepFoldProtein/patchr/blob/main/colab_server.ipynb)

## Server

Start a REST API server for use with PATCHR-Studio or custom clients:

```bash
patchr serve --model boltz2 --device-id 0
patchr serve --model protenix --port 8080
patchr serve --model all  # Load both backends
```

See `patchr serve --help` for all options.

## PATCHR Atlas

Pre-computed completed structures for ~35,000 monomeric proteins (and growing to ~160,000 complexes including RNA, DNA, and multi-chain assemblies). Browse and download simulation-ready structures without running anything locally.

[Explore the Atlas &rarr;](https://patchr.deepfold.org/atlas)

## Performance

Evaluated on 1,000 PDB40 structures with realistic missing region patterns:

| Metric | Value |
|---|---|
| Backbone RMSD (missing residues) | 1.78 &#8491; |
| lDDT (missing atoms) | 98.6 |
| Connectivity pass rate | 99.4% |

<details>
<summary><b>Breakdown by structure type</b></summary>

| Region | RMSD (&#8491;) | | Accessibility | RMSD (&#8491;) |
|---|---|---|---|---|
| Helix | 0.30 | | Buried | 0.39 |
| Strand | 0.26 | | Intermediate | 0.65 |
| Loop | 0.85 | | Surface | 1.01 |

</details>

## License

MIT -- free for academic and commercial use.

## Acknowledgments

PATCHR builds upon [Boltz-2](https://doi.org/10.1101/2025.06.14.659707) by Passaro, Corso, Wohlwend et al. We thank the Boltz team for making their model and code openly available.

If you use automatic MSA generation, please also cite [ColabFold](https://doi.org/10.1038/s41592-022-01488-1) (Mirdita et al., 2022).

## Cite

```bibtex
@article{bae2025patchr,
  author = {Bae, Hanjin and Kim, Kunwoo and Yoo, Jejoong and Joo, Keehyoung},
  title = {PATCHR-Studio: Template-conditioned diffusion-based molecular structure
           inpainting for Protein, RNA, and DNA complexes},
  year = {2025}
}
```
