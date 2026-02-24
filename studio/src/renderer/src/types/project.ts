// Re-export types from preload for renderer usage
export interface ProjectInfo {
  path: string;
  name: string;
  yamlPath: string;
  structuresPath: string;
  mappingsPath: string;
  resultsPath: string;
}

export interface ResidueMapping {
  chain_mapping: {
    [authorChainId: string]: {
      author_id: string;
      canonical_id: string;
    };
  };
  residue_mappings: {
    [chainId: string]: {
      [authorResId: string]: {
        canonical_index: number;
        author_id: string | null;
        generated_id?: string; // "I1", "I2", ...
        type?: "complete_missing" | "partial" | "sidechain_rebuild";
        insertion_code?: string;
      };
    };
  };
}

export interface InpaintingYAML {
  version: number;
  metadata: {
    original_pdb: string;
    created: string;
    modified: string;
  };
  sequences: Array<{
    protein: {
      id: string; // Canonical chain ID
      author_chain_id: string;
      full_sequence: string;
      residue_mapping_ref: string; // Reference to mapping file
      msa: "empty" | string;
    };
  }>;
  inpainting: Array<{
    input_cif: string; // Path to canonical CIF
    chain_id: string;
    residue_ranges: Array<{
      start: number;
      end: number;
      type: "complete_missing" | "partial" | "sidechain_rebuild";
      author_id_range: [number, number] | null;
      generated_ids?: string[];
    }>;
    context?: {
      include_neighbors: boolean;
      radius_Ang: number;
      soft_shell_Ang?: number;
    };
  }>;
}
