# PATCHR Prediction Guide

Full reference for running structure predictions with PATCHR.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Step 1: Template Generation](#step-1-template-generation)
- [Step 2: Prediction](#step-2-prediction)
- [Input Format (YAML)](#input-format-yaml)
- [Output Format](#output-format)
- [Backends](#backends)
- [Simulation-Ready Output](#simulation-ready-output)
- [CLI Reference](#cli-reference)
- [Server Mode](#server-mode)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)

---

## Installation

Requires Python 3.11+ and a CUDA-capable GPU (recommended).

```bash
git clone https://github.com/DeepFoldProtein/patchr.git
cd patchr
pip install -e .
```

<details>
<summary>Mac (Apple Silicon / MPS)</summary>

```bash
conda create --name patchr python=3.12 llvmlite==0.44.0 numba==0.61.0 numpy==1.26.3
conda activate patchr
git clone https://github.com/DeepFoldProtein/patchr.git
cd patchr && pip install -e .
export KMP_DUPLICATE_LIB_OK=TRUE
```

MPS is supported but runs significantly slower than CUDA. CPU fallback is also available.
</details>

---

## Quick Start

```bash
# 1. Generate template from PDB
patchr template 4ZLO A,B

# 2. Run prediction
patchr predict examples/inpainting/4zlo_AB.yaml --out_dir results
```

The first run downloads the Boltz-2 checkpoint (~1.5 GB) to `~/.boltz/`.

---

## Step 1: Template Generation

`patchr template` downloads a PDB structure, extracts specified chains, detects missing regions, and outputs the YAML + CIF files needed for prediction.

### Basic Usage

```bash
# From PDB ID with specific chains
patchr template 4ZLO A,B

# From PDB ID with UniProt sequence (includes terminal extensions)
patchr template 4ZLO A,B --uniprot

# From a local CIF file
patchr template --input structure.cif A,B

# Specify output directory
patchr template 4ZLO A,B -o my_templates/
```

### Chain Selection

```bash
# Specific chains
patchr template 1CK4 A,B

# All polymer chains (one per entity, no duplicate copies)
patchr template 1CK4 all

# All polymer chains including duplicate copies
patchr template 1CK4 all-copies

# Use biological assembly
patchr template 1CK4 all --assembly best

# List available assemblies without processing
patchr template 1CK4 all --list-assemblies
```

### Custom Sequences

```bash
# Single chain with custom sequence
patchr template 7EOQ A --sequence ACDEFGHIKLMNPQRSTVWY

# Multiple chains with custom sequences
patchr template 1CK4 A,B --sequence A:ACDEFG,B:MNOPQR

# Interactive mode (prompts for each chain)
patchr template 7EOQ A --interactive
```

### Advanced Options

```bash
# Include solvent atoms in template CIF
patchr template 7EOQ A --include-solvent

# Exclude ligands from template
patchr template 4LRF A --exclude-ligands

# Only inpaint internal gaps, skip terminal extensions
patchr template 7EOQ A --skip-terminal

# Verbose output with detailed region analysis
patchr template 7EOQ A -v
```

### Output Files

Template generation produces:

| File | Description |
|---|---|
| `{pdb}_{chains}.yaml` | Input YAML for `patchr predict` |
| `{PDB}_chain{chains}.cif` | Template CIF with known coordinates |
| `{pdb}_{chains}_inpainting_metadata.json` | Missing region metadata |

---

## Step 2: Prediction

`patchr predict` runs the diffusion model on the prepared YAML input.

### Basic Usage

```bash
# Default: Boltz-2 with inpainting enabled
patchr predict input.yaml --out_dir results

# With a specific random seed
patchr predict input.yaml --out_dir results --seed 42

# Multiple diffusion samples
patchr predict input.yaml --out_dir results --diffusion_samples 5
```

### Backend Selection

```bash
# Boltz-2 (default)
patchr predict input.yaml --out_dir results --backend boltz2

# Protenix (AlphaFold 3-based)
patchr predict input.yaml --out_dir results --backend protenix --seed 42

# Protenix with multiple seeds
patchr predict input.yaml --out_dir results --backend protenix --seeds 42,101,202
```

### Inpainting Options

```bash
# Inpainting is enabled by default. To disable:
patchr predict input.yaml --out_dir results --no-inpainting

# Disable boundary refinement (Local Refinement Denoising)
patchr predict input.yaml --out_dir results --disable_boundary_refinement
```

### MSA Options

```bash
# Use ColabFold MSA server (auto-generates MSA for protein chains)
patchr predict input.yaml --out_dir results --use_msa_server

# Custom MSA server URL
patchr predict input.yaml --out_dir results --use_msa_server \
  --msa_server_url https://my-server.example.com

# Limit MSA depth
patchr predict input.yaml --out_dir results --max_msa_seqs 4096
```

MSA server credentials can be passed via environment variables:

| Variable | Description |
|---|---|
| `BOLTZ_MSA_USERNAME` | Basic auth username |
| `BOLTZ_MSA_PASSWORD` | Basic auth password |
| `MSA_API_KEY_VALUE` | API key (X-API-Key header) |

### Performance Tuning

```bash
# Adjust sampling steps (more = slower but potentially better)
patchr predict input.yaml --out_dir results --sampling_steps 200

# Step scale controls diversity (lower = more diverse, recommended 1.0-2.0)
patchr predict input.yaml --out_dir results --step_scale 1.5

# Run on CPU (very slow, for testing only)
patchr predict input.yaml --out_dir results --accelerator cpu

# Multi-GPU (DDP)
patchr predict input.yaml --out_dir results --devices 4

# Disable CUDA kernels (for debugging or compatibility)
patchr predict input.yaml --out_dir results --no_kernels

# Number of dataloader workers
patchr predict input.yaml --out_dir results --num_workers 4
```

### Additional Outputs

```bash
# Write full PAE/PDE matrices
patchr predict input.yaml --out_dir results --write_full_pae --write_full_pde

# Write intermediate embeddings
patchr predict input.yaml --out_dir results --write_embeddings

# PDB output instead of mmCIF
patchr predict input.yaml --out_dir results --output_format pdb
```

---

## Input Format (YAML)

PATCHR uses YAML input files to define sequences, templates, and constraints.

### Minimal Example (Protein Inpainting)

```yaml
version: 1

sequences:
  - protein:
      id: A
      sequence: MVTPEGNVSLQHKFNR...
      msa: empty

templates:
  - cif: path/to/template.cif
    chain_id: ['A']
```

### Multi-Chain Protein

```yaml
version: 1

sequences:
  - protein:
      id: A
      sequence: MVTPEGNVSLQHKFNR...
      msa: empty

  - protein:
      id: B
      sequence: GPGSMSKDVTPWD...
      msa: empty

templates:
  - cif: path/to/template.cif
    chain_id: ['A', 'B']
```

### DNA/RNA

```yaml
version: 1

sequences:
  - dna:
      id: A
      sequence: CGCGAATTCGCG

  - dna:
      id: B
      sequence: CGCGAATTCGCG

templates:
  - cif: path/to/template.cif
    chain_id: ['A', 'B']
```

### Protein with Ligands

```yaml
version: 1

sequences:
  - protein:
      id: A
      sequence: NKYKRIFLVVMDSVGIG...
      msa: empty
      modifications:
        - position: 84
          ccd: 'TPO'

  - ligand:
      id: B
      ccd: 'MN'

  - ligand:
      id: C
      ccd: 'GOL'

templates:
  - cif: path/to/template.cif
    chain_id: ['A', 'B', 'C']
```

### Ligand by SMILES

```yaml
version: 1

sequences:
  - protein:
      id: A
      sequence: MVTPEGNVSLQHKFNR...

  - ligand:
      id: B
      smiles: 'N[C@@H](Cc1ccc(O)cc1)C(=O)O'
```

### Constraints

```yaml
version: 1

sequences:
  - protein:
      id: A
      sequence: MVTPEGNVSLQHKFNR...

  - ligand:
      id: B
      ccd: 'SAH'

constraints:
  - bond:
      atom1: [A, 10, CA]
      atom2: [B, 1, C1]
  - pocket:
      binder: B
      contacts: [[A, 5], [A, 10]]
      max_distance: 6.0
  - contact:
      token1: [A, 5]
      token2: [A, 20]
      max_distance: 8.0
```

### Template Options

```yaml
templates:
  - cif: path/to/template.cif
    chain_id: ['A', 'B']
    template_id: ['A_template', 'B_template']  # Optional
    force: true                                  # Optional: force template usage
    threshold: 2.0                               # Optional: alignment threshold (A)
```

### MSA

The `msa` field for protein chains accepts:
- `empty` — single-sequence mode (no MSA, typical for inpainting)
- Path to an `.a3m` or `.csv` MSA file
- Omitted — requires `--use_msa_server` flag to auto-generate

---

## Output Format

Both backends produce the same directory structure:

```
{out_dir}/patchr_results_{input_name}/
├── predictions/
│   └── {input_name}/
│       ├── {input_name}_model_0.cif                  # Predicted structure (mmCIF)
│       ├── confidence_{input_name}_model_0.json      # Confidence metrics
│       ├── pae_{input_name}_model_0.npz              # Predicted Aligned Error
│       ├── pde_{input_name}_model_0.npz              # Predicted Distance Error
│       ├── plddt_{input_name}_model_0.npz            # Per-residue pLDDT
│       ├── inpainting_metadata_{input_name}.json     # Inpainting region info (Boltz)
│       └── {input_name}_model_1.cif                  # Additional samples (if --diffusion_samples > 1)
└── processed/                                         # Preprocessed data (Boltz only)
    ├── manifest.json
    ├── structures/
    ├── msa/
    ├── templates/
    ├── constraints/
    └── mols/
```

### Confidence JSON

`confidence_{name}_model_0.json` contains confidence metrics. The exact fields vary by backend:

**Boltz-2:**

```json
{
    "complex_plddt": 85.42,
    "complex_pde": 0.83,
    "ptm": 0.78,
    "iptm": 0.65,
    "chains_ptm": [0.80, 0.75],
    "pair_chains_iptm": [[0.0, 0.65], [0.65, 0.0]],
    "confidence_score": 0.72,
    "protein_iptm": 0.65,
    "ligand_iptm": 0.0
}
```

**Protenix:**

```json
{
    "plddt": 85.42,
    "gpde": 0.83,
    "ptm": 0.78,
    "iptm": 0.65,
    "chain_plddt": [0.87, 0.82],
    "chain_ptm": [0.80, 0.75],
    "chain_pair_iptm": [[0.0, 0.65], [0.65, 0.0]],
    "has_clash": false,
    "disorder": 0.02,
    "ranking_score": 0.72,
    "num_recycles": 3
}
```

**Common fields (both backends):**

| Field | Description |
|---|---|
| `ptm` | Predicted TM-score (0-1). |
| `iptm` | Interface predicted TM-score (0-1). Relevant for complexes. |

**Boltz-2 specific:**

| Field | Description |
|---|---|
| `complex_plddt` | Global pLDDT (0-100). Higher = more confident. |
| `complex_pde` | Global predicted distance error. Lower = better. |
| `chains_ptm` | Per-chain TM scores. |
| `pair_chains_iptm` | Pairwise inter-chain scores. |
| `confidence_score` | Aggregate ranking score. Higher = better. |

**Protenix specific:**

| Field | Description |
|---|---|
| `plddt` | Global pLDDT (0-100). Higher = more confident. |
| `gpde` | Global predicted distance error. Lower = better. |
| `chain_plddt` | Per-chain pLDDT scores. |
| `chain_ptm` | Per-chain TM scores. |
| `chain_pair_iptm` | Pairwise inter-chain scores. |
| `has_clash` | Whether steric clashes were detected. |
| `ranking_score` | Aggregate ranking score. Higher = better. |

### PAE / PDE Matrices

```python
import numpy as np

pae = np.load("pae_{name}_model_0.npz")["pae"]  # Shape: (N_tokens, N_tokens)
pde = np.load("pde_{name}_model_0.npz")["pde"]  # Shape: (N_tokens, N_tokens)
```

---

## Backends

PATCHR supports two prediction backends:

### Boltz-2 (default)

- Based on the [Boltz-2](https://doi.org/10.1101/2025.06.14.659707) architecture
- Checkpoint: `~/.boltz/boltz2_conf.ckpt` (auto-downloaded)
- Supports: proteins, DNA, RNA, ligands, modifications, constraints
- Inpainting with boundary refinement (LRD)
- MSA generation via ColabFold

```bash
patchr predict input.yaml --out_dir results --backend boltz2
```

### Protenix

- Based on the AlphaFold 3 architecture
- Checkpoint: `~/checkpoint/protenix_base_default_v1.0.0.pt` (auto-downloaded)
- Supports: proteins, DNA, RNA, ligands, modifications
- Inpainting with boundary refinement
- Multiple seeds for ensemble predictions

```bash
patchr predict input.yaml --out_dir results --backend protenix --seeds 42,101
```

> **Note:** Protenix inpainting requires `protenix_base_default_v1.0.0`. Mini/tiny models use reduced diffusion parameters that cannot produce connected boundaries.

### Comparison

| Feature | Boltz-2 | Protenix |
|---|---|---|
| Checkpoint size | ~1.5 GB | ~1.4 GB |
| Inference speed (200aa) | ~10s | ~20s |
| Multi-seed | `--seed` (single) | `--seeds` (multiple) |
| MSA server | Supported | Not used |
| Constraints | Supported | Not supported |
| Affinity prediction | Supported | Not supported |

---

## Simulation-Ready Output

PATCHR can go directly from structure completion to MD simulation input. Add `--sim-ready` to `patchr predict` to run post-processing automatically.

Adds hydrogens at target pH, solvates in a water box, and neutralizes with counter ions. For GROMACS, generates CHARMM-GUI-style output with `toppar/` directory, MDP files, and a run script.

```bash
# Predict + GROMACS files
patchr predict input.yaml --out_dir results --sim-ready gromacs

# Predict + AMBER files with AMBER force field
patchr predict input.yaml --out_dir results --sim-ready amber --ff amber14sb

# Predict + OpenMM files
patchr predict input.yaml --out_dir results --sim-ready openmm
```

Output is written to `patchr_results_{name}/sim_ready/`:

**GROMACS output:**

| File | Description |
|---|---|
| `topol.top` | Main topology with `#include` directives |
| `toppar/forcefield.itp` | Force field parameters ([defaults], [atomtypes], [cmaptypes]) |
| `toppar/PROA.itp` | Protein topology with position restraints |
| `toppar/HOH.itp` | Water topology (with SETTLE) |
| `toppar/NA.itp`, `toppar/CL.itp` | Ion topologies |
| `step5_input.gro` | Coordinates (.gro) |
| `step5_input.pdb` | Coordinates (.pdb) |
| `index.ndx` | Index file (SOLU, SOLV, SYSTEM groups) |
| `step6.0_minimization.mdp` | Energy minimization |
| `step6.{1-6}_equilibration.mdp` | 6-step equilibration with progressive restraint release |
| `step7_production.mdp` | Production MD |
| `README` | GROMACS run script |
| `system.xml` | OpenMM serialized system (backup) |
| `sim_ready_summary.json` | System stats (atom counts, box size, etc.) |

**Other engines:**

| File | Engine | Description |
|---|---|---|
| `topology.pdb` | OpenMM | Topology reference PDB |
| `state.xml` | OpenMM | Serialized state (positions) |
| `system_for_amber.pdb` | AMBER | PDB for tleap |

### Standalone Command

You can also run sim-ready on any existing CIF file:

```bash
patchr sim-ready prediction.cif --engine gromacs --ff charmm36m
patchr sim-ready prediction.cif --engine openmm --padding 1.2 --ion-conc 0.15
```

### Force Fields

| Name | Description | Recommended for |
|---|---|---|
| `charmm36m` | CHARMM36m (default) | General purpose |
| `charmm36` | CHARMM36 | General purpose |
| `amber14sb` | AMBER ff14SB | AMBER users |
| `amber99sbildn` | AMBER ff99SB-ILDN | Legacy AMBER |
| `amber19sb` | AMBER ff19SB | Latest AMBER |

---

## CLI Reference

### `patchr predict`

```
Usage: patchr predict [OPTIONS] DATA

Options:
  --out_dir PATH                  Output directory (default: ./)
  --backend [boltz2|protenix]     Prediction backend (default: boltz2)
  --cache PATH                    Model cache directory (default: ~/.boltz)
  --checkpoint PATH               Custom model checkpoint
  --devices INTEGER               Number of GPU devices (default: 1)
  --accelerator [gpu|cpu|tpu]     Accelerator type (default: gpu)
  --recycling_steps INTEGER       Recycling iterations (default: 3)
  --sampling_steps INTEGER        Diffusion sampling steps (default: 200)
  --diffusion_samples INTEGER     Number of output samples (default: 1)
  --max_parallel_samples INTEGER  Max parallel samples (default: 5)
  --step_scale FLOAT              Diffusion temperature (default: 1.5)
  --write_full_pae                Write full PAE matrix to .npz
  --write_full_pde                Write full PDE matrix to .npz
  --output_format [pdb|mmcif]     Output structure format (default: mmcif)
  --num_workers INTEGER           Dataloader workers (default: 2)
  --override                      Override existing predictions
  --seed INTEGER                  Random seed (single)
  --seeds TEXT                    Comma-separated seeds (Protenix)
  --use_msa_server                Auto-generate MSA via ColabFold
  --msa_server_url TEXT           MSA server URL
  --msa_pairing_strategy TEXT     MSA pairing: greedy or complete
  --use_potentials                Enable steering potentials (Boltz)
  --inpainting / --no-inpainting  Toggle inpainting mode (default: on)
  --disable_boundary_refinement   Disable LRD boundary refinement
  --preprocessing-threads INT     Preprocessing threads
  --max_msa_seqs INTEGER          Max MSA sequences (default: 8192)
  --subsample_msa                 Subsample MSA
  --num_subsampled_msa INTEGER    Subsampled MSA count (default: 1024)
  --no_kernels                    Disable custom CUDA kernels
  --write_embeddings              Write s/z embeddings
  --method TEXT                   Method conditioning (Boltz-2)
  --sim-ready [gromacs|amber|openmm]
                                  Post-processing: prepare simulation files
  --ff [charmm36m|charmm36|amber14sb|amber99sbildn|amber19sb]
                                  Force field for sim-ready
```

### `patchr sim-ready`

```
Usage: patchr sim-ready [OPTIONS] INPUT_CIF

Options:
  -o, --out-dir PATH              Output directory
  --engine [gromacs|amber|openmm] MD engine (default: gromacs)
  --ff [charmm36m|...]            Force field (default: charmm36m)
  --water [tip3p|tip3pfb|tip4pew|spce]  Water model (default: tip3p)
  --ph FLOAT                      Protonation pH (default: 7.0)
  --padding FLOAT                 Box padding in nm (default: 1.0)
  --ion-conc FLOAT                Ion concentration in mol/L (default: 0.15)
  --keep-water                    Keep crystallographic waters
```

### `patchr template`

```
Usage: patchr template [OPTIONS] [PDB_ID] [CHAIN_IDS]

Options:
  -i, --input PATH               Local CIF/PDB file
  --uniprot                      Use UniProt sequence
  -s, --sequence TEXT            Custom sequence(s)
  -o, --out_dir PATH             Output directory (default: examples/inpainting)
  --include-solvent              Include solvent atoms
  --exclude-ligands              Exclude non-polymer ligands
  --assembly TEXT                Biological assembly ID or 'best'
  --list-assemblies              List assemblies and exit
  --skip-terminal                Skip terminal missing residues
  -v, --verbose                  Verbose output
  --interactive                  Prompt for sequence input
  --format [yaml|protenix-json]  Output format (default: yaml)
```

### `patchr serve`

```
Usage: patchr serve [OPTIONS]

Options:
  --host TEXT                     Bind host (default: 0.0.0.0)
  --port INTEGER                  Bind port (default: 31212)
  --device-id TEXT                GPU device ID (e.g. '0')
  --model [boltz2|protenix|all]
                                  Model(s) to preload (default: boltz2)
  --work-dir PATH                 Job working directory (default: ./patchr_jobs)
  --reload                        Enable auto-reload (dev mode)
```

---

## Server Mode

PATCHR includes a REST API server for integration with PATCHR-Studio and custom clients.

### Starting the Server

```bash
# Default: Boltz-2 with inpainting
patchr serve

# Specific model and GPU
patchr serve --model boltz2 --device-id 0

# Protenix backend
patchr serve --model protenix --port 8080

# Both backends (uses more VRAM)
patchr serve --model all
```

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Health check |
| `POST` | `/api/v1/template/generate` | Generate template from PDB ID |
| `POST` | `/api/v1/template/upload` | Upload CIF and generate template |
| `POST` | `/api/v1/predict/run` | Run prediction on a template job |
| `GET` | `/api/v1/jobs/{job_id}` | Get job status |
| `GET` | `/api/v1/jobs/{job_id}/progress` | Stream progress (SSE) |
| `GET` | `/api/v1/jobs/{job_id}/files/{type}` | Download results (cif/yaml/prediction) |
| `GET` | `/api/v1/jobs` | List all jobs |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete a job |
| `POST` | `/api/v1/sim-ready` | Prepare simulation-ready files from prediction |
| `GET` | `/api/v1/jobs/{job_id}/sim-result` | Get sim-ready result details |

### Example API Usage

```bash
# Health check
curl http://localhost:31212/api/v1/health

# Generate template
curl -X POST http://localhost:31212/api/v1/template/generate \
  -H "Content-Type: application/json" \
  -d '{"pdb_id": "4ZLO", "chain_ids": "A,B"}'

# Run prediction (using job_id from template generation)
curl -X POST http://localhost:31212/api/v1/predict/run \
  -H "Content-Type: application/json" \
  -d '{"job_id": "...", "model": "boltz2"}'

# Download results
curl -O http://localhost:31212/api/v1/jobs/{job_id}/files/prediction
```

### Google Colab

Run the server on Colab's free GPU and connect from PATCHR-Studio:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/DeepFoldProtein/patchr/blob/main/colab_server.ipynb)

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BOLTZ_CACHE` | Boltz model/data cache directory | `~/.boltz` |
| `PATCHR_DEVICE_ID` | GPU device ID for server | Auto-detect |
| `PATCHR_DEFAULT_MODEL` | Default model for server startup | `boltz2` |
| `PATCHR_WORK_DIR` | Server job working directory | `./patchr_jobs` |
| `BOLTZ_MSA_USERNAME` | MSA server basic auth username | — |
| `BOLTZ_MSA_PASSWORD` | MSA server basic auth password | — |
| `MSA_API_KEY_VALUE` | MSA server API key | — |
| `CUDA_VISIBLE_DEVICES` | GPU visibility | All GPUs |

---

## Troubleshooting

### Common Issues

**"No matching distribution found for trifast/cuequivariance"**
- Requires Python >= 3.11. Check with `python --version`.

**"Missing MSA's in input and --use_msa_server flag not set"**
- Your YAML has protein chains without MSA. Either:
  - Set `msa: empty` for each protein chain (single-sequence mode), or
  - Add `--use_msa_server` flag.

**"CUDA out of memory"**
- Reduce `--diffusion_samples` or `--max_parallel_samples`.
- For large structures (>500 residues), a GPU with 24+ GB VRAM is recommended.

**Broken bonds at inpainting boundaries**
- This is expected occasionally. Try:
  - Different `--seed` values.
  - Keeping boundary refinement enabled (default).
  - Using the Protenix backend with multiple seeds (`--seeds 42,101,202`) and picking the best sample.

**Slow inference on Mac**
- MPS backend is supported but ~10x slower than CUDA. Consider using Google Colab.

### Model Checkpoints

| Backend | Checkpoint | Location |
|---|---|---|
| Boltz-2 | `boltz2_conf.ckpt` | `~/.boltz/` (auto-downloaded) |
| Protenix | `protenix_base_default_v1.0.0.pt` | `~/checkpoint/` (auto-downloaded) |

To use a custom checkpoint:

```bash
# Boltz
patchr predict input.yaml --checkpoint /path/to/model.ckpt --out_dir results

# Protenix (set via environment)
export PROTENIX_ROOT_DIR=/path/to/checkpoints
patchr predict input.yaml --backend protenix --out_dir results
```
