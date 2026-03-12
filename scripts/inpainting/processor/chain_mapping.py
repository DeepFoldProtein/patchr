"""Chain ID mapping: auth_asym_id ↔ label_asym_id normalisation."""
from typing import Dict, List, Optional, Tuple

from .log import info, debug, warning, error, detail


class ChainMappingMixin:
    def build_auth_to_label_chain_mapping(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Build a mapping from auth_asym_id to label_asym_id and vice versa.
        
        In mmCIF files:
        - label_asym_id: internal chain IDs (A, B, C, D, E, F, G, H, I, J)
        - auth_asym_id: author chain IDs (X, Y, Z, A, B, etc.) - what users see in PDB viewers
        
        Returns:
            Tuple of (auth_to_label, label_to_auth) mappings
        """
        if not self.cif_content:
            raise ValueError("CIF content not loaded")
        
        try:
            cif_dict = self._get_cif_dict()
            
            auth_to_label = {}
            label_to_auth = {}
            
            # Build mapping from _atom_site records
            if '_atom_site.label_asym_id' in cif_dict and '_atom_site.auth_asym_id' in cif_dict:
                label_asym_ids = cif_dict['_atom_site.label_asym_id']
                auth_asym_ids = cif_dict['_atom_site.auth_asym_id']
                
                for label_id, auth_id in zip(label_asym_ids, auth_asym_ids):
                    # Store mapping (preserve original case, but use uppercase for lookup)
                    auth_upper = auth_id.upper()
                    label_upper = label_id.upper()
                    # Store with uppercase key for case-insensitive lookup, but preserve original values
                    if auth_upper not in auth_to_label:
                        auth_to_label[auth_upper] = label_id  # Preserve original case
                    if label_upper not in label_to_auth:
                        label_to_auth[label_upper] = auth_id  # Preserve original case
            
            return auth_to_label, label_to_auth
        except Exception as e:
            warning(f"Failed to build chain ID mapping: {e}")
            return {}, {}
    
    def normalize_chain_ids(self) -> None:
        """Normalize chain IDs to use label_asym_id (internal CIF IDs).
        
        Users may provide either auth_asym_id (author chain IDs like X, Y, Z) 
        or label_asym_id (internal IDs like A, B, C). This method converts 
        everything to label_asym_id for consistent processing.
        
        For 1DE9 example:
        - Author chain X -> label chain A (DNA entity 1)
        - Author chain Y -> label chain B (DNA entity 2 with 3DR)
        - Author chain Z -> label chain C (DNA entity 3)
        - Author chain A -> label chain G (Protein entity 4)
        """
        if not self.cif_content:
            raise ValueError("CIF content not loaded")
        
        # Skip if ALL or ALL-COPIES is specified (will be resolved later)
        if 'ALL' in self.chain_ids or 'ALL-COPIES' in self.chain_ids:
            return
        
        auth_to_label, label_to_auth = self.build_auth_to_label_chain_mapping()
        
        if not auth_to_label:
            return  # No mapping available, proceed as-is
        
        # Store mappings for reference
        self.auth_to_label = auth_to_label
        self.label_to_auth = label_to_auth
        
        # Get available label_asym_ids from struct_asym
        try:
            cif_dict = self._get_cif_dict()
            available_label_ids = set()
            if '_struct_asym.id' in cif_dict:
                asym_ids = cif_dict['_struct_asym.id']
                if isinstance(asym_ids, str):
                    asym_ids = [asym_ids]
                available_label_ids = set(aid.upper() for aid in asym_ids)
        except Exception:
            available_label_ids = set(label_to_auth.keys())
        
        # Determine if user is providing author chain IDs or label chain IDs
        # If ANY of the provided chain IDs exist in auth_to_label mapping, treat ALL as author IDs
        # This handles cases like 1DE9 where author 'A' -> label 'G', but 'A' also exists as label
        using_author_ids = any(c.upper() in auth_to_label for c in self.chain_ids)
        
        if using_author_ids:
            info("Treating chain IDs as author chain IDs (from PDB viewer)")
        
        # Normalize each chain ID (preserve case in output)
        normalized_chain_ids = []
        chain_id_mapping = {}  # original -> normalized
        
        for chain_id in self.chain_ids:
            chain_upper = chain_id.upper()
            
            # Priority 1: If using author IDs, always try to convert from auth_to_label first
            if using_author_ids and chain_upper in auth_to_label:
                label_id = auth_to_label[chain_upper]  # Already preserves original case
                normalized_chain_ids.append(label_id)
                chain_id_mapping[chain_id] = label_id
                # Store author chain ID for output files (preserve original case)
                self.author_chain_ids[label_id] = chain_id  # Use original case
                detail(f"{chain_id} (author) -> {label_id} (internal)")
            # Priority 2: Check if it's a valid label_asym_id
            elif chain_upper in available_label_ids:
                # Find the actual label_id with original case from CIF
                actual_label_id = None
                try:
                    cif_dict = self._get_cif_dict()
                    if '_struct_asym.id' in cif_dict:
                        asym_ids = cif_dict['_struct_asym.id']
                        if isinstance(asym_ids, str):
                            asym_ids = [asym_ids]
                        for aid in asym_ids:
                            if aid.upper() == chain_upper:
                                actual_label_id = aid  # Preserve original case
                                break
                except:
                    pass
                if actual_label_id is None:
                    actual_label_id = chain_id  # Fallback to original
                normalized_chain_ids.append(actual_label_id)
                chain_id_mapping[chain_id] = actual_label_id
                # If label ID, try to find corresponding author ID
                if chain_upper in label_to_auth:
                    self.author_chain_ids[actual_label_id] = label_to_auth[chain_upper]  # Preserve original case
                else:
                    # No mapping, use label ID as author ID
                    self.author_chain_ids[actual_label_id] = chain_id  # Preserve original case
            # Priority 3: Try auth_to_label conversion (for mixed input)
            elif chain_upper in auth_to_label:
                label_id = auth_to_label[chain_upper]  # Already preserves original case
                normalized_chain_ids.append(label_id)
                chain_id_mapping[chain_id] = label_id
                # Store author chain ID for output files (preserve original case)
                self.author_chain_ids[label_id] = chain_id  # Use original case
                info(f"Converting author chain ID '{chain_id}' to internal chain ID '{label_id}'")
            else:
                # Unknown chain ID, keep as-is (will fail later with proper error)
                normalized_chain_ids.append(chain_id)  # Preserve original case
                chain_id_mapping[chain_id] = chain_id
                # No mapping, use as-is for both
                self.author_chain_ids[chain_id] = chain_id  # Preserve original case
                warning(f"Unknown chain ID '{chain_id}', keeping as-is")
        
        # Update chain_ids
        self.chain_ids = normalized_chain_ids
        
        # Update manual_sequences keys if needed
        debug(f"Before mapping - manual_sequences keys: {list(self.manual_sequences.keys())}")
        debug(f"chain_id_mapping: {chain_id_mapping}")
        
        updated_sequences = {}
        for orig_chain, seq in self.manual_sequences.items():
            if orig_chain in chain_id_mapping:
                mapped_chain = chain_id_mapping[orig_chain]
                updated_sequences[mapped_chain] = seq
                debug(f"Mapped custom sequence: {orig_chain} -> {mapped_chain} (seq_length={len(seq)})")
            elif orig_chain.upper() in chain_id_mapping.values():
                updated_sequences[orig_chain.upper()] = seq
                debug(f"Kept custom sequence: {orig_chain} (already normalized, seq_length={len(seq)})")
            elif orig_chain == '_default_':
                updated_sequences[orig_chain] = seq
                debug(f"Kept default sequence (seq_length={len(seq)})")
            else:
                # Try to normalize this chain ID too
                orig_upper = orig_chain.upper()
                if orig_upper in auth_to_label:
                    mapped_chain = auth_to_label[orig_upper]
                    updated_sequences[mapped_chain] = seq
                    debug(f"Mapped custom sequence (auth->label): {orig_upper} -> {mapped_chain} (seq_length={len(seq)})")
                else:
                    updated_sequences[orig_upper] = seq
                    debug(f"Kept custom sequence (no mapping found): {orig_upper} (seq_length={len(seq)})")
        
        self.manual_sequences = updated_sequences
        debug(f"After mapping - manual_sequences keys: {list(self.manual_sequences.keys())}")
    

    @staticmethod
    def _base_chain_id(chain_id: str) -> str:
        """Return the original label_asym_id for synthetic chains created by symmetry ops.

        Synthetic chain IDs have the form "<original>-<N>" or "<original>-<N>-<M>"
        (e.g. "A-2", "A-12-60"). For regular chains the input is returned unchanged.
        """
        if '-' not in chain_id:
            return chain_id
        parts = chain_id.split('-')
        # All parts after the first must be numeric operator IDs
        if all(p.isdigit() for p in parts[1:]):
            return parts[0]
        return chain_id

