#!/usr/bin/env python3
"""
Extract FASTA sequences from CIF files using Biopython.
"""

import os
import sys

from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord


def extract_fasta_from_cif(cif_file_path, output_fasta_path=None):
    """
    Extract FASTA sequences from a CIF file using _entity_poly_seq.

    Args:
        cif_file_path (str): Path to the CIF file.
        output_fasta_path (str, optional): Path to save the FASTA file. If None, prints to stdout.

    Returns:
        None
    """
    # Parse the CIF file as dictionary
    data = MMCIF2Dict(cif_file_path)

    sequences = []

    # Get entity poly data
    entity_ids = data.get("_entity_poly.entity_id", [])
    seqs = data.get("_entity_poly.pdbx_seq_one_letter_code_can", [])
    types = data.get("_entity_poly.type", [])

    for i, entity_id in enumerate(entity_ids):
        seq = seqs[i] if i < len(seqs) else ""
        seq_type = types[i] if i < len(types) else ""
        if seq and seq_type == "polypeptide(L)":  # Only polypeptides
            record = SeqRecord(
                Seq(seq),
                id=f"{os.path.basename(cif_file_path).replace('.cif', '')}_entity_{entity_id}",
                description=f"Entity {entity_id} polypeptide from {cif_file_path}",
            )
            sequences.append(record)

    # Write to FASTA file or stdout without line breaks in sequence
    if output_fasta_path:
        with open(output_fasta_path, "w") as f:
            for record in sequences:
                f.write(f">{record.id} {record.description}\n")
                f.write(str(record.seq) + "\n")
        print(f"FASTA sequences saved to {output_fasta_path}")
    else:
        for record in sequences:
            sys.stdout.write(f">{record.id} {record.description}\n")
            sys.stdout.write(str(record.seq) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_fasta_from_cif.py <cif_file> [output_fasta]")
        sys.exit(1)

    cif_file = sys.argv[1]
    output_fasta = sys.argv[2] if len(sys.argv) > 2 else None

    extract_fasta_from_cif(cif_file, output_fasta)
