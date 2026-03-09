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

from math import sqrt
from typing import Any, Callable, Optional

import torch

from protenix.model.utils import centre_random_augmentation
from protenix.utils.geometry import apply_rigid_transform, weighted_rigid_align


class TrainingNoiseSampler:
    """
    Sample the noise-level of training samples.

    Args:
        p_mean (float, optional): gaussian mean. Defaults to -1.2.
        p_std (float, optional): gaussian std. Defaults to 1.5.
        sigma_data (float, optional): scale. Defaults to 16.0, but this is 1.0 in EDM.
    """

    def __init__(
        self,
        p_mean: float = -1.2,
        p_std: float = 1.5,
        sigma_data: float = 16.0,  # NOTE: in EDM, this is 1.0
    ) -> None:
        self.sigma_data = sigma_data
        self.p_mean = p_mean
        self.p_std = p_std
        print(f"train scheduler {self.sigma_data}")

    def __call__(
        self, size: torch.Size, device: torch.device = torch.device("cpu")
    ) -> torch.Tensor:
        """Sampling

        Args:
            size (torch.Size): the target size
            device (torch.device, optional): target device. Defaults to torch.device("cpu").

        Returns:
            torch.Tensor: sampled noise-level
        """
        rnd_normal = torch.randn(size=size, device=device)
        noise_level = (rnd_normal * self.p_std + self.p_mean).exp() * self.sigma_data
        return noise_level


class InferenceNoiseScheduler:
    """
    Scheduler for noise-level (time steps).

    Args:
        s_max (float, optional): maximal noise level. Defaults to 160.0.
        s_min (float, optional): minimal noise level. Defaults to 4e-4.
        rho (float, optional): the exponent numerical part. Defaults to 7.
        sigma_data (float, optional): scale. Defaults to 16.0, but this is 1.0 in EDM.
    """

    def __init__(
        self,
        s_max: float = 160.0,
        s_min: float = 4e-4,
        rho: float = 7,
        sigma_data: float = 16.0,  # NOTE: in EDM, this is 1.0
    ) -> None:
        self.sigma_data = sigma_data
        self.s_max = s_max
        self.s_min = s_min
        self.rho = rho
        print(f"inference scheduler {self.sigma_data}")

    def __call__(
        self,
        N_step: int = 200,
        device: torch.device = torch.device("cpu"),
        dtype: torch.dtype = torch.float32,
    ) -> torch.Tensor:
        """Schedule the noise-level (time steps). No sampling is performed.

        Args:
            N_step (int, optional): number of time steps. Defaults to 200.
            device (torch.device, optional): target device. Defaults to torch.device("cpu").
            dtype (torch.dtype, optional): target dtype. Defaults to torch.float32.

        Returns:
            torch.Tensor: noise-level (time_steps)
                [N_step+1]
        """
        step_size = 1 / N_step
        step_indices = torch.arange(N_step + 1, device=device, dtype=dtype)
        t_step_list = (
            self.sigma_data
            * (
                self.s_max ** (1 / self.rho)
                + step_indices
                * step_size
                * (self.s_min ** (1 / self.rho) - self.s_max ** (1 / self.rho))
            )
            ** self.rho
        )
        # replace the last time step by 0
        t_step_list[..., -1] = 0  # t_N = 0

        return t_step_list


def _get_boundary_region_mask(
    template_mask: torch.Tensor,  # (n_atoms,) bool
    atom_to_token_idx: torch.Tensor,  # (n_atoms,) int – index into token dim
    asym_id: torch.Tensor,  # (n_tokens,) int
    boundary_window: int = 2,
) -> torch.Tensor:
    """Return bool atom mask for atoms within *boundary_window* residues of the
    template/generated boundary (on both sides).

    Args:
        template_mask: Per-atom bool tensor, True = fixed by template.
        atom_to_token_idx: Per-atom token index.
        asym_id: Per-token asym (chain) ID.
        boundary_window: Residue distance window around boundary.

    Returns:
        Boolean atom mask, True = boundary region.
    """
    n_tokens = int(asym_id.shape[0])
    # Build residue-level template mask: residue is template if ANY atom is template
    residue_tmpl = torch.zeros(n_tokens, dtype=torch.bool, device=template_mask.device)
    for tok_idx in range(n_tokens):
        atom_sel = atom_to_token_idx == tok_idx
        if atom_sel.any():
            residue_tmpl[tok_idx] = template_mask[atom_sel].any()

    # Find initial boundary residues (status changes between consecutive same-chain residues)
    boundary_init = torch.zeros(n_tokens, dtype=torch.bool, device=template_mask.device)
    for i in range(n_tokens):
        if i > 0 and asym_id[i] == asym_id[i - 1]:
            if residue_tmpl[i] != residue_tmpl[i - 1]:
                boundary_init[i] = True
                boundary_init[i - 1] = True

    # Expand boundary by window on both sides (within same chain)
    boundary_expanded = torch.zeros(n_tokens, dtype=torch.bool, device=template_mask.device)
    boundary_indices = torch.where(boundary_init)[0]
    for i in range(n_tokens):
        for bi in boundary_indices:
            if asym_id[i] != asym_id[bi]:
                continue
            # Check all tokens between i and bi are same chain
            lo, hi = (i, bi.item()) if i <= bi else (bi.item(), i)
            same_chain = (asym_id[lo:hi + 1] == asym_id[i]).all()
            if same_chain and abs(i - bi.item()) <= boundary_window:
                boundary_expanded[i] = True
                break

    # Map back to atoms
    boundary_atom_mask = boundary_expanded[atom_to_token_idx]
    return boundary_atom_mask


def sample_diffusion(
    denoise_net: Callable,
    input_feature_dict: dict[str, Any],
    s_inputs: torch.Tensor,
    s_trunk: torch.Tensor,
    z_trunk: torch.Tensor,
    pair_z: torch.Tensor,
    p_lm: torch.Tensor,
    c_l: torch.Tensor,
    noise_schedule: torch.Tensor,
    N_sample: int = 1,
    gamma0: float = 0.8,
    gamma_min: float = 1.0,
    noise_scale_lambda: float = 1.003,
    step_scale_eta: float = 1.5,
    diffusion_chunk_size: Optional[int] = None,
    inplace_safe: bool = False,
    attn_chunk_size: Optional[int] = None,
    enable_efficient_fusion: bool = False,
    # Inpainting parameters
    boundary_refinement_enabled: bool = True,
    boundary_refinement_window: int = 2,
    boundary_refinement_sigma_start: float = 1.5,
    boundary_refinement_steps: int = 25,
) -> torch.Tensor:
    """Implements Algorithm 18 in AF3 with optional inpainting support.

    When ``input_feature_dict`` contains ``inpainting_template_coords`` and
    ``inpainting_template_mask`` the sampling loop switches to inpainting mode:

    Per-step (Stage 1):
        ① Template noise injection – fixed atoms are reset to template + σ noise
        ② Network denoising (unchanged)
        ③ Kabsch alignment – noisy frame aligned to denoised; template follows
        ④ Euler step (unchanged)
        ⑤ Template hard reset – fixed atoms snapped back to current template frame

    After Stage 1, a short boundary-refinement pass (Stage 2) smooths the
    transition between template and generated regions.

    Args:
        denoise_net: the network that performs the denoising step.
        input_feature_dict: input meta feature dict.
        s_inputs: single embedding from InputFeatureEmbedder [..., N_tokens, c_s_inputs]
        s_trunk: single feature embedding from PairFormer [..., N_tokens, c_s]
        z_trunk: pair feature embedding from PairFormer [..., N_tokens, N_tokens, c_z]
        pair_z: pair embedding from InputFeatureEmbedder [..., N_tokens, N_tokens, c_z]
        p_lm: MSA embedding [..., N_tokens, c_p_lm]
        c_l: ligand embedding [..., N_tokens, c_l]
        noise_schedule: [N_step+1] sigma schedule.
        N_sample: number of generated samples.
        gamma0, gamma_min, noise_scale_lambda, step_scale_eta: AF3 Alg.18 params.
        diffusion_chunk_size: chunk size for N_sample dimension.
        inplace_safe, attn_chunk_size, enable_efficient_fusion: standard flags.
        boundary_refinement_enabled: run Stage 2 boundary refinement.
        boundary_refinement_window: ±residues around boundary.
        boundary_refinement_sigma_start: starting noise level for Stage 2.
        boundary_refinement_steps: number of steps in Stage 2.

    Returns:
        Denoised coordinates [..., N_sample, N_atom, 3].
    """
    N_atom = input_feature_dict["atom_to_token_idx"].size(-1)
    batch_shape = s_inputs.shape[:-2]
    device = s_inputs.device
    dtype = s_inputs.dtype

    # ── Inpainting setup ────────────────────────────────────────────────────
    raw_template_coords = input_feature_dict.get("inpainting_template_coords")
    raw_template_mask = input_feature_dict.get("inpainting_template_mask")
    enable_inpainting = raw_template_coords is not None and raw_template_mask is not None

    if enable_inpainting:
        # Bring to device / dtype
        _tc = raw_template_coords.to(device=device, dtype=dtype)  # (N_atom, 3)
        _tm = raw_template_mask.to(device=device, dtype=torch.bool)  # (N_atom,)
        n_fixed = int(_tm.sum())
        print(f"[Inpainting] Stage 1: {n_fixed}/{N_atom} template atoms will be fixed")

    # ── Inner loop ──────────────────────────────────────────────────────────
    def _chunk_sample_diffusion(chunk_n_sample: int, inplace_safe: bool) -> torch.Tensor:
        # [..., chunk_n_sample, N_atom, 3]
        x_l = noise_schedule[0] * torch.randn(
            size=(*batch_shape, chunk_n_sample, N_atom, 3), device=device, dtype=dtype
        )

        if enable_inpainting:
            # Expand template for each sample in this chunk
            # [..., chunk_n_sample, N_atom, 3]
            template_coords = _tc.unsqueeze(-3).expand(
                *batch_shape, chunk_n_sample, N_atom, 3
            ).clone()
            template_mask = _tm.unsqueeze(-2).expand(
                *batch_shape, chunk_n_sample, N_atom
            )  # no clone needed – read-only

        for step_idx, (c_tau_last, c_tau) in enumerate(
            zip(noise_schedule[:-1], noise_schedule[1:])
        ):
            # ① Template noise injection (inpainting only)
            if enable_inpainting:
                sigma_from = float(c_tau_last)
                noise = torch.randn_like(x_l) * sigma_from
                x_l = x_l.clone()
                x_l[template_mask] = template_coords[template_mask] + noise[template_mask]
            else:
                # Normal mode: random augmentation
                x_l = (
                    centre_random_augmentation(x_input_coords=x_l, N_sample=1)
                    .squeeze(dim=-3)
                    .to(dtype)
                )

            # Stochastic noise injection (AF3 Alg.18 step 2)
            gamma = float(gamma0) if c_tau > gamma_min else 0
            t_hat = c_tau_last * (gamma + 1)
            delta_noise_level = torch.sqrt(t_hat ** 2 - c_tau_last ** 2)
            x_noisy = x_l + noise_scale_lambda * delta_noise_level * torch.randn(
                size=x_l.shape, device=device, dtype=dtype
            )

            # ② Network denoising
            t_hat_expanded = (
                t_hat.reshape((1,) * (len(batch_shape) + 1))
                .expand(*batch_shape, chunk_n_sample)
                .to(dtype)
            )
            x_denoised = denoise_net(
                x_noisy=x_noisy,
                t_hat_noise_level=t_hat_expanded,
                input_feature_dict=input_feature_dict,
                s_inputs=s_inputs,
                s_trunk=s_trunk,
                z_trunk=z_trunk,
                pair_z=pair_z,
                p_lm=p_lm,
                c_l=c_l,
                chunk_size=attn_chunk_size,
                inplace_safe=inplace_safe,
                enable_efficient_fusion=enable_efficient_fusion,
            )

            # ③ Kabsch alignment (inpainting: keep template in sync with frame)
            if enable_inpainting:
                with torch.autocast("cuda", enabled=False):
                    ones = torch.ones(
                        (*batch_shape, chunk_n_sample, N_atom),
                        device=device, dtype=torch.float32
                    )
                    x_noisy_aligned, rot, src_ctr, tgt_ctr = weighted_rigid_align(
                        x_noisy.float(),
                        x_denoised.float(),
                        weights=ones,
                        mask=ones,
                        return_transform=True,
                    )
                    template_coords = apply_rigid_transform(
                        template_coords.float(), rot, src_ctr, tgt_ctr
                    ).to(dtype)
                x_noisy = x_noisy_aligned.to(dtype)

            # ④ Euler step
            delta = (x_noisy - x_denoised) / t_hat_expanded[..., None, None]
            dt = c_tau - t_hat_expanded
            x_l = x_noisy + step_scale_eta * dt[..., None, None] * delta

            # ⑤ Template hard reset
            if enable_inpainting:
                x_l = x_l.clone()
                x_l[template_mask] = template_coords[template_mask].to(dtype)

        if not enable_inpainting:
            return x_l

        # ── Final alignment to PDB frame ──
        _tc_original = _tc.unsqueeze(-3).expand(
            *batch_shape, chunk_n_sample, N_atom, 3
        )
        def _final_align_to_pdb_frame(x):
            with torch.autocast("cuda", enabled=False):
                w = template_mask.float()
                m = torch.ones_like(w)
                xa, _, _, _ = weighted_rigid_align(
                    x.float(), _tc_original.float(),
                    weights=w, mask=m, return_transform=True,
                )
            return xa.to(dtype)

        # ── Stage 2: Boundary Refinement ────────────────────────────────────
        # Runs a short focused diffusion on atoms near the template boundary.
        if not boundary_refinement_enabled or n_fixed == 0 or n_fixed == N_atom:
            return x_l

        atom_to_token_idx = input_feature_dict["atom_to_token_idx"]  # (N_atom,)
        asym_id = input_feature_dict["asym_id"]                       # (N_token,)
        if asym_id.dim() > 1:
            asym_id = asym_id[0]

        boundary_mask = _get_boundary_region_mask(
            _tm, atom_to_token_idx, asym_id, boundary_window=boundary_refinement_window
        )  # (N_atom,)

        # ── Fix 4: Protein-only filtering & PTM exclusion ──
        is_protein = input_feature_dict.get("is_protein")
        if is_protein is not None:
            protein_atom_mask = is_protein.to(device=device, dtype=torch.bool)
            if protein_atom_mask.dim() > 1:
                protein_atom_mask = protein_atom_mask[0]
            boundary_mask = boundary_mask & protein_atom_mask
            print("  - Boundary refinement: PROTEIN only (DNA, RNA, ligand excluded)")

        modified_res_mask = input_feature_dict.get("modified_res_mask")
        if modified_res_mask is not None:
            ptm_mask = modified_res_mask.to(device=device, dtype=torch.bool)
            if ptm_mask.dim() > 1:
                ptm_mask = ptm_mask[0]
            boundary_mask = boundary_mask & (~ptm_mask)
            print("  - Boundary refinement: modified (PTM) residues excluded")

        # Note: Refine BOTH template-side and generated-side boundary atoms.
        # Template-side atoms drift from their exact template positions during LRD,
        # but this produces better peptide bond geometry at boundaries.
        # The final Kabsch alignment (_final_align_to_pdb_frame) corrects the global frame.

        # Expand boundary mask for chunk dimension
        boundary_mask_exp = boundary_mask.unsqueeze(-2).expand(
            *batch_shape, chunk_n_sample, N_atom
        )
        # The "fixed" set for Stage 2 = everything NOT in boundary region
        refinement_fixed_mask = ~boundary_mask_exp
        refinement_template_coords = x_l.clone()  # current coordinates are "template"

        boundary_atom_count = int(boundary_mask.sum())
        print(f"[Inpainting] Stage 2: boundary refinement "
              f"({boundary_atom_count} boundary atoms, "
              f"σ_start={boundary_refinement_sigma_start:.2f}, "
              f"steps={boundary_refinement_steps})")

        # ── BOUNDARY MASK DEBUG ──
        _n_tokens = int(asym_id.shape[0])
        _residue_tmpl = torch.zeros(_n_tokens, dtype=torch.bool, device=device)
        for _ti in range(_n_tokens):
            _asel = atom_to_token_idx == _ti
            if _asel.any():
                _residue_tmpl[_ti] = _tm[_asel].any()
        # Find boundary initial tokens
        _boundary_init_toks = []
        for _i in range(_n_tokens):
            if _i > 0 and asym_id[_i] == asym_id[_i - 1]:
                if _residue_tmpl[_i] != _residue_tmpl[_i - 1]:
                    _boundary_init_toks.extend([_i - 1, _i])
        _boundary_init_toks = sorted(set(_boundary_init_toks))
        # Show expanded boundary tokens
        _boundary_expanded_toks = []
        for _ti in range(_n_tokens):
            if boundary_mask[atom_to_token_idx == _ti].any():
                _boundary_expanded_toks.append(_ti)
        # Per-token atom count
        _tok_atom_counts = []
        for _ti in _boundary_expanded_toks:
            _n = int((atom_to_token_idx == _ti).sum())
            _is_tmpl = "T" if _residue_tmpl[_ti] else "G"
            _n_bnd = int(boundary_mask[atom_to_token_idx == _ti].sum())
            _tok_atom_counts.append(f"{_ti}({_is_tmpl}):{_n_bnd}/{_n}")
        print(f"  [BND-DEBUG] N_tokens={_n_tokens}, N_atoms={int(atom_to_token_idx.shape[0])}")
        print(f"  [BND-DEBUG] Template tokens: {_residue_tmpl.sum().item()}/{_n_tokens}")
        print(f"  [BND-DEBUG] Generated token ranges: ", end="")
        _gen_ranges = []
        _in_gen = False
        _gen_start = 0
        for _i in range(_n_tokens):
            if not _residue_tmpl[_i] and not _in_gen:
                _gen_start = _i
                _in_gen = True
            elif _residue_tmpl[_i] and _in_gen:
                _gen_ranges.append(f"{_gen_start}-{_i-1}")
                _in_gen = False
        if _in_gen:
            _gen_ranges.append(f"{_gen_start}-{_n_tokens-1}")
        print(", ".join(_gen_ranges) if _gen_ranges else "none")
        print(f"  [BND-DEBUG] Boundary init tokens: {_boundary_init_toks}")
        print(f"  [BND-DEBUG] Boundary expanded tokens (window={boundary_refinement_window}): {_boundary_expanded_toks}")
        print(f"  [BND-DEBUG] Per-token boundary atoms: {_tok_atom_counts}")

        if boundary_atom_count == 0:
            return _final_align_to_pdb_frame(x_l)

        # ── DEBUG: identify boundary residues & measure bond distances ──
        _dbg_residue_tmpl = torch.zeros(int(asym_id.shape[0]), dtype=torch.bool, device=device)
        for tok_idx in range(int(asym_id.shape[0])):
            atom_sel = atom_to_token_idx == tok_idx
            if atom_sel.any():
                _dbg_residue_tmpl[tok_idx] = _tm[atom_sel].any()
        _dbg_boundary_init = []
        for i in range(int(asym_id.shape[0])):
            if i > 0 and asym_id[i] == asym_id[i - 1]:
                if _dbg_residue_tmpl[i] != _dbg_residue_tmpl[i - 1]:
                    _dbg_boundary_init.append((i - 1, i))
        print(f"  [DEBUG] Boundary residue pairs (token indices): {_dbg_boundary_init}")
        print(f"  [DEBUG] Residue template mask: {_dbg_residue_tmpl.int().tolist()}")

        # Decode atom names from ref_atom_name_chars (4 chars per atom, one-hot encoded)
        _ref_name_chars = input_feature_dict.get("ref_atom_name_chars")
        def _get_atom_name(atom_idx):
            if _ref_name_chars is None:
                return "?"
            # ref_atom_name_chars: (N_atom, 4, 64) one-hot → decode
            chars = _ref_name_chars[atom_idx]  # (4, 64)
            name = ""
            for ch in range(4):
                idx = chars[ch].argmax().item()
                if idx == 0:
                    name += " "
                else:
                    name += chr(idx + 31)  # rough ASCII mapping
                    # The encoding might use different schemes; fall back
            return name.strip()

        # Measure backbone C→N peptide bond distances at boundary
        def _measure_boundary_bonds(coords, label=""):
            """Measure backbone peptide bond (C→N) distances at boundary junctions."""
            c = coords[..., 0, :, :] if coords.dim() > 2 else coords
            if c.dim() > 2:
                c = c.reshape(-1, 3)
            for (tok_a, tok_b) in _dbg_boundary_init:
                atoms_a = (atom_to_token_idx == tok_a).nonzero(as_tuple=True)[0]
                atoms_b = (atom_to_token_idx == tok_b).nonzero(as_tuple=True)[0]
                if len(atoms_a) == 0 or len(atoms_b) == 0:
                    continue
                # For protein: atom ordering is typically N=0, CA=1, C=2, O=3, ...
                # Find C atom (index 2) in tok_a and N atom (index 0) in tok_b
                c_atom_idx = atoms_a[2] if len(atoms_a) > 2 else atoms_a[-1]  # backbone C
                n_atom_idx = atoms_b[0]  # backbone N
                cn_dist = (c[c_atom_idx] - c[n_atom_idx]).norm().item()
                # Also CA→CA distance (should be ~3.8Å)
                ca_a = atoms_a[1] if len(atoms_a) > 1 else atoms_a[0]
                ca_b = atoms_b[1] if len(atoms_b) > 1 else atoms_b[0]
                caca_dist = (c[ca_a] - c[ca_b]).norm().item()
                # Min distance
                dists = torch.cdist(c[atoms_a].unsqueeze(0).float(),
                                    c[atoms_b].unsqueeze(0).float()).squeeze(0)
                min_dist = dists.min().item()
                is_tmpl_a = "T" if _dbg_residue_tmpl[tok_a] else "G"
                is_tmpl_b = "T" if _dbg_residue_tmpl[tok_b] else "G"
                in_boundary_a = "B" if boundary_mask[atoms_a].any() else "-"
                in_boundary_b = "B" if boundary_mask[atoms_b].any() else "-"
                print(f"  [{label}] tok {tok_a}({is_tmpl_a}{in_boundary_a})"
                      f"→tok {tok_b}({is_tmpl_b}{in_boundary_b}): "
                      f"C→N={cn_dist:.3f}Å (ideal ~1.33), "
                      f"CA→CA={caca_dist:.3f}Å (ideal ~3.8), "
                      f"min={min_dist:.3f}Å")
        _measure_boundary_bonds(x_l, "BEFORE-LRD")

        # ── Measure ALL consecutive bonds in generated regions ──
        _gen_regions = []  # list of (start, end) inclusive
        _in_gen = False
        for _i in range(int(asym_id.shape[0])):
            if not _dbg_residue_tmpl[_i] and not _in_gen:
                _gen_start = _i
                _in_gen = True
            elif (_dbg_residue_tmpl[_i] or _i == int(asym_id.shape[0]) - 1) and _in_gen:
                _gen_end = _i - 1 if _dbg_residue_tmpl[_i] else _i
                _gen_regions.append((_gen_start, _gen_end))
                _in_gen = False

        _c_coords = x_l[..., 0, :, :] if x_l.dim() > 2 else x_l
        if _c_coords.dim() > 2:
            _c_coords_flat = _c_coords.reshape(-1, 3)
        else:
            _c_coords_flat = _c_coords

        _all_bonds_to_check = []  # (tok_a, tok_b) for all bonds in/around generated regions
        for (gs, ge) in _gen_regions:
            # Include boundary-1 to boundary+1
            check_start = max(0, gs - 1)
            check_end = min(int(asym_id.shape[0]) - 1, ge + 1)
            for t in range(check_start, check_end):
                if asym_id[t] == asym_id[t + 1]:
                    _all_bonds_to_check.append((t, t + 1))

        _broken_internal_bonds = []
        print(f"  [BONDS] All bonds in/near generated regions:")
        for (tok_a, tok_b) in _all_bonds_to_check:
            atoms_a = (atom_to_token_idx == tok_a).nonzero(as_tuple=True)[0]
            atoms_b = (atom_to_token_idx == tok_b).nonzero(as_tuple=True)[0]
            if len(atoms_a) < 3 or len(atoms_b) == 0:
                continue
            cn_dist = (_c_coords_flat[atoms_a[2]] - _c_coords_flat[atoms_b[0]]).norm().item()
            cn_err = abs(cn_dist - 1.33)
            is_boundary = (tok_a, tok_b) in _dbg_boundary_init
            tag = "BND" if is_boundary else "INT"
            status = "OK" if cn_err <= 0.35 else "BROKEN"
            is_a = "T" if _dbg_residue_tmpl[tok_a] else "G"
            is_b = "T" if _dbg_residue_tmpl[tok_b] else "G"
            print(f"    {tok_a}({is_a})→{tok_b}({is_b}) [{tag}]: C→N={cn_dist:.3f}Å (err={cn_err:.3f}) {status}")
            if not is_boundary and cn_err > 0.35:
                _broken_internal_bonds.append((tok_a, tok_b))

        # ── Per-region independent LRD ──
        # Run LRD separately for each generated region to avoid inter-region interference.
        # LRD params
        _lrd_gamma0 = 0.8
        _lrd_gamma_min = 1.0
        _lrd_noise_scale = 1.003
        _lrd_step_scale = 1.5
        _sigma_data = 16.0
        _sigma_min_norm = 0.0004
        _sigma_max_norm = boundary_refinement_sigma_start / _sigma_data
        _rho = 7
        _inv_rho = 1.0 / _rho

        # Build noise schedule (shared across regions)
        _steps = torch.arange(boundary_refinement_steps, device=device, dtype=torch.float32)
        ref_schedule = (
            _sigma_max_norm ** _inv_rho
            + _steps / (boundary_refinement_steps - 1)
            * (_sigma_min_norm ** _inv_rho - _sigma_max_norm ** _inv_rho)
        ) ** _rho * _sigma_data
        ref_schedule = torch.cat([ref_schedule, torch.zeros(1, device=device)]).to(dtype)

        _n_stochastic = int((ref_schedule[1:] > _lrd_gamma_min).sum())
        print(f"  [LRD] Schedule: {boundary_refinement_steps} steps, "
              f"σ={float(ref_schedule[0]):.4f}→0, "
              f"γ_min={_lrd_gamma_min} ({_n_stochastic} stochastic steps)")

        # ── Global LRD (Boltz-style) ──
        # Refine all boundary atoms at once with a single diffusion loop.
        refinement_template = x_l.clone()

        # Add initial noise to boundary atoms only
        init_sigma = ref_schedule[0]
        boundary_noise = init_sigma * torch.randn_like(x_l)
        x_ref = x_l.clone()
        x_ref[boundary_mask_exp] = refinement_template[boundary_mask_exp] + boundary_noise[boundary_mask_exp]

        for ref_c_tau_last, ref_c_tau in zip(ref_schedule[:-1], ref_schedule[1:]):
            # Inject noise into boundary atoms from template
            sigma_from = float(ref_c_tau_last)
            noise = torch.randn_like(x_ref) * sigma_from
            x_ref = x_ref.clone()
            x_ref[boundary_mask_exp] = (
                refinement_template[boundary_mask_exp] + noise[boundary_mask_exp]
            )
            # Hard reset fixed atoms
            x_ref[refinement_fixed_mask] = refinement_template[refinement_fixed_mask]

            gamma = float(gamma0) if ref_c_tau > gamma_min else 0
            t_hat = ref_c_tau_last * (gamma + 1)
            delta_noise = torch.sqrt(t_hat ** 2 - ref_c_tau_last ** 2)
            x_noisy = x_ref + noise_scale_lambda * delta_noise * torch.randn_like(x_ref)

            t_hat_exp = (
                t_hat.reshape((1,) * (len(batch_shape) + 1))
                .expand(*batch_shape, chunk_n_sample).to(dtype)
            )
            with torch.no_grad():
                x_denoised = denoise_net(
                    x_noisy=x_noisy, t_hat_noise_level=t_hat_exp,
                    input_feature_dict=input_feature_dict,
                    s_inputs=s_inputs, s_trunk=s_trunk, z_trunk=z_trunk,
                    pair_z=pair_z, p_lm=p_lm, c_l=c_l,
                    chunk_size=attn_chunk_size, inplace_safe=inplace_safe,
                    enable_efficient_fusion=enable_efficient_fusion,
                )

            delta = (x_noisy - x_denoised) / t_hat_exp[..., None, None]
            dt = ref_c_tau - t_hat_exp
            x_ref = x_noisy + step_scale_eta * dt[..., None, None] * delta

            # Hard reset fixed atoms after Euler step
            x_ref = x_ref.clone()
            x_ref[refinement_fixed_mask] = refinement_template[refinement_fixed_mask]

        x_result = x_ref

        _measure_boundary_bonds(x_result, "AFTER-LRD")

        return x_result
    # ────────────────────────────────────────────────────────────────────────

    if diffusion_chunk_size is None:
        x_l = _chunk_sample_diffusion(N_sample, inplace_safe=inplace_safe)
    else:
        x_l = []
        no_chunks = N_sample // diffusion_chunk_size + (
            N_sample % diffusion_chunk_size != 0
        )
        for i in range(no_chunks):
            chunk_n_sample = (
                diffusion_chunk_size
                if i < no_chunks - 1
                else N_sample - i * diffusion_chunk_size
            )
            chunk_x_l = _chunk_sample_diffusion(
                chunk_n_sample, inplace_safe=inplace_safe
            )
            x_l.append(chunk_x_l)
        x_l = torch.cat(x_l, -3)  # [..., N_sample, N_atom, 3]
    return x_l


def sample_diffusion_training(
    noise_sampler: TrainingNoiseSampler,
    denoise_net: Callable,
    label_dict: dict[str, Any],
    input_feature_dict: dict[str, Any],
    s_inputs: torch.Tensor,
    s_trunk: torch.Tensor,
    z_trunk: torch.Tensor,
    pair_z: torch.Tensor,
    p_lm: torch.Tensor,
    c_l: torch.Tensor,
    N_sample: int = 1,
    diffusion_chunk_size: Optional[int] = None,
    use_conditioning: bool = True,
    enable_efficient_fusion: bool = False,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Implements diffusion training as described in AF3 Appendix at page 23.
    It performances denoising steps from time 0 to time T.
    The time steps (=noise levels) are given by noise_schedule.

    Args:
        noise_sampler (TrainingNoiseSampler): sampler for training noise-level.
        denoise_net (Callable): the network that performs the denoising step.
        label_dict (dict[str, Any]) : a dictionary containing the followings.
            "coordinate": the ground-truth coordinates
                [..., N_atom, 3]
            "coordinate_mask": whether true coordinates exist.
                [..., N_atom]
        input_feature_dict (dict[str, Any]): input meta feature dict
        s_inputs (torch.Tensor): single embedding from InputFeatureEmbedder
            [..., N_tokens, c_s_inputs]
        s_trunk (torch.Tensor): single feature embedding from PairFormer (Alg17)
            [..., N_tokens, c_s]
        z_trunk (torch.Tensor): pair feature embedding from PairFormer (Alg17)
            [..., N_tokens, N_tokens, c_z]
        pair_z (torch.Tensor): pair feature embedding from InputFeatureEmbedder
            [..., N_tokens, N_tokens, c_z_inputs]
        p_lm (torch.Tensor): MSA embedding
            [..., N_tokens, c_p_lm]
        c_l (torch.Tensor): ligand embedding
            [..., N_tokens, c_c_l]
        N_sample (int): number of training samples
        diffusion_chunk_size (Optional[int]): Chunk size for diffusion operation. Defaults to None.
        use_conditioning (bool): Whether to use conditioning. Defaults to True.
        enable_efficient_fusion (bool): Whether to enable efficient fusion. Defaults to False.

    Returns:
        tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
            x_gt_augment: the augmented ground-truth coordinates [..., N_sample, N_atom, 3]
            x_denoised: the denoised coordinates [..., N_sample, N_atom, 3]
            sigma: the sampled noise-level [..., N_sample]
    """
    batch_size_shape = label_dict["coordinate"].shape[:-2]
    device = label_dict["coordinate"].device
    dtype = label_dict["coordinate"].dtype
    # Areate N_sample versions of the input structure by randomly rotating and translating
    x_gt_augment = centre_random_augmentation(
        x_input_coords=label_dict["coordinate"],
        N_sample=N_sample,
        mask=label_dict["coordinate_mask"],
    ).to(
        dtype
    )  # [..., N_sample, N_atom, 3]

    # Add independent noise to each structure
    # sigma: independent noise-level [..., N_sample]
    sigma = noise_sampler(size=(*batch_size_shape, N_sample), device=device).to(dtype)
    # noise: [..., N_sample, N_atom, 3]
    noise = torch.randn_like(x_gt_augment, dtype=dtype) * sigma[..., None, None]

    # Get denoising outputs [..., N_sample, N_atom, 3]
    if diffusion_chunk_size is None:
        x_denoised = denoise_net(
            x_noisy=x_gt_augment + noise,
            t_hat_noise_level=sigma,
            input_feature_dict=input_feature_dict,
            s_inputs=s_inputs,
            s_trunk=s_trunk,
            z_trunk=z_trunk,
            pair_z=pair_z,
            p_lm=p_lm,
            c_l=c_l,
            use_conditioning=use_conditioning,
            enable_efficient_fusion=enable_efficient_fusion,
        )
    else:
        x_denoised = []
        no_chunks = N_sample // diffusion_chunk_size + (
            N_sample % diffusion_chunk_size != 0
        )
        for i in range(no_chunks):
            x_noisy_i = (x_gt_augment + noise)[
                ..., i * diffusion_chunk_size : (i + 1) * diffusion_chunk_size, :, :
            ]
            t_hat_noise_level_i = sigma[
                ..., i * diffusion_chunk_size : (i + 1) * diffusion_chunk_size
            ]
            x_denoised_i = denoise_net(
                x_noisy=x_noisy_i,
                t_hat_noise_level=t_hat_noise_level_i,
                input_feature_dict=input_feature_dict,
                s_inputs=s_inputs,
                s_trunk=s_trunk,
                z_trunk=z_trunk,
                pair_z=pair_z,
                p_lm=p_lm,
                c_l=c_l,
                use_conditioning=use_conditioning,
                enable_efficient_fusion=enable_efficient_fusion,
            )
            x_denoised.append(x_denoised_i)
        x_denoised = torch.cat(x_denoised, dim=-3)

    return x_gt_augment, x_denoised, sigma
