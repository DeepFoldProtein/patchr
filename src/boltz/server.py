"""
FastAPI server for Boltz Inpainting.

This server provides REST API endpoints for:
1. Generating inpainting templates from PDB structures
2. Running Boltz inpainting predictions
3. Monitoring job status and retrieving results
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import warnings
import zipfile
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import BasePredictionWriter, Callback
from pytorch_lightning.utilities import rank_zero_only
from rdkit import Chem

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

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

# Constants
WORK_DIR = Path("./boltz_inpainting_jobs")
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Global server configuration
# Can be set via --device-id argument or BOLTZ_DEVICE_ID environment variable
DEFAULT_DEVICE_ID = os.environ.get("BOLTZ_DEVICE_ID")

# Preloaded model (loaded at server startup)
_preloaded_model: Optional[Boltz2] = None
_preloaded_model_params: Optional[Dict[str, Any]] = None

# Job status
class JobStatus(str, Enum):
    PENDING = "pending"
    GENERATING_TEMPLATE = "generating_template"
    RUNNING_PREDICTION = "running_prediction"
    COMPLETED = "completed"
    FAILED = "failed"


# Pydantic models
class TemplateGenerateRequest(BaseModel):
    pdb_id: str = Field(..., description="PDB ID (e.g., 7EOQ)")
    chain_ids: str = Field(..., description="Chain IDs (e.g., 'A' or 'A,B' for multimeric)")
    uniprot: bool = Field(False, description="Use UniProt sequence instead of SEQRES")
    custom_sequences: Optional[Dict[str, str]] = Field(
        None, 
        description="Custom sequences for chains (e.g., {'A': 'ACDEFG...', 'B': 'MNOPQR...'})"
    )


class PredictionRequest(BaseModel):
    job_id: str = Field(..., description="Job ID from template generation")
    recycling_steps: int = Field(3, description="Number of recycling steps")
    sampling_steps: int = Field(200, description="Number of sampling steps")
    diffusion_samples: int = Field(1, description="Number of diffusion samples")
    devices: int = Field(1, description="Number of devices to use")
    accelerator: str = Field("gpu", description="Accelerator type (gpu, cpu, tpu)")
    use_msa_server: bool = Field(False, description="Use MSA server for MSA generation")


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


# Job storage (in production, use a database)
jobs_db: Dict[str, Dict] = {}

# Progress tracking storage
progress_streams: Dict[str, asyncio.Queue] = {}


class ProgressTracker(Callback):
    """Custom callback to track prediction progress."""
    
    def __init__(self, job_id: str, event_loop=None):
        super().__init__()
        self.job_id = job_id
        self.total_batches = 0
        self.current_batch = 0
        self.event_loop = event_loop
        self.base_progress = 0  # Progress before diffusion (0-40%)
        self.diffusion_progress = 0  # Progress during diffusion (0-60%)
        
    def on_predict_start(self, trainer, pl_module):
        """Called when prediction starts."""
        self._emit_progress("Prediction started", 0)
    
    def on_predict_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx=0):
        """Called before processing each batch."""
        self.current_batch = batch_idx
        if hasattr(trainer, 'num_predict_batches'):
            self.total_batches = trainer.num_predict_batches[0]
        
        # Reset progress for new batch
        self.base_progress = 0
        self.diffusion_progress = 0
        
        progress = 0
        if self.total_batches > 0:
            progress = int((self.current_batch / self.total_batches) * 100)
        
        self._emit_progress(
            f"Processing batch {self.current_batch + 1}/{self.total_batches or '?'}",
            progress
        )
    
    def on_predict_batch_end(self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx=0):
        """Called after processing each batch."""
        self.current_batch = batch_idx + 1
        if hasattr(trainer, 'num_predict_batches'):
            self.total_batches = trainer.num_predict_batches[0]
        
        progress = 100
        if self.total_batches > 0:
            progress = int((self.current_batch / self.total_batches) * 100)
        
        self._emit_progress(
            f"Completed batch {self.current_batch}/{self.total_batches or '?'}",
            progress
        )
    
    def on_predict_end(self, trainer, pl_module):
        """Called when prediction ends."""
        self._emit_progress("Prediction completed", 100)
    
    def update_base_progress(self, message: str, percentage: int):
        """Update progress for pre-diffusion phase (0-40%)."""
        self.base_progress = min(percentage, 40)
        total_progress = self.base_progress + self.diffusion_progress
        self._emit_progress(message, total_progress)
    
    def update_diffusion_progress(self, message: str, step: int, total_steps: int):
        """Update progress for diffusion phase (40-100%)."""
        if total_steps > 0:
            # Diffusion takes 60% of total progress (40-100%)
            diffusion_percentage = int((step / total_steps) * 60)
            self.diffusion_progress = diffusion_percentage
            total_progress = self.base_progress + self.diffusion_progress
            self._emit_progress(message, total_progress)
    
    def _emit_progress(self, message: str, percentage: int):
        """Emit progress update (thread-safe)."""
        # Update job status (thread-safe, can be called from any thread)
        update_job_status(
            self.job_id,
            JobStatus.RUNNING_PREDICTION,
            progress=f"{message} ({percentage}%)"
        )
        
        # Try to put in queue if it exists (schedule in main event loop)
        if self.job_id in progress_streams and self.event_loop:
            try:
                queue = progress_streams[self.job_id]
                # Schedule coroutine in the main event loop
                if self.event_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._put_progress(queue, message, percentage),
                        self.event_loop
                    )
            except Exception:
                pass  # Queue might be closed or loop might be closed
    
    async def _put_progress(self, queue: asyncio.Queue, message: str, percentage: int):
        """Put progress update in queue."""
        try:
            await queue.put({
                "message": message,
                "percentage": percentage,
                "timestamp": datetime.now().isoformat()
            })
        except Exception:
            pass  # Queue might be closed


# FastAPI app
app = FastAPI(
    title="Boltz Inpainting API",
    description="REST API for Boltz protein structure inpainting",
    version="1.0.0",
)


def _preload_model(device_id: Optional[str] = None):
    """Preload Boltz2 model on GPU at server startup."""
    global _preloaded_model, _preloaded_model_params
    
    try:
        print(f"Preloading Boltz2 model on GPU... (device_id={device_id})")
        
        # Suppress warnings
        warnings.filterwarnings(
            "ignore", ".*that has Tensor Cores. To properly utilize them.*"
        )
        
        # Set no grad
        torch.set_grad_enabled(False)
        
        # Set float32 matmul precision
        torch.set_float32_matmul_precision("highest")
        
        # Set rdkit pickle logic
        Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)
        
        # Get cache path
        cache = Path(get_cache_path()).expanduser()
        cache.mkdir(parents=True, exist_ok=True)
        
        # Download Boltz2 model if needed
        print("Downloading/verifying model checkpoint...")
        download_boltz2(cache)
        
        checkpoint = cache / "boltz2_conf.ckpt"
        if not checkpoint.exists():
            print("Warning: Model checkpoint not found, skipping preload")
            return
        
        # Determine device
        if device_id:
            try:
                device_id_int = int(device_id)
                map_location = f"cuda:{device_id_int}"
                print(f"Using device_id={device_id} -> map_location={map_location}")
            except ValueError:
                map_location = device_id  # e.g., "cuda:0"
                print(f"Using device_id={device_id} (as-is) -> map_location={map_location}")
        else:
            map_location = "cuda:0" if torch.cuda.is_available() else "cpu"
            print(f"No device_id provided, using default: {map_location}")
        
        # Default parameters (can be overridden per request)
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
        steering_args.inpainting = True
        
        print(f"Loading model checkpoint to {map_location}...")
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
            enable_inpainting=True,
        )
        model_module.eval()
        
        # Store preloaded model and params
        _preloaded_model = model_module
        _preloaded_model_params = {
            "recycling_steps": 3,
            "sampling_steps": 200,
            "diffusion_samples": 1,
            "map_location": map_location,
        }
        
        print(f"Model preloaded successfully on {map_location}")
        
    except Exception as e:
        print(f"Warning: Failed to preload model: {e}")
        print("Model will be loaded on-demand for each request")
        import traceback
        traceback.print_exc()


@app.on_event("startup")
async def startup_event():
    """Load model on server startup."""
    # Get device-id from module variable or environment variable
    device_id = DEFAULT_DEVICE_ID or os.environ.get("BOLTZ_DEVICE_ID")
    print(f"Startup event: DEFAULT_DEVICE_ID = {DEFAULT_DEVICE_ID}, device_id = {device_id}")
    
    # Preload model if device-id is set
    if device_id:
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _preload_model, device_id)
    else:
        # Try to preload on default GPU if available
        if torch.cuda.is_available():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _preload_model, "0")


def update_job_status(
    job_id: str, 
    status: JobStatus, 
    error: Optional[str] = None,
    **kwargs
):
    """Update job status in the database."""
    if job_id not in jobs_db:
        return
    
    jobs_db[job_id]["status"] = status
    jobs_db[job_id]["updated_at"] = datetime.now().isoformat()
    
    if error:
        jobs_db[job_id]["error"] = error
    
    for key, value in kwargs.items():
        jobs_db[job_id][key] = value


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
        
        # Build command
        cmd = [
            sys.executable,
            "scripts/generate_inpainting_template.py",
        ]
        
        if cif_file_path:
            cmd.extend(["--input", str(cif_file_path)])
            cmd.append(chain_ids)
        else:
            cmd.extend([pdb_id, chain_ids])
        
        if uniprot:
            cmd.append("--uniprot")
        
        if custom_sequences:
            # Format: A:SEQ1,B:SEQ2
            seq_str = ",".join([f"{chain}:{seq}" for chain, seq in custom_sequences.items()])
            cmd.extend(["--sequence", seq_str])
        
        cmd.extend(["-o", str(output_dir)])
        
        update_job_status(job_id, JobStatus.GENERATING_TEMPLATE, progress="Running template generation script")
        
        # Run the script
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
        
        # Find generated files
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
            progress="Template generation completed"
        )
        
    except Exception as e:
        error_msg = f"Template generation error: {str(e)}"
        update_job_status(job_id, JobStatus.FAILED, error=error_msg)


async def run_boltz_prediction(
    job_id: str,
    yaml_file: Path,
    recycling_steps: int,
    sampling_steps: int,
    diffusion_samples: int,
    devices: int,
    accelerator: str,
    use_msa_server: bool,
):
    """Background task to run Boltz prediction using direct model integration."""
    try:
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Initializing Boltz prediction")
        
        job_dir = WORK_DIR / job_id
        out_dir = job_dir / "predictions"
        
        # Create progress queue for this job
        progress_streams[job_id] = asyncio.Queue()
        
        # Run prediction in thread pool to avoid blocking
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
            loop,  # Pass event loop for progress tracking
        )
        
        # Find prediction results
        pred_base_dir = out_dir / f"boltz_results_{yaml_file.stem}"
        pred_dir = pred_base_dir / "predictions"
        
        if not pred_dir.exists():
            error_msg = "Prediction did not produce expected results"
            update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            return
        
        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            prediction_dir=str(pred_dir.relative_to(WORK_DIR)),
            progress="Prediction completed successfully"
        )
        
    except Exception as e:
        error_msg = f"Prediction error: {str(e)}"
        update_job_status(job_id, JobStatus.FAILED, error=error_msg)
    finally:
        # Close progress stream
        if job_id in progress_streams:
            await progress_streams[job_id].put(None)  # Signal end
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
    event_loop=None,
):
    """Synchronous function to run Boltz prediction."""
    try:
        # Suppress warnings
        warnings.filterwarnings(
            "ignore", ".*that has Tensor Cores. To properly utilize them.*"
        )
        
        # Set no grad
        torch.set_grad_enabled(False)
        
        # Set float32 matmul precision
        torch.set_float32_matmul_precision("highest")
        
        # Set rdkit pickle logic
        Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)
        
        # Get cache path
        cache = Path(get_cache_path()).expanduser()
        cache.mkdir(parents=True, exist_ok=True)
        
        # Download Boltz2 model if needed
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Downloading model if needed")
        download_boltz2(cache)
        
        # Validate inputs
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Validating inputs")
        data = check_inputs(yaml_file)
        
        # Create output directory
        results_dir = out_dir / f"boltz_results_{yaml_file.stem}"
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # Process inputs
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
        
        # Load manifest
        manifest = Manifest.load(results_dir / "processed" / "manifest.json")
        
        # Filter out existing predictions
        filtered_manifest = filter_inputs_structure(
            manifest=manifest,
            outdir=results_dir,
            override=False,
        )
        
        if not filtered_manifest.records:
            update_job_status(job_id, JobStatus.COMPLETED, progress="Prediction already exists")
            return
        
        # Load processed data
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
        
        # Set up model parameters
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Setting up model parameters")
        diffusion_params = Boltz2DiffusionParams()
        diffusion_params.step_scale = 1.5
        pairformer_args = PairformerArgsV2()
        msa_args = MSAModuleArgs(
            subsample_msa=True,
            num_subsampled_msa=1024,
            use_paired_feature=True,
        )
        
        # Create prediction writer
        pred_writer = BoltzWriter(
            data_dir=str(processed.targets_dir),
            output_dir=str(results_dir / "predictions"),
            output_format="mmcif",
            boltz2=True,
            write_embeddings=False,
        )
        
        # Create progress tracker with event loop
        progress_tracker = ProgressTracker(job_id, event_loop=event_loop)
        
        # Set up trainer with specific device
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Setting up trainer")
        
        # Determine which devices to use (convert to list if using specific device)
        trainer_devices = devices
        if DEFAULT_DEVICE_ID:
            try:
                # Convert device_id to list for Trainer
                device_id_int = int(DEFAULT_DEVICE_ID)
                trainer_devices = [device_id_int]
                print(f"Trainer will use GPU device: {trainer_devices}")
            except ValueError:
                # If not an integer, use the devices parameter as-is
                print(f"Trainer will use devices: {devices}")
        else:
            print(f"Trainer will use devices: {devices}")
        
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
        
        # Create data module
        update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Creating data module")
        data_module = Boltz2InferenceDataModule(
            manifest=processed.manifest,
            target_dir=processed.targets_dir,
            msa_dir=processed.msa_dir,
            mol_dir=mol_dir,
            num_workers=0,  # Avoid multiprocessing issues
            constraints_dir=processed.constraints_dir,
            template_dir=processed.template_dir,
            extra_mols_dir=processed.extra_mols_dir,
            override_method=None,
        )
        
        # Load model (reuse preloaded if parameters match)
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
        steering_args.inpainting = True  # Enable inpainting
        
        # Determine map_location based on device_id or accelerator
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
        print(f"\n[Model Reuse Check]")
        print(f"  Preloaded model exists: {_preloaded_model is not None}")
        print(f"  Preloaded params exists: {_preloaded_model_params is not None}")
        
        if _preloaded_model_params:
            print(f"  Preloaded params: {_preloaded_model_params}")
            print(f"  Request params: recycling={recycling_steps}, sampling={sampling_steps}, diffusion={diffusion_samples}")
            print(f"  Preloaded map_location: {_preloaded_model_params.get('map_location')}")
            print(f"  Request map_location: {map_location}")
        
        can_reuse = (
            _preloaded_model is not None
            and _preloaded_model_params is not None
            and _preloaded_model_params.get("recycling_steps") == recycling_steps
            and _preloaded_model_params.get("sampling_steps") == sampling_steps
            and _preloaded_model_params.get("diffusion_samples") == diffusion_samples
            and _preloaded_model_params.get("map_location") == map_location
        )
        
        print(f"  Can reuse: {can_reuse}")
        
        if can_reuse:
            update_job_status(job_id, JobStatus.RUNNING_PREDICTION, progress="Reusing preloaded model")
            model_module = _preloaded_model
            
            # Verify model is on the correct device
            try:
                # Check if model has parameters and verify device
                if hasattr(model_module, 'parameters'):
                    first_param = next(model_module.parameters(), None)
                    if first_param is not None:
                        model_device = str(first_param.device)
                        expected_device = f"cuda:{device_id_int}" if DEFAULT_DEVICE_ID and isinstance(device_id_int, int) else map_location
                        print(f"Preloaded model device: {model_device}, Expected: {expected_device}")
                        if model_device != expected_device:
                            print(f"WARNING: Model is on {model_device} but expected {expected_device}")
            except Exception as e:
                print(f"Could not verify model device: {e}")
            
            # Update predict_args (create a new dict to avoid modifying the original)
            # Note: Some models may not allow direct assignment, so we try to update if possible
            try:
                if hasattr(model_module, 'predict_args'):
                    # Create a copy and update
                    updated_args = dict(model_module.predict_args) if model_module.predict_args else {}
                    updated_args.update(predict_args)
                    model_module.predict_args = updated_args
            except Exception:
                # If we can't update, that's okay - the model should still work
                pass
            print(f"✓ Reusing preloaded model from {map_location}")
            print(f"  Model object ID: {id(model_module)}")
            print(f"  Preloaded model object ID: {id(_preloaded_model)}")
            print(f"  Same object: {model_module is _preloaded_model}")
        else:
            if _preloaded_model is not None:
                print(f"✗ Preloaded model exists but parameters don't match. Loading NEW model to {map_location}")
                if _preloaded_model_params:
                    print(f"  Mismatch details:")
                    print(f"    recycling_steps: {_preloaded_model_params.get('recycling_steps')} vs {recycling_steps}")
                    print(f"    sampling_steps: {_preloaded_model_params.get('sampling_steps')} vs {sampling_steps}")
                    print(f"    diffusion_samples: {_preloaded_model_params.get('diffusion_samples')} vs {diffusion_samples}")
                    print(f"    map_location: {_preloaded_model_params.get('map_location')} vs {map_location}")
            else:
                print(f"✗ No preloaded model available. Loading NEW model to {map_location}")
            
            print(f"  Loading checkpoint from: {checkpoint}")
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
                enable_inpainting=True,
            )
            model_module.eval()
        
        # Run prediction
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


@app.get("/")
async def root():
    """Root endpoint."""
    print(f"[API Request] GET /")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    return {
        "service": "Boltz Inpainting API",
        "version": "1.0.0",
        "description": "Direct Boltz integration with real-time progress streaming",
        "endpoints": {
            "generate_template": "/api/v1/template/generate",
            "upload_structure": "/api/v1/template/upload",
            "run_prediction": "/api/v1/predict/run",
            "job_status": "/api/v1/jobs/{job_id}",
            "job_progress_stream": "/api/v1/jobs/{job_id}/progress",
            "list_jobs": "/api/v1/jobs",
            "download_file": "/api/v1/jobs/{job_id}/files/{file_type}",
        }
    }


@app.post("/api/v1/template/generate", response_model=JobStatusResponse)
async def generate_template(
    request: TemplateGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Generate inpainting template from PDB ID.
    
    This endpoint downloads a PDB structure, extracts specified chains,
    and generates template CIF and YAML files for inpainting.
    """
    print(f"[API Request] POST /api/v1/template/generate")
    print(f"  Request body: pdb_id={request.pdb_id}, chain_ids={request.chain_ids}, uniprot={request.uniprot}, custom_sequences={request.custom_sequences}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    job_id = str(uuid.uuid4())
    
    # Create job record
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
    
    # Create job directory
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Start background task
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
    """
    Upload a CIF structure file and generate inpainting template.
    
    This endpoint allows uploading a custom structure file instead of
    downloading from PDB.
    """
    print(f"[API Request] POST /api/v1/template/upload")
    print(f"  Request params: filename={cif_file.filename}, chain_ids={chain_ids}, custom_sequences={custom_sequences}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    # Validate file type
    if not cif_file.filename.endswith(('.cif', '.mmcif')):
        raise HTTPException(status_code=400, detail="File must be a CIF file (.cif or .mmcif)")
    
    job_id = str(uuid.uuid4())
    
    # Create job directory
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Save uploaded file
    cif_path = job_dir / cif_file.filename
    with open(cif_path, "wb") as f:
        content = await cif_file.read()
        f.write(content)
    
    # Parse custom sequences if provided
    custom_seq_dict = None
    if custom_sequences:
        try:
            custom_seq_dict = {}
            for pair in custom_sequences.split(','):
                if ':' in pair:
                    chain, seq = pair.split(':', 1)
                    custom_seq_dict[chain.strip()] = seq.strip()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid custom_sequences format: {str(e)}")
    
    # Create job record
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
    
    # Start background task
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
    Run Boltz inpainting prediction on generated template.
    
    This endpoint requires a job_id from a completed template generation.
    It will run the Boltz model with inpainting enabled.
    """
    print(f"[API Request] POST /api/v1/predict/run")
    print(f"  Request body: job_id={request.job_id}, recycling_steps={request.recycling_steps}, sampling_steps={request.sampling_steps}, diffusion_samples={request.diffusion_samples}, devices={request.devices}, accelerator={request.accelerator}, use_msa_server={request.use_msa_server}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    # Check if job exists
    if request.job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {request.job_id} not found")
    
    job = jobs_db[request.job_id]
    
    # Check if template generation is complete
    if job["status"] != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Template generation not complete. Current status: {job['status']}"
        )
    
    # Check if template files exist
    if "template_files" not in job or "yaml" not in job["template_files"]:
        raise HTTPException(status_code=400, detail="Template YAML file not found")
    
    yaml_file = WORK_DIR / job["template_files"]["yaml"]
    if not yaml_file.exists():
        raise HTTPException(status_code=400, detail="Template YAML file does not exist")
    
    # Update job status
    update_job_status(request.job_id, JobStatus.PENDING, progress="Preparing to run prediction")
    
    # Start background task
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
    )
    
    return JobStatusResponse(**jobs_db[request.job_id])


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get the status of a job.
    
    Returns current status, progress information, and available results.
    """
    print(f"[API Request] GET /api/v1/jobs/{job_id}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return JobStatusResponse(**jobs_db[job_id])


@app.get("/api/v1/jobs/{job_id}/progress")
async def stream_job_progress(job_id: str):
    """
    Stream real-time progress updates for a job using Server-Sent Events (SSE).
    
    This endpoint provides a continuous stream of progress updates while
    the prediction is running.
    
    Example client usage (JavaScript):
    ```javascript
    const eventSource = new EventSource('/api/v1/jobs/{job_id}/progress');
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log(`Progress: ${data.percentage}% - ${data.message}`);
    };
    ```
    """
    import json
    
    print(f"[API Request] GET /api/v1/jobs/{job_id}/progress")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    async def event_generator():
        """Generate SSE events."""
        # If job is not running, send current status and close
        if jobs_db[job_id]["status"] not in [JobStatus.RUNNING_PREDICTION, JobStatus.GENERATING_TEMPLATE]:
            status_data = {
                "status": jobs_db[job_id]["status"],
                "progress": jobs_db[job_id].get("progress", "")
            }
            yield f"data: {json.dumps(status_data)}\n\n"
            return
        
        # Create queue if doesn't exist
        if job_id not in progress_streams:
            progress_streams[job_id] = asyncio.Queue()
        
        queue = progress_streams[job_id]
        
        try:
            while True:
                # Wait for progress update with timeout
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=30.0)
                    
                    # None signals end of stream
                    if update is None:
                        break
                    
                    # Send update as SSE
                    yield f"data: {json.dumps(update)}\n\n"
                    
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
                    
        except asyncio.CancelledError:
            # Client disconnected
            pass
        finally:
            # Send final status
            if job_id in jobs_db:
                final_status = {
                    "status": jobs_db[job_id]["status"],
                    "progress": jobs_db[job_id].get("progress", ""),
                    "timestamp": datetime.now().isoformat()
                }
                yield f"data: {json.dumps(final_status)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/v1/jobs", response_model=JobListResponse)
async def list_jobs(
    status: Optional[JobStatus] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    List all jobs, optionally filtered by status.
    """
    print(f"[API Request] GET /api/v1/jobs")
    print(f"  Query params: status={status}, limit={limit}, offset={offset}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    jobs = list(jobs_db.values())
    
    # Filter by status if provided
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    
    # Sort by created_at (most recent first)
    jobs.sort(key=lambda x: x["created_at"], reverse=True)
    
    # Paginate
    total = len(jobs)
    jobs = jobs[offset:offset + limit]
    
    return JobListResponse(
        jobs=[JobStatusResponse(**j) for j in jobs],
        total=total,
    )


@app.get("/api/v1/jobs/{job_id}/files/{file_type}")
async def download_file(job_id: str, file_type: str):
    """
    Download files from a job.
    
    file_type can be:
    - 'cif': Template CIF file
    - 'yaml': Template YAML file
    - 'prediction': Prediction results (zip archive containing predictions/, template YAML, and template CIF)
    """
    print(f"[API Request] GET /api/v1/jobs/{job_id}/files/{file_type}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
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
        
        # Create zip archive including prediction results, yaml, and template (cif)
        zip_path = WORK_DIR / job_id / f"{job_id}_predictions.zip"
        
        # Create zip file with all relevant files
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add prediction directory contents under 'predictions/' prefix
            for root, dirs, files in os.walk(pred_dir):
                for file in files:
                    file_path = Path(root) / file
                    # Create relative path from pred_dir and prefix with 'predictions/'
                    rel_path = file_path.relative_to(pred_dir)
                    arcname = f"predictions/{rel_path}"
                    zipf.write(file_path, arcname)
            
            # Add yaml template file if available
            if "template_files" in job and "yaml" in job["template_files"]:
                yaml_path = WORK_DIR / job["template_files"]["yaml"]
                if yaml_path.exists():
                    zipf.write(yaml_path, yaml_path.name)
            
            # Add cif template file if available
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
    """
    Delete a job and all associated files.
    """
    print(f"[API Request] DELETE /api/v1/jobs/{job_id}")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    # Delete job directory
    job_dir = WORK_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    
    # Remove from database
    del jobs_db[job_id]
    
    return {"message": f"Job {job_id} deleted successfully"}


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    print(f"[API Request] GET /api/v1/health")
    print(f"  Timestamp: {datetime.now().isoformat()}")
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "jobs_count": len(jobs_db),
        "work_dir": str(WORK_DIR),
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Boltz Inpainting API Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=31212, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR, help="Working directory for jobs")
    parser.add_argument("--device-id", type=str, default=None, help="Default device ID (e.g., '0', '1', 'cuda:0')")
    
    args = parser.parse_args()
    
    # Update work directory if specified (module-level, no global needed)
    if args.work_dir != WORK_DIR:
        WORK_DIR = args.work_dir  # type: ignore
        WORK_DIR.mkdir(parents=True, exist_ok=True)
    
    # Set default device ID if provided (module-level, no global needed)
    if args.device_id is not None:
        DEFAULT_DEVICE_ID = args.device_id  # type: ignore
    
    print(f"Starting Boltz Inpainting API Server on {args.host}:{args.port}")
    print(f"Work directory: {WORK_DIR.absolute()}")
    if DEFAULT_DEVICE_ID:
        print(f"Default device ID: {DEFAULT_DEVICE_ID}")
    print(f"API documentation: http://{args.host}:{args.port}/docs")
    
    # Use app object directly to preserve module state (DEFAULT_DEVICE_ID)
    # Note: reload mode requires string, but we'll set it via environment variable
    if args.reload:
        # In reload mode, we need to use string, but device-id will be lost
        # So we set it as environment variable
        if DEFAULT_DEVICE_ID:
            os.environ["BOLTZ_DEVICE_ID"] = DEFAULT_DEVICE_ID
        uvicorn.run(
            "boltz.server:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    else:
        # In non-reload mode, use app object directly to preserve state
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            reload=False,
        )

