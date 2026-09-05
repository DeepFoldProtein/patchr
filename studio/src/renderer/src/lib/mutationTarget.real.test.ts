// Cross-checks the author -> result numbering against what the patchr backend
// actually produced for the bundled mock structures. The expected values come
// from running `scripts/generate_inpainting_template.py --skip-terminal` on
// each CIF (see the comments per case); the backend renumbers results by the
// target sequence, so those numbers are what the result CIF carries.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parsePolySeqScheme } from "./polySeq";
import { parseUniProtRefs } from "./structRef";
import {
  authorAtTargetIndex,
  keptRange,
  presentTargetPositions,
  resultResidueNumber,
  targetIndexOf,
  toResultSites,
  type ChainTargetContext
} from "./mutationTarget";

function loadMock(name: string): string {
  return readFileSync(
    fileURLToPath(new URL(`../../public/mock/${name}`, import.meta.url)),
    "utf8"
  );
}

function ctxFor(cif: string, chainId: string): ChainTargetContext {
  return { polySeq: parsePolySeqScheme(cif).get(chainId) };
}

function unresolvedPositions(ctx: ChainTargetContext): number[] {
  return ctx.polySeq!.positions.filter(p => !p.resolved).map(p => p.seqId);
}

function range(a: number, b: number): number[] {
  return Array.from({ length: b - a + 1 }, (_, i) => a + i);
}

describe("1TON chain A (chymotrypsinogen numbering: offset + insertion codes)", () => {
  // Backend run with the SEQRES mutated at positions 1 (I→A) and 60 (F→W):
  //   trim: kept_start 2, kept_end 235
  //   fully_inpainted_residues: 60, 80-86   (60 = the mutated residue)
  //   template CIF atoms: label_seq_id 2..235, residue 60 absent
  const cif = loadMock("1TON.cif");
  const ctx = ctxFor(cif, "A");

  it("maps author residues to SEQRES positions", () => {
    expect(targetIndexOf(16, "", ctx)).toBe(1); // first residue, author 16
    expect(targetIndexOf(79, "A", ctx)).toBe(60); // insertion-coded residue
    expect(targetIndexOf(79, "", ctx)).toBe(59);
    expect(targetIndexOf(95, "E", ctx)).toBe(81);
    expect(targetIndexOf(246, "", ctx)).toBe(235); // last residue
  });

  it("finds the internal gap the backend inpaints", () => {
    expect(unresolvedPositions(ctx)).toEqual(range(80, 86));
  });

  it("reproduces the backend's kept range once mutations are excluded", () => {
    const mutations = [
      { chainId: "A", authSeqId: 16, insCode: "" },
      { chainId: "A", authSeqId: 79, insCode: "A" }
    ];
    const withMut = { ...ctx, mutatedKeys: new Set(["16|", "79|A"]) };
    expect(keptRange(ctx)).toEqual({ start: 1, end: 235 });
    expect(keptRange(withMut)).toEqual({ start: 2, end: 235 });

    // Result numbering: residue 60 of the target becomes 59 after the trim;
    // the mutated N-terminal residue is trimmed away and cannot be painted.
    expect(toResultSites(mutations, () => ctx, true)).toEqual([
      { chainId: "A", resNum: 59 }
    ]);
    // Without skip-terminal the result keeps full canonical numbering.
    expect(toResultSites(mutations, () => ctx, false)).toEqual([
      { chainId: "A", resNum: 1 },
      { chainId: "A", resNum: 60 }
    ]);
  });

  it("would have painted the wrong residue with author numbers", () => {
    // The old code painted auth_seq_id 79 in the result, which is target
    // position 79 (author 95C) — not the mutated 79A at position 60.
    expect(targetIndexOf(95, "C", ctx)).toBe(79);
  });
});

describe("1TON chain A with the UniProt reference (P00759) as target", () => {
  // Backend run with the full UniProt sequence (259 aa) as custom sequence,
  // mutated at UniProt position 84 (the SEQRES position 60 / author 79A):
  //   Matches 227, Mismatches 1 ; trim: kept_start 25, kept_end 259
  //   fully_inpainted_residues: 84, 104-110 ; partially fixed: 103
  const cif = loadMock("1TON.cif");
  const uniprotRef = parseUniProtRefs(cif).get("A");
  const ctx: ChainTargetContext = {
    polySeq: parsePolySeqScheme(cif).get("A"),
    uniprotRef,
    reference: "X".repeat(259)
  };

  it("reads the alignment from _struct_ref_seq", () => {
    expect(uniprotRef).toMatchObject({
      accession: "P00759",
      dbBeg: 25,
      dbEnd: 259,
      authBeg: 16,
      authEnd: 246,
      seqBeg: 1,
      seqEnd: 235
    });
  });

  it("maps author residues onto UniProt positions in SEQRES order", () => {
    expect(targetIndexOf(16, "", ctx)).toBe(25);
    // Author 246 is SEQRES 235 -> UniProt 259, not 25 + (246 - 16) = 255:
    // insertion codes and numbering jumps make author numbers non-contiguous.
    expect(targetIndexOf(246, "", ctx)).toBe(259);
    // The mutated residue of the backend run: author 79A -> UniProt 84.
    expect(targetIndexOf(79, "A", ctx)).toBe(84);
    expect(authorAtTargetIndex(84, ctx)).toEqual({
      authSeqId: 79,
      insCode: "A",
      seqId: 60
    });
    // Signal-peptide region the structure does not cover.
    expect(authorAtTargetIndex(24, ctx)).toBeUndefined();
  });

  it("reproduces the backend trim and inpainted positions", () => {
    expect(keptRange(ctx)).toEqual({ start: 25, end: 259 });
    // Unresolved SEQRES positions 80-86 sit at UniProt 104-110 (offset 24).
    // Those seven are all author 95 with insertion codes D..J, so any
    // author-number arithmetic would collapse them onto one position.
    const unresolvedAuth = ctx.polySeq!.positions.filter(p => !p.resolved);
    expect(unresolvedAuth.map(p => `${p.authSeqId}${p.insCode}`)).toEqual([
      "95D",
      "95E",
      "95F",
      "95G",
      "95H",
      "95I",
      "95J"
    ]);
    expect(
      unresolvedAuth.map(p => targetIndexOf(p.authSeqId!, p.insCode, ctx))
    ).toEqual(range(104, 110));
  });

  it("numbers a mutation the way the trimmed result does", () => {
    // The backend run mutated UniProt 84 (author 79A): internal, so the kept
    // range is unchanged and the result residue is 84 - 24 = 60.
    const mutations = [{ chainId: "A", authSeqId: 79, insCode: "A" }];
    expect(keptRange({ ...ctx, mutatedKeys: new Set(["79|A"]) })).toEqual({
      start: 25,
      end: 259
    });
    expect(toResultSites(mutations, () => ctx, true)).toEqual([
      { chainId: "A", resNum: 60 }
    ]);
    expect(toResultSites(mutations, () => ctx, false)).toEqual([
      { chainId: "A", resNum: 84 }
    ]);
    // Mutating the first aligned residue (author 16, UniProt 25) strips it,
    // moving kept_start to 26; the mutation itself is then trimmed away.
    const terminal = [{ chainId: "A", authSeqId: 16, insCode: "" }];
    expect(keptRange({ ...ctx, mutatedKeys: new Set(["16|"]) })).toEqual({
      start: 26,
      end: 259
    });
    expect(toResultSites(terminal, () => ctx, true)).toEqual([]);
    expect(toResultSites(terminal, () => ctx, false)).toEqual([
      { chainId: "A", resNum: 25 }
    ]);
  });
});

describe("4J76 chain A (N-terminal tag + long unresolved N-terminus)", () => {
  // Backend run: trim kept_start 21, kept_end 409; inpainted 271-287.
  const cif = loadMock("4J76.cif");
  const ctx = ctxFor(cif, "A");

  it("matches the backend trim and gap", () => {
    expect(unresolvedPositions(ctx)).toEqual([
      ...range(1, 20),
      ...range(271, 287)
    ]);
    expect(keptRange(ctx)).toEqual({ start: 21, end: 409 });
  });

  it("renumbers the first resolved residue to 1 under skip-terminal", () => {
    const first = ctx.polySeq!.positions[20];
    expect(first.resolved).toBe(true);
    expect(
      resultResidueNumber(first.authSeqId!, first.insCode, ctx, true)
    ).toBe(1);
    expect(
      resultResidueNumber(first.authSeqId!, first.insCode, ctx, false)
    ).toBe(21);
  });
});

describe("2R27 chains A/B (author numbering from 0, unresolved residue 1)", () => {
  // Backend run: both chains trim kept_start 2, kept_end 154;
  //   A inpainted 69-79, 133-140 ; B inpainted 69-79, 133-140 (80 partial).
  const cif = loadMock("2R27.cif");

  for (const chainId of ["A", "B"]) {
    it(`chain ${chainId}: trim and inpainted positions agree`, () => {
      const ctx = ctxFor(cif, chainId);
      expect(keptRange(ctx)).toEqual({ start: 2, end: 154 });
      const kept = keptRange(ctx)!;
      const internalGaps = unresolvedPositions(ctx).filter(
        p => p >= kept.start && p <= kept.end
      );
      expect(internalGaps).toEqual([...range(69, 79), ...range(133, 140)]);
      // Author 0 is position 1 (trimmed); author 1 is position 2 -> result 1.
      expect(targetIndexOf(0, "", ctx)).toBe(1);
      expect(resultResidueNumber(0, "", ctx, true)).toBeUndefined();
      expect(resultResidueNumber(1, "", ctx, true)).toBe(1);
      expect(resultResidueNumber(1, "", ctx, false)).toBe(2);
    });
  }

  it("erasing the first resolved residue moves the kept range", () => {
    const ctx = { ...ctxFor(cif, "A"), erasedKeys: new Set(["1|"]) };
    expect(presentTargetPositions(ctx)![0]).toBe(3);
    expect(keptRange(ctx)).toEqual({ start: 3, end: 154 });
    expect(resultResidueNumber(2, "", ctx, true)).toBe(1);
  });
});
