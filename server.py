"""
Unified FastAPI server for Boltz + Protenix.

This server provides REST API endpoints for:
1. Generating inpainting templates from PDB structures
2. Running Boltz or Protenix predictions
3. Monitoring job status and retrieving results
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
import warnings
import zipfile
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import torch
import uvicorn
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import Callback
from rdkit import Chem

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Import Boltz modules
from boltz.data.module.inferencev2 import Boltz2InferenceDataModule
from boltz.data.types import Manifest
from boltz.data.write.writer import BoltzWriter
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

logger = logging.getLogger(__name__)

# Constants
WORK_DIR = Path(os.environ.get("PATCHR_WORK_DIR", "./patchr_jobs"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Global server configuration
DEFAULT_DEVICE_ID = os.environ.get("PATCHR_DEVICE_ID") or os.environ.get("BOLTZ_DEVICE_ID")


# ── Model types ──────────────────────────────────────────────────────────────

class ModelType(str, Enum):
    BOLTZ2 = "boltz2"
    # Note: boltz2 always runs with inpainting enabled in PATCHR
    PROTENIX = "protenix"


# Model registry: model_type -> model object
_model_registry: Dict[str, Any] = {}
_model_params: Dict[str, Dict[str, Any]] = {}

# Protenix inference lock (not thread-safe by design)
_protenix_lock = threading.Lock()


# ── Job status ───────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING = "pending"
    GENERATING_TEMPLATE = "generating_template"
    RUNNING_PREDICTION = "running_prediction"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Pydantic models ─────────────────────────────────────────────────────────

class TemplateGenerateRequest(BaseModel):
    pdb_id: str = Field(..., description="PDB ID (e.g., 7EOQ)")
    chain_ids: str = Field(..., description="Chain IDs (e.g., 'A' or 'A,B' for multimeric)")
    uniprot: bool = Field(False, description="Use UniProt sequence instead of SEQRES")
    custom_sequences: Optional[Dict[str, str]] = Field(
        None,
        description="Custom sequences for chains (e.g., {'A': 'ACDEFG...', 'B': 'MNOPQR...'})",
    )


class PredictionRequest(BaseModel):
    job_id: str = Field(..., description="Job ID from template generation")
    model: ModelType = Field(
        ModelType.BOLTZ2,
        description="Model to use for prediction",
    )
    recycling_steps: int = Field(3, description="Number of recycling steps (Boltz: recycling_steps, Protenix: model.N_cycle)")
    sampling_steps: int = Field(200, description="Number of sampling steps (Boltz: sampling_steps, Protenix: sample_diffusion.N_step)")
    diffusion_samples: int = Field(1, description="Number of diffusion samples (Boltz: diffusion_samples, Protenix: sample_diffusion.N_sample)")
    devices: int = Field(1, description="Number of devices to use (Boltz only)")
    accelerator: str = Field("gpu", description="Accelerator type (Boltz only)")
    use_msa_server: bool = Field(False, description="Use MSA server for MSA generation (Boltz only)")


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    pdb_id: Optional[str] = None
    chain_ids: Optional[str] = None
    template_files: Optional[Dict[str, str]] = None
    prediction_dir: Optional[str] = None
    error: Optional[str] = None
    progress: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: List[JobStatusResponse]
    total: int


# Job storage
jobs_db: Dict[str, Dict] = {}
progress_streams: Dict[str, asyncio.Queue] = {}


# ── Progress tracker (Boltz) ────────────────────────────────────────────────

class ProgressTracker(Callback):
    """Custom callback to track prediction progress."""

    def __init__(self, job_id: str, event_loop=None):
        super().__init__()
        self.job_id = job_id
        self.total_batches = 0
        self.current_batch = 0
        self.event_loop = event_loop
        self.base_progress = 0
        self.diffusion_progress = 0

    def on_predict_start(self, trainer, pl_module):
        self._emit_progress("Prediction started", 0)

    def on_predict_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx=0):
        self.current_batch = batch_idx
        if hasattr(trainer, "num_predict_batches"):
            self.total_batches = trainer.num_predict_batches[0]
        self.base_progress = 0
        self.diffusion_progress = 0
        progress = 0
        if self.total_batches > 0:
            progress = int((self.current_batch / self.total_batches) * 100)
        self._emit_progress(
            f"Processing batch {self.current_batch + 1}/{self.total_batches or '?'}",
            progress,
        )

    def on_predict_batch_end(self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx=0):
        self.current_batch = batch_idx + 1
        if hasattr(trainer, "num_predict_batches"):
            self.total_batches = trainer.num_predict_batches[0]
        progress = 100
        if self.total_batches > 0:
            progress = int((self.current_batch / self.total_batches) * 100)
        self._emit_progress(
            f"Completed batch {self.current_batch}/{self.total_batches or '?'}",
            progress,
        )

    def on_predict_end(self, trainer, pl_module):
        self._emit_progress("Prediction completed", 100)

    def update_base_progress(self, message: str, percentage: int):
        self.base_progress = min(percentage, 40)
        total_progress = self.base_progress + self.diffusion_progress
        self._emit_progress(message, total_progress)

    def update_diffusion_progress(self, message: str, step: int, total_steps: int):
        if total_steps > 0:
            diffusion_percentage = int((step / total_steps) * 60)
            self.diffusion_progress = diffusion_percentage
            total_progress = self.base_progress + self.diffusion_progress
            self._emit_progress(message, total_progress)

    def _emit_progress(self, message: str, percentage: int):
        update_job_status(
            self.job_id,
            JobStatus.RUNNING_PREDICTION,
            progress=f"{message} ({percentage}%)",
        )
        if self.job_id in progress_streams and self.event_loop:
            try:
                queue = progress_streams[self.job_id]
                if self.event_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._put_progress(queue, message, percentage),
                        self.event_loop,
                    )
            except Exception:
                pass

    async def _put_progress(self, queue: asyncio.Queue, message: str, percentage: int):
        try:
            await queue.put(
                {
                    "message": message,
                    "percentage": percentage,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception:
            pass


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Patchr API",
    description="Unified REST API for Boltz and Protenix protein structure prediction",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Model preloading ────────────────────────────────────────────────────────

def _preload_boltz_model(device_id: Optional[str] = None, enable_inpainting: bool = True):
    """Preload Boltz2 model on GPU at server startup."""
    model_key = "boltz2"
    try:
        print(f"Preloading Boltz2 model (inpainting={enable_inpainting}) on GPU... (device_id={device_id})")

        warnings.filterwarnings("ignore", ".*that has Tensor Cores. To properly utilize them.*")
        torch.set_grad_enabled(False)
        torch.set_float32_matmul_precision("highest")
        Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)

        cache = Path(get_cache_path()).expanduser()
        cache.mkdir(parents=True, exist_ok=True)

        print("Downloading/verifying Boltz model checkpoint...")
        download_boltz2(cache)

        checkpoint = cache / "boltz2_conf.ckpt"
        if not checkpoint.exists():
            print("Warning: Model checkpoint not found, skipping Boltz preload")
            return

        if device_id:
            try:
                map_location = f"cuda:{int(device_id)}"
            except ValueError:
                map_location = device_id
        else:
            map_location = "cuda:0" if torch.cuda.is_available() else "cpu"

        default_predict_args = {
            "recycling_steps": 3,
            "sampling_steps": 200,
            "diffusion_samples": 1,
            "max_parallel_samples": 1,
            "write_confidence_summary": True,
            "write_full_pae": False,
            "write_full_pde": False,
        }

        diffusion_params = Boltz2DiffusionParams()
        diffusion_params.step_scale = 1.5
        pairformer_args = PairformerArgsV2()
        msa_args = MSAModuleArgs(
            subsample_msa=True,
            num_subsampled_msa=1024,
            use_paired_feature=True,
        )

        steering_args = BoltzSteeringParams()
        steering_args.fk_steering = False
        steering_args.physical_guidance_update = False
        steering_args.contact_guidance_update = False
        steering_args.inpainting = enable_inpainting

        print(f"Loading Boltz checkpoint to {map_location}...")
        model_module = Boltz2.load_from_checkpoint(
            str(checkpoint),
            strict=True,
            predict_args=default_predict_args,
            map_location=map_location,
            diffusion_process_args=asdict(diffusion_params),
            ema=False,
            use_kernels=True,
            pairformer_args=asdict(pairformer_args),
            msa_args=asdict(msa_args),
            steering_args=asdict(steering_args),
            enable_inpainting=enable_inpainting,
        )
        model_module.eval()

        _model_registry[model_key] = model_module
        _model_params[model_key] = {
            "recycling_steps": 3,
            "sampling_steps": 200,
            "diffusion_samples": 1,
            "map_location": map_location,
        }

        print(f"Boltz2 ({model_key}) preloaded successfully on {map_location}")

    except Exception as e:
        print(f"Warning: Failed to preload Boltz model: {e}")
        import traceback
        traceback.print_exc()


def _preload_protenix_model(device_id: Optional[str] = None):
    """Preload Protenix model on GPU at server startup."""
    try:
        print(f"Preloading Protenix model... (device_id={device_id})")

        from protenix_configs.configs_base import configs as configs_base
        from protenix_configs.configs_data import data_configs
        from protenix_configs.configs_inference import inference_configs
        from protenix_configs.configs_model_type import model_configs
        from ml_collections.config_dict import ConfigDict
        from protenix.config.config import parse_configs

        from protenix_runner.inference import (
            InferenceRunner,
            download_inference_cache,
            update_gpu_compatible_configs,
        )

        model_name = "protenix_base_default_v1.0.0"
        inference_configs["model_name"] = model_name
        configs = {**configs_base, **{"data": data_configs}, **inference_configs}
        configs = parse_configs(configs=configs, fill_required_with_null=True)

        model_name_parts = model_name.split("_", 3)
        if len(model_name_parts) == 4:
            _, model_size, model_feature, model_version = model_name_parts
        else:
            model_size = model_feature = model_version = "unknown"

        model_specfics_configs = ConfigDict(model_configs[model_name])
        configs.update(model_specfics_configs)

        # Set defaults
        configs.model.N_cycle = 10
        configs.sample_diffusion.N_sample = 1
        configs.sample_diffusion.N_step = 200
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
        configs.seeds = [101]

        configs = update_gpu_compatible_configs(configs)

        print(
            f"Inference by Protenix: model_size: {model_size}, "
            f"with_feature: {model_feature.replace('-', ',')}, "
            f"model_version: {model_version}, dtype: {configs.dtype}"
        )

        download_inference_cache(configs)
        runner = InferenceRunner(configs)

        _model_registry["protenix"] = runner
        _model_params["protenix"] = {
            "model_name": model_name,
            "N_cycle": configs.model.N_cycle,
            "N_step": configs.sample_diffusion.N_step,
            "N_sample": configs.sample_diffusion.N_sample,
        }

        print("Protenix model preloaded successfully")

    except Exception as e:
        print(f"Warning: Failed to preload Protenix model: {e}")
        import traceback
        traceback.print_exc()


# ── Startup ──────────────────────────────────────────────────────────────────

# Which models to load at startup (set from CLI or env)
_startup_model: Optional[str] = None


@app.on_event("startup")
async def startup_event():
    """Load model(s) on server startup."""
    device_id = DEFAULT_DEVICE_ID or os.environ.get("PATCHR_DEVICE_ID") or os.environ.get("BOLTZ_DEVICE_ID")
    startup = _startup_model or os.environ.get("PATCHR_DEFAULT_MODEL", "boltz2")

    print(f"Startup: device_id={device_id}, default_model={startup}")

    if not device_id and torch.cuda.is_available():
        device_id = "0"

    loop = asyncio.get_event_loop()

    if startup == "boltz2":
        await loop.run_in_executor(None, _preload_boltz_model, device_id, True)
    elif startup == "protenix":
        await loop.run_in_executor(None, _preload_protenix_model, device_id)
    elif startup == "all":
        await loop.run_in_executor(None, _preload_boltz_model, device_id, True)
        await loop.run_in_executor(None, _preload_protenix_model, device_id)


# ── Job helpers ──────────────────────────────────────────────────────────────

def update_job_status(
    job_id: str,
    status: JobStatus,
    error: Optional[str] = None,
    **kwargs,
):
    if job_id not in jobs_db:
        return
    jobs_db[job_id]["status"] = status
    jobs_db[job_id]["updated_at"] = datetime.now().isoformat()
    if error:
        jobs_db[job_id]["error"] = error
    for key, value in kwargs.items():
        jobs_db[job_id][key] = value


# ── Template generation ─────────────────────────────────────────────────────

async def run_template_generation(
    job_id: str,
    pdb_id: str,
    chain_ids: str,
    uniprot: bool,
    custom_sequences: Optional[Dict[str, str]],
    cif_file_path: Optional[Path] = None,
):
    """Background task to generate inpainting template."""
    try:
        update_job_status(job_id, JobStatus.GENERATING_TEMPLATE, progress="Starting template generation")

        job_dir = WORK_DIR / job_id
        output_dir = job_dir / "templates"
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [sys.executable, "scripts/generate_inpainting_template.py"]

        if cif_file_path:
            cmd.extend(["--input", str(cif_file_path)])
            cmd.append(chain_ids)
        else:
            cmd.extend([pdb_id, chain_ids])

        if uniprot:
            cmd.append("--uniprot")

        if custom_sequences:
            seq_str = ",".join([f"{chain}:{seq}" for chain, seq in custom_sequences.items()])
            cmd.extend(["--sequence", seq_str])

        cmd.extend(["-o", str(output_dir)])

        update_job_status(job_id, JobStatus.GENERATING_TEMPLATE, progress="Running template generation script")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = f"Template generation failed: {stderr.decode()}"
            update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            return

        cif_files = list(output_dir.glob("*.cif"))
        yaml_files = list(output_dir.glob("*.yaml"))

        if not cif_files or not yaml_files:
            error_msg = "Template generation did not produce expected files"
            update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            return

        template_files = {
            "cif": str(cif_files[0].relative_to(WORK_DIR)),
            "yaml": str(yaml_files[0].relative_to(WORK_DIR)),
        }

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            template_files=template_files,
            progress="Template generation completed",
        )

    except Exception as e:
        error_msg = f"Template generation error: {str(e)}"
        update_job_status(job_id, JobStatus.FAILED, error=error_msg)


# ── Boltz prediction ────────────────────────────────────────────────────────

async def run_boltz_prediction(
    job_id: str,
    yaml_file: Path,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
    devices: int,
    accelerator: str,
    use_msa_server: bool,
    model_type: ModelType = ModelType.BOLTZ2,
):
    """Background task to run Boltz prediction."""
    try:
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Initializing Boltz prediction")

        job_dir = WORK_DIR / job_id
        out_dir = job_dir / "predictions"
        progress_streams[job_id] = asyncio.Queue()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            _run_boltz_prediction_sync,
            job_id,
            yaml_file,
            out_dir,
            recycling_steps,
            sampling_steps,
            diffusion_samples,
            devices,
            accelerator,
            use_msa_server,
            model_type,
            loop,
        )

        pred_base_dir = out_dir / f"patchr_results_{yaml_file.stem}"
        pred_dir = pred_base_dir / "predictions"

        if not pred_dir.exists():
            error_msg = "Prediction did not produce expected results"
            update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            return

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            prediction_dir=str(pred_dir.relative_to(WORK_DIR)),
            progress="Prediction completed successfully",
        )

    except Exception as e:
        error_msg = f"Prediction error: {str(e)}"
        update_job_status(job_id, JobStatus.FAILED, error=error_msg)
    finally:
        if job_id in progress_streams:
            await progress_streams[job_id].put(None)
            del progress_streams[job_id]


def _run_boltz_prediction_sync(
    job_id: str,
    yaml_file: Path,
    out_dir: Path,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
    devices: int,
    accelerator: str,
    use_msa_server: bool,
    model_type: ModelType = ModelType.BOLTZ2,
    event_loop=None,
):
    """Synchronous function to run Boltz prediction."""
    try:
        warnings.filterwarnings("ignore", ".*that has Tensor Cores. To properly utilize them.*")
        torch.set_grad_enabled(False)
        torch.set_float32_matmul_precision("highest")
        Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)

        cache = Path(get_cache_path()).expanduser()
        cache.mkdir(parents=True, exist_ok=True)

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Downloading model if needed")
        download_boltz2(cache)

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Validating inputs")
        data = check_inputs(yaml_file)

        results_dir = out_dir / f"patchr_results_{yaml_file.stem}"
        results_dir.mkdir(parents=True, exist_ok=True)

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Processing inputs and generating MSAs")
        ccd_path = cache / "ccd.pkl"
        mol_dir = cache / "mols"

        process_inputs(
            data=data,
            out_dir=results_dir,
            ccd_path=ccd_path,
            mol_dir=mol_dir,
            use_msa_server=use_msa_server,
            msa_server_url="https://api.colabfold.com",
            msa_pairing_strategy="greedy",
            msa_server_username=os.environ.get("BOLTZ_MSA_USERNAME"),
            msa_server_password=os.environ.get("BOLTZ_MSA_PASSWORD"),
            api_key_header=None,
            api_key_value=os.environ.get("MSA_API_KEY_VALUE"),
            boltz2=True,
            preprocessing_threads=1,
            max_msa_seqs=8192,
            override=False,
        )

        manifest = Manifest.load(results_dir / "processed" / "manifest.json")
        filtered_manifest = filter_inputs_structure(
            manifest=manifest,
            outdir=results_dir,
            override=False,
        )

        if not filtered_manifest.records:
            update_job_status(job_id, JobStatus.COMPLETED, progress="Prediction already exists")
            return

        processed_dir = results_dir / "processed"
        processed = BoltzProcessedInput(
            manifest=filtered_manifest,
            targets_dir=processed_dir / "structures",
            msa_dir=processed_dir / "msa",
            constraints_dir=(
                (processed_dir / "constraints")
                if (processed_dir / "constraints").exists()
                else None
            ),
            template_dir=(
                (processed_dir / "templates")
                if (processed_dir / "templates").exists()
                else None
            ),
            extra_mols_dir=(
                (processed_dir / "mols") if (processed_dir / "mols").exists() else None
            ),
        )

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Setting up model parameters")
        diffusion_params = Boltz2DiffusionParams()
        diffusion_params.step_scale = 1.5
        pairformer_args = PairformerArgsV2()
        msa_args = MSAModuleArgs(
            subsample_msa=True,
            num_subsampled_msa=1024,
            use_paired_feature=True,
        )

        enable_inpainting = model_type == ModelType.BOLTZ2

        pred_writer = BoltzWriter(
            data_dir=str(processed.targets_dir),
            output_dir=str(results_dir / "predictions"),
            output_format="mmcif",
            boltz2=True,
            write_embeddings=False,
        )

        progress_tracker = ProgressTracker(job_id, event_loop=event_loop)

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Setting up trainer")

        trainer_devices = devices
        if DEFAULT_DEVICE_ID:
            try:
                device_id_int = int(DEFAULT_DEVICE_ID)
                trainer_devices = [device_id_int]
            except ValueError:
                pass

        trainer = Trainer(
            default_root_dir=str(results_dir),
            strategy="auto",
            callbacks=[pred_writer, progress_tracker],
            accelerator=accelerator,
            devices=trainer_devices,
            precision="bf16-mixed",
            logger=False,
            enable_checkpointing=False,
            enable_progress_bar=False,
            enable_model_summary=False,
        )

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Creating data module")
        data_module = Boltz2InferenceDataModule(
            manifest=processed.manifest,
            target_dir=processed.targets_dir,
            msa_dir=processed.msa_dir,
            mol_dir=mol_dir,
            num_workers=0,
            constraints_dir=processed.constraints_dir,
            template_dir=processed.template_dir,
            extra_mols_dir=processed.extra_mols_dir,
            override_method=None,
        )

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Loading model checkpoint")
        checkpoint = cache / "boltz2_conf.ckpt"

        predict_args = {
            "recycling_steps": recycling_steps,
            "sampling_steps": sampling_steps,
            "diffusion_samples": diffusion_samples,
            "max_parallel_samples": diffusion_samples,
            "write_confidence_summary": True,
            "write_full_pae": False,
            "write_full_pde": False,
        }

        steering_args = BoltzSteeringParams()
        steering_args.fk_steering = False
        steering_args.physical_guidance_update = False
        steering_args.contact_guidance_update = False
        steering_args.inpainting = enable_inpainting

        # Determine map_location
        device_id_int = None
        if DEFAULT_DEVICE_ID:
            try:
                device_id_int = int(DEFAULT_DEVICE_ID)
                map_location = f"cuda:{device_id_int}"
            except ValueError:
                map_location = DEFAULT_DEVICE_ID
        elif accelerator == "gpu" and torch.cuda.is_available():
            map_location = "cuda:0"
            device_id_int = 0
        else:
            map_location = "cpu"

        # Check if we can reuse preloaded model
        model_key = "boltz2"
        preloaded = _model_registry.get(model_key)
        preloaded_params = _model_params.get(model_key)

        can_reuse = (
            preloaded is not None
            and preloaded_params is not None
            and preloaded_params.get("recycling_steps") == recycling_steps
            and preloaded_params.get("sampling_steps") == sampling_steps
            and preloaded_params.get("diffusion_samples") == diffusion_samples
            and preloaded_params.get("map_location") == map_location
        )

        if can_reuse:
            update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Reusing preloaded Boltz model")
            model_module = preloaded
            try:
                if hasattr(model_module, "predict_args"):
                    updated_args = dict(model_module.predict_args) if model_module.predict_args else {}
                    updated_args.update(predict_args)
                    model_module.predict_args = updated_args
            except Exception:
                pass
            print(f"Reusing preloaded Boltz model ({model_key}) from {map_location}")
        else:
            print(f"Loading new Boltz model ({model_key}) to {map_location}")
            model_module = Boltz2.load_from_checkpoint(
                str(checkpoint),
                strict=True,
                predict_args=predict_args,
                map_location=map_location,
                diffusion_process_args=asdict(diffusion_params),
                ema=False,
                use_kernels=True,
                pairformer_args=asdict(pairformer_args),
                msa_args=asdict(msa_args),
                steering_args=asdict(steering_args),
                enable_inpainting=enable_inpainting,
            )
            model_module.eval()

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Running prediction")
        trainer.predict(
            model_module,
            datamodule=data_module,
            return_predictions=False,
        )

        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Finalizing results")

    except Exception as e:
        error_msg = f"Prediction error: {str(e)}"
        import traceback
        traceback.print_exc()
        update_job_status(job_id, JobStatus.FAILED, error=error_msg)
        raise


# ── Protenix prediction ─────────────────────────────────────────────────────

async def run_protenix_prediction(
    job_id: str,
    yaml_file: Path,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
):
    """Background task to run Protenix prediction."""
    try:
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Initializing Protenix prediction")

        job_dir = WORK_DIR / job_id
        out_dir = job_dir / "predictions"
        out_dir.mkdir(parents=True, exist_ok=True)
        progress_streams[job_id] = asyncio.Queue()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            _run_protenix_prediction_sync,
            job_id,
            yaml_file,
            out_dir,
            recycling_steps,
            sampling_steps,
            diffusion_samples,
            loop,
        )

        # Find prediction results — Protenix dumps to {out_dir}/predictions/{name}/
        pred_dir = out_dir / "predictions"
        if not pred_dir.exists():
            error_msg = "Protenix prediction did not produce expected results"
            update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            return

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            prediction_dir=str(pred_dir.relative_to(WORK_DIR)),
            progress="Protenix prediction completed successfully",
        )

    except Exception as e:
        error_msg = f"Protenix prediction error: {str(e)}"
        update_job_status(job_id, JobStatus.FAILED, error=error_msg)
    finally:
        if job_id in progress_streams:
            await progress_streams[job_id].put(None)
            del progress_streams[job_id]


def _run_protenix_prediction_sync(
    job_id: str,
    yaml_file: Path,
    out_dir: Path,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
    event_loop=None,
):
    """Synchronous function to run Protenix prediction."""
    from protenix_runner.inference import infer_predict

    with _protenix_lock:
        try:
            runner = _model_registry.get("protenix")
            if runner is None:
                update_job_status(job_id, JobStatus.FAILED, error="Protenix model not loaded. Start server with --model protenix or --model all")
                return

            update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Configuring Protenix parameters")

            configs = runner.configs
            configs.input_path = str(yaml_file)
            configs.dump_dir = str(out_dir)
            configs.model.N_cycle = recycling_steps
            configs.sample_diffusion.N_step = sampling_steps
            configs.sample_diffusion.N_sample = diffusion_samples

            # Re-init dumper with updated dump_dir
            runner.dump_dir = str(out_dir)
            runner.error_dir = os.path.join(str(out_dir), "ERR")
            os.makedirs(runner.dump_dir, exist_ok=True)
            os.makedirs(runner.error_dir, exist_ok=True)
            runner.init_dumper(
                need_atom_confidence=configs.need_atom_confidence,
                sorted_by_ranking_score=configs.sorted_by_ranking_score,
            )

            update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Running Protenix inference")

            infer_predict(runner, configs)

            update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Finalizing Protenix results")

        except Exception as e:
            error_msg = f"Protenix prediction error: {str(e)}"
            import traceback
            traceback.print_exc()
            update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            raise


# ── API endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Patchr API",
        "version": "2.0.0",
        "description": "Unified Boltz + Protenix prediction server",
        "loaded_models": list(_model_registry.keys()),
        "endpoints": {
            "generate_template": "/api/v1/template/generate",
            "upload_structure": "/api/v1/template/upload",
            "run_prediction": "/api/v1/predict/run",
            "job_status": "/api/v1/jobs/{job_id}",
            "job_progress_stream": "/api/v1/jobs/{job_id}/progress",
            "list_jobs": "/api/v1/jobs",
            "download_file": "/api/v1/jobs/{job_id}/files/{file_type}",
            "health": "/api/v1/health",
        },
    }


@app.post("/api/v1/template/generate", response_model=JobStatusResponse)
async def generate_template(
    request: TemplateGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Generate inpainting template from PDB ID.

    Downloads a PDB structure, extracts specified chains,
    and generates template CIF and YAML files for inpainting.
    """
    print(f"[API] POST /api/v1/template/generate pdb_id={request.pdb_id} chain_ids={request.chain_ids}")

    job_id = str(uuid.uuid4())
    job_record = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "pdb_id": request.pdb_id,
        "chain_ids": request.chain_ids,
        "uniprot": request.uniprot,
    }
    jobs_db[job_id] = job_record

    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    background_tasks.add_task(
        run_template_generation,
        job_id=job_id,
        pdb_id=request.pdb_id,
        chain_ids=request.chain_ids,
        uniprot=request.uniprot,
        custom_sequences=request.custom_sequences,
    )

    return JobStatusResponse(**job_record)


@app.post("/api/v1/template/upload", response_model=JobStatusResponse)
async def upload_structure(
    background_tasks: BackgroundTasks,
    cif_file: UploadFile = File(..., description="CIF structure file"),
    chain_ids: str = Form(..., description="Chain IDs (e.g., 'A' or 'A,B')"),
    custom_sequences: Optional[str] = Form(None, description="Custom sequences in format 'A:SEQ1,B:SEQ2'"),
):
    """Upload a CIF structure file and generate inpainting template."""
    print(f"[API] POST /api/v1/template/upload filename={cif_file.filename} chain_ids={chain_ids}")

    if not cif_file.filename.endswith((".cif", ".mmcif")):
        raise HTTPException(status_code=400, detail="File must be a CIF file (.cif or .mmcif)")

    job_id = str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    cif_path = job_dir / cif_file.filename
    with open(cif_path, "wb") as f:
        content = await cif_file.read()
        f.write(content)

    custom_seq_dict = None
    if custom_sequences:
        try:
            custom_seq_dict = {}
            for pair in custom_sequences.split(","):
                if ":" in pair:
                    chain, seq = pair.split(":", 1)
                    custom_seq_dict[chain.strip()] = seq.strip()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid custom_sequences format: {str(e)}")

    pdb_id = cif_path.stem.upper()
    job_record = {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "pdb_id": pdb_id,
        "chain_ids": chain_ids,
        "uploaded_file": str(cif_path.name),
    }
    jobs_db[job_id] = job_record

    background_tasks.add_task(
        run_template_generation,
        job_id=job_id,
        pdb_id=pdb_id,
        chain_ids=chain_ids,
        uniprot=False,
        custom_sequences=custom_seq_dict,
        cif_file_path=cif_path,
    )

    return JobStatusResponse(**job_record)


@app.post("/api/v1/predict/run", response_model=JobStatusResponse)
async def run_prediction(
    request: PredictionRequest,
    background_tasks: BackgroundTasks,
):
    """
    Run prediction on generated template.

    Dispatches to Boltz or Protenix depending on request.model.
    """
    print(
        f"[API] POST /api/v1/predict/run job_id={request.job_id} "
        f"model={request.model} recycling={request.recycling_steps} "
        f"sampling={request.sampling_steps} samples={request.diffusion_samples}"
    )

    if request.job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {request.job_id} not found")

    job = jobs_db[request.job_id]

    if job["status"] != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Template generation not complete. Current status: {job['status']}",
        )

    if "template_files" not in job or "yaml" not in job["template_files"]:
        raise HTTPException(status_code=400, detail="Template YAML file not found")

    yaml_file = WORK_DIR / job["template_files"]["yaml"]
    if not yaml_file.exists():
        raise HTTPException(status_code=400, detail="Template YAML file does not exist")

    update_job_status(request.job_id, JobStatus.PENDING, progress="Preparing to run prediction")

    # Dispatch based on model type
    if request.model == ModelType.BOLTZ2:
        background_tasks.add_task(
            run_boltz_prediction,
            job_id=request.job_id,
            yaml_file=yaml_file,
            recycling_steps=request.recycling_steps,
            sampling_steps=request.sampling_steps,
            diffusion_samples=request.diffusion_samples,
            devices=request.devices,
            accelerator=request.accelerator,
            use_msa_server=request.use_msa_server,
            model_type=request.model,
        )
    elif request.model == ModelType.PROTENIX:
        background_tasks.add_task(
            run_protenix_prediction,
            job_id=request.job_id,
            yaml_file=yaml_file,
            recycling_steps=request.recycling_steps,
            sampling_steps=request.sampling_steps,
            diffusion_samples=request.diffusion_samples,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown model type: {request.model}")

    return JobStatusResponse(**jobs_db[request.job_id])


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Get the status of a job."""
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobStatusResponse(**jobs_db[job_id])


@app.get("/api/v1/jobs/{job_id}/progress")
async def stream_job_progress(job_id: str):
    """Stream real-time progress updates for a job using Server-Sent Events (SSE)."""
    import json as _json

    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    async def event_generator():
        if jobs_db[job_id]["status"] not in [JobStatus.RUNNING_PREDICTION, JobStatus.GENERATING_TEMPLATE]:
            status_data = {
                "status": jobs_db[job_id]["status"],
                "progress": jobs_db[job_id].get("progress", ""),
            }
            yield f"data: {_json.dumps(status_data)}\n\n"
            return

        if job_id not in progress_streams:
            progress_streams[job_id] = asyncio.Queue()

        queue = progress_streams[job_id]

        try:
            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if update is None:
                        break
                    yield f"data: {_json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if job_id in jobs_db:
                final_status = {
                    "status": jobs_db[job_id]["status"],
                    "progress": jobs_db[job_id].get("progress", ""),
                    "timestamp": datetime.now().isoformat(),
                }
                yield f"data: {_json.dumps(final_status)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/jobs", response_model=JobListResponse)
async def list_jobs(
    status: Optional[JobStatus] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List all jobs, optionally filtered by status."""
    jobs = list(jobs_db.values())
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    jobs.sort(key=lambda x: x["created_at"], reverse=True)
    total = len(jobs)
    jobs = jobs[offset : offset + limit]
    return JobListResponse(
        jobs=[JobStatusResponse(**j) for j in jobs],
        total=total,
    )


@app.get("/api/v1/jobs/{job_id}/files/{file_type}")
async def download_file(job_id: str, file_type: str):
    """
    Download files from a job.

    file_type: 'cif', 'yaml', or 'prediction' (zip archive).
    """
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = jobs_db[job_id]

    if file_type == "cif":
        if "template_files" not in job or "cif" not in job["template_files"]:
            raise HTTPException(status_code=404, detail="CIF file not found")
        file_path = WORK_DIR / job["template_files"]["cif"]

    elif file_type == "yaml":
        if "template_files" not in job or "yaml" not in job["template_files"]:
            raise HTTPException(status_code=404, detail="YAML file not found")
        file_path = WORK_DIR / job["template_files"]["yaml"]

    elif file_type == "prediction":
        if "prediction_dir" not in job:
            raise HTTPException(status_code=404, detail="Prediction results not found")

        pred_dir = WORK_DIR / job["prediction_dir"]
        if not pred_dir.exists():
            raise HTTPException(status_code=404, detail="Prediction directory not found")

        zip_path = WORK_DIR / job_id / f"{job_id}_predictions.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(pred_dir):
                for file in files:
                    fp = Path(root) / file
                    rel_path = fp.relative_to(pred_dir)
                    arcname = f"predictions/{rel_path}"
                    zipf.write(fp, arcname)

            if "template_files" in job and "yaml" in job["template_files"]:
                yaml_path = WORK_DIR / job["template_files"]["yaml"]
                if yaml_path.exists():
                    zipf.write(yaml_path, yaml_path.name)

            if "template_files" in job and "cif" in job["template_files"]:
                cif_path = WORK_DIR / job["template_files"]["cif"]
                if cif_path.exists():
                    zipf.write(cif_path, cif_path.name)

        file_path = zip_path
    else:
        raise HTTPException(status_code=400, detail=f"Invalid file_type: {file_type}")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )


@app.delete("/api/v1/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and all associated files."""
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job_dir = WORK_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)

    del jobs_db[job_id]
    return {"message": f"Job {job_id} deleted successfully"}


# ── Sim-Ready & Membrane endpoints ─────────────────────────────────────────

class SimReadyRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="Job ID of a completed prediction (uses its output CIF)")
    cif_path: Optional[str] = Field(None, description="Direct path to a CIF file (alternative to job_id)")
    cif_content: Optional[str] = Field(None, description="CIF file content string (uploaded from client)")
    cif_filename: Optional[str] = Field(None, description="Original filename for uploaded CIF content")
    engine: str = Field("gromacs", description="MD engine: gromacs, amber, openmm")
    forcefield: str = Field("charmm36m", description="Force field: charmm36m, amber14sb, etc.")
    water_model: str = Field("tip3p", description="Water model: tip3p, tip3pfb, spce, tip4pew")
    ph: float = Field(7.0, description="Protonation pH")
    padding: float = Field(1.0, description="Box padding in nm")
    ion_concentration: float = Field(0.15, description="Ion concentration in mol/L")
    keep_water: bool = Field(False, description="Keep crystallographic waters")


class MembraneRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="Job ID of a completed prediction")
    cif_path: Optional[str] = Field(None, description="Direct path to a CIF file")
    cif_content: Optional[str] = Field(None, description="CIF file content string (uploaded from client)")
    cif_filename: Optional[str] = Field(None, description="Original filename for uploaded CIF content")
    pdb_id: Optional[str] = Field(None, description="PDB ID for OPM orientation lookup")
    lipid_type: str = Field("POPC", description="Lipid type: POPC, POPE, DLPC, DLPE, DMPC, DOPC, DPPC")
    engine: str = Field("gromacs", description="MD engine: gromacs, amber, openmm")
    forcefield: str = Field("charmm36m", description="Force field")
    water_model: str = Field("tip3p", description="Water model")
    ph: float = Field(7.0, description="Protonation pH")
    padding: float = Field(1.0, description="Membrane padding in nm")
    ion_concentration: float = Field(0.15, description="Ion concentration in mol/L")
    skip_opm: bool = Field(False, description="Skip OPM orientation lookup")
    center_z: Optional[float] = Field(None, description="Manual membrane center Z in nm")


def _resolve_cif_from_request(
    job_id: Optional[str],
    cif_path: Optional[str],
    cif_content: Optional[str] = None,
    cif_filename: Optional[str] = None,
) -> str:
    """Resolve CIF file path from job_id, direct path, or uploaded content."""
    # Option 1: CIF content uploaded from client
    if cif_content:
        suffix = ".cif"
        if cif_filename:
            suffix = Path(cif_filename).suffix or ".cif"
        tmp_dir = WORK_DIR / "_uploaded_cifs"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = tmp_dir / f"{uuid.uuid4()}{suffix}"
        tmp_file.write_text(cif_content)
        return str(tmp_file)

    # Option 2: Direct path on the server filesystem
    if cif_path:
        p = Path(cif_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"CIF file not found: {cif_path}")
        return str(p)

    # Option 3: Job ID from a completed prediction
    if job_id:
        if job_id not in jobs_db:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        job = jobs_db[job_id]
        if job.get("status") != JobStatus.COMPLETED:
            raise HTTPException(status_code=400, detail=f"Job {job_id} is not completed (status: {job.get('status')})")

        # Find the prediction CIF
        pred_dir = job.get("prediction_dir")
        if not pred_dir or not Path(pred_dir).exists():
            raise HTTPException(status_code=404, detail="Prediction directory not found")

        cif_files = list(Path(pred_dir).rglob("*_model_0.cif"))
        if not cif_files:
            cif_files = list(Path(pred_dir).rglob("*.cif"))
        if not cif_files:
            raise HTTPException(status_code=404, detail="No CIF files found in prediction output")
        return str(cif_files[0])

    raise HTTPException(status_code=400, detail="Either job_id, cif_path, or cif_content must be provided")


def _run_sim_ready_sync(sim_job_id: str, cif_path: str, request: SimReadyRequest):
    """Background worker for sim-ready preparation."""
    try:
        from boltz.sim_ready import SimReadyConfig, prepare_sim_ready

        out_dir = WORK_DIR / sim_job_id / "sim_ready"
        config = SimReadyConfig(
            input_cif=cif_path,
            output_dir=str(out_dir),
            engine=request.engine,
            forcefield=request.forcefield,
            water_model=request.water_model,
            ph=request.ph,
            padding=request.padding,
            ion_concentration=request.ion_concentration,
            keep_water=request.keep_water,
        )

        def progress_cb(step, pct):
            update_job_status(sim_job_id, JobStatus.RUNNING_PREDICTION, progress=f"{step} ({pct*100:.0f}%)")

        result = prepare_sim_ready(config, progress_callback=progress_cb)

        jobs_db[sim_job_id]["sim_ready_result"] = result.to_dict()
        jobs_db[sim_job_id]["prediction_dir"] = str(out_dir)
        update_job_status(sim_job_id, JobStatus.COMPLETED, progress="done")

    except Exception as e:
        logging.exception(f"Sim-ready failed for job {sim_job_id}")
        update_job_status(sim_job_id, JobStatus.FAILED, error=str(e))


def _run_membrane_sync(mem_job_id: str, cif_path: str, request: MembraneRequest):
    """Background worker for membrane embedding."""
    try:
        from boltz.membrane import MembraneConfig, build_membrane_system

        out_dir = WORK_DIR / mem_job_id / "membrane"
        config = MembraneConfig(
            input_cif=cif_path,
            output_dir=str(out_dir),
            pdb_id=request.pdb_id,
            lipid_type=request.lipid_type,
            engine=request.engine,
            forcefield=request.forcefield,
            water_model=request.water_model,
            ph=request.ph,
            padding=request.padding,
            ion_concentration=request.ion_concentration,
            skip_opm=request.skip_opm,
            manual_center_z=request.center_z,
        )

        def progress_cb(step, pct):
            update_job_status(mem_job_id, JobStatus.RUNNING_PREDICTION, progress=f"{step} ({pct*100:.0f}%)")

        result = build_membrane_system(config, progress_callback=progress_cb)

        jobs_db[mem_job_id]["membrane_result"] = result.to_dict()
        jobs_db[mem_job_id]["prediction_dir"] = str(out_dir)
        update_job_status(mem_job_id, JobStatus.COMPLETED, progress="done")

    except Exception as e:
        logging.exception(f"Membrane embedding failed for job {mem_job_id}")
        update_job_status(mem_job_id, JobStatus.FAILED, error=str(e))


@app.post("/api/v1/sim-ready")
async def sim_ready_endpoint(
    request: SimReadyRequest,
    background_tasks: BackgroundTasks,
) -> JobStatusResponse:
    """Prepare simulation-ready files from a prediction or CIF file.

    Adds hydrogens, solvates, ionizes, and exports files for the chosen MD engine.
    """
    cif_path = _resolve_cif_from_request(request.job_id, request.cif_path, request.cif_content, request.cif_filename)

    sim_job_id = str(uuid.uuid4())
    jobs_db[sim_job_id] = {
        "job_id": sim_job_id,
        "status": JobStatus.PENDING,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "progress": "Preparing sim-ready pipeline",
        "source_cif": cif_path,
    }

    background_tasks.add_task(_run_sim_ready_sync, sim_job_id, cif_path, request)
    return JobStatusResponse(**{k: v for k, v in jobs_db[sim_job_id].items() if k in JobStatusResponse.model_fields})


@app.post("/api/v1/membrane")
async def membrane_endpoint(
    request: MembraneRequest,
    background_tasks: BackgroundTasks,
) -> JobStatusResponse:
    """Embed a protein in a lipid membrane for MD simulation.

    Fetches OPM orientation (if available), builds lipid bilayer, solvates, and ionizes.
    """
    cif_path = _resolve_cif_from_request(request.job_id, request.cif_path, request.cif_content, request.cif_filename)

    mem_job_id = str(uuid.uuid4())
    jobs_db[mem_job_id] = {
        "job_id": mem_job_id,
        "status": JobStatus.PENDING,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "progress": "Preparing membrane embedding",
        "source_cif": cif_path,
        "pdb_id": request.pdb_id,
    }

    background_tasks.add_task(_run_membrane_sync, mem_job_id, cif_path, request)
    return JobStatusResponse(**{k: v for k, v in jobs_db[mem_job_id].items() if k in JobStatusResponse.model_fields})


@app.get("/api/v1/jobs/{job_id}/sim-result")
async def get_sim_result(job_id: str):
    """Get simulation preparation result details."""
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = jobs_db[job_id]
    result = job.get("sim_ready_result") or job.get("membrane_result")
    if not result:
        raise HTTPException(status_code=404, detail="No simulation result found for this job")

    return result


@app.get("/api/v1/opm/{pdb_id}")
async def get_opm_info(pdb_id: str):
    """Fetch OPM (Orientations of Proteins in Membranes) data for a PDB ID."""
    from boltz.membrane import fetch_opm_data

    data = fetch_opm_data(pdb_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"No OPM data found for {pdb_id}")

    return {
        "pdb_id": data.pdb_id,
        "thickness": data.thickness,
        "tilt_angle": data.tilt_angle,
        "type": data.type_name,
        "topology": data.topology,
        "family": data.family,
        "superfamily": data.superfamily,
        "has_coordinates": data.coordinates_pdb is not None,
    }


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "loaded_models": list(_model_registry.keys()),
        "jobs_count": len(jobs_db),
        "work_dir": str(WORK_DIR),
    }


# ── CLI entrypoint ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    log_format = (
        "%(asctime)s,%(msecs)-3d %(levelname)-8s "
        "[%(filename)s:%(lineno)s %(funcName)s] %(message)s"
    )
    logging.basicConfig(
        format=log_format,
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
        filemode="w",
    )

    parser = argparse.ArgumentParser(description="Patchr Unified API Server (Boltz + Protenix)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=31212, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR, help="Working directory for jobs")
    parser.add_argument(
        "--device-id",
        type=str,
        default=None,
        help="GPU device ID (e.g., '0', '1', 'cuda:0')",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        choices=["boltz2", "protenix", "all"],
        help="Model(s) to preload at startup (default: boltz2, or PATCHR_DEFAULT_MODEL env)",
    )

    args = parser.parse_args()

    if args.work_dir != WORK_DIR:
        WORK_DIR = args.work_dir  # type: ignore
        WORK_DIR.mkdir(parents=True, exist_ok=True)

    if args.device_id is not None:
        DEFAULT_DEVICE_ID = args.device_id  # type: ignore

    if args.model is not None:
        _startup_model = args.model

    print(f"Starting Patchr API Server on {args.host}:{args.port}")
    print(f"Work directory: {WORK_DIR.absolute()}")
    print(f"Default model: {args.model or os.environ.get('PATCHR_DEFAULT_MODEL', 'boltz2')}")
    if DEFAULT_DEVICE_ID:
        print(f"Device ID: {DEFAULT_DEVICE_ID}")
    print(f"API docs: http://{args.host}:{args.port}/docs")

    if args.reload:
        if DEFAULT_DEVICE_ID:
            os.environ["PATCHR_DEVICE_ID"] = DEFAULT_DEVICE_ID
        if _startup_model:
            os.environ["PATCHR_DEFAULT_MODEL"] = _startup_model
        uvicorn.run(
            "server:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    else:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            reload=False,
        )
