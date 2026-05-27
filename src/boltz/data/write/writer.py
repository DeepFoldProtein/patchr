import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal

import matplotlib
matplotlib.use("Agg")  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import torch
from pytorch_lightning import LightningModule, Trainer
from pytorch_lightning.callbacks import BasePredictionWriter
from torch import Tensor

from boltz.data.types import Coords, Interface, Record, Structure, StructureV2
from boltz.data.write.merge_cif_blocks import merge_template_blocks_into_cif
from boltz.data.write.mmcif import to_mmcif
from boltz.data.write.pdb import to_pdb


def _write_trajectory_pdb(
    traj_frames: Tensor,
    pad_mask: Tensor,
    structure,
    plddts,
    boltz2: bool,
    output_path: Path,
) -> None:
    """Write a denoising trajectory as a multi-model PDB.

    Each frame's coords are substituted into ``structure.atoms["coords"]`` and
    rendered with ``to_pdb``; per-frame ATOM/HETATM records are wrapped in
    ``MODEL N`` / ``ENDMDL`` blocks. The final ``END`` plus a single CONECT
    block (shared across models) is emitted once at the end.
    """
    mask_np = pad_mask.bool().cpu().numpy()
    num_frames = int(traj_frames.shape[0])

    # Snapshot existing coords so callers' subsequent writes are unaffected by
    # the in-place mutation we do per-frame below.
    original_coords = structure.atoms["coords"].copy()

    out_lines: list[str] = []
    conect_lines: list[str] = []
    for frame_idx in range(num_frames):
        frame_coords = traj_frames[frame_idx][mask_np].cpu().numpy()
        # Substitute coords (atoms array is mutable; final structure write at the
        # end of write_on_batch_end will overwrite it back to the final coords).
        structure.atoms["coords"] = frame_coords
        if boltz2:
            structure_coords_view = np.array([(x,) for x in frame_coords], dtype=Coords)
            new_struct = replace(structure, coords=structure_coords_view)
        else:
            new_struct = structure

        pdb_str = to_pdb(new_struct, plddts=plddts, boltz2=boltz2)
        atom_lines = []
        for line in pdb_str.splitlines():
            stripped = line.rstrip()
            if stripped.startswith(("ATOM", "HETATM", "TER")):
                atom_lines.append(line)
            elif stripped.startswith("CONECT") and frame_idx == 0:
                conect_lines.append(line)
            # Drop END and blank lines per-frame; we emit them once at the end.

        out_lines.append(f"MODEL{frame_idx + 1:>9}".ljust(80))
        out_lines.extend(atom_lines)
        out_lines.append("ENDMDL".ljust(80))

    out_lines.extend(conect_lines)
    out_lines.append("END".ljust(80))
    out_lines.append("")
    output_path.write_text("\n".join(out_lines))

    # Restore so the caller's atoms array is unchanged on return.
    structure.atoms["coords"] = original_coords


class BoltzWriter(BasePredictionWriter):
    """Custom writer for predictions."""

    def __init__(
        self,
        data_dir: str,
        output_dir: str,
        output_format: Literal["pdb", "mmcif"] = "mmcif",
        boltz2: bool = False,
        write_embeddings: bool = False,
    ) -> None:
        """Initialize the writer.

        Parameters
        ----------
        output_dir : str
            The directory to save the predictions.

        """
        super().__init__(write_interval="batch")
        if output_format not in ["pdb", "mmcif"]:
            msg = f"Invalid output format: {output_format}"
            raise ValueError(msg)

        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_format = output_format
        self.failed = 0
        self.boltz2 = boltz2
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.write_embeddings = write_embeddings

    def write_on_batch_end(
        self,
        trainer: Trainer,  # noqa: ARG002
        pl_module: LightningModule,  # noqa: ARG002
        prediction: dict[str, Tensor],
        batch_indices: list[int],  # noqa: ARG002
        batch: dict[str, Tensor],
        batch_idx: int,  # noqa: ARG002
        dataloader_idx: int,  # noqa: ARG002
    ) -> None:
        """Write the predictions to disk."""
        if prediction["exception"]:
            self.failed += 1
            return

        # Get the records
        records: list[Record] = batch["record"]

        # Get the predictions
        coords = prediction["coords"]
        coords = coords.unsqueeze(0)

        pad_masks = prediction["masks"]

        # Get ranking
        if "confidence_score" in prediction:
            argsort = torch.argsort(prediction["confidence_score"], descending=True)
            idx_to_rank = {idx.item(): rank for rank, idx in enumerate(argsort)}
        # Handles cases where confidence summary is False
        else:
            idx_to_rank = {i: i for i in range(len(records))}

        # Iterate over the records
        for record, coord, pad_mask in zip(records, coords, pad_masks):
            # Load the structure
            path = self.data_dir / f"{record.id}.npz"
            if self.boltz2:
                structure: StructureV2 = StructureV2.load(path)
            else:
                structure: Structure = Structure.load(path)

            # Compute chain map with masked removed, to be used later
            chain_map = {}
            for i, mask in enumerate(structure.mask):
                if mask:
                    chain_map[len(chain_map)] = i

            # Remove masked chains completely
            structure = structure.remove_invalid_chains()

            for model_idx in range(coord.shape[0]):
                # Get model coord
                model_coord = coord[model_idx]
                # Unpad
                coord_unpad = model_coord[pad_mask.bool()]
                coord_unpad = coord_unpad.cpu().numpy()

                # New atom table
                atoms = structure.atoms
                atoms["coords"] = coord_unpad
                atoms["is_present"] = True
                if self.boltz2:
                    structure: StructureV2
                    coord_unpad = [(x,) for x in coord_unpad]
                    coord_unpad = np.array(coord_unpad, dtype=Coords)

                # Mew residue table
                residues = structure.residues
                residues["is_present"] = True

                # Update the structure
                interfaces = np.array([], dtype=Interface)
                if self.boltz2:
                    new_structure: StructureV2 = replace(
                        structure,
                        atoms=atoms,
                        residues=residues,
                        interfaces=interfaces,
                        coords=coord_unpad,
                    )
                else:
                    new_structure: Structure = replace(
                        structure,
                        atoms=atoms,
                        residues=residues,
                        interfaces=interfaces,
                    )

                # Update chain info
                chain_info = []
                for chain in new_structure.chains:
                    old_chain_idx = chain_map[chain["asym_id"]]
                    old_chain_info = record.chains[old_chain_idx]
                    new_chain_info = replace(
                        old_chain_info,
                        chain_id=int(chain["asym_id"]),
                        valid=True,
                    )
                    chain_info.append(new_chain_info)

                # Save the structure
                struct_dir = self.output_dir / record.id
                struct_dir.mkdir(exist_ok=True)

                # Get plddt's
                plddts = None
                if "plddt" in prediction:
                    plddts = prediction["plddt"][model_idx]

                # Create path name
                outname = f"{record.id}_model_{idx_to_rank[model_idx]}"

                # Save the structure
                if self.output_format == "pdb":
                    path = struct_dir / f"{outname}.pdb"
                    with path.open("w") as f:
                        f.write(
                            to_pdb(new_structure, plddts=plddts, boltz2=self.boltz2)
                        )
                elif self.output_format == "mmcif":
                    path = struct_dir / f"{outname}.cif"
                    cif_str = to_mmcif(
                        new_structure, plddts=plddts, boltz2=self.boltz2
                    )
                    template_cif_path = getattr(
                        record, "template_cif_path", None
                    )
                    if template_cif_path:
                        cif_str = merge_template_blocks_into_cif(
                            cif_str,
                            template_cif_path,
                            entry_id=record.id,
                        )
                    with path.open("w") as f:
                        f.write(cif_str)
                else:
                    path = struct_dir / f"{outname}.npz"
                    np.savez_compressed(path, **asdict(new_structure))

                if self.boltz2 and record.affinity and idx_to_rank[model_idx] == 0:
                    path = struct_dir / f"pre_affinity_{record.id}.npz"
                    np.savez_compressed(path, **asdict(new_structure))
                    np.array(atoms["coords"][:, None], dtype=Coords)

                # Save confidence summary
                if "plddt" in prediction:
                    path = (
                        struct_dir
                        / f"confidence_{record.id}_model_{idx_to_rank[model_idx]}.json"
                    )
                    confidence_summary_dict = {}
                    for key in [
                        "confidence_score",
                        "ptm",
                        "iptm",
                        "ligand_iptm",
                        "protein_iptm",
                        "complex_plddt",
                        "complex_iplddt",
                        "complex_pde",
                        "complex_ipde",
                    ]:
                        confidence_summary_dict[key] = prediction[key][model_idx].item()
                    confidence_summary_dict["chains_ptm"] = {
                        idx: prediction["pair_chains_iptm"][idx][idx][model_idx].item()
                        for idx in prediction["pair_chains_iptm"]
                    }
                    confidence_summary_dict["pair_chains_iptm"] = {
                        idx1: {
                            idx2: prediction["pair_chains_iptm"][idx1][idx2][
                                model_idx
                            ].item()
                            for idx2 in prediction["pair_chains_iptm"][idx1]
                        }
                        for idx1 in prediction["pair_chains_iptm"]
                    }
                    with path.open("w") as f:
                        f.write(
                            json.dumps(
                                confidence_summary_dict,
                                indent=4,
                            )
                        )

                    # Save plddt
                    plddt = prediction["plddt"][model_idx]
                    path = (
                        struct_dir
                        / f"plddt_{record.id}_model_{idx_to_rank[model_idx]}.npz"
                    )
                    np.savez_compressed(path, plddt=plddt.cpu().numpy())

                # Save diffusion trajectory as multi-model PDB (for Mol* / PyMOL playback).
                # prediction["trajectory"] shape: (num_frames, multiplicity, n_atoms, 3),
                # CPU float32 tensor produced by DiffusionV2.sample.
                if "trajectory" in prediction:
                    traj = prediction["trajectory"]
                    if isinstance(traj, torch.Tensor):
                        traj_frames = traj[:, model_idx]  # (num_frames, n_atoms, 3)
                        traj_path = (
                            struct_dir
                            / f"trajectory_{record.id}_model_{idx_to_rank[model_idx]}.pdb"
                        )
                        _write_trajectory_pdb(
                            traj_frames=traj_frames,
                            pad_mask=pad_mask,
                            structure=new_structure,
                            plddts=plddts,
                            boltz2=self.boltz2,
                            output_path=traj_path,
                        )

                # Save detailed per-step NPZ trajectory (atom_coords, rotated template
                # coords, and x̂_0 denoised prediction at every step + sigmas/stages).
                if "trajectory_npz" in prediction:
                    npz_in = prediction["trajectory_npz"]
                    pad_mask_np = pad_mask.bool().cpu().numpy()
                    save_dict: dict = {}

                    def _unpad_frames(t: Tensor) -> np.ndarray:
                        # t: (num_frames, multiplicity, n_atoms, 3) → (num_frames, n_real, 3)
                        return t[:, model_idx][:, pad_mask_np].cpu().numpy()

                    def _unpad_single(t: Tensor) -> np.ndarray:
                        # t: (multiplicity, n_atoms, 3) → (n_real, 3)
                        return t[model_idx][pad_mask_np].cpu().numpy()

                    for key in ("atom_coords", "template_coords", "denoised_coords"):
                        if key in npz_in and isinstance(npz_in[key], torch.Tensor):
                            save_dict[key] = _unpad_frames(npz_in[key])
                    for key in ("initial_coords", "initial_template_coords"):
                        if key in npz_in and isinstance(npz_in[key], torch.Tensor):
                            save_dict[key] = _unpad_single(npz_in[key])
                    if "sigmas" in npz_in:
                        save_dict["sigmas"] = npz_in["sigmas"].cpu().numpy()
                    if "stages" in npz_in:
                        save_dict["stages"] = npz_in["stages"].cpu().numpy()
                    if "template_mask" in npz_in and isinstance(
                        npz_in["template_mask"], torch.Tensor
                    ):
                        tmpl_mask = npz_in["template_mask"]
                        if tmpl_mask.dim() == 2:
                            tmpl_mask = tmpl_mask[model_idx]
                        save_dict["template_mask"] = (
                            tmpl_mask[pad_mask_np].cpu().numpy()
                        )
                    if "boundary_mask" in npz_in and isinstance(
                        npz_in["boundary_mask"], torch.Tensor
                    ):
                        bnd_mask = npz_in["boundary_mask"]
                        if bnd_mask.dim() == 2:
                            bnd_mask = bnd_mask[model_idx]
                        save_dict["boundary_mask"] = (
                            bnd_mask[pad_mask_np].cpu().numpy()
                        )

                    npz_path = (
                        struct_dir
                        / f"detailed_trajectory_{record.id}_model_{idx_to_rank[model_idx]}.npz"
                    )
                    np.savez_compressed(npz_path, **save_dict)

                # Save pae
                if "pae" in prediction:
                    pae = prediction["pae"][model_idx]
                    path = (
                        struct_dir
                        / f"pae_{record.id}_model_{idx_to_rank[model_idx]}.npz"
                    )
                    np.savez_compressed(path, pae=pae.cpu().numpy())

                # Save pde
                if "pde" in prediction:
                    pde = prediction["pde"][model_idx]
                    path = (
                        struct_dir
                        / f"pde_{record.id}_model_{idx_to_rank[model_idx]}.npz"
                    )
                    np.savez_compressed(path, pde=pde.cpu().numpy())

                # Save template_output visualization (only once per record, not per model)
                if "template_output" in prediction and model_idx == 0:
                    template_output = prediction["template_output"]
                    # template_output shape: (B, L, L, token_z) or (L, L, token_z)
                    if isinstance(template_output, torch.Tensor):
                        template_output = template_output.cpu()
                    
                    if len(template_output.shape) == 4:
                        # Take first batch and compute L2 norm across feature dimension
                        template_output = template_output[0]  # (L, L, token_z)
                    elif len(template_output.shape) == 3:
                        # Already (L, L, token_z)
                        pass
                    else:
                        # Unexpected shape, skip
                        template_output = None
                    
                    if template_output is not None:
                        # Convert to numpy if still tensor
                        if isinstance(template_output, torch.Tensor):
                            # Convert to float32 first to handle bfloat16 and other types
                            template_output = template_output.float()
                            # Compute L2 norm across feature dimension to get 2D matrix
                            template_output_norm = torch.norm(template_output, dim=-1).cpu().numpy()
                        else:
                            # Already numpy, compute norm
                            template_output_norm = np.linalg.norm(template_output, axis=-1)
                        
                        # Create visualization
                        fig, ax = plt.subplots(figsize=(10, 10))
                        im = ax.imshow(template_output_norm, cmap="viridis", aspect="equal")
                        ax.set_xlabel("Token j")
                        ax.set_ylabel("Token i")
                        ax.set_title("Template Output (L2 Norm)")
                        plt.colorbar(im, ax=ax, label="L2 Norm")
                        
                        # Save PNG (without model_idx since it's the same for all models)
                        path = struct_dir / f"template_output_{record.id}.png"
                        plt.savefig(path, dpi=150, bbox_inches="tight")
                        plt.close(fig)
                
                # Save embeddings
            if self.write_embeddings and "s" in prediction and "z" in prediction:
                s = prediction["s"].cpu().numpy()
                z = prediction["z"].cpu().numpy()

                path = (
                    struct_dir
                    / f"embeddings_{record.id}.npz"
                )
                np.savez_compressed(path, s=s, z=z)
            
            # Save inpainting metadata (only once per record, not per model)
            if "inpainting_metadata" in prediction and model_idx == 0:
                inpainting_metadata = prediction["inpainting_metadata"]
                
                # Convert chain index (asym_id) to chain_id (chain_name) using record.chains
                # Create mapping from chain_id (asym_id/index) to chain_name
                chain_index_to_name = {}
                for chain_info in record.chains:
                    chain_index_to_name[chain_info.chain_id] = chain_info.chain_name
                
                # Convert chain-based metadata to use chain_name instead of chain index
                # (model may already send chain names as keys; use as-is in that case)
                converted_metadata = {}
                if "chains" in inpainting_metadata:
                    converted_metadata["chains"] = {}
                    for chain_index, chain_data in inpainting_metadata["chains"].items():
                        if isinstance(chain_index, str):
                            chain_name = chain_index
                        else:
                            chain_name = chain_index_to_name.get(
                                chain_index, f"chain_{chain_index}"
                            )
                        converted_metadata["chains"][chain_name] = chain_data
                
                # Add LRD boundary info if available, converting chain indices to chain names
                if "lrd_boundary" in inpainting_metadata:
                    lrd_boundary = inpainting_metadata["lrd_boundary"].copy()
                    if "residues_by_chain" in lrd_boundary:
                        converted_lrd_by_chain = {}
                        for chain_index, residues in lrd_boundary["residues_by_chain"].items():
                            chain_name = chain_index_to_name.get(int(chain_index), f"chain_{chain_index}")
                            converted_lrd_by_chain[chain_name] = residues
                        lrd_boundary["residues_by_chain"] = converted_lrd_by_chain
                    converted_metadata["lrd_boundary"] = lrd_boundary

                path = struct_dir / f"inpainting_metadata_{record.id}.json"
                with path.open("w") as f:
                    f.write(json.dumps(converted_metadata, indent=4))

    def on_predict_epoch_end(
        self,
        trainer: Trainer,  # noqa: ARG002
        pl_module: LightningModule,  # noqa: ARG002
    ) -> None:
        """Print the number of failed examples."""
        # Print number of failed examples
        print(f"Number of failed examples: {self.failed}")  # noqa: T201


class BoltzAffinityWriter(BasePredictionWriter):
    """Custom writer for predictions."""

    def __init__(
        self,
        data_dir: str,
        output_dir: str,
    ) -> None:
        """Initialize the writer.

        Parameters
        ----------
        output_dir : str
            The directory to save the predictions.

        """
        super().__init__(write_interval="batch")
        self.failed = 0
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_on_batch_end(
        self,
        trainer: Trainer,  # noqa: ARG002
        pl_module: LightningModule,  # noqa: ARG002
        prediction: dict[str, Tensor],
        batch_indices: list[int],  # noqa: ARG002
        batch: dict[str, Tensor],
        batch_idx: int,  # noqa: ARG002
        dataloader_idx: int,  # noqa: ARG002
    ) -> None:
        """Write the predictions to disk."""
        if prediction["exception"]:
            self.failed += 1
            return
        # Dump affinity summary
        affinity_summary = {}
        pred_affinity_value = prediction["affinity_pred_value"]
        pred_affinity_probability = prediction["affinity_probability_binary"]
        affinity_summary = {
            "affinity_pred_value": pred_affinity_value.item(),
            "affinity_probability_binary": pred_affinity_probability.item(),
        }
        if "affinity_pred_value1" in prediction:
            pred_affinity_value1 = prediction["affinity_pred_value1"]
            pred_affinity_probability1 = prediction["affinity_probability_binary1"]
            pred_affinity_value2 = prediction["affinity_pred_value2"]
            pred_affinity_probability2 = prediction["affinity_probability_binary2"]
            affinity_summary["affinity_pred_value1"] = pred_affinity_value1.item()
            affinity_summary["affinity_probability_binary1"] = (
                pred_affinity_probability1.item()
            )
            affinity_summary["affinity_pred_value2"] = pred_affinity_value2.item()
            affinity_summary["affinity_probability_binary2"] = (
                pred_affinity_probability2.item()
            )

        # Save the affinity summary
        struct_dir = self.output_dir / batch["record"][0].id
        struct_dir.mkdir(exist_ok=True)
        path = struct_dir / f"affinity_{batch['record'][0].id}.json"

        with path.open("w") as f:
            f.write(json.dumps(affinity_summary, indent=4))

    def on_predict_epoch_end(
        self,
        trainer: Trainer,  # noqa: ARG002
        pl_module: LightningModule,  # noqa: ARG002
    ) -> None:
        """Print the number of failed examples."""
        # Print number of failed examples
        print(f"Number of failed examples: {self.failed}")  # noqa: T201
