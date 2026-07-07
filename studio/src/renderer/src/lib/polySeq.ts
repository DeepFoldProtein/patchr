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

// One position of the full polymer sequence (present or missing coordinates).
export interface PolySeqPosition {
  code: string; // one-letter
  resName: string; // three-letter mon_id
  authSeqId?: number; // author residue number (pdb_seq_num); absent if unknown
  insCode: string;
  seqId: number; // entity seq_id (_entity_poly_seq.num)
}

export interface ChainPolySeq {
  authChainId: string;
  monIds: string[]; // three-letter component ids, ordered by seq_id
  oneLetter: string;
  /** Full ordered sequence, including residues missing from the structure. */
  positions: PolySeqPosition[];
  /** "authSeqNum|insCode" -> 0-based index into monIds/oneLetter. */
  keyToIndex: Map<string, number>;
  /** "authSeqNum|insCode" -> entity seq_id (1-based, _entity_poly_seq.num). */
  keyToSeqId: Map<string, number>;
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
  // Prefer pdb_seq_num: it carries the author number even for residues missing
  // from the structure (auth_seq_num is "?" for those).
  const authNumCol =
    cols["pdb_seq_num"] ?? cols["auth_seq_num"] ?? cols["ndb_seq_num"];
  const insCol = cols["pdb_ins_code"];
  const seqIdCol = cols["seq_id"];
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
        positions: [],
        keyToIndex: new Map(),
        keyToSeqId: new Map()
      };
      result.set(chain, entry);
    }

    const index = entry.monIds.length;
    entry.monIds.push(mon);

    const ins = insCol !== undefined ? normalizeIns(row[insCol]) : "";
    const authRaw = authNumCol !== undefined ? row[authNumCol] : undefined;
    const authSeqId =
      authRaw && authRaw !== "?" && authRaw !== "."
        ? parseInt(authRaw, 10)
        : undefined;
    const seqIdRaw = seqIdCol !== undefined ? row[seqIdCol] : undefined;
    const seqId = seqIdRaw ? parseInt(seqIdRaw, 10) : index + 1;

    entry.positions.push({
      code: monToOne(mon),
      resName: mon,
      authSeqId: Number.isFinite(authSeqId) ? authSeqId : undefined,
      insCode: ins,
      seqId: Number.isFinite(seqId) ? seqId : index + 1
    });

    if (authSeqId !== undefined && Number.isFinite(authSeqId)) {
      const key = `${authSeqId}|${ins}`;
      entry.keyToIndex.set(key, index);
      entry.keyToSeqId.set(key, Number.isFinite(seqId) ? seqId : index + 1);
    }
  }

  for (const entry of result.values()) {
    entry.oneLetter = entry.monIds.map(monToOne).join("");
  }

  return result;
}
