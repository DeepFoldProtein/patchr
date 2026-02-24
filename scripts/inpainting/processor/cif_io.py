"""CIF file I/O: load and cache the parsed mmCIF dictionary."""
import os
import sys
from io import StringIO
from typing import Dict, Optional
from pathlib import Path

import requests
from Bio.PDB.MMCIF2Dict import MMCIF2Dict


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
        """Load CIF file from local file or download from RCSB PDB."""
        if self.is_local_file:
            # Load from local file
            if not self.cif_file_path:
                print(f"ERROR: Local file path not specified", file=sys.stderr)
                sys.exit(1)
            
            if not os.path.exists(self.cif_file_path):
                print(f"ERROR: File not found: {self.cif_file_path}", file=sys.stderr)
                sys.exit(1)
            
            print(f"Loading CIF file from local path: {self.cif_file_path}")
            try:
                with open(self.cif_file_path, 'r') as f:
                    self.cif_content = f.read()
                self._cif_dict = None  # invalidate cache when content changes
                print(f"Successfully loaded {os.path.basename(self.cif_file_path)}")
                return self.cif_content
            except Exception as e:
                print(f"ERROR: Failed to read CIF file: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Download from RCSB PDB
            url = f"https://files.rcsb.org/download/{self.pdb_id}.cif"
            print(f"Downloading CIF file from {url}")
            
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                self.cif_content = response.text
                self._cif_dict = None  # invalidate cache when content changes
                print(f"Successfully downloaded {self.pdb_id}.cif")
                return self.cif_content
            except requests.exceptions.RequestException as e:
                print(f"ERROR: Failed to download CIF file: {e}", file=sys.stderr)
                sys.exit(1)
    
