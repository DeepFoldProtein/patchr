// Estimates the model token count of the loaded structure, matching how the
// backend tokenizes: protein residues are one token each, while nucleic acids
// (DNA/RNA) and ligands are tokenized per atom. Water is ignored. This is used
// to pre-warn in the GUI when a structure exceeds what the default server can
// handle.

import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import {
  StructureElement,
  StructureProperties,
  Unit
} from "molstar/lib/mol-model/structure";

// Standard + common modified amino acids (residue-level tokens).
const AMINO_ACIDS = new Set([
  "ALA",
  "ARG",
  "ASN",
  "ASP",
  "CYS",
  "GLN",
  "GLU",
  "GLY",
  "HIS",
  "ILE",
  "LEU",
  "LYS",
  "MET",
  "PHE",
  "PRO",
  "SER",
  "THR",
  "TRP",
  "TYR",
  "VAL",
  "MSE",
  "SEP",
  "TPO",
  "PTR",
  "HYP",
  "CSO",
  "KCX",
  "MLY",
  "M3L",
  "ALY",
  "SAC",
  "CAS",
  "PCA",
  "UNK"
]);

const WATER = new Set(["HOH", "WAT", "DOD", "H2O"]);

export interface TokenCount {
  total: number;
  proteinResidues: number; // one token each
  atomTokens: number; // nucleic + ligand atoms
}

/**
 * Count tokens for the first loaded structure. Returns zeros when no structure
 * is present.
 */
export function countStructureTokens(
  plugin: PluginUIContext | null
): TokenCount {
  const empty: TokenCount = { total: 0, proteinResidues: 0, atomTokens: 0 };
  if (!plugin) return empty;

  const structures = plugin.managers.structure.hierarchy.current.structures;
  const structure = structures?.[0]?.cell.obj?.data;
  if (!structure) return empty;

  const proteinResidues = new Set<string>();
  let atomTokens = 0;

  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;
    const loc = StructureElement.Location.create(structure, unit);

    for (let i = 0; i < unit.elements.length; i++) {
      loc.element = unit.elements[i];
      const comp = StructureProperties.atom.label_comp_id(loc).toUpperCase();
      if (WATER.has(comp)) continue;

      if (AMINO_ACIDS.has(comp)) {
        const chainId = StructureProperties.chain.auth_asym_id(loc);
        const authSeqId = StructureProperties.residue.auth_seq_id(loc);
        const insCode =
          StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";
        proteinResidues.add(`${chainId}|${authSeqId}|${insCode}`);
      } else {
        // Nucleic acid or ligand atom → one token per atom.
        atomTokens++;
      }
    }
  }

  return {
    total: proteinResidues.size + atomTokens,
    proteinResidues: proteinResidues.size,
    atomTokens
  };
}
