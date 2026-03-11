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
  set(repairContextsAtom, new Map());
  set(repairResultsAtom, []);
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
