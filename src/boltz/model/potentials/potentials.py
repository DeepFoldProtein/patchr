import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set, Union

import numpy as np
import torch

from boltz.data import const
from boltz.model.loss.diffusionv2 import weighted_rigid_align
from boltz.model.potentials.schedules import (
    ExponentialInterpolation,
    ParameterSchedule,
    PiecewiseStepFunction,
)


class Potential(ABC):
    def __init__(
        self,
        parameters: Optional[
            Dict[str, Union[ParameterSchedule, float, int, bool]]
        ] = None,
    ):
        self.parameters = parameters

    def compute(self, coords, feats, parameters):
        index, args, com_args, ref_args, operator_args = self.compute_args(
            feats, parameters
        )

        if index.shape[1] == 0:
            return torch.zeros(coords.shape[:-2], device=coords.device)

        if com_args is not None:
            com_index, atom_pad_mask = com_args
            unpad_com_index = com_index[atom_pad_mask]
            unpad_coords = coords[..., atom_pad_mask, :]
            coords = torch.zeros(
                (*unpad_coords.shape[:-2], unpad_com_index.max() + 1, 3),
                device=coords.device,
            ).scatter_reduce(
                -2,
                unpad_com_index.unsqueeze(-1).expand_as(unpad_coords),
                unpad_coords,
                "mean",
            )
        else:
            com_index, atom_pad_mask = None, None

        if ref_args is not None:
            ref_coords, ref_mask, ref_atom_index, ref_token_index = ref_args
            coords = coords[..., ref_atom_index, :]
        else:
            ref_coords, ref_mask, ref_atom_index, ref_token_index = (
                None,
                None,
                None,
                None,
            )

        if operator_args is not None:
            negation_mask, union_index = operator_args
        else:
            negation_mask, union_index = None, None

        value = self.compute_variable(
            coords,
            index,
            ref_coords=ref_coords,
            ref_mask=ref_mask,
            compute_gradient=False,
        )
        energy = self.compute_function(
            value, *args, negation_mask=negation_mask, compute_derivative=False
        )

        if union_index is not None:
            neg_exp_energy = torch.exp(-1 * parameters["union_lambda"] * energy)
            Z = torch.zeros(
                (*energy.shape[:-1], union_index.max() + 1), device=union_index.device
            ).scatter_reduce(
                -1,
                union_index.expand_as(neg_exp_energy),
                neg_exp_energy,
                "sum",
            )
            softmax_energy = neg_exp_energy / Z[..., union_index]
            softmax_energy[Z[..., union_index] == 0] = 0
            return (energy * softmax_energy).sum(dim=-1)

        return energy.sum(dim=tuple(range(1, energy.dim())))

    def compute_gradient(self, coords, feats, parameters):
        index, args, com_args, ref_args, operator_args = self.compute_args(
            feats, parameters
        )
        if index.shape[1] == 0:
            return torch.zeros_like(coords)

        if com_args is not None:
            com_index, atom_pad_mask = com_args
            unpad_coords = coords[..., atom_pad_mask, :]
            unpad_com_index = com_index[atom_pad_mask]
            coords = torch.zeros(
                (*unpad_coords.shape[:-2], unpad_com_index.max() + 1, 3),
                device=coords.device,
            ).scatter_reduce(
                -2,
                unpad_com_index.unsqueeze(-1).expand_as(unpad_coords),
                unpad_coords,
                "mean",
            )
            com_counts = torch.bincount(com_index[atom_pad_mask])
        else:
            com_index, atom_pad_mask = None, None

        if ref_args is not None:
            ref_coords, ref_mask, ref_atom_index, ref_token_index = ref_args
            coords = coords[..., ref_atom_index, :]
        else:
            ref_coords, ref_mask, ref_atom_index, ref_token_index = (
                None,
                None,
                None,
                None,
            )

        if operator_args is not None:
            negation_mask, union_index = operator_args
        else:
            negation_mask, union_index = None, None

        value, grad_value = self.compute_variable(
            coords,
            index,
            ref_coords=ref_coords,
            ref_mask=ref_mask,
            compute_gradient=True,
        )
        energy, dEnergy = self.compute_function(
            value, *args, negation_mask=negation_mask, compute_derivative=True
        )
        if union_index is not None:
            neg_exp_energy = torch.exp(-1 * parameters["union_lambda"] * energy)
            Z = torch.zeros(
                (*energy.shape[:-1], union_index.max() + 1), device=union_index.device
            ).scatter_reduce(
                -1,
                union_index.expand_as(energy),
                neg_exp_energy,
                "sum",
            )
            softmax_energy = neg_exp_energy / Z[..., union_index]
            softmax_energy[Z[..., union_index] == 0] = 0
            f = torch.zeros(
                (*energy.shape[:-1], union_index.max() + 1), device=union_index.device
            ).scatter_reduce(
                -1,
                union_index.expand_as(energy),
                energy * softmax_energy,
                "sum",
            )
            dSoftmax = (
                dEnergy
                * softmax_energy
                * (1 + parameters["union_lambda"] * (energy - f[..., union_index]))
            )
            prod = dSoftmax.tile(grad_value.shape[-3]).unsqueeze(
                -1
            ) * grad_value.flatten(start_dim=-3, end_dim=-2)
            if prod.dim() > 3:
                prod = prod.sum(dim=list(range(1, prod.dim() - 2)))
            grad_atom = torch.zeros_like(coords).scatter_reduce(
                -2,
                index.flatten(start_dim=0, end_dim=1)
                .unsqueeze(-1)
                .expand((*coords.shape[:-2], -1, 3)),
                prod,
                "sum",
            )
        else:
            prod = dEnergy.tile(grad_value.shape[-3]).unsqueeze(
                -1
            ) * grad_value.flatten(start_dim=-3, end_dim=-2)
            if prod.dim() > 3:
                prod = prod.sum(dim=list(range(1, prod.dim() - 2)))
            grad_atom = torch.zeros_like(coords).scatter_reduce(
                -2,
                index.flatten(start_dim=0, end_dim=1)
                .unsqueeze(-1)
                .expand((*coords.shape[:-2], -1, 3)),  # 9 x 516 x 3
                prod,
                "sum",
            )

        if com_index is not None:
            grad_atom = grad_atom[..., com_index, :]
        elif ref_token_index is not None:
            grad_atom = grad_atom[..., ref_token_index, :]

        return grad_atom

    def compute_parameters(self, t):
        if self.parameters is None:
            return None
        parameters = {
            name: (
                parameter
                if not isinstance(parameter, ParameterSchedule)
                else parameter.compute(t)
            )
            for name, parameter in self.parameters.items()
        }
        return parameters

    @abstractmethod
    def compute_function(
        self, value, *args, negation_mask=None, compute_derivative=False
    ):
        raise NotImplementedError

    @abstractmethod
    def compute_variable(self, coords, index, compute_gradient=False):
        raise NotImplementedError

    @abstractmethod
    def compute_args(self, t, feats, **parameters):
        raise NotImplementedError

    def get_reference_coords(self, feats, parameters):
        return None, None


class FlatBottomPotential(Potential):
    def compute_function(
        self,
        value,
        k,
        lower_bounds,
        upper_bounds,
        negation_mask=None,
        compute_derivative=False,
    ):
        if lower_bounds is None:
            lower_bounds = torch.full_like(value, float("-inf"))
        if upper_bounds is None:
            upper_bounds = torch.full_like(value, float("inf"))
        lower_bounds = lower_bounds.expand_as(value).clone()
        upper_bounds = upper_bounds.expand_as(value).clone()

        if negation_mask is not None:
            unbounded_below_mask = torch.isneginf(lower_bounds)
            unbounded_above_mask = torch.isposinf(upper_bounds)
            unbounded_mask = unbounded_below_mask + unbounded_above_mask
            assert torch.all(unbounded_mask + negation_mask)
            lower_bounds[~unbounded_above_mask * ~negation_mask] = upper_bounds[
                ~unbounded_above_mask * ~negation_mask
            ]
            upper_bounds[~unbounded_above_mask * ~negation_mask] = float("inf")
            upper_bounds[~unbounded_below_mask * ~negation_mask] = lower_bounds[
                ~unbounded_below_mask * ~negation_mask
            ]
            lower_bounds[~unbounded_below_mask * ~negation_mask] = float("-inf")

        neg_overflow_mask = value < lower_bounds
        pos_overflow_mask = value > upper_bounds

        energy = torch.zeros_like(value)
        energy[neg_overflow_mask] = (k * (lower_bounds - value))[neg_overflow_mask]
        energy[pos_overflow_mask] = (k * (value - upper_bounds))[pos_overflow_mask]
        if not compute_derivative:
            return energy

        dEnergy = torch.zeros_like(value)
        dEnergy[neg_overflow_mask] = (
            -1 * k.expand_as(neg_overflow_mask)[neg_overflow_mask]
        )
        dEnergy[pos_overflow_mask] = (
            1 * k.expand_as(pos_overflow_mask)[pos_overflow_mask]
        )

        return energy, dEnergy


class ReferencePotential(Potential):
    def compute_variable(
        self, coords, index, ref_coords, ref_mask, compute_gradient=False
    ):
        aligned_ref_coords = weighted_rigid_align(
            ref_coords.float(),
            coords[:, index].float(),
            ref_mask,
            ref_mask,
        )

        r = coords[:, index] - aligned_ref_coords
        r_norm = torch.linalg.norm(r, dim=-1)

        if not compute_gradient:
            return r_norm

        r_hat = r / r_norm.unsqueeze(-1)
        grad = (r_hat * ref_mask.unsqueeze(-1)).unsqueeze(1)
        return r_norm, grad


class DistancePotential(Potential):
    def compute_variable(
        self, coords, index, ref_coords=None, ref_mask=None, compute_gradient=False
    ):
        r_ij = coords.index_select(-2, index[0]) - coords.index_select(-2, index[1])
        r_ij_norm = torch.linalg.norm(r_ij, dim=-1)
        r_hat_ij = r_ij / r_ij_norm.unsqueeze(-1)

        if not compute_gradient:
            return r_ij_norm

        grad_i = r_hat_ij
        grad_j = -1 * r_hat_ij
        grad = torch.stack((grad_i, grad_j), dim=1)
        return r_ij_norm, grad


class DihedralPotential(Potential):
    def compute_variable(
        self, coords, index, ref_coords=None, ref_mask=None, compute_gradient=False
    ):
        r_ij = coords.index_select(-2, index[0]) - coords.index_select(-2, index[1])
        r_kj = coords.index_select(-2, index[2]) - coords.index_select(-2, index[1])
        r_kl = coords.index_select(-2, index[2]) - coords.index_select(-2, index[3])

        n_ijk = torch.cross(r_ij, r_kj, dim=-1)
        n_jkl = torch.cross(r_kj, r_kl, dim=-1)

        r_kj_norm = torch.linalg.norm(r_kj, dim=-1)
        n_ijk_norm = torch.linalg.norm(n_ijk, dim=-1)
        n_jkl_norm = torch.linalg.norm(n_jkl, dim=-1)

        sign_phi = torch.sign(
            r_kj.unsqueeze(-2) @ torch.cross(n_ijk, n_jkl, dim=-1).unsqueeze(-1)
        ).squeeze(-1, -2)
        phi = sign_phi * torch.arccos(
            torch.clamp(
                (n_ijk.unsqueeze(-2) @ n_jkl.unsqueeze(-1)).squeeze(-1, -2)
                / (n_ijk_norm * n_jkl_norm),
                -1 + 1e-8,
                1 - 1e-8,
            )
        )

        if not compute_gradient:
            return phi

        a = (
            (r_ij.unsqueeze(-2) @ r_kj.unsqueeze(-1)).squeeze(-1, -2) / (r_kj_norm**2)
        ).unsqueeze(-1)
        b = (
            (r_kl.unsqueeze(-2) @ r_kj.unsqueeze(-1)).squeeze(-1, -2) / (r_kj_norm**2)
        ).unsqueeze(-1)

        grad_i = n_ijk * (r_kj_norm / n_ijk_norm**2).unsqueeze(-1)
        grad_l = -1 * n_jkl * (r_kj_norm / n_jkl_norm**2).unsqueeze(-1)
        grad_j = (a - 1) * grad_i - b * grad_l
        grad_k = (b - 1) * grad_l - a * grad_i
        grad = torch.stack((grad_i, grad_j, grad_k, grad_l), dim=1)
        return phi, grad


class AbsDihedralPotential(DihedralPotential):
    def compute_variable(
        self, coords, index, ref_coords=None, ref_mask=None, compute_gradient=False
    ):
        if not compute_gradient:
            phi = super().compute_variable(
                coords, index, compute_gradient=compute_gradient
            )
            phi = torch.abs(phi)
            return phi

        phi, grad = super().compute_variable(
            coords, index, compute_gradient=compute_gradient
        )
        grad[(phi < 0)[..., None, :, None].expand_as(grad)] *= -1
        phi = torch.abs(phi)

        return phi, grad


class PoseBustersPotential(FlatBottomPotential, DistancePotential):
    def compute_args(self, feats, parameters):
        pair_index = feats["rdkit_bounds_index"][0]
        lower_bounds = feats["rdkit_lower_bounds"][0].clone()
        upper_bounds = feats["rdkit_upper_bounds"][0].clone()
        bond_mask = feats["rdkit_bounds_bond_mask"][0]
        angle_mask = feats["rdkit_bounds_angle_mask"][0]

        lower_bounds[bond_mask * ~angle_mask] *= 1.0 - parameters["bond_buffer"]
        upper_bounds[bond_mask * ~angle_mask] *= 1.0 + parameters["bond_buffer"]
        lower_bounds[~bond_mask * angle_mask] *= 1.0 - parameters["angle_buffer"]
        upper_bounds[~bond_mask * angle_mask] *= 1.0 + parameters["angle_buffer"]
        lower_bounds[bond_mask * angle_mask] *= 1.0 - min(
            parameters["bond_buffer"], parameters["angle_buffer"]
        )
        upper_bounds[bond_mask * angle_mask] *= 1.0 + min(
            parameters["bond_buffer"], parameters["angle_buffer"]
        )
        lower_bounds[~bond_mask * ~angle_mask] *= 1.0 - parameters["clash_buffer"]
        upper_bounds[~bond_mask * ~angle_mask] = float("inf")

        vdw_radii = torch.zeros(
            const.num_elements, dtype=torch.float32, device=pair_index.device
        )
        vdw_radii[1:119] = torch.tensor(
            const.vdw_radii, dtype=torch.float32, device=pair_index.device
        )
        atom_vdw_radii = (
            feats["ref_element"].float() @ vdw_radii.unsqueeze(-1)
        ).squeeze(-1)[0]
        bond_cutoffs = 0.35 + atom_vdw_radii[pair_index].mean(dim=0)
        lower_bounds[~bond_mask] = torch.max(
            lower_bounds[~bond_mask], bond_cutoffs[~bond_mask]
        )
        upper_bounds[bond_mask] = torch.min(
            upper_bounds[bond_mask], bond_cutoffs[bond_mask]
        )

        k = torch.ones_like(lower_bounds)

        return pair_index, (k, lower_bounds, upper_bounds), None, None, None


class ConnectionsPotential(FlatBottomPotential, DistancePotential):
    def compute_args(self, feats, parameters):
        pair_index = feats["connected_atom_index"][0]
        lower_bounds = None
        upper_bounds = torch.full(
            (pair_index.shape[1],), parameters["buffer"], device=pair_index.device
        )
        k = torch.ones_like(upper_bounds)

        return pair_index, (k, lower_bounds, upper_bounds), None, None, None


class VDWOverlapPotential(FlatBottomPotential, DistancePotential):
    def compute_args(self, feats, parameters):
        atom_chain_id = (
            torch.bmm(
                feats["atom_to_token"].float(), feats["asym_id"].unsqueeze(-1).float()
            )
            .squeeze(-1)
            .long()
        )[0]
        atom_pad_mask = feats["atom_pad_mask"][0].bool()
        chain_sizes = torch.bincount(atom_chain_id[atom_pad_mask])
        single_ion_mask = (chain_sizes > 1)[atom_chain_id]

        vdw_radii = torch.zeros(
            const.num_elements, dtype=torch.float32, device=atom_chain_id.device
        )
        vdw_radii[1:119] = torch.tensor(
            const.vdw_radii, dtype=torch.float32, device=atom_chain_id.device
        )
        atom_vdw_radii = (
            feats["ref_element"].float() @ vdw_radii.unsqueeze(-1)
        ).squeeze(-1)[0]

        pair_index = torch.triu_indices(
            atom_chain_id.shape[0],
            atom_chain_id.shape[0],
            1,
            device=atom_chain_id.device,
        )

        pair_pad_mask = atom_pad_mask[pair_index].all(dim=0)
        pair_ion_mask = single_ion_mask[pair_index[0]] * single_ion_mask[pair_index[1]]

        num_chains = atom_chain_id.max() + 1
        connected_chain_index = feats["connected_chain_index"][0]
        connected_chain_matrix = torch.eye(
            num_chains, device=atom_chain_id.device, dtype=torch.bool
        )
        connected_chain_matrix[connected_chain_index[0], connected_chain_index[1]] = (
            True
        )
        connected_chain_matrix[connected_chain_index[1], connected_chain_index[0]] = (
            True
        )
        connected_chain_mask = connected_chain_matrix[
            atom_chain_id[pair_index[0]], atom_chain_id[pair_index[1]]
        ]

        pair_index = pair_index[
            :, pair_pad_mask * pair_ion_mask * ~connected_chain_mask
        ]

        lower_bounds = atom_vdw_radii[pair_index].sum(dim=0) * (
            1.0 - parameters["buffer"]
        )
        upper_bounds = None
        k = torch.ones_like(lower_bounds)

        return pair_index, (k, lower_bounds, upper_bounds), None, None, None


class SymmetricChainCOMPotential(FlatBottomPotential, DistancePotential):
    def compute_args(self, feats, parameters):
        atom_chain_id = (
            torch.bmm(
                feats["atom_to_token"].float(), feats["asym_id"].unsqueeze(-1).float()
            )
            .squeeze(-1)
            .long()
        )[0]
        atom_pad_mask = feats["atom_pad_mask"][0].bool()
        chain_sizes = torch.bincount(atom_chain_id[atom_pad_mask])
        single_ion_mask = chain_sizes > 1

        pair_index = feats["symmetric_chain_index"][0]
        pair_ion_mask = single_ion_mask[pair_index[0]] * single_ion_mask[pair_index[1]]
        pair_index = pair_index[:, pair_ion_mask]
        lower_bounds = torch.full(
            (pair_index.shape[1],),
            parameters["buffer"],
            dtype=torch.float32,
            device=pair_index.device,
        )
        upper_bounds = None
        k = torch.ones_like(lower_bounds)

        return (
            pair_index,
            (k, lower_bounds, upper_bounds),
            (atom_chain_id, atom_pad_mask),
            None,
            None,
        )


class StereoBondPotential(FlatBottomPotential, AbsDihedralPotential):
    def compute_args(self, feats, parameters):
        stereo_bond_index = feats["stereo_bond_index"][0]
        stereo_bond_orientations = feats["stereo_bond_orientations"][0].bool()

        lower_bounds = torch.zeros(
            stereo_bond_orientations.shape, device=stereo_bond_orientations.device
        )
        upper_bounds = torch.zeros(
            stereo_bond_orientations.shape, device=stereo_bond_orientations.device
        )
        lower_bounds[stereo_bond_orientations] = torch.pi - parameters["buffer"]
        upper_bounds[stereo_bond_orientations] = float("inf")
        lower_bounds[~stereo_bond_orientations] = float("-inf")
        upper_bounds[~stereo_bond_orientations] = parameters["buffer"]

        k = torch.ones_like(lower_bounds)

        return stereo_bond_index, (k, lower_bounds, upper_bounds), None, None, None


class ChiralAtomPotential(FlatBottomPotential, DihedralPotential):
    def compute_args(self, feats, parameters):
        chiral_atom_index = feats["chiral_atom_index"][0]
        chiral_atom_orientations = feats["chiral_atom_orientations"][0].bool()

        lower_bounds = torch.zeros(
            chiral_atom_orientations.shape, device=chiral_atom_orientations.device
        )
        upper_bounds = torch.zeros(
            chiral_atom_orientations.shape, device=chiral_atom_orientations.device
        )
        lower_bounds[chiral_atom_orientations] = parameters["buffer"]
        upper_bounds[chiral_atom_orientations] = float("inf")
        upper_bounds[~chiral_atom_orientations] = -1 * parameters["buffer"]
        lower_bounds[~chiral_atom_orientations] = float("-inf")

        k = torch.ones_like(lower_bounds)
        return chiral_atom_index, (k, lower_bounds, upper_bounds), None, None, None


class PlanarBondPotential(FlatBottomPotential, AbsDihedralPotential):
    def compute_args(self, feats, parameters):
        double_bond_index = feats["planar_bond_index"][0].T
        double_bond_improper_index = torch.tensor(
            [
                [1, 2, 3, 0],
                [4, 5, 0, 3],
            ],
            device=double_bond_index.device,
        ).T
        improper_index = (
            double_bond_index[:, double_bond_improper_index]
            .swapaxes(0, 1)
            .flatten(start_dim=1)
        )
        lower_bounds = None
        upper_bounds = torch.full(
            (improper_index.shape[1],),
            parameters["buffer"],
            device=improper_index.device,
        )
        k = torch.ones_like(upper_bounds)

        return improper_index, (k, lower_bounds, upper_bounds), None, None, None


class TemplateReferencePotential(FlatBottomPotential, ReferencePotential):
    def compute_args(self, feats, parameters):
        if "template_mask_cb" not in feats or "template_force" not in feats:
            return torch.empty([1, 0]), None, None, None, None

        template_mask = feats["template_mask_cb"][feats["template_force"]]
        if template_mask.shape[0] == 0:
            return torch.empty([1, 0]), None, None, None, None

        ref_coords = feats["template_cb"][feats["template_force"]].clone()
        ref_mask = feats["template_mask_cb"][feats["template_force"]].clone()
        ref_atom_index = (
            torch.bmm(
                feats["token_to_rep_atom"].float(),
                torch.arange(
                    feats["atom_pad_mask"].shape[1],
                    device=feats["atom_pad_mask"].device,
                    dtype=torch.float32,
                )[None, :, None],
            )
            .squeeze(-1)
            .long()
        )[0]
        ref_token_index = (
            torch.bmm(
                feats["atom_to_token"].float(),
                feats["token_index"].unsqueeze(-1).float(),
            )
            .squeeze(-1)
            .long()
        )[0]

        index = torch.arange(
            template_mask.shape[-1], dtype=torch.long, device=template_mask.device
        )[None]
        upper_bounds = torch.full(
            template_mask.shape, float("inf"), device=index.device, dtype=torch.float32
        )
        ref_idxs = torch.argwhere(template_mask).T
        upper_bounds[ref_idxs.unbind()] = feats["template_force_threshold"][
            feats["template_force"]
        ][ref_idxs[0]]

        lower_bounds = None
        k = torch.ones_like(upper_bounds)
        return (
            index,
            (k, lower_bounds, upper_bounds),
            None,
            (ref_coords, ref_mask, ref_atom_index, ref_token_index),
            None,
        )


class ContactPotentital(FlatBottomPotential, DistancePotential):
    def compute_args(self, feats, parameters):
        index = feats["contact_pair_index"][0]
        union_index = feats["contact_union_index"][0]
        negation_mask = feats["contact_negation_mask"][0]
        lower_bounds = None
        upper_bounds = feats["contact_thresholds"][0].clone()
        k = torch.ones_like(upper_bounds)
        return (
            index,
            (k, lower_bounds, upper_bounds),
            None,
            None,
            (negation_mask, union_index),
        )


class InpaintingBoundaryPeptideBondPotential(FlatBottomPotential, DistancePotential):
    """Potential to pull peptide bond atoms (C and N) at inpainting boundaries to ~1.3Å.

    This potential identifies boundaries between fixed and inpainted regions and
    applies a distance constraint on the peptide bond (C of residue i and N of residue i+1).
    """

    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.log_interval = 10  # Log every N steps
        self.step_count = 0
        self.boundary_pairs = []
        self.last_index = None
        self._boundary_cache_valid = False  # Cache flag
        self._cached_device = None

    def _find_boundaries(self, feats):
        """Find boundary residues and cache the result."""
        # Check if inpainting is enabled
        if (
            "inpainting_template_mask" not in feats
            or feats["inpainting_template_mask"] is None
        ):
            return []

        if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
            return []

        template_mask = feats["inpainting_template_mask"][0]  # (atoms,)
        atom_to_token = feats["atom_to_token"][0]  # (atoms, tokens)
        atom_backbone_feat = feats["atom_backbone_feat"][
            0
        ]  # (atoms, num_classes) - one-hot encoded
        atom_pad_mask = feats["atom_pad_mask"][0].bool()  # (atoms,)

        num_tokens = atom_to_token.shape[1]
        device = template_mask.device

        # Convert one-hot encoded backbone_feat to integer indices
        # atom_backbone_feat is one-hot: (atoms, num_classes)
        # C atom: index 3 (1-based, C is index 2 -> 3)
        # N atom: index 1 (1-based, N is index 0 -> 1)
        if atom_backbone_feat.dim() > 1:
            # One-hot encoded: convert to integer indices
            backbone_feat_indices = atom_backbone_feat.argmax(dim=-1)  # (atoms,)
        else:
            # Already integer indices
            backbone_feat_indices = atom_backbone_feat.long()

        # Find boundary residues
        # Boundary: residue i has template and residue i+1 doesn't, or vice versa
        # Exclude N-term (residue 0) and C-term (last residue) - but we'll include them if they're boundaries
        boundary_pairs = []

        # Get residue-level template mask (residue has template if any atom has template)
        residue_has_template = torch.zeros(num_tokens, dtype=torch.bool, device=device)
        for token_idx in range(num_tokens):
            token_atoms = atom_to_token[:, token_idx].bool()
            if token_atoms.any():
                residue_has_template[token_idx] = template_mask[token_atoms].any()

        # Find boundaries: consecutive residues with different template status
        # Exclude N-term (token_idx == 0) and C-term (token_idx == num_tokens - 2) boundaries
        for token_idx in range(1, num_tokens - 2):  # Skip first and last boundaries
            # Check if they have different template status (this is a boundary)
            if residue_has_template[token_idx] != residue_has_template[token_idx + 1]:
                # This is a boundary
                # Find C atom in residue i and N atom in residue i+1
                token_i_atoms = atom_to_token[:, token_idx].bool() & atom_pad_mask
                token_i1_atoms = atom_to_token[:, token_idx + 1].bool() & atom_pad_mask

                # Find C atom in residue i (backbone_feat == 3, 1-based: C is index 2 -> 3)
                # Find N atom in residue i+1 (backbone_feat == 1, 1-based: N is index 0 -> 1)
                c_atoms = torch.where(token_i_atoms & (backbone_feat_indices == 3))[0]
                n_atoms = torch.where(token_i1_atoms & (backbone_feat_indices == 1))[0]

                if len(c_atoms) > 0 and len(n_atoms) > 0:
                    # Use first matching atom (should typically be only one)
                    c_atom = c_atoms[0]
                    n_atom = n_atoms[0]
                    boundary_pairs.append(
                        (c_atom.item(), n_atom.item(), token_idx, token_idx + 1)
                    )

        return boundary_pairs

    def compute_args(self, feats, parameters):
        # Check if inpainting is enabled
        if (
            "inpainting_template_mask" not in feats
            or feats["inpainting_template_mask"] is None
        ):
            self.boundary_pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._boundary_cache_valid = False
            return self.last_index, None, None, None, None

        if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
            self.boundary_pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._boundary_cache_valid = False
            return self.last_index, None, None, None, None

        device = feats["inpainting_template_mask"][0].device

        # Use cached boundary pairs if available and device matches
        if not self._boundary_cache_valid or self._cached_device != device:
            # Find boundaries and cache the result
            boundary_pairs = self._find_boundaries(feats)
            self.boundary_pairs = boundary_pairs
            self._boundary_cache_valid = True
            self._cached_device = device

            # Log initial boundary bond distances only when first finding boundaries
            if (
                len(boundary_pairs) > 0
                and "inpainting_template_coords" in feats
                and feats["inpainting_template_coords"] is not None
            ):
                template_mask = feats["inpainting_template_mask"][0]
                template_coords = feats["inpainting_template_coords"][0]  # (atoms, 3)
                print(
                    f"[InpaintingBoundaryPeptideBond] Found {len(boundary_pairs)} boundary pairs (cached):"
                )
                for i, pair in enumerate(boundary_pairs):
                    c_idx, n_idx, res_i, res_i1 = pair
                    c_coord = template_coords[c_idx] if template_mask[c_idx] else None
                    n_coord = template_coords[n_idx] if template_mask[n_idx] else None
                    c_is_template = (
                        template_mask[c_idx].item()
                        if c_idx < len(template_mask)
                        else False
                    )
                    n_is_template = (
                        template_mask[n_idx].item()
                        if n_idx < len(template_mask)
                        else False
                    )
                    if c_coord is not None and n_coord is not None:
                        dist = torch.linalg.norm(c_coord - n_coord).item()
                        print(
                            f"  Res{res_i+1}-Res{res_i1+1}: C atom {c_idx} (template={c_is_template}), N atom {n_idx} (template={n_is_template}), initial C-N dist={dist:.3f}Å"
                        )
                    else:
                        print(
                            f"  Res{res_i+1}-Res{res_i1+1}: C atom {c_idx} (template={c_is_template}), N atom {n_idx} (template={n_is_template}), (one or both atoms need inpainting)"
                        )
        else:
            # Use cached boundary pairs
            boundary_pairs = self.boundary_pairs

        if len(boundary_pairs) == 0:
            self.last_index = torch.empty([2, 0], dtype=torch.long, device=device)
            return self.last_index, None, None, None, None

        # Create index tensor for C-N distance potential only (keep it simple)
        c_indices = torch.tensor(
            [pair[0] for pair in boundary_pairs], dtype=torch.long, device=device
        )
        n_indices = torch.tensor(
            [pair[1] for pair in boundary_pairs], dtype=torch.long, device=device
        )
        index = torch.stack([c_indices, n_indices], dim=0)  # (2, num_pairs)
        self.last_index = index

        # Set target distance for C-N to 1.3Å with some tolerance
        target_distance = parameters.get("target_distance", 1.3) if parameters else 1.3
        tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1

        # Use base k value
        base_k = parameters.get("k", 20.0) if parameters else 20.0
        k = torch.ones(index.shape[1], device=device, dtype=torch.float32) * base_k

        lower_bounds = torch.full(
            (index.shape[1],),
            target_distance - tolerance,
            device=device,
            dtype=torch.float32,
        )
        upper_bounds = torch.full(
            (index.shape[1],),
            target_distance + tolerance,
            device=device,
            dtype=torch.float32,
        )

        return index, (k, lower_bounds, upper_bounds), None, None, None

    def compute_gradient(self, coords, feats, parameters):
        """Override compute_gradient to mask template atoms and fix gradient direction.

        The issue: FlatBottomPotential gives dEnergy = +k when distance > upper_bounds,
        which makes gradient push atoms apart. We need to flip the sign so that
        when distance is too large, atoms are pulled together.
        """
        # Log distances BEFORE gradient application
        dist_before = None
        if (
            len(self.boundary_pairs) > 0
            and self.last_index is not None
            and self.last_index.shape[1] > 0
        ):
            c_coords_before = coords[0, self.last_index[0], :]
            n_coords_before = coords[0, self.last_index[1], :]
            dist_before = torch.linalg.norm(c_coords_before - n_coords_before, dim=-1)

        result = super().compute_gradient(coords, feats, parameters)

        # CRITICAL FIX: The gradient from FlatBottomPotential pushes atoms apart when distance > upper_bounds
        # But we want to pull them together. Since guidance_update -= energy_gradient,
        # we need to make sure the gradient points in the direction that increases energy
        # (so that subtracting it decreases energy and pulls atoms together).
        #
        # Current behavior: dEnergy = +k when distance > upper_bounds
        #   grad_C = +k * (C-N)/|C-N| (pushes C away from N)
        #   grad_N = -k * (C-N)/|C-N| (pushes N away from C)
        # With guidance_update -= energy_gradient:
        #   guidance_update_C = -k * (C-N)/|C-N| = +k * (N-C)/|C-N| (pulls C toward N) ✓
        #   guidance_update_N = +k * (C-N)/|C-N| (pulls N toward C) ✓
        #
        # So the original logic should work! But it's not working. Let's check if the issue
        # is that we're flipping the gradient AFTER it's computed, which might be causing issues.
        #
        # Actually, wait - if dot=+30.0000 means gradient is in C→N direction, and we want
        # to pull together, then C should move toward N, which means gradient should be N→C direction.
        # So we DO need to flip it!

        # But the current flip is making it worse. Let me think...
        # If dot=+30.0000 after flipping, and distance is increasing, then the flip is wrong.
        # Let's NOT flip and see what happens with the original gradient.

        # Get template mask before masking
        template_mask = None
        if (
            "inpainting_template_mask" in feats
            and feats["inpainting_template_mask"] is not None
        ):
            template_mask = feats["inpainting_template_mask"][0]  # (atoms,)

        # Log gradient BEFORE masking to understand the raw gradient
        if (
            len(self.boundary_pairs) > 0
            and self.last_index is not None
            and self.last_index.shape[1] > 0
        ):
            # Use step_idx from parameters if available (from diffusionv2.py), otherwise use step_count
            step_idx = parameters.get("step_idx", None) if parameters else None
            is_last_guidance_step = (
                parameters.get("is_last_guidance_step", True) if parameters else True
            )

            if step_idx is not None:
                # Use step_idx directly from diffusion module
                current_step = step_idx
            else:
                # Fallback to step_count for backward compatibility
                self.step_count += 1
                current_step = self.step_count

            log_interval = self.log_interval
            if parameters is not None:
                log_interval = parameters.get("log_interval", self.log_interval)

            # Only log on the last guidance_step of each diffusion step to avoid duplicate logs
            # (same step_idx can have multiple guidance_steps)
            # Also log on the last step if explicitly requested
            is_last_step = (
                parameters.get("is_last_step", False) if parameters else False
            )
            if (
                current_step % log_interval == 0 or is_last_step
            ) and is_last_guidance_step:
                # Get current C-N distances
                c_coords = coords[0, self.last_index[0], :]
                n_coords = coords[0, self.last_index[1], :]
                distances = torch.linalg.norm(c_coords - n_coords, dim=-1)

                # Get gradient BEFORE masking
                guidance_weight = (
                    parameters.get("guidance_weight", 1.0) if parameters else 1.0
                )
                c_grad_raw = result[0, self.last_index[0], :]  # (num_pairs, 3)
                n_grad_raw = result[0, self.last_index[1], :]  # (num_pairs, 3)
                c_grad_mags_raw = torch.linalg.norm(c_grad_raw, dim=-1)
                n_grad_mags_raw = torch.linalg.norm(n_grad_raw, dim=-1)

                # Get gradient direction (unit vector from C to N)
                c_to_n = n_coords - c_coords  # (num_pairs, 3)
                c_to_n_norm = torch.linalg.norm(
                    c_to_n, dim=-1, keepdim=True
                )  # (num_pairs, 1)
                c_to_n_unit = c_to_n / (c_to_n_norm + 1e-8)  # (num_pairs, 3)

                # Check if gradient is in the right direction (should point C->N when distance is too large)
                c_grad_dot = (c_grad_raw * c_to_n_unit).sum(dim=-1)  # dot product
                n_grad_dot = (n_grad_raw * (-c_to_n_unit)).sum(
                    dim=-1
                )  # N should move opposite direction

                # Log distances and gradients
                distances_list = distances.cpu().tolist()
                dist_before_list = (
                    dist_before.cpu().tolist()
                    if dist_before is not None
                    else [None] * len(distances_list)
                )
                c_grad_list = (c_grad_mags_raw * guidance_weight).cpu().tolist()
                n_grad_list = (n_grad_mags_raw * guidance_weight).cpu().tolist()
                c_grad_dot_list = (c_grad_dot * guidance_weight).cpu().tolist()
                n_grad_dot_list = (n_grad_dot * guidance_weight).cpu().tolist()

                pairs_info = []
                for i, pair in enumerate(self.boundary_pairs):
                    res_i, res_i1 = pair[2], pair[3]  # token_idx, token_idx + 1
                    dist_curr = distances_list[i]
                    dist_prev = (
                        dist_before_list[i]
                        if dist_before_list[i] is not None
                        else dist_curr
                    )
                    c_grad = c_grad_list[i]
                    n_grad = n_grad_list[i]
                    c_dot = c_grad_dot_list[i]
                    n_dot = n_grad_dot_list[i]
                    c_is_template = (
                        template_mask[self.last_index[0, i]].item()
                        if template_mask is not None
                        else False
                    )
                    n_is_template = (
                        template_mask[self.last_index[1, i]].item()
                        if template_mask is not None
                        else False
                    )
                    target_dist = (
                        parameters.get("target_distance", 1.3) if parameters else 1.3
                    )
                    info = f"Res{res_i+1}-Res{res_i1+1}: C-N={dist_curr:.3f}Å (target={target_dist:.1f}Å, C_tmpl={c_is_template}, N_tmpl={n_is_template}), grad_C={c_grad:.4f} (dot={c_dot:+.4f}), grad_N={n_grad:.4f} (dot={n_dot:+.4f})"
                    pairs_info.append(info)

                print(
                    f"[InpaintingBoundaryPeptideBond] Step {current_step}: {len(pairs_info)} boundary bonds"
                )
                for info in pairs_info:
                    print(f"  {info}")

        # Simply mask gradient for template atoms (they should not be moved)
        if template_mask is not None:
            result[0, template_mask, :] = 0.0

        return result


class InpaintingBoundaryCACDistancePotential(FlatBottomPotential, DistancePotential):
    """Potential to constrain CA-C distance to ~1.53Å within inpainting target residues at boundaries.

    This potential identifies inpainting target residues (those without template) at boundaries
    and applies a distance constraint on the CA-C bond within each residue.
    """

    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.log_interval = 1  # Log every N steps
        self.step_count = 0
        self.ca_c_pairs = []  # List of (ca_atom_idx, c_atom_idx, token_idx)
        self.last_index = None
        self._cache_valid = False  # Cache flag
        self._cached_device = None

    def _find_boundary_inpainting_residues(self, feats):
        """Find inpainting target residues at boundaries and their CA-C pairs."""
        # Check if inpainting is enabled
        if (
            "inpainting_template_mask" not in feats
            or feats["inpainting_template_mask"] is None
        ):
            return []

        if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
            return []

        template_mask = feats["inpainting_template_mask"][0]  # (atoms,)
        atom_to_token = feats["atom_to_token"][0]  # (atoms, tokens)
        atom_backbone_feat = feats["atom_backbone_feat"][
            0
        ]  # (atoms, num_classes) - one-hot encoded
        atom_pad_mask = feats["atom_pad_mask"][0].bool()  # (atoms,)

        num_tokens = atom_to_token.shape[1]
        device = template_mask.device

        # Convert one-hot encoded backbone_feat to integer indices
        # atom_backbone_feat is one-hot: (atoms, num_classes)
        # N atom: index 1 (1-based, N is index 0 -> 1)
        # CA atom: index 2 (1-based, CA is index 1 -> 2)
        # C atom: index 3 (1-based, C is index 2 -> 3)
        if atom_backbone_feat.dim() > 1:
            # One-hot encoded: convert to integer indices
            backbone_feat_indices = atom_backbone_feat.argmax(dim=-1)  # (atoms,)
        else:
            # Already integer indices
            backbone_feat_indices = atom_backbone_feat.long()

        # Get residue-level template mask (residue has template if any atom has template)
        residue_has_template = torch.zeros(num_tokens, dtype=torch.bool, device=device)
        for token_idx in range(num_tokens):
            token_atoms = atom_to_token[:, token_idx].bool()
            if token_atoms.any():
                residue_has_template[token_idx] = template_mask[token_atoms].any()

        # Find boundary residues: consecutive residues with different template status
        boundary_residues = set()
        for token_idx in range(num_tokens - 1):
            if residue_has_template[token_idx] != residue_has_template[token_idx + 1]:
                # This is a boundary
                # Add the inpainting target residue (the one without template)
                if not residue_has_template[token_idx]:
                    boundary_residues.add(token_idx)
                if not residue_has_template[token_idx + 1]:
                    boundary_residues.add(token_idx + 1)

        # Find CA-C pairs within boundary inpainting residues
        ca_c_pairs = []
        for token_idx in boundary_residues:
            # Get atoms in this residue
            token_atoms = atom_to_token[:, token_idx].bool() & atom_pad_mask

            # Find CA atom (backbone_feat == 2)
            ca_atoms = torch.where(token_atoms & (backbone_feat_indices == 2))[0]
            # Find C atom (backbone_feat == 3)
            c_atoms = torch.where(token_atoms & (backbone_feat_indices == 3))[0]

            if len(ca_atoms) > 0 and len(c_atoms) > 0:
                # Use first matching atom (should typically be only one)
                ca_atom = ca_atoms[0]
                c_atom = c_atoms[0]
                ca_c_pairs.append((ca_atom.item(), c_atom.item(), token_idx))

        return ca_c_pairs

    def compute_args(self, feats, parameters):
        # Check if inpainting is enabled
        if (
            "inpainting_template_mask" not in feats
            or feats["inpainting_template_mask"] is None
        ):
            self.ca_c_pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._cache_valid = False
            return self.last_index, None, None, None, None

        if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
            self.ca_c_pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._cache_valid = False
            return self.last_index, None, None, None, None

        device = feats["inpainting_template_mask"][0].device

        # Use cached pairs if available and device matches
        if not self._cache_valid or self._cached_device != device:
            # Find boundary inpainting residues and their CA-C pairs
            ca_c_pairs = self._find_boundary_inpainting_residues(feats)
            self.ca_c_pairs = ca_c_pairs
            self._cache_valid = True
            self._cached_device = device

            # Log initial CA-C distances only when first finding pairs
            if (
                len(ca_c_pairs) > 0
                and "inpainting_template_coords" in feats
                and feats["inpainting_template_coords"] is not None
            ):
                template_mask = feats["inpainting_template_mask"][0]
                template_coords = feats["inpainting_template_coords"][0]  # (atoms, 3)
                print(
                    f"[InpaintingBoundaryCACDistance] Found {len(ca_c_pairs)} CA-C pairs in boundary inpainting residues (cached):"
                )
                for i, pair in enumerate(ca_c_pairs):
                    ca_idx, c_idx, res_idx = pair
                    ca_coord = (
                        template_coords[ca_idx] if template_mask[ca_idx] else None
                    )
                    c_coord = template_coords[c_idx] if template_mask[c_idx] else None
                    ca_is_template = (
                        template_mask[ca_idx].item()
                        if ca_idx < len(template_mask)
                        else False
                    )
                    c_is_template = (
                        template_mask[c_idx].item()
                        if c_idx < len(template_mask)
                        else False
                    )
                    if ca_coord is not None and c_coord is not None:
                        dist = torch.linalg.norm(ca_coord - c_coord).item()
                        print(
                            f"  Res{res_idx+1}: CA atom {ca_idx} (template={ca_is_template}), C atom {c_idx} (template={c_is_template}), initial CA-C dist={dist:.3f}Å"
                        )
                    else:
                        print(
                            f"  Res{res_idx+1}: CA atom {ca_idx} (template={ca_is_template}), C atom {c_idx} (template={c_is_template}), (one or both atoms need inpainting)"
                        )
        else:
            # Use cached pairs
            ca_c_pairs = self.ca_c_pairs

        if len(ca_c_pairs) == 0:
            self.last_index = torch.empty([2, 0], dtype=torch.long, device=device)
            return self.last_index, None, None, None, None

        # Create index tensor for CA-C distance potential
        ca_indices = torch.tensor(
            [pair[0] for pair in ca_c_pairs], dtype=torch.long, device=device
        )
        c_indices = torch.tensor(
            [pair[1] for pair in ca_c_pairs], dtype=torch.long, device=device
        )
        index = torch.stack([ca_indices, c_indices], dim=0)  # (2, num_pairs)
        self.last_index = index

        # Set target distance for CA-C to 1.53Å with some tolerance
        target_distance = (
            parameters.get("target_distance", 1.53) if parameters else 1.53
        )
        tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1

        # Use base k value
        base_k = parameters.get("k", 20.0) if parameters else 20.0
        k = torch.ones(index.shape[1], device=device, dtype=torch.float32) * base_k

        lower_bounds = torch.full(
            (index.shape[1],),
            target_distance - tolerance,
            device=device,
            dtype=torch.float32,
        )
        upper_bounds = torch.full(
            (index.shape[1],),
            target_distance + tolerance,
            device=device,
            dtype=torch.float32,
        )

        return index, (k, lower_bounds, upper_bounds), None, None, None

    def compute_gradient(self, coords, feats, parameters):
        """Override compute_gradient to mask template atoms."""
        result = super().compute_gradient(coords, feats, parameters)

        # Get template mask before masking
        template_mask = None
        if (
            "inpainting_template_mask" in feats
            and feats["inpainting_template_mask"] is not None
        ):
            template_mask = feats["inpainting_template_mask"][0]  # (atoms,)

        # Log distances and gradients periodically
        if (
            len(self.ca_c_pairs) > 0
            and self.last_index is not None
            and self.last_index.shape[1] > 0
        ):
            # Use step_idx from parameters if available (from diffusionv2.py), otherwise use step_count
            step_idx = parameters.get("step_idx", None) if parameters else None
            is_last_guidance_step = (
                parameters.get("is_last_guidance_step", True) if parameters else True
            )

            if step_idx is not None:
                # Use step_idx directly from diffusion module
                current_step = step_idx
            else:
                # Fallback to step_count for backward compatibility
                self.step_count += 1
                current_step = self.step_count

            log_interval = self.log_interval
            if parameters is not None:
                log_interval = parameters.get("log_interval", self.log_interval)

            # Only log on the last guidance_step of each diffusion step to avoid duplicate logs
            # (same step_idx can have multiple guidance_steps)
            # Also log on the last step if explicitly requested
            is_last_step = (
                parameters.get("is_last_step", False) if parameters else False
            )
            if (
                current_step % log_interval == 0 or is_last_step
            ) and is_last_guidance_step:
                # Get current CA-C distances
                ca_coords = coords[0, self.last_index[0], :]
                c_coords = coords[0, self.last_index[1], :]
                distances = torch.linalg.norm(ca_coords - c_coords, dim=-1)

                # Get gradient magnitudes
                guidance_weight = (
                    parameters.get("guidance_weight", 1.0) if parameters else 1.0
                )
                ca_grad_raw = result[0, self.last_index[0], :]  # (num_pairs, 3)
                c_grad_raw = result[0, self.last_index[1], :]  # (num_pairs, 3)
                ca_grad_mags = torch.linalg.norm(ca_grad_raw, dim=-1)
                c_grad_mags = torch.linalg.norm(c_grad_raw, dim=-1)

                # Log distances and gradients
                distances_list = distances.cpu().tolist()
                ca_grad_list = (ca_grad_mags * guidance_weight).cpu().tolist()
                c_grad_list = (c_grad_mags * guidance_weight).cpu().tolist()

                pairs_info = []
                for i, pair in enumerate(self.ca_c_pairs):
                    res_idx = pair[2]  # token_idx
                    dist_curr = distances_list[i]
                    ca_grad = ca_grad_list[i]
                    c_grad = c_grad_list[i]
                    ca_is_template = (
                        template_mask[self.last_index[0, i]].item()
                        if template_mask is not None
                        else False
                    )
                    c_is_template = (
                        template_mask[self.last_index[1, i]].item()
                        if template_mask is not None
                        else False
                    )
                    target_dist = (
                        parameters.get("target_distance", 1.53) if parameters else 1.53
                    )
                    info = f"Res{res_idx+1}: CA-C={dist_curr:.3f}Å (target={target_dist:.2f}Å, CA_tmpl={ca_is_template}, C_tmpl={c_is_template}), grad_CA={ca_grad:.4f}, grad_C={c_grad:.4f}"
                    pairs_info.append(info)

                print(
                    f"[InpaintingBoundaryCACDistance] Step {current_step}: {len(pairs_info)} CA-C pairs"
                )
                for info in pairs_info:
                    print(f"  {info}")

        # Mask gradient for template atoms (they should not be moved)
        if template_mask is not None:
            result[0, template_mask, :] = 0.0

        return result


class InpaintingBoundaryNCADistancePotential(FlatBottomPotential, DistancePotential):
    """Potential to constrain N-CA distance to ~1.46Å within inpainting target residues at boundaries.

    This potential identifies inpainting target residues (those without template) at boundaries
    and applies a distance constraint on the N-CA bond within each residue.
    """

    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.log_interval = 1  # Log every N steps
        self.step_count = 0
        self.n_ca_pairs = []  # List of (n_atom_idx, ca_atom_idx, token_idx)
        self.last_index = None
        self._cache_valid = False  # Cache flag
        self._cached_device = None

    def _find_boundary_inpainting_residues(self, feats):
        """Find inpainting target residues at boundaries and their N-CA pairs."""
        # Check if inpainting is enabled
        if (
            "inpainting_template_mask" not in feats
            or feats["inpainting_template_mask"] is None
        ):
            return []

        if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
            return []

        template_mask = feats["inpainting_template_mask"][0]  # (atoms,)
        atom_to_token = feats["atom_to_token"][0]  # (atoms, tokens)
        atom_backbone_feat = feats["atom_backbone_feat"][
            0
        ]  # (atoms, num_classes) - one-hot encoded
        atom_pad_mask = feats["atom_pad_mask"][0].bool()  # (atoms,)

        num_tokens = atom_to_token.shape[1]
        device = template_mask.device

        # Convert one-hot encoded backbone_feat to integer indices
        # atom_backbone_feat is one-hot: (atoms, num_classes)
        # N atom: index 1 (1-based, N is index 0 -> 1)
        # CA atom: index 2 (1-based, CA is index 1 -> 2)
        # C atom: index 3 (1-based, C is index 2 -> 3)
        if atom_backbone_feat.dim() > 1:
            # One-hot encoded: convert to integer indices
            backbone_feat_indices = atom_backbone_feat.argmax(dim=-1)  # (atoms,)
        else:
            # Already integer indices
            backbone_feat_indices = atom_backbone_feat.long()

        # Get residue-level template mask (residue has template if any atom has template)
        residue_has_template = torch.zeros(num_tokens, dtype=torch.bool, device=device)
        for token_idx in range(num_tokens):
            token_atoms = atom_to_token[:, token_idx].bool()
            if token_atoms.any():
                residue_has_template[token_idx] = template_mask[token_atoms].any()

        # Find boundary residues: consecutive residues with different template status
        boundary_residues = set()
        for token_idx in range(num_tokens - 1):
            if residue_has_template[token_idx] != residue_has_template[token_idx + 1]:
                # This is a boundary
                # Add the inpainting target residue (the one without template)
                if not residue_has_template[token_idx]:
                    boundary_residues.add(token_idx)
                if not residue_has_template[token_idx + 1]:
                    boundary_residues.add(token_idx + 1)

        # Find N-CA pairs within boundary inpainting residues
        n_ca_pairs = []
        for token_idx in boundary_residues:
            # Get atoms in this residue
            token_atoms = atom_to_token[:, token_idx].bool() & atom_pad_mask

            # Find N atom (backbone_feat == 1)
            n_atoms = torch.where(token_atoms & (backbone_feat_indices == 1))[0]
            # Find CA atom (backbone_feat == 2)
            ca_atoms = torch.where(token_atoms & (backbone_feat_indices == 2))[0]

            if len(n_atoms) > 0 and len(ca_atoms) > 0:
                # Use first matching atom (should typically be only one)
                n_atom = n_atoms[0]
                ca_atom = ca_atoms[0]
                n_ca_pairs.append((n_atom.item(), ca_atom.item(), token_idx))

        return n_ca_pairs


# Shared helper functions for inpainting potentials
def _get_inpainting_target_residues(
    feats, include_boundary=True, include_internal=True
):
    """Get all inpainting target residues (those without template).

    Args:
        feats: Feature dictionary
        include_boundary: If True, include residues at boundaries
        include_internal: If True, include internal residues (not at boundaries)

    Returns:
        tuple: (inpainting_residues_set, residue_has_template, backbone_feat_indices,
                atom_to_token, atom_pad_mask, device)
    """
    if (
        "inpainting_template_mask" not in feats
        or feats["inpainting_template_mask"] is None
    ):
        return set(), None, None, None, None, None

    if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
        return set(), None, None, None, None, None

    template_mask = feats["inpainting_template_mask"][0]  # (atoms,)
    atom_to_token = feats["atom_to_token"][0]  # (atoms, tokens)
    atom_backbone_feat = feats["atom_backbone_feat"][
        0
    ]  # (atoms, num_classes) - one-hot encoded
    atom_pad_mask = feats["atom_pad_mask"][0].bool()  # (atoms,)

    num_tokens = atom_to_token.shape[1]
    device = template_mask.device

    # Convert one-hot encoded backbone_feat to integer indices
    if atom_backbone_feat.dim() > 1:
        backbone_feat_indices = atom_backbone_feat.argmax(dim=-1)  # (atoms,)
    else:
        backbone_feat_indices = atom_backbone_feat.long()

    # Get residue-level template mask
    residue_has_template = torch.zeros(num_tokens, dtype=torch.bool, device=device)
    for token_idx in range(num_tokens):
        token_atoms = atom_to_token[:, token_idx].bool()
        if token_atoms.any():
            residue_has_template[token_idx] = template_mask[token_atoms].any()

    # Find all inpainting target residues (those without template)
    inpainting_residues = set()
    for token_idx in range(num_tokens):
        if not residue_has_template[token_idx]:
            # Check if it's a boundary residue
            is_boundary = False
            if token_idx > 0 and residue_has_template[token_idx - 1]:
                is_boundary = True
            if token_idx < num_tokens - 1 and residue_has_template[token_idx + 1]:
                is_boundary = True

            if (include_boundary and is_boundary) or (
                include_internal and not is_boundary
            ):
                inpainting_residues.add(token_idx)

    return (
        inpainting_residues,
        residue_has_template,
        backbone_feat_indices,
        atom_to_token,
        atom_pad_mask,
        device,
    )


def _find_atom_pairs_in_residues(
    inpainting_residues,
    atom_to_token,
    atom_pad_mask,
    backbone_feat_indices,
    atom_type1,
    atom_type2,
):
    """Find atom pairs of specified types within given residues.

    Args:
        inpainting_residues: Set of token indices
        atom_to_token: (atoms, tokens) mapping
        atom_pad_mask: (atoms,) boolean mask
        backbone_feat_indices: (atoms,) integer indices for backbone atoms
        atom_type1: Integer index for first atom type (e.g., 1 for N, 2 for CA, 3 for C)
        atom_type2: Integer index for second atom type

    Returns:
        List of tuples: (atom1_idx, atom2_idx, token_idx)
    """
    pairs = []
    for token_idx in inpainting_residues:
        token_atoms = atom_to_token[:, token_idx].bool() & atom_pad_mask

        atoms1 = torch.where(token_atoms & (backbone_feat_indices == atom_type1))[0]
        atoms2 = torch.where(token_atoms & (backbone_feat_indices == atom_type2))[0]

        if len(atoms1) > 0 and len(atoms2) > 0:
            pairs.append((atoms1[0].item(), atoms2[0].item(), token_idx))

    return pairs


def _find_peptide_bond_pairs(
    inpainting_residues,
    atom_to_token,
    atom_pad_mask,
    backbone_feat_indices,
    residue_has_template,
):
    """Find C-N peptide bond pairs between consecutive residues in inpainting regions.

    Includes both internal bonds (both residues are inpainting) and boundary bonds
    (one residue is inpainting, the other has template).

    Args:
        inpainting_residues: Set of token indices
        atom_to_token: (atoms, tokens) mapping
        atom_pad_mask: (atoms,) boolean mask
        backbone_feat_indices: (atoms,) integer indices
        residue_has_template: (num_tokens,) boolean mask

    Returns:
        List of tuples: (c_atom_idx, n_atom_idx, token_i, token_i1)
    """
    pairs = []
    sorted_residues = sorted(inpainting_residues)
    num_tokens = residue_has_template.shape[0]
    pairs_set = set()  # To avoid duplicates

    for token_idx in sorted_residues:
        # Check peptide bond to next residue (token_idx -> token_idx + 1)
        if token_idx + 1 < num_tokens:
            # Include if:
            # 1. Both residues are inpainting (internal bond), OR
            # 2. Current residue is inpainting and next has template (boundary bond)
            next_is_inpainting = (token_idx + 1) in inpainting_residues
            next_has_template = residue_has_template[token_idx + 1].item()

            if next_is_inpainting or next_has_template:
                token_i_atoms = atom_to_token[:, token_idx].bool() & atom_pad_mask
                token_i1_atoms = atom_to_token[:, token_idx + 1].bool() & atom_pad_mask

                c_atoms = torch.where(token_i_atoms & (backbone_feat_indices == 3))[0]
                n_atoms = torch.where(token_i1_atoms & (backbone_feat_indices == 1))[0]

                if len(c_atoms) > 0 and len(n_atoms) > 0:
                    pair_key = (token_idx, token_idx + 1)
                    if pair_key not in pairs_set:
                        pairs.append(
                            (c_atoms[0].item(), n_atoms[0].item(), token_idx, token_idx + 1)
                        )
                        pairs_set.add(pair_key)

        # Also check peptide bond from previous residue (token_idx - 1 -> token_idx)
        # This catches boundary bonds where template -> inpainting
        if token_idx > 0:
            prev_has_template = residue_has_template[token_idx - 1].item()
            prev_is_inpainting = (token_idx - 1) in inpainting_residues

            # Include if previous residue has template and current is inpainting (boundary bond)
            if prev_has_template and not prev_is_inpainting:
                token_prev_atoms = atom_to_token[:, token_idx - 1].bool() & atom_pad_mask
                token_i_atoms = atom_to_token[:, token_idx].bool() & atom_pad_mask

                c_atoms = torch.where(token_prev_atoms & (backbone_feat_indices == 3))[0]
                n_atoms = torch.where(token_i_atoms & (backbone_feat_indices == 1))[0]

                if len(c_atoms) > 0 and len(n_atoms) > 0:
                    pair_key = (token_idx - 1, token_idx)
                    if pair_key not in pairs_set:
                        pairs.append(
                            (c_atoms[0].item(), n_atoms[0].item(), token_idx - 1, token_idx)
                        )
                        pairs_set.add(pair_key)

    return pairs


class InpaintingBoundaryNCADistancePotential(FlatBottomPotential, DistancePotential):
    """Potential to constrain N-CA distance to ~1.46Å within inpainting target residues at boundaries.

    This potential identifies inpainting target residues (those without template) at boundaries
    and applies a distance constraint on the N-CA bond within each residue.
    """

    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.log_interval = 1  # Log every N steps
        self.step_count = 0
        self.n_ca_pairs = []  # List of (n_atom_idx, ca_atom_idx, token_idx)
        self.last_index = None
        self._cache_valid = False  # Cache flag
        self._cached_device = None

    def _find_boundary_inpainting_residues(self, feats):
        """Find inpainting target residues at boundaries and their N-CA pairs."""
        # Check if inpainting is enabled
        if (
            "inpainting_template_mask" not in feats
            or feats["inpainting_template_mask"] is None
        ):
            return []

        if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
            return []

        template_mask = feats["inpainting_template_mask"][0]  # (atoms,)
        atom_to_token = feats["atom_to_token"][0]  # (atoms, tokens)
        atom_backbone_feat = feats["atom_backbone_feat"][
            0
        ]  # (atoms, num_classes) - one-hot encoded
        atom_pad_mask = feats["atom_pad_mask"][0].bool()  # (atoms,)

        num_tokens = atom_to_token.shape[1]
        device = template_mask.device

        # Convert one-hot encoded backbone_feat to integer indices
        # atom_backbone_feat is one-hot: (atoms, num_classes)
        # N atom: index 1 (1-based, N is index 0 -> 1)
        # CA atom: index 2 (1-based, CA is index 1 -> 2)
        # C atom: index 3 (1-based, C is index 2 -> 3)
        if atom_backbone_feat.dim() > 1:
            # One-hot encoded: convert to integer indices
            backbone_feat_indices = atom_backbone_feat.argmax(dim=-1)  # (atoms,)
        else:
            # Already integer indices
            backbone_feat_indices = atom_backbone_feat.long()

        # Get residue-level template mask (residue has template if any atom has template)
        residue_has_template = torch.zeros(num_tokens, dtype=torch.bool, device=device)
        for token_idx in range(num_tokens):
            token_atoms = atom_to_token[:, token_idx].bool()
            if token_atoms.any():
                residue_has_template[token_idx] = template_mask[token_atoms].any()

        # Find boundary residues: consecutive residues with different template status
        boundary_residues = set()
        for token_idx in range(num_tokens - 1):
            if residue_has_template[token_idx] != residue_has_template[token_idx + 1]:
                # This is a boundary
                # Add the inpainting target residue (the one without template)
                if not residue_has_template[token_idx]:
                    boundary_residues.add(token_idx)
                if not residue_has_template[token_idx + 1]:
                    boundary_residues.add(token_idx + 1)

        # Find N-CA pairs within boundary inpainting residues
        n_ca_pairs = []
        for token_idx in boundary_residues:
            # Get atoms in this residue
            token_atoms = atom_to_token[:, token_idx].bool() & atom_pad_mask

            # Find N atom (backbone_feat == 1)
            n_atoms = torch.where(token_atoms & (backbone_feat_indices == 1))[0]
            # Find CA atom (backbone_feat == 2)
            ca_atoms = torch.where(token_atoms & (backbone_feat_indices == 2))[0]

            if len(n_atoms) > 0 and len(ca_atoms) > 0:
                # Use first matching atom (should typically be only one)
                n_atom = n_atoms[0]
                ca_atom = ca_atoms[0]
                n_ca_pairs.append((n_atom.item(), ca_atom.item(), token_idx))

        return n_ca_pairs

    def compute_args(self, feats, parameters):
        # Check if inpainting is enabled
        if (
            "inpainting_template_mask" not in feats
            or feats["inpainting_template_mask"] is None
        ):
            self.n_ca_pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._cache_valid = False
            return self.last_index, None, None, None, None

        if "atom_to_token" not in feats or "atom_backbone_feat" not in feats:
            self.n_ca_pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._cache_valid = False
            return self.last_index, None, None, None, None

        device = feats["inpainting_template_mask"][0].device

        # Use cached pairs if available and device matches
        if not self._cache_valid or self._cached_device != device:
            # Find boundary inpainting residues and their N-CA pairs
            n_ca_pairs = self._find_boundary_inpainting_residues(feats)
            self.n_ca_pairs = n_ca_pairs
            self._cache_valid = True
            self._cached_device = device

            # Log initial N-CA distances only when first finding pairs
            if (
                len(n_ca_pairs) > 0
                and "inpainting_template_coords" in feats
                and feats["inpainting_template_coords"] is not None
            ):
                template_mask = feats["inpainting_template_mask"][0]
                template_coords = feats["inpainting_template_coords"][0]  # (atoms, 3)
                print(
                    f"[InpaintingBoundaryNCADistance] Found {len(n_ca_pairs)} N-CA pairs in boundary inpainting residues (cached):"
                )
                for i, pair in enumerate(n_ca_pairs):
                    n_idx, ca_idx, res_idx = pair
                    n_coord = template_coords[n_idx] if template_mask[n_idx] else None
                    ca_coord = (
                        template_coords[ca_idx] if template_mask[ca_idx] else None
                    )
                    n_is_template = (
                        template_mask[n_idx].item()
                        if n_idx < len(template_mask)
                        else False
                    )
                    ca_is_template = (
                        template_mask[ca_idx].item()
                        if ca_idx < len(template_mask)
                        else False
                    )
                    if n_coord is not None and ca_coord is not None:
                        dist = torch.linalg.norm(n_coord - ca_coord).item()
                        print(
                            f"  Res{res_idx+1}: N atom {n_idx} (template={n_is_template}), CA atom {ca_idx} (template={ca_is_template}), initial N-CA dist={dist:.3f}Å"
                        )
                    else:
                        print(
                            f"  Res{res_idx+1}: N atom {n_idx} (template={n_is_template}), CA atom {ca_idx} (template={ca_is_template}), (one or both atoms need inpainting)"
                        )
        else:
            # Use cached pairs
            n_ca_pairs = self.n_ca_pairs

        if len(n_ca_pairs) == 0:
            self.last_index = torch.empty([2, 0], dtype=torch.long, device=device)
            return self.last_index, None, None, None, None

        # Create index tensor for N-CA distance potential
        n_indices = torch.tensor(
            [pair[0] for pair in n_ca_pairs], dtype=torch.long, device=device
        )
        ca_indices = torch.tensor(
            [pair[1] for pair in n_ca_pairs], dtype=torch.long, device=device
        )
        index = torch.stack([n_indices, ca_indices], dim=0)  # (2, num_pairs)
        self.last_index = index

        # Set target distance for N-CA to 1.46Å with some tolerance
        target_distance = (
            parameters.get("target_distance", 1.46) if parameters else 1.46
        )
        tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1

        # Use base k value
        base_k = parameters.get("k", 20.0) if parameters else 20.0
        k = torch.ones(index.shape[1], device=device, dtype=torch.float32) * base_k

        lower_bounds = torch.full(
            (index.shape[1],),
            target_distance - tolerance,
            device=device,
            dtype=torch.float32,
        )
        upper_bounds = torch.full(
            (index.shape[1],),
            target_distance + tolerance,
            device=device,
            dtype=torch.float32,
        )

        return index, (k, lower_bounds, upper_bounds), None, None, None

    def compute_gradient(self, coords, feats, parameters):
        """Override compute_gradient to mask template atoms."""
        result = super().compute_gradient(coords, feats, parameters)

        # Get template mask before masking
        template_mask = None
        if (
            "inpainting_template_mask" in feats
            and feats["inpainting_template_mask"] is not None
        ):
            template_mask = feats["inpainting_template_mask"][0]  # (atoms,)

        # Log distances and gradients periodically
        if (
            len(self.n_ca_pairs) > 0
            and self.last_index is not None
            and self.last_index.shape[1] > 0
        ):
            # Use step_idx from parameters if available (from diffusionv2.py), otherwise use step_count
            step_idx = parameters.get("step_idx", None) if parameters else None
            is_last_guidance_step = (
                parameters.get("is_last_guidance_step", True) if parameters else True
            )

            if step_idx is not None:
                # Use step_idx directly from diffusion module
                current_step = step_idx
            else:
                # Fallback to step_count for backward compatibility
                self.step_count += 1
                current_step = self.step_count

            log_interval = self.log_interval
            if parameters is not None:
                log_interval = parameters.get("log_interval", self.log_interval)

            # Only log on the last guidance_step of each diffusion step to avoid duplicate logs
            # (same step_idx can have multiple guidance_steps)
            # Also log on the last step if explicitly requested
            is_last_step = (
                parameters.get("is_last_step", False) if parameters else False
            )
            if (
                current_step % log_interval == 0 or is_last_step
            ) and is_last_guidance_step:
                # Get current N-CA distances
                n_coords = coords[0, self.last_index[0], :]
                ca_coords = coords[0, self.last_index[1], :]
                distances = torch.linalg.norm(n_coords - ca_coords, dim=-1)

                # Get gradient magnitudes
                guidance_weight = (
                    parameters.get("guidance_weight", 1.0) if parameters else 1.0
                )
                n_grad_raw = result[0, self.last_index[0], :]  # (num_pairs, 3)
                ca_grad_raw = result[0, self.last_index[1], :]  # (num_pairs, 3)
                n_grad_mags = torch.linalg.norm(n_grad_raw, dim=-1)
                ca_grad_mags = torch.linalg.norm(ca_grad_raw, dim=-1)

                # Log distances and gradients
                distances_list = distances.cpu().tolist()
                n_grad_list = (n_grad_mags * guidance_weight).cpu().tolist()
                ca_grad_list = (ca_grad_mags * guidance_weight).cpu().tolist()

                pairs_info = []
                for i, pair in enumerate(self.n_ca_pairs):
                    res_idx = pair[2]  # token_idx
                    dist_curr = distances_list[i]
                    n_grad = n_grad_list[i]
                    ca_grad = ca_grad_list[i]
                    n_is_template = (
                        template_mask[self.last_index[0, i]].item()
                        if template_mask is not None
                        else False
                    )
                    ca_is_template = (
                        template_mask[self.last_index[1, i]].item()
                        if template_mask is not None
                        else False
                    )
                    target_dist = (
                        parameters.get("target_distance", 1.46) if parameters else 1.46
                    )
                    info = f"Res{res_idx+1}: N-CA={dist_curr:.3f}Å (target={target_dist:.2f}Å, N_tmpl={n_is_template}, CA_tmpl={ca_is_template}), grad_N={n_grad:.4f}, grad_CA={ca_grad:.4f}"
                    pairs_info.append(info)

                print(
                    f"[InpaintingBoundaryNCADistance] Step {current_step}: {len(pairs_info)} N-CA pairs"
                )
                for info in pairs_info:
                    print(f"  {info}")

        # Mask gradient for template atoms (they should not be moved)
        if template_mask is not None:
            result[0, template_mask, :] = 0.0

        return result


# New classes for internal + boundary inpainting potentials (using shared helpers)
class InpaintingPeptideBondPotential(FlatBottomPotential, DistancePotential):
    """Potential to constrain peptide bond (C-N) distances to ~1.3Å in all inpainting target residues.

    This potential applies to both boundary and internal inpainting residues.
    """

    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.log_interval = 10
        self.step_count = 0
        self.pairs = []
        self.last_index = None
        self._cache_valid = False
        self._cached_device = None

    def compute_args(self, feats, parameters):
        (
            inpainting_residues,
            residue_has_template,
            backbone_feat_indices,
            atom_to_token,
            atom_pad_mask,
            device,
        ) = _get_inpainting_target_residues(
            feats, include_boundary=True, include_internal=True
        )

        if device is None or len(inpainting_residues) == 0:
            self.pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._cache_valid = False
            return self.last_index, None, None, None, None

        if not self._cache_valid or self._cached_device != device:
            pairs = _find_peptide_bond_pairs(
                inpainting_residues,
                atom_to_token,
                atom_pad_mask,
                backbone_feat_indices,
                residue_has_template,
            )
            self.pairs = pairs
            self._cache_valid = True
            self._cached_device = device
        else:
            pairs = self.pairs

        if len(pairs) == 0:
            self.last_index = torch.empty([2, 0], dtype=torch.long, device=device)
            return self.last_index, None, None, None, None

        c_indices = torch.tensor(
            [pair[0] for pair in pairs], dtype=torch.long, device=device
        )
        n_indices = torch.tensor(
            [pair[1] for pair in pairs], dtype=torch.long, device=device
        )
        index = torch.stack([c_indices, n_indices], dim=0)
        self.last_index = index

        target_distance = parameters.get("target_distance", 1.3) if parameters else 1.3
        tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1
        base_k = parameters.get("k", 20.0) if parameters else 20.0
        k = torch.ones(index.shape[1], device=device, dtype=torch.float32) * base_k
        lower_bounds = torch.full(
            (index.shape[1],),
            target_distance - tolerance,
            device=device,
            dtype=torch.float32,
        )
        upper_bounds = torch.full(
            (index.shape[1],),
            target_distance + tolerance,
            device=device,
            dtype=torch.float32,
        )

        return index, (k, lower_bounds, upper_bounds), None, None, None

    def compute_gradient(self, coords, feats, parameters):
        result = super().compute_gradient(coords, feats, parameters)

        template_mask = None
        if (
            "inpainting_template_mask" in feats
            and feats["inpainting_template_mask"] is not None
        ):
            template_mask = feats["inpainting_template_mask"][0]

        # Comprehensive logging
        if (
            len(self.pairs) > 0
            and self.last_index is not None
            and self.last_index.shape[1] > 0
        ):
            step_idx = parameters.get("step_idx", None) if parameters else None
            is_last_guidance_step = (
                parameters.get("is_last_guidance_step", True) if parameters else True
            )

            if step_idx is not None:
                current_step = step_idx
            else:
                self.step_count += 1
                current_step = self.step_count

            log_interval = (
                parameters.get("log_interval", self.log_interval)
                if parameters
                else self.log_interval
            )
            is_last_step = (
                parameters.get("is_last_step", False) if parameters else False
            )

            if (
                current_step % log_interval == 0 or is_last_step
            ) and is_last_guidance_step:
                # Get current distances
                c_coords = coords[0, self.last_index[0], :]
                n_coords = coords[0, self.last_index[1], :]
                distances = torch.linalg.norm(c_coords - n_coords, dim=-1)

                # Get parameters
                target_distance = (
                    parameters.get("target_distance", 1.3) if parameters else 1.3
                )
                tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1
                guidance_weight = (
                    parameters.get("guidance_weight", 1.0) if parameters else 1.0
                )
                lower_bound = target_distance - tolerance
                upper_bound = target_distance + tolerance

                # Condition satisfaction statistics
                in_range = (distances >= lower_bound) & (distances <= upper_bound)
                too_close = distances < lower_bound
                too_far = distances > upper_bound
                num_satisfied = in_range.sum().item()
                num_too_close = too_close.sum().item()
                num_too_far = too_far.sum().item()
                total_pairs = len(distances)

                # Get gradients
                c_grad = result[0, self.last_index[0], :]  # (num_pairs, 3)
                n_grad = result[0, self.last_index[1], :]  # (num_pairs, 3)
                c_grad_mags = torch.linalg.norm(c_grad, dim=-1) * guidance_weight
                n_grad_mags = torch.linalg.norm(n_grad, dim=-1) * guidance_weight

                # Gradient direction analysis
                c_to_n = n_coords - c_coords  # (num_pairs, 3)
                c_to_n_unit = c_to_n / (
                    torch.linalg.norm(c_to_n, dim=-1, keepdim=True) + 1e-8
                )
                c_grad_dot = (c_grad * c_to_n_unit).sum(dim=-1) * guidance_weight
                n_grad_dot = (n_grad * (-c_to_n_unit)).sum(dim=-1) * guidance_weight

                # Find worst violations (furthest from target)
                violations = torch.abs(distances - target_distance)
                violations[in_range] = (
                    -1
                )  # Mark satisfied ones as -1 so they won't be selected
                worst_indices = torch.topk(violations, min(10, total_pairs)).indices

                # Log summary
                print(
                    f"[InpaintingPeptideBond] Step {current_step}: {total_pairs} C-N pairs"
                )
                print(
                    f"  Condition: {num_satisfied}/{total_pairs} satisfied ({100*num_satisfied/total_pairs:.1f}%), "
                    f"{num_too_close} too close, {num_too_far} too far"
                )
                print(
                    f"  Distance: mean={distances.mean().item():.3f}Å, "
                    f"min={distances.min().item():.3f}Å, max={distances.max().item():.3f}Å, "
                    f"target={target_distance:.2f}±{tolerance:.2f}Å"
                )
                print(
                    f"  Gradient: C mean={c_grad_mags.mean().item():.4f}, max={c_grad_mags.max().item():.4f}, "
                    f"N mean={n_grad_mags.mean().item():.4f}, max={n_grad_mags.max().item():.4f}"
                )
                print(
                    f"  Gradient direction: C→N dot mean={c_grad_dot.mean().item():+.4f}, "
                    f"N→C dot mean={n_grad_dot.mean().item():+.4f} "
                    f"(positive=push apart, negative=pull together)"
                )

                # Log top violations
                if len(worst_indices) > 0:
                    print(f"  Top {len(worst_indices)} violations:")
                    for i, idx in enumerate(worst_indices):
                        if violations[idx] >= 0:  # Only log actual violations
                            pair = self.pairs[idx]
                            res_i, res_i1 = pair[2], pair[3]
                            dist = distances[idx].item()
                            c_grad_mag = c_grad_mags[idx].item()
                            n_grad_mag = n_grad_mags[idx].item()
                            c_dot = c_grad_dot[idx].item()
                            n_dot = n_grad_dot[idx].item()
                            status = "too_close" if dist < lower_bound else "too_far"
                            print(
                                f"    #{i+1} Res{res_i+1}-Res{res_i1+1}: dist={dist:.3f}Å "
                                f"({status}, target={target_distance:.2f}±{tolerance:.2f}Å), "
                                f"grad_C={c_grad_mag:.4f} (dot={c_dot:+.4f}), "
                                f"grad_N={n_grad_mag:.4f} (dot={n_dot:+.4f})"
                            )

        if template_mask is not None:
            result[0, template_mask, :] = 0.0

        return result


class InpaintingCACDistancePotential(FlatBottomPotential, DistancePotential):
    """Potential to constrain CA-C distance to ~1.53Å in all inpainting target residues.

    This potential applies to both boundary and internal inpainting residues.
    """

    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.log_interval = 1
        self.step_count = 0
        self.pairs = []
        self.last_index = None
        self._cache_valid = False
        self._cached_device = None

    def compute_args(self, feats, parameters):
        (
            inpainting_residues,
            _,
            backbone_feat_indices,
            atom_to_token,
            atom_pad_mask,
            device,
        ) = _get_inpainting_target_residues(
            feats, include_boundary=True, include_internal=True
        )

        if device is None or len(inpainting_residues) == 0:
            self.pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._cache_valid = False
            return self.last_index, None, None, None, None

        if not self._cache_valid or self._cached_device != device:
            pairs = _find_atom_pairs_in_residues(
                inpainting_residues,
                atom_to_token,
                atom_pad_mask,
                backbone_feat_indices,
                2,
                3,  # CA=2, C=3
            )
            self.pairs = pairs
            self._cache_valid = True
            self._cached_device = device
        else:
            pairs = self.pairs

        if len(pairs) == 0:
            self.last_index = torch.empty([2, 0], dtype=torch.long, device=device)
            return self.last_index, None, None, None, None

        ca_indices = torch.tensor(
            [pair[0] for pair in pairs], dtype=torch.long, device=device
        )
        c_indices = torch.tensor(
            [pair[1] for pair in pairs], dtype=torch.long, device=device
        )
        index = torch.stack([ca_indices, c_indices], dim=0)
        self.last_index = index

        target_distance = (
            parameters.get("target_distance", 1.53) if parameters else 1.53
        )
        tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1
        base_k = parameters.get("k", 20.0) if parameters else 20.0
        k = torch.ones(index.shape[1], device=device, dtype=torch.float32) * base_k
        lower_bounds = torch.full(
            (index.shape[1],),
            target_distance - tolerance,
            device=device,
            dtype=torch.float32,
        )
        upper_bounds = torch.full(
            (index.shape[1],),
            target_distance + tolerance,
            device=device,
            dtype=torch.float32,
        )

        return index, (k, lower_bounds, upper_bounds), None, None, None

    def compute_gradient(self, coords, feats, parameters):
        result = super().compute_gradient(coords, feats, parameters)

        template_mask = None
        if (
            "inpainting_template_mask" in feats
            and feats["inpainting_template_mask"] is not None
        ):
            template_mask = feats["inpainting_template_mask"][0]

        # Comprehensive logging
        if (
            len(self.pairs) > 0
            and self.last_index is not None
            and self.last_index.shape[1] > 0
        ):
            step_idx = parameters.get("step_idx", None) if parameters else None
            is_last_guidance_step = (
                parameters.get("is_last_guidance_step", True) if parameters else True
            )

            if step_idx is not None:
                current_step = step_idx
            else:
                self.step_count += 1
                current_step = self.step_count

            log_interval = (
                parameters.get("log_interval", self.log_interval)
                if parameters
                else self.log_interval
            )
            is_last_step = (
                parameters.get("is_last_step", False) if parameters else False
            )

            if (
                current_step % log_interval == 0 or is_last_step
            ) and is_last_guidance_step:
                # Get current distances
                ca_coords = coords[0, self.last_index[0], :]
                c_coords = coords[0, self.last_index[1], :]
                distances = torch.linalg.norm(ca_coords - c_coords, dim=-1)

                # Get parameters
                target_distance = (
                    parameters.get("target_distance", 1.53) if parameters else 1.53
                )
                tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1
                guidance_weight = (
                    parameters.get("guidance_weight", 1.0) if parameters else 1.0
                )
                lower_bound = target_distance - tolerance
                upper_bound = target_distance + tolerance

                # Condition satisfaction statistics
                in_range = (distances >= lower_bound) & (distances <= upper_bound)
                too_close = distances < lower_bound
                too_far = distances > upper_bound
                num_satisfied = in_range.sum().item()
                num_too_close = too_close.sum().item()
                num_too_far = too_far.sum().item()
                total_pairs = len(distances)

                # Get gradients
                ca_grad = result[0, self.last_index[0], :]  # (num_pairs, 3)
                c_grad = result[0, self.last_index[1], :]  # (num_pairs, 3)
                ca_grad_mags = torch.linalg.norm(ca_grad, dim=-1) * guidance_weight
                c_grad_mags = torch.linalg.norm(c_grad, dim=-1) * guidance_weight

                # Gradient direction analysis
                ca_to_c = c_coords - ca_coords  # (num_pairs, 3)
                ca_to_c_unit = ca_to_c / (
                    torch.linalg.norm(ca_to_c, dim=-1, keepdim=True) + 1e-8
                )
                ca_grad_dot = (ca_grad * ca_to_c_unit).sum(dim=-1) * guidance_weight
                c_grad_dot = (c_grad * (-ca_to_c_unit)).sum(dim=-1) * guidance_weight

                # Find worst violations (furthest from target)
                violations = torch.abs(distances - target_distance)
                violations[in_range] = (
                    -1
                )  # Mark satisfied ones as -1 so they won't be selected
                worst_indices = torch.topk(violations, min(10, total_pairs)).indices

                # Log summary
                print(
                    f"[InpaintingCACDistance] Step {current_step}: {total_pairs} CA-C pairs"
                )
                print(
                    f"  Condition: {num_satisfied}/{total_pairs} satisfied ({100*num_satisfied/total_pairs:.1f}%), "
                    f"{num_too_close} too close, {num_too_far} too far"
                )
                print(
                    f"  Distance: mean={distances.mean().item():.3f}Å, "
                    f"min={distances.min().item():.3f}Å, max={distances.max().item():.3f}Å, "
                    f"target={target_distance:.2f}±{tolerance:.2f}Å"
                )
                print(
                    f"  Gradient: CA mean={ca_grad_mags.mean().item():.4f}, max={ca_grad_mags.max().item():.4f}, "
                    f"C mean={c_grad_mags.mean().item():.4f}, max={c_grad_mags.max().item():.4f}"
                )
                print(
                    f"  Gradient direction: CA→C dot mean={ca_grad_dot.mean().item():+.4f}, "
                    f"C→CA dot mean={c_grad_dot.mean().item():+.4f} "
                    f"(positive=push apart, negative=pull together)"
                )

                # Log top violations
                if len(worst_indices) > 0:
                    print(f"  Top {len(worst_indices)} violations:")
                    for i, idx in enumerate(worst_indices):
                        if violations[idx] >= 0:  # Only log actual violations
                            pair = self.pairs[idx]
                            res_idx = pair[2]
                            dist = distances[idx].item()
                            ca_grad_mag = ca_grad_mags[idx].item()
                            c_grad_mag = c_grad_mags[idx].item()
                            ca_dot = ca_grad_dot[idx].item()
                            c_dot = c_grad_dot[idx].item()
                            status = "too_close" if dist < lower_bound else "too_far"
                            print(
                                f"    #{i+1} Res{res_idx+1}: dist={dist:.3f}Å "
                                f"({status}, target={target_distance:.2f}±{tolerance:.2f}Å), "
                                f"grad_CA={ca_grad_mag:.4f} (dot={ca_dot:+.4f}), "
                                f"grad_C={c_grad_mag:.4f} (dot={c_dot:+.4f})"
                            )

        if template_mask is not None:
            result[0, template_mask, :] = 0.0

        return result


class InpaintingNCADistancePotential(FlatBottomPotential, DistancePotential):
    """Potential to constrain N-CA distance to ~1.46Å in all inpainting target residues.

    This potential applies to both boundary and internal inpainting residues.
    """

    def __init__(self, parameters=None):
        super().__init__(parameters)
        self.log_interval = 1
        self.step_count = 0
        self.pairs = []
        self.last_index = None
        self._cache_valid = False
        self._cached_device = None

    def compute_args(self, feats, parameters):
        (
            inpainting_residues,
            _,
            backbone_feat_indices,
            atom_to_token,
            atom_pad_mask,
            device,
        ) = _get_inpainting_target_residues(
            feats, include_boundary=True, include_internal=True
        )

        if device is None or len(inpainting_residues) == 0:
            self.pairs = []
            self.last_index = torch.empty(
                [2, 0],
                dtype=torch.long,
                device=feats.get("atom_pad_mask", torch.tensor([])).device,
            )
            self._cache_valid = False
            return self.last_index, None, None, None, None

        if not self._cache_valid or self._cached_device != device:
            pairs = _find_atom_pairs_in_residues(
                inpainting_residues,
                atom_to_token,
                atom_pad_mask,
                backbone_feat_indices,
                1,
                2,  # N=1, CA=2
            )
            self.pairs = pairs
            self._cache_valid = True
            self._cached_device = device
        else:
            pairs = self.pairs

        if len(pairs) == 0:
            self.last_index = torch.empty([2, 0], dtype=torch.long, device=device)
            return self.last_index, None, None, None, None

        n_indices = torch.tensor(
            [pair[0] for pair in pairs], dtype=torch.long, device=device
        )
        ca_indices = torch.tensor(
            [pair[1] for pair in pairs], dtype=torch.long, device=device
        )
        index = torch.stack([n_indices, ca_indices], dim=0)
        self.last_index = index

        target_distance = (
            parameters.get("target_distance", 1.46) if parameters else 1.46
        )
        tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1
        base_k = parameters.get("k", 20.0) if parameters else 20.0
        k = torch.ones(index.shape[1], device=device, dtype=torch.float32) * base_k
        lower_bounds = torch.full(
            (index.shape[1],),
            target_distance - tolerance,
            device=device,
            dtype=torch.float32,
        )
        upper_bounds = torch.full(
            (index.shape[1],),
            target_distance + tolerance,
            device=device,
            dtype=torch.float32,
        )

        return index, (k, lower_bounds, upper_bounds), None, None, None

    def compute_gradient(self, coords, feats, parameters):
        result = super().compute_gradient(coords, feats, parameters)

        template_mask = None
        if (
            "inpainting_template_mask" in feats
            and feats["inpainting_template_mask"] is not None
        ):
            template_mask = feats["inpainting_template_mask"][0]

        # Comprehensive logging
        if (
            len(self.pairs) > 0
            and self.last_index is not None
            and self.last_index.shape[1] > 0
        ):
            step_idx = parameters.get("step_idx", None) if parameters else None
            is_last_guidance_step = (
                parameters.get("is_last_guidance_step", True) if parameters else True
            )

            if step_idx is not None:
                current_step = step_idx
            else:
                self.step_count += 1
                current_step = self.step_count

            log_interval = (
                parameters.get("log_interval", self.log_interval)
                if parameters
                else self.log_interval
            )
            is_last_step = (
                parameters.get("is_last_step", False) if parameters else False
            )

            if (
                current_step % log_interval == 0 or is_last_step
            ) and is_last_guidance_step:
                # Get current distances
                n_coords = coords[0, self.last_index[0], :]
                ca_coords = coords[0, self.last_index[1], :]
                distances = torch.linalg.norm(n_coords - ca_coords, dim=-1)

                # Get parameters
                target_distance = (
                    parameters.get("target_distance", 1.46) if parameters else 1.46
                )
                tolerance = parameters.get("tolerance", 0.1) if parameters else 0.1
                guidance_weight = (
                    parameters.get("guidance_weight", 1.0) if parameters else 1.0
                )
                lower_bound = target_distance - tolerance
                upper_bound = target_distance + tolerance

                # Condition satisfaction statistics
                in_range = (distances >= lower_bound) & (distances <= upper_bound)
                too_close = distances < lower_bound
                too_far = distances > upper_bound
                num_satisfied = in_range.sum().item()
                num_too_close = too_close.sum().item()
                num_too_far = too_far.sum().item()
                total_pairs = len(distances)

                # Get gradients
                n_grad = result[0, self.last_index[0], :]  # (num_pairs, 3)
                ca_grad = result[0, self.last_index[1], :]  # (num_pairs, 3)
                n_grad_mags = torch.linalg.norm(n_grad, dim=-1) * guidance_weight
                ca_grad_mags = torch.linalg.norm(ca_grad, dim=-1) * guidance_weight

                # Gradient direction analysis
                n_to_ca = ca_coords - n_coords  # (num_pairs, 3)
                n_to_ca_unit = n_to_ca / (
                    torch.linalg.norm(n_to_ca, dim=-1, keepdim=True) + 1e-8
                )
                n_grad_dot = (n_grad * n_to_ca_unit).sum(dim=-1) * guidance_weight
                ca_grad_dot = (ca_grad * (-n_to_ca_unit)).sum(dim=-1) * guidance_weight

                # Find worst violations (furthest from target)
                violations = torch.abs(distances - target_distance)
                violations[in_range] = (
                    -1
                )  # Mark satisfied ones as -1 so they won't be selected
                worst_indices = torch.topk(violations, min(10, total_pairs)).indices

                # Log summary
                print(
                    f"[InpaintingNCADistance] Step {current_step}: {total_pairs} N-CA pairs"
                )
                print(
                    f"  Condition: {num_satisfied}/{total_pairs} satisfied ({100*num_satisfied/total_pairs:.1f}%), "
                    f"{num_too_close} too close, {num_too_far} too far"
                )
                print(
                    f"  Distance: mean={distances.mean().item():.3f}Å, "
                    f"min={distances.min().item():.3f}Å, max={distances.max().item():.3f}Å, "
                    f"target={target_distance:.2f}±{tolerance:.2f}Å"
                )
                print(
                    f"  Gradient: N mean={n_grad_mags.mean().item():.4f}, max={n_grad_mags.max().item():.4f}, "
                    f"CA mean={ca_grad_mags.mean().item():.4f}, max={ca_grad_mags.max().item():.4f}"
                )
                print(
                    f"  Gradient direction: N→CA dot mean={n_grad_dot.mean().item():+.4f}, "
                    f"CA→N dot mean={ca_grad_dot.mean().item():+.4f} "
                    f"(positive=push apart, negative=pull together)"
                )

                # Log top violations
                if len(worst_indices) > 0:
                    print(f"  Top {len(worst_indices)} violations:")
                    for i, idx in enumerate(worst_indices):
                        if violations[idx] >= 0:  # Only log actual violations
                            pair = self.pairs[idx]
                            res_idx = pair[2]
                            dist = distances[idx].item()
                            n_grad_mag = n_grad_mags[idx].item()
                            ca_grad_mag = ca_grad_mags[idx].item()
                            n_dot = n_grad_dot[idx].item()
                            ca_dot = ca_grad_dot[idx].item()
                            status = "too_close" if dist < lower_bound else "too_far"
                            print(
                                f"    #{i+1} Res{res_idx+1}: dist={dist:.3f}Å "
                                f"({status}, target={target_distance:.2f}±{tolerance:.2f}Å), "
                                f"grad_N={n_grad_mag:.4f} (dot={n_dot:+.4f}), "
                                f"grad_CA={ca_grad_mag:.4f} (dot={ca_dot:+.4f})"
                            )

        if template_mask is not None:
            result[0, template_mask, :] = 0.0

        return result


def get_potentials(steering_args, boltz2=False):
    potentials = []
    if steering_args.get("inpainting", False):
        potentials.extend(
            [
                # # Internal + boundary potentials (applies to all inpainting target residues)
                # InpaintingPeptideBondPotential(
                #     parameters={
                #         "guidance_interval": 1,
                #         "guidance_weight": PiecewiseStepFunction(
                #             thresholds=[0.05], values=[0.1, 0.0]
                #         ),
                #         "target_distance": 1.3,
                #         "tolerance": 0.2,
                #         "k": 5.0,
                #         "log_interval": 1,
                #     }
                # ),
                # InpaintingCACDistancePotential(
                #     parameters={
                #         "guidance_interval": 1,
                #         "guidance_weight": PiecewiseStepFunction(
                #             thresholds=[0.05], values=[0.05, 0.0]
                #         ),
                #         "target_distance": 1.53,
                #         "tolerance": 0.2,
                #         "k": 5.0,
                #         "log_interval": 1,
                #     }
                # ),
                # InpaintingNCADistancePotential(
                #     parameters={
                #         "guidance_interval": 1,
                #         "guidance_weight": PiecewiseStepFunction(
                #             thresholds=[0.05], values=[0.05, 0.0]
                #         ),
                #         "target_distance": 1.46,
                #         "tolerance": 0.2,
                #         "k": 5.0,
                #         "log_interval": 1,
                #     }
                # ),
                TemplateReferencePotential(
                    parameters={
                        "guidance_interval": 2,
                        "guidance_weight": (
                            0.1
                        ),
                        "resampling_weight": 1.0,
                    }
                ),
            ]
        )
    elif steering_args["fk_steering"] or steering_args["physical_guidance_update"]:
        potentials.extend(
            [
                SymmetricChainCOMPotential(
                    parameters={
                        "guidance_interval": 4,
                        "guidance_weight": (
                            0.5 if steering_args["physical_guidance_update"] else 0.0
                        ),
                        "resampling_weight": 0.5,
                        "buffer": ExponentialInterpolation(
                            start=1.0, end=5.0, alpha=-2.0
                        ),
                    }
                ),
                VDWOverlapPotential(
                    parameters={
                        "guidance_interval": 5,
                        "guidance_weight": (
                            PiecewiseStepFunction(thresholds=[0.4], values=[0.125, 0.0])
                            if steering_args["physical_guidance_update"]
                            else 0.0
                        ),
                        "resampling_weight": PiecewiseStepFunction(
                            thresholds=[0.6], values=[0.01, 0.0]
                        ),
                        "buffer": 0.225,
                    }
                ),
                ConnectionsPotential(
                    parameters={
                        "guidance_interval": 1,
                        "guidance_weight": (
                            0.15 if steering_args["physical_guidance_update"] else 0.0
                        ),
                        "resampling_weight": 1.0,
                        "buffer": 2.0,
                    }
                ),
                PoseBustersPotential(
                    parameters={
                        "guidance_interval": 1,
                        "guidance_weight": (
                            0.01 if steering_args["physical_guidance_update"] else 0.0
                        ),
                        "resampling_weight": 0.1,
                        "bond_buffer": 0.125,
                        "angle_buffer": 0.125,
                        "clash_buffer": 0.10,
                    }
                ),
                ChiralAtomPotential(
                    parameters={
                        "guidance_interval": 1,
                        "guidance_weight": (
                            0.1 if steering_args["physical_guidance_update"] else 0.0
                        ),
                        "resampling_weight": 1.0,
                        "buffer": 0.52360,
                    }
                ),
                StereoBondPotential(
                    parameters={
                        "guidance_interval": 1,
                        "guidance_weight": (
                            0.05 if steering_args["physical_guidance_update"] else 0.0
                        ),
                        "resampling_weight": 1.0,
                        "buffer": 0.52360,
                    }
                ),
                PlanarBondPotential(
                    parameters={
                        "guidance_interval": 1,
                        "guidance_weight": (
                            0.05 if steering_args["physical_guidance_update"] else 0.0
                        ),
                        "resampling_weight": 1.0,
                        "buffer": 0.26180,
                    }
                ),
            ]
        )
    if boltz2 and (
        steering_args["fk_steering"] or steering_args["contact_guidance_update"]
    ):
        potentials.extend(
            [
                ContactPotentital(
                    parameters={
                        "guidance_interval": 4,
                        "guidance_weight": (
                            PiecewiseStepFunction(
                                thresholds=[0.25, 0.75], values=[0.0, 0.5, 1.0]
                            )
                            if steering_args["contact_guidance_update"]
                            else 0.0
                        ),
                        "resampling_weight": 1.0,
                        "union_lambda": ExponentialInterpolation(
                            start=8.0, end=0.0, alpha=-2.0
                        ),
                    }
                ),
                TemplateReferencePotential(
                    parameters={
                        "guidance_interval": 2,
                        "guidance_weight": (
                            0.1 if steering_args["contact_guidance_update"] else 0.0
                        ),
                        "resampling_weight": 1.0,
                    }
                ),
            ]
        )
    return potentials
