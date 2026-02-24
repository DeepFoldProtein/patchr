// Mol* Viewer Types

export interface StructureInfo {
  title: string;
  chainIds: string[];
  residueCount: number;
  atomCount: number;
  format: "pdb" | "mmcif" | "bcif";
}

export interface SelectionInfo {
  residues: Array<{ chain: string; seqId: number }>;
  atoms: number[];
  chains: string[];
}

export type RepresentationType =
  | "cartoon"
  | "surface"
  | "ball-and-stick"
  | "spacefill"
  | "ribbon";

export type ColorScheme = "chain-id" | "residue-name" | "rainbow" | "uniform";

export interface CameraState {
  position: [number, number, number];
  target: [number, number, number];
  up: [number, number, number];
}

export interface MaskSpec {
  version: number;
  units: "residue" | "atom";
  include: Array<{
    chain: string;
    residues?: number[];
    atomIds?: number[];
  }>;
  exclude: Array<{
    chain: string;
    residues?: number[];
    atomIds?: number[];
  }>;
  fixed: Array<{
    chain: string;
    residues?: number[];
  }>;
  soft_shell_Ang: number;
}

export interface InpaintParams {
  steps: number;
  tau: number;
  seeds: number;
}

export interface PreviewFrame {
  frameId: string;
  frameIndex: number;
  totalFrames: number;
  structure: ArrayBuffer;
  confidence?: number;
  timestamp: number;
}

export interface PreviewState {
  isRunning: boolean;
  progress: number;
  currentFrame: PreviewFrame | null;
  frames: PreviewFrame[];
  error: string | null;
  eta: number;
}
