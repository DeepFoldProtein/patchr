// Repair Atoms - Repair Console 상태 관리
import { atom } from "jotai";
import { logger } from "../lib/logger";
import { apiConnectionStatusAtom } from "./api-atoms";
import type {
  MissingRegionInfo,
  RepairSegment,
  SequenceMapping,
  RepairContext,
  RepairResult
} from "../types";

// Missing Region 감지 상태
export const missingRegionsDetectedAtom = atom<MissingRegionInfo[]>([]);
export const missingRegionDetectionLoadingAtom = atom<boolean>(false);
export const missingRegionDetectionErrorAtom = atom<string | null>(null);

// Repair Segments (인페인팅 단위)
export const repairSegmentsAtom = atom<RepairSegment[]>([]);
export const selectedSegmentIdsAtom = atom<string[]>([]);

// Sequence Mapping
export const sequenceMappingsAtom = atom<SequenceMapping[]>([]);
export const fastaInputAtom = atom<string>("");
export const enableSequenceMappingAtom = atom<boolean>(false);

// Residues marked for erasure in the Sequence editor. Each region is shown
// semi-transparent in the 3D viewer and can be individually restored; the next
// inpainting run strips all of them from the uploaded CIF so the backend
// re-detects them as missing regions and regenerates them.
export interface EraseRegion {
  id: string; // stable id for restore
  chainId: string; // author chain id
  residues: { authSeqId: number; insCode: string }[];
  label: string; // human-readable summary, e.g. "A 45–52 (8)"
}
export const erasedRegionsAtom = atom<EraseRegion[]>([]);

// Flattened set of erased residue keys per chain, for the 3D transparency
// overlay and quick membership checks. Derived from erasedRegionsAtom.
export const erasedResidueKeysAtom = atom(get => {
  const byChain = new Map<string, Set<string>>();
  for (const region of get(erasedRegionsAtom)) {
    let set = byChain.get(region.chainId);
    if (!set) {
      set = new Set();
      byChain.set(region.chainId, set);
    }
    for (const r of region.residues) set.add(`${r.authSeqId}|${r.insCode}`);
  }
  return byChain;
});

// Staged "add PTM" request from the Sequence editor. The next inpainting run
// forwards it to the backend as a `modifications` field so Boltz models the
// modified residue (e.g. SEP) at that entity position.
export interface PendingPtm {
  chainId: string; // author chain id
  seqId: number; // entity seq_id (_entity_poly_seq.num)
  ccd: string; // component id, e.g. SEP / TPO / PTR / MLY
  label: string; // human-readable summary
}
export const pendingPtmAtom = atom<PendingPtm | null>(null);

// Skip N/C-terminal missing residues (only inpaint internal gaps).
// Mutually exclusive with sequence mapping — when mapping is on, terminals
// are derived from the provided sequence, so this flag is forced off.
export const skipTerminalAtom = atom<boolean>(false);

// Repair Context (Context & Inpaint 설정)
export const repairContextsAtom = atom<Map<string, RepairContext>>(new Map());

// Repair Results
export const repairResultsAtom = atom<RepairResult[]>([]);

// Reset all repair state (for project change)
export const resetRepairStateAtom = atom(null, (_get, set) => {
  set(missingRegionsDetectedAtom, []);
  set(missingRegionDetectionLoadingAtom, false);
  set(missingRegionDetectionErrorAtom, null);
  set(repairSegmentsAtom, []);
  set(selectedSegmentIdsAtom, []);
  set(sequenceMappingsAtom, []);
  set(fastaInputAtom, "");
  set(enableSequenceMappingAtom, false);
  set(skipTerminalAtom, false);
  set(repairContextsAtom, new Map());
  set(repairResultsAtom, []);
  set(erasedRegionsAtom, []);
  set(pendingPtmAtom, null);
  set(apiConnectionStatusAtom, "idle");
  logger.log("[Repair Atoms] Reset all repair state");
});

// 선택된 segment의 컨텍스트 가져오기 (derived atom)
export const selectedRepairContextsAtom = atom(get => {
  const segmentIds = get(selectedSegmentIdsAtom);
  const contexts = get(repairContextsAtom);
  const result: RepairContext[] = [];
  for (const segmentId of segmentIds) {
    const context = contexts.get(segmentId);
    if (context) {
      result.push(context);
    }
  }
  return result;
});

// 선택된 segments 가져오기 (derived atom)
export const selectedRepairSegmentsAtom = atom(get => {
  const segmentIds = get(selectedSegmentIdsAtom);
  const segments = get(repairSegmentsAtom);
  return segments.filter(s => segmentIds.includes(s.segmentId));
});

// Repair Console UI 상태
export const repairConsoleExpandedAtom = atom<
  "missing-region-review" | "sequence" | "context" | "relax" | null
>("missing-region-review");

// API Connection Status — canonical source is api-atoms.ts
export { apiConnectionStatusAtom } from "./api-atoms";
