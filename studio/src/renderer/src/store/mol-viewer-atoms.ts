// Mol* Viewer Atoms
import { atom } from "jotai";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import type {
  StructureInfo,
  SelectionInfo,
  ColorScheme,
  RepresentationType,
  CameraState
} from "../types/mol-viewer";
import type { PreviewState } from "../types";

// Mol* Plugin instance (shared globally)
export const pluginAtom = atom<PluginUIContext | null>(null);

// 구조 로딩 상태
export const structureLoadingAtom = atom<boolean>(false);
export const structureErrorAtom = atom<string | null>(null);
export const structureInfoAtom = atom<StructureInfo | null>(null);

// 선택 상태
export const selectionAtom = atom<SelectionInfo | null>(null);

// 뷰어 설정
export const viewerSettingsAtom = atom<{
  colorScheme: ColorScheme;
  representation: RepresentationType;
  backgroundColor: string;
}>({
  colorScheme: "chain-id",
  representation: "cartoon",
  backgroundColor: "#0f172a"
});

// 카메라 상태
export const cameraStateAtom = atom<CameraState | null>(null);

// 프리뷰 상태
export const previewStateAtom = atom<PreviewState>({
  isRunning: false,
  progress: 0,
  elapsed_s: 0,
  remaining_s: 0,
  currentFrame: null,
  frames: [],
  error: null,
  runId: null
});
