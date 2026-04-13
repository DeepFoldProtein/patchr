"""CIF file I/O: load and cache the parsed mmCIF dictionary."""
import os
from io import StringIO
from typing import Dict, Optional
from pathlib import Path

import requests
from Bio.PDB.MMCIF2Dict import MMCIF2Dict

from .log import info, warning, success, fatal


def _convert_pdb_to_cif(pdb_content: str) -> str:
    """Convert PDB format content to mmCIF format using gemmi.

    Args:
        pdb_content: PDB format string

    Returns:
        mmCIF format string
    """
    import gemmi
    structure = gemmi.read_pdb_string(pdb_content)
    structure.setup_entities()
    structure.assign_label_seq_id()
    doc = structure.make_mmcif_document()
    return doc.as_string()


def _is_pdb_format(content: str) -> bool:
    """Detect if content is in PDB format (not mmCIF)."""
    trimmed = content.lstrip()
    if trimmed.startswith("data_") or trimmed.startswith("_"):
        return False
    if trimmed.startswith("HEADER") or trimmed.startswith("ATOM") or trimmed.startswith("HETATM"):
        return True
    # Check first few lines for PDB record types
    for line in trimmed.split("\n", 10):
        if line[:6].rstrip() in ("HEADER", "TITLE", "COMPND", "SOURCE", "KEYWDS",
                                  "EXPDTA", "AUTHOR", "REMARK", "SEQRES",
                                  "ATOM", "HETATM", "MODEL", "CRYST1"):
            return True
    return False


class CifIOMixin:
    def _get_cif_dict(self) -> Dict:
        """Parse CIF content once and cache; reused by all chain-level methods."""
        if self._cif_dict is None and self.cif_content:
            try:
                self._cif_dict = MMCIF2Dict(StringIO(self.cif_content))
            except Exception:
                self._cif_dict = {}
        return self._cif_dict or {}

    def load_cif(self) -> str:
        """Load CIF file from local file or download from RCSB PDB.

        If the input file is in PDB format, it is automatically converted
        to mmCIF using gemmi so that all downstream processing works uniformly.
        """
        if self.is_local_file:
            # Load from local file
            if not self.cif_file_path:
                fatal("Local file path not specified")

            if not os.path.exists(self.cif_file_path):
                fatal(f"File not found: {self.cif_file_path}")

            info(f"Loading structure file from local path: {self.cif_file_path}")
            try:
                with open(self.cif_file_path, 'r') as f:
                    content = f.read()

                # Auto-detect PDB format and convert to mmCIF
                if _is_pdb_format(content):
                    info("Detected PDB format; converting to mmCIF via gemmi...")
                    content = _convert_pdb_to_cif(content)
                    success("PDB → mmCIF conversion successful")

                self.cif_content = content
                self._cif_dict = None  # invalidate cache when content changes
                success(f"Successfully loaded {os.path.basename(self.cif_file_path)}")
                return self.cif_content
            except Exception as e:
                fatal(f"Failed to read structure file: {e}")
        else:
            # Download from RCSB PDB
            url = f"https://files.rcsb.org/download/{self.pdb_id}.cif"
            info(f"Downloading CIF file from {url}")

            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                self.cif_content = response.text
                self._cif_dict = None  # invalidate cache when content changes
                success(f"Successfully downloaded {self.pdb_id}.cif")
                return self.cif_content
            except requests.exceptions.RequestException as e:
                fatal(f"Failed to download CIF file: {e}")
