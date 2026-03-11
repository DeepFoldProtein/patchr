"""
PATCHR — unified CLI for structure inpainting and prediction.

Subcommands
-----------
patchr predict   Run structure prediction (Boltz-2 or Protenix backend)
patchr template  Generate inpainting template from a PDB structure
patchr serve     Start the REST API server
"""

import multiprocessing
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

import click


# ---------------------------------------------------------------------------
# Top-level CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="patchr")
def cli() -> None:
    """PATCHR — diffusion-based structure completion for proteins, DNA, RNA, and complexes."""


# ---------------------------------------------------------------------------
# patchr predict
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("data", type=click.Path(exists=True))
@click.option("--out_dir", type=click.Path(exists=False), default="./", help="Output directory.")
@click.option(
    "--backend",
    type=click.Choice(["boltz2", "protenix"]),
    default="boltz2",
    help="Prediction backend. Default: boltz2.",
)
@click.option(
    "--cache",
    type=click.Path(exists=False),
    default=None,
    help="Model/data cache directory (default: ~/.boltz or $BOLTZ_CACHE).",
)
@click.option("--checkpoint", type=click.Path(exists=True), default=None, help="Custom model checkpoint.")
@click.option("--devices", type=int, default=1, help="Number of devices. Default: 1.")
@click.option(
    "--accelerator",
    type=click.Choice(["gpu", "cpu", "tpu"]),
    default="gpu",
    help="Accelerator. Default: gpu.",
)
@click.option("--recycling_steps", type=int, default=3, help="Recycling steps. Default: 3.")
@click.option("--sampling_steps", type=int, default=200, help="Sampling (diffusion) steps. Default: 200.")
@click.option("--diffusion_samples", type=int, default=1, help="Number of diffusion samples. Default: 1.")
@click.option("--max_parallel_samples", type=int, default=5, help="Max parallel samples. Default: 5.")
@click.option("--step_scale", type=float, default=None, help="Diffusion step scale (temperature). Default: backend-specific.")
@click.option("--write_full_pae", is_flag=True, help="Write full PAE matrix.")
@click.option("--write_full_pde", is_flag=True, help="Write full PDE matrix.")
@click.option(
    "--output_format",
    type=click.Choice(["pdb", "mmcif"]),
    default="mmcif",
    help="Output structure format. Default: mmcif.",
)
@click.option("--num_workers", type=int, default=2, help="Dataloader workers. Default: 2.")
@click.option("--override", is_flag=True, help="Override existing predictions.")
@click.option("--seed", type=int, default=None, help="Random seed.")
@click.option("--seeds", type=str, default=None, help="Comma-separated seeds (Protenix). E.g. '42,101'.")
@click.option("--use_msa_server", is_flag=True, help="Use MMSeqs2 server for MSA generation.")
@click.option("--msa_server_url", type=str, default="https://api.colabfold.com", help="MSA server URL.")
@click.option("--msa_pairing_strategy", type=str, default="greedy", help="MSA pairing strategy.")
@click.option("--use_potentials", is_flag=True, help="Use potentials for steering (Boltz only).")
@click.option("--inpainting/--no-inpainting", default=True, help="Enable inpainting mode. Default: enabled.")
@click.option("--disable_boundary_refinement", is_flag=True, help="Disable boundary refinement (LRD).")
@click.option(
    "--preprocessing-threads",
    type=int,
    default=multiprocessing.cpu_count(),
    help="Preprocessing threads.",
)
@click.option("--max_msa_seqs", type=int, default=8192, help="Max MSA sequences.")
@click.option("--subsample_msa", is_flag=True, help="Subsample MSA.")
@click.option("--num_subsampled_msa", type=int, default=1024, help="Subsampled MSA count.")
@click.option("--no_kernels", is_flag=True, help="Disable custom kernels (Boltz).")
@click.option("--write_embeddings", is_flag=True, help="Write s/z embeddings (Boltz).")
@click.option("--method", type=str, default=None, help="Method conditioning (Boltz-2 only).")
# Post-processing options
@click.option("--sim-ready", "sim_ready_engine", type=click.Choice(["gromacs", "amber", "openmm"]), default=None,
              help="After prediction, prepare simulation-ready files for the given MD engine.")
@click.option("--membrane", "membrane_lipid", type=click.Choice(["POPC", "POPE", "DLPC", "DLPE", "DMPC", "DOPC", "DPPC"]), default=None,
              help="After prediction, embed in a lipid membrane of the given type.")
@click.option("--pdb-id", "sim_pdb_id", type=str, default=None, help="PDB ID for OPM membrane orientation lookup.")
@click.option("--ff", "sim_ff", type=click.Choice(["charmm36m", "charmm36", "amber14sb", "amber99sbildn", "amber19sb"]),
              default="charmm36m", help="Force field for sim-ready/membrane. Default: charmm36m.")
def predict(  # noqa: C901, PLR0912, PLR0913, PLR0915
    data: str,
    out_dir: str,
    backend: str,
    cache: Optional[str],
    checkpoint: Optional[str],
    devices: int,
    accelerator: str,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
    max_parallel_samples: int,
    step_scale: Optional[float],
    write_full_pae: bool,
    write_full_pde: bool,
    output_format: str,
    num_workers: int,
    override: bool,
    seed: Optional[int],
    seeds: Optional[str],
    use_msa_server: bool,
    msa_server_url: str,
    msa_pairing_strategy: str,
    use_potentials: bool,
    inpainting: bool,
    disable_boundary_refinement: bool,
    preprocessing_threads: int,
    max_msa_seqs: int,
    subsample_msa: bool,
    num_subsampled_msa: int,
    no_kernels: bool,
    write_embeddings: bool,
    method: Optional[str],
    sim_ready_engine: Optional[str],
    membrane_lipid: Optional[str],
    sim_pdb_id: Optional[str],
    sim_ff: str,
) -> None:
    """Run structure prediction.

    DATA is a YAML/FASTA input file or directory.

    \b
    Examples:
      patchr predict input.yaml --out_dir results
      patchr predict input.yaml --out_dir results --backend protenix --seed 42
      patchr predict input.yaml --out_dir results --sim-ready gromacs
      patchr predict input.yaml --out_dir results --membrane POPC --pdb-id 4HFI
    """
    if backend == "protenix":
        _predict_protenix(
            data=data,
            out_dir=out_dir,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
            diffusion_samples=diffusion_samples,
            seed=seed,
            seeds=seeds,
        )
    else:
        _predict_boltz(
            data=data,
            out_dir=out_dir,
            cache=cache,
            checkpoint=checkpoint,
            devices=devices,
            accelerator=accelerator,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
            diffusion_samples=diffusion_samples,
            max_parallel_samples=max_parallel_samples,
            step_scale=step_scale,
            write_full_pae=write_full_pae,
            write_full_pde=write_full_pde,
            output_format=output_format,
            num_workers=num_workers,
            override=override,
            seed=seed,
            use_msa_server=use_msa_server,
            msa_server_url=msa_server_url,
            msa_pairing_strategy=msa_pairing_strategy,
            use_potentials=use_potentials,
            inpainting=inpainting,
            disable_boundary_refinement=disable_boundary_refinement,
            preprocessing_threads=preprocessing_threads,
            max_msa_seqs=max_msa_seqs,
            subsample_msa=subsample_msa,
            num_subsampled_msa=num_subsampled_msa,
            no_kernels=no_kernels,
            write_embeddings=write_embeddings,
            method=method,
        )

    # Post-processing: sim-ready or membrane
    if sim_ready_engine or membrane_lipid:
        _run_post_processing(
            data=data,
            out_dir=out_dir,
            sim_ready_engine=sim_ready_engine,
            membrane_lipid=membrane_lipid,
            pdb_id=sim_pdb_id,
            ff=sim_ff,
        )


def _run_post_processing(
    data: str,
    out_dir: str,
    sim_ready_engine: Optional[str],
    membrane_lipid: Optional[str],
    pdb_id: Optional[str],
    ff: str,
) -> None:
    """Run sim-ready or membrane post-processing on prediction output."""
    import glob

    data_path = Path(data).expanduser()
    out_path = Path(out_dir).expanduser()
    results_dir = out_path / f"patchr_results_{data_path.stem}"
    predictions_dir = results_dir / "predictions"

    # Find all output CIF files
    cif_files = sorted(glob.glob(str(predictions_dir / "**" / "*_model_*.cif"), recursive=True))
    if not cif_files:
        click.echo("Warning: No prediction CIF files found for post-processing.")
        return

    # Process only the first model (model_0)
    cif_path = cif_files[0]
    click.echo(f"\nPost-processing: {Path(cif_path).name}")

    if membrane_lipid:
        from boltz.membrane import MembraneConfig, build_membrane_system

        engine = sim_ready_engine or "gromacs"
        sim_dir = results_dir / "membrane"
        config = MembraneConfig(
            input_cif=cif_path,
            output_dir=str(sim_dir),
            pdb_id=pdb_id,
            lipid_type=membrane_lipid,
            engine=engine,
            forcefield=ff,
        )
        result = build_membrane_system(config, progress_callback=lambda s, p: click.echo(f"  [{p*100:5.1f}%] {s}"))
        click.echo(f"\nMembrane system: {result.n_atoms:,} atoms, {result.n_lipids} lipids, {result.n_waters:,} waters")
        click.echo(f"  Box: {result.box_size[0]:.2f} x {result.box_size[1]:.2f} x {result.box_size[2]:.2f} nm")
        for key, path in result.files.items():
            click.echo(f"  {key}: {path}")

    elif sim_ready_engine:
        from boltz.sim_ready import SimReadyConfig, prepare_sim_ready

        sim_dir = results_dir / "sim_ready"
        config = SimReadyConfig(
            input_cif=cif_path,
            output_dir=str(sim_dir),
            engine=sim_ready_engine,
            forcefield=ff,
        )
        result = prepare_sim_ready(config, progress_callback=lambda s, p: click.echo(f"  [{p*100:5.1f}%] {s}"))
        click.echo(f"\nSim-ready: {result.n_atoms:,} atoms, {result.n_waters:,} waters, {result.n_ions} ions")
        click.echo(f"  Box: {result.box_size[0]:.2f} x {result.box_size[1]:.2f} x {result.box_size[2]:.2f} nm")
        for key, path in result.files.items():
            click.echo(f"  {key}: {path}")


def _predict_boltz(
    data: str,
    out_dir: str,
    cache: Optional[str],
    checkpoint: Optional[str],
    devices: int,
    accelerator: str,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
    max_parallel_samples: int,
    step_scale: Optional[float],
    write_full_pae: bool,
    write_full_pde: bool,
    output_format: str,
    num_workers: int,
    override: bool,
    seed: Optional[int],
    use_msa_server: bool,
    msa_server_url: str,
    msa_pairing_strategy: str,
    use_potentials: bool,
    inpainting: bool,
    disable_boundary_refinement: bool,
    preprocessing_threads: int,
    max_msa_seqs: int,
    subsample_msa: bool,
    num_subsampled_msa: int,
    no_kernels: bool,
    write_embeddings: bool,
    method: Optional[str],
) -> None:
    """Run Boltz-2 prediction."""
    import pickle
    import platform
    from dataclasses import asdict
    from functools import partial

    import torch
    from pytorch_lightning import Trainer, seed_everything
    from pytorch_lightning.strategies import DDPStrategy
    from rdkit import Chem

    from boltz.data import const
    from boltz.data.module.inference import BoltzInferenceDataModule
    from boltz.data.module.inferencev2 import Boltz2InferenceDataModule
    from boltz.data.types import Manifest
    from boltz.data.write.writer import BoltzAffinityWriter, BoltzWriter
    from boltz.main import (
        Boltz2DiffusionParams,
        BoltzProcessedInput,
        BoltzSteeringParams,
        MSAModuleArgs,
        PairformerArgsV2,
        check_inputs,
        download_boltz2,
        filter_inputs_structure,
        get_cache_path,
        process_inputs,
    )
    from boltz.model.models.boltz2 import Boltz2

    if accelerator == "cpu":
        click.echo("Running on CPU — this will be slow. Consider using a GPU.")

    warnings.filterwarnings("ignore", ".*that has Tensor Cores. To properly utilize them.*")
    torch.set_grad_enabled(False)
    torch.set_float32_matmul_precision("highest")
    Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)

    if seed is not None:
        seed_everything(seed)

    for key in ["CUEQ_DEFAULT_CONFIG", "CUEQ_DISABLE_AOT_TUNING"]:
        os.environ[key] = os.environ.get(key, "1")

    # Cache
    if cache is None:
        cache = get_cache_path()
    cache_path = Path(cache).expanduser()
    cache_path.mkdir(parents=True, exist_ok=True)

    # MSA credentials
    msa_server_username = os.environ.get("BOLTZ_MSA_USERNAME") if use_msa_server else None
    msa_server_password = os.environ.get("BOLTZ_MSA_PASSWORD") if use_msa_server else None
    api_key_value = os.environ.get("MSA_API_KEY_VALUE") if use_msa_server else None

    # Output directory
    data_path = Path(data).expanduser()
    out_path = Path(out_dir).expanduser()
    results_dir = out_path / f"patchr_results_{data_path.stem}"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Download model
    download_boltz2(cache_path)

    # Validate inputs
    input_paths = check_inputs(data_path)

    # Check method
    if method is not None:
        if method.lower() not in const.method_types_ids:
            method_names = list(const.method_types_ids.keys())
            msg = f"Method {method} not supported. Supported: {method_names}"
            raise ValueError(msg)

    # Process inputs
    mol_dir = cache_path / "mols"
    process_inputs(
        data=input_paths,
        out_dir=results_dir,
        ccd_path=cache_path / "ccd.pkl",
        mol_dir=mol_dir,
        use_msa_server=use_msa_server,
        msa_server_url=msa_server_url,
        msa_pairing_strategy=msa_pairing_strategy,
        msa_server_username=msa_server_username,
        msa_server_password=msa_server_password,
        api_key_header=None,
        api_key_value=api_key_value,
        boltz2=True,
        preprocessing_threads=preprocessing_threads,
        max_msa_seqs=max_msa_seqs,
        override=override,
    )

    manifest = Manifest.load(results_dir / "processed" / "manifest.json")
    filtered_manifest = filter_inputs_structure(manifest=manifest, outdir=results_dir, override=override)

    processed_dir = results_dir / "processed"
    processed = BoltzProcessedInput(
        manifest=filtered_manifest,
        targets_dir=processed_dir / "structures",
        msa_dir=processed_dir / "msa",
        constraints_dir=(processed_dir / "constraints") if (processed_dir / "constraints").exists() else None,
        template_dir=(processed_dir / "templates") if (processed_dir / "templates").exists() else None,
        extra_mols_dir=(processed_dir / "mols") if (processed_dir / "mols").exists() else None,
    )

    # Trainer strategy
    strategy = "auto"
    if torch.backends.mps.is_available():
        devices = 1
        num_workers = 0
    elif (isinstance(devices, int) and devices > 1) or (isinstance(devices, list) and len(devices) > 1):
        start_method = "fork" if platform.system() not in ("win32", "Windows") else "spawn"
        strategy = DDPStrategy(start_method=start_method)
        if len(filtered_manifest.records) < devices:
            click.echo("Requested devices > predictions; using minimum.")
            devices = max(1, min(len(filtered_manifest.records), devices))

    # Model params
    enable_inpainting = inpainting
    diffusion_params = Boltz2DiffusionParams()
    diffusion_params.step_scale = 1.5 if step_scale is None else step_scale
    pairformer_args = PairformerArgsV2()
    msa_args = MSAModuleArgs(
        subsample_msa=subsample_msa,
        num_subsampled_msa=num_subsampled_msa,
        use_paired_feature=True,
    )

    pred_writer = BoltzWriter(
        data_dir=processed.targets_dir,
        output_dir=results_dir / "predictions",
        output_format=output_format,
        boltz2=True,
        write_embeddings=write_embeddings,
    )

    trainer = Trainer(
        default_root_dir=results_dir,
        strategy=strategy,
        callbacks=[pred_writer],
        accelerator=accelerator,
        devices=devices,
        precision=32 if torch.backends.mps.is_available() else "bf16-mixed",
    )

    if filtered_manifest.records:
        n = len(filtered_manifest.records)
        click.echo(f"Running structure prediction for {n} input{'s' if n > 1 else ''}.")

        data_module = Boltz2InferenceDataModule(
            manifest=processed.manifest,
            target_dir=processed.targets_dir,
            msa_dir=processed.msa_dir,
            mol_dir=mol_dir,
            num_workers=num_workers,
            constraints_dir=processed.constraints_dir,
            template_dir=processed.template_dir,
            extra_mols_dir=processed.extra_mols_dir,
            override_method=method,
        )

        if checkpoint is None:
            checkpoint = str(cache_path / "boltz2_conf.ckpt")

        predict_args = {
            "recycling_steps": recycling_steps,
            "sampling_steps": sampling_steps,
            "diffusion_samples": diffusion_samples,
            "max_parallel_samples": max_parallel_samples,
            "write_confidence_summary": True,
            "write_full_pae": write_full_pae,
            "write_full_pde": write_full_pde,
            "boundary_refinement_enabled": not disable_boundary_refinement,
        }

        steering_args = BoltzSteeringParams()
        steering_args.fk_steering = use_potentials
        steering_args.physical_guidance_update = use_potentials
        steering_args.contact_guidance_update = use_potentials
        steering_args.inpainting = enable_inpainting

        model_module = Boltz2.load_from_checkpoint(
            checkpoint,
            strict=True,
            weights_only=False,
            predict_args=predict_args,
            map_location="cpu",
            diffusion_process_args=asdict(diffusion_params),
            ema=False,
            use_kernels=not no_kernels,
            pairformer_args=asdict(pairformer_args),
            msa_args=asdict(msa_args),
            steering_args=asdict(steering_args),
            enable_inpainting=enable_inpainting,
        )
        model_module.eval()

        trainer.predict(model_module, datamodule=data_module, return_predictions=False)

    click.echo(f"Results saved to {results_dir}")


def _predict_protenix(
    data: str,
    out_dir: str,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
    seed: Optional[int],
    seeds: Optional[str],
) -> None:
    """Run Protenix prediction with unified output format."""
    import torch

    # Ensure paths are on sys.path
    project_root = Path(__file__).resolve().parent.parent.parent
    for p in [str(project_root / "src"), str(project_root)]:
        if p not in sys.path:
            sys.path.insert(0, p)

    from protenix_configs.configs_base import configs as configs_base
    from protenix_configs.configs_data import data_configs
    from protenix_configs.configs_inference import inference_configs
    from protenix_configs.configs_model_type import model_configs
    from ml_collections.config_dict import ConfigDict
    from protenix.config.config import parse_configs
    from protenix_runner.inference import (
        InferenceRunner,
        download_inference_cache,
        infer_predict,
        update_gpu_compatible_configs,
    )

    model_name = "protenix_base_default_v1.0.0"
    inference_configs["model_name"] = model_name

    # Parse seeds
    seed_list = [101]
    if seeds:
        seed_list = [int(s.strip()) for s in seeds.split(",")]
    elif seed is not None:
        seed_list = [seed]

    # Build config
    configs = {**configs_base, **{"data": data_configs}, **inference_configs}
    configs = parse_configs(configs=configs, fill_required_with_null=True)

    model_name_parts = model_name.split("_", 3)
    if len(model_name_parts) == 4:
        _, model_size, model_feature, model_version = model_name_parts
    else:
        model_size = model_feature = model_version = "unknown"

    model_specfics_configs = ConfigDict(model_configs[model_name])
    configs.update(model_specfics_configs)

    # Set parameters
    data_path = Path(data).expanduser()
    out_path = Path(out_dir).expanduser()
    results_dir = out_path / f"patchr_results_{data_path.stem}"

    configs.input_path = str(data_path)
    configs.dump_dir = str(results_dir)
    configs.model.N_cycle = recycling_steps
    configs.sample_diffusion.N_step = sampling_steps
    configs.sample_diffusion.N_sample = diffusion_samples
    configs.seeds = seed_list
    configs.dtype = "bf16"
    configs.use_msa = True
    configs.triangle_multiplicative = "cuequivariance"
    configs.triangle_attention = "cuequivariance"
    configs.enable_diffusion_shared_vars_cache = True
    configs.enable_efficient_fusion = True
    configs.enable_tf32 = True
    configs.use_template = False
    configs.use_rna_msa = False
    configs.use_seeds_in_json = False
    configs.need_atom_confidence = False

    configs = update_gpu_compatible_configs(configs)

    click.echo(f"Running Protenix prediction (model={model_name}, seeds={seed_list})")

    download_inference_cache(configs)
    runner = InferenceRunner(configs)

    torch.set_grad_enabled(False)
    infer_predict(runner, configs)

    click.echo(f"Results saved to {results_dir}")


# ---------------------------------------------------------------------------
# patchr template
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("pdb_id", required=False, default=None)
@click.argument("chain_ids", required=False, default=None)
@click.option("--input", "-i", "input_file", type=click.Path(exists=True), default=None, help="Local CIF file.")
@click.option("--uniprot", is_flag=True, help="Use UniProt sequence instead of SEQRES.")
@click.option("--sequence", "-s", type=str, default=None, help="Custom sequence(s). E.g. 'ACDEFG' or 'A:ACDEFG,B:MNOPQR'.")
@click.option("-o", "--out_dir", type=click.Path(), default="examples/inpainting", help="Output directory.")
@click.option("--include-solvent", is_flag=True, help="Include solvent atoms.")
@click.option("--exclude-ligands", is_flag=True, help="Exclude non-polymer ligands.")
@click.option("--assembly", type=str, default=None, help="Biological assembly ID or 'best'.")
@click.option("--list-assemblies", is_flag=True, help="List assemblies and exit.")
@click.option("--skip-terminal", is_flag=True, help="Skip terminal missing residues.")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
@click.option("--interactive", is_flag=True, help="Prompt for sequence input.")
@click.option("--format", "output_format", type=click.Choice(["yaml", "protenix-json"]), default="yaml", help="Output format.")
def template(
    pdb_id: Optional[str],
    chain_ids: Optional[str],
    input_file: Optional[str],
    uniprot: bool,
    sequence: Optional[str],
    out_dir: str,
    include_solvent: bool,
    exclude_ligands: bool,
    assembly: Optional[str],
    list_assemblies: bool,
    skip_terminal: bool,
    verbose: bool,
    interactive: bool,
    output_format: str,
) -> None:
    """Generate inpainting template from a PDB structure.

    \b
    Examples:
      patchr template 4ZLO A,B
      patchr template 4ZLO A,B --uniprot
      patchr template --input structure.cif A,B
      patchr template 1CK4 all --assembly best
    """
    import re

    # Ensure scripts dir is on path
    scripts_dir = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from inpainting.structure_processor import StructureProcessor

    # Parse custom sequences
    custom_sequences = {}
    if sequence:
        if ":" in sequence:
            for pair in sequence.split(","):
                pair = pair.strip()
                if ":" in pair:
                    chain, seq = pair.split(":", 1)
                    chain = chain.strip().upper()
                    chain = re.sub(r"\s*\[(?:DNA|RNA|PROTEIN)\]\s*", "", chain).strip()
                    custom_sequences[chain] = seq.strip()
        else:
            custom_sequences["_default_"] = sequence.strip()

    # Resolve input source
    assembly_id = assembly
    cif_file_path = None

    if input_file:
        cif_file_path = input_file
        resolved_pdb_id = Path(input_file).stem
        resolved_chain_ids = pdb_id if (pdb_id and not chain_ids) else chain_ids
        if not resolved_chain_ids:
            click.echo("Error: chain_ids required when using --input.", err=True)
            sys.exit(1)
    elif pdb_id:
        pdb_path = Path(pdb_id)
        if pdb_path.suffix.lower() in (".cif", ".pdb") or pdb_path.exists():
            cif_file_path = str(pdb_path)
            resolved_pdb_id = pdb_path.stem
            resolved_chain_ids = chain_ids or "ALL"
            if assembly_id is None and not list_assemblies:
                assembly_id = "1"
        else:
            resolved_pdb_id = pdb_id
            resolved_chain_ids = chain_ids or "ALL"
            if not chain_ids and assembly_id is None and not list_assemblies:
                assembly_id = "1"
    else:
        click.echo("Error: provide PDB_ID or --input.", err=True)
        sys.exit(1)

    processor = StructureProcessor(
        pdb_id=resolved_pdb_id,
        chain_ids=resolved_chain_ids,
        uniprot_mode=uniprot,
        cif_file_path=cif_file_path,
        interactive_sequence=interactive,
        custom_sequences=custom_sequences,
        cache_dir=Path(out_dir) if False else None,  # cache_dir is separate
        include_solvent=include_solvent,
        include_ligands=not exclude_ligands,
        assembly_id=assembly_id,
        list_assemblies=list_assemblies,
        skip_terminal=skip_terminal,
        verbose=verbose,
        output_format=output_format,
    )
    processor.process(Path(out_dir))


# ---------------------------------------------------------------------------
# patchr serve
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--host", type=str, default="0.0.0.0", help="Host to bind. Default: 0.0.0.0.")
@click.option("--port", type=int, default=31212, help="Port. Default: 31212.")
@click.option("--device-id", type=str, default=None, help="GPU device ID (e.g. '0').")
@click.option(
    "--model",
    type=click.Choice(["boltz2", "protenix", "all"]),
    default=None,
    help="Model(s) to preload. Default: boltz2.",
)
@click.option("--work-dir", type=click.Path(), default="./patchr_jobs", help="Job working directory.")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev mode).")
def serve(
    host: str,
    port: int,
    device_id: Optional[str],
    model: Optional[str],
    work_dir: str,
    reload: bool,
) -> None:
    """Start the PATCHR REST API server.

    \b
    Examples:
      patchr serve
      patchr serve --model boltz2 --device-id 0
      patchr serve --model all --port 8080
    """
    import uvicorn

    # Set env vars so server.py picks them up
    if device_id is not None:
        os.environ["PATCHR_DEVICE_ID"] = device_id
    if model is not None:
        os.environ["PATCHR_DEFAULT_MODEL"] = model

    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    os.environ["PATCHR_WORK_DIR"] = str(work_path.resolve())

    click.echo(f"Starting PATCHR server on {host}:{port}")
    click.echo(f"Model: {model or os.environ.get('PATCHR_DEFAULT_MODEL', 'boltz2')}")
    click.echo(f"Work dir: {work_path.resolve()}")
    if device_id:
        click.echo(f"Device: {device_id}")
    click.echo(f"API docs: http://{host}:{port}/docs")

    if reload:
        uvicorn.run("server:app", host=host, port=port, reload=True)
    else:
        # Import server app directly
        project_root = Path(__file__).resolve().parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from server import app  # noqa: E402

        uvicorn.run(app, host=host, port=port)


# ---------------------------------------------------------------------------
# patchr sim-ready
# ---------------------------------------------------------------------------

@cli.command("sim-ready")
@click.argument("input_cif", type=click.Path(exists=True))
@click.option("-o", "--out-dir", type=click.Path(), default=None, help="Output directory. Default: ./sim_ready_{stem}/")
@click.option(
    "--engine",
    type=click.Choice(["gromacs", "amber", "openmm"]),
    default="gromacs",
    help="MD engine output format. Default: gromacs.",
)
@click.option(
    "--ff",
    type=click.Choice(["charmm36m", "charmm36", "amber14sb", "amber99sbildn", "amber19sb"]),
    default="charmm36m",
    help="Force field. Default: charmm36m.",
)
@click.option("--water", type=click.Choice(["tip3p", "tip3pfb", "tip4pew", "spce"]), default="tip3p", help="Water model.")
@click.option("--ph", type=float, default=7.0, help="Protonation pH. Default: 7.0.")
@click.option("--padding", type=float, default=1.0, help="Box padding in nm. Default: 1.0.")
@click.option("--ion-conc", type=float, default=0.15, help="Ion concentration in mol/L. Default: 0.15.")
@click.option("--keep-water", is_flag=True, help="Keep crystallographic waters.")
def sim_ready(
    input_cif: str,
    out_dir: Optional[str],
    engine: str,
    ff: str,
    water: str,
    ph: float,
    padding: float,
    ion_conc: float,
    keep_water: bool,
) -> None:
    """Prepare a simulation-ready system from a predicted structure.

    Takes a CIF file (e.g. from patchr predict) and produces force-field
    parameterized, solvated, ionized files ready for MD simulation.

    \b
    Examples:
      patchr sim-ready results/prediction.cif
      patchr sim-ready prediction.cif --engine amber --ff amber14sb
      patchr sim-ready prediction.cif --engine gromacs --ff charmm36m --ion-conc 0.15
      patchr sim-ready prediction.cif --engine openmm --padding 1.2
    """
    from boltz.sim_ready import SimReadyConfig, prepare_sim_ready

    if out_dir is None:
        stem = Path(input_cif).stem
        out_dir = f"./sim_ready_{stem}"

    config = SimReadyConfig(
        input_cif=input_cif,
        output_dir=out_dir,
        engine=engine,
        forcefield=ff,
        water_model=water,
        ph=ph,
        padding=padding,
        ion_concentration=ion_conc,
        keep_water=keep_water,
    )

    def progress(step, pct):
        click.echo(f"  [{pct*100:5.1f}%] {step}")

    click.echo(f"Preparing simulation-ready system: {input_cif}")
    click.echo(f"  Engine: {engine} | FF: {ff} | Water: {water}")
    click.echo(f"  pH: {ph} | Padding: {padding} nm | Ions: {ion_conc} M")

    result = prepare_sim_ready(config, progress_callback=progress)

    click.echo(f"\nSystem summary:")
    click.echo(f"  Atoms: {result.n_atoms:,}")
    click.echo(f"  Waters: {result.n_waters:,}")
    click.echo(f"  Ions: {result.n_ions}")
    click.echo(f"  Box: {result.box_size[0]:.2f} x {result.box_size[1]:.2f} x {result.box_size[2]:.2f} nm")
    click.echo(f"\nOutput files:")
    for key, path in result.files.items():
        click.echo(f"  {key}: {path}")


# ---------------------------------------------------------------------------
# patchr membrane
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("input_cif", type=click.Path(exists=True))
@click.option("-o", "--out-dir", type=click.Path(), default=None, help="Output directory.")
@click.option("--pdb-id", type=str, default=None, help="PDB ID for OPM orientation lookup.")
@click.option(
    "--lipid",
    type=click.Choice(["POPC", "POPE", "DLPC", "DLPE", "DMPC", "DOPC", "DPPC"]),
    default="POPC",
    help="Lipid type. Default: POPC.",
)
@click.option(
    "--engine",
    type=click.Choice(["gromacs", "amber", "openmm"]),
    default="gromacs",
    help="MD engine output format. Default: gromacs.",
)
@click.option(
    "--ff",
    type=click.Choice(["charmm36m", "charmm36", "amber14sb", "amber99sbildn", "amber19sb"]),
    default="charmm36m",
    help="Force field. Default: charmm36m.",
)
@click.option("--water", type=click.Choice(["tip3p", "tip3pfb", "tip4pew", "spce"]), default="tip3p", help="Water model.")
@click.option("--ph", type=float, default=7.0, help="Protonation pH. Default: 7.0.")
@click.option("--padding", type=float, default=1.0, help="Membrane padding in nm. Default: 1.0.")
@click.option("--ion-conc", type=float, default=0.15, help="Ion concentration in mol/L. Default: 0.15.")
@click.option("--skip-opm", is_flag=True, help="Skip OPM orientation lookup.")
@click.option("--center-z", type=float, default=None, help="Manual membrane center Z in nm.")
def membrane(
    input_cif: str,
    out_dir: Optional[str],
    pdb_id: Optional[str],
    lipid: str,
    engine: str,
    ff: str,
    water: str,
    ph: float,
    padding: float,
    ion_conc: float,
    skip_opm: bool,
    center_z: Optional[float],
) -> None:
    """Embed a protein in a lipid membrane for MD simulation.

    Automatically fetches orientation from the OPM database (if available),
    builds a lipid bilayer, solvates, and ionizes the system.

    \b
    Examples:
      patchr membrane prediction.cif --pdb-id 4ZLO
      patchr membrane prediction.cif --lipid POPE --engine amber
      patchr membrane prediction.cif --pdb-id 1BNA --ff charmm36m --ion-conc 0.15
    """
    from boltz.membrane import MembraneConfig, build_membrane_system

    if out_dir is None:
        stem = Path(input_cif).stem
        out_dir = f"./membrane_{stem}"

    config = MembraneConfig(
        input_cif=input_cif,
        output_dir=out_dir,
        pdb_id=pdb_id,
        lipid_type=lipid,
        engine=engine,
        forcefield=ff,
        water_model=water,
        ph=ph,
        padding=padding,
        ion_concentration=ion_conc,
        skip_opm=skip_opm,
        manual_center_z=center_z,
    )

    def progress(step, pct):
        click.echo(f"  [{pct*100:5.1f}%] {step}")

    click.echo(f"Building membrane system: {input_cif}")
    click.echo(f"  Lipid: {lipid} | Engine: {engine} | FF: {ff}")
    if pdb_id:
        click.echo(f"  OPM lookup: {pdb_id}")

    result = build_membrane_system(config, progress_callback=progress)

    click.echo(f"\nMembrane system summary:")
    click.echo(f"  Atoms: {result.n_atoms:,}")
    click.echo(f"  Lipids: {result.n_lipids}")
    click.echo(f"  Waters: {result.n_waters:,}")
    click.echo(f"  Ions: {result.n_ions}")
    click.echo(f"  Box: {result.box_size[0]:.2f} x {result.box_size[1]:.2f} x {result.box_size[2]:.2f} nm")
    if result.opm_used:
        click.echo(f"  OPM: {result.opm_pdb_id} (thickness={result.membrane_thickness:.1f}A)")
    click.echo(f"\nOutput files:")
    for key, path in result.files.items():
        click.echo(f"  {key}: {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
