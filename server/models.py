"""Pydantic request/response models and status enums for the patchr server."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ModelType(str, Enum):
    BOLTZ2 = "boltz2"
    # Note: boltz2 always runs with inpainting enabled in PATCHR
    PROTENIX = "protenix"


class JobStatus(str, Enum):
    PENDING = "pending"
    GENERATING_TEMPLATE = "generating_template"
    RUNNING_PREDICTION = "running_prediction"
    COMPLETED = "completed"
    FAILED = "failed"


class TemplateGenerateRequest(BaseModel):
    pdb_id: str = Field(..., description="PDB ID (e.g., 7EOQ)")
    chain_ids: str = Field(..., description="Chain IDs (e.g., 'A' or 'A,B' for multimeric)")
    uniprot: bool = Field(False, description="Use UniProt sequence instead of SEQRES")
    custom_sequences: Optional[Dict[str, str]] = Field(
        None,
        description="Custom sequences for chains (e.g., {'A': 'ACDEFG...', 'B': 'MNOPQR...'})",
    )
    skip_terminal: bool = Field(
        False,
        description="Skip N/C-terminal missing residues (only inpaint internal gaps)",
    )
    modifications: Optional[List[str]] = Field(
        None,
        description="PTM/modifications as 'CHAIN:SEQID:CCD' where CHAIN is the author "
                    "chain id, SEQID is the 1-based ENTITY (canonical) sequence "
                    "position (the seq_id a structure viewer shows, same numbering "
                    "boltz uses), and CCD is the modified-residue code (e.g. 'A:12:SEP'). "
                    "Protein chains only.",
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
