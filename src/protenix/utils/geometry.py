# Copyright 2024 ByteDance and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import numpy as np
import torch
from einops import einsum
from scipy.spatial.transform import Rotation


def weighted_rigid_align(
    true_coords: torch.Tensor,   # Float[..., n, 3]  – coords to align (source)
    pred_coords: torch.Tensor,   # Float[..., n, 3]  – target frame
    weights: torch.Tensor,       # Float[..., n]      – per-atom weights
    mask: torch.Tensor,          # Bool/Float[..., n] – valid-atom mask
    return_transform: bool = False,
):
    """Weighted Kabsch alignment: align *true_coords* onto *pred_coords*.

    Ported from patchr ``boltz/model/loss/diffusionv2.py`` (Algorithm 28 in AF3).

    Returns aligned_coords, or (aligned_coords, rot_matrix, true_centroid,
    pred_centroid) when *return_transform* is True so the same transformation
    can be applied to additional tensors via :func:`apply_rigid_transform`.
    """
    out_shape = torch.broadcast_shapes(true_coords.shape, pred_coords.shape)
    *batch_size, num_points, dim = out_shape
    w = (mask.float() * weights).unsqueeze(-1)  # [..., n, 1]

    true_centroid = (true_coords * w).sum(dim=-2, keepdim=True) / w.sum(dim=-2, keepdim=True)
    pred_centroid = (pred_coords * w).sum(dim=-2, keepdim=True) / w.sum(dim=-2, keepdim=True)

    tc = true_coords - true_centroid
    pc = pred_coords - pred_centroid

    cov = einsum(w * pc, tc, "... n i, ... n j -> ... i j")

    orig_dtype = cov.dtype
    cov32 = cov.to(torch.float32)
    if cov32.device.type == "mps":
        U, S, V = torch.linalg.svd(cov32.cpu())
        U, S, V = U.to("mps"), S.to("mps"), V.to("mps")
    else:
        U, S, V = torch.linalg.svd(cov32, driver="gesvd" if cov32.is_cuda else None)
    V = V.mH

    rot = torch.einsum("... i j, ... k j -> ... i k", U, V).to(torch.float32)
    if batch_size:
        F = torch.eye(dim, dtype=cov32.dtype, device=cov.device)[None].repeat(*batch_size, 1, 1)
    else:
        F = torch.eye(dim, dtype=cov32.dtype, device=cov.device)
    det = torch.det(rot.cpu()).to(rot.device) if rot.is_mps else torch.det(rot)
    F[..., -1, -1] = det
    rot = einsum(U, F, V, "... i j, ... j k, ... l k -> ... i l").to(orig_dtype)

    aligned = einsum(tc, rot, "... n i, ... j i -> ... n j") + pred_centroid
    aligned = aligned.detach()

    if return_transform:
        return aligned, rot.detach(), true_centroid.detach(), pred_centroid.detach()
    return aligned


def apply_rigid_transform(
    coords: torch.Tensor,          # Float[..., n, 3]
    rot_matrix: torch.Tensor,      # Float[..., 3, 3]
    source_centroid: torch.Tensor, # Float[..., 1, 3]
    target_centroid: torch.Tensor, # Float[..., 1, 3]
) -> torch.Tensor:
    """Apply the rigid transform from :func:`weighted_rigid_align` to *coords*.

    Computes: ``R @ (coords − source_centroid) + target_centroid``.

    Ported from patchr ``boltz/model/loss/diffusionv2.py``.
    """
    coords_c = coords - source_centroid
    return einsum(coords_c, rot_matrix, "... n i, ... j i -> ... n j") + target_centroid


def angle_3p(a, b, c):
    """
    Calculate the angle between three points in a 2D space.

    Args:
        a (list or array-like): The coordinates of the first point.
        b (list or array-like): The coordinates of the second point.
        c (list or array-like): The coordinates of the third point.

    Returns:
        float: The angle in degrees (0, 180) between the vectors
               from point a to point b and point b to point c.
    """
    a = np.asarray(a)
    b = np.asarray(b)
    c = np.asarray(c)

    ab = b - a
    bc = c - b

    dot_product = np.dot(ab, bc)

    norm_ab = np.linalg.norm(ab)
    norm_bc = np.linalg.norm(bc)

    cos_theta = np.clip(dot_product / (norm_ab * norm_bc + 1e-4), -1, 1)
    theta_radians = np.arccos(cos_theta)
    theta_degrees = np.degrees(theta_radians)
    return theta_degrees


def random_transform(
    points, max_translation=1.0, apply_augmentation=False, centralize=True
) -> np.ndarray:
    """
    Randomly transform a set of 3D points.

    Args:
        points (numpy.ndarray): The points to be transformed, shape=(N, 3)
        max_translation (float): The maximum translation value. Default is 1.0.
        apply_augmentation (bool): Whether to apply random rotation/translation on ref_pos

    Returns:
        numpy.ndarray: The transformed points.
    """
    if centralize:
        points = points - points.mean(axis=0)
    if not apply_augmentation:
        return points
    translation = np.random.uniform(-max_translation, max_translation, size=3)
    R = Rotation.random().as_matrix()
    transformed_points = np.dot(points + translation, R.T)
    return transformed_points
