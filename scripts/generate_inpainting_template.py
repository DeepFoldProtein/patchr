#!/usr/bin/env python3
"""
Generate YAML and template CIF files for inpainting.

This script downloads a PDB structure, extracts a specific chain,
renumbers residues starting from 1, and generates the necessary
YAML and CIF template files for inpainting.

Usage:
    python generate_inpainting_template.py <pdb_id> <chain_id> [--uniprot]

Implementation is in the scripts.inpainting package (scripts/inpainting/).
"""

import sys
from pathlib import Path

# Ensure scripts/ is on path so that inpainting can import benchmark.generate_yaml
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from inpainting.main import main

if __name__ == '__main__':
    main()
