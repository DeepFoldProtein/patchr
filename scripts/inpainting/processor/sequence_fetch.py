"""External sequence data: UniProt / SIFTS, interactive / CLI input."""
from typing import Dict, List, Optional

import requests

from .log import info, debug, warning, error, section, detail, fatal


class SequenceFetchMixin:
    def prompt_manual_sequence(self, chain_id: str, entity_type: str, suggested_sequence: str = "") -> Optional[str]:
        """Prompt user to enter sequence manually for a chain."""
        section(f"Manual Sequence Input for Chain: {chain_id}")

        if suggested_sequence:
            info(f"Suggested sequence (from structure/SEQRES, length: {len(suggested_sequence)}):")
            # Show first 80 characters
            if len(suggested_sequence) > 80:
                detail(f"{suggested_sequence[:80]}...")
            else:
                detail(f"{suggested_sequence}")

        if entity_type == 'protein':
            info("Enter protein sequence (one-letter amino acid codes: A, C, D, E, F, G, H, I, K, L, M, N, P, Q, R, S, T, V, W, Y)")
        elif entity_type == 'dna':
            info("Enter DNA sequence (one-letter codes: A, C, G, T)")
        elif entity_type == 'rna':
            info("Enter RNA sequence (one-letter codes: A, C, G, U)")
        else:
            info(f"Enter {entity_type} sequence")

        info("(Press Enter without input to use suggested sequence, or 'skip' to skip this chain)")

        while True:
            user_input = input(f"Sequence for chain {chain_id}: ").strip()

            if not user_input:
                # Empty input - use suggested sequence
                if suggested_sequence:
                    info(f"Using suggested sequence (length: {len(suggested_sequence)})")
                    return suggested_sequence
                else:
                    error("No sequence provided and no suggested sequence available")
                    continue

            if user_input.lower() == 'skip':
                return None

            # Validate sequence
            if entity_type == 'protein':
                valid_chars = set('ACDEFGHIKLMNPQRSTVWYX*')
                invalid_chars = set(user_input.upper()) - valid_chars
                if invalid_chars:
                    warning(f"Invalid characters found: {invalid_chars}")
                    info("Protein sequences should only contain: A, C, D, E, F, G, H, I, K, L, M, N, P, Q, R, S, T, V, W, Y, X (unknown), * (stop)")
                    retry = input("Continue anyway? (y/n): ").strip().lower()
                    if retry != 'y':
                        continue
            elif entity_type == 'dna':
                valid_chars = set('ACGTN')
                invalid_chars = set(user_input.upper()) - valid_chars
                if invalid_chars:
                    warning(f"Invalid characters found: {invalid_chars}")
                    info("DNA sequences should only contain: A, C, G, T, N (unknown)")
                    retry = input("Continue anyway? (y/n): ").strip().lower()
                    if retry != 'y':
                        continue
            elif entity_type == 'rna':
                valid_chars = set('ACGUN')
                invalid_chars = set(user_input.upper()) - valid_chars
                if invalid_chars:
                    warning(f"Invalid characters found: {invalid_chars}")
                    info("RNA sequences should only contain: A, C, G, U, N (unknown)")
                    retry = input("Continue anyway? (y/n): ").strip().lower()
                    if retry != 'y':
                        continue

            # Convert to uppercase
            sequence = user_input.upper()
            info(f"Accepted sequence (length: {len(sequence)})")
            return sequence


    def get_uniprot_id_from_pdb(self, chain_id: str) -> Optional[str]:
        """Get UniProt ID from PDB using SIFTS API.

        Note: SIFTS API uses author chain IDs (auth_asym_id), not label chain IDs.
        This method converts label chain ID to author chain ID if needed.
        """
        if self.is_local_file:
            warning(f"Cannot fetch UniProt mapping for local file. Skipping UniProt lookup for chain {chain_id}")
            return None

        # Convert label chain ID to author chain ID for SIFTS API
        # SIFTS API uses author chain IDs (what users see in PDB viewers)
        author_chain_id = chain_id
        if hasattr(self, 'label_to_auth') and self.label_to_auth:
            if chain_id.upper() in self.label_to_auth:
                author_chain_id = self.label_to_auth[chain_id.upper()]
                debug(f"Converting label chain ID '{chain_id}' to author chain ID '{author_chain_id}' for SIFTS API")

        url = f"https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{self.pdb_id}"
        info(f"Fetching UniProt mapping from SIFTS: {url}")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Navigate through the JSON structure
            if self.pdb_id.lower() in data:
                pdb_data = data[self.pdb_id.lower()]
                for uniprot_id, uniprot_data in pdb_data['UniProt'].items():
                    for mapping in uniprot_data['mappings']:
                        # SIFTS API uses author chain IDs
                        if mapping['chain_id'] == author_chain_id:
                            info(f"Found UniProt ID: {uniprot_id} for chain {chain_id} (author: {author_chain_id})")
                            return uniprot_id

            warning(f"No UniProt mapping found for chain {chain_id} (author: {author_chain_id})")
            return None
        except Exception as e:
            error(f"Failed to get UniProt ID: {e}")
            return None

    def fetch_uniprot_sequence(self, uniprot_id: str) -> str:
        """Fetch sequence from UniProt."""
        url = f"https://www.uniprot.org/uniprot/{uniprot_id}.fasta"
        info(f"Fetching UniProt sequence from {url}")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            fasta = response.text

            # Parse FASTA format
            lines = fasta.strip().split('\n')
            sequence = ''.join(lines[1:])  # Skip header
            info(f"Retrieved UniProt sequence (length: {len(sequence)})")
            return sequence
        except requests.exceptions.RequestException as e:
            fatal(f"Failed to fetch UniProt sequence: {e}")
