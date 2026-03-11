"""Membrane protein embedding pipeline.

Orients proteins using OPM data and builds lipid bilayer systems
ready for MD simulation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Optional

import numpy as np
import requests

from boltz.sim_ready import FF_MAP, WATER_MAP, SimReadyResult


# ── OPM integration ─────────────────────────────────────────────────────────

OPM_API_URL = "https://opm-api.phar.umich.edu/pdb"

SUPPORTED_LIPIDS = ["POPC", "POPE", "DLPC", "DLPE", "DMPC", "DOPC", "DPPC"]


@dataclass
class OPMData:
    """Orientation data from the OPM database."""

    pdb_id: str
    thickness: float  # membrane thickness in Angstroms
    tilt_angle: float  # tilt angle in degrees
    membrane_center_z: float  # Z coordinate of membrane center
    subunit: str = ""
    family: str = ""
    superfamily: str = ""
    type_name: str = ""  # e.g. "Transmembrane", "Peripheral"
    topology: str = ""
    coordinates_pdb: Optional[str] = None  # OPM-oriented PDB text


@dataclass
class MembraneConfig:
    """Configuration for membrane embedding."""

    input_cif: str
    output_dir: str
    pdb_id: Optional[str] = None  # for OPM lookup
    lipid_type: str = "POPC"
    forcefield: str = "charmm36m"
    water_model: str = "tip3p"
    padding: float = 1.0  # nm, minimum padding around protein
    ion_concentration: float = 0.15  # mol/L
    positive_ion: str = "Na+"
    negative_ion: str = "Cl-"
    ph: float = 7.0
    engine: str = "gromacs"  # output format
    # Manual orientation (if no OPM data)
    manual_center_z: Optional[float] = None  # nm
    skip_opm: bool = False


@dataclass
class MembraneResult:
    """Result of membrane embedding."""

    output_dir: str
    lipid_type: str
    forcefield: str
    engine: str
    files: dict = field(default_factory=dict)
    n_atoms: int = 0
    n_lipids: int = 0
    n_waters: int = 0
    n_ions: int = 0
    box_size: tuple = (0.0, 0.0, 0.0)
    membrane_thickness: float = 0.0
    opm_used: bool = False
    opm_pdb_id: str = ""

    def to_dict(self) -> dict:
        return {
            "output_dir": self.output_dir,
            "lipid_type": self.lipid_type,
            "forcefield": self.forcefield,
            "engine": self.engine,
            "files": self.files,
            "n_atoms": self.n_atoms,
            "n_lipids": self.n_lipids,
            "n_waters": self.n_waters,
            "n_ions": self.n_ions,
            "box_size": list(self.box_size),
            "membrane_thickness": self.membrane_thickness,
            "opm_used": self.opm_used,
            "opm_pdb_id": self.opm_pdb_id,
        }


def fetch_opm_data(pdb_id: str) -> Optional[OPMData]:
    """Fetch orientation data from the OPM database.

    Parameters
    ----------
    pdb_id : str
        4-letter PDB ID.

    Returns
    -------
    OPMData or None
        Orientation data if available.
    """
    pdb_id = pdb_id.upper().strip()

    # Try the OPM API
    try:
        resp = requests.get(f"{OPM_API_URL}/{pdb_id.lower()}", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            opm = OPMData(
                pdb_id=pdb_id,
                thickness=float(data.get("thickness", 0)),
                tilt_angle=float(data.get("tilt", 0)),
                membrane_center_z=0.0,
                subunit=data.get("subunit", ""),
                family=data.get("family", ""),
                superfamily=data.get("superfamily", ""),
                type_name=data.get("type", ""),
                topology=data.get("topology", ""),
            )
            return opm
    except (requests.RequestException, json.JSONDecodeError, KeyError):
        pass

    # Try fetching the OPM-oriented PDB
    try:
        pdb_url = f"https://opm-assets.storage.googleapis.com/pdb/{pdb_id.lower()}.pdb"
        resp = requests.get(pdb_url, timeout=30)
        if resp.status_code == 200:
            pdb_text = resp.text
            # Parse thickness from REMARK lines
            thickness = 0.0
            for line in pdb_text.split("\n"):
                if "thickness" in line.lower():
                    match = re.search(r"(\d+\.?\d*)", line)
                    if match:
                        thickness = float(match.group(1))
                        break

            return OPMData(
                pdb_id=pdb_id,
                thickness=thickness,
                tilt_angle=0.0,
                membrane_center_z=0.0,
                coordinates_pdb=pdb_text,
            )
    except requests.RequestException:
        pass

    return None


def _extract_pdb_id_from_cif(cif_path: str) -> Optional[str]:
    """Try to extract PDB ID from a CIF file."""
    import gemmi

    try:
        doc = gemmi.cif.read(cif_path)
        block = doc[0]
        # Try _entry.id
        entry_id = block.find_value("_entry.id")
        if entry_id and len(entry_id) == 4:
            return entry_id.upper()
        # Try block name
        name = block.name.upper()
        if len(name) == 4 and name.isalnum():
            return name
    except Exception:
        pass
    return None


def _orient_with_opm(pdb_string: str, opm_data: OPMData) -> str:
    """Apply OPM orientation to a PDB structure.

    If OPM provides pre-oriented coordinates, use those.
    Otherwise, center the protein at Z=0 (membrane center).
    """
    if opm_data.coordinates_pdb:
        return opm_data.coordinates_pdb
    # If no OPM coordinates, just return the input
    # (user may need to orient manually)
    return pdb_string


def build_membrane_system(config: MembraneConfig, progress_callback=None) -> MembraneResult:
    """Build a membrane-embedded protein system.

    Parameters
    ----------
    config : MembraneConfig
        Configuration for membrane building.
    progress_callback : callable, optional
        Called with (step_name: str, progress: float 0-1).

    Returns
    -------
    MembraneResult
        Result with file paths and system info.
    """
    import openmm.app as app
    import openmm.unit as unit
    from pdbfixer import PDBFixer

    from boltz.sim_ready import _cif_to_pdb_string, _write_amber, _write_gromacs, _write_openmm

    def _progress(step: str, pct: float):
        if progress_callback:
            progress_callback(step, pct)

    _progress("loading", 0.0)

    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = MembraneResult(
        output_dir=str(out_dir),
        lipid_type=config.lipid_type,
        forcefield=config.forcefield,
        engine=config.engine,
    )

    # Step 1: Get OPM orientation
    opm_data = None
    pdb_id = config.pdb_id

    if not pdb_id:
        pdb_id = _extract_pdb_id_from_cif(config.input_cif)

    if pdb_id and not config.skip_opm:
        _progress("fetching_opm", 0.05)
        opm_data = fetch_opm_data(pdb_id)
        if opm_data:
            result.opm_used = True
            result.opm_pdb_id = pdb_id
            result.membrane_thickness = opm_data.thickness
            print(f"OPM data found for {pdb_id}: thickness={opm_data.thickness:.1f}A, type={opm_data.type_name}")

    # Step 2: Convert CIF to PDB and optionally apply OPM orientation
    _progress("converting", 0.1)
    pdb_string = _cif_to_pdb_string(config.input_cif, keep_water=False)

    if opm_data and opm_data.coordinates_pdb:
        # Use OPM-oriented coordinates
        pdb_string = opm_data.coordinates_pdb
        print("Using OPM-oriented coordinates")

    # Step 3: Fix structure
    _progress("fixing_structure", 0.15)
    fixer = PDBFixer(pdbfile=StringIO(pdb_string))
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(config.ph)
    fixer.removeHeterogens(keepWater=False)

    # Step 4: Load force field
    _progress("parameterizing", 0.25)

    if config.forcefield not in FF_MAP:
        msg = f"Unsupported force field: {config.forcefield}. Available: {list(FF_MAP.keys())}"
        raise ValueError(msg)

    # Membrane building requires CHARMM36 lipid parameters
    charmm_ffs = ("charmm36m", "charmm36")
    if config.forcefield not in charmm_ffs:
        print(f"Warning: Membrane building uses CHARMM36 lipid parameters. "
              f"Switching from {config.forcefield} to charmm36m for membrane construction.")
        config.forcefield = "charmm36m"

    ff_xmls = FF_MAP[config.forcefield]
    forcefield = app.ForceField(*ff_xmls)

    # Step 5: Build membrane + solvate
    _progress("building_membrane", 0.3)
    modeller = app.Modeller(fixer.topology, fixer.positions)

    membrane_center = 0.0 * unit.nanometer
    if config.manual_center_z is not None:
        membrane_center = config.manual_center_z * unit.nanometer

    if config.lipid_type.upper() not in SUPPORTED_LIPIDS:
        msg = f"Unsupported lipid: {config.lipid_type}. Available: {SUPPORTED_LIPIDS}"
        raise ValueError(msg)

    print(f"Building {config.lipid_type} membrane (this may take a few minutes)...")
    modeller.addMembrane(
        forcefield,
        lipidType=config.lipid_type.upper(),
        membraneCenterZ=membrane_center,
        minimumPadding=config.padding * unit.nanometer,
        positiveIon=config.positive_ion,
        negativeIon=config.negative_ion,
        ionicStrength=config.ion_concentration * unit.molar,
        neutralize=True,
    )

    _progress("building_system", 0.7)

    # Step 6: Create system (for serialization / export)
    system = forcefield.createSystem(
        modeller.topology,
        nonbondedMethod=app.PME,
        nonbondedCutoff=1.0 * unit.nanometer,
        constraints=app.HBonds,
    )

    _progress("writing_output", 0.8)

    # Gather stats
    lipid_residue_names = {"POPC", "POPE", "DLPC", "DLPE", "DMPC", "DOPC", "DPPC"}
    n_lipids = sum(1 for r in modeller.topology.residues() if r.name in lipid_residue_names)
    n_waters = sum(1 for r in modeller.topology.residues() if r.name in ("HOH", "WAT", "TIP3"))
    n_ions = sum(1 for r in modeller.topology.residues() if r.name in ("NA", "CL", "Na+", "Cl-"))
    n_atoms = sum(1 for _ in modeller.topology.atoms())

    box = modeller.topology.getPeriodicBoxVectors()
    box_nm = tuple(box[i][i].value_in_unit(unit.nanometer) for i in range(3))

    result.n_atoms = n_atoms
    result.n_lipids = n_lipids
    result.n_waters = n_waters
    result.n_ions = n_ions
    result.box_size = box_nm

    # Step 8: Write output files
    if config.engine == "openmm":
        result.files = _write_openmm(modeller, system, out_dir)
    elif config.engine == "gromacs":
        result.files = _write_gromacs(modeller, system, out_dir)
    elif config.engine == "amber":
        result.files = _write_amber(modeller, system, out_dir)

    # Always write PDB
    pdb_path = out_dir / "membrane_system.pdb"
    with open(pdb_path, "w") as f:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, f)
    result.files["pdb"] = str(pdb_path)

    # Save OPM info if available
    if opm_data:
        opm_path = out_dir / "opm_info.json"
        with open(opm_path, "w") as f:
            json.dump({
                "pdb_id": opm_data.pdb_id,
                "thickness": opm_data.thickness,
                "tilt_angle": opm_data.tilt_angle,
                "type": opm_data.type_name,
                "topology": opm_data.topology,
            }, f, indent=2)
        result.files["opm_info"] = str(opm_path)

    # Write summary
    summary_path = out_dir / "membrane_summary.json"
    with open(summary_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    result.files["summary"] = str(summary_path)

    _progress("done", 1.0)
    return result
