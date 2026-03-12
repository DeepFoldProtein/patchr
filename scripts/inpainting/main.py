"""
CLI entry point for inpainting template generation.
"""

import re
import sys
from pathlib import Path

import rich_click as click

from .structure_processor import StructureProcessor

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
click.rich_click.STYLE_ERRORS_SUGGESTION = "bold italic"
click.rich_click.ERRORS_SUGGESTION = "Try the '--help' flag for more information."
click.rich_click.OPTION_GROUPS = {
    "main": [
        {
            "name": "Input",
            "options": ["pdb_id", "chain_ids", "--input"],
        },
        {
            "name": "Sequence",
            "options": ["--uniprot", "--sequence", "--interactive"],
        },
        {
            "name": "Assembly",
            "options": ["--assembly", "--list-assemblies"],
        },
        {
            "name": "Output",
            "options": ["--output", "--format", "--skip-terminal",
                        "--include-solvent", "--exclude-ligands"],
        },
        {
            "name": "Other",
            "options": ["--cache", "--verbose", "--help"],
        },
    ],
}


@click.command(
    "main",
    epilog="""
[bold]Examples:[/bold]

  [dim]# Single chain[/dim]
  python -m inpainting.main 7EOQ A

  [dim]# Multiple chains with UniProt[/dim]
  python -m inpainting.main 1CK4 A,B --uniprot

  [dim]# All polymer chains[/dim]
  python -m inpainting.main 1CK4 all

  [dim]# All polymer chains including duplicate copies[/dim]
  python -m inpainting.main 1CK4 all-copies

  [dim]# Biological assembly[/dim]
  python -m inpainting.main 4ZLO --assembly best

  [dim]# Local CIF file[/dim]
  python -m inpainting.main --input structure.cif A,B

  [dim]# Custom sequences[/dim]
  python -m inpainting.main 1CK4 A,B --sequence A:ACDEFG,B:MNOPQR

  [dim]# Skip terminal missing residues[/dim]
  python -m inpainting.main 7EOQ A --skip-terminal
""",
)
@click.argument("pdb_id", required=False, default=None)
@click.argument("chain_ids", required=False, default=None)
@click.option(
    "--input", "-i", "-f", "input_file", type=click.Path(exists=True), default=None,
    help="Local CIF file path (alternative to PDB_ID).",
)
@click.option(
    "--uniprot", is_flag=True,
    help="Use UniProt sequence instead of SEQRES.",
)
@click.option(
    "--interactive", is_flag=True,
    help="Prompt for manual sequence input for each chain.",
)
@click.option(
    "--sequence", "-s", type=str, default=None,
    help='Custom sequence(s). Single: "ACDEFG". Multiple: "A:ACDEFG,B:MNOPQR".',
)
@click.option(
    "-o", "--output", "out_dir", type=click.Path(), default="examples/inpainting",
    help="Output directory.",
)
@click.option(
    "--cache", type=click.Path(), default=None,
    help="Boltz cache directory for ccd.pkl.",
)
@click.option(
    "--include-solvent", is_flag=True,
    help="Include water/solvent atoms in output CIF.",
)
@click.option(
    "--exclude-ligands", is_flag=True,
    help="Exclude non-polymer (ligand) chains from output.",
)
@click.option(
    "--assembly", type=str, default=None, metavar="ID",
    help='Biological assembly ID or "best" for auto-selection.',
)
@click.option(
    "--list-assemblies", is_flag=True,
    help="List available biological assemblies and exit.",
)
@click.option(
    "--skip-terminal", is_flag=True,
    help="Skip terminal missing residues (only inpaint internal gaps).",
)
@click.option(
    "--verbose", "-v", is_flag=True,
    help="Print detailed inpainting region analysis.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["yaml", "protenix-json"]),
    default="yaml",
    help="Output format.",
)
def main(
    pdb_id,
    chain_ids,
    input_file,
    uniprot,
    interactive,
    sequence,
    out_dir,
    cache,
    include_solvent,
    exclude_ligands,
    assembly,
    list_assemblies,
    skip_terminal,
    verbose,
    output_format,
) -> None:
    """Generate YAML and template CIF files for inpainting."""

    # Parse custom sequences
    custom_sequences = {}
    if sequence:
        if ':' in sequence:
            for pair in sequence.split(','):
                pair = pair.strip()
                if ':' in pair:
                    chain, seq = pair.split(':', 1)
                    chain = chain.strip().upper()
                    chain = re.sub(r'\s*\[(?:DNA|RNA|PROTEIN)\]\s*', '', chain).strip()
                    custom_sequences[chain] = seq.strip()
                else:
                    raise click.BadParameter(
                        f"Invalid format: {pair}. Expected CHAIN:SEQUENCE.",
                        param_hint="'--sequence'",
                    )
        else:
            custom_sequences['_default_'] = sequence.strip()

    # Resolve input source
    assembly_id = assembly
    cif_file_path = None

    if input_file:
        cif_file_path = input_file
        resolved_pdb_id = Path(input_file).stem
        resolved_chain_ids = pdb_id if (pdb_id and not chain_ids) else chain_ids
        if not resolved_chain_ids:
            raise click.UsageError("CHAIN_IDS required when using --input.")
    elif pdb_id:
        pdb_path = Path(pdb_id)
        if pdb_path.suffix.lower() in ('.cif', '.pdb') or pdb_path.exists():
            cif_file_path = str(pdb_path)
            resolved_pdb_id = pdb_path.stem
            resolved_chain_ids = chain_ids or 'ALL'
            if assembly_id is None and not list_assemblies:
                assembly_id = '1'
        else:
            cif_file_path = None
            resolved_pdb_id = pdb_id
            resolved_chain_ids = chain_ids or 'ALL'
            if not chain_ids and assembly_id is None and not list_assemblies:
                assembly_id = '1'
    else:
        raise click.UsageError("Provide PDB_ID or --input.")

    processor = StructureProcessor(
        pdb_id=resolved_pdb_id,
        chain_ids=resolved_chain_ids,
        uniprot_mode=uniprot,
        cif_file_path=cif_file_path,
        interactive_sequence=interactive,
        custom_sequences=custom_sequences,
        cache_dir=cache,
        include_solvent=include_solvent,
        include_ligands=not exclude_ligands,
        assembly_id=assembly_id,
        list_assemblies=list_assemblies,
        skip_terminal=skip_terminal,
        verbose=verbose,
        output_format=output_format,
    )
    processor.process(Path(out_dir))


if __name__ == '__main__':
    main()
    sys.exit(0)
