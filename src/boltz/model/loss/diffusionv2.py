# started from code from https://github.com/lucidrains/alphafold3-pytorch, MIT License, Copyright (c) 2024 Phil Wang
# Mac GPU support added from https://github.com/fnachon/boltz

import einx
import torch
import torch.nn.functional as F
from einops import einsum, rearrange


def weighted_rigid_align(
    true_coords,  # Float['b n 3'],       #  true coordinates
    pred_coords,  # Float['b n 3'],       # predicted coordinates
    weights,  # Float['b n'],             # weights for each atom
    mask,  # Bool['b n'] | None = None    # mask for variable lengths
    return_transform=False,  # If True, also return (rot_matrix, true_centroid, pred_centroid)
):  # -> Float['b n 3'] or (Float['b n 3'], Float['b 3 3'], Float['b 1 3'], Float['b 1 3']):
    """Algorithm 28 : note there is a problem with the pseudocode in the paper where predicted and
    GT are swapped in algorithm 28, but correct in equation (2).
    
    Aligns true_coords to pred_coords using weighted Kabsch algorithm.
    
    The transformation is: aligned = R @ (true - true_centroid) + pred_centroid
    
    If return_transform=True, returns (aligned_coords, rot_matrix, true_centroid, pred_centroid)
    so that the same transformation can be applied to other coordinates:
        other_aligned = (other - true_centroid) @ rot_matrix.transpose(-1, -2) + pred_centroid
    """

    out_shape = torch.broadcast_shapes(true_coords.shape, pred_coords.shape)
    *batch_size, num_points, dim = out_shape
    weights = (mask * weights).unsqueeze(-1)

    # Compute weighted centroids
    true_centroid = (true_coords * weights).sum(dim=-2, keepdim=True) / weights.sum(
        dim=-2, keepdim=True
    )
    pred_centroid = (pred_coords * weights).sum(dim=-2, keepdim=True) / weights.sum(
        dim=-2, keepdim=True
    )

    # Center the coordinates
    true_coords_centered = true_coords - true_centroid
    pred_coords_centered = pred_coords - pred_centroid

    if torch.any(mask.sum(dim=-1) < (dim + 1)):
        print(
            "Warning: The size of one of the point clouds is <= dim+1. "
            + "`WeightedRigidAlign` cannot return a unique rotation."
        )

    # Compute the weighted covariance matrix
    cov_matrix = einsum(
        weights * pred_coords_centered,
        true_coords_centered,
        "... n i, ... n j -> ... i j",
    )

    # Compute the SVD of the covariance matrix, required float32 for svd and determinant
    original_dtype = cov_matrix.dtype
    cov_matrix_32 = cov_matrix.to(dtype=torch.float32)

    # Mac GPU support: Move to CPU for SVD on MPS (from https://github.com/fnachon/boltz)
    if cov_matrix_32.device.type == "mps":
        # Move to CPU for SVD
        cov_matrix_32_cpu = cov_matrix_32.cpu()
        U, S, V = torch.linalg.svd(cov_matrix_32_cpu)
        U = U.to("mps")
        S = S.to("mps")
        V = V.to("mps")
    else:
        U, S, V = torch.linalg.svd(
            cov_matrix_32, driver="gesvd" if cov_matrix_32.is_cuda else None
        )
    V = V.mH

    # Catch ambiguous rotation by checking the magnitude of singular values
    if (S.abs() <= 1e-15).any() and not (num_points < (dim + 1)):
        print(
            "Warning: Excessively low rank of "
            + "cross-correlation between aligned point clouds. "
            + "`WeightedRigidAlign` cannot return a unique rotation."
        )

    # Compute the rotation matrix
    rot_matrix = torch.einsum("... i j, ... k j -> ... i k", U, V).to(
        dtype=torch.float32
    )

    # Ensure proper rotation matrix with determinant 1
    F = torch.eye(dim, dtype=cov_matrix_32.dtype, device=cov_matrix.device)[
        None
    ].repeat(*batch_size, 1, 1)
    # Mac GPU support: torch.det is not supported yet on mps move to CPU (from https://github.com/fnachon/boltz)
    if rot_matrix.is_mps:
        F[..., -1, -1] = torch.det(rot_matrix.cpu()).to("mps")
    else:
        F[..., -1, -1] = torch.det(rot_matrix)
    rot_matrix = einsum(U, F, V, "... i j, ... j k, ... l k -> ... i l")
    rot_matrix = rot_matrix.to(dtype=original_dtype)

    # Apply the rotation and translation
    aligned_coords = (
        einsum(true_coords_centered, rot_matrix, "... n i, ... j i -> ... n j")
        + pred_centroid
    )
    aligned_coords.detach_()

    if return_transform:
        return aligned_coords, rot_matrix.detach(), true_centroid.detach(), pred_centroid.detach()
    return aligned_coords


def apply_rigid_transform(
    coords,  # Float['b n 3']
    rot_matrix,  # Float['b 3 3']
    source_centroid,  # Float['b 1 3']
    target_centroid,  # Float['b 1 3']
):  # -> Float['b n 3']
    """Apply the same rigid transformation computed by weighted_rigid_align to other coordinates.
    
    This applies: aligned = R @ (coords - source_centroid) + target_centroid
    
    This is useful when you want to transform additional coordinates (e.g., template)
    using the same transformation that was used to align the main coordinates.
    
    Args:
        coords: Coordinates to transform
        rot_matrix: Rotation matrix from weighted_rigid_align (with return_transform=True)
        source_centroid: Source centroid (true_centroid from weighted_rigid_align)
        target_centroid: Target centroid (pred_centroid from weighted_rigid_align)
    
    Returns:
        Transformed coordinates
    """
    coords_centered = coords - source_centroid
    transformed = einsum(coords_centered, rot_matrix, "... n i, ... j i -> ... n j") + target_centroid
    return transformed



def smooth_lddt_loss(
    pred_coords,  # Float['b n 3'],
    true_coords,  # Float['b n 3'],
    is_nucleotide,  # Bool['b n'],
    coords_mask,  # Bool['b n'] | None = None,
    nucleic_acid_cutoff: float = 30.0,
    other_cutoff: float = 15.0,
    multiplicity: int = 1,
):  # -> Float['']:
    """Algorithm 27
    pred_coords: predicted coordinates
    true_coords: true coordinates
    Note: for efficiency pred_coords is the only one with the multiplicity expanded
    TODO: add weighing which overweight the smooth lddt contribution close to t=0 (not present in the paper)
    """
    lddt = []
    for i in range(true_coords.shape[0]):
        true_dists = torch.cdist(true_coords[i], true_coords[i])

        is_nucleotide_i = is_nucleotide[i // multiplicity]
        coords_mask_i = coords_mask[i // multiplicity]

        is_nucleotide_pair = is_nucleotide_i.unsqueeze(-1).expand(
            -1, is_nucleotide_i.shape[-1]
        )

        mask = is_nucleotide_pair * (true_dists < nucleic_acid_cutoff).float()
        mask += (1 - is_nucleotide_pair) * (true_dists < other_cutoff).float()
        mask *= 1 - torch.eye(pred_coords.shape[1], device=pred_coords.device)
        mask *= coords_mask_i.unsqueeze(-1)
        mask *= coords_mask_i.unsqueeze(-2)

        valid_pairs = mask.nonzero()
        true_dists_i = true_dists[valid_pairs[:, 0], valid_pairs[:, 1]]

        pred_coords_i1 = pred_coords[i, valid_pairs[:, 0]]
        pred_coords_i2 = pred_coords[i, valid_pairs[:, 1]]
        pred_dists_i = F.pairwise_distance(pred_coords_i1, pred_coords_i2)

        dist_diff_i = torch.abs(true_dists_i - pred_dists_i)

        eps_i = (
            F.sigmoid(0.5 - dist_diff_i)
            + F.sigmoid(1.0 - dist_diff_i)
            + F.sigmoid(2.0 - dist_diff_i)
            + F.sigmoid(4.0 - dist_diff_i)
        ) / 4.0

        lddt_i = eps_i.sum() / (valid_pairs.shape[0] + 1e-5)
        lddt.append(lddt_i)

    # average over batch & multiplicity
    return 1.0 - torch.stack(lddt, dim=0).mean(dim=0)
