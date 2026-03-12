import mitt from "mitt";
import type { RepairSegment, PreviewFrame } from "../types";
import type { SelectionInfo, MaskSpec } from "../types/mol-viewer";

/** All application events with their payload types. */
export type AppEvents = {
  // Selection
  "selection:changed": SelectionInfo;
  "selection:cleared": void;
  "selection:clear": void;

  // Mask overlay
  "mask:apply": MaskSpec;
  "mask:overlayed": MaskSpec;
  "mask:clear": void;
  "mask:cleared": void;

  // Preview / Inpainting stream
  "preview:started": { runId: string };
  "preview:progress": {
    progress: number;
    elapsed_s: number;
    remaining_s: number;
  };
  "preview:complete": { totalFrames: number; plddt_scores?: number[] };
  "preview:error": { error: string; code?: string };
  "preview:frameUpdated": PreviewFrame;
  "preview:cancelled": void;

  // Missing region / Gap
  "missing-region:focus": string; // regionId

  // Structure
  "structure:loaded": { format: string; chainCount: number };
  "structure:representations-ready": { isBaseStructure: boolean };

  // Repair
  "repair:missing-regions-ready": RepairSegment[];
  "repair:segment-selected": string; // segmentId

  // Inpainting results
  "inpainting:load-result": {
    filePath: string;
    fileContent: string;
    superpose?: boolean;
  };
  "inpainting:remove-result": { filePath: string; visible?: boolean };
  "inpainting:structure-loaded": { filePath: string };

  // Results
  "results:updated": void;

  // Simulation viewer
  "simulation:load-system": {
    filePath: string;
    fileContent: string;
    label: string;
  };
};

export const bus = mitt<AppEvents>();
