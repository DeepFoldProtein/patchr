"""Simulation-ready structure preparation pipeline.

Converts PATCHR output CIF into simulation-ready files for MD engines
(GROMACS, AMBER, OpenMM) with proper protonation, solvation, and ionization.

GROMACS output follows the CHARMM-GUI Membrane Builder directory conventions:
  - toppar/ directory with forcefield.itp and per-molecule .itp files
  - 6-step equilibration with progressive position restraint release
  - CHARMM36m force field with ParmEd-based topology conversion

References:
  Jo S, Kim T, Iyer VG, Im W. CHARMM-GUI: A web-based graphical user
  interface for CHARMM. J Comput Chem. 2008;29(11):1859-1865.
  doi:10.1002/jcc.20945

  Wu EL, Cheng X, Jo S, et al. CHARMM-GUI Membrane Builder toward
  realistic biological membrane simulations. J Comput Chem. 2014;
  35(27):1997-2004. doi:10.1002/jcc.23702
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import gemmi


# ── Force field / water model maps ───────────────────────────────────────────

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

# ── Residue classification sets ──────────────────────────────────────────────

_PROTEIN_RESIDUES = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "HID", "HIE", "HIP", "HSD", "HSE", "HSP", "CYX", "CYM",
    "ASH", "GLH", "LYN",
    "ACE", "NME", "NMA",
}

_WATER_RESIDUES = {"HOH", "WAT", "TIP3", "SOL", "TIP4", "TIP5", "SPC"}

_ION_RESIDUES = {
    "NA", "CL", "Na+", "Cl-", "K", "K+",
    "NA+", "CL-", "SOD", "CLA", "POT", "MG", "CA", "ZN",
}

_BACKBONE_ATOMS = {"N", "CA", "C", "O", "OXT"}

# PDBFixer atom name → CHARMM template name aliases
_NAME_ALIASES = {
    "H": ["HN", "HT1", "HT2", "HT3", "H"],
    "H2": ["HT2", "H2"],
    "H3": ["HT3", "H3"],
    "O": ["O", "OT1", "OH2"],
    "OXT": ["OT2", "OXT"],
    "HA3": ["HA2", "HA1", "HA3"],
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
        # Convert absolute paths in files to relative paths (relative to output_dir)
        out = Path(self.output_dir)
        rel_files = {}
        for k, v in self.files.items():
            try:
                rel_files[k] = str(Path(v).relative_to(out))
            except ValueError:
                rel_files[k] = v
        return {
            "engine": self.engine,
            "forcefield": self.forcefield,
            "files": rel_files,
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
        result.files = _write_gromacs(modeller, system, out_dir, forcefield_obj=forcefield)
    elif config.engine == "amber":
        result.files = _write_amber(modeller, system, out_dir)
    else:
        msg = f"Unsupported engine: {config.engine}. Available: gromacs, amber, openmm"
        raise ValueError(msg)

    # Write a PDB of the solvated system (for non-GROMACS engines which don't already write one)
    if config.engine != "gromacs":
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


def _write_gromacs(modeller, system, out_dir: Path, forcefield_obj=None) -> dict:
    """Write complete GROMACS simulation setup (CHARMM-GUI style)."""
    import openmm
    import openmm.app as app
    import parmed

    files = {}

    # Topology
    top_path = out_dir / "topol.top"
    _write_gmx_topology(top_path, modeller, system, forcefield_obj)
    files["topology"] = str(top_path)

    # Coordinates (.gro + .pdb)
    structure = parmed.openmm.load_topology(modeller.topology, xyz=modeller.positions)
    gro_path = out_dir / "step5_input.gro"
    structure.save(str(gro_path), overwrite=True)
    files["gro"] = str(gro_path)

    pdb_path = out_dir / "step5_input.pdb"
    with open(pdb_path, "w") as f:
        app.PDBFile.writeFile(modeller.topology, modeller.positions, f)
    files["pdb"] = str(pdb_path)

    # Index file, MDP files, README
    ndx_path = out_dir / "index.ndx"
    _write_index_ndx(ndx_path, modeller.topology)
    files["index"] = str(ndx_path)
    files.update(_write_mdp_files(out_dir))

    readme_path = out_dir / "README"
    _write_readme(readme_path)
    files["readme"] = str(readme_path)

    # OpenMM system XML as backup
    system_path = out_dir / "system.xml"
    with open(system_path, "w") as f:
        f.write(openmm.XmlSerializer.serialize(system))
    files["system_xml"] = str(system_path)

    return files


# ── GROMACS topology (ParmEd-based) ──────────────────────────────────────────

def _write_gmx_topology(top_path: Path, modeller, system, forcefield_obj):
    """Write GROMACS topology with toppar/ directory (CHARMM-GUI style).

    Pipeline: OpenMM system → ParmEd struct → fix atom types/LJ → monolithic .top
    → split into toppar/ directory with per-molecule ITP files + position restraints.
    """
    import warnings

    import openmm.app as app
    import openmm.unit as unit
    import parmed

    warnings.filterwarnings("ignore", category=UserWarning, module="parmed")

    topology = modeller.topology

    # Create unconstrained system so ParmEd can parse water bonds from HarmonicBondForce
    system_noconstr = forcefield_obj.createSystem(
        topology,
        nonbondedMethod=app.PME,
        nonbondedCutoff=1.0 * unit.nanometer,
        constraints=None,
        rigidWater=False,
    )

    struct = parmed.openmm.load_topology(topology, system_noconstr, xyz=modeller.positions)

    # Fix CHARMM36 atom types (ParmEd can't read CustomNonbondedForce)
    _fix_atom_types(struct, topology, forcefield_obj)

    # Add water angles for SETTLE geometry detection (if missing)
    _ensure_water_angles(struct)

    # Save monolithic .top, split into toppar/, clean up
    mono_path = top_path.parent / "_parmed_full.top"
    struct.save(str(mono_path), overwrite=True)
    _split_topology_to_toppar(str(mono_path), top_path)
    mono_path.unlink(missing_ok=True)


def _fix_atom_types(struct, topology, forcefield_obj):
    """Fix ParmEd atom types and LJ params using ForceField templates.

    ParmEd assigns generic types (N1, H1, C1) because CHARMM36 uses
    CustomNonbondedForce for LJ. We restore proper types (NH3, HC, CT1)
    from ForceField templates and LJ from LennardJonesGenerator.
    """
    import parmed

    # Build atom index → CHARMM type map from ForceField templates
    atom_type_map = _build_atom_type_map(topology, forcefield_obj)

    # Get LJ parameters from LennardJonesGenerator
    lj_data = {}
    for gen in forcefield_obj._forces:
        if gen.__class__.__name__ == "LennardJonesGenerator":
            lj_data = gen.ljTypes.paramsForType
            break

    type_registry = {}
    for i, atom in enumerate(struct.atoms):
        atype = atom_type_map.get(i)
        if not atype:
            continue
        atom.type = atype
        if atype not in type_registry:
            lj = lj_data.get(atype, {"sigma": 0.1, "epsilon": 0.0})
            sig_A = lj["sigma"] * 10              # nm → Å
            eps_kcal = lj["epsilon"] / 4.184       # kJ/mol → kcal/mol
            rmin = sig_A * 2 ** (1 / 6) / 2       # σ → Rmin/2
            at = parmed.AtomType(atype, None, atom.mass, atom.atomic_number)
            at.set_lj_params(eps_kcal, rmin)
            type_registry[atype] = at
        atom.atom_type = type_registry[atype]


def _ensure_water_angles(struct):
    """Add water H-O-H angles if missing (needed for ParmEd SETTLE detection)."""
    import parmed

    if any(a.atom1.residue.name in _WATER_RESIDUES for a in struct.angles):
        return

    hoh_angle_type = parmed.AngleType(k=100.0, theteq=104.52)
    water_residues = {}
    for atom in struct.atoms:
        if atom.residue.name in _WATER_RESIDUES:
            water_residues.setdefault(atom.residue.idx, []).append(atom)

    for atoms in water_residues.values():
        if len(atoms) != 3:
            continue
        o = next((a for a in atoms if a.atomic_number == 8), None)
        hs = [a for a in atoms if a.atomic_number == 1]
        if o and len(hs) == 2:
            struct.angles.append(parmed.Angle(hs[0], o, hs[1], type=hoh_angle_type))


def _split_topology_to_toppar(mono_path: str, top_path: Path):
    """Split ParmEd monolithic .top into CHARMM-GUI-style toppar/ directory.

    Output:
    - toppar/forcefield.itp  ([defaults] + [atomtypes] + [cmaptypes])
    - toppar/{MOLNAME}.itp   (per-molecule blocks + position restraints)
    - topol.top              (#include directives + [system] + [molecules])
    """
    with open(mono_path) as f:
        content = f.read()

    toppar_dir = top_path.parent / "toppar"
    toppar_dir.mkdir(parents=True, exist_ok=True)

    # Parse into [(header, body), ...] sections
    sections = _parse_top_sections(content)

    # Categorize sections
    ff_sections, mol_blocks, system_section, molecules_section = _categorize_sections(sections)

    # Rename protein molecules: ParmEd auto-names → PROA, PROB, ...
    name_remap = _rename_protein_molecules(mol_blocks)
    for old, new in name_remap.items():
        molecules_section = molecules_section.replace(old, new)

    # Write toppar/forcefield.itp
    _write_itp(toppar_dir / "forcefield.itp", ff_sections)

    # Write toppar/{MOLNAME}.itp for each unique molecule
    mol_order = []
    seen = set()
    for mol_name, mol_sections in mol_blocks:
        if mol_name in seen:
            continue
        seen.add(mol_name)
        mol_order.append(mol_name)

        itp_path = toppar_dir / f"{mol_name}.itp"
        with open(itp_path, "w") as f:
            f.write(f";;\n;; Generated by PATCHR simulation-ready pipeline\n;;\n")
            f.write(f";; GROMACS topology file for {mol_name}\n;;\n\n")
            for header, body in mol_sections:
                f.write(header + "\n" + body)
            _append_position_restraints(f, mol_name, mol_sections)

    # Write topol.top
    with open(top_path, "w") as f:
        f.write(";;\n;; Generated by PATCHR simulation-ready pipeline\n;;\n")
        f.write(";; The main GROMACS topology file\n;;\n\n")
        f.write("; Include forcefield parameters\n")
        f.write('#include "toppar/forcefield.itp"\n')
        for mol_name in mol_order:
            f.write(f'#include "toppar/{mol_name}.itp"\n')
        f.write("\n")
        f.write(system_section)
        f.write(molecules_section)


def _parse_top_sections(content: str):
    """Parse GROMACS topology text into [(header, body), ...] sections."""
    parts = re.compile(r"^(\[.*?\])", re.MULTILINE).split(content)
    sections = []
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((header, body))
    return sections


def _categorize_sections(sections):
    """Separate sections into forcefield, molecule blocks, system, and molecules."""
    _FF_SECTIONS = {"defaults", "atomtypes", "cmaptypes"}

    ff_sections = []
    mol_blocks = []       # [(name, [(header, body), ...]), ...]
    system_section = ""
    molecules_section = ""

    cur_mol = None        # (name, sections_list)

    for header, body in sections:
        name = header.strip("[] ").lower()

        if name in _FF_SECTIONS:
            ff_sections.append((header, body))
        elif name == "moleculetype":
            if cur_mol:
                mol_blocks.append(cur_mol)
            mol_name = _parse_mol_name(body)
            cur_mol = (mol_name, [(header, body)])
        elif name == "system":
            if cur_mol:
                mol_blocks.append(cur_mol)
                cur_mol = None
            system_section = header + body
        elif name == "molecules":
            molecules_section = header + body
        elif cur_mol:
            cur_mol = (cur_mol[0], cur_mol[1] + [(header, body)])

    if cur_mol:
        mol_blocks.append(cur_mol)

    return ff_sections, mol_blocks, system_section, molecules_section


def _parse_mol_name(body: str) -> str:
    """Extract molecule name from [moleculetype] body."""
    for line in body.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith(";"):
            return line.split()[0]
    return "UNK"


def _rename_protein_molecules(mol_blocks):
    """Rename protein molecule blocks from ParmEd auto-names to PROA/PROB/etc.

    Modifies mol_blocks in-place and returns the name mapping.
    """
    chain_labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    name_remap = {}
    chain_idx = 0

    for i, (mol_name, mol_sections) in enumerate(mol_blocks):
        if mol_name in _WATER_RESIDUES | _ION_RESIDUES:
            continue
        if not _is_protein_block(mol_sections):
            continue

        label = chain_labels[chain_idx] if chain_idx < 26 else str(chain_idx)
        new_name = f"PRO{label}"
        name_remap[mol_name] = new_name
        chain_idx += 1

        # Rename in [moleculetype] body
        new_sections = []
        for header, body in mol_sections:
            if "moleculetype" in header.lower():
                body = body.replace(mol_name, new_name, 1)
            new_sections.append((header, body))
        mol_blocks[i] = (new_name, new_sections)

    return name_remap


def _is_protein_block(mol_sections) -> bool:
    """Check if a molecule block is a protein by its first residue name."""
    for header, body in mol_sections:
        if "atoms" not in header.lower():
            continue
        for line in body.strip().split("\n"):
            parts = line.strip().split()
            if parts and not parts[0].startswith(";") and len(parts) > 3:
                return parts[3] in _PROTEIN_RESIDUES
    return False


def _write_itp(path: Path, sections):
    """Write an ITP file from section list."""
    with open(path, "w") as f:
        f.write(";;\n;; Generated by PATCHR simulation-ready pipeline\n;;\n\n")
        for header, body in sections:
            f.write(header + "\n" + body)


def _append_position_restraints(f, mol_name, mol_sections):
    """Append position restraint section to a protein molecule ITP file.

    Adds POSRES_FC_BB (backbone) / POSRES_FC_SC (sidechain) restraints.
    """
    atom_lines = []
    for header, body in mol_sections:
        if "atoms" in header.lower():
            for line in body.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith(";"):
                    atom_lines.append(line)

    if not atom_lines:
        return

    first_resname = atom_lines[0].split()[3] if len(atom_lines[0].split()) > 3 else ""
    if first_resname not in _PROTEIN_RESIDUES:
        return

    f.write("\n#ifdef POSRES\n")
    f.write("[ position_restraints ]\n")
    f.write("; atom  functype      fcx              fcy              fcz\n")
    for line in atom_lines:
        parts = line.split()
        if len(parts) < 5:
            continue
        atom_nr = int(parts[0])
        atom_type = parts[1]
        atom_name = parts[4]
        if atom_type.startswith("H") and atom_type not in ("HSD", "HSE", "HSP"):
            continue
        if atom_name in _BACKBONE_ATOMS:
            f.write(f"{atom_nr:5d}     1    POSRES_FC_BB"
                    f"    POSRES_FC_BB    POSRES_FC_BB\n")
        else:
            f.write(f"{atom_nr:5d}     1    POSRES_FC_SC"
                    f"    POSRES_FC_SC    POSRES_FC_SC\n")
    f.write("#endif\n")


def _build_atom_type_map(topology, forcefield_obj) -> dict:
    """Map each atom index → CHARMM36 type using ForceField templates.

    Handles terminal variants and PDBFixer vs CHARMM naming differences
    via _NAME_ALIASES. Falls back to element-based matching as last resort.
    """
    atom_type_map = {}

    # Use ForceField's own residue matching for best accuracy
    try:
        data = forcefield_obj._SystemData(topology)
        template_for_res = forcefield_obj._matchAllResiduesToTemplates(
            data, topology, dict(), False
        )
    except Exception:
        template_for_res = None

    for residue in topology.residues():
        tmpl = (template_for_res[residue.index] if template_for_res
                else forcefield_obj._templates.get(residue.name))

        if tmpl is None:
            for atom in residue.atoms():
                elem = atom.element.symbol if atom.element else "X"
                atom_type_map[atom.index] = f"X{elem}"
            continue

        template_atoms = {a.name: a.type for a in tmpl.atoms}
        used = set()

        for atom in residue.atoms():
            atype = _match_atom_type(atom, tmpl, template_atoms, used)
            atom_type_map[atom.index] = atype

    return atom_type_map


def _match_atom_type(atom, tmpl, template_atoms, used) -> str:
    """Match a single atom to its CHARMM type from a ForceField template."""
    # Direct name match
    atype = template_atoms.get(atom.name)
    if atype and atom.name not in used:
        used.add(atom.name)
        return atype

    # Try aliases (PDBFixer name → CHARMM template name)
    for alias in _NAME_ALIASES.get(atom.name, []):
        if alias in template_atoms and alias not in used:
            used.add(alias)
            return template_atoms[alias]

    # Last resort: match by element
    elem = atom.element.symbol if atom.element else "X"
    for tmpl_atom in tmpl.atoms:
        if tmpl_atom.name not in used and tmpl_atom.element and tmpl_atom.element.symbol == elem:
            used.add(tmpl_atom.name)
            return tmpl_atom.type

    return f"X{elem}"


def _classify_residues(topology):
    """Classify residues into SOLU, SOLV groups. Returns atom index lists (1-based)."""
    solu, solv = [], []

    for atom in topology.atoms():
        idx = atom.index + 1  # GROMACS is 1-based
        if atom.residue.name in _PROTEIN_RESIDUES:
            solu.append(idx)
        else:
            solv.append(idx)

    return solu, solv


def _write_ndx_group(f, name: str, indices: list):
    """Write one index group in GROMACS .ndx format (15 per line)."""
    f.write(f"[ {name} ]\n")
    for i in range(0, len(indices), 15):
        line = " ".join(f"{idx:6d}" for idx in indices[i:i + 15])
        f.write(line + "\n")
    f.write("\n")


def _write_index_ndx(ndx_path: Path, topology):
    """Generate GROMACS index file with SOLU, SOLV, SYSTEM groups."""
    solu, solv = _classify_residues(topology)
    system = list(range(1, sum(1 for _ in topology.atoms()) + 1))

    with open(ndx_path, "w") as f:
        _write_ndx_group(f, "SOLU", solu)
        _write_ndx_group(f, "SOLV", solv)
        _write_ndx_group(f, "SYSTEM", system)



# ── MDP file generation ─────────────────────────────────────────────────────
#
# Conventional soluble-protein equilibration protocol (4 steps, ~150 ps total).
#
# References:
#   - Lemkul GROMACS lysozyme tutorial (NVT 100 ps + NPT 100 ps, 1000 kJ/mol/nm²):
#     http://www.mdtutorials.com/gmx/lysozyme/06_equil.html
#     http://www.mdtutorials.com/gmx/lysozyme/07_equil2.html
#   - CHARMM-GUI Solution Builder (gradual restraint release, NVT→NPT):
#     https://www.charmm-gui.org
#   - Desmond/Schrödinger default relaxation (5 stages, ~160 ps):
#     https://github.com/maurobedoya/desmond_builder
#
# Schedule: NVT with gen_vel → NVT continuation → NPT with gradual release → NPT unrestrained
# Total: 25 + 25 + 50 + 50 = 150 ps

# Equilibration schedule: (step, BB, SC, dt, nsteps, pcoupl, gen_vel)
_EQ_SCHEDULE = [
    ("6.1", 1000, 1000, 0.001, 25000, False, True),   # NVT  25 ps
    ("6.2", 1000,  500, 0.001, 25000, False, False),   # NVT  25 ps
    ("6.3",  500,  200, 0.002, 25000, True,  False),   # NPT  50 ps
    ("6.4",  200,    0, 0.002, 25000, True,  False),   # NPT  50 ps
]


def _make_define_line(bb, sc):
    """Build the define line for MDP restraints."""
    return f"-DPOSRES -DPOSRES_FC_BB={bb:.1f} -DPOSRES_FC_SC={sc:.1f}"


def _make_minimization_mdp():
    """Generate minimization MDP content."""
    define = _make_define_line(4000, 2000)

    return f"""\
define                  = {define}
integrator              = steep
emtol                   = 1000.0
nsteps                  = 5000
nstlist                 = 10
cutoff-scheme           = Verlet
rlist                   = 1.2
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw_switch             = 1.0
rvdw                    = 1.2
coulombtype             = PME
rcoulomb                = 1.2
;
constraints             = h-bonds
constraint_algorithm    = LINCS
"""


def _make_equilibration_mdp(step, bb, sc, dt, nsteps, pcoupl, gen_vel):
    """Generate equilibration MDP content."""
    define = _make_define_line(bb, sc)
    tc_grps = "SOLU SOLV"
    tau_t = "1.0 1.0"
    ref_t = "300.0 300.0"
    comm_grps = "SOLU SOLV"
    gen_temp = "300.0"

    lines = [
        f"define                  = {define}",
        "integrator              = md",
        f"dt                      = {dt}",
        f"nsteps                  = {nsteps}",
        "nstxout-compressed      = 5000",
        "nstxout                 = 0",
        "nstvout                 = 0",
        "nstfout                 = 0",
        "nstcalcenergy           = 100",
        "nstenergy               = 1000",
        "nstlog                  = 1000",
        ";",
        "cutoff-scheme           = Verlet",
        "nstlist                 = 20",
        "rlist                   = 1.2",
        "vdwtype                 = Cut-off",
        "vdw-modifier            = Force-switch",
        "rvdw_switch             = 1.0",
        "rvdw                    = 1.2",
        "coulombtype             = PME",
        "rcoulomb                = 1.2",
        ";",
        "tcoupl                  = v-rescale",
        f"tc_grps                 = {tc_grps}",
        f"tau_t                   = {tau_t}",
        f"ref_t                   = {ref_t}",
    ]

    if pcoupl:
        lines += [
            ";",
            "pcoupl                  = C-rescale",
            "pcoupltype              = isotropic",
            "tau_p                   = 5.0",
            "compressibility         = 4.5e-5",
            "ref_p                   = 1.0",
            "refcoord_scaling        = com",
        ]

    lines += [";", "constraints             = h-bonds", "constraint_algorithm    = LINCS"]

    if not gen_vel:
        lines.append("continuation            = yes")

    lines += [
        ";",
        "nstcomm                 = 100",
        "comm_mode               = linear",
        f"comm_grps               = {comm_grps}",
    ]

    if gen_vel:
        lines += [
            ";",
            "gen-vel                 = yes",
            f"gen-temp                = {gen_temp}",
            "gen-seed                = -1",
        ]

    return "\n".join(lines) + "\n"


def _make_production_mdp():
    """Generate production MDP content."""
    tc_grps = "SOLU SOLV"
    tau_t = "1.0 1.0"
    ref_t = "300.0 300.0"
    comm_grps = "SOLU SOLV"

    return f"""\
integrator              = md
dt                      = 0.002
nsteps                  = 500000
nstxout-compressed      = 50000
nstxout                 = 0
nstvout                 = 0
nstfout                 = 0
nstcalcenergy           = 100
nstenergy               = 1000
nstlog                  = 1000
;
cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw_switch             = 1.0
rvdw                    = 1.2
coulombtype             = PME
rcoulomb                = 1.2
;
tcoupl                  = v-rescale
tc_grps                 = {tc_grps}
tau_t                   = {tau_t}
ref_t                   = {ref_t}
;
pcoupl                  = C-rescale
pcoupltype              = isotropic
tau_p                   = 5.0
compressibility         = 4.5e-5
ref_p                   = 1.0
;
constraints             = h-bonds
constraint_algorithm    = LINCS
continuation            = yes
;
nstcomm                 = 100
comm_mode               = linear
comm_grps               = {comm_grps}
"""


def _write_mdp_files(out_dir: Path) -> dict:
    """Write all MDP files and return file dict."""
    files = {}

    # Minimization
    mini_path = out_dir / "step6.0_minimization.mdp"
    mini_path.write_text(_make_minimization_mdp())
    files["mdp_minimization"] = str(mini_path)

    # Equilibration steps
    for step, bb, sc, dt, nsteps, pcoupl, gen_vel in _EQ_SCHEDULE:
        eq_path = out_dir / f"step{step}_equilibration.mdp"
        eq_path.write_text(_make_equilibration_mdp(step, bb, sc, dt, nsteps, pcoupl, gen_vel))
        files[f"mdp_equilibration_{step}"] = str(eq_path)

    # Production
    prod_path = out_dir / "step7_production.mdp"
    prod_path.write_text(_make_production_mdp())
    files["mdp_production"] = str(prod_path)

    return files


def _write_readme(readme_path: Path):
    """Write GROMACS run script README."""
    readme_path.write_text("""\
#!/bin/bash
#
# Generated by PATCHR simulation-ready pipeline
# Conventional soluble-protein equilibration protocol (4 steps, ~150 ps).
#
# References:
#   Lemkul GROMACS tutorial: http://www.mdtutorials.com/gmx/lysozyme/06_equil.html
#   CHARMM-GUI Solution Builder: https://www.charmm-gui.org
#
# GROMACS simulation setup with progressive restraint relaxation.
# Optimized for GROMACS 2019.2 or above.
#
# For MPI parallelizing:
#   mpirun -np $NUM_CPU gmx mdrun -ntomp 1

set -e

init=step5_input
rest_prefix=step5_input
mini_prefix=step6.0_minimization
prod_prefix=step7_production
prod_step=step7

# Minimization
# If minimization fails with single precision, try double precision (gmx_d)
gmx grompp -f ${mini_prefix}.mdp -o ${mini_prefix}.tpr -c ${init}.gro -r ${rest_prefix}.gro -p topol.top -n index.ndx
gmx mdrun -v -deffnm ${mini_prefix}

# Equilibration (4 steps with decreasing restraints)
for cnt in 1 2 3 4; do
    pcnt=$((cnt - 1))
    istep=$(printf "step6.%d_equilibration" $cnt)
    if [ $cnt -eq 1 ]; then
        pstep=${mini_prefix}
    else
        pstep=$(printf "step6.%d_equilibration" $pcnt)
    fi

    gmx grompp -f ${istep}.mdp -o ${istep}.tpr -c ${pstep}.gro -r ${rest_prefix}.gro -p topol.top -n index.ndx
    gmx mdrun -v -deffnm ${istep}
done

# Production (10 segments)
for cnt in $(seq 1 10); do
    pcnt=$((cnt - 1))
    istep=${prod_step}_${cnt}
    pstep=${prod_step}_${pcnt}

    if [ $cnt -eq 1 ]; then
        pstep=$(printf "step6.%d_equilibration" 4)
        gmx grompp -f ${prod_prefix}.mdp -o ${istep}.tpr -c ${pstep}.gro -p topol.top -n index.ndx
    else
        gmx grompp -f ${prod_prefix}.mdp -o ${istep}.tpr -c ${pstep}.gro -t ${pstep}.cpt -p topol.top -n index.ndx
    fi
    gmx mdrun -v -deffnm ${istep}
done
""")


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
