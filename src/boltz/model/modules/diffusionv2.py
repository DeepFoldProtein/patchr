# started from code from https://github.com/lucidrains/alphafold3-pytorch, MIT License, Copyright (c) 2024 Phil Wang

from __future__ import annotations

from math import sqrt

import numpy as np
import torch
import torch.nn.functional as F  # noqa: N812
from einops import rearrange
from torch import nn
from torch.nn import Module
from tqdm import tqdm
import boltz.model.layers.initialize as init
from boltz.data import const
from boltz.model.loss.diffusionv2 import (
    apply_rigid_transform,
    smooth_lddt_loss,
    weighted_rigid_align,
)
from boltz.model.modules.encodersv2 import (
    AtomAttentionDecoder,
    AtomAttentionEncoder,
    SingleConditioning,
)
from boltz.model.modules.transformersv2 import DiffusionTransformer
from boltz.model.modules.utils import (
    LinearNoBias,
    center_random_augmentation,
    compute_random_augmentation,
    default,
    log,
)
from boltz.model.potentials.potentials import get_potentials


def get_boundary_region_mask(template_mask, feats, boundary_window=2):
    """
    Get mask for atoms in boundary region (template side + generated side).
    
    This identifies atoms that are within boundary_window distance from the
    template-generated boundary, on BOTH sides.
    
    Args:
        template_mask: (batch, n_atoms) boolean tensor
        feats: feature dictionary containing atom_to_token mapping and asym_id
        boundary_window: distance from boundary within which to include residues
                        (e.g., 2 = boundary ± 2 residues on both sides)
    
    Returns:
        boundary_region_mask: (batch, n_atoms) boolean tensor for atoms near boundary
    """
    # Get residue-level template mask
    atom_to_token = feats["atom_to_token"].float()  # (batch, n_atoms, n_residues)
    
    # A residue is template if ANY of its atoms is template
    residue_template_mask = (atom_to_token.transpose(1, 2) @ template_mask.unsqueeze(-1).float()).squeeze(-1) > 0
    
    # Get chain information
    asym_id = feats.get("asym_id", None)
    if asym_id is not None:
        if asym_id.dim() > 1:
            asym_id = asym_id[0]
        asym_id_np = asym_id.cpu().numpy() if isinstance(asym_id, torch.Tensor) else asym_id
    else:
        asym_id_np = None
    
    batch_size, n_residues = residue_template_mask.shape
    
    # First, find initial boundary residues (where template status changes)
    boundary_residues_initial = torch.zeros_like(residue_template_mask, dtype=torch.bool)
    
    for b in range(batch_size):
        for i in range(n_residues):
            # Check previous residue (only if same chain)
            if i > 0:
                if asym_id_np is None or asym_id_np[i] == asym_id_np[i-1]:
                    if residue_template_mask[b, i] != residue_template_mask[b, i-1]:
                        boundary_residues_initial[b, i] = True
                        boundary_residues_initial[b, i-1] = True
            
            # Check next residue (only if same chain)
            if i < n_residues - 1:
                if asym_id_np is None or asym_id_np[i] == asym_id_np[i+1]:
                    if residue_template_mask[b, i] != residue_template_mask[b, i+1]:
                        boundary_residues_initial[b, i] = True
                        boundary_residues_initial[b, i+1] = True
    
    # Expand boundary to include residues within boundary_window distance
    # This includes BOTH template side and generated side
    boundary_region_residues = torch.zeros_like(residue_template_mask, dtype=torch.bool)
    
    for b in range(batch_size):
        boundary_indices = torch.where(boundary_residues_initial[b])[0].cpu().numpy()
        
        if len(boundary_indices) == 0:
            continue
        
        for i in range(n_residues):
            min_distance = float('inf')
            
            for boundary_idx in boundary_indices:
                # Check if same chain
                if asym_id_np is not None and asym_id_np[i] != asym_id_np[boundary_idx]:
                    continue
                
                # Compute sequential distance within same chain
                if i < boundary_idx:
                    same_chain = True
                    for j in range(i, boundary_idx):
                        if asym_id_np is not None and j + 1 < len(asym_id_np):
                            if asym_id_np[j] != asym_id_np[j + 1]:
                                same_chain = False
                                break
                    if same_chain:
                        distance = boundary_idx - i
                    else:
                        distance = float('inf')
                elif i > boundary_idx:
                    same_chain = True
                    for j in range(boundary_idx, i):
                        if asym_id_np is not None and j + 1 < len(asym_id_np):
                            if asym_id_np[j] != asym_id_np[j + 1]:
                                same_chain = False
                                break
                    if same_chain:
                        distance = i - boundary_idx
                    else:
                        distance = float('inf')
                else:
                    distance = 0
                
                min_distance = min(min_distance, distance)
            
            # Include residue if within boundary_window distance (both sides)
            if min_distance <= boundary_window:
                boundary_region_residues[b, i] = True
    
    # Convert residue mask to atom mask
    boundary_atom_mask = (atom_to_token @ boundary_region_residues.unsqueeze(-1).float()).squeeze(-1) > 0
    
    return boundary_atom_mask


class DiffusionModule(Module):
    """Diffusion module"""

    def __init__(
        self,
        token_s: int,
        atom_s: int,
        atoms_per_window_queries: int = 32,
        atoms_per_window_keys: int = 128,
        sigma_data: int = 16,
        dim_fourier: int = 256,
        atom_encoder_depth: int = 3,
        atom_encoder_heads: int = 4,
        token_transformer_depth: int = 24,
        token_transformer_heads: int = 8,
        atom_decoder_depth: int = 3,
        atom_decoder_heads: int = 4,
        conditioning_transition_layers: int = 2,
        activation_checkpointing: bool = False,
        transformer_post_ln: bool = False,
    ) -> None:
        super().__init__()

        self.atoms_per_window_queries = atoms_per_window_queries
        self.atoms_per_window_keys = atoms_per_window_keys
        self.sigma_data = sigma_data
        self.activation_checkpointing = activation_checkpointing

        # conditioning
        self.single_conditioner = SingleConditioning(
            sigma_data=sigma_data,
            token_s=token_s,
            dim_fourier=dim_fourier,
            num_transitions=conditioning_transition_layers,
        )

        self.atom_attention_encoder = AtomAttentionEncoder(
            atom_s=atom_s,
            token_s=token_s,
            atoms_per_window_queries=atoms_per_window_queries,
            atoms_per_window_keys=atoms_per_window_keys,
            atom_encoder_depth=atom_encoder_depth,
            atom_encoder_heads=atom_encoder_heads,
            structure_prediction=True,
            activation_checkpointing=activation_checkpointing,
            transformer_post_layer_norm=transformer_post_ln,
        )

        self.s_to_a_linear = nn.Sequential(
            nn.LayerNorm(2 * token_s), LinearNoBias(2 * token_s, 2 * token_s)
        )
        init.final_init_(self.s_to_a_linear[1].weight)

        self.token_transformer = DiffusionTransformer(
            dim=2 * token_s,
            dim_single_cond=2 * token_s,
            depth=token_transformer_depth,
            heads=token_transformer_heads,
            activation_checkpointing=activation_checkpointing,
            # post_layer_norm=transformer_post_ln,
        )

        self.a_norm = nn.LayerNorm(
            2 * token_s
        )  # if not transformer_post_ln else nn.Identity()

        self.atom_attention_decoder = AtomAttentionDecoder(
            atom_s=atom_s,
            token_s=token_s,
            attn_window_queries=atoms_per_window_queries,
            attn_window_keys=atoms_per_window_keys,
            atom_decoder_depth=atom_decoder_depth,
            atom_decoder_heads=atom_decoder_heads,
            activation_checkpointing=activation_checkpointing,
            # transformer_post_layer_norm=transformer_post_ln,
        )

    def forward(
        self,
        s_inputs,  # Float['b n ts']
        s_trunk,  # Float['b n ts']
        r_noisy,  # Float['bm m 3']
        times,  # Float['bm 1 1']
        feats,
        diffusion_conditioning,
        multiplicity=1,
    ):
        if self.activation_checkpointing and self.training:
            s, normed_fourier = torch.utils.checkpoint.checkpoint(
                self.single_conditioner,
                times,
                s_trunk.repeat_interleave(multiplicity, 0),
                s_inputs.repeat_interleave(multiplicity, 0),
            )
        else:
            s, normed_fourier = self.single_conditioner(
                times,
                s_trunk.repeat_interleave(multiplicity, 0),
                s_inputs.repeat_interleave(multiplicity, 0),
            )

        # Sequence-local Atom Attention and aggregation to coarse-grained tokens
        a, q_skip, c_skip, to_keys = self.atom_attention_encoder(
            feats=feats,
            q=diffusion_conditioning["q"].float(),
            c=diffusion_conditioning["c"].float(),
            atom_enc_bias=diffusion_conditioning["atom_enc_bias"].float(),
            to_keys=diffusion_conditioning["to_keys"],
            r=r_noisy,  # Float['b m 3'],
            multiplicity=multiplicity,
        )

        # Full self-attention on token level
        a = a + self.s_to_a_linear(s)

        mask = feats["token_pad_mask"].repeat_interleave(multiplicity, 0)
        a = self.token_transformer(
            a,
            mask=mask.float(),
            s=s,
            bias=diffusion_conditioning[
                "token_trans_bias"
            ].float(),  # note z is not expanded with multiplicity until after bias is computed
            multiplicity=multiplicity,
        )
        a = self.a_norm(a)

        # Broadcast token activations to atoms and run Sequence-local Atom Attention
        r_update = self.atom_attention_decoder(
            a=a,
            q=q_skip,
            c=c_skip,
            atom_dec_bias=diffusion_conditioning["atom_dec_bias"].float(),
            feats=feats,
            multiplicity=multiplicity,
            to_keys=to_keys,
        )

        return r_update


class AtomDiffusion(Module):
    def __init__(
        self,
        score_model_args,
        num_sampling_steps: int = 5,  # number of sampling steps
        sigma_min: float = 0.0004,  # min noise level
        sigma_max: float = 160.0,  # max noise level
        sigma_data: float = 16.0,  # standard deviation of data distribution
        rho: float = 7,  # controls the sampling schedule
        P_mean: float = -1.2,  # mean of log-normal distribution from which noise is drawn for training
        P_std: float = 1.5,  # standard deviation of log-normal distribution from which noise is drawn for training
        gamma_0: float = 0.8,
        gamma_min: float = 1.0,
        noise_scale: float = 1.003,
        step_scale: float = 1.5,
        step_scale_random: list = None,
        coordinate_augmentation: bool = True,
        coordinate_augmentation_inference=None,
        compile_score: bool = False,
        alignment_reverse_diff: bool = False,
        synchronize_sigmas: bool = False,
        # Inpainting parameters
        template_noise_injection: bool = True,
    ):
        super().__init__()
        self.score_model = DiffusionModule(
            **score_model_args,
        )
        if compile_score:
            self.score_model = torch.compile(
                self.score_model, dynamic=False, fullgraph=False
            )

        # parameters
        self.sigma_min = sigma_min
        self.sigma_max = sigma_max
        self.sigma_data = sigma_data
        self.rho = rho
        self.P_mean = P_mean
        self.P_std = P_std
        self.num_sampling_steps = num_sampling_steps
        self.gamma_0 = gamma_0
        self.gamma_min = gamma_min
        self.noise_scale = noise_scale
        self.step_scale = step_scale
        self.step_scale_random = step_scale_random
        self.coordinate_augmentation = coordinate_augmentation
        self.coordinate_augmentation_inference = (
            coordinate_augmentation_inference
            if coordinate_augmentation_inference is not None
            else coordinate_augmentation
        )
        self.alignment_reverse_diff = alignment_reverse_diff
        self.synchronize_sigmas = synchronize_sigmas

        # Inpainting parameters
        self.template_noise_injection = template_noise_injection

        # Boundary refinement parameters (Global-to-Local Refinement)
        # After global diffusion, refine boundary regions with a short, focused diffusion
        self.boundary_refinement_enabled = True  # Enable boundary refinement for inpainting
        self.boundary_refinement_window = 2 # ±N residues from boundary to refine
        self.boundary_refinement_sigma_start = 1.5  # Start sigma for refinement (Å)
        self.boundary_refinement_steps = 25  # Number of refinement steps
        self.boundary_refinement_inpainting_region_mode = False  # If True, only refine inpainting region (generated side) of boundary

        self.token_s = score_model_args["token_s"]
        self.register_buffer("zero", torch.tensor(0.0), persistent=False)

    @property
    def device(self):
        return next(self.score_model.parameters()).device

    def c_skip(self, sigma):
        return (self.sigma_data**2) / (sigma**2 + self.sigma_data**2)

    def c_out(self, sigma):
        return sigma * self.sigma_data / torch.sqrt(self.sigma_data**2 + sigma**2)

    def c_in(self, sigma):
        return 1 / torch.sqrt(sigma**2 + self.sigma_data**2)

    def c_noise(self, sigma):
        return log(sigma / self.sigma_data) * 0.25

    def preconditioned_network_forward(
        self,
        noised_atom_coords,  #: Float['b m 3'],
        sigma,  #: Float['b'] | Float[' '] | float,
        network_condition_kwargs: dict,
    ):
        batch, device = noised_atom_coords.shape[0], noised_atom_coords.device

        if isinstance(sigma, float):
            sigma = torch.full((batch,), sigma, device=device)

        padded_sigma = rearrange(sigma, "b -> b 1 1")

        r_update = self.score_model(
            r_noisy=self.c_in(padded_sigma) * noised_atom_coords,
            times=self.c_noise(sigma),
            **network_condition_kwargs,
        )

        denoised_coords = (
            self.c_skip(padded_sigma) * noised_atom_coords
            + self.c_out(padded_sigma) * r_update
        )
        return denoised_coords

    def sample_schedule(self, num_sampling_steps=None, sigma_max_override=None):
        num_sampling_steps = default(num_sampling_steps, self.num_sampling_steps)
        inv_rho = 1 / self.rho
        
        # Use override sigma_max if provided, otherwise use default
        sigma_max = default(sigma_max_override, self.sigma_max)

        steps = torch.arange(
            num_sampling_steps, device=self.device, dtype=torch.float32
        )
        sigmas = (
            sigma_max**inv_rho
            + steps
            / (num_sampling_steps - 1)
            * (self.sigma_min**inv_rho - sigma_max**inv_rho)
        ) ** self.rho

        sigmas = sigmas * self.sigma_data

        sigmas = F.pad(sigmas, (0, 1), value=0.0)  # last step is sigma value of 0.
        return sigmas

    def inject_template_noise(
        self,
        template_coords_clean,
        current_sigma,
        template_mask,
    ):
        """
        Inject noise into template coordinates to match current noise level.

        The known (template) region needs to have the same noise level as the
        generated region to be properly merged during inpainting.
        
        Args:
            template_coords_clean: Clean template coordinates (no noise)
            current_sigma: Current sigma value (noise level)
            template_mask: Boolean mask for template atoms
        
        Returns:
            Template coordinates with noise added
        """
        noise = torch.randn_like(template_coords_clean) * current_sigma
        template_coords_noisy = template_coords_clean + noise
        return template_coords_noisy

    def sample(
        self,
        atom_mask,
        num_sampling_steps=None,
        multiplicity=1,
        max_parallel_samples=None,
        steering_args=None,
        progress_tracker=None,
        # Boundary refinement parameters (can override class defaults)
        boundary_refinement_enabled=None,
        boundary_refinement_window=None,
        boundary_refinement_sigma_start=None,
        boundary_refinement_steps=None,
        boundary_refinement_inpainting_region_mode=None,
        **network_condition_kwargs,
    ):
        # Extract inpainting information if available
        feats = network_condition_kwargs.get("feats", {})
        inpainting_template_coords = feats.get("inpainting_template_coords", None)
        inpainting_template_mask = feats.get("inpainting_template_mask", None)
        enable_inpainting = (
            inpainting_template_coords is not None
            and inpainting_template_mask is not None
        )

        if enable_inpainting:
            print(
                f"[Inpainting] Diffusion will fix {inpainting_template_mask.sum().item()} template atoms"
            )

        if steering_args is not None and (
            steering_args["fk_steering"]
            or steering_args["physical_guidance_update"]
            or steering_args["contact_guidance_update"]
            or steering_args.get("inpainting", False)
        ):
            potentials = get_potentials(steering_args, boltz2=True)

        if steering_args["fk_steering"]:
            multiplicity = multiplicity * steering_args["num_particles"]
            energy_traj = torch.empty((multiplicity, 0), device=self.device)
            resample_weights = torch.ones(multiplicity, device=self.device).reshape(
                -1, steering_args["num_particles"]
            )
        if (
            steering_args["physical_guidance_update"]
            or steering_args["contact_guidance_update"]
            or steering_args.get("inpainting", False)
        ):
            scaled_guidance_update = torch.zeros(
                (multiplicity, *atom_mask.shape[1:], 3),
                dtype=torch.float32,
                device=self.device,
            )
        if max_parallel_samples is None:
            max_parallel_samples = multiplicity

        num_sampling_steps = default(num_sampling_steps, self.num_sampling_steps)
        atom_mask = atom_mask.repeat_interleave(multiplicity, 0)

        shape = (*atom_mask.shape, 3)
        sigmas = self.sample_schedule(num_sampling_steps)
        gammas = torch.where(sigmas > self.gamma_min, self.gamma_0, 0.0)
        
        schedule = [(i, i+1, 'backward') for i in range(len(sigmas) - 1)]
        
        if self.training and self.step_scale_random is not None:
            step_scale = np.random.choice(self.step_scale_random)
        else:
            step_scale = self.step_scale

        # atom position is noise at the beginning
        init_sigma = sigmas[0]
        atom_coords = init_sigma * torch.randn(shape, device=self.device)

        # Inpainting: Initialize template atoms with template coordinates
        if enable_inpainting:
            # Repeat template coords and mask for multiplicity
            template_coords_expanded = inpainting_template_coords.repeat_interleave(
                multiplicity, 0
            )
            template_mask_expanded = inpainting_template_mask.repeat_interleave(
                multiplicity, 0
            )
            
            # Store original template coordinates for final alignment back to original coordinate system
            # This is needed because we transform template along with noisy coords during diffusion
            template_coords_original = template_coords_expanded.clone()

        token_repr = None
        atom_coords_denoised = None

        # Update progress: diffusion started (40%)
        if progress_tracker:
            progress_tracker.update_diffusion_progress("Starting diffusion", 0, len(schedule))

        # gradually denoise
        for step_idx, (idx_from, idx_to, _) in tqdm(enumerate(schedule), total=len(schedule), desc="Diffusion Steps"):
            # Get sigma values from indices
            sigma_from = sigmas[idx_from].item()
            sigma_to = sigmas[idx_to].item()

            # Get gamma for this step
            gamma = gammas[idx_to].item() if idx_to < len(gammas) else 0.0
            # Inpainting: inject noise into template atoms to match current noise level
            if enable_inpainting and self.template_noise_injection:
                # Inject noise into template coordinates
                template_noise = self.inject_template_noise(
                    template_coords_expanded[template_mask_expanded],
                    sigma_from,
                    template_mask_expanded[template_mask_expanded],
                )
                atom_coords[template_mask_expanded] = template_noise
            
            if self.coordinate_augmentation and not enable_inpainting:
                # Normal mode: center + random augmentation
                random_R, random_tr = compute_random_augmentation(
                    multiplicity, device=atom_coords.device, dtype=atom_coords.dtype
                )
                atom_coords = atom_coords - atom_coords.mean(dim=-2, keepdims=True)
                atom_coords = (
                    torch.einsum("bmd,bds->bms", atom_coords, random_R) + random_tr
                )
                if atom_coords_denoised is not None:
                    atom_coords_denoised -= atom_coords_denoised.mean(
                        dim=-2, keepdims=True
                    )
                    atom_coords_denoised = (
                        torch.einsum("bmd,bds->bms", atom_coords_denoised, random_R)
                        + random_tr
                    )
                if (
                    steering_args is not None
                    and (
                        steering_args["physical_guidance_update"]
                        or steering_args["contact_guidance_update"]
                    )
                    and scaled_guidance_update is not None
                ):
                    scaled_guidance_update = torch.einsum(
                        "bmd,bds->bms", scaled_guidance_update, random_R
                    )

            sigma_tm = sigma_from
            sigma_t = sigma_to

            t_hat = sigma_tm * (1 + gamma)
            steering_t = 1.0 - (step_idx / num_sampling_steps)
            noise_var = self.noise_scale**2 * (t_hat**2 - sigma_tm**2)
            eps = sqrt(noise_var) * torch.randn(shape, device=self.device)
            atom_coords_noisy = atom_coords + eps
            # Apply scaled_guidance_update from previous step to current noisy coordinates
            if (
                steering_args is not None
                and (
                    steering_args["physical_guidance_update"]
                    or steering_args["contact_guidance_update"]
                    or steering_args.get("inpainting", False)
                )
                and scaled_guidance_update is not None
            ):
                atom_coords_noisy = atom_coords_noisy + scaled_guidance_update

            with torch.no_grad():
                atom_coords_denoised = torch.zeros_like(atom_coords_noisy)
                sample_ids = torch.arange(multiplicity).to(atom_coords_noisy.device)
                sample_ids_chunks = sample_ids.chunk(
                    multiplicity % max_parallel_samples + 1
                )

                for sample_ids_chunk in sample_ids_chunks:
                    atom_coords_denoised[sample_ids_chunk] = self.preconditioned_network_forward(
                        atom_coords_noisy[sample_ids_chunk],
                        t_hat,
                        network_condition_kwargs=dict(
                            multiplicity=sample_ids_chunk.numel(),
                            **network_condition_kwargs,
                        ),
                    )

                if steering_args["fk_steering"] and (
                    (
                        step_idx % steering_args["fk_resampling_interval"] == 0
                        and noise_var > 0
                    )
                    or step_idx == num_sampling_steps - 1
                ):
                    # Compute energy of x_0 prediction
                    energy = torch.zeros(multiplicity, device=self.device)
                    for potential in potentials:
                        parameters = potential.compute_parameters(steering_t)
                        if parameters["resampling_weight"] > 0:
                            component_energy = potential.compute(
                                atom_coords_denoised,
                                network_condition_kwargs["feats"],
                                parameters,
                            )
                            energy += parameters["resampling_weight"] * component_energy
                    energy_traj = torch.cat((energy_traj, energy.unsqueeze(1)), dim=1)

                    # Compute log G values
                    if step_idx == 0:
                        log_G = -1 * energy
                    else:
                        log_G = energy_traj[:, -2] - energy_traj[:, -1]

                    # Compute ll difference between guided and unguided transition distribution
                    if (
                        steering_args["physical_guidance_update"]
                        or steering_args["contact_guidance_update"]
                        or steering_args.get("inpainting", False)
                    ) and noise_var > 0:
                        ll_difference = (
                            eps**2 - (eps + scaled_guidance_update) ** 2
                        ).sum(dim=(-1, -2)) / (2 * noise_var)
                    else:
                        ll_difference = torch.zeros_like(energy)

                    # Compute resampling weights
                    resample_weights = F.softmax(
                        (ll_difference + steering_args["fk_lambda"] * log_G).reshape(
                            -1, steering_args["num_particles"]
                        ),
                        dim=1,
                    )

                # Compute guidance update to x_0 prediction
                if (
                    steering_args is not None
                    and (
                        steering_args.get("physical_guidance_update", False)
                        or steering_args.get("contact_guidance_update", False)
                        or steering_args.get("inpainting", False)
                    )
                    and step_idx < num_sampling_steps - 1
                ):
                    # Log distances BEFORE guidance update for boundary peptide bonds
                    boundary_dist_before = None
                    boundary_potential = None
                    for potential in potentials:
                        if hasattr(potential, 'boundary_pairs') and hasattr(potential, 'last_index'):
                            if len(potential.boundary_pairs) > 0 and potential.last_index is not None and potential.last_index.shape[1] > 0:
                                boundary_potential = potential
                                c_coords = atom_coords_denoised[0, potential.last_index[0], :]
                                n_coords = atom_coords_denoised[0, potential.last_index[1], :]
                                boundary_dist_before = torch.linalg.norm(c_coords - n_coords, dim=-1)
                                break
                    
                    guidance_update = torch.zeros_like(atom_coords_denoised)
                    for guidance_step in range(steering_args["num_gd_steps"]):
                        energy_gradient = torch.zeros_like(atom_coords_denoised)
                        for potential in potentials:
                            parameters = potential.compute_parameters(steering_t)
                            # Add step_idx and guidance_step to parameters so potential can use them for logging
                            parameters["step_idx"] = step_idx
                            parameters["guidance_step"] = guidance_step
                            parameters["is_last_guidance_step"] = (guidance_step == steering_args["num_gd_steps"] - 1)
                            if (
                                parameters["guidance_weight"] > 0
                                and (guidance_step) % parameters["guidance_interval"]
                                == 0
                            ):
                                energy_gradient += parameters[
                                    "guidance_weight"
                                ] * potential.compute_gradient(
                                    atom_coords_denoised + guidance_update,
                                    network_condition_kwargs["feats"],
                                    parameters,
                                )
                        guidance_update -= energy_gradient
                    
                    # Log guidance_update magnitude before applying
                    guidance_update_mags = None
                    if boundary_potential is not None:
                        # Calculate magnitude for each pair: combine C and N atom guidance updates
                        c_guid = guidance_update[0, boundary_potential.last_index[0], :]  # (num_pairs, 3)
                        n_guid = guidance_update[0, boundary_potential.last_index[1], :]  # (num_pairs, 3)
                        # Magnitude of the combined effect (relative movement between C and N)
                        relative_guid = c_guid - n_guid  # (num_pairs, 3)
                        guidance_update_mags = torch.linalg.norm(relative_guid, dim=-1)  # (num_pairs,)
                        max_guidance_mag = guidance_update_mags.max().item()
                        if step_idx % 10 == 0 or step_idx == num_sampling_steps - 1:
                            print(f"[InpaintingBoundaryPeptideBond] Diffusion step {step_idx} : guidance_update magnitude (max={max_guidance_mag:.6f})")
                    
                    # Log distances AFTER guidance update for boundary peptide bonds
                    if boundary_potential is not None and boundary_dist_before is not None:
                        c_coords_after = (atom_coords_denoised + guidance_update)[0, boundary_potential.last_index[0], :]
                        n_coords_after = (atom_coords_denoised + guidance_update)[0, boundary_potential.last_index[1], :]
                        boundary_dist_after = torch.linalg.norm(c_coords_after - n_coords_after, dim=-1)
                        
                        # Log only occasionally to avoid spam
                        if step_idx % 10 == 0 or step_idx == num_sampling_steps - 1:
                            dist_before_list = boundary_dist_before.cpu().tolist()
                            dist_after_list = boundary_dist_after.cpu().tolist()
                            guid_mags_list = guidance_update_mags.cpu().tolist() if guidance_update_mags is not None else [0.0] * len(dist_before_list)
                            print(f"[InpaintingBoundaryPeptideBond] Diffusion step {step_idx} : guidance_update applied")
                            for i, pair in enumerate(boundary_potential.boundary_pairs):
                                res_i, res_i1 = pair[2], pair[3]
                                dist_before = dist_before_list[i]
                                dist_after = dist_after_list[i]
                                change = dist_after - dist_before
                                guid_mag = guid_mags_list[i]
                                print(f"  Res{res_i+1}-Res{res_i1+1}: before={dist_before:.3f}Å, after={dist_after:.3f}Å, change={change:+.3f}Å, guid_mag={guid_mag:.6f}")
                    
                    atom_coords_denoised += guidance_update
                    scaled_guidance_update = (
                        guidance_update
                        * -1
                        * self.step_scale
                        * (sigma_t - t_hat)
                        / t_hat
                    )
                
                # Log potential for last step even if guidance update is not computed
                if (
                    step_idx == num_sampling_steps - 1
                    and steering_args is not None
                    and (
                        steering_args.get("physical_guidance_update", False)
                        or steering_args.get("contact_guidance_update", False)
                        or steering_args.get("inpainting", False)
                    )
                ):
                    # Log potential state for the last step
                    for potential in potentials:
                        parameters = potential.compute_parameters(steering_t)
                        parameters["step_idx"] = step_idx
                        parameters["guidance_step"] = 0
                        parameters["is_last_guidance_step"] = True
                        parameters["is_last_step"] = True  # Force logging on last step
                        # Call compute_gradient with zero weight to trigger logging
                        if hasattr(potential, 'compute_gradient'):
                            _ = potential.compute_gradient(
                                atom_coords_denoised,
                                network_condition_kwargs["feats"],
                                parameters,
                            )
                        
                if steering_args is not None and steering_args.get("fk_steering", False) and (
                    (
                        step_idx % steering_args["fk_resampling_interval"] == 0
                        and noise_var > 0
                    )
                    or step_idx == num_sampling_steps - 1
                ):
                    resample_indices = (
                        torch.multinomial(
                            resample_weights,
                            (
                                resample_weights.shape[1]
                                if step_idx < num_sampling_steps - 1
                                else 1
                            ),
                            replacement=True,
                        )
                        + resample_weights.shape[1]
                        * torch.arange(
                            resample_weights.shape[0], device=resample_weights.device
                        ).unsqueeze(-1)
                    ).flatten()

                    atom_coords = atom_coords[resample_indices]
                    atom_coords_noisy = atom_coords_noisy[resample_indices]
                    atom_mask = atom_mask[resample_indices]
                    if atom_coords_denoised is not None:
                        atom_coords_denoised = atom_coords_denoised[resample_indices]
                    energy_traj = energy_traj[resample_indices]
                    if (
                        steering_args["physical_guidance_update"]
                        or steering_args["contact_guidance_update"]
                        or steering_args.get("inpainting", False)
                    ):
                        scaled_guidance_update = scaled_guidance_update[
                            resample_indices
                        ]
                    if token_repr is not None:
                        token_repr = token_repr[resample_indices]

            # Kabsch diffusion interpolation (alignment before interpolation)
            # 
            # Mathematical Framework:
            # =======================
            # weighted_rigid_align(A, B, ...) transforms A to align with B:
            #   aligned = R @ (A - centroid_A) + centroid_B
            # 
            # The interpolation formula is:
            #   x_{t-1} = x_t + s * (σ_{t-1} - t̂) * (x_t - x̂_0) / t̂
            # 
            # For this to work correctly, x_t and x̂_0 must be in the same coordinate system.
            #
            # Both Normal and Inpainting modes now use the same approach:
            # ============================================================
            # 1. Align noisy → denoised: x_t' = align(x_t, x̂_0)
            # 2. For Inpainting: Transform template with same (R, t):
            #    T' = R @ (T - centroid_noisy) + centroid_denoised
            # 3. Interpolate in denoised's coordinate system
            # 4. Template injection uses transformed template T'
            #
            # Mathematical Equivalence:
            # =========================
            # Let R₁ be the rotation for align(denoised→noisy), R₂ for align(noisy→denoised)
            # Then R₁ = R₂ᵀ (inverse rotation)
            # 
            # The key relationship: (x_t' - x̂_0) = R₂ @ (x_t - x̂_0')
            # where x̂_0' is denoised aligned to noisy's coordinate system.
            # 
            # This means both approaches produce structurally identical results,
            # just in different coordinate systems.
            #
            # Why use this approach for Inpainting?
            # =====================================
            # 1. Model's prediction x̂_0 is the "ideal answer" - interpolating in its
            #    coordinate system respects the model's learned representations
            # 2. Consistency: Same logic as Normal mode, easier to reason about
            # 3. The denoised_over_sigma vector = (x_t' - x̂_0)/t̂ is computed in the
            #    coordinate system where the model made its prediction
            #
            # Floating Point Considerations:
            # ==============================
            # Each step applies a new transformation to the template. Over 200+ steps,
            # errors could accumulate. However:
            # - Each transformation is computed fresh from the current state
            # - Template is re-noised each step anyway, so sub-angstrom drift is negligible
            # - Final coordinates can be aligned back to original template if needed
            if self.alignment_reverse_diff:
                with torch.autocast("cuda", enabled=False):
                    if not enable_inpainting:
                        # Normal: Move current state toward model's prediction
                        atom_coords_noisy = weighted_rigid_align(
                            atom_coords_noisy.float(),
                            atom_coords_denoised.float(),
                            atom_mask.float(),
                            atom_mask.float(),
                        )
                        atom_coords_noisy = atom_coords_noisy.to(atom_coords_denoised)
                    else:
                        # Inpainting: Same as Normal, but also transform template
                        # 
                        # Step 1: Align noisy → denoised and get transformation
                        atom_coords_noisy_aligned, rot_matrix, src_centroid, tgt_centroid = weighted_rigid_align(
                            atom_coords_noisy.float(),
                            atom_coords_denoised.float(),
                            atom_mask.float(),
                            atom_mask.float(),
                            return_transform=True,
                        )
                        
                        # Step 2: Apply same transformation to template coordinates
                        # This keeps template and generated parts in the same coordinate system
                        template_coords_expanded = apply_rigid_transform(
                            template_coords_expanded.float(),
                            rot_matrix,
                            src_centroid,
                            tgt_centroid,
                        )
                        template_coords_expanded = template_coords_expanded.to(atom_coords_noisy)
                        
                        # Step 3: Update noisy coordinates
                        atom_coords_noisy = atom_coords_noisy_aligned.to(atom_coords_denoised)

            # Compute denoised_over_sigma
            denoised_over_sigma = (atom_coords_noisy - atom_coords_denoised) / t_hat
            atom_coords_next = (
                atom_coords_noisy + step_scale * (sigma_t - t_hat) * denoised_over_sigma
            )



            atom_coords = atom_coords_next

            # Inpainting: reset template atoms to exact current-frame positions after each step.
            # Backbone is already correct (conditioned via template_ca/frame features),
            # but sidechain and ligand atoms drift because the network has no per-atom
            # conditioning for them. Resetting here ensures the inpainted region is always
            # generated in the context of correctly-positioned template atoms.
            if enable_inpainting:
                atom_coords[template_mask_expanded] = (
                    template_coords_expanded[template_mask_expanded].to(atom_coords)
                )

            # Update progress: diffusion step completed (40-100%)
            if progress_tracker:
                progress_tracker.update_diffusion_progress(
                    f"Diffusion step {step_idx + 1}/{len(schedule)}",
                    step_idx + 1,
                    len(schedule)
                )

        # Update progress: diffusion completed (100%)
        if progress_tracker:
            progress_tracker.update_diffusion_progress("Diffusion completed", len(schedule), len(schedule))

        # ===================================================================
        # Stage 2: Boundary Refinement (Global-to-Local Refinement)
        # ===================================================================
        # After global diffusion, refine only the boundary region with a short,
        # focused diffusion. This helps to:
        # 1. Smooth out the transition between template and generated regions
        # 2. Improve peptide bond geometry at boundaries
        # 3. Allow boundary atoms to find geometrically stable positions
        #
        # Process:
        # 1. Create a new template mask that fixes EVERYTHING except boundary region
        # 2. Add noise to boundary atoms starting from medium sigma (e.g., 2.0Å)
        # 3. Run short diffusion (10-20 steps) to refine boundary only
        # ===================================================================
        
        # Use provided parameters or fall back to class defaults
        _boundary_refinement_enabled = default(boundary_refinement_enabled, self.boundary_refinement_enabled)
        _boundary_refinement_window = default(boundary_refinement_window, self.boundary_refinement_window)
        _boundary_refinement_sigma_start = default(boundary_refinement_sigma_start, self.boundary_refinement_sigma_start)
        _boundary_refinement_steps = default(boundary_refinement_steps, self.boundary_refinement_steps)
        _boundary_refinement_inpainting_region_mode = default(boundary_refinement_inpainting_region_mode, self.boundary_refinement_inpainting_region_mode)
        
        if enable_inpainting and _boundary_refinement_enabled:
            print(f"\n[Inpainting] Starting Stage 2: Boundary Refinement")
            print(f"  - Boundary window: ±{_boundary_refinement_window} residues")
            print(f"  - Starting sigma: {_boundary_refinement_sigma_start}Å")
            print(f"  - Refinement steps: {_boundary_refinement_steps}")
            print(f"  - Inpainting region mode: {_boundary_refinement_inpainting_region_mode}")
            
            # Get boundary region mask (atoms within ±N residues of boundary)
            # Use the ORIGINAL template mask to identify boundaries
            boundary_region_mask = get_boundary_region_mask(
                inpainting_template_mask.repeat_interleave(multiplicity, 0),
                feats,
                boundary_window=_boundary_refinement_window
            )
            
            # Restrict boundary refinement to PROTEIN only (exclude DNA, RNA, non-polymer/ligand)
            if "mol_type" in feats and "atom_to_token" in feats:
                atom_to_token = feats["atom_to_token"].float()  # (batch, n_atoms, n_residues)
                mol_type = feats["mol_type"].float()  # (batch, n_residues)
                atom_type = torch.bmm(atom_to_token, mol_type.unsqueeze(-1)).squeeze(-1)  # (batch, n_atoms)
                protein_atom_mask = atom_type == const.chain_type_ids["PROTEIN"]
                protein_atom_mask = protein_atom_mask.repeat_interleave(multiplicity, 0)
                boundary_region_mask = boundary_region_mask & protein_atom_mask
                print(f"  - Boundary refinement: PROTEIN only (DNA, RNA, ligand excluded)")

            # Exclude modification (PTM) residues from local refinement
            if "modified" in feats and "atom_to_token" in feats and feats["modified"] is not None:
                atom_to_token = feats["atom_to_token"].float()  # (batch, n_atoms, n_residues)
                modified_tokens = feats["modified"].float()  # (batch, n_residues)
                if modified_tokens.dim() == 1:
                    modified_tokens = modified_tokens.unsqueeze(0)
                # (batch, n_atoms): atom is in a modified residue if its token has modified=1
                atom_modified = (torch.bmm(atom_to_token, modified_tokens.unsqueeze(-1)).squeeze(-1) > 0)
                atom_modified = atom_modified.repeat_interleave(multiplicity, 0)
                boundary_region_mask = boundary_region_mask & (~atom_modified)
                print(f"  - Boundary refinement: modification (PTM) residues excluded from refinement")
            
            # If inpainting region mode is enabled, restrict refinement to inpainting region only
            # (i.e., generated side of boundary, not template side)
            if _boundary_refinement_inpainting_region_mode:
                # Inpainting region = atoms that are NOT in template (generated atoms)
                inpainting_region_mask = ~inpainting_template_mask.repeat_interleave(multiplicity, 0)
                # Refinement region = boundary region AND inpainting region
                boundary_region_mask = boundary_region_mask & inpainting_region_mask
                print(f"  - Restricted to inpainting region (generated side only)")
            
            # Count boundary atoms
            boundary_atom_count = boundary_region_mask[0].sum().item()
            total_atom_count = atom_mask[0].sum().item()
            print(f"  - Boundary atoms to refine: {boundary_atom_count} / {total_atom_count}")

            # ── BOUNDARY MASK DEBUG ──
            _atom_to_token = feats["atom_to_token"].float()  # (batch, n_atoms, n_residues)
            _res_tmpl = ((_atom_to_token[0].T) @ inpainting_template_mask[0].unsqueeze(-1).float()).squeeze(-1) > 0
            _n_res = _res_tmpl.shape[0]
            _n_atoms_total = int(atom_mask[0].sum().item())
            print(f"  [BND-DEBUG] N_tokens={_n_res}, N_atoms={_n_atoms_total}")
            print(f"  [BND-DEBUG] Template tokens: {_res_tmpl.sum().item()}/{_n_res}")
            # Generated token ranges
            _gen_ranges = []
            _in_gen = False
            _gen_start = 0
            for _i in range(_n_res):
                if not _res_tmpl[_i] and not _in_gen:
                    _gen_start = _i
                    _in_gen = True
                elif _res_tmpl[_i] and _in_gen:
                    _gen_ranges.append(f"{_gen_start}-{_i-1}")
                    _in_gen = False
            if _in_gen:
                _gen_ranges.append(f"{_gen_start}-{_n_res-1}")
            print(f"  [BND-DEBUG] Generated token ranges: {', '.join(_gen_ranges) if _gen_ranges else 'none'}")
            # Boundary initial tokens
            _bnd_init = []
            _asym = feats.get("asym_id", None)
            if _asym is not None:
                if _asym.dim() > 1:
                    _asym = _asym[0]
                _asym_np = _asym.cpu().numpy()
            else:
                _asym_np = None
            for _i in range(_n_res):
                if _i > 0:
                    if _asym_np is None or _asym_np[_i] == _asym_np[_i-1]:
                        if _res_tmpl[_i] != _res_tmpl[_i-1]:
                            _bnd_init.extend([_i-1, _i])
            _bnd_init = sorted(set(_bnd_init))
            print(f"  [BND-DEBUG] Boundary init tokens: {_bnd_init}")
            # Expanded boundary tokens
            _bnd_res = boundary_region_mask[0]  # atom-level
            # Map atom mask to token: which tokens have at least one boundary atom?
            _bnd_token_mask = ((_atom_to_token[0].T) @ _bnd_res.unsqueeze(-1).float()).squeeze(-1) > 0
            _bnd_expanded_toks = torch.where(_bnd_token_mask)[0].tolist()
            print(f"  [BND-DEBUG] Boundary expanded tokens (window={_boundary_refinement_window}): {_bnd_expanded_toks}")
            # Per-token atom counts
            _tok_details = []
            for _ti in _bnd_expanded_toks:
                _tok_atoms = _atom_to_token[0, :, _ti]  # (n_atoms,) - which atoms belong to this token
                _n_total = int(_tok_atoms.sum().item())
                _n_bnd = int((_tok_atoms.bool() & _bnd_res).sum().item())
                _is_tmpl = "T" if _res_tmpl[_ti] else "G"
                _tok_details.append(f"{_ti}({_is_tmpl}):{_n_bnd}/{_n_total}")
            print(f"  [BND-DEBUG] Per-token boundary atoms: {_tok_details}")

            if boundary_atom_count > 0:
                # Create refinement template mask: fix everything EXCEPT boundary region
                # Template atoms that are NOT in boundary region remain fixed
                refinement_template_mask = ~boundary_region_mask
                
                # Store current coordinates as the new "template" for refinement
                refinement_template_coords = atom_coords.clone()
                
                # Generate refinement schedule (shorter, starting from lower sigma)
                refinement_sigmas = self.sample_schedule(
                    num_sampling_steps=_boundary_refinement_steps,
                    sigma_max_override=_boundary_refinement_sigma_start / self.sigma_data  # Normalize
                )
                refinement_gammas = torch.where(
                    refinement_sigmas > self.gamma_min, self.gamma_0, 0.0
                )
                
                print(f"  [BOLTZ-LRD] Schedule ({_boundary_refinement_steps} steps): "
                      f"σ_start={refinement_sigmas[0].item():.4f}, "
                      f"σ_end={refinement_sigmas[-2].item():.4f}, σ_final=0")
                print(f"  [BOLTZ-LRD] Params: gamma_0={self.gamma_0}, gamma_min={self.gamma_min}, "
                      f"noise_scale={self.noise_scale}, step_scale={step_scale}")
                print(f"  [BOLTZ-LRD] sigma_min={self.sigma_min}, "
                      f"sigma_max_override={_boundary_refinement_sigma_start / self.sigma_data:.6f}, "
                      f"rho={self.rho}")

                # Add noise ONLY to boundary region atoms
                init_refinement_sigma = refinement_sigmas[0]
                boundary_noise = init_refinement_sigma * torch.randn_like(atom_coords)
                # Only add noise to boundary region
                atom_coords_refinement = atom_coords.clone()
                atom_coords_refinement[boundary_region_mask] = (
                    atom_coords[boundary_region_mask] + boundary_noise[boundary_region_mask]
                )

                # Save pre-refinement coords for comparison
                _dbg_pre_refine = atom_coords[0].clone()

                print(f"  [BOLTZ-LRD] Init noise σ={init_refinement_sigma.item():.4f} applied to "
                      f"{boundary_atom_count} boundary atoms")

                # Simple backward schedule for refinement
                refinement_schedule = [(i, i+1, 'backward') for i in range(len(refinement_sigmas) - 1)]

                # Refinement diffusion loop
                atom_coords_denoised_ref = None
                for step_idx, schedule_item in tqdm(
                    enumerate(refinement_schedule),
                    total=len(refinement_schedule),
                    desc="Boundary Refinement"
                ):
                    idx_from, idx_to, direction = schedule_item

                    sigma_from = refinement_sigmas[idx_from].item()
                    sigma_to = refinement_sigmas[idx_to].item()
                    gamma = refinement_gammas[idx_to].item() if idx_to < len(refinement_gammas) else 0.0

                    # For refinement: inject noise to non-boundary (fixed) atoms
                    # to match current noise level for consistency
                    if self.template_noise_injection:
                        fixed_noise = torch.randn_like(refinement_template_coords) * sigma_from
                        # Fixed atoms = everything except boundary region
                        fixed_mask = refinement_template_mask
                        atom_coords_refinement[fixed_mask] = (
                            refinement_template_coords[fixed_mask] + fixed_noise[fixed_mask]
                        )

                    # Denoising step
                    sigma_tm = sigma_from
                    sigma_t = sigma_to
                    t_hat = sigma_tm * (1 + gamma)

                    noise_var = self.noise_scale**2 * (t_hat**2 - sigma_tm**2)
                    eps = sqrt(noise_var) * torch.randn(shape, device=self.device)
                    atom_coords_noisy_ref = atom_coords_refinement + eps

                    with torch.no_grad():
                        atom_coords_denoised_ref = torch.zeros_like(atom_coords_noisy_ref)
                        sample_ids = torch.arange(multiplicity).to(atom_coords_noisy_ref.device)
                        sample_ids_chunks = sample_ids.chunk(
                            multiplicity % max_parallel_samples + 1
                        )

                        for sample_ids_chunk in sample_ids_chunks:
                            denoised_chunk = self.preconditioned_network_forward(
                                atom_coords_noisy_ref[sample_ids_chunk],
                                t_hat,
                                network_condition_kwargs=dict(
                                    multiplicity=sample_ids_chunk.numel(),
                                    **network_condition_kwargs,
                                ),
                            )
                            atom_coords_denoised_ref[sample_ids_chunk] = denoised_chunk

                        # Kabsch alignment (same as main loop)
                        if self.alignment_reverse_diff:
                            with torch.autocast("cuda", enabled=False):
                                atom_coords_noisy_ref_aligned, rot_matrix, src_centroid, tgt_centroid = weighted_rigid_align(
                                    atom_coords_noisy_ref.float(),
                                    atom_coords_denoised_ref.float(),
                                    atom_mask.float(),
                                    atom_mask.float(),
                                    return_transform=True,
                                )

                                # Transform refinement template coordinates with same rotation
                                refinement_template_coords = apply_rigid_transform(
                                    refinement_template_coords.float(),
                                    rot_matrix,
                                    src_centroid,
                                    tgt_centroid,
                                )
                                refinement_template_coords = refinement_template_coords.to(atom_coords_noisy_ref)

                                atom_coords_noisy_ref = atom_coords_noisy_ref_aligned.to(atom_coords_denoised_ref)

                        # Interpolation step
                        denoised_over_sigma = (atom_coords_noisy_ref - atom_coords_denoised_ref) / t_hat
                        atom_coords_next_ref = (
                            atom_coords_noisy_ref + step_scale * (sigma_t - t_hat) * denoised_over_sigma
                        )

                        atom_coords_refinement = atom_coords_next_ref

                    # DEBUG: detailed per-step logging (matching protenix format)
                    _c = atom_coords_refinement[0]
                    _c_tmpl = refinement_template_coords[0]
                    _bnd_disp = (_c.float() - _c_tmpl.float())[boundary_region_mask[0]].norm(dim=-1)
                    _denoise_mag = (atom_coords_noisy_ref[0].float() - atom_coords_denoised_ref[0].float()).norm(dim=-1).mean()
                    print(f"  [BOLTZ-LRD step {step_idx+1:2d}/{len(refinement_schedule)}] "
                          f"σ={sigma_from:.4f}→{sigma_to:.4f}, "
                          f"t_hat={t_hat:.4f}, γ={gamma:.2f}, "
                          f"noise_var={noise_var:.6f}, "
                          f"bnd_disp: mean={_bnd_disp.mean():.3f} max={_bnd_disp.max():.3f}Å, "
                          f"denoise_mag={_denoise_mag:.3f}Å")

                # After refinement: combine refined boundary with fixed regions
                # For non-boundary atoms, use the transformed refinement template
                # For boundary atoms, use the refined coordinates
                atom_coords_final = refinement_template_coords.clone()
                atom_coords_final[boundary_region_mask] = atom_coords_refinement[boundary_region_mask]

                # DEBUG: post-LRD displacement
                _dbg_post_refine = atom_coords_final[0]
                _total_displacement = (_dbg_post_refine.float() - _dbg_pre_refine.float()).norm(dim=-1)
                _boundary_only = _total_displacement[boundary_region_mask[0]]
                _fixed_only = _total_displacement[~boundary_region_mask[0]]
                print(f"  [BOLTZ-LRD] Overall boundary displacement (pre→post): "
                      f"mean={_boundary_only.mean():.3f}Å, "
                      f"max={_boundary_only.max():.3f}Å, "
                      f"min={_boundary_only.min():.3f}Å")
                print(f"  [BOLTZ-LRD] Fixed atom drift (pre→post): "
                      f"mean={_fixed_only.mean():.3f}Å, "
                      f"max={_fixed_only.max():.3f}Å")

                # Use the refined coordinates
                atom_coords = atom_coords_final

                # Also update template_coords_expanded to reflect transformations
                # (needed for final alignment back to original coordinate system)
                template_coords_expanded = refinement_template_coords

                print(f"[Inpainting] Boundary refinement completed")

                # Add boundary refinement metadata
                if "inpainting_metadata" not in feats:
                    feats["inpainting_metadata"] = {}
                feats["inpainting_metadata"]["boundary_refinement"] = {
                    "enabled": True,
                    "boundary_window": int(_boundary_refinement_window),
                    "sigma_start": float(_boundary_refinement_sigma_start),
                    "num_steps": int(_boundary_refinement_steps),
                    "boundary_atoms_refined": int(boundary_atom_count),
                    "inpainting_region_mode": bool(_boundary_refinement_inpainting_region_mode),
                }

        # Inpainting: Align final coordinates back to original template coordinate system
        # 
        # After diffusion, the coordinates are in model's preferred coordinate system.
        # To restore to user's original template coordinate system:
        # - Align the final coords using template atoms as anchors
        # - This ensures the template part returns to its original position
        # - Generated parts follow naturally, maintaining proper connectivity
        #
        # Mathematical justification:
        # ===========================
        # Let T_orig be original template, T_final be transformed template after diffusion
        # Let X_final be final generated coordinates
        # 
        # We find R, t such that: T_orig ≈ R @ T_final + t (using template mask as weights)
        # Then apply same transform to all coords: X_restored = R @ X_final + t
        # 
        # # This preserves the relative geometry between template and generated parts
        # # while restoring the absolute coordinate system to match user's input.
        # if enable_inpainting and self.alignment_reverse_diff:
        #     with torch.autocast("cuda", enabled=False):
        #         # Align final coordinates to original template coordinate system
        #         # We align the transformed template back to original template,
        #         # then apply the same transformation to all atoms
        #         atom_coords_restored, rot_matrix, src_centroid, tgt_centroid = weighted_rigid_align(
        #             atom_coords.float(),
        #             template_coords_original.float(),
        #             # Use only template atoms as weights for alignment
        #             template_mask_expanded.float(),
        #             atom_mask.float(),
        #             return_transform=True,
        #         )
        #         atom_coords = atom_coords_restored.to(atom_coords)

        #         # Force-replace template atoms to exact template positions.
        #         # The rigid alignment minimises global RMSD but leaves flexible
        #         # sidechains (ARG, HIS, …) slightly off.  Overwriting ensures
        #         # every template-masked atom is pixel-perfect.
        #         atom_coords[template_mask_expanded] = template_coords_original[template_mask_expanded].to(atom_coords)

        return dict(
            sample_atom_coords=atom_coords,
            diff_token_repr=token_repr,
        )

    def loss_weight(self, sigma):
        return (sigma**2 + self.sigma_data**2) / ((sigma * self.sigma_data) ** 2)

    def noise_distribution(self, batch_size):
        return (
            self.sigma_data
            * (
                self.P_mean
                + self.P_std * torch.randn((batch_size,), device=self.device)
            ).exp()
        )

    def forward(
        self,
        s_inputs,
        s_trunk,
        feats,
        diffusion_conditioning,
        multiplicity=1,
    ):
        # training diffusion step
        batch_size = feats["coords"].shape[0] // multiplicity

        if self.synchronize_sigmas:
            sigmas = self.noise_distribution(batch_size).repeat_interleave(
                multiplicity, 0
            )
        else:
            sigmas = self.noise_distribution(batch_size * multiplicity)
        padded_sigmas = rearrange(sigmas, "b -> b 1 1")

        atom_coords = feats["coords"]

        atom_mask = feats["atom_pad_mask"]
        atom_mask = atom_mask.repeat_interleave(multiplicity, 0)

        atom_coords = center_random_augmentation(
            atom_coords, atom_mask, augmentation=self.coordinate_augmentation
        )

        noise = torch.randn_like(atom_coords)
        noised_atom_coords = atom_coords + padded_sigmas * noise

        denoised_atom_coords = self.preconditioned_network_forward(
            noised_atom_coords,
            sigmas,
            network_condition_kwargs={
                "s_inputs": s_inputs,
                "s_trunk": s_trunk,
                "feats": feats,
                "multiplicity": multiplicity,
                "diffusion_conditioning": diffusion_conditioning,
            },
        )

        return {
            "denoised_atom_coords": denoised_atom_coords,
            "sigmas": sigmas,
            "aligned_true_atom_coords": atom_coords,
        }

    def compute_loss(
        self,
        feats,
        out_dict,
        add_smooth_lddt_loss=True,
        nucleotide_loss_weight=5.0,
        ligand_loss_weight=10.0,
        multiplicity=1,
        filter_by_plddt=0.0,
    ):
        with torch.autocast("cuda", enabled=False):
            denoised_atom_coords = out_dict["denoised_atom_coords"].float()
            sigmas = out_dict["sigmas"].float()

            resolved_atom_mask_uni = feats["atom_resolved_mask"].float()

            if filter_by_plddt > 0:
                plddt_mask = feats["plddt"] > filter_by_plddt
                resolved_atom_mask_uni = resolved_atom_mask_uni * plddt_mask.float()

            resolved_atom_mask = resolved_atom_mask_uni.repeat_interleave(
                multiplicity, 0
            )

            align_weights = denoised_atom_coords.new_ones(
                denoised_atom_coords.shape[:2]
            )
            atom_type = (
                torch.bmm(
                    feats["atom_to_token"].float(),
                    feats["mol_type"].unsqueeze(-1).float(),
                )
                .squeeze(-1)
                .long()
            )
            atom_type_mult = atom_type.repeat_interleave(multiplicity, 0)

            align_weights = (
                align_weights
                * (
                    1
                    + nucleotide_loss_weight
                    * (
                        torch.eq(atom_type_mult, const.chain_type_ids["DNA"]).float()
                        + torch.eq(atom_type_mult, const.chain_type_ids["RNA"]).float()
                    )
                    + ligand_loss_weight
                    * torch.eq(
                        atom_type_mult, const.chain_type_ids["NONPOLYMER"]
                    ).float()
                ).float()
            )

            atom_coords = out_dict["aligned_true_atom_coords"].float()
            atom_coords_aligned_ground_truth = weighted_rigid_align(
                atom_coords.detach(),
                denoised_atom_coords.detach(),
                align_weights.detach(),
                mask=feats["atom_resolved_mask"]
                .float()
                .repeat_interleave(multiplicity, 0)
                .detach(),
            )

            # Cast back
            atom_coords_aligned_ground_truth = atom_coords_aligned_ground_truth.to(
                denoised_atom_coords
            )

            # weighted MSE loss of denoised atom positions
            mse_loss = (
                (denoised_atom_coords - atom_coords_aligned_ground_truth) ** 2
            ).sum(dim=-1)
            mse_loss = torch.sum(
                mse_loss * align_weights * resolved_atom_mask, dim=-1
            ) / (torch.sum(3 * align_weights * resolved_atom_mask, dim=-1) + 1e-5)

            # weight by sigma factor
            loss_weights = self.loss_weight(sigmas)
            mse_loss = (mse_loss * loss_weights).mean()

            total_loss = mse_loss

            # proposed auxiliary smooth lddt loss
            lddt_loss = self.zero
            if add_smooth_lddt_loss:
                lddt_loss = smooth_lddt_loss(
                    denoised_atom_coords,
                    feats["coords"],
                    torch.eq(atom_type, const.chain_type_ids["DNA"]).float()
                    + torch.eq(atom_type, const.chain_type_ids["RNA"]).float(),
                    coords_mask=resolved_atom_mask_uni,
                    multiplicity=multiplicity,
                )

                total_loss = total_loss + lddt_loss

            loss_breakdown = {
                "mse_loss": mse_loss,
                "smooth_lddt_loss": lddt_loss,
            }

        return {"loss": total_loss, "loss_breakdown": loss_breakdown}
