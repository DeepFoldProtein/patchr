import * as React from "react";
import type { PreviewFrame } from "../../types";

export interface SampleGalleryProps {
  frames: PreviewFrame[];
  onSelectFrame?: (frame: PreviewFrame) => void;
  selectedFrameId?: string;
}

/**
 * Display gallery of generated samples from different seeds
 */
export function SampleGallery({
  frames,
  onSelectFrame,
  selectedFrameId
}: SampleGalleryProps): React.ReactElement {
  if (frames.length === 0) {
    return (
      <div className="rounded border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
        No samples generated yet
      </div>
    );
  }

  return (
    <div className="space-y-2 border-t border-border pt-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-300">
          Generated Samples ({frames.length})
        </p>
        {frames.length > 0 && (
          <p className="text-xs text-gray-400">
            Avg pLDDT:{" "}
            {(
              frames.reduce((sum, f) => sum + (f.plddt_mean ?? 0), 0) /
              frames.length
            ).toFixed(1)}
          </p>
        )}
      </div>

      <div className="flex gap-2 overflow-x-auto pb-2">
        {frames.map(frame => (
          <button
            key={frame.frameId}
            onClick={() => onSelectFrame?.(frame)}
            className={`
              flex h-20 w-16 flex-shrink-0 flex-col items-center justify-center
              rounded border-2 transition-colors
              ${
                selectedFrameId === frame.frameId
                  ? "border-neutral-300 bg-neutral-500/20"
                  : "border-neutral-600 bg-neutral-700 hover:border-neutral-500"
              }
            `}
            title={`Seed ${frame.frameIndex}, pLDDT: ${frame.plddt_mean?.toFixed(1) ?? "N/A"}`}
          >
            <span className="text-center">
              <div className="text-xs font-medium">#{frame.frameIndex + 1}</div>
              {frame.plddt_mean !== undefined && (
                <div className="mt-1 text-[10px] text-gray-300">
                  {frame.plddt_mean.toFixed(1)}
                </div>
              )}
              <div
                className={`mt-1 text-[10px] ${
                  (frame.plddt_mean ?? 0) >= 70
                    ? "text-green-400"
                    : (frame.plddt_mean ?? 0) >= 50
                      ? "text-yellow-400"
                      : "text-red-400"
                }`}
              >
                {(frame.plddt_mean ?? 0) >= 70
                  ? "Good"
                  : (frame.plddt_mean ?? 0) >= 50
                    ? "Fair"
                    : "Poor"}
              </div>
            </span>
          </button>
        ))}
      </div>

      {/* Quality legend */}
      <div className="flex items-center gap-3 text-[10px] text-gray-400">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-green-400" />
          Good (≥70)
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-yellow-400" />
          Fair (50-70)
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-red-400" />
          Poor (&lt;50)
        </span>
      </div>
    </div>
  );
}
