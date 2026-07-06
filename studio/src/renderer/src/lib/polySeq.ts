// Parses the mmCIF `_pdbx_poly_seq_scheme` loop, which is the authoritative
// per-chain polymer sequence: it lists every entity position (seq_id) with its
// residue identity (mon_id) AND the author numbering (auth_seq_num + ins code).
// This lets the Sequence editor build a full, gap-aware target sequence and map
// a selected author residue to its position for mutation via the custom-sequence
// upload path (the backend's intended residue-substitution mechanism).

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

const NUC_1: Record<string, string> = {
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

function monToOne(mon: string): string {
  const m = mon.toUpperCase();
  return AA_3_TO_1[m] ?? NUC_1[m] ?? "X";
}

export interface ChainPolySeq {
  authChainId: string;
  monIds: string[]; // three-letter component ids, ordered by seq_id
  oneLetter: string;
  /** "authSeqNum|insCode" -> 0-based index into monIds/oneLetter. */
  keyToIndex: Map<string, number>;
}

function normalizeIns(ins: string | undefined): string {
  if (!ins || ins === "." || ins === "?") return "";
  return ins;
}

// Tokenize a whitespace-delimited CIF row honoring single/double quotes.
function tokenize(line: string): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === " " || ch === "\t") {
      i++;
      continue;
    }
    if (ch === "'" || ch === '"') {
      const end = line.indexOf(ch, i + 1);
      if (end === -1) {
        out.push(line.slice(i + 1));
        break;
      }
      out.push(line.slice(i + 1, end));
      i = end + 1;
      continue;
    }
    let j = i;
    while (j < line.length && line[j] !== " " && line[j] !== "\t") j++;
    out.push(line.slice(i, j));
    i = j;
  }
  return out;
}

/**
 * Parse `_pdbx_poly_seq_scheme` into per-author-chain sequences. Returns an
 * empty map when the category is absent (e.g. a minimal or PDB-format file).
 */
export function parsePolySeqScheme(
  content: string | null | undefined
): Map<string, ChainPolySeq> {
  const result = new Map<string, ChainPolySeq>();
  if (!content) return result;

  const lines = content.split("\n");
  const headers: string[] = [];
  let inHeader = false;
  let inData = false;
  let cols: Record<string, number> = {};

  const rows: string[][] = [];

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();

    if (trimmed.startsWith("_pdbx_poly_seq_scheme.")) {
      inHeader = true;
      headers.push(trimmed.replace("_pdbx_poly_seq_scheme.", ""));
      continue;
    }

    if (inHeader && !trimmed.startsWith("_pdbx_poly_seq_scheme.")) {
      // Header block finished.
      inHeader = false;
      cols = {};
      headers.forEach((h, idx) => (cols[h] = idx));
      inData = true;
      // fall through to process this first data line
    }

    if (inData) {
      if (
        !trimmed ||
        trimmed.startsWith("#") ||
        trimmed.startsWith("loop_") ||
        trimmed.startsWith("_")
      ) {
        break; // end of this loop
      }
      rows.push(tokenize(trimmed));
    }
  }

  if (rows.length === 0) return result;

  const strandCol = cols["pdb_strand_id"] ?? cols["asym_id"];
  const monCol = cols["mon_id"];
  const authNumCol =
    cols["auth_seq_num"] ?? cols["pdb_seq_num"] ?? cols["ndb_seq_num"];
  const insCol = cols["pdb_ins_code"];
  if (strandCol === undefined || monCol === undefined) return result;

  for (const row of rows) {
    const chain = row[strandCol];
    const mon = row[monCol];
    if (!chain || !mon) continue;

    let entry = result.get(chain);
    if (!entry) {
      entry = {
        authChainId: chain,
        monIds: [],
        oneLetter: "",
        keyToIndex: new Map()
      };
      result.set(chain, entry);
    }

    const index = entry.monIds.length;
    entry.monIds.push(mon);

    if (authNumCol !== undefined) {
      const authNum = row[authNumCol];
      const ins = insCol !== undefined ? normalizeIns(row[insCol]) : "";
      if (authNum && authNum !== "?" && authNum !== ".") {
        entry.keyToIndex.set(`${authNum}|${ins}`, index);
      }
    }
  }

  for (const entry of result.values()) {
    entry.oneLetter = entry.monIds.map(monToOne).join("");
  }

  return result;
}
