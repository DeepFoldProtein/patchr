// Maps author-numbered residues onto the numbering of an inpainting result.
//
// The backend rebuilds each chain from its *target sequence* (the SEQRES from
// `_pdbx_poly_seq_scheme`, or a loaded UniProt reference) and writes the result
// with canonical numbering: residue i of the target sequence gets
// auth_seq_id == label_seq_id == i. With skip-terminal the sequence is first
// sliced to the observed range [kept_start, kept_end] and renumbered from 1.
// Author numbers (offsets, gaps, insertion codes) never survive, so anything we
// want to locate in a result — a staged mutation — has to be converted first.
// The same conversion defines where a mutation lands in the custom sequence
// sent to the backend, so both sides share this module.
import type { ChainPolySeq } from "./polySeq";
import type { UniProtRef } from "./structRef";

export interface ChainTargetContext {
  /** Full polymer sequence of the chain from `_pdbx_poly_seq_scheme`. */
  polySeq?: ChainPolySeq;
  /** UniProt alignment of the chain from `_struct_ref_seq`. */
  uniprotRef?: UniProtRef;
  /** Loaded UniProt reference sequence; when present it IS the target. */
  reference?: string;
  /** "authSeqId|insCode" keys of residues erased before the run. */
  erasedKeys?: Set<string>;
  /**
   * "authSeqId|insCode" keys of residues staged for mutation. The backend
   * aligns the structure to the target sequence and strips every mismatched
   * residue (it is rebuilt as fully inpainted), so a mutated residue does not
   * count as present when the kept range is derived.
   */
  mutatedKeys?: Set<string>;
}

export function residueKey(authSeqId: number, insCode: string): string {
  return `${authSeqId}|${insCode}`;
}

/** Whether the loaded UniProt reference drives the target sequence. */
export function usesUniProtTarget(ctx: ChainTargetContext): boolean {
  return (
    ctx.reference !== undefined &&
    ctx.reference.length > 0 &&
    ctx.uniprotRef !== undefined &&
    ctx.uniprotRef.dbEnd >= ctx.uniprotRef.dbBeg
  );
}

/**
 * Offset from SEQRES position to UniProt position. The backend aligns the
 * structure's residue sequence to the reference, so the mapping follows SEQRES
 * order (insertion codes and author numbering jumps included), anchored by
 * `_struct_ref_seq.seq_align_beg` -> `db_align_beg`. Undefined when the
 * SEQRES anchor is not recorded.
 */
function uniprotSeqresOffset(ctx: ChainTargetContext): number | undefined {
  const ref = ctx.uniprotRef;
  if (!ref || ref.seqBeg === undefined || !ctx.polySeq) return undefined;
  return ref.dbBeg - ref.seqBeg;
}

/**
 * 1-based position of an author residue in the chain's target sequence, or
 * undefined when it has no place there (outside the reference, or an unknown
 * author number).
 */
export function targetIndexOf(
  authSeqId: number,
  insCode: string,
  ctx: ChainTargetContext
): number | undefined {
  if (usesUniProtTarget(ctx)) {
    const ref = ctx.uniprotRef!;
    const offset = uniprotSeqresOffset(ctx);
    let pos: number | undefined;
    if (offset !== undefined) {
      const idx = ctx.polySeq!.keyToIndex.get(residueKey(authSeqId, insCode));
      pos = idx === undefined ? undefined : idx + 1 + offset;
    } else {
      // No SEQRES anchor: assume contiguous author numbering. Insertion codes
      // cannot be placed.
      if (insCode) return undefined;
      pos = ref.dbBeg + (authSeqId - ref.authBeg);
    }
    return pos !== undefined && pos >= 1 && pos <= ctx.reference!.length
      ? pos
      : undefined;
  }
  const idx = ctx.polySeq?.keyToIndex.get(residueKey(authSeqId, insCode));
  return idx === undefined ? undefined : idx + 1;
}

export interface AuthorResidue {
  authSeqId: number;
  insCode: string;
  /** Entity seq_id (_entity_poly_seq.num), when known. */
  seqId?: number;
}

/**
 * Inverse of `targetIndexOf`: the author residue sitting at a 1-based target
 * position, or undefined when the position lies outside the structure's
 * sequence (a reference region the structure does not cover).
 */
export function authorAtTargetIndex(
  pos: number,
  ctx: ChainTargetContext
): AuthorResidue | undefined {
  if (usesUniProtTarget(ctx)) {
    const ref = ctx.uniprotRef!;
    const offset = uniprotSeqresOffset(ctx);
    if (offset !== undefined) {
      const p = ctx.polySeq!.positions[pos - offset - 1];
      if (!p || p.authSeqId === undefined) return undefined;
      return { authSeqId: p.authSeqId, insCode: p.insCode, seqId: p.seqId };
    }
    if (pos < ref.dbBeg || pos > ref.dbEnd) return undefined;
    const authSeqId = ref.authBeg + (pos - ref.dbBeg);
    return {
      authSeqId,
      insCode: "",
      seqId: ctx.polySeq?.keyToSeqId.get(residueKey(authSeqId, ""))
    };
  }
  const p = ctx.polySeq?.positions[pos - 1];
  if (!p || p.authSeqId === undefined) return undefined;
  return { authSeqId: p.authSeqId, insCode: p.insCode, seqId: p.seqId };
}

/** Length of the target sequence, if known. */
export function targetLength(ctx: ChainTargetContext): number | undefined {
  if (usesUniProtTarget(ctx)) return ctx.reference!.length;
  return ctx.polySeq?.positions.length;
}

/**
 * Target positions that carry coordinates at run time: resolved in the
 * structure, not erased, and not mutated. This is the set the backend's
 * --skip-terminal derives its kept range from. Null when the structure gives
 * no sequence info.
 */
export function presentTargetPositions(
  ctx: ChainTargetContext
): number[] | null {
  if (!ctx.polySeq) return null;
  const out: number[] = [];
  for (const pos of ctx.polySeq.positions) {
    if (!pos.resolved || pos.authSeqId === undefined) continue;
    const key = residueKey(pos.authSeqId, pos.insCode);
    if (ctx.erasedKeys?.has(key) || ctx.mutatedKeys?.has(key)) continue;
    const idx = targetIndexOf(pos.authSeqId, pos.insCode, ctx);
    if (idx !== undefined) out.push(idx);
  }
  return out.sort((a, b) => a - b);
}

export interface KeptRange {
  /** First target position kept (1-based, inclusive). */
  start: number;
  /** Last target position kept (1-based, inclusive). */
  end: number;
}

/**
 * Range the backend keeps under --skip-terminal: from the first to the last
 * present position. Null when it cannot be determined (no trim applied then).
 */
export function keptRange(ctx: ChainTargetContext): KeptRange | null {
  const present = presentTargetPositions(ctx);
  if (!present || present.length === 0) return null;
  return { start: present[0], end: present[present.length - 1] };
}

/**
 * Residue number an author residue carries in the result structure, or
 * undefined when it is absent from the result (unmappable, or trimmed away).
 */
export function resultResidueNumber(
  authSeqId: number,
  insCode: string,
  ctx: ChainTargetContext,
  skipTerminal: boolean
): number | undefined {
  const pos = targetIndexOf(authSeqId, insCode, ctx);
  if (pos === undefined) return undefined;
  if (!skipTerminal) return pos;
  const range = keptRange(ctx);
  if (!range) return pos;
  if (pos < range.start || pos > range.end) return undefined;
  return pos - (range.start - 1);
}

export interface AuthorResidueRef {
  chainId: string;
  authSeqId: number;
  insCode: string;
}

export interface ResultResidueSite {
  chainId: string;
  /** auth_seq_id (== label_seq_id) of the residue in the result structure. */
  resNum: number;
}

/** Group "authSeqId|insCode" keys by chain id. */
export function residueKeysByChain(
  residues: AuthorResidueRef[]
): Map<string, Set<string>> {
  const byChain = new Map<string, Set<string>>();
  for (const r of residues) {
    let set = byChain.get(r.chainId);
    if (!set) {
      set = new Set();
      byChain.set(r.chainId, set);
    }
    set.add(residueKey(r.authSeqId, r.insCode));
  }
  return byChain;
}

/**
 * Convert staged mutations to result residue numbers. The mutations themselves
 * are excluded from the present set (see `mutatedKeys`). Residues that have no
 * place in the result are dropped.
 */
export function toResultSites(
  mutations: AuthorResidueRef[],
  contextFor: (chainId: string) => ChainTargetContext,
  skipTerminal: boolean
): ResultResidueSite[] {
  const mutatedByChain = residueKeysByChain(mutations);
  const ctxCache = new Map<string, ChainTargetContext>();
  const out: ResultResidueSite[] = [];
  for (const r of mutations) {
    let ctx = ctxCache.get(r.chainId);
    if (!ctx) {
      ctx = {
        ...contextFor(r.chainId),
        mutatedKeys: mutatedByChain.get(r.chainId)
      };
      ctxCache.set(r.chainId, ctx);
    }
    const resNum = resultResidueNumber(
      r.authSeqId,
      r.insCode,
      ctx,
      skipTerminal
    );
    if (resNum !== undefined) out.push({ chainId: r.chainId, resNum });
  }
  return out;
}
