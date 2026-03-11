"""Simulation-ready structure preparation pipeline.

Converts PATCHR output CIF into simulation-ready files for MD engines
(GROMACS, AMBER, OpenMM) with proper protonation, solvation, and ionization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import gemmi


# ── Force field mapping ──────────────────────────────────────────────────────

FF_MAP = {
    "charmm36m": ("charmm36.xml", "charmm36/water.xml"),
    "charmm36": ("charmm36.xml", "charmm36/water.xml"),
    "amber14sb": ("amber14-all.xml", "amber14/tip3pfb.xml"),
    "amber99sbildn": ("amber99sbildn.xml", "amber99_obc.xml"),
    "amber19sb": ("amber19-all.xml", "amber14/tip3pfb.xml"),
}

WATER_MAP = {
    "tip3p": "tip3p",
    "tip3pfb": "tip3pfb",
    "tip4pew": "tip4pew",
    "spce": "spce",
    "tip5p": "tip5p",
}


@dataclass
class SimReadyConfig:
    """Configuration for simulation-ready preparation."""

    input_cif: str
    output_dir: str
    engine: str = "gromacs"  # gromacs, amber, openmm
    forcefield: str = "charmm36m"
    water_model: str = "tip3p"
    ph: float = 7.0
    padding: float = 1.0  # nm
    ion_concentration: float = 0.15  # mol/L
    positive_ion: str = "Na+"
    negative_ion: str = "Cl-"
    keep_water: bool = False  # keep crystallographic waters


@dataclass
class SimReadyResult:
    """Result of simulation-ready preparation."""

    output_dir: str
    engine: str
    forcefield: str
    files: dict = field(default_factory=dict)
    n_atoms: int = 0
    n_residues: int = 0
    n_waters: int = 0
    n_ions: int = 0
    box_size: tuple = (0.0, 0.0, 0.0)
    total_charge: float = 0.0

    def to_dict(self) -> dict:
        return {
            "output_dir": self.output_dir,
            "engine": self.engine,
            "forcefield": self.forcefield,
            "files": self.files,
            "n_atoms": self.n_atoms,
            "n_residues": self.n_residues,
            "n_waters": self.n_waters,
            "n_ions": self.n_ions,
            "box_size": list(self.box_size),
            "total_charge": self.total_charge,
        }


def _strip_duplicate_chem_comp(cif_text: str) -> str:
    """Remove duplicate _chem_comp loop from CIF text (keep first occurrence)."""
    marker = "loop_\n_chem_comp."
    first = cif_text.find(marker)
    if first == -1:
        return cif_text
    second = cif_text.find(marker, first + len(marker))
    if second == -1:
        return cif_text
    # Find the end of the second loop: next line starting with 'loop_' or '#' or '_' that
    # is not part of the _chem_comp block, or end of file.
    end = second
    in_header = True
    for line in cif_text[second:].splitlines(keepends=True):
        if in_header:
            if line.startswith("_chem_comp.") or line.startswith("loop_"):
                end += len(line)
                continue
            in_header = False
        # Data lines: non-empty lines that don't start a new block
        if line.strip() == "" or line.startswith("loop_") or line.startswith("_") or line.startswith("#"):
            break
        end += len(line)
    return cif_text[:second] + cif_text[end:]


def _cif_to_pdb_string(cif_path: str, keep_water: bool = False) -> str:
    """Convert CIF to PDB format string via gemmi."""
    try:
        doc = gemmi.cif.read(cif_path)
    except (ValueError, RuntimeError) as e:
        if "duplicate tag" in str(e):
            cif_text = Path(cif_path).read_text()
            cif_text = _strip_duplicate_chem_comp(cif_text)
            doc = gemmi.cif.read_string(cif_text)
        else:
            raise
    st = gemmi.make_structure_from_block(doc[0])
    st.setup_entities()
    st.assign_label_seq_id()

    if not keep_water:
        for model in st:
            for chain in model:
                residues_to_remove = []
                for i, res in enumerate(chain):
                    if res.name in ("HOH", "WAT", "DOD"):
                        residues_to_remove.append(i)
                for i in reversed(residues_to_remove):
                    del chain[i]

    return st.make_pdb_string()


def prepare_sim_ready(config: SimReadyConfig, progress_callback=None) -> SimReadyResult:
    """Run the full simulation-ready pipeline.

    Parameters
    ----------
    config : SimReadyConfig
        Configuration for the preparation.
    progress_callback : callable, optional
        Called with (step_name: str, progress: float 0-1) for progress tracking.

    Returns
    -------
    SimReadyResult
        Result with file paths and system info.
    """
    from io import StringIO

    import openmm.app as app
    import openmm.unit as unit
    from pdbfixer import PDBFixer

    def _progress(step: str, pct: float):
        if progress_callback:
            progress_callback(step, pct)

    _progress("loading", 0.0)

    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Convert CIF → PDB string → PDBFixer
    pdb_string = _cif_to_pdb_string(config.input_cif, keep_water=config.keep_water)
    fixer = PDBFixer(pdbfile=StringIO(pdb_string))

    _progress("fixing_structure", 0.1)

    # Step 2: Fix structure with PDBFixer
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    if not config.keep_water:
        fixer.removeHeterogens(keepWater=False)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(config.ph)

    _progress("parameterizing", 0.3)

    # Step 3: Load force field
    if config.forcefield not in FF_MAP:
        msg = f"Unsupported force field: {config.forcefield}. Available: {list(FF_MAP.keys())}"
        raise ValueError(msg)

    ff_xmls = FF_MAP[config.forcefield]
    forcefield = app.ForceField(*ff_xmls)

    # Step 4: Create modeller and solvate
    modeller = app.Modeller(fixer.topology, fixer.positions)

    _progress("solvating", 0.4)

    modeller.addSolvent(
        forcefield,
        model=WATER_MAP.get(config.water_model, config.water_model),
        padding=config.padding * unit.nanometer,
        positiveIon=config.positive_ion,
        negativeIon=config.negative_ion,
        ionicStrength=config.ion_concentration * unit.molar,
        neutralize=True,
    )

    _progress("building_system", 0.6)

    # Step 5: Create system (for serialization / export)
    system = forcefield.createSystem(
        modeller.topology,
        nonbondedMethod=app.PME,
        nonbondedCutoff=1.0 * unit.nanometer,
        constraints=app.HBonds,
    )

    _progress("writing_output", 0.8)

    # Gather stats
    result = SimReadyResult(
        output_dir=str(out_dir),
        engine=config.engine,
        forcefield=config.forcefield,
    )

    n_waters = sum(1 for r in modeller.topology.residues() if r.name in ("HOH", "WAT", "TIP3"))
    n_ions = sum(1 for r in modeller.topology.residues() if r.name in ("NA", "CL", "Na+", "Cl-"))
    n_residues = sum(1 for _ in modeller.topology.residues())
    n_atoms = sum(1 for _ in modeller.topology.atoms())

    box = modeller.topology.getPeriodicBoxVectors()
    box_nm = tuple(box[i][i].value_in_unit(unit.nanometer) for i in range(3))

    result.n_atoms = n_atoms
    result.n_residues = n_residues
    result.n_waters = n_waters
    result.n_ions = n_ions
    result.box_size = box_nm

    # Step 7: Write output files based on engine
    if config.engine == "openmm":
        result.files = _write_openmm(modeller, system, out_dir)
    elif config.engine == "gromacs":
        result.files = _write_gromacs(modeller, system, out_dir)
    elif config.engine == "amber":
        result.files = _write_amber(modeller, system, out_dir)
    else:
        msg = f"Unsupported engine: {config.engine}. Available: gromacs, amber, openmm"
        raise ValueError(msg)

    # Always write a PDB of the solvated system
    pdb_path = out_dir / "system.pdb"
    with open(pdb_path, "w") as f:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, f)
    result.files["pdb"] = str(pdb_path)

    # Write summary JSON
    summary_path = out_dir / "sim_ready_summary.json"
    with open(summary_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    result.files["summary"] = str(summary_path)

    _progress("done", 1.0)
    return result


def _write_openmm(modeller, system, out_dir: Path) -> dict:
    """Write OpenMM-native output files."""
    import openmm
    import openmm.app as app

    files = {}

    # System XML
    system_path = out_dir / "system.xml"
    with open(system_path, "w") as f:
        f.write(openmm.XmlSerializer.serialize(system))
    files["system_xml"] = str(system_path)

    # Topology PDB (for loading back)
    topo_path = out_dir / "topology.pdb"
    with open(topo_path, "w") as f:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, f)
    files["topology_pdb"] = str(topo_path)

    # State XML (positions)
    integrator = openmm.VerletIntegrator(0.001)
    simulation = app.Simulation(modeller.topology, system, integrator)
    simulation.context.setPositions(modeller.positions)
    state = simulation.context.getState(getPositions=True, getVelocities=True)
    state_path = out_dir / "state.xml"
    with open(state_path, "w") as f:
        f.write(openmm.XmlSerializer.serialize(state))
    files["state_xml"] = str(state_path)

    return files


def _write_gromacs(modeller, system, out_dir: Path) -> dict:
    """Write GROMACS-compatible output files.

    Writes .gro (coordinates) and .pdb (for pdb2gmx topology generation).
    ParmEd cannot reliably write GROMACS .top from OpenMM CHARMM36 systems,
    so we provide the PDB for use with GROMACS pdb2gmx.
    """
    import openmm.app as app
    import parmed

    files = {}

    # Write .gro via ParmEd (coordinates only — this works fine)
    structure = parmed.openmm.load_topology(
        modeller.topology,
        xyz=modeller.positions,
    )
    gro_path = out_dir / "system.gro"
    structure.save(str(gro_path), overwrite=True)
    files["gro"] = str(gro_path)

    # Write PDB for pdb2gmx
    pdb_path = out_dir / "system_for_gmx.pdb"
    with open(pdb_path, "w") as f:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, f)
    files["pdb_for_gmx"] = str(pdb_path)

    # Write OpenMM system XML as backup (complete parameterization)
    import openmm
    system_path = out_dir / "system.xml"
    with open(system_path, "w") as f:
        f.write(openmm.XmlSerializer.serialize(system))
    files["system_xml"] = str(system_path)

    return files


def _write_amber(modeller, system, out_dir: Path) -> dict:
    """Write AMBER-compatible output files.

    Writes PDB + OpenMM system XML. Users can convert to native AMBER
    format using ParmEd or ambertools (parmed -i convert.in).
    """
    import openmm
    import openmm.app as app

    files = {}

    # Write PDB
    pdb_path = out_dir / "system_for_amber.pdb"
    with open(pdb_path, "w") as f:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, f)
    files["pdb_for_amber"] = str(pdb_path)

    # Write OpenMM system XML (complete parameterization)
    system_path = out_dir / "system.xml"
    with open(system_path, "w") as f:
        f.write(openmm.XmlSerializer.serialize(system))
    files["system_xml"] = str(system_path)

    return files
