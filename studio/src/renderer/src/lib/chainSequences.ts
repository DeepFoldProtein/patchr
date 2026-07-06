// Extracts resolved, author-numbered per-chain sequences from the loaded Mol*
// structure. This is the data source for the Sequence editor tab, where the
// user selects residues to erase/regenerate or mutate. Only residues that have
// coordinates are returned — unresolved gaps are simply absent, which mirrors
// how the inpainting backend re-detects missing regions from the CIF.

import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import {
  StructureElement,
  StructureProperties,
  Unit
} from "molstar/lib/mol-model/structure";

export interface ResidueCell {
  /** Author residue number (auth_seq_id). */
  authSeqId: number;
  /** PDB insertion code, or "" when absent. */
  insCode: string;
  /** Three-letter component id (label_comp_id), e.g. "ALA", "DA". */
  resName: string;
  /** One-letter code, or "X" (protein) / "N" (nucleic) when unknown. */
  code: string;
}

export interface ChainSequence {
  /** Author chain id (auth_asym_id). */
  authChainId: string;
  /** Whether the chain is nucleic acid (affects one-letter fallbacks). */
  isNucleic: boolean;
  residues: ResidueCell[];
}

const AA_3_TO_1: Record<string, string> = {
  ALA: "A",
  ARG: "R",
  ASN: "N",
  ASP: "D",
  CYS: "C",
  GLN: "Q",
  GLU: "E",
  GLY: "G",
  HIS: "H",
  ILE: "I",
  LEU: "L",
  LYS: "K",
  MET: "M",
  PHE: "F",
  PRO: "P",
  SER: "S",
  THR: "T",
  TRP: "W",
  TYR: "Y",
  VAL: "V",
  // common non-standard / modified residues mapped to their parent code
  MSE: "M",
  SEP: "S",
  TPO: "T",
  PTR: "Y",
  HYP: "P",
  CSO: "C",
  KCX: "K",
  MLY: "K",
  M3L: "K",
  ALY: "K",
  SAC: "S",
  CAS: "C"
};

const NUC_TO_1: Record<string, string> = {
  DA: "A",
  DC: "C",
  DG: "G",
  DT: "T",
  DU: "U",
  DI: "I",
  A: "A",
  C: "C",
  G: "G",
  U: "U",
  I: "I",
  N: "N"
};

function isNucleicResName(name: string): boolean {
  return Object.prototype.hasOwnProperty.call(NUC_TO_1, name);
}

function oneLetter(resName: string, nucleic: boolean): string {
  const n = resName.toUpperCase();
  if (nucleic) return NUC_TO_1[n] ?? "N";
  return AA_3_TO_1[n] ?? "X";
}

/**
 * Read resolved per-chain sequences from the first loaded structure.
 * Returns an empty array when no structure is present.
 */
export function getChainSequences(
  plugin: PluginUIContext | null
): ChainSequence[] {
  if (!plugin) return [];

  const structures = plugin.managers.structure.hierarchy.current.structures;
  const structure = structures?.[0]?.cell.obj?.data;
  if (!structure) return [];

  // chainId -> ordered residues, deduped by (authSeqId, insCode)
  const chainMap = new Map<
    string,
    { residues: ResidueCell[]; seen: Set<string>; nucleicVotes: number }
  >();

  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;

    const loc = StructureElement.Location.create(structure, unit);

    for (let i = 0; i < unit.elements.length; i++) {
      loc.element = unit.elements[i];

      const chainId = StructureProperties.chain.auth_asym_id(loc);
      const authSeqId = StructureProperties.residue.auth_seq_id(loc);
      const insCode = StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";
      const resName = StructureProperties.atom.label_comp_id(loc);

      let entry = chainMap.get(chainId);
      if (!entry) {
        entry = { residues: [], seen: new Set(), nucleicVotes: 0 };
        chainMap.set(chainId, entry);
      }

      const key = `${authSeqId}|${insCode}`;
      if (entry.seen.has(key)) continue;
      entry.seen.add(key);

      const nucleic = isNucleicResName(resName.toUpperCase());
      if (nucleic) entry.nucleicVotes++;

      entry.residues.push({
        authSeqId,
        insCode,
        resName,
        // one-letter resolved after we know the chain's dominant type
        code: ""
      });
    }
  }

  const result: ChainSequence[] = [];
  for (const [authChainId, entry] of chainMap.entries()) {
    entry.residues.sort((a, b) => {
      if (a.authSeqId !== b.authSeqId) return a.authSeqId - b.authSeqId;
      return a.insCode.localeCompare(b.insCode);
    });
    const isNucleic = entry.nucleicVotes > entry.residues.length / 2;
    for (const r of entry.residues) {
      r.code = oneLetter(r.resName, isNucleic);
    }
    result.push({ authChainId, isNucleic, residues: entry.residues });
  }

  result.sort((a, b) => a.authChainId.localeCompare(b.authChainId));
  return result;
}
