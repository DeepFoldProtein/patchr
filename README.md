<div align="center">
  <div>&nbsp;</div>

<img src="docs/e2e_demo.gif" width="480"/>

[Website](https://patchr.deepfold.org/) | [Atlas](https://patchr.deepfold.org/atlas) | [Paper](#cite) | [PATCHR-Studio](#patchr-studio)

</div>

<br/>

## Why PATCHR?

Most experimental structures in the PDB have **missing regions** -- flexible loops, disordered terminals, unresolved sidechains. These gaps block molecular dynamics simulations, drug design pipelines, and structural analysis.

PATCHR fills them in. It generates physically plausible coordinates for missing segments while keeping your existing experimental structure **exactly as-is**.

- Works with **proteins, DNA, RNA**, and multi-chain complexes
- Preserves all original atomic coordinates -- zero drift
- 99.4% of reconstructed structures have **no connectivity issues**
- Handles everything from short loops to 600+ residue extensions

## Quick Start

```bash
git clone https://github.com/DeepFoldProtein/patchr.git
cd patchr
pip install -e .[cuda]          # Boltz-2 backend
pip install -e .[cuda,protenix] # + Protenix (AlphaFold 3) backend
```

**Step 1.** Generate a YAML template from a PDB structure:

```bash
# Single chain
python scripts/generate_inpainting_template.py 4ZLO A,B

# With UniProt sequence (for terminal extensions)
python scripts/generate_inpainting_template.py 4ZLO A,B --uniprot

# From a local CIF file
python scripts/generate_inpainting_template.py --input structure.cif A,B
```

This auto-detects missing regions and outputs a YAML + template CIF to `examples/inpainting/`.

**Step 2.** Run inpainting with Boltz-2:

```bash
boltz predict examples/inpainting/4zlo_AB.yaml \
  --model boltz2_inpaint \
  --accelerator gpu \
  --out_dir results
```

Or with **Protenix** (AlphaFold 3-based):

```bash
# Generate a Protenix JSON instead of a YAML
python scripts/generate_inpainting_template.py 4ZLO A,B --format protenix-json

# Run inference (inpainting requires protenix_base_default_v1.0.0)
PYTHONPATH="$(pwd)" python runner/inference.py \
  --model_name protenix_base_default_v1.0.0 \
  --input_path examples/inpainting/5k7g_AEFG.yaml \
  --dump_dir results \
  --seeds 42
```

The first run downloads the model checkpoint automatically to `~/checkpoint/`.

> **Note:** Inpainting requires `protenix_base_default_v1.0.0`. Mini/tiny models use reduced diffusion parameters (5 steps, no stochastic noise) that cannot produce connected boundaries. If a different model is specified with an inpainting input, it will be automatically overridden.

> For CPU-only or non-CUDA GPUs, use `pip install -e .` instead. See [prediction docs](docs/prediction.md) for all options.

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

<details>
<summary><b>More template generation options</b></summary>

```bash
# All polymer chains (one per entity)
python scripts/generate_inpainting_template.py 1CK4 all

# All chains including duplicate copies
python scripts/generate_inpainting_template.py 1CK4 all-copies

# Custom output directory
python scripts/generate_inpainting_template.py 1CK4 A,B -o my_templates/

# Include solvent atoms
python scripts/generate_inpainting_template.py 7EOQ A --include-solvent

# Use biological assembly
python scripts/generate_inpainting_template.py 1CK4 all --assembly best
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
