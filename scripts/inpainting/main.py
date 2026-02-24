"""
CLI entry point for inpainting template generation.
"""

import re
import sys
from pathlib import Path

from .structure_processor import StructureProcessor


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate YAML and template CIF files for inpainting',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single chain without UniProt (use SEQRES)
  python generate_inpainting_template.py 7EOQ A

  # Single chain with UniProt
  python generate_inpainting_template.py 7EOQ A --uniprot

  # Multimeric (multiple chains)
  python generate_inpainting_template.py 1CK4 A,B

  # All polymer chains (one per entity, excludes duplicate copies)
  python generate_inpainting_template.py 1CK4 all

  # All polymer chains including duplicate copies
  python generate_inpainting_template.py 1CK4 all-copies

  # Multimeric with UniProt
  python generate_inpainting_template.py 1CK4 A,B --uniprot

  # All chains with UniProt
  python generate_inpainting_template.py 1CK4 all --uniprot

  # Specify output directory
  python generate_inpainting_template.py 1CK4 A,B --uniprot -o output/

  # Use local CIF file
  python generate_inpainting_template.py --input structure.cif A

  # Use local CIF file with all chains
  python generate_inpainting_template.py --input structure.cif all

  # Interactive sequence input (prompts for each chain)
  python generate_inpainting_template.py 7EOQ A --interactive

  # Custom sequence via CLI (single chain)
  python generate_inpainting_template.py 7EOQ A --sequence ACDEFGHIKLMNPQRSTVWY

  # Custom sequences for multiple chains
  python generate_inpainting_template.py 1CK4 A,B --sequence A:ACDEFG,B:MNOPQR

  # Custom sequence with local file
  python generate_inpainting_template.py --input structure.cif A --sequence ACDEFGHIKLMNPQRSTVWY

  # Skip terminal missing residues (only inpaint internal gaps)
  python generate_inpainting_template.py 7EOQ A --skip-terminal

  # Skip terminal + UniProt sequence
  python generate_inpainting_template.py 7EOQ A --uniprot --skip-terminal
        """
    )

    parser.add_argument('pdb_id', nargs='?', help='PDB ID (e.g., 7EOQ) or local CIF file path')
    parser.add_argument('chain_ids', nargs='?', help='Chain ID(s) (e.g., A or A,B for multimeric)')
    parser.add_argument('--input', '--file', '-i', '-f', type=str,
                        help='Local CIF file path (alternative to pdb_id)')
    parser.add_argument('--uniprot', action='store_true',
                        help='Use UniProt sequence instead of SEQRES (not available for local files)')
    parser.add_argument('--interactive', '--manual-sequence', action='store_true',
                        help='Prompt for manual sequence input for each chain')
    parser.add_argument('--sequence', '--seq', '-s', type=str,
                        help='Custom sequence(s). For single chain: "ACDEFG...". For multiple: "A:ACDEFG,B:MNOPQR"')
    parser.add_argument('-o', '--output', '--out_dir', type=Path,
                        default=Path('examples/inpainting'),
                        help='Output directory (default: examples/inpainting)')
    parser.add_argument('--cache', type=Path, default=None,
                        help='Boltz cache directory for ccd.pkl (default: BOLTZ_CACHE or ~/.boltz)')
    parser.add_argument('--include-solvent', action='store_true',
                        help='Include water/solvent atoms in output CIF for full structure transfer')
    parser.add_argument('--exclude-ligands', action='store_true',
                        help='Do not include non-polymer (ligand) chains in YAML and template (default: include ligands)')
    parser.add_argument('--assembly', '--bio-assembly', type=str, default=None,
                        metavar='ID',
                        help='Biological assembly to use. "best" auto-selects the first '
                             'author_and_software_defined assembly. Integer N selects assembly N. '
                             'If omitted, uses manually-provided chain IDs or ALL (current behaviour).')
    parser.add_argument('--list-assemblies', action='store_true',
                        help='List available biological assemblies and exit without processing.')
    parser.add_argument('--skip-terminal', action='store_true',
                        help='Skip terminal missing residues: trim the sequence to span only from the first '
                             'residue with structure to the last, so N/C-terminal disordered tails are '
                             'excluded from inpainting and only internal (non-terminal) gaps are inpainted.')

    args = parser.parse_args()

    custom_sequences = {}
    if args.sequence:
        print(f"DEBUG: Parsing --sequence argument: {args.sequence}")
        if ':' in args.sequence:
            for chain_seq in args.sequence.split(','):
                chain_seq = chain_seq.strip()
                if ':' in chain_seq:
                    chain_id, seq = chain_seq.split(':', 1)
                    chain_id = chain_id.strip().upper()
                    chain_id = re.sub(r'\s*\[(?:DNA|RNA|PROTEIN)\]\s*', '', chain_id).strip()
                    seq = seq.strip()
                    custom_sequences[chain_id] = seq
                    print(f"DEBUG: Parsed custom sequence: chain_id='{chain_id}', seq_length={len(seq)}, seq_preview={seq[:20]}...")
                else:
                    parser.error(f"Invalid sequence format: {chain_seq}. Expected format: CHAIN:SEQUENCE")
        else:
            custom_sequences['_default_'] = args.sequence.strip()
        print(f"DEBUG: Final custom_sequences dict: {list(custom_sequences.keys())}")

    # Determine assembly_id: if no chain_ids given anywhere, default to best assembly
    assembly_id = args.assembly

    if args.input:
        if args.pdb_id and not args.chain_ids:
            chain_ids = args.pdb_id
            cif_file_path = args.input
            pdb_id = Path(cif_file_path).stem
        elif args.chain_ids:
            chain_ids = args.chain_ids
            cif_file_path = args.input
            pdb_id = Path(cif_file_path).stem
        else:
            parser.error("chain_ids is required when using --input option. Usage: --input file.cif CHAIN_ID")
    elif args.pdb_id:
        # If pdb_id looks like a file path (ends with .cif / .pdb / exists on disk), treat as local file
        pdb_path = Path(args.pdb_id)
        if pdb_path.suffix.lower() in ('.cif', '.pdb') or pdb_path.exists():
            cif_file_path = str(pdb_path)
            pdb_id = pdb_path.stem
            if args.chain_ids:
                chain_ids = args.chain_ids
            else:
                # No chain IDs given → use assembly 1 by default.
                # Intentionally '1' (not 'best') so behaviour is predictable and reproducible.
                chain_ids = 'ALL'
                if assembly_id is None and not args.list_assemblies:
                    assembly_id = '1'
        else:
            cif_file_path = None
            pdb_id = args.pdb_id
            if args.chain_ids:
                chain_ids = args.chain_ids
            else:
                # No chain IDs given → use assembly 1 by default.
                # Intentionally '1' (not 'best') so behaviour is predictable and reproducible.
                chain_ids = 'ALL'
                if assembly_id is None and not args.list_assemblies:
                    assembly_id = '1'
    else:
        parser.error("Either pdb_id or --input option must be provided")

    processor = StructureProcessor(
        pdb_id=pdb_id,
        chain_ids=chain_ids,
        uniprot_mode=args.uniprot,
        cif_file_path=cif_file_path,
        interactive_sequence=args.interactive,
        custom_sequences=custom_sequences,
        cache_dir=args.cache,
        include_solvent=args.include_solvent,
        include_ligands=not args.exclude_ligands,
        assembly_id=assembly_id,
        list_assemblies=args.list_assemblies,
        skip_terminal=args.skip_terminal,
    )
    processor.process(args.output)


if __name__ == '__main__':
    main()
    sys.exit(0)
