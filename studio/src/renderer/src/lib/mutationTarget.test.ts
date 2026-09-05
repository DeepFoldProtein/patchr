import { describe, expect, it } from "vitest";
import { parsePolySeqScheme, type ChainPolySeq } from "./polySeq";
import type { UniProtRef } from "./structRef";
import {
  authorAtTargetIndex,
  keptRange,
  presentTargetPositions,
  resultResidueNumber,
  targetIndexOf,
  targetLength,
  toResultSites,
  usesUniProtTarget
} from "./mutationTarget";

// Build a `_pdbx_poly_seq_scheme` loop from (mon, pdb_seq_num, ins, resolved)
// rows so the fixture goes through the real parser (and its resolved flag).
interface Row {
  mon: string;
  num: number;
  ins?: string;
  resolved?: boolean;
}
function polySeqCif(chain: string, rows: Row[]): string {
  const lines = [
    "data_test",
    "loop_",
    "_pdbx_poly_seq_scheme.asym_id",
    "_pdbx_poly_seq_scheme.entity_id",
    "_pdbx_poly_seq_scheme.seq_id",
    "_pdbx_poly_seq_scheme.mon_id",
    "_pdbx_poly_seq_scheme.ndb_seq_num",
    "_pdbx_poly_seq_scheme.pdb_seq_num",
    "_pdbx_poly_seq_scheme.auth_seq_num",
    "_pdbx_poly_seq_scheme.pdb_mon_id",
    "_pdbx_poly_seq_scheme.auth_mon_id",
    "_pdbx_poly_seq_scheme.pdb_strand_id",
    "_pdbx_poly_seq_scheme.pdb_ins_code",
    "_pdbx_poly_seq_scheme.hetero"
  ];
  rows.forEach((r, i) => {
    const resolved = r.resolved ?? true;
    const ins = r.ins || ".";
    lines.push(
      `${chain} 1 ${i + 1} ${r.mon} ${i + 1} ${r.num} ${resolved ? r.num : "?"} ${
        resolved ? r.mon : "?"
      } ${resolved ? r.mon : "?"} ${chain} ${ins} n`
    );
  });
  lines.push("#");
  return lines.join("\n");
}

function chain(rows: Row[], id = "A"): ChainPolySeq {
  const parsed = parsePolySeqScheme(polySeqCif(id, rows)).get(id);
  if (!parsed) throw new Error("fixture did not parse");
  return parsed;
}

// Author numbering 16..24 with an insertion (19A) and a numbering jump (21→23).
const OFFSET_INS_GAP: Row[] = [
  { mon: "ILE", num: 16 },
  { mon: "VAL", num: 17 },
  { mon: "GLY", num: 18 },
  { mon: "GLY", num: 19 },
  { mon: "TYR", num: 19, ins: "A" },
  { mon: "LYS", num: 20 },
  { mon: "CYS", num: 21 },
  { mon: "GLU", num: 23 },
  { mon: "LYS", num: 24 }
];

describe("polySeq resolved flag", () => {
  it("marks rows with auth_seq_num '?' as unresolved", () => {
    const c = chain([
      { mon: "MET", num: 1, resolved: false },
      { mon: "ALA", num: 2 },
      { mon: "GLY", num: 3, resolved: false }
    ]);
    expect(c.positions.map(p => p.resolved)).toEqual([false, true, false]);
    // Unresolved rows still carry the author number (from pdb_seq_num).
    expect(c.positions.map(p => p.authSeqId)).toEqual([1, 2, 3]);
  });
});

describe("targetIndexOf (SEQRES target)", () => {
  const ctx = { polySeq: chain(OFFSET_INS_GAP) };

  it("maps an author offset to the 1-based SEQRES position", () => {
    expect(targetIndexOf(16, "", ctx)).toBe(1);
    expect(targetIndexOf(17, "", ctx)).toBe(2);
  });

  it("distinguishes insertion-coded residues", () => {
    expect(targetIndexOf(19, "", ctx)).toBe(4);
    expect(targetIndexOf(19, "A", ctx)).toBe(5);
    expect(targetIndexOf(20, "", ctx)).toBe(6);
  });

  it("follows author numbering jumps", () => {
    expect(targetIndexOf(21, "", ctx)).toBe(7);
    expect(targetIndexOf(22, "", ctx)).toBeUndefined();
    expect(targetIndexOf(23, "", ctx)).toBe(8);
    expect(targetIndexOf(24, "", ctx)).toBe(9);
  });

  it("is undefined for unknown residues or a missing scheme", () => {
    expect(targetIndexOf(99, "", ctx)).toBeUndefined();
    expect(targetIndexOf(16, "", {})).toBeUndefined();
  });

  it("reports the target length", () => {
    expect(targetLength(ctx)).toBe(9);
    expect(targetLength({})).toBeUndefined();
  });
});

describe("targetIndexOf (UniProt target)", () => {
  // SEQRES 1..6 (authors 10, 11, 11A, 12, 14, 15) aligns to UniProt 101..106
  // of a 200-aa reference.
  const rows: Row[] = [
    { mon: "ALA", num: 10 },
    { mon: "ALA", num: 11 },
    { mon: "ALA", num: 11, ins: "A" },
    { mon: "ALA", num: 12 },
    { mon: "ALA", num: 14 },
    { mon: "ALA", num: 15 }
  ];
  const uniprotRef: UniProtRef = {
    accession: "P00000",
    dbBeg: 101,
    dbEnd: 106,
    authBeg: 10,
    authEnd: 15,
    seqBeg: 1,
    seqEnd: 6
  };
  const reference = "M".repeat(200);
  const ctx = { polySeq: chain(rows), uniprotRef, reference };

  it("uses the reference when one is loaded and aligned", () => {
    expect(usesUniProtTarget(ctx)).toBe(true);
    expect(targetLength(ctx)).toBe(200);
    expect(targetIndexOf(10, "", ctx)).toBe(101);
    expect(targetIndexOf(15, "", ctx)).toBe(106);
  });

  it("follows SEQRES order across insertion codes and numbering jumps", () => {
    expect(targetIndexOf(11, "", ctx)).toBe(102);
    expect(targetIndexOf(11, "A", ctx)).toBe(103);
    expect(targetIndexOf(12, "", ctx)).toBe(104);
    expect(targetIndexOf(13, "", ctx)).toBeUndefined();
    expect(targetIndexOf(14, "", ctx)).toBe(105);
  });

  it("inverts back to the author residue", () => {
    expect(authorAtTargetIndex(103, ctx)).toEqual({
      authSeqId: 11,
      insCode: "A",
      seqId: 3
    });
    expect(authorAtTargetIndex(105, ctx)).toMatchObject({ authSeqId: 14 });
    // Reference positions the structure does not cover have no author residue.
    expect(authorAtTargetIndex(100, ctx)).toBeUndefined();
    expect(authorAtTargetIndex(107, ctx)).toBeUndefined();
  });

  it("anchors on a SEQRES offset other than 1", () => {
    // Structure SEQRES starts 3 residues before the aligned region.
    const shifted = {
      ...ctx,
      uniprotRef: { ...uniprotRef, seqBeg: 4, dbBeg: 50, dbEnd: 52 }
    };
    expect(targetIndexOf(10, "", shifted)).toBe(47);
    expect(targetIndexOf(12, "", shifted)).toBe(50);
    expect(authorAtTargetIndex(50, shifted)).toMatchObject({ authSeqId: 12 });
  });

  it("falls back to contiguous author numbering without a SEQRES anchor", () => {
    const noAnchor = {
      ...ctx,
      uniprotRef: { ...uniprotRef, seqBeg: undefined, seqEnd: undefined }
    };
    expect(targetIndexOf(10, "", noAnchor)).toBe(101);
    expect(targetIndexOf(14, "", noAnchor)).toBe(105);
    expect(targetIndexOf(11, "A", noAnchor)).toBeUndefined();
    expect(authorAtTargetIndex(102, noAnchor)).toEqual({
      authSeqId: 11,
      insCode: "",
      seqId: 2
    });
    expect(authorAtTargetIndex(100, noAnchor)).toBeUndefined();
  });

  it("rejects positions outside the reference", () => {
    const longRef = {
      ...ctx,
      uniprotRef: { ...uniprotRef, dbBeg: 199, dbEnd: 204, seqBeg: 1 }
    };
    expect(targetIndexOf(10, "", longRef)).toBe(199);
    expect(targetIndexOf(11, "", longRef)).toBe(200);
    expect(targetIndexOf(11, "A", longRef)).toBeUndefined();
  });

  it("falls back to SEQRES without an alignment or with an empty reference", () => {
    expect(targetIndexOf(10, "", { ...ctx, uniprotRef: undefined })).toBe(1);
    expect(targetIndexOf(10, "", { ...ctx, reference: "" })).toBe(1);
    expect(authorAtTargetIndex(3, { ...ctx, reference: "" })).toEqual({
      authSeqId: 11,
      insCode: "A",
      seqId: 3
    });
  });
});

describe("kept range and result numbering under skip-terminal", () => {
  // 10 positions; 1-2 and 10 unresolved (terminal gaps), 6 unresolved (internal).
  const rows: Row[] = [
    { mon: "MET", num: 1, resolved: false },
    { mon: "SER", num: 2, resolved: false },
    { mon: "ALA", num: 3 },
    { mon: "GLY", num: 4 },
    { mon: "LEU", num: 5 },
    { mon: "LYS", num: 6, resolved: false },
    { mon: "PHE", num: 7 },
    { mon: "TRP", num: 8 },
    { mon: "TYR", num: 9 },
    { mon: "HIS", num: 10, resolved: false }
  ];
  const base = { polySeq: chain(rows) };

  it("lists present positions from resolved, non-erased, non-mutated residues", () => {
    expect(presentTargetPositions(base)).toEqual([3, 4, 5, 7, 8, 9]);
    expect(
      presentTargetPositions({ ...base, erasedKeys: new Set(["3|", "4|"]) })
    ).toEqual([5, 7, 8, 9]);
    expect(
      presentTargetPositions({ ...base, mutatedKeys: new Set(["9|"]) })
    ).toEqual([3, 4, 5, 7, 8]);
    expect(presentTargetPositions({})).toBeNull();
  });

  it("derives the kept range from the first and last present position", () => {
    expect(keptRange(base)).toEqual({ start: 3, end: 9 });
    expect(keptRange({ ...base, erasedKeys: new Set(["3|"]) })).toEqual({
      start: 4,
      end: 9
    });
    expect(keptRange({ ...base, mutatedKeys: new Set(["9|", "8|"]) })).toEqual({
      start: 3,
      end: 7
    });
    expect(keptRange({})).toBeNull();
  });

  it("keeps canonical numbering when skip-terminal is off", () => {
    expect(resultResidueNumber(3, "", base, false)).toBe(3);
    expect(resultResidueNumber(7, "", base, false)).toBe(7);
    expect(resultResidueNumber(1, "", base, false)).toBe(1);
  });

  it("shifts by kept_start - 1 when skip-terminal is on", () => {
    expect(resultResidueNumber(3, "", base, true)).toBe(1);
    expect(resultResidueNumber(7, "", base, true)).toBe(5);
    // Internal gap residues are kept and renumbered too.
    expect(resultResidueNumber(6, "", base, true)).toBe(4);
  });

  it("drops residues the trim removes", () => {
    expect(resultResidueNumber(1, "", base, true)).toBeUndefined();
    expect(resultResidueNumber(2, "", base, true)).toBeUndefined();
    expect(resultResidueNumber(10, "", base, true)).toBeUndefined();
  });

  it("applies the trim without a shift when nothing is trimmed", () => {
    const full = { polySeq: chain(rows.map(r => ({ ...r, resolved: true }))) };
    expect(keptRange(full)).toEqual({ start: 1, end: 10 });
    expect(resultResidueNumber(10, "", full, true)).toBe(10);
  });

  it("leaves numbering untouched when the present set is unknown", () => {
    // No resolved information at all (e.g. no poly_seq_scheme): no trim applied.
    expect(resultResidueNumber(3, "", {}, true)).toBeUndefined();
  });
});

describe("toResultSites", () => {
  const rows: Row[] = [
    { mon: "MET", num: 1, resolved: false },
    { mon: "SER", num: 2 },
    { mon: "ALA", num: 3 },
    { mon: "GLY", num: 4 },
    { mon: "LEU", num: 5 }
  ];
  const contextFor = (): { polySeq: ChainPolySeq } => ({
    polySeq: chain(rows)
  });

  it("converts each mutation to its result residue number", () => {
    const sites = toResultSites(
      [
        { chainId: "A", authSeqId: 3, insCode: "" },
        { chainId: "A", authSeqId: 5, insCode: "" }
      ],
      contextFor,
      false
    );
    expect(sites).toEqual([
      { chainId: "A", resNum: 3 },
      { chainId: "A", resNum: 5 }
    ]);
  });

  it("treats the mutated residues themselves as absent for the kept range", () => {
    // Mutating the first resolved residue (2) moves kept_start to 3, exactly as
    // the backend strips a mismatched residue before computing the trim.
    const sites = toResultSites(
      [
        { chainId: "A", authSeqId: 2, insCode: "" },
        { chainId: "A", authSeqId: 4, insCode: "" }
      ],
      contextFor,
      true
    );
    expect(sites).toEqual([{ chainId: "A", resNum: 2 }]);
  });

  it("drops mutations with no place in the result", () => {
    const sites = toResultSites(
      [
        { chainId: "A", authSeqId: 42, insCode: "" },
        { chainId: "B", authSeqId: 3, insCode: "" }
      ],
      id => (id === "A" ? contextFor() : {}),
      false
    );
    expect(sites).toEqual([]);
  });
});
