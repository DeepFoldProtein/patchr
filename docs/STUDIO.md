# PATCHR-Studio: Capabilities and Parameters

Reference documentation for PATCHR-Studio, the desktop application for
template-conditioned structure inpainting, and for the equivalent CLI and REST
interfaces. This document enumerates what each interface can do and the
parameters it exposes.

- [1. Overview](#1-overview)
- [2. Projects and outputs](#2-projects-and-outputs)
- [3. Structure input](#3-structure-input)
- [4. Automatic gap detection](#4-automatic-gap-detection)
- [5. Interactive sequence editing](#5-interactive-sequence-editing)
- [6. Reconstruction](#6-reconstruction)
- [7. Inspection of results](#7-inspection-of-results)
- [8. Simulation-ready export](#8-simulation-ready-export)
- [9. Command-line interface](#9-command-line-interface)
- [10. REST API](#10-rest-api)
- [11. Application maintenance](#11-application-maintenance)

---

## 1. Overview

PATCHR is exposed through three interfaces that share one generation backend:

| Interface | Purpose |
|---|---|
| **PATCHR-Studio** | Desktop application (Electron); interactive, per-structure work |
| **CLI** | Programmatic and large-scale template generation |
| **REST API** | Inference server (`patchr serve`); consumed by Studio and third-party tools |

Studio guides the user through four stages:

1. **Load** a structure into a project.
2. **Detect** missing regions automatically, at residue and atom level.
3. **Edit** the sequence interactively (erase, mutate, add PTMs) — optional.
4. **Reconstruct**, inspect, and export simulation-ready inputs.

Studio does not perform inference locally: it submits jobs to a PATCHR inference
server (default `https://patchr-inference.deepfold.org`, configurable per
project; a local or Colab server may be used instead).

---

## 2. Projects and outputs

A project is a directory holding inputs and every generated artifact. Outputs
are versioned so runs can be compared rather than overwritten.

```
<project>/
├── structures/
│   ├── original/      # structure as loaded
│   └── canonical/     # canonicalized structure
├── results/
│   ├── run_001/       # one inpainting run
│   │   └── predictions/…/*_model_0.cif
│   └── run_002/ …
└── simulations/
    ├── sim_001/       # one simulation-ready export
    └── sim_002/ …
```

Runs (`run_NNN`) and simulation exports (`sim_NNN`) are auto-numbered. Each run
retains its predicted structure, the inpainting metadata, the template CIF and
YAML, and confidence files.

---

## 3. Structure input

| Capability | Detail |
|---|---|
| Formats | mmCIF (`.cif`, `.mmcif`) and PDB (`.pdb`) |
| PDB conversion | PDB input is converted to mmCIF (gemmi; `setup_entities`, `assign_label_seq_id`) so SEQRES/entity records are available downstream |
| Assemblies | Biological assembly selection (CLI `--assembly`, default `1`, or `best`) |
| Solvent | Water hidden in the viewer by default; inclusion controlled at generation time |
| Chains | Proteins, DNA, RNA, ligands, and multi-chain complexes |

Reconstruction requires the polymer sequence records (`_entity_poly` /
`_pdbx_poly_seq_scheme`): missing regions are defined as the difference between
the deposited sequence and the observed coordinates.

---

## 4. Automatic gap detection

On load, Studio compares the full polymer sequence against observed atoms and
classifies every discrepancy. Detection is automatic; no manual gap marking is
required.

| Region type | Meaning |
|---|---|
| `complete` | Entire residue absent from coordinates |
| `partial` | Residue present but missing atoms (e.g. unresolved side chain) |

| Position | Meaning |
|---|---|
| `internal` | Gap flanked by resolved residues; always reconstructed |
| `nterm` / `cterm` | Missing terminal residues; reconstructed only if terminal inclusion is enabled |

Detected regions are listed, highlighted in the 3D view and the sequence panel,
and annotated with chain, author residue range, and length. Per-residue missing
atoms are reported individually (e.g. `ARG79 missing 6 atoms: CG, CD, NE, CZ,
NH1, NH2`).

---

## 5. Interactive sequence editing

The sequence editor stages residue-level edits on top of the detected gaps. All
edits are **staged** — listed, individually reversible, and applied only when a
run is started. Editing is restricted to **protein chains**; DNA, RNA, and
ligand chains are view-only, as reconstruction of those edits is not supported.

| Edit | Effect | Mechanism |
|---|---|---|
| **Erase and regenerate** | Removes resolved residues so they are rebuilt from scratch | Selected residues are stripped from `_atom_site`; the backend then re-detects them as missing and inpaints them |
| **Mutation** | Substitutes a residue identity; the new side chain is built by inpainting | Applied through the custom-sequence path (`custom_sequences`) |
| **Post-translational modification** | Installs a modified residue | Forwarded to the backend as `modifications` (`CHAIN:SEQID:CCD`) and modelled by Boltz |

Erase, mutation, and PTM are mutually exclusive per residue. Erasing is limited
to resolved residues; residues already missing (i.e. inpainting targets) may be
mutated or PTM-modified but not erased.

### Available modifications

| Parent residue | Modification | CCD |
|---|---|---|
| Ser | Phosphoserine | `SEP` |
| Thr | Phosphothreonine | `TPO` |
| Tyr | Phosphotyrosine | `PTR` |
| Lys | N6-methyllysine | `MLY` |
| Lys | N6,N6,N6-trimethyllysine | `M3L` |

PTM positions are specified by the **1-based entity (canonical) sequence
position** — the `seq_id` a structure viewer shows, and the numbering Boltz
uses — together with the **author chain identifier**.

### Additional editing controls

| Control | Effect |
|---|---|
| **UniProt reference** | Fetches a reference sequence (auto-prefilled from the structure's `_struct_ref`) and aligns the displayed sequence to it, exposing residues absent from the deposited construct |
| **Include N/C-terminal residues** | Includes terminal missing residues as reconstruction targets; when off they are skipped (`skip_terminal`) |
| **Reset** | Clears all staged edits |

---

## 6. Reconstruction

### Token budget

Before submission Studio estimates the model token count, matching backend
tokenization:

- protein: **1 token per residue**
- DNA, RNA, ligands: **1 token per atom**
- water: excluded

If the structure exceeds the default server's capacity (~1400 tokens on an
RTX 3090), the run is blocked with guidance to use a larger self-hosted server.

### Queue

Jobs are dispatched to a GPU queue. While waiting, Studio shows the live
system-wide queue position (jobs ahead, jobs running), aggregated across server
replicas.

### Generation parameters

Studio submits template generation with the following, derived from the UI:

| Parameter | Source in Studio |
|---|---|
| `chain_ids` | Chains of the loaded structure |
| `custom_sequences` | Staged mutations / UniProt reference (`A:SEQ,B:SEQ`) |
| `skip_terminal` | "Include N/C-terminal residues" toggle (inverted) |
| `modifications` | Staged PTMs (`CHAIN:SEQID:CCD`, comma-separated) |

Prediction parameters are **fixed in Studio** and exposed only through the CLI
and REST API:

| Parameter | Studio value | Meaning |
|---|---|---|
| `model` | `boltz2` | Backend (`boltz2` or `protenix`) |
| `recycling_steps` | `3` | Recycling iterations |
| `sampling_steps` | `200` | Diffusion sampling steps |
| `diffusion_samples` | `1` | Number of samples generated |
| `devices` | `1` | Device count (Boltz) |
| `accelerator` | `gpu` | Accelerator type (Boltz) |
| `use_msa_server` | `false` | MSA generation via remote server (Boltz) |

---

## 7. Inspection of results

Each completed run is loaded into the 3D viewer, superposed onto the input
structure, and annotated. Results are versioned; multiple runs may be toggled
and compared.

### Colour scheme

| Colour | Meaning |
|---|---|
| Red (`#ef4444`) | Fully inpainted residues |
| Orange (`#f97316`) | Partially fixed residues (rebuilt atoms) |
| Yellow (`#eab308`) | Boundary (flexible region) |
| Purple (`#a855f7`) | Post-translational modification |
| Teal (`#14b8a6`) | Mutation |

Edit colours (PTM, mutation) take precedence over reconstruction colours where
they coincide.

### Reported metrics

| Metric | Description |
|---|---|
| pLDDT | Mean predicted confidence over the run |
| MolProbability | Geometry quality score |
| Combined score | Aggregate ranking score used to sort runs |

---

## 8. Simulation-ready export

Converts a predicted structure into inputs for common MD engines: protonation,
solvation, ionization, and topology generation. GROMACS output follows
CHARMM-GUI directory conventions (`toppar/` with `forcefield.itp` and
per-molecule `.itp` files), and includes a staged equilibration protocol with
progressive release of position restraints.

### Parameters

| Parameter | Default | Range / options | Description |
|---|---|---|---|
| `engine` | `gromacs` | `gromacs`, `amber`, `openmm` | Target MD engine |
| `forcefield` | `charmm36m` | `charmm36m`, `charmm36`, `amber14sb`, `amber99sbildn`, `amber19sb` | Force field |
| `water_model` | `tip3p` | `tip3p`, `tip3pfb`, `spce`, `tip4pew`, `tip5p` | Water model |
| `ph` | `7.0` | float | pH used for protonation state assignment |
| `padding` | `1.0` | nm | Solvation box padding |
| `ion_concentration` | `0.15` | mol/L | Salt concentration |
| `positive_ion` | `Na+` | — | Cation species |
| `negative_ion` | `Cl-` | — | Anion species |
| `keep_water` | `false` | bool | Retain crystallographic waters |

### Reported system properties

`n_atoms`, `n_residues`, `n_waters`, `n_ions`, `total_charge`, and the paths of
all generated files.

---

## 9. Command-line interface

Template generation. The CLI accepts a PDB identifier (downloaded on demand) or
a local structure file.

```bash
patchr <PDB_ID> <CHAIN_IDS> [options]
patchr --input structure.cif A,B [options]
```

| Option | Default | Description |
|---|---|---|
| `PDB_ID` | — | PDB identifier (positional) |
| `CHAIN_IDS` | — | Chain identifiers, e.g. `A` or `A,B` (positional) |
| `-i`, `-f`, `--input` | — | Local CIF/PDB path (alternative to `PDB_ID`) |
| `--uniprot` | off | Use the UniProt sequence instead of SEQRES |
| `--interactive` | off | Prompt for a manual sequence per chain |
| `-s`, `--sequence` | — | Custom sequence(s): `ACDEFG` or `A:ACDEFG,B:MNOPQR` |
| `-m`, `--modification` | — | PTM as `CHAIN:SEQID:CCD` (e.g. `A:12:SEP`); entity/canonical `SEQID`, author chain; protein chains only; repeatable |
| `--skip-terminal` | off | Reconstruct internal gaps only |
| `--assembly` | `1` | Biological assembly ID, or `best` for auto-selection |
| `--list-assemblies` | — | List available assemblies and exit |
| `-o`, `--output` | `examples/inpainting` | Output directory |
| `--cache` | — | Boltz cache directory (`ccd.pkl`) |
| `--format` | `yaml` | Output format: `yaml` or `protenix-json` |

Additional flags control inclusion of solvent, exclusion of non-polymer
(ligand) chains, and verbose reporting of the inpainting-region analysis.

Serving:

```bash
patchr serve --model boltz2 --device-id 0
patchr serve --model protenix --port 8080
patchr serve --model all
```

---

## 10. REST API

Base path `/api/v1`.

| Endpoint | Method | Purpose |
|---|---|---|
| `/template/generate` | POST | Generate a template from a PDB ID |
| `/template/upload` | POST | Upload a structure and generate a template |
| `/predict/run` | POST | Run prediction on a generated template |
| `/jobs/{job_id}` | GET | Job status (includes live queue position) |
| `/jobs/{job_id}/progress` | GET | Server-sent progress stream |
| `/jobs/{job_id}/files/{type}` | GET | Download `cif`, `yaml`, `prediction`, `sim_ready` |
| `/jobs` | GET | List jobs |
| `/queue/status` | GET | System-wide GPU queue; `?job_id=` for a job's position |
| `/sim-ready` | POST | Simulation-ready preparation |
| `/health` | GET | Health and loaded models |
| `/convert/pdb-to-cif` | POST | Convert PDB to mmCIF |

**`/template/upload`** (multipart): `cif_file`, `chain_ids`,
`custom_sequences` (`A:SEQ1,B:SEQ2`), `skip_terminal`, `modifications`
(`CHAIN:SEQID:CCD`; repeatable or comma-separated).

**`/template/generate`** (JSON): `pdb_id`, `chain_ids`, `uniprot`,
`custom_sequences`, `skip_terminal`, `modifications`.

**`/predict/run`** (JSON): `job_id`, `model`, `recycling_steps`,
`sampling_steps`, `diffusion_samples`, `devices`, `accelerator`,
`use_msa_server` — see the table in [§6](#6-reconstruction) for defaults.

**`/sim-ready`** (JSON): `job_id` or `cif_path` or `cif_content` +
`cif_filename`, plus the parameters in [§8](#8-simulation-ready-export).

---

## 11. Application maintenance

| Feature | Detail |
|---|---|
| Server configuration | Inference server URL is set per project; connection state is shown in the status bar |
| Updates | Explicit: the status bar reports the current version and, when a newer release exists, the user deliberately triggers download and restart. Nothing is downloaded or installed silently |
| Appearance | Light and dark themes |
