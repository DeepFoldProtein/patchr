import gc
from typing import Any, Optional

import numpy as np
import torch
import torch._dynamo
from pytorch_lightning import Callback, LightningModule
from torch import Tensor, nn
from torchmetrics import MeanMetric

import boltz.model.layers.initialize as init
from boltz.data import const
from boltz.data.mol import minimum_lddt_symmetry_coords
from boltz.model.layers.pairformer import PairformerModule
from boltz.model.loss.bfactor import bfactor_loss_fn
from boltz.model.loss.confidencev2 import confidence_loss
from boltz.model.loss.distogramv2 import distogram_loss
from boltz.model.modules.affinity import AffinityModule
from boltz.model.modules.confidencev2 import ConfidenceModule
from boltz.model.modules.diffusion_conditioning import DiffusionConditioning
from boltz.model.modules.diffusionv2 import AtomDiffusion
from boltz.model.modules.encodersv2 import RelativePositionEncoder
from boltz.model.modules.utils import center
from boltz.model.modules.trunkv2 import (
    BFactorModule,
    ContactConditioning,
    DistogramModule,
    InputEmbedder,
    MSAModule,
    TemplateModule,
    TemplateV2Module,
)
from boltz.model.optim.ema import EMA
from boltz.model.optim.scheduler import AlphaFoldLRScheduler


class Boltz2(LightningModule):
    """Boltz2 model."""

    def __init__(
        self,
        atom_s: int,
        atom_z: int,
        token_s: int,
        token_z: int,
        num_bins: int,
        training_args: dict[str, Any],
        validation_args: dict[str, Any],
        embedder_args: dict[str, Any],
        msa_args: dict[str, Any],
        pairformer_args: dict[str, Any],
        score_model_args: dict[str, Any],
        diffusion_process_args: dict[str, Any],
        diffusion_loss_args: dict[str, Any],
        confidence_model_args: Optional[dict[str, Any]] = None,
        affinity_model_args: Optional[dict[str, Any]] = None,
        affinity_model_args1: Optional[dict[str, Any]] = None,
        affinity_model_args2: Optional[dict[str, Any]] = None,
        validators: Any = None,
        num_val_datasets: int = 1,
        atom_feature_dim: int = 128,
        template_args: Optional[dict] = None,
        confidence_prediction: bool = True,
        affinity_prediction: bool = False,
        affinity_ensemble: bool = False,
        affinity_mw_correction: bool = True,
        run_trunk_and_structure: bool = True,
        skip_run_structure: bool = False,
        token_level_confidence: bool = True,
        alpha_pae: float = 0.0,
        structure_prediction_training: bool = True,
        validate_structure: bool = True,
        atoms_per_window_queries: int = 32,
        atoms_per_window_keys: int = 128,
        compile_pairformer: bool = False,
        compile_structure: bool = False,
        compile_confidence: bool = False,
        compile_affinity: bool = False,
        compile_msa: bool = False,
        exclude_ions_from_lddt: bool = False,
        ema: bool = False,
        ema_decay: float = 0.999,
        min_dist: float = 2.0,
        max_dist: float = 22.0,
        predict_args: Optional[dict[str, Any]] = None,
        fix_sym_check: bool = False,
        cyclic_pos_enc: bool = False,
        aggregate_distogram: bool = True,
        bond_type_feature: bool = False,
        use_no_atom_char: bool = False,
        no_random_recycling_training: bool = False,
        use_atom_backbone_feat: bool = False,
        use_residue_feats_atoms: bool = False,
        conditioning_cutoff_min: float = 4.0,
        conditioning_cutoff_max: float = 20.0,
        steering_args: Optional[dict] = None,
        use_templates: bool = False,
        compile_templates: bool = False,
        predict_bfactor: bool = False,
        log_loss_every_steps: int = 50,
        checkpoint_diffusion_conditioning: bool = False,
        use_templates_v2: bool = False,
        use_kernels: bool = False,
        enable_inpainting: bool = False,
    ) -> None:
        super().__init__()
        self.save_hyperparameters(ignore=["validators"])

        # No random recycling
        self.no_random_recycling_training = no_random_recycling_training

        if validate_structure:
            # Late init at setup time
            self.val_group_mapper = (
                {}
            )  # maps a dataset index to a validation group name
            self.validator_mapper = {}  # maps a dataset index to a validator

            # Validators for each dataset keep track of all metrics,
            # compute validation, aggregate results and log
            self.validators = nn.ModuleList(validators)

        self.num_val_datasets = num_val_datasets
        self.log_loss_every_steps = log_loss_every_steps

        # EMA
        self.use_ema = ema
        self.ema_decay = ema_decay

        # Arguments
        self.training_args = training_args
        self.validation_args = validation_args
        self.diffusion_loss_args = diffusion_loss_args
        self.predict_args = predict_args
        self.steering_args = steering_args

        # Inpainting configuration
        self.enable_inpainting = enable_inpainting

        # Training metrics
        if validate_structure:
            self.train_confidence_loss_logger = MeanMetric()
            self.train_confidence_loss_dict_logger = nn.ModuleDict()
            for m in [
                "plddt_loss",
                "resolved_loss",
                "pde_loss",
                "pae_loss",
            ]:
                self.train_confidence_loss_dict_logger[m] = MeanMetric()

        self.exclude_ions_from_lddt = exclude_ions_from_lddt

        # Distogram
        self.num_bins = num_bins
        self.min_dist = min_dist
        self.max_dist = max_dist
        self.aggregate_distogram = aggregate_distogram

        # Trunk
        self.is_pairformer_compiled = False
        self.is_msa_compiled = False
        self.is_template_compiled = False

        # Kernels
        self.use_kernels = use_kernels

        # Input embeddings
        full_embedder_args = {
            "atom_s": atom_s,
            "atom_z": atom_z,
            "token_s": token_s,
            "token_z": token_z,
            "atoms_per_window_queries": atoms_per_window_queries,
            "atoms_per_window_keys": atoms_per_window_keys,
            "atom_feature_dim": atom_feature_dim,
            "use_no_atom_char": use_no_atom_char,
            "use_atom_backbone_feat": use_atom_backbone_feat,
            "use_residue_feats_atoms": use_residue_feats_atoms,
            **embedder_args,
        }
        self.input_embedder = InputEmbedder(**full_embedder_args)

        self.s_init = nn.Linear(token_s, token_s, bias=False)
        self.z_init_1 = nn.Linear(token_s, token_z, bias=False)
        self.z_init_2 = nn.Linear(token_s, token_z, bias=False)

        self.rel_pos = RelativePositionEncoder(
            token_z, fix_sym_check=fix_sym_check, cyclic_pos_enc=cyclic_pos_enc
        )

        self.token_bonds = nn.Linear(1, token_z, bias=False)
        self.bond_type_feature = bond_type_feature
        if bond_type_feature:
            self.token_bonds_type = nn.Embedding(len(const.bond_types) + 1, token_z)

        self.contact_conditioning = ContactConditioning(
            token_z=token_z,
            cutoff_min=conditioning_cutoff_min,
            cutoff_max=conditioning_cutoff_max,
        )

        # Normalization layers
        self.s_norm = nn.LayerNorm(token_s)
        self.z_norm = nn.LayerNorm(token_z)

        # Recycling projections
        self.s_recycle = nn.Linear(token_s, token_s, bias=False)
        self.z_recycle = nn.Linear(token_z, token_z, bias=False)
        init.gating_init_(self.s_recycle.weight)
        init.gating_init_(self.z_recycle.weight)

        # Set compile rules
        # Big models hit the default cache limit (8)
        torch._dynamo.config.cache_size_limit = 512  # noqa: SLF001
        torch._dynamo.config.accumulated_cache_size_limit = 512  # noqa: SLF001

        # Pairwise stack
        self.use_templates = use_templates
        if use_templates:
            if use_templates_v2:
                self.template_module = TemplateV2Module(token_z, **template_args)
            else:
                self.template_module = TemplateModule(token_z, **template_args)
            if compile_templates:
                self.is_template_compiled = True
                self.template_module = torch.compile(
                    self.template_module,
                    dynamic=False,
                    fullgraph=False,
                )

        self.msa_module = MSAModule(
            token_z=token_z,
            token_s=token_s,
            **msa_args,
        )
        if compile_msa:
            self.is_msa_compiled = True
            self.msa_module = torch.compile(
                self.msa_module,
                dynamic=False,
                fullgraph=False,
            )
        self.pairformer_module = PairformerModule(token_s, token_z, **pairformer_args)
        if compile_pairformer:
            self.is_pairformer_compiled = True
            self.pairformer_module = torch.compile(
                self.pairformer_module,
                dynamic=False,
                fullgraph=False,
            )

        self.checkpoint_diffusion_conditioning = checkpoint_diffusion_conditioning
        self.diffusion_conditioning = DiffusionConditioning(
            token_s=token_s,
            token_z=token_z,
            atom_s=atom_s,
            atom_z=atom_z,
            atoms_per_window_queries=atoms_per_window_queries,
            atoms_per_window_keys=atoms_per_window_keys,
            atom_encoder_depth=score_model_args["atom_encoder_depth"],
            atom_encoder_heads=score_model_args["atom_encoder_heads"],
            token_transformer_depth=score_model_args["token_transformer_depth"],
            token_transformer_heads=score_model_args["token_transformer_heads"],
            atom_decoder_depth=score_model_args["atom_decoder_depth"],
            atom_decoder_heads=score_model_args["atom_decoder_heads"],
            atom_feature_dim=atom_feature_dim,
            conditioning_transition_layers=score_model_args[
                "conditioning_transition_layers"
            ],
            use_no_atom_char=use_no_atom_char,
            use_atom_backbone_feat=use_atom_backbone_feat,
            use_residue_feats_atoms=use_residue_feats_atoms,
        )

        # Output modules
        self.structure_module = AtomDiffusion(
            score_model_args={
                "token_s": token_s,
                "atom_s": atom_s,
                "atoms_per_window_queries": atoms_per_window_queries,
                "atoms_per_window_keys": atoms_per_window_keys,
                **score_model_args,
            },
            compile_score=compile_structure,
            **diffusion_process_args,
        )
        self.distogram_module = DistogramModule(
            token_z,
            num_bins,
        )
        self.predict_bfactor = predict_bfactor
        if predict_bfactor:
            self.bfactor_module = BFactorModule(token_s, num_bins)

        self.confidence_prediction = confidence_prediction
        self.affinity_prediction = affinity_prediction
        self.affinity_ensemble = affinity_ensemble
        self.affinity_mw_correction = affinity_mw_correction
        self.run_trunk_and_structure = run_trunk_and_structure
        self.skip_run_structure = skip_run_structure
        self.token_level_confidence = token_level_confidence
        self.alpha_pae = alpha_pae
        self.structure_prediction_training = structure_prediction_training

        if self.confidence_prediction:
            self.confidence_module = ConfidenceModule(
                token_s,
                token_z,
                token_level_confidence=token_level_confidence,
                bond_type_feature=bond_type_feature,
                fix_sym_check=fix_sym_check,
                cyclic_pos_enc=cyclic_pos_enc,
                conditioning_cutoff_min=conditioning_cutoff_min,
                conditioning_cutoff_max=conditioning_cutoff_max,
                **confidence_model_args,
            )
            if compile_confidence:
                self.confidence_module = torch.compile(
                    self.confidence_module, dynamic=False, fullgraph=False
                )

        if self.affinity_prediction:
            if self.affinity_ensemble:
                self.affinity_module1 = AffinityModule(
                    token_s,
                    token_z,
                    **affinity_model_args1,
                )
                self.affinity_module2 = AffinityModule(
                    token_s,
                    token_z,
                    **affinity_model_args2,
                )
                if compile_affinity:
                    self.affinity_module1 = torch.compile(
                        self.affinity_module1, dynamic=False, fullgraph=False
                    )
                    self.affinity_module2 = torch.compile(
                        self.affinity_module2, dynamic=False, fullgraph=False
                    )
            else:
                self.affinity_module = AffinityModule(
                    token_s,
                    token_z,
                    **affinity_model_args,
                )
                if compile_affinity:
                    self.affinity_module = torch.compile(
                        self.affinity_module, dynamic=False, fullgraph=False
                    )

        # Remove grad from weights they are not trained for ddp
        if not structure_prediction_training:
            for name, param in self.named_parameters():
                if (
                    name.split(".")[0] not in ["confidence_module", "affinity_module"]
                    and "out_token_feat_update" not in name
                ):
                    param.requires_grad = False

    def setup(self, stage: str) -> None:
        """Set the model for training, validation and inference."""
        if stage == "predict" and not (
            torch.cuda.is_available()
            and torch.cuda.get_device_properties(torch.device("cuda")).major
            >= 8.0  # noqa: PLR2004
        ):
            self.use_kernels = False

        if (
            stage != "predict"
            and hasattr(self.trainer, "datamodule")
            and self.trainer.datamodule
            and self.validate_structure
        ):
            self.val_group_mapper.update(self.trainer.datamodule.val_group_mapper)

            l1 = len(self.val_group_mapper)
            l2 = self.num_val_datasets
            msg = (
                f"Number of validation datasets num_val_datasets={l2} "
                f"does not match the number of val_group_mapper entries={l1}."
            )
            assert l1 == l2, msg

            # Map an index to a validator, and double check val names
            # match from datamodule
            all_validator_names = []
            for validator in self.validators:
                for val_name in validator.val_names:
                    msg = f"Validator {val_name} duplicated in validators."
                    assert val_name not in all_validator_names, msg
                    all_validator_names.append(val_name)
                    for val_idx, val_group in self.val_group_mapper.items():
                        if val_name == val_group["label"]:
                            self.validator_mapper[val_idx] = validator

            msg = "Mismatch between validator names and val_group_mapper values."
            assert set(all_validator_names) == {
                x["label"] for x in self.val_group_mapper.values()
            }, msg

    def _get_progress_tracker(self):
        """Get ProgressTracker from trainer callbacks if available."""
        if hasattr(self, "trainer") and self.trainer is not None:
            for callback in self.trainer.callbacks:
                # Check if it's a ProgressTracker (from server.py)
                if hasattr(callback, "update_base_progress") and hasattr(
                    callback, "update_diffusion_progress"
                ):
                    return callback
        return None

    def forward(
        self,
        feats: dict[str, Tensor],
        recycling_steps: int = 0,
        num_sampling_steps: Optional[int] = None,
        multiplicity_diffusion_train: int = 1,
        diffusion_samples: int = 1,
        max_parallel_samples: Optional[int] = None,
        run_confidence_sequentially: bool = False,
    ) -> dict[str, Tensor]:
        # Inpainting mode: validate and prepare template coordinates
        if self.enable_inpainting:
            self._validate_and_prepare_inpainting(feats)

        # Update progress: pre-diffusion phase (0-40%)
        progress_tracker = self._get_progress_tracker()
        if progress_tracker:
            progress_tracker.update_base_progress("Initializing embeddings", 5)

        with torch.set_grad_enabled(
            self.training and self.structure_prediction_training
        ):
            s_inputs = self.input_embedder(feats)

            # Initialize the sequence embeddings
            s_init = self.s_init(s_inputs)

            # Initialize pairwise embeddings
            z_init = (
                self.z_init_1(s_inputs)[:, :, None]
                + self.z_init_2(s_inputs)[:, None, :]
            )
            relative_position_encoding = self.rel_pos(feats)
            z_init = z_init + relative_position_encoding
            z_init = z_init + self.token_bonds(feats["token_bonds"].float())
            if self.bond_type_feature:
                z_init = z_init + self.token_bonds_type(feats["type_bonds"].long())
            z_init = z_init + self.contact_conditioning(feats)

            # Perform rounds of the pairwise stack
            s = torch.zeros_like(s_init)
            z = torch.zeros_like(z_init)

            # Compute pairwise mask
            mask = feats["token_pad_mask"].float()
            pair_mask = mask[:, :, None] * mask[:, None, :]
            template_output = None  # Initialize template_output

            # Update progress: trunk processing
            if progress_tracker:
                progress_tracker.update_base_progress("Running trunk processing", 20)

            if self.run_trunk_and_structure:
                for i in range(recycling_steps + 1):
                    # Update progress during recycling
                    if progress_tracker and recycling_steps > 0:
                        recycling_progress = 20 + int(
                            (i / (recycling_steps + 1)) * 10
                        )  # 20-30%
                        progress_tracker.update_base_progress(
                            f"Recycling step {i + 1}/{recycling_steps + 1}",
                            recycling_progress,
                        )

                    with torch.set_grad_enabled(
                        self.training
                        and self.structure_prediction_training
                        and (i == recycling_steps)
                    ):
                        # Issue with unused parameters in autocast
                        if (
                            self.training
                            and (i == recycling_steps)
                            and torch.is_autocast_enabled()
                        ):
                            torch.clear_autocast_cache()

                        # Apply recycling
                        s = s_init + self.s_recycle(self.s_norm(s))
                        z = z_init + self.z_recycle(self.z_norm(z))

                        # Compute pairwise stack
                        if self.use_templates:
                            if self.is_template_compiled and not self.training:
                                template_module = (
                                    self.template_module._orig_mod
                                )  # noqa: SLF001
                            else:
                                template_module = self.template_module

                            template_output = template_module(
                                z, feats, pair_mask, use_kernels=self.use_kernels
                            )
                            z = z + template_output

                        if self.is_msa_compiled and not self.training:
                            msa_module = self.msa_module._orig_mod  # noqa: SLF001
                        else:
                            msa_module = self.msa_module

                        z = z + msa_module(
                            z, s_inputs, feats, use_kernels=self.use_kernels
                        )

                        # Revert to uncompiled version for validation
                        if self.is_pairformer_compiled and not self.training:
                            pairformer_module = (
                                self.pairformer_module._orig_mod
                            )  # noqa: SLF001
                        else:
                            pairformer_module = self.pairformer_module

                        s, z = pairformer_module(
                            s,
                            z,
                            mask=mask,
                            pair_mask=pair_mask,
                            use_kernels=self.use_kernels,
                        )

            pdistogram = self.distogram_module(z)
            dict_out = {
                "pdistogram": pdistogram,
                "s": s,
                "z": z,
            }
            # Store template_output for visualization if templates are used
            if self.use_templates and template_output is not None:
                dict_out["template_output"] = template_output

            if (
                self.run_trunk_and_structure
                and ((not self.training) or self.confidence_prediction)
                and (not self.skip_run_structure)
            ):
                if self.checkpoint_diffusion_conditioning and self.training:
                    # TODO decide whether this should be with bf16 or not
                    q, c, to_keys, atom_enc_bias, atom_dec_bias, token_trans_bias = (
                        torch.utils.checkpoint.checkpoint(
                            self.diffusion_conditioning,
                            s,
                            z,
                            relative_position_encoding,
                            feats,
                        )
                    )
                else:
                    q, c, to_keys, atom_enc_bias, atom_dec_bias, token_trans_bias = (
                        self.diffusion_conditioning(
                            s_trunk=s,
                            z_trunk=z,
                            relative_position_encoding=relative_position_encoding,
                            feats=feats,
                        )
                    )
                diffusion_conditioning = {
                    "q": q,
                    "c": c,
                    "to_keys": to_keys,
                    "atom_enc_bias": atom_enc_bias,
                    "atom_dec_bias": atom_dec_bias,
                    "token_trans_bias": token_trans_bias,
                }

                # Update progress: diffusion conditioning ready, starting diffusion
                if progress_tracker:
                    progress_tracker.update_base_progress("Preparing diffusion", 40)

                with torch.autocast("cuda", enabled=False):
                    # Get boundary refinement setting from predict_args if available
                    boundary_refinement_enabled = None
                    if self.predict_args is not None:
                        boundary_refinement_enabled = self.predict_args.get(
                            "boundary_refinement_enabled", None
                        )

                    struct_out = self.structure_module.sample(
                        s_trunk=s.float(),
                        s_inputs=s_inputs.float(),
                        feats=feats,
                        num_sampling_steps=num_sampling_steps,
                        atom_mask=feats["atom_pad_mask"].float(),
                        multiplicity=diffusion_samples,
                        max_parallel_samples=max_parallel_samples,
                        steering_args=self.steering_args,
                        diffusion_conditioning=diffusion_conditioning,
                        progress_tracker=progress_tracker,  # Pass progress tracker
                        boundary_refinement_enabled=boundary_refinement_enabled,
                    )
                    dict_out.update(struct_out)

                if self.predict_bfactor:
                    pbfactor = self.bfactor_module(s)
                    dict_out["pbfactor"] = pbfactor

            if self.training and self.confidence_prediction:
                assert len(feats["coords"].shape) == 4
                assert (
                    feats["coords"].shape[1] == 1
                ), "Only one conformation is supported for confidence"

            # Compute structure module
            if self.training and self.structure_prediction_training:
                atom_coords = feats["coords"]
                B, K, L = atom_coords.shape[0:3]
                assert K in (
                    multiplicity_diffusion_train,
                    1,
                )  # TODO make check somewhere else, expand to m % N == 0, m > N
                atom_coords = atom_coords.reshape(B * K, L, 3)
                atom_coords = atom_coords.repeat_interleave(
                    multiplicity_diffusion_train // K, 0
                )
                feats["coords"] = atom_coords  # (multiplicity, L, 3)
                assert len(feats["coords"].shape) == 3

                with torch.autocast("cuda", enabled=False):
                    struct_out = self.structure_module(
                        s_trunk=s.float(),
                        s_inputs=s_inputs.float(),
                        feats=feats,
                        multiplicity=multiplicity_diffusion_train,
                        diffusion_conditioning=diffusion_conditioning,
                    )
                    dict_out.update(struct_out)

            elif self.training:
                feats["coords"] = feats["coords"].squeeze(1)
                assert len(feats["coords"].shape) == 3

        if self.confidence_prediction:
            dict_out.update(
                self.confidence_module(
                    s_inputs=s_inputs.detach(),
                    s=s.detach(),
                    z=z.detach(),
                    x_pred=(
                        dict_out["sample_atom_coords"].detach()
                        if not self.skip_run_structure
                        else feats["coords"].repeat_interleave(diffusion_samples, 0)
                    ),
                    feats=feats,
                    pred_distogram_logits=(
                        dict_out["pdistogram"][
                            :, :, :, 0
                        ].detach()  # TODO only implemented for 1 distogram
                    ),
                    multiplicity=diffusion_samples,
                    run_sequentially=run_confidence_sequentially,
                    use_kernels=self.use_kernels,
                )
            )

        if self.affinity_prediction:
            pad_token_mask = feats["token_pad_mask"][0]
            rec_mask = feats["mol_type"][0] == 0
            rec_mask = rec_mask * pad_token_mask
            lig_mask = feats["affinity_token_mask"][0].to(torch.bool)
            lig_mask = lig_mask * pad_token_mask
            cross_pair_mask = (
                lig_mask[:, None] * rec_mask[None, :]
                + rec_mask[:, None] * lig_mask[None, :]
                + lig_mask[:, None] * lig_mask[None, :]
            )
            z_affinity = z * cross_pair_mask[None, :, :, None]

            argsort = torch.argsort(dict_out["iptm"], descending=True)
            best_idx = argsort[0].item()
            coords_affinity = dict_out["sample_atom_coords"].detach()[best_idx][
                None, None
            ]
            s_inputs = self.input_embedder(feats, affinity=True)

            with torch.autocast("cuda", enabled=False):
                if self.affinity_ensemble:
                    dict_out_affinity1 = self.affinity_module1(
                        s_inputs=s_inputs.detach(),
                        z=z_affinity.detach(),
                        x_pred=coords_affinity,
                        feats=feats,
                        multiplicity=1,
                        use_kernels=self.use_kernels,
                    )

                    dict_out_affinity1["affinity_probability_binary"] = (
                        torch.nn.functional.sigmoid(
                            dict_out_affinity1["affinity_logits_binary"]
                        )
                    )
                    dict_out_affinity2 = self.affinity_module2(
                        s_inputs=s_inputs.detach(),
                        z=z_affinity.detach(),
                        x_pred=coords_affinity,
                        feats=feats,
                        multiplicity=1,
                        use_kernels=self.use_kernels,
                    )
                    dict_out_affinity2["affinity_probability_binary"] = (
                        torch.nn.functional.sigmoid(
                            dict_out_affinity2["affinity_logits_binary"]
                        )
                    )

                    dict_out_affinity_ensemble = {
                        "affinity_pred_value": (
                            dict_out_affinity1["affinity_pred_value"]
                            + dict_out_affinity2["affinity_pred_value"]
                        )
                        / 2,
                        "affinity_probability_binary": (
                            dict_out_affinity1["affinity_probability_binary"]
                            + dict_out_affinity2["affinity_probability_binary"]
                        )
                        / 2,
                    }

                    dict_out_affinity1 = {
                        "affinity_pred_value1": dict_out_affinity1[
                            "affinity_pred_value"
                        ],
                        "affinity_probability_binary1": dict_out_affinity1[
                            "affinity_probability_binary"
                        ],
                    }
                    dict_out_affinity2 = {
                        "affinity_pred_value2": dict_out_affinity2[
                            "affinity_pred_value"
                        ],
                        "affinity_probability_binary2": dict_out_affinity2[
                            "affinity_probability_binary"
                        ],
                    }
                    if self.affinity_mw_correction:
                        model_coef = 1.03525938
                        mw_coef = -0.59992683
                        bias = 2.83288489
                        mw = feats["affinity_mw"][0] ** 0.3
                        dict_out_affinity_ensemble["affinity_pred_value"] = (
                            model_coef
                            * dict_out_affinity_ensemble["affinity_pred_value"]
                            + mw_coef * mw
                            + bias
                        )

                    dict_out.update(dict_out_affinity_ensemble)
                    dict_out.update(dict_out_affinity1)
                    dict_out.update(dict_out_affinity2)
                else:
                    dict_out_affinity = self.affinity_module(
                        s_inputs=s_inputs.detach(),
                        z=z_affinity.detach(),
                        x_pred=coords_affinity,
                        feats=feats,
                        multiplicity=1,
                        use_kernels=self.use_kernels,
                    )
                    dict_out.update(
                        {
                            "affinity_pred_value": dict_out_affinity[
                                "affinity_pred_value"
                            ],
                            "affinity_probability_binary": torch.nn.functional.sigmoid(
                                dict_out_affinity["affinity_logits_binary"]
                            ),
                        }
                    )

        # Store inpainting metadata in output dict for JSON export
        if "inpainting_metadata" in feats:
            dict_out["inpainting_metadata"] = feats["inpainting_metadata"]

        return dict_out

    def get_true_coordinates(
        self,
        batch: dict[str, Tensor],
        out: dict[str, Tensor],
        diffusion_samples: int,
        symmetry_correction: bool,
        expand_to_diffusion_samples: bool = True,
    ):
        if symmetry_correction:
            msg = "expand_to_diffusion_samples must be true for symmetry correction."
            assert expand_to_diffusion_samples, msg

        return_dict = {}

        assert (
            batch["coords"].shape[0] == 1
        ), f"Validation is not supported for batch sizes={batch['coords'].shape[0]}"

        if symmetry_correction:
            true_coords = []
            true_coords_resolved_mask = []
            for idx in range(batch["token_index"].shape[0]):
                for rep in range(diffusion_samples):
                    i = idx * diffusion_samples + rep
                    best_true_coords, best_true_coords_resolved_mask = (
                        minimum_lddt_symmetry_coords(
                            coords=out["sample_atom_coords"][i : i + 1],
                            feats=batch,
                            index_batch=idx,
                        )
                    )
                    true_coords.append(best_true_coords)
                    true_coords_resolved_mask.append(best_true_coords_resolved_mask)

            true_coords = torch.cat(true_coords, dim=0)
            true_coords_resolved_mask = torch.cat(true_coords_resolved_mask, dim=0)
            true_coords = true_coords.unsqueeze(1)

            true_coords_resolved_mask = true_coords_resolved_mask

            return_dict["true_coords"] = true_coords
            return_dict["true_coords_resolved_mask"] = true_coords_resolved_mask
            return_dict["rmsds"] = 0
            return_dict["best_rmsd_recall"] = 0

        else:
            K, L = batch["coords"].shape[1:3]

            true_coords_resolved_mask = batch["atom_resolved_mask"]
            true_coords = batch["coords"].squeeze(0)
            if expand_to_diffusion_samples:
                true_coords = true_coords.repeat((diffusion_samples, 1, 1)).reshape(
                    diffusion_samples, K, L, 3
                )

                true_coords_resolved_mask = true_coords_resolved_mask.repeat_interleave(
                    diffusion_samples, dim=0
                )  # since all masks are the same across conformers and diffusion samples, can just repeat S times
            else:
                true_coords_resolved_mask = true_coords_resolved_mask.squeeze(0)

            return_dict["true_coords"] = true_coords
            return_dict["true_coords_resolved_mask"] = true_coords_resolved_mask
            return_dict["rmsds"] = 0
            return_dict["best_rmsd_recall"] = 0
            return_dict["best_rmsd_precision"] = 0

        return return_dict

    def training_step(self, batch: dict[str, Tensor], batch_idx: int) -> Tensor:
        # Sample recycling steps
        if self.no_random_recycling_training:
            recycling_steps = self.training_args.recycling_steps
        else:
            rgn = np.random.default_rng(self.global_step)
            recycling_steps = rgn.integers(
                0, self.training_args.recycling_steps + 1
            ).item()

        if self.training_args.get("sampling_steps_random", None) is not None:
            rgn_samplng_steps = np.random.default_rng(self.global_step)
            sampling_steps = rgn_samplng_steps.choice(
                self.training_args.sampling_steps_random
            )
        else:
            sampling_steps = self.training_args.sampling_steps

        # Compute the forward pass
        out = self(
            feats=batch,
            recycling_steps=recycling_steps,
            num_sampling_steps=sampling_steps,
            multiplicity_diffusion_train=self.training_args.diffusion_multiplicity,
            diffusion_samples=self.training_args.diffusion_samples,
        )

        # Compute losses
        if self.structure_prediction_training:
            disto_loss, _ = distogram_loss(
                out,
                batch,
                aggregate_distogram=self.aggregate_distogram,
            )
            try:
                diffusion_loss_dict = self.structure_module.compute_loss(
                    batch,
                    out,
                    multiplicity=self.training_args.diffusion_multiplicity,
                    **self.diffusion_loss_args,
                )
            except Exception as e:
                print(f"Skipping batch {batch_idx} due to error: {e}")
                return None

            if self.predict_bfactor:
                bfactor_loss = bfactor_loss_fn(out, batch)
            else:
                bfactor_loss = 0.0

        else:
            disto_loss = 0.0
            bfactor_loss = 0.0
            diffusion_loss_dict = {"loss": 0.0, "loss_breakdown": {}}

        if self.confidence_prediction:
            try:
                # confidence model symmetry correction
                return_dict = self.get_true_coordinates(
                    batch,
                    out,
                    diffusion_samples=self.training_args.diffusion_samples,
                    symmetry_correction=self.training_args.symmetry_correction,
                )
            except Exception as e:
                print(f"Skipping batch with id {batch['pdb_id']} due to error: {e}")
                return None

            true_coords = return_dict["true_coords"]
            true_coords_resolved_mask = return_dict["true_coords_resolved_mask"]

            # TODO remove once multiple conformers are supported
            K = true_coords.shape[1]
            assert (
                K == 1
            ), f"Confidence_prediction is not supported for num_ensembles_val={K}."

            # For now, just take the only conformer.
            true_coords = true_coords.squeeze(1)  # (S, L, 3)
            batch["frames_idx"] = batch["frames_idx"].squeeze(
                1
            )  # remove conformer dimension
            batch["frame_resolved_mask"] = batch["frame_resolved_mask"].squeeze(
                1
            )  # remove conformer dimension

            confidence_loss_dict = confidence_loss(
                out,
                batch,
                true_coords,
                true_coords_resolved_mask,
                token_level_confidence=self.token_level_confidence,
                alpha_pae=self.alpha_pae,
                multiplicity=self.training_args.diffusion_samples,
            )

        else:
            confidence_loss_dict = {
                "loss": torch.tensor(0.0, device=batch["token_index"].device),
                "loss_breakdown": {},
            }

        # Aggregate losses
        # NOTE: we already have an implicit weight in the losses induced by dataset sampling
        # NOTE: this logic works only for datasets with confidence labels
        loss = (
            self.training_args.confidence_loss_weight * confidence_loss_dict["loss"]
            + self.training_args.diffusion_loss_weight * diffusion_loss_dict["loss"]
            + self.training_args.distogram_loss_weight * disto_loss
            + self.training_args.get("bfactor_loss_weight", 0.0) * bfactor_loss
        )

        if not (self.global_step % self.log_loss_every_steps):
            # Log losses
            if self.validate_structure:
                self.log("train/distogram_loss", disto_loss)
                self.log("train/diffusion_loss", diffusion_loss_dict["loss"])
                for k, v in diffusion_loss_dict["loss_breakdown"].items():
                    self.log(f"train/{k}", v)

            if self.confidence_prediction:
                self.train_confidence_loss_logger.update(
                    confidence_loss_dict["loss"].detach()
                )
                for k in self.train_confidence_loss_dict_logger:
                    self.train_confidence_loss_dict_logger[k].update(
                        (
                            confidence_loss_dict["loss_breakdown"][k].detach()
                            if torch.is_tensor(
                                confidence_loss_dict["loss_breakdown"][k]
                            )
                            else confidence_loss_dict["loss_breakdown"][k]
                        )
                    )
            self.log("train/loss", loss)
            self.training_log()
        return loss

    def training_log(self):
        self.log("train/grad_norm", self.gradient_norm(self), prog_bar=False)
        self.log("train/param_norm", self.parameter_norm(self), prog_bar=False)

        lr = self.trainer.optimizers[0].param_groups[0]["lr"]
        self.log("lr", lr, prog_bar=False)

        self.log(
            "train/param_norm_msa_module",
            self.parameter_norm(self.msa_module),
            prog_bar=False,
        )

        self.log(
            "train/param_norm_pairformer_module",
            self.parameter_norm(self.pairformer_module),
            prog_bar=False,
        )

        self.log(
            "train/param_norm_structure_module",
            self.parameter_norm(self.structure_module),
            prog_bar=False,
        )

        if self.confidence_prediction:
            self.log(
                "train/grad_norm_confidence_module",
                self.gradient_norm(self.confidence_module),
                prog_bar=False,
            )
            self.log(
                "train/param_norm_confidence_module",
                self.parameter_norm(self.confidence_module),
                prog_bar=False,
            )

    def on_train_epoch_end(self):
        if self.confidence_prediction:
            self.log(
                "train/confidence_loss",
                self.train_confidence_loss_logger,
                prog_bar=False,
                on_step=False,
                on_epoch=True,
            )
            for k, v in self.train_confidence_loss_dict_logger.items():
                self.log(f"train/{k}", v, prog_bar=False, on_step=False, on_epoch=True)

    def gradient_norm(self, module):
        parameters = [
            p.grad.norm(p=2) ** 2
            for p in module.parameters()
            if p.requires_grad and p.grad is not None
        ]
        if len(parameters) == 0:
            # Mac GPU support: device selection (from https://github.com/fnachon/boltz)
            return torch.tensor(
                0.0,
                device=torch.device(
                    "mps"
                    if torch.backends.mps.is_available()
                    else "cuda" if torch.cuda.is_available() else "cpu"
                ),
            )
        norm = torch.stack(parameters).sum().sqrt()
        return norm

    def parameter_norm(self, module):
        parameters = [p.norm(p=2) ** 2 for p in module.parameters() if p.requires_grad]
        if len(parameters) == 0:
            # Mac GPU support: device selection (from https://github.com/fnachon/boltz)
            return torch.tensor(
                0.0,
                device=torch.device(
                    "mps"
                    if torch.backends.mps.is_available()
                    else "cuda" if torch.cuda.is_available() else "cpu"
                ),
            )
        norm = torch.stack(parameters).sum().sqrt()
        return norm

    def validation_step(self, batch: dict[str, Tensor], batch_idx: int):
        if self.validate_structure:
            try:
                msg = "Only batch=1 is supported for validation"
                assert batch["idx_dataset"].shape[0] == 1, msg

                # Select validator based on dataset
                idx_dataset = batch["idx_dataset"][0].item()
                validator = self.validator_mapper[idx_dataset]

                # Run forward pass
                out = validator.run_model(
                    model=self, batch=batch, idx_dataset=idx_dataset
                )
                # Compute validation step
                validator.process(
                    model=self, batch=batch, out=out, idx_dataset=idx_dataset
                )
            except RuntimeError as e:  # catch out of memory exceptions
                idx_dataset = batch["idx_dataset"][0].item()
                if "out of memory" in str(e):
                    msg = f"| WARNING: ran out of memory, skipping batch, {idx_dataset}"
                    print(msg)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    # Mac GPU support: MPS cache clearing (from https://github.com/fnachon/boltz)
                    if torch.backends.mps.is_available():
                        torch.backends.mps.empty_cache()
                    gc.collect()
                    return
                raise e
        else:
            try:
                out = self(
                    batch,
                    recycling_steps=self.validation_args.recycling_steps,
                    num_sampling_steps=self.validation_args.sampling_steps,
                    diffusion_samples=self.validation_args.diffusion_samples,
                    run_confidence_sequentially=self.validation_args.get(
                        "run_confidence_sequentially", False
                    ),
                )
            except RuntimeError as e:  # catch out of memory exceptions
                idx_dataset = batch["idx_dataset"][0].item()
                if "out of memory" in str(e):
                    msg = f"| WARNING: ran out of memory, skipping batch, {idx_dataset}"
                    print(msg)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    # Mac GPU support: MPS cache clearing (from https://github.com/fnachon/boltz)
                    if torch.backends.mps.is_available():
                        torch.backends.mps.empty_cache()
                    gc.collect()
                    return
                raise e

    def on_validation_epoch_end(self):
        """Aggregate all metrics for each validator."""
        if self.validate_structure:
            for validator in self.validator_mapper.values():
                # This will aggregate, compute and log all metrics
                validator.on_epoch_end(model=self)

    def predict_step(self, batch: Any, batch_idx: int, dataloader_idx: int = 0) -> dict:
        try:
            out = self(
                batch,
                recycling_steps=self.predict_args["recycling_steps"],
                num_sampling_steps=self.predict_args["sampling_steps"],
                diffusion_samples=self.predict_args["diffusion_samples"],
                max_parallel_samples=self.predict_args["max_parallel_samples"],
                run_confidence_sequentially=True,
            )
            pred_dict = {"exception": False}
            if "keys_dict_batch" in self.predict_args:
                for key in self.predict_args["keys_dict_batch"]:
                    pred_dict[key] = batch[key]

            pred_dict["masks"] = batch["atom_pad_mask"]
            pred_dict["token_masks"] = batch["token_pad_mask"]
            pred_dict["s"] = out["s"]
            pred_dict["z"] = out["z"]

            if "keys_dict_out" in self.predict_args:
                for key in self.predict_args["keys_dict_out"]:
                    pred_dict[key] = out[key]
            pred_dict["coords"] = out["sample_atom_coords"]
            # Store template_output for visualization if available
            if "template_output" in out:
                pred_dict["template_output"] = out["template_output"]

            # Store inpainting metadata if available (for JSON export)
            if "inpainting_metadata" in out:
                pred_dict["inpainting_metadata"] = out["inpainting_metadata"]
            if self.confidence_prediction:
                # pred_dict["confidence"] = out.get("ablation_confidence", None)
                pred_dict["pde"] = out["pde"]
                pred_dict["plddt"] = out["plddt"]
                pred_dict["confidence_score"] = (
                    4 * out["complex_plddt"]
                    + (
                        out["iptm"]
                        if not torch.allclose(
                            out["iptm"], torch.zeros_like(out["iptm"])
                        )
                        else out["ptm"]
                    )
                ) / 5

                pred_dict["complex_plddt"] = out["complex_plddt"]
                pred_dict["complex_iplddt"] = out["complex_iplddt"]
                pred_dict["complex_pde"] = out["complex_pde"]
                pred_dict["complex_ipde"] = out["complex_ipde"]
                if self.alpha_pae > 0:
                    pred_dict["pae"] = out["pae"]
                    pred_dict["ptm"] = out["ptm"]
                    pred_dict["iptm"] = out["iptm"]
                    pred_dict["ligand_iptm"] = out["ligand_iptm"]
                    pred_dict["protein_iptm"] = out["protein_iptm"]
                    pred_dict["pair_chains_iptm"] = out["pair_chains_iptm"]
            if self.affinity_prediction:
                pred_dict["affinity_pred_value"] = out["affinity_pred_value"]
                pred_dict["affinity_probability_binary"] = out[
                    "affinity_probability_binary"
                ]
                if self.affinity_ensemble:
                    pred_dict["affinity_pred_value1"] = out["affinity_pred_value1"]
                    pred_dict["affinity_probability_binary1"] = out[
                        "affinity_probability_binary1"
                    ]
                    pred_dict["affinity_pred_value2"] = out["affinity_pred_value2"]
                    pred_dict["affinity_probability_binary2"] = out[
                        "affinity_probability_binary2"
                    ]
            return pred_dict

        except RuntimeError as e:  # catch out of memory exceptions
            if "out of memory" in str(e):
                print("| WARNING: ran out of memory, skipping batch")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                # Mac GPU support: MPS cache clearing (from https://github.com/fnachon/boltz)
                if torch.backends.mps.is_available():
                    torch.backends.mps.empty_cache()
                gc.collect()
                return {"exception": True}
            else:
                raise e

    def configure_optimizers(self) -> torch.optim.Optimizer:
        """Configure the optimizer."""
        param_dict = dict(self.named_parameters())

        if self.structure_prediction_training:
            all_parameter_names = [
                pn for pn, p in self.named_parameters() if p.requires_grad
            ]
        else:
            all_parameter_names = [
                pn
                for pn, p in self.named_parameters()
                if p.requires_grad
                and ("out_token_feat_update" in pn or "confidence_module" in pn)
            ]

        if self.training_args.get("weight_decay", 0.0) > 0:
            w_decay = self.training_args.get("weight_decay", 0.0)
            if self.training_args.get("weight_decay_exclude", False):
                nodecay_params_names = [
                    pn
                    for pn in all_parameter_names
                    if (
                        "norm" in pn
                        or "rel_pos" in pn
                        or ".s_init" in pn
                        or ".z_init_" in pn
                        or "token_bonds" in pn
                        or "embed_atom_features" in pn
                        or "dist_bin_pairwise_embed" in pn
                    )
                ]
                nodecay_params = [param_dict[pn] for pn in nodecay_params_names]
                decay_params = [
                    param_dict[pn]
                    for pn in all_parameter_names
                    if pn not in nodecay_params_names
                ]
                optim_groups = [
                    {"params": decay_params, "weight_decay": w_decay},
                    {"params": nodecay_params, "weight_decay": 0.0},
                ]
                optimizer = torch.optim.AdamW(
                    optim_groups,
                    betas=(
                        self.training_args.adam_beta_1,
                        self.training_args.adam_beta_2,
                    ),
                    eps=self.training_args.adam_eps,
                    lr=self.training_args.base_lr,
                )

            else:
                optimizer = torch.optim.AdamW(
                    [param_dict[pn] for pn in all_parameter_names],
                    betas=(
                        self.training_args.adam_beta_1,
                        self.training_args.adam_beta_2,
                    ),
                    eps=self.training_args.adam_eps,
                    lr=self.training_args.base_lr,
                    weight_decay=self.training_args.get("weight_decay", 0.0),
                )
        else:
            optimizer = torch.optim.AdamW(
                [param_dict[pn] for pn in all_parameter_names],
                betas=(self.training_args.adam_beta_1, self.training_args.adam_beta_2),
                eps=self.training_args.adam_eps,
                lr=self.training_args.base_lr,
                weight_decay=self.training_args.get("weight_decay", 0.0),
            )

        if self.training_args.lr_scheduler == "af3":
            scheduler = AlphaFoldLRScheduler(
                optimizer,
                base_lr=self.training_args.base_lr,
                max_lr=self.training_args.max_lr,
                warmup_no_steps=self.training_args.lr_warmup_no_steps,
                start_decay_after_n_steps=self.training_args.lr_start_decay_after_n_steps,
                decay_every_n_steps=self.training_args.lr_decay_every_n_steps,
                decay_factor=self.training_args.lr_decay_factor,
            )
            return [optimizer], [{"scheduler": scheduler, "interval": "step"}]

        return optimizer

    def on_load_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        # Ignore the lr from the checkpoint
        lr = self.training_args.max_lr
        weight_decay = self.training_args.weight_decay
        if "optimizer_states" in checkpoint:
            for state in checkpoint["optimizer_states"]:
                for group in state["param_groups"]:
                    group["lr"] = lr
                    group["weight_decay"] = weight_decay
        if "lr_schedulers" in checkpoint:
            for scheduler in checkpoint["lr_schedulers"]:
                scheduler["max_lr"] = lr
                scheduler["base_lrs"] = [lr] * len(scheduler["base_lrs"])
                scheduler["_last_lr"] = [lr] * len(scheduler["_last_lr"])

        # Ignore the training diffusion_multiplicity and recycling steps from the checkpoint
        if "hyper_parameters" in checkpoint:
            checkpoint["hyper_parameters"]["training_args"]["max_lr"] = lr
            checkpoint["hyper_parameters"]["training_args"][
                "diffusion_multiplicity"
            ] = self.training_args.diffusion_multiplicity
            checkpoint["hyper_parameters"]["training_args"][
                "recycling_steps"
            ] = self.training_args.recycling_steps
            checkpoint["hyper_parameters"]["training_args"][
                "weight_decay"
            ] = self.training_args.weight_decay

    def configure_callbacks(self) -> list[Callback]:
        """Configure model callbacks.

        Returns
        -------
        List[Callback]
            List of callbacks to be used in the model.

        """
        return [EMA(self.ema_decay)] if self.use_ema else []

    def _format_residue_ranges(self, residue_list: list[int]) -> str:
        """Convert a list of residue numbers into range format (e.g., [1,2,3,5,6,7] -> '1-3, 5-7').

        Args:
            residue_list: List of residue numbers (1-indexed)

        Returns:
            String with ranges formatted as 'start-end' separated by commas
        """
        if not residue_list:
            return ""

        residue_list = sorted(residue_list)
        ranges = []
        start = residue_list[0]
        end = residue_list[0]

        for i in range(1, len(residue_list)):
            if residue_list[i] == end + 1:
                # Consecutive, extend range
                end = residue_list[i]
            else:
                # Gap found, save current range
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start} - {end}")
                start = residue_list[i]
                end = residue_list[i]

        # Add last range
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start} - {end}")

        return ", ".join(ranges)

    def _validate_and_prepare_inpainting(self, feats: dict[str, Tensor]) -> None:
        """Validate FASTA/structure sequence consistency and prepare template coordinates for inpainting.

        This method:
        1. Validates that FASTA sequence matches structure sequence
        2. Extracts template coordinates from template features (supports multimer by merging all templates)
        3. Creates atom-level template mask (True = has structure, False = needs inpainting)
        4. Prints which residues have structure and which need to be inpainted (per chain for multimer)
        5. Adds inpainting info to feats dictionary

        Args:
            feats: Feature dictionary that will be modified in-place
        """
        # Check if atom-level template information is available
        if "template_atom_coords" not in feats or feats["template_atom_coords"] is None:
            print(
                "[Inpainting] Warning: No template_atom_coords found, inpainting will not be applied"
            )
            feats["inpainting_template_coords"] = None
            feats["inpainting_template_mask"] = None
            return

        template_atom_coords = feats[
            "template_atom_coords"
        ]  # (batch, num_templates, atoms, 3)
        template_atom_mask = feats.get(
            "template_atom_mask", None
        )  # (batch, num_templates, atoms)

        if template_atom_mask is None:
            print(
                "[Inpainting] Warning: No template_atom_mask found, inpainting will not be applied"
            )
            feats["inpainting_template_coords"] = None
            feats["inpainting_template_mask"] = None
            return

        # Debug: Show template mask statistics
        print(
            f"[DEBUG boltz2] template_atom_coords shape: {template_atom_coords.shape}"
        )
        print(f"[DEBUG boltz2] template_atom_mask shape: {template_atom_mask.shape}")
        for template_idx in range(template_atom_mask.shape[1]):
            mask_sum = template_atom_mask[0, template_idx].sum().item()
            print(
                f"[DEBUG boltz2]   Template {template_idx}: {mask_sum} atoms with structure"
            )

        # Use the first batch and merge all templates for multimer support
        # template_atom_coords shape: (batch, num_templates, atoms, 3)
        # template_atom_mask shape: (batch, num_templates, atoms)
        batch_idx = 0
        num_templates = template_atom_coords.shape[1]

        # Merge all templates: if multiple templates provide info for the same atom,
        # use the first template that has valid coordinates
        template_coords = template_atom_coords[batch_idx, 0].clone()  # (atoms, 3)
        template_mask = template_atom_mask[batch_idx, 0].clone()  # (atoms,)

        # Merge additional templates: fill in atoms that weren't covered by the first template
        for template_idx in range(1, num_templates):
            template_coords_t = template_atom_coords[
                batch_idx, template_idx
            ]  # (atoms, 3)
            template_mask_t = template_atom_mask[batch_idx, template_idx]  # (atoms,)

            # For atoms that don't have structure in current mask but do in this template, add them
            new_atoms = (~template_mask.bool()) & template_mask_t.bool()
            template_coords[new_atoms] = template_coords_t[new_atoms]
            template_mask[new_atoms] = template_mask_t[new_atoms]

        if num_templates > 1:
            print(f"[Inpainting] Merged {num_templates} templates for multimer support")

        # Get the expected atom dimension from atom_to_token if available
        atom_to_token = feats.get("atom_to_token", None)
        if atom_to_token is not None:
            expected_num_atoms = atom_to_token.shape[1]  # (batch, atoms, tokens)
            current_num_atoms = template_mask.shape[0]

            # Pad template_mask and template_coords if necessary
            if current_num_atoms < expected_num_atoms:
                padding_size = expected_num_atoms - current_num_atoms
                # Pad template_mask with False (no structure)
                template_mask = torch.nn.functional.pad(
                    template_mask, (0, padding_size), mode="constant", value=0
                )
                # Pad template_coords with zeros
                template_coords = torch.nn.functional.pad(
                    template_coords, (0, 0, 0, padding_size), mode="constant", value=0
                )
            elif current_num_atoms > expected_num_atoms:
                # Truncate if template has more atoms than expected
                template_mask = template_mask[:expected_num_atoms]
                template_coords = template_coords[:expected_num_atoms]

        # Add batch dimension for consistency
        template_coords = template_coords.unsqueeze(0)  # (1, atoms, 3)
        template_mask = template_mask.unsqueeze(0)  # (1, atoms)

        num_atoms = template_coords.shape[1]
        device = template_coords.device

        # Convert mask to boolean
        template_mask_bool = template_mask.bool()

        # Count atoms with and without structure
        num_template_atoms = template_mask_bool.sum().item()
        num_inpaint_atoms = num_atoms - num_template_atoms

        # Report per-residue statistics using atom-to-token mapping (already retrieved above)
        if atom_to_token is not None:
            # atom_to_token is one-hot encoded with shape (batch, atoms, tokens)
            num_tokens = atom_to_token.shape[2]

            # Get chain information for multimer support
            asym_id = feats.get("asym_id", None)  # (batch, tokens) or (tokens,)
            mol_type = feats.get("mol_type", None)  # (batch, tokens) or (tokens,)

            if asym_id is not None:
                if asym_id.dim() > 1:
                    asym_id = asym_id[0]  # Get first batch
                # Convert to numpy for easier processing
                asym_id_np = (
                    asym_id.cpu().numpy()
                    if isinstance(asym_id, torch.Tensor)
                    else asym_id
                )
            else:
                asym_id_np = None

            if mol_type is not None:
                if mol_type.dim() > 1:
                    mol_type = mol_type[0]  # Get first batch
                mol_type_np = (
                    mol_type.cpu().numpy()
                    if isinstance(mol_type, torch.Tensor)
                    else mol_type
                )
            else:
                mol_type_np = None

            # Build asym_id (chain index) -> chain_id (chain name, e.g. "A", "B") for display and metadata
            asym_id_to_chain_name = {}
            if "record" in feats:
                record = feats["record"]
                if isinstance(record, list):
                    record = record[0] if record else None
                if record is not None and hasattr(record, "chains"):
                    for c in record.chains:
                        asym_id_to_chain_name[c.chain_id] = c.chain_name

            def _chain_display(asym_id_val: int) -> str:
                """Return chain ID (name) for display, fallback to index string if no mapping."""
                return asym_id_to_chain_name.get(asym_id_val, str(asym_id_val))

            # Count residues with different levels of structure
            residues_fully_fixed = []
            residues_partially_fixed = []
            residues_fully_inpainted = []

            # For multimer: group by chain
            chain_residues = (
                {}
            )  # chain_id -> {fully_fixed: [], partially_fixed: [], fully_inpainted: []}

            for token_idx in range(num_tokens):
                # Get atoms belonging to this token
                token_atoms = atom_to_token[0, :, token_idx].bool()
                token_atom_mask = token_atoms & template_mask_bool[0]

                # Count atoms in this residue
                total_atoms_in_residue = token_atoms.sum().item()
                template_atoms_in_residue = token_atom_mask.sum().item()

                if total_atoms_in_residue == 0:
                    continue  # Skip empty residues

                # Get chain ID for this token (if available)
                chain_id = None
                if asym_id_np is not None and token_idx < len(asym_id_np):
                    chain_id = int(asym_id_np[token_idx])
                    if chain_id not in chain_residues:
                        chain_residues[chain_id] = {
                            "fully_fixed": [],
                            "partially_fixed": [],
                            "fully_inpainted": [],
                        }

                residue_info = (
                    token_idx + 1,  # 1-indexed
                    template_atoms_in_residue,
                    total_atoms_in_residue,
                    chain_id,
                )

                if template_atoms_in_residue == total_atoms_in_residue:
                    # All atoms have structure
                    residues_fully_fixed.append(residue_info)
                    if chain_id is not None:
                        chain_residues[chain_id]["fully_fixed"].append(token_idx + 1)
                elif template_atoms_in_residue > 0:
                    # Some atoms have structure
                    residues_partially_fixed.append(residue_info)
                    if chain_id is not None:
                        chain_residues[chain_id]["partially_fixed"].append(
                            (
                                token_idx + 1,
                                template_atoms_in_residue,
                                total_atoms_in_residue,
                            )
                        )
                else:
                    # No atoms have structure
                    residues_fully_inpainted.append(residue_info)
                    if chain_id is not None:
                        chain_residues[chain_id]["fully_inpainted"].append(
                            token_idx + 1
                        )

            # Print summary
            print(f"\n[Inpainting] Batch 0 validation:")
            print(f"  Total residues: {num_tokens}")

            # Print chain-specific information for multimer
            if chain_residues:
                print(f"  Number of chains: {len(chain_residues)}")

                # Find the first token_idx for each chain to convert to chain-local residue numbering
                chain_first_token = {}  # chain_id -> first token_idx (0-indexed)
                chain_is_nonpolymer = {}  # chain_id -> is NONPOLYMER
                for token_idx in range(num_tokens):
                    if asym_id_np is not None and token_idx < len(asym_id_np):
                        chain_id = int(asym_id_np[token_idx])
                        if chain_id not in chain_first_token:
                            chain_first_token[chain_id] = token_idx
                            # Check if this chain is NONPOLYMER (ligand)
                            if mol_type_np is not None and token_idx < len(mol_type_np):
                                chain_is_nonpolymer[chain_id] = (
                                    int(mol_type_np[token_idx])
                                    == const.chain_type_ids["NONPOLYMER"]
                                )
                            else:
                                chain_is_nonpolymer[chain_id] = False

                for chain_id in sorted(chain_residues.keys()):
                    chain_info = chain_residues[chain_id]
                    # Get the first token_idx for this chain to convert to chain-local numbering
                    chain_offset = chain_first_token.get(chain_id, 0)
                    is_ligand = chain_is_nonpolymer.get(chain_id, False)

                    chain_type_label = "LIGAND" if is_ligand else "POLYMER"
                    print(f"\n  Chain {_chain_display(chain_id)} ({chain_type_label}):")

                    if is_ligand:
                        # For ligands, show total atoms instead of residue ranges
                        total_residues = (
                            len(chain_info["fully_fixed"])
                            + len(chain_info["partially_fixed"])
                            + len(chain_info["fully_inpainted"])
                        )
                        print(f"    Total residues: {total_residues}")
                        print(
                            f"    Fully fixed residues: {len(chain_info['fully_fixed'])}"
                        )
                        if chain_info["partially_fixed"]:
                            print(
                                f"    Partially fixed residues: {len(chain_info['partially_fixed'])}"
                            )
                            for res_idx, fixed_atoms, total_atoms in chain_info[
                                "partially_fixed"
                            ]:
                                chain_local_res_idx = res_idx - chain_offset
                                print(
                                    f"      Residue {chain_local_res_idx}: {fixed_atoms}/{total_atoms} atoms fixed"
                                )
                        print(
                            f"    Fully inpainted residues: {len(chain_info['fully_inpainted'])}"
                        )
                    else:
                        # For polymers, show residue ranges as before
                        print(
                            f"    Fully fixed residues: {len(chain_info['fully_fixed'])}"
                        )
                        if chain_info["fully_fixed"]:
                            # Convert global residue numbers to chain-local (1-indexed within chain)
                            chain_local_fixed = [
                                res_idx - chain_offset
                                for res_idx in chain_info["fully_fixed"]
                            ]
                            fully_fixed_ranges = self._format_residue_ranges(
                                chain_local_fixed
                            )
                            print(f"      Residues: {fully_fixed_ranges}")
                        print(
                            f"    Partially fixed residues: {len(chain_info['partially_fixed'])}"
                        )
                        if chain_info["partially_fixed"]:
                            for res_idx, fixed_atoms, total_atoms in chain_info[
                                "partially_fixed"
                            ]:
                                # Convert to chain-local residue number
                                chain_local_res_idx = res_idx - chain_offset
                                print(
                                    f"      Residue {chain_local_res_idx}: {fixed_atoms}/{total_atoms} atoms fixed"
                                )
                        print(
                            f"    Fully inpainted residues: {len(chain_info['fully_inpainted'])}"
                        )
                        if chain_info["fully_inpainted"]:
                            # Convert global residue numbers to chain-local (1-indexed within chain)
                            chain_local_inpainted = [
                                res_idx - chain_offset
                                for res_idx in chain_info["fully_inpainted"]
                            ]
                            fully_inpainted_ranges = self._format_residue_ranges(
                                chain_local_inpainted
                            )
                            print(f"      Residues: {fully_inpainted_ranges}")

            # Print overall summary
            print(f"\n  Overall summary:")
            print(
                f"  Residues FULLY FIXED (all atoms have structure): {len(residues_fully_fixed)}"
            )
            if residues_fully_fixed:
                fully_fixed_ranges = self._format_residue_ranges(
                    [r[0] for r in residues_fully_fixed]
                )
                print(f"    Residues: {fully_fixed_ranges}")
            else:
                print("    Residues: (none)")

            print(
                f"  Residues PARTIALLY FIXED (some atoms have structure, some need inpainting): {len(residues_partially_fixed)}"
            )
            if residues_partially_fixed:
                for res_info in residues_partially_fixed:
                    res_idx, fixed_atoms, total_atoms, chain_id = res_info
                    chain_str = (
                        f" (Chain {_chain_display(chain_id)})"
                        if chain_id is not None
                        else ""
                    )
                    print(
                        f"    Residue {res_idx}{chain_str}: {fixed_atoms}/{total_atoms} atoms fixed"
                    )
            else:
                print("    Residues: (none)")

            print(
                f"  Residues FULLY INPAINTED (no atoms have structure): {len(residues_fully_inpainted)}"
            )
            if residues_fully_inpainted:
                fully_inpainted_ranges = self._format_residue_ranges(
                    [r[0] for r in residues_fully_inpainted]
                )
                print(f"    Residues: {fully_inpainted_ranges}")
            else:
                print("    Residues: (none)")

        print(
            f"  Total atoms WITH template structure: {num_template_atoms} / {num_atoms}"
        )
        print(f"  Total atoms to be INPAINTED: {num_inpaint_atoms} / {num_atoms}")

        # Center template coordinates to avoid issues with large absolute coordinate values
        # This ensures that r_to_q_trans receives coordinates in a similar distribution to training
        # Log mean before centering
        mean_before_centering = template_coords[0][template_mask_bool[0]].mean(dim=0)
        print(
            f"[Inpainting] Template coordinates before centering (mean: {mean_before_centering.norm().item():.6f}, "
            f"values: [{mean_before_centering[0].item():.3f}, {mean_before_centering[1].item():.3f}, {mean_before_centering[2].item():.3f}])"
        )

        template_coords_centered = center(template_coords, template_mask_bool)

        # Verify centering worked (mean should be close to zero)
        mean_after_centering = template_coords_centered[0][template_mask_bool[0]].mean(
            dim=0
        )
        print(
            f"[Inpainting] Template coordinates after centering (mean: {mean_after_centering.norm().item():.6f}, "
            f"values: [{mean_after_centering[0].item():.3f}, {mean_after_centering[1].item():.3f}, {mean_after_centering[2].item():.3f}])"
        )
        template_coords = template_coords_centered

        # Store inpainting information in feats
        feats["inpainting_template_coords"] = template_coords
        feats["inpainting_template_mask"] = template_mask_bool

        # Store inpainting metadata for JSON export (chain-based only)
        # Use chain ID (chain name, e.g. "A", "B") as key when available from record; else "chain_{index}"
        # Convert global residue indices to chain-local indices (starting from 1 for each chain)
        inpainting_metadata = {}
        if atom_to_token is not None and chain_residues:
            # Find the first token_idx for each chain to convert to chain-local residue numbering
            chain_first_token = {}  # chain_id -> first token_idx (0-indexed)
            if asym_id_np is not None:
                for token_idx in range(num_tokens):
                    if token_idx < len(asym_id_np):
                        chain_id = int(asym_id_np[token_idx])
                        if chain_id not in chain_first_token:
                            chain_first_token[chain_id] = token_idx

            inpainting_metadata["chains"] = {}
            for chain_id, info in chain_residues.items():
                # Use chain name (e.g. "A", "B") as key when available
                chain_key = (
                    asym_id_to_chain_name.get(chain_id, f"chain_{chain_id}")
                    if asym_id_to_chain_name
                    else f"chain_{chain_id}"
                )
                # Get the chain offset (first token_idx for this chain)
                chain_offset = chain_first_token.get(chain_id, 0)

                # Convert global residue indices to chain-local (1-indexed within chain)
                fully_fixed_local = [int(r) - chain_offset for r in info["fully_fixed"]]
                partially_fixed_local = [
                    {
                        "residue": int(r[0]) - chain_offset,
                        "fixed_atoms": int(r[1]),
                        "total_atoms": int(r[2]),
                    }
                    for r in info["partially_fixed"]
                ]
                fully_inpainted_local = [
                    int(r) - chain_offset for r in info["fully_inpainted"]
                ]

                inpainting_metadata["chains"][chain_key] = {
                    "fully_fixed_residues": fully_fixed_local,
                    "partially_fixed_residues": partially_fixed_local,
                    "fully_inpainted_residues": fully_inpainted_local,
                }
        else:
            inpainting_metadata["chains"] = {}

        feats["inpainting_metadata"] = inpainting_metadata

        print(f"\n[Inpainting] Validation complete. Template coordinates prepared.\n")
