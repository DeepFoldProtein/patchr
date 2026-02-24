"""
Inpainting template generation: CIF/YAML generation and structure processing.

Entry point: run from scripts/ as
  python generate_inpainting_template.py <pdb_id> <chain_id> [options]
or
  python -m inpainting.main
"""

from .structure_processor import StructureProcessor
from .main import main

__all__ = ['StructureProcessor', 'main']
