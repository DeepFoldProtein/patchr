"""StructureProcessor: main class that composes all Mixin capabilities."""
import os
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .. import cif_writer, yaml_writer, json_writer
from ..ccd_utils import load_ccd_dict, get_non_standard_parent_from_ccd, is_ccd_available
from ..constants import (
    get_boltz_cache,
    get_default_ccd_path,
    NONSTANDARD_TO_STANDARD,
    STANDARD_AA_CODES,
    STANDARD_AA_THREE_LETTER,
    STANDARD_NUCLEOTIDE_CODES,
    STANDARD_RES_ONE_LETTER,
    STANDARD_RES_THREE_LETTER,
    ref_atoms,
)

from .cif_io import CifIOMixin
from .chain_mapping import ChainMappingMixin
from .chain_discovery import ChainDiscoveryMixin
from .modifications import ModificationsMixin
from .sequence_fetch import SequenceFetchMixin
from .sequence_extract import SequenceExtractMixin
from .atom_parse import AtomParseMixin
from .alignment import AlignmentMixin
from .validation import ValidationMixin
from .assembly import AssemblyMixin
from .log import info, debug, warning, error, status, section, detail, success, fatal


class StructureProcessor(
    CifIOMixin,
    ChainMappingMixin,
    ChainDiscoveryMixin,
    ModificationsMixin,
    SequenceFetchMixin,
    SequenceExtractMixin,
    AtomParseMixin,
    AlignmentMixin,
    ValidationMixin,
    AssemblyMixin,
):
    """Orchestrates PDB structure processing for inpainting template generation."""

    def __init__(self, pdb_id: str, chain_ids: List[str], uniprot_mode: bool = False, cif_file_path: Optional[str] = None, interactive_sequence: bool = False, custom_sequences: Optional[Dict[str, str]] = None, cache_dir: Optional[Path] = None, include_solvent: bool = False, include_ligands: bool = True, assembly_id: Optional[Union[int, str]] = None, list_assemblies: bool = False, skip_terminal: bool = False, verbose: bool = False, output_format: str = 'yaml', use_absolute_path: bool = True, modifications: Optional[Dict[str, List[Dict]]] = None):
        # Check if pdb_id is a file path
        self.is_local_file = False
        self.cif_file_path = cif_file_path
        self.cache_dir = cache_dir  # for ccd.pkl (BOLTZ_CACHE or ~/.boltz)
        self.include_solvent = include_solvent
        self.include_ligands = include_ligands
        self.skip_terminal = skip_terminal
        # User-requested PTMs: {chain: [{'resid': <entity seq_id int>, 'ccd': CCD}, ...]}.
        # 'resid' is the 1-based ENTITY (canonical) sequence position — the same seq_id
        # the studio sends and the same numbering boltz uses for modifications.position.
        # Keyed by AUTHOR chain id on input; chain_mapping remaps to internal label ids.
        self.user_modifications: Dict[str, List[Dict]] = modifications or {}
        
        if cif_file_path:
            # Explicit file path provided
            self.is_local_file = True
            self.pdb_id = Path(cif_file_path).stem.upper()  # Use filename without extension as PDB ID
        elif os.path.exists(pdb_id):
            # pdb_id is actually a file path
            self.is_local_file = True
            self.cif_file_path = pdb_id
            self.pdb_id = Path(pdb_id).stem.upper()
        else:
            # pdb_id is a PDB ID
            self.pdb_id = pdb_id.upper()
        
        # Normalize chain_ids to list (preserve case for chain IDs)
        if isinstance(chain_ids, str):
            # Support comma-separated string like "A,B" or single "A", or "all"/"all-copies"
            chain_ids_stripped = chain_ids.strip()
            chain_ids_upper = chain_ids_stripped.upper()
            if chain_ids_upper == 'ALL':
                chain_ids = ['ALL']  # Will be resolved after loading CIF (all polymer chains, e.g. A,B,C,D for 1A1B)
            elif chain_ids_upper == 'ALL-COPIES':
                chain_ids = ['ALL-COPIES']  # Same as ALL: all polymer chains
            else:
                chain_ids = [c.strip() for c in chain_ids.split(',')]  # Preserve case
        self.chain_ids = list(chain_ids)  # Preserve case
        self.uniprot_mode = uniprot_mode
        self.interactive_sequence = interactive_sequence
        self.cif_content = None
        # Per-chain data
        self.chain_data = {}  # chain_id -> {sequence, seqres_sequence, uniprot_id, ...}
        self.chain_entity_types = {}  # chain_id -> 'protein', 'dna', or 'rna'
        self.manual_sequences = custom_sequences or {}  # chain_id -> custom sequence (from CLI or interactive)
        # Chain ID mapping (auth_asym_id <-> label_asym_id)
        self.auth_to_label = {}  # e.g., 'X' -> 'A'
        self.label_to_auth = {}  # e.g., 'A' -> 'X'
        # Author chain IDs for output (YAML, CIF file names, etc.)
        self.author_chain_ids = {}  # label_id -> author_id (for output files)
        # Non-standard residue information (e.g. ACE, TPO, NH2)
        # chain_id -> {seq_id: {'ccd': CCD_CODE, 'parent': PARENT_CODE, 'parent_one': ONE_LETTER}}
        self.non_standard_residues = {}
        # Cached CIF dict to avoid re-parsing the same CIF many times per chain (major speedup)
        self._cif_dict = None
        # When True, print DEBUG and per-chain blocks (set via --verbose flag or BOLTZ_VERBOSE=1)
        self.verbose = verbose or os.environ.get("BOLTZ_VERBOSE", "").strip().lower() in ("1", "true", "yes")
        # Output format: 'yaml' (patchr) or 'protenix-json'
        self.output_format = output_format
        # Assembly selection
        self.assembly_id = assembly_id          # None / 'best' / str(N)
        self.list_assemblies = list_assemblies
        self.use_absolute_path = use_absolute_path
        self._synthetic_atoms: Dict[str, List[Dict]] = {}  # synthetic chain atoms from non-identity symmetry ops
        self._assembly_entity_types: Dict[str, str] = {}   # label_asym_id -> entity type for assembly chains


    def _processed_chain_ids(self, all_chains_data: Dict[str, Dict]) -> List[str]:
        """Return only the chain IDs that were successfully processed (present in all_chains_data).

        Chains may be absent because their CCD was unsupported, they had no atoms, etc.
        Preserving the original order from self.chain_ids.
        """
        return [c for c in self.chain_ids if c in all_chains_data]

    def generate_cif(self, all_chains_data: Dict[str, Dict], solvent_atoms: Optional[List[Dict]] = None) -> str:
        """Generate complete CIF file for multiple chains (delegates to cif_writer)."""
        return cif_writer.generate_cif(
            self.pdb_id,
            self._processed_chain_ids(all_chains_data),
            all_chains_data,
            solvent_atoms,
            self.cif_content,
            getattr(self, "_modifications_from_entity_poly", {}),
        )


    def generate_yaml(self, cif_path: Path, output_dir: Path, all_chains_data: Dict[str, Dict],
                       inpainting_metadata_path: Path = None,
                       use_absolute_path: bool = True) -> str:
        """Generate YAML configuration (delegates to yaml_writer)."""
        return yaml_writer.generate_yaml(self._processed_chain_ids(all_chains_data), all_chains_data, cif_path, output_dir,
                                         inpainting_metadata_path=inpainting_metadata_path,
                                         use_absolute_path=use_absolute_path)

    def generate_json(self, cif_path: Path, output_dir: Path, all_chains_data: Dict[str, Dict],
                      inpainting_metadata_path: Path = None,
                      use_absolute_path: bool = True) -> str:
        """Generate Protenix JSON configuration (delegates to json_writer)."""
        return json_writer.generate_json(self._processed_chain_ids(all_chains_data), all_chains_data, cif_path, output_dir,
                                         inpainting_metadata_path=inpainting_metadata_path,
                                         use_absolute_path=use_absolute_path)



    def process(self, output_dir: Path):
        """Main processing pipeline for multiple chains."""
        chain_ids_str = ','.join(self.chain_ids)
        section(f"Processing PDB: {self.pdb_id}, Chains: {chain_ids_str}")
        info(f"UniProt mode: {'ON' if self.uniprot_mode else 'OFF'}")
        
        # Load CIF (from local file or download)
        self.load_cif()

        # Build authoritative entity type map from CIF tables (_entity_poly.type etc.)
        # This is used as the primary source for entity type detection throughout.
        self._assembly_entity_types = self._build_entity_type_map()

        # ------------------------------------------------------------------
        # Assembly selection (--assembly / --list-assemblies)
        # Runs before chain normalization so that assembly chain IDs (which
        # are label_asym_ids straight from the CIF) are used directly.
        # ------------------------------------------------------------------
        if self.list_assemblies or self.assembly_id is not None:
            assembly_info = self.parse_assembly_info()
            self._print_assembly_info(assembly_info)

            if self.list_assemblies:
                # Just listing — stop here
                return

            # Determine which assembly to use
            if str(self.assembly_id).lower() == 'best':
                selected_id = self.select_best_assembly(assembly_info)
                if selected_id is None:
                    warning("Could not determine best assembly; proceeding with original chains.")
                else:
                    info(f"Auto-selected assembly {selected_id} "
                         f"({assembly_info['assemblies'].get(selected_id, {}).get('details', '?')}, "
                         f"{assembly_info['assemblies'].get(selected_id, {}).get('oligomeric_details', '?')})")
            else:
                selected_id = str(self.assembly_id)
                if selected_id not in assembly_info.get('assemblies', {}):
                    warning(f"Assembly {selected_id} not found; "
                            f"available: {list(assembly_info['assemblies'].keys())}. "
                            "Proceeding with original chains.")
                    selected_id = None

            if selected_id is not None:
                asm_chain_ids, synthetic_atoms = self.get_assembly_chains(selected_id, assembly_info)
                if asm_chain_ids:
                    info(f"Assembly {selected_id} chains: {', '.join(asm_chain_ids)}")
                    # Override chain selection (assembly takes precedence over CLI chain IDs / ALL)
                    self.chain_ids = asm_chain_ids
                    self._synthetic_atoms = synthetic_atoms
                    # Build author_chain_ids for assembly chains
                    # Also store to self so UniProt mode / sequence_fetch can use label_to_auth
                    auth_to_label, label_to_auth = self.build_auth_to_label_chain_mapping()
                    self.auth_to_label = auth_to_label
                    self.label_to_auth = label_to_auth
                    for cid in asm_chain_ids:
                        cid_upper = cid.upper()
                        if cid_upper in label_to_auth:
                            self.author_chain_ids[cid] = label_to_auth[cid_upper]
                        else:
                            self.author_chain_ids[cid] = cid
                else:
                    warning("Assembly produced no chains; proceeding with original chains.")

        # Load CCD from ccd.pkl (same as mmcif.parse_mmcif mols / main.py)
        ccd_dir = self.cache_dir or get_boltz_cache()
        ccd_path = ccd_dir / "ccd.pkl"
        if not ccd_path.exists():
            import urllib.request
            CCD_URL = "https://huggingface.co/boltz-community/boltz-1/resolve/main/ccd.pkl"
            info(f"Downloading CCD dictionary to {ccd_path} ...")
            ccd_dir.mkdir(parents=True, exist_ok=True)
            try:
                urllib.request.urlretrieve(CCD_URL, str(ccd_path))  # noqa: S310
                success(f"Downloaded ccd.pkl successfully.")
            except Exception as e:
                error(f"Failed to download ccd.pkl: {e}")
                fatal("Please download manually or set --cache to a directory containing ccd.pkl.")
        ccd = load_ccd_dict(ccd_path)
        self.ccd = ccd  # stored so ligand / modification validation can use it later
        # Parse non-standard residue info from CIF (uses ccd.pkl via ccd_utils)
        self.parse_non_standard_residues(ccd=ccd)

        # Modifications from _entity_poly_seq (same as generate_yaml.py) for correct ACE/PTR/DIP in YAML
        self._modifications_from_entity_poly = self._get_modifications_from_entity_poly_seq()
        # Modifications from _struct_conn (covale) e.g. NH2 at B 7 when entity_poly_seq has UNK
        self._modifications_from_struct_conn = self._get_modifications_from_struct_conn()

        # Normalize chain IDs: convert auth_asym_id (X, Y, Z) to label_asym_id (A, B, C)
        # This handles the common case where users provide author chain IDs from PDB viewers
        # (Skip if assembly already resolved chain IDs — they are already label_asym_ids)
        if self.assembly_id is None:
            self.normalize_chain_ids()

        # If "ALL" or "ALL-COPIES" is specified, detect all polymer chains automatically.
        # Skip this block when assembly selection already determined self.chain_ids.
        if 'ALL' in self.chain_ids or 'ALL-COPIES' in self.chain_ids:
            include_all_copies = True  # Always include all chains so ALL gives A,B,C,D for 1A1B
            all_chains, chain_entity_types = self.get_all_polymer_chains(include_all_copies=include_all_copies)
            if not all_chains:
                fatal("No polymer chains found in structure")
            self.chain_ids = all_chains
            self.chain_entity_types = chain_entity_types
            
            # Build author chain ID mapping for auto-detected chains
            if hasattr(self, 'label_to_auth') and self.label_to_auth:
                for chain_id in all_chains:
                    chain_upper = chain_id.upper()
                    if chain_upper in self.label_to_auth:
                        self.author_chain_ids[chain_id] = self.label_to_auth[chain_upper]
                    else:
                        self.author_chain_ids[chain_id] = chain_id
            else:
                for chain_id in all_chains:
                    self.author_chain_ids[chain_id] = chain_id
            
            type_summary = ', '.join([f"{chain_entity_types.get(c, '?')}" for c in all_chains])
            info(f"Auto-detected {len(self.chain_ids)} polymer chain(s): {','.join(self.chain_ids)} ({type_summary})")

        # Ligand chain handling
        if self.assembly_id is not None:
            # Assembly mode: assembly_gen already includes ligand chains.
            # If --exclude-ligands, remove them from the list now.
            if not self.include_ligands:
                # Use base chain ID for synthetic chains so ligand lookup works
                real_ligand_chains = set(self.get_ligand_chain_ids())
                before = list(self.chain_ids)
                self.chain_ids = [
                    c for c in self.chain_ids
                    if self._base_chain_id(c) not in real_ligand_chains
                ]
                removed = [c for c in before if c not in self.chain_ids]
                if removed:
                    info(f"Excluded ligand chain(s) from assembly: {removed}")
        else:
            # Non-assembly mode: add ligand chains if include_ligands
            if self.include_ligands:
                ligand_chains = self.get_ligand_chain_ids()
                added = [c for c in ligand_chains if c not in self.chain_ids]
                for c in added:
                    self.chain_ids = list(self.chain_ids) + [c]
                    # Resolve author chain ID from _atom_site if possible.
                    if hasattr(self, 'label_to_auth') and self.label_to_auth:
                        self.author_chain_ids[c] = self.label_to_auth.get(c.upper(), c)
                    else:
                        self.author_chain_ids[c] = c
                if added:
                    info(f"Include ligands: added chain(s) {added}")
        
        # Handle default sequence (single sequence for single chain)
        if '_default_' in self.manual_sequences:
            default_seq = self.manual_sequences.pop('_default_')
            if len(self.chain_ids) == 1:
                # Single chain - apply default sequence
                self.manual_sequences[self.chain_ids[0]] = default_seq
            else:
                # Multiple chains - error
                error("Single sequence provided but multiple chains detected.")
                error(f"Please specify sequences for each chain: --sequence A:SEQ1,B:SEQ2")
                fatal(f"Detected chains: {','.join(self.chain_ids)}")
        
        # NOTE: author_chain_ids may contain duplicates (e.g. 8WLO where all
        # NAG ligand asym_ids share auth "A"/"B"/"C" with the polymer chains).
        # That is fine because the output CIF / YAML / metadata key off
        # label_asym_id (which is guaranteed unique).  The original author
        # IDs are preserved in _atom_site.auth_asym_id and in the metadata's
        # chain_mapping, so downstream tools can still recover them.

        # Process each chain
        all_chains_data = {}
        entity_id = 1
        assembly_solvent_atoms: list = []  # solvent atoms collected from assembly chains

        for chain_id in self.chain_ids:
            # Detect water/solvent chains and collect them separately.
            # They flow through the assembly path (with symmetry ops applied) but
            # are not processed as polymers or ligands.
            base_id = self._base_chain_id(chain_id)
            chain_etype = self._assembly_entity_types.get(base_id, '')
            if 'water' in chain_etype:
                if self.include_solvent:
                    atoms = self.parse_atom_records(chain_id)
                    if atoms:
                        author_chain_id = self.author_chain_ids.get(chain_id, chain_id)
                        for atom in atoms:
                            atom['auth_asym_id'] = author_chain_id
                            atom['label_asym_id'] = chain_id  # keep unique label
                        assembly_solvent_atoms.extend(atoms)
                        info(f"Chain {chain_id}: solvent ({len(atoms)} atoms)")
                continue

            if self.verbose:
                section(f"Processing Chain: {chain_id}")
            
            # Get entity type for this chain (determined from actual atoms or CIF entity)
            # First try to get from chain_entity_types (if already set from get_all_polymer_chains)
            entity_type = self.chain_entity_types.get(chain_id)
            if entity_type is None:
                # For synthetic chains (e.g. A-2), check the base chain's entity type first
                base_id = self._base_chain_id(chain_id)
                if base_id != chain_id:
                    entity_type = self.chain_entity_types.get(base_id)
            if entity_type is None:
                # Chains added via include_ligands are non-polymer; treat as ligand
                # (use base chain ID for synthetic chains)
                real_ligand_set = set(self.get_ligand_chain_ids())
                lookup_chain = self._base_chain_id(chain_id)
                if lookup_chain in real_ligand_set:
                    entity_type = 'ligand'
                else:
                    # Primary: use authoritative CIF entity type map (_entity_poly.type)
                    entity_type = self._assembly_entity_types.get(lookup_chain)

                    if entity_type is None or entity_type == 'water':
                        # Fallback: determine from actual atoms for this chain
                        cif_dict = self._get_cif_dict()
                        if '_atom_site.label_asym_id' in cif_dict and '_atom_site.label_comp_id' in cif_dict:
                            label_asym_ids = cif_dict['_atom_site.label_asym_id']
                            label_comp_ids = cif_dict['_atom_site.label_comp_id']

                            chain_residues = set()
                            for i, chain in enumerate(label_asym_ids):
                                if chain != lookup_chain:
                                    continue
                                if i < len(label_comp_ids):
                                    chain_residues.add(label_comp_ids[i])

                            dna_rna_residues = {'DA', 'DC', 'DG', 'DT', 'DI', 'A', 'C', 'G', 'T', 'U', 'I'}
                            protein_residues = {'ALA', 'CYS', 'ASP', 'GLU', 'PHE', 'GLY', 'HIS', 'ILE',
                                                'LYS', 'LEU', 'MET', 'ASN', 'PRO', 'GLN', 'ARG', 'SER',
                                                'THR', 'VAL', 'TRP', 'TYR'}
                            has_dna_rna = bool(chain_residues & dna_rna_residues)
                            has_protein = bool(chain_residues & protein_residues)
                            if has_dna_rna and not has_protein:
                                if 'U' in chain_residues or any('R' in r for r in chain_residues if len(r) > 1 and 'R' in r):
                                    entity_type = 'rna'
                                else:
                                    entity_type = 'dna'
                            elif has_protein and not has_dna_rna:
                                entity_type = 'protein'
                            elif chain_residues:
                                entity_type = 'ligand'
                            else:
                                entity_type = 'protein'  # Default
                        else:
                            entity_type = 'protein'  # Default

                # Store for later use
                self.chain_entity_types[chain_id] = entity_type
            
            # Branched glycans (oligosaccharides, e.g. NAG-(1-4)-NAG) cannot be
            # represented in the AF3/boltz input format. Encoding them as a
            # pseudo-protein corrupts the prediction: the "fixed" sugar atoms are
            # not preserved and drift ~20 A. Drop such chains from the template /
            # YAML / CIF and warn, rather than emitting a broken structure.
            if entity_type == 'branched':
                warning(f"Chain {chain_id}: branched glycan/oligosaccharide is not "
                        f"representable in the boltz (AF3) input format — dropping this "
                        f"chain (its sugar residues are excluded from the template and "
                        f"prediction).")
                continue

            # Ligand chain: no sequence, use CCD from atoms; include in CIF and YAML (docs/prediction.md)
            if entity_type == 'ligand':
                atoms = self.parse_atom_records(chain_id)
                if not atoms:
                    warning(f"No atoms for ligand chain {chain_id}, skipping")
                    continue
                ligand_ccd = (atoms[0].get('label_comp_id') or 'UNK').strip().upper()
                if not is_ccd_available(getattr(self, 'ccd', None), ligand_ccd):
                    warning(f"CCD '{ligand_ccd}' not found in boltz CCD database (or has no conformer), "
                            f"skipping ligand chain {chain_id}")
                    continue
                author_chain_id = self.author_chain_ids.get(chain_id, chain_id)
                if '\\' in author_chain_id:
                    warning(f"Chain {chain_id} has unsafe author chain ID {author_chain_id!r} "
                            f"(contains backslash), skipping")
                    continue
                for atom in atoms:
                    atom['label_entity_id'] = str(entity_id)
                    atom['label_seq_id'] = 1
                    atom['auth_seq_id'] = atom.get('auth_seq_id') or 1
                    atom['auth_asym_id'] = author_chain_id
                    atom['label_asym_id'] = chain_id  # unique label
                # Ligand chains are fully fixed (all atoms from template structure)
                ligand_atom_names = set(a.get('label_atom_id', '') for a in atoms)
                ligand_inpainting_meta = {
                    "fully_fixed_residues": [1],
                    "partially_fixed_residues": [],
                    "fully_inpainted_residues": [],
                    "total_atoms_with_structure": len(ligand_atom_names),
                    "total_expected_atoms": len(ligand_atom_names),
                }
                all_chains_data[chain_id] = {
                    'atoms': atoms,
                    'sequence': '',
                    'entity_id': entity_id,
                    'uniprot_id': None,
                    'entity_type': 'ligand',
                    'monomer_ids': {1: ligand_ccd},
                    'author_chain_id': author_chain_id,
                    'modifications': [],
                    'ccd': ligand_ccd,
                    'inpainting_metadata': ligand_inpainting_meta,
                }
                info(f"Chain {chain_id}: ligand (ccd={ligand_ccd})")
                entity_id += 1
                continue
            
            # Extract sequence: try SEQRES first, but if entity_poly_seq type doesn't match
            # actual atom type, extract from atoms instead
            try:
                seqres_sequence = self.extract_seqres_from_cif(chain_id)
                # Fallback: empty SEQRES (e.g. short peptides with no _entity_poly_seq entry)
                if not seqres_sequence:
                    warning(f"Empty SEQRES for chain {chain_id}, extracting sequence from atoms")
                    seqres_sequence = self.extract_sequence_from_atoms(chain_id)
                # Fallback for synthetic chains (e.g. D-2): extract_sequence_from_atoms looks up
                # label_asym_id in the CIF which only has the base chain ('D'), not 'D-2'.
                if not seqres_sequence:
                    base_id = self._base_chain_id(chain_id)
                    if base_id != chain_id:
                        warning(f"Empty sequence for synthetic chain {chain_id}, "
                                f"retrying with base chain {base_id}")
                        seqres_sequence = self.extract_sequence_from_atoms(base_id)
                        if not seqres_sequence:
                            seqres_sequence = self.extract_seqres_from_cif(base_id)
                # Verify sequence type matches entity type. Allow U (SEC) and O (PYL):
                # the canonical sequence uses these standard one-letter codes for the
                # 21st/22nd amino acids, so they are valid in a protein SEQRES and must
                # not trigger the nucleic-acid-misassignment fallback.
                if entity_type == 'protein':
                    protein_residues = set('ACDEFGHIKLMNPQRSTVWYUO')
                    if not all(c in protein_residues for c in seqres_sequence if c != 'X'):
                        # SEQRES doesn't match, extract from atoms
                        warning(f"SEQRES sequence type doesn't match protein atoms, extracting from atoms")
                        seqres_sequence = self.extract_sequence_from_atoms(chain_id)
                elif entity_type in ['dna', 'rna']:
                    dna_rna_residues = set('ACGTUIN')
                    if not all(c in dna_rna_residues for c in seqres_sequence if c != 'X' and c != 'N'):
                        # SEQRES doesn't match, extract from atoms
                        warning(f"SEQRES sequence type doesn't match {entity_type.upper()} atoms, extracting from atoms")
                        seqres_sequence = self.extract_sequence_from_atoms(chain_id)
            except Exception as e:
                # If SEQRES extraction fails, extract from atoms
                warning(f"Failed to extract SEQRES, extracting from atoms: {e}")
                seqres_sequence = self.extract_sequence_from_atoms(chain_id)
        
            # Get final sequence to use
            uniprot_id = None
            
            if self.verbose:
                debug(f"Checking sequence for chain {chain_id}:")
                detail(f"Available in manual_sequences: {chain_id in self.manual_sequences}")
                detail(f"manual_sequences keys: {list(self.manual_sequences.keys())}")
                detail(f"Entity type: {entity_type}")
                detail(f"SEQRES sequence length: {len(seqres_sequence)}")
            
            # Check if custom sequence is provided (CLI or interactive)
            if chain_id in self.manual_sequences:
                # Use custom sequence from CLI
                final_sequence = self.manual_sequences[chain_id]
                info(f"Using custom sequence for chain {chain_id} (length: {len(final_sequence)})")
                debug(f"Custom sequence preview: {final_sequence[:50]}...")
            elif self.interactive_sequence:
                # Prompt for manual sequence input
                manual_seq = self.prompt_manual_sequence(chain_id, entity_type, seqres_sequence)
                if manual_seq:
                    final_sequence = manual_seq
                    self.manual_sequences[chain_id] = manual_seq
                    info(f"Using manually entered sequence for chain {chain_id} (length: {len(final_sequence)})")
                else:
                    info(f"Skipping chain {chain_id}")
                    continue
            elif self.uniprot_mode and entity_type == 'protein':
                # UniProt only for proteins
                uniprot_id = self.get_uniprot_id_from_pdb(chain_id)
                if uniprot_id:
                    uniprot_sequence = self.fetch_uniprot_sequence(uniprot_id)
                    # Use UniProt sequence as the final sequence
                    final_sequence = uniprot_sequence
                else:
                    warning("Falling back to SEQRES sequence")
                    final_sequence = seqres_sequence
            else:
                # Use SEQRES sequence (for DNA/RNA or when UniProt mode is off)
                if self.uniprot_mode and entity_type != 'protein':
                    warning(f"UniProt mode is ON but chain {chain_id} is {entity_type.upper()}, using SEQRES sequence")
                final_sequence = seqres_sequence
            
            # Parse atoms
            atoms = self.parse_atom_records(chain_id)
            
            # Get residue mapping (for DNA/RNA, use simpler mapping based on structure order)
            if entity_type in ['dna', 'rna']:
                # For DNA/RNA, use simpler sequential mapping
                # Map structure residues sequentially to sequence positions
                residue_mapping = self.get_residue_mapping_dna_rna(atoms, seqres_sequence, final_sequence)
            else:
                # For proteins, use alignment-based mapping (pass chain_id so non-standard residues get parent_one)
                residue_mapping = self.get_residue_mapping(atoms, seqres_sequence, final_sequence, chain_id=chain_id)
            
            # Filter atoms by target sequence (UniProt, manually entered, or custom) if applicable (only for proteins)
            removed_residues = []
            if (self.uniprot_mode or self.interactive_sequence or chain_id in self.manual_sequences) and entity_type == 'protein':
                atoms, removed_residues = self.filter_atoms_by_uniprot_sequence(atoms, residue_mapping, final_sequence)
                
                if removed_residues:
                    sequence_type = "manually entered sequence" if self.interactive_sequence else "UniProt sequence"
                    section(f"REMOVED RESIDUES (Chain {chain_id}, {sequence_type} mismatch):")
                    info(f"Total residues removed: {len(removed_residues)}")
                    for entry in removed_residues:
                        pos_info = f"Position {entry['uniprot_pos']}" if entry['uniprot_pos'] else "Not mapped"
                        target_aa_label = "Target" if self.interactive_sequence else "UniProt"
                        detail(f"Residue {entry['residue']} ({pos_info}): "
                               f"Structure={entry['struct_type']} ({entry['struct_aa']}), "
                               f"{target_aa_label}={entry['uniprot_aa']}")
                    
                    # Recalculate residue mapping after filtering
                    residue_mapping = self.get_residue_mapping(atoms, seqres_sequence, final_sequence, chain_id=chain_id)
                else:
                    sequence_type = "manually entered sequence" if self.interactive_sequence else "UniProt sequence"
                    section(f"Sequence check (Chain {chain_id}, {sequence_type}):")
                    detail(f"All residues match {sequence_type}!")
            
            # Check for missing atoms in residues (only for proteins)
            if entity_type == 'protein':
                self.check_missing_atoms(atoms, residue_mapping, final_sequence)
            
            # Determine inpainting region (only for proteins, DNA/RNA uses different logic)
            chain_inpainting_metadata = None
            if entity_type == 'protein':
                _, chain_inpainting_metadata = self.determine_inpainting_region(atoms, residue_mapping, final_sequence)

            # --skip-terminal: mark N/C-terminal missing residues so they are NOT
            # inpainted, WITHOUT truncating the sequence or renumbering. The full
            # canonical sequence and original SEQRES numbering (label_seq_id) are kept
            # in the YAML/CIF; the trimmed range [kept_start, kept_end] (1-based, full-
            # sequence coords) is recorded so `patchr predict` can slice the sequence and
            # structure at read time. Only internal gaps stay in fully_inpainted_residues.
            chain_trim = None
            if self.skip_terminal and entity_type == 'protein':
                present_positions = set(residue_mapping.values())
                if present_positions:
                    kept_start = min(present_positions)
                    kept_end = max(present_positions)
                    if kept_start > 1 or kept_end < len(final_sequence):
                        chain_trim = {"kept_start": kept_start, "kept_end": kept_end,
                                      "full_length": len(final_sequence)}
                        detail(f"--skip-terminal: keeping full sequence (len "
                               f"{len(final_sequence)}); marked terminal residues "
                               f"1..{kept_start-1} and {kept_end+1}..{len(final_sequence)} "
                               f"as trimmed (not inpainted)")
                        if chain_inpainting_metadata is not None:
                            def _within(residues):
                                return [r for r in residues if kept_start <= r <= kept_end]
                            # Present residues are already inside the kept range; only
                            # the terminal *missing* residues need dropping from inpaint.
                            chain_inpainting_metadata["fully_inpainted_residues"] = _within(
                                chain_inpainting_metadata["fully_inpainted_residues"])

            # Renumber atoms (update label_entity_id and label_asym_id for multimeric)
            renumbered_atoms = self.renumber_atoms(atoms, residue_mapping)
            
            # Update entity_id and label_asym_id for multimeric support
            # Use author chain ID for auth_asym_id (for output files)
            author_chain_id = self.author_chain_ids.get(chain_id, chain_id)
            for atom in renumbered_atoms:
                atom['label_entity_id'] = str(entity_id)
                atom['label_asym_id'] = chain_id  # Keep label_asym_id as internal ID
                atom['auth_asym_id'] = author_chain_id  # Use author chain ID for output
            
            # Extract actual monomer IDs from atoms for each sequence position
            # This is critical for non-standard residues like 3DR (abasic site)
            seq_pos_to_monomer = {}
            for atom in renumbered_atoms:
                seq_id = atom.get('label_seq_id', '?')
                if seq_id != '?' and str(seq_id).isdigit():
                    pos = int(seq_id)
                    comp_id = atom.get('label_comp_id', 'UNK')
                    if pos not in seq_pos_to_monomer:
                        seq_pos_to_monomer[pos] = comp_id

            # Reconcile final_sequence with actual atom residues at each position.
            # This ensures entity_poly.pdbx_seq_one_letter_code, entity_poly_seq,
            # and atom_site are all consistent (prevents Alignment mismatch in boltz parser).
            _recon_map = {}
            if entity_type in ('dna', 'rna'):
                _dna_to_one = {'DA': 'A', 'DC': 'C', 'DG': 'G', 'DT': 'T', 'DI': 'I'}
                _rna_to_one = {'A': 'A', 'C': 'C', 'G': 'G', 'U': 'U', 'I': 'I'}
                _recon_map = _dna_to_one if entity_type == 'dna' else _rna_to_one
            else:
                _recon_map = {
                    'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F',
                    'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LYS': 'K', 'LEU': 'L',
                    'MET': 'M', 'ASN': 'N', 'PRO': 'P', 'GLN': 'Q', 'ARG': 'R',
                    'SER': 'S', 'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y',
                }
            # Invariant check only — do NOT overwrite the SEQRES-derived sequence with
            # observed atom residues. With label_seq_id-based mapping the position of
            # each atom is exact, so any disagreement here is either (a) a real
            # SEQRES/coordinate discrepancy that we must not silently "fix", or (b) an
            # altloc/microheterogeneity position where seq_pos_to_monomer captured the
            # first (possibly lower-occupancy) altloc. Overwriting previously propagated
            # BLASTP mis-placements into the sequence; now we only warn.
            _seq_list = list(final_sequence)
            _mismatches = []
            for pos, comp_id in seq_pos_to_monomer.items():
                if pos < 1 or pos > len(_seq_list):
                    continue
                actual_one = _recon_map.get(comp_id.upper())
                if actual_one is None:
                    continue  # non-standard residue, handled by modifications
                if _seq_list[pos - 1] != actual_one:
                    _mismatches.append((pos, _seq_list[pos - 1], actual_one, comp_id))
            if _mismatches:
                _preview = ", ".join(f"{p}:SEQRES={e}/atom={a}({c})"
                                     for p, e, a, c in _mismatches[:5])
                warning(f"SEQRES/atom mismatch at {len(_mismatches)} position(s) for "
                        f"chain {chain_id} (not overwriting): {_preview}")

            # Modifications for YAML: use _entity_poly_seq (same as generate_yaml.py) so ACE, PTR, DIP all appear
            # For synthetic chains (e.g. D-2) from assembly: try base chain ID first, then the
            # full chain_id (handles re-processed generated CIFs where synthetic chains are real entities).
            # positions from _entity_poly_seq / struct_conn / non_standard_residues are in
            # SEQRES coordinates, which is exactly the coordinate system of the full
            # (un-truncated) sequence kept here — no shift needed. --skip-terminal keeps
            # the full sequence and records a `trim` range instead; predict applies it.
            _mod_key = self._base_chain_id(chain_id)
            if _mod_key not in self._modifications_from_entity_poly and chain_id in self._modifications_from_entity_poly:
                _mod_key = chain_id
            seq_len_full = len(final_sequence)
            if _mod_key in self._modifications_from_entity_poly:
                chain_modifications = []
                for m in self._modifications_from_entity_poly[_mod_key]:
                    new_pos = m['position']
                    if not (1 <= new_pos <= seq_len_full):
                        continue
                    # Per-copy microheterogeneity guard: the entity's canonical residue may be
                    # modified (e.g. KCX) while THIS copy's deposited atoms are the plain parent
                    # (LYS) or carry a different comp (e.g. 1k55 chains A/B are KCX but C/D are LYS).
                    # Applying the entity modification would add atoms (the carboxyl) that are
                    # absent from this copy's template, so boltz generates and collapses them.
                    # When this position is resolved for this chain, trust the observed comp.
                    ccd = m['ccd']
                    actual = seq_pos_to_monomer.get(new_pos)
                    if actual is not None and actual != ccd:
                        if actual in STANDARD_AA_THREE_LETTER or actual in STANDARD_NUCLEOTIDE_CODES:
                            continue  # this copy is the plain parent residue -> no modification
                        ccd = actual  # this copy carries a different modification -> use it
                    elif actual is None and seq_pos_to_monomer:
                        # This chain resolves other positions but NOT this one. Entity-level
                        # modifications are entity-wide, so two copies that resolve different
                        # residue ranges (e.g. complementary DNA strands: chain B resolves
                        # 12-18, chain C resolves 4-11) each inherit the other's modifications.
                        # A modification at an unresolved position has no template atom to fix
                        # it, so boltz inpaints the modified residue freely and it collapses.
                        # Drop it — the position is inpainted as its plain sequence residue.
                        continue
                    chain_modifications.append({'position': new_pos, 'ccd': ccd, 'parent': None, 'parent_one': None})
            else:
                chain_modifications = []
            positions_added = {m['position'] for m in chain_modifications}
            # Merge modifications from _struct_conn (e.g. NH2 at B 7 when entity_poly_seq has UNK)
            _conn_key = self._base_chain_id(chain_id)
            if _conn_key not in getattr(self, '_modifications_from_struct_conn', {}) and chain_id in getattr(self, '_modifications_from_struct_conn', {}):
                _conn_key = chain_id
            if _conn_key in getattr(self, '_modifications_from_struct_conn', {}):
                for m in self._modifications_from_struct_conn[_conn_key]:
                    new_pos = m['position']
                    if 1 <= new_pos <= seq_len_full and new_pos not in positions_added:
                        chain_modifications.append({'position': new_pos, 'ccd': m['ccd'], 'parent': None, 'parent_one': None})
                        positions_added.add(new_pos)
            if _mod_key not in self._modifications_from_entity_poly:
                _ns_key = self._base_chain_id(chain_id)
                if _ns_key not in self.non_standard_residues and chain_id in self.non_standard_residues:
                    _ns_key = chain_id
                if _ns_key in self.non_standard_residues:
                    for seq_pos, ns_info in sorted(self.non_standard_residues[_ns_key].items()):
                        new_pos = seq_pos
                        if 1 <= new_pos <= seq_len_full and new_pos not in positions_added:
                            chain_modifications.append({
                                'position': new_pos, 'ccd': ns_info['ccd'],
                                'parent': ns_info['parent'], 'parent_one': ns_info['parent_one']
                            })
                            positions_added.add(new_pos)
                for pos, comp_id in sorted(seq_pos_to_monomer.items()):
                    # seq_pos_to_monomer already uses trimmed coords (from renumbered_atoms)
                    if comp_id not in STANDARD_AA_THREE_LETTER and comp_id not in STANDARD_NUCLEOTIDE_CODES and pos not in positions_added:
                        chain_modifications.append({'position': pos, 'ccd': comp_id, 'parent': None, 'parent_one': None})
                        positions_added.add(pos)
            # User-requested PTMs (--modification CHAIN:SEQID:CCD). SEQID is the
            # 1-based ENTITY (canonical) sequence position — the same numbering boltz
            # uses for `modifications.position` and the entity seq_id the studio sends.
            # --skip-terminal keeps the full sequence, so no coordinate shift is applied.
            #
            # CHAIN is resolved in the AUTHOR namespace: user_modifications is keyed by
            # the author chain id (what the viewer shows), so we match on the author id
            # of the chain being processed (author_chain_id), NOT the internal
            # label_asym_id. This is critical because label ids can collide with a
            # different chain's author id — e.g. 1DE9 label 'A' is a DNA chain while the
            # protein is author 'A' / label 'G'; matching by label would send the PTM to
            # the DNA chain and wrongly reject. Matching by author id works in both the
            # assembly path (all chains processed) and the normalize path. Synthetic
            # symmetry copies (e.g. label 'G-2') fall back to their base chain's author.
            _base_author = self.author_chain_ids.get(self._base_chain_id(chain_id))
            _umods = (self.user_modifications.get(author_chain_id)
                      or (self.user_modifications.get(_base_author) if _base_author else None)
                      or [])
            if _umods and entity_type != 'protein':
                fatal(f"--modification: chain {author_chain_id} is {str(entity_type).upper()}, "
                      f"not protein. PTMs are only supported on protein chains.")
            if _umods:
                for _um in _umods:
                    _seqid = int(_um['resid'])
                    _pos = _seqid
                    if not (1 <= _pos <= seq_len_full):
                        warning(f"--modification: chain {author_chain_id} seq_id {_seqid} "
                                f"is outside the modelled sequence (1..{seq_len_full}) — skipped")
                        continue
                    chain_modifications = [m for m in chain_modifications if m['position'] != _pos]
                    chain_modifications.append({'position': _pos, 'ccd': str(_um['ccd']).upper(),
                                                'parent': None, 'parent_one': None})
                    info(f"--modification: chain {author_chain_id} seq_id {_seqid} "
                         f"-> sequence position {_pos} -> {str(_um['ccd']).upper()}")
                positions_added = {m['position'] for m in chain_modifications}

            # Per-copy microheterogeneity safety net (covers every modification source, incl.
            # _struct_conn): if a position is RESOLVED for this chain as a plain standard residue
            # but a source applied an entity-level modification there (e.g. 1k55 chains A/B are KCX
            # while C/D are plain LYS), drop it — otherwise boltz builds the modified residue and
            # generates its extra atoms (the carboxyl), which are absent from this copy's template
            # and collapse. Unresolved positions (no atoms) keep the modification so they inpaint
            # as the right residue type.
            def _keep_mod(_m):
                _act = seq_pos_to_monomer.get(_m['position'])
                if _act is None or _act == _m['ccd']:
                    return True
                if _act in STANDARD_AA_THREE_LETTER or _act in STANDARD_NUCLEOTIDE_CODES:
                    return False
                return True
            chain_modifications = [_m for _m in chain_modifications if _keep_mod(_m)]

            chain_modifications.sort(key=lambda m: m['position'])

            # Enrich each modification with parent info (some sources omit it,
            # e.g. _modifications_from_entity_poly_seq → only {position, ccd}).
            _ccd_db = getattr(self, 'ccd', None)
            _ns_key = self._base_chain_id(chain_id)
            if _ns_key not in self.non_standard_residues and chain_id in self.non_standard_residues:
                _ns_key = chain_id
            _ns_chain = self.non_standard_residues.get(_ns_key, {})
            for _m in chain_modifications:
                if _m.get('parent') in STANDARD_RES_THREE_LETTER:
                    # Even if the parent was set by an earlier source, make sure
                    # parent_one is filled with the correct 1-letter code.
                    if not _m.get('parent_one'):
                        _m['parent_one'] = STANDARD_RES_ONE_LETTER.get(_m['parent'], 'X')
                    continue
                # (a) non_standard_residues keyed by untrimmed SEQRES position
                ns_info = _ns_chain.get(_m['position'])
                if ns_info and ns_info.get('parent') in STANDARD_RES_THREE_LETTER:
                    _m['parent'] = ns_info['parent']
                    _m['parent_one'] = ns_info.get('parent_one') or STANDARD_RES_ONE_LETTER.get(ns_info['parent'], 'X')
                    continue
                # (b) ccd.pkl fallback (resolves _chem_comp.mon_nstd_parent_comp_id)
                resolved = get_non_standard_parent_from_ccd(_ccd_db, _m.get('ccd', ''))
                if resolved:
                    _m['parent'], _m['parent_one'] = resolved
                    continue
                # (c) hardcoded common-modification table (covers cases where
                #     ccd.pkl was built without `mon_nstd_parent_comp_id` props).
                hard_parent = NONSTANDARD_TO_STANDARD.get(_m.get('ccd', '').upper())
                if hard_parent and hard_parent in STANDARD_RES_THREE_LETTER:
                    _m['parent'] = hard_parent
                    _m['parent_one'] = STANDARD_RES_ONE_LETTER[hard_parent]

            # Categorise each modification:
            #   1) standard AA / nucleotide  → keep as-is
            #   2) MSE                       → keep (Boltz hardcodes MSE→MET, SE→SD)
            #   3) CCD mol available         → keep
            #   4) CCD missing + parent OK   → drop from mods, rewrite atoms to parent
            #   5) CCD missing + no parent   → drop from mods, rewrite atoms to UNK
            # In all cases the atom coordinates are preserved (categories 4 and 5 may
            # drop atoms whose names are absent from the parent / UNK ref_atoms set).
            filtered_mods = []
            _rewrites: Dict[int, str] = {}  # position -> parent three-letter (or 'UNK')
            for _m in chain_modifications:
                ccd = _m.get('ccd', '')
                parent = _m.get('parent', '')
                if ccd in STANDARD_RES_THREE_LETTER:
                    filtered_mods.append(_m)
                elif ccd == 'MSE' or is_ccd_available(_ccd_db, ccd):
                    filtered_mods.append(_m)
                elif parent in STANDARD_RES_THREE_LETTER:
                    _rewrites[_m['position']] = parent
                    info(f"Chain {chain_id}: CCD '{ccd}' at position {_m['position']} "
                         f"unavailable in boltz mols; substituting atoms with parent '{parent}' "
                         f"(coordinates preserved)")
                else:
                    _rewrites[_m['position']] = 'UNK'
                    warning(f"Chain {chain_id}: CCD '{ccd}' at position {_m['position']} "
                            f"unavailable in boltz mols and no parent resolvable; "
                            f"labeling atoms as UNK (coordinates preserved)")
            chain_modifications = filtered_mods

            # Apply atom rewrites for parent / UNK substitutions.
            # Drop atoms whose names are not in the target residue's ref_atoms set
            # (e.g. SEP's PO3 group, MLY's CM1/CM2) so the template CIF stays valid
            # under boltz's per-residue ref_atoms filter (mmcif.py:660).
            if _rewrites:
                def _atom_seq_pos(a):
                    try:
                        return int(a.get('label_seq_id', -1))
                    except (ValueError, TypeError):
                        return -1
                _new_atoms = []
                for atom in renumbered_atoms:
                    pos = _atom_seq_pos(atom)
                    if pos in _rewrites:
                        new_comp = _rewrites[pos]
                        parent_ref = set(ref_atoms.get(new_comp, ref_atoms.get('UNK', [])))
                        atom_name = (atom.get('label_atom_id') or '').strip()
                        if atom_name in parent_ref:
                            atom['label_comp_id'] = new_comp
                            atom['auth_comp_id'] = new_comp
                            # Atom now belongs to a standard residue → normalise
                            # group_PDB to 'ATOM' (was 'HETATM' as the source
                            # non-standard residue). UNK fallback stays HETATM.
                            if new_comp != 'UNK':
                                atom['group_PDB'] = 'ATOM'
                            _new_atoms.append(atom)
                        # else: drop atom (not part of the target ref set)
                    else:
                        _new_atoms.append(atom)
                renumbered_atoms = _new_atoms

                # cif_writer (_entity_poly_seq, _chem_comp) reads monomer_ids first;
                # keep it consistent with the rewritten atoms or alignment will break.
                for pos, new_comp in _rewrites.items():
                    seq_pos_to_monomer[pos] = new_comp

                # Reflect rewrites in the sequence so YAML carries the parent one-letter
                # at category-4 positions (instead of the placeholder 'X').
                seq_list = list(final_sequence)
                for pos, new_comp in _rewrites.items():
                    if 1 <= pos <= len(seq_list):
                        seq_list[pos - 1] = STANDARD_RES_ONE_LETTER.get(new_comp, 'X')
                final_sequence = ''.join(seq_list)
            # The sequence now comes from RCSB's canonical field, which already carries
            # the correct one-letter code at every modified position (SEC->U, BRU->U,
            # PTR->Y, ...). We deliberately do NOT overwrite those with the parent code:
            # doing so diverged from _can/OF3 (e.g. SEC->C) and is unnecessary because
            # boltz replaces each modification position's token with the CCD from the
            # `modifications` list. Positions whose atoms were rewritten to a parent
            # residue (category 4/5, CCD unavailable) were already patched above via
            # `_rewrites`, so the sequence stays consistent with the emitted structure.
            output_sequence = final_sequence
            if chain_modifications:
                info(f"Chain {chain_id} has {len(chain_modifications)} modification(s):")
                for mod in chain_modifications:
                    parent = mod.get('parent') or '-'
                    detail(f"Position {mod['position']}: {mod['ccd']} (parent: {parent})")
            
            # Store chain data (include author chain ID for output files)
            author_chain_id = self.author_chain_ids.get(chain_id, chain_id)
            if '\\' in author_chain_id:
                warning(f"Chain {chain_id} has unsafe author chain ID {author_chain_id!r} "
                        f"(contains backslash), skipping")
                continue
            all_chains_data[chain_id] = {
                'atoms': renumbered_atoms,
                'sequence': output_sequence,
                'entity_id': entity_id,
                'uniprot_id': uniprot_id,
                'entity_type': entity_type,
                'monomer_ids': seq_pos_to_monomer,  # Actual 3-letter codes from atoms (e.g., 3DR)
                'author_chain_id': author_chain_id,  # Author chain ID for output files
                'modifications': chain_modifications,  # modifications for YAML output
                'inpainting_metadata': chain_inpainting_metadata,  # None for non-protein chains
                'trim': chain_trim,  # {kept_start, kept_end, full_length} or None (--skip-terminal)
            }
            
            entity_id += 1
        
        # Generate output files
        output_dir.mkdir(parents=True, exist_ok=True)

        # File naming: use only the PDB ID (e.g. 6AAW.cif / 6aaw.yaml).
        # Modifiers (--uniprot, --skip-terminal) are still reflected as suffixes
        # so separate runs don't overwrite each other.
        suffix = ""
        if self.uniprot_mode:
            suffix += "_uniprot"
        if self.skip_terminal:
            suffix += "_trimmed"
        cif_filename = f"{self.pdb_id}{suffix}.cif"
        ext = 'json' if self.output_format == 'protenix-json' else 'yaml'
        config_filename = f"{self.pdb_id.lower()}{suffix}.{ext}"

        cif_path = output_dir / cif_filename
        config_path = output_dir / config_filename

        # Optional: include solvent (water) atoms for full structure transfer.
        # When in assembly mode, solvent atoms were already collected above with
        # correct symmetry ops and chain IDs.  Fall back to raw CIF extraction
        # only for non-assembly runs.
        if assembly_solvent_atoms:
            solvent_atoms = assembly_solvent_atoms
        elif self.include_solvent:
            solvent_atoms = self._extract_solvent_atoms()
        else:
            solvent_atoms = None

        # Generate and save CIF
        cif_content = self.generate_cif(all_chains_data, solvent_atoms=solvent_atoms)
        with open(cif_path, 'w') as f:
            f.write(cif_content)
        success(f"Saved CIF file: {cif_path.absolute()}")

        # Save inpainting metadata JSON (per-chain, matching boltz2 format)
        # Must be saved before config so the path can be embedded in it.
        # Use label_asym_id as the key (matches CIF / YAML chain IDs) and
        # include a label→author mapping so downstream tools can recover
        # original author IDs.
        metadata_path = None
        inpainting_meta_by_chain = {}
        chain_mapping: Dict[str, str] = {}
        for cid, cdata in all_chains_data.items():
            meta = cdata.get('inpainting_metadata')
            if meta is not None:
                inpainting_meta_by_chain[cid] = meta
            chain_mapping[cid] = cdata.get('author_chain_id', cid)
        if inpainting_meta_by_chain:
            meta_filename = f"{self.pdb_id.lower()}{suffix}_inpainting_metadata.json"
            metadata_path = output_dir / meta_filename
            self.save_inpainting_metadata(
                inpainting_meta_by_chain, metadata_path, chain_mapping=chain_mapping
            )

        # Generate and save config (YAML or Protenix JSON)
        if self.output_format == 'protenix-json':
            config_content = self.generate_json(cif_path, output_dir, all_chains_data,
                                                inpainting_metadata_path=metadata_path,
                                                use_absolute_path=self.use_absolute_path)
            with open(config_path, 'w') as f:
                f.write(config_content)
            success(f"Saved Protenix JSON: {config_path.absolute()}")
        else:
            config_content = self.generate_yaml(cif_path, output_dir, all_chains_data,
                                                inpainting_metadata_path=metadata_path,
                                                use_absolute_path=self.use_absolute_path)
            with open(config_path, 'w') as f:
                f.write(config_content)
            success(f"Saved YAML file: {config_path.absolute()}")

        section("Processing complete!")


