// MissingRegionReviewSection.tsx - Missing Region Review 섹션 (체인별 coverage)
import React from "react";
import { useAtom } from "jotai";
import {
  missingRegionsDetectedAtom,
  missingRegionDetectionLoadingAtom
} from "../../store/repair-atoms";
import { CheckCircle } from "lucide-react";
import { bus } from "../../lib/event-bus";
import { logger } from "../../lib/logger";

export function MissingRegionReviewSection(): React.ReactElement {
  const [missingRegions] = useAtom(missingRegionsDetectedAtom);
  const [loading] = useAtom(missingRegionDetectionLoadingAtom);

  const handleRegionClick = (regionId: string): void => {
    logger.log(`[Missing Region Review] Region clicked: ${regionId}`);
    bus.emit("missing-region:focus", regionId);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-center">
          <div className="mb-2 animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto"></div>
          <p className="text-sm text-muted-foreground">
            Analyzing structure...
          </p>
        </div>
      </div>
    );
  }

  if (missingRegions.length === 0) {
    return (
      <div className="p-6 text-center">
        <CheckCircle className="mx-auto mb-2 h-8 w-8 text-green-500" />
        <h3 className="mb-1 text-sm font-semibold">
          No Missing Regions Detected
        </h3>
        <p className="text-xs text-muted-foreground">
          Structure appears complete. All residues have coordinates.
        </p>
      </div>
    );
  }

  // 체인별로 그룹화
  const chainGroups = new Map<string, typeof missingRegions>();
  for (const region of missingRegions) {
    const existing = chainGroups.get(region.chainId) ?? [];
    existing.push(region);
    chainGroups.set(region.chainId, existing);
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs text-muted-foreground">
          Found {missingRegions.length} region(s) in {chainGroups.size} chain(s)
        </p>
      </div>

      {/* Chain Coverage Timeline */}
      <div className="space-y-3">
        {Array.from(chainGroups.entries()).map(([chainId, chainRegions]) => (
          <div
            key={chainId}
            className="rounded-lg border border-border bg-muted/20 p-3"
          >
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="rounded bg-primary px-2 py-0.5 text-xs font-mono text-primary-foreground">
                  Chain {chainId}
                </span>
                <span className="text-xs text-muted-foreground">
                  {chainRegions.length} region(s)
                </span>
              </div>
            </div>

            {/* Missing Region 목록 */}
            <div className="space-y-2">
              {chainRegions.map(region => {
                const startAuthDisplay = region.startAuthSeqId
                  ? `${region.startAuthSeqId}${region.insertionCode || ""}`
                  : region.startResId.toString();
                const endAuthDisplay = region.endAuthSeqId
                  ? `${region.endAuthSeqId}${region.endInsertionCode || ""}`
                  : region.endResId.toString();

                const regionRangeDisplay =
                  region.regionType === "complete" &&
                  startAuthDisplay !== endAuthDisplay
                    ? `${startAuthDisplay} - ${endAuthDisplay}`
                    : startAuthDisplay;

                return (
                  <div
                    key={region.regionId}
                    onClick={() => handleRegionClick(region.regionId)}
                    className="rounded border border-border/50 bg-background p-2 cursor-pointer hover:bg-accent/50 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="mb-1 flex items-center gap-2">
                          <span
                            className={`inline-block h-2 w-2 rounded-full ${
                              region.regionType === "complete"
                                ? "bg-orange-500"
                                : "bg-yellow-500"
                            }`}
                          ></span>
                          <span className="text-xs font-medium">
                            {region.regionType === "complete"
                              ? "Complete Missing Region"
                              : "Partial Residue"}
                          </span>
                          <span className="text-xs text-muted-foreground font-mono">
                            {regionRangeDisplay}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {region.regionType === "complete" && (
                            <>
                              Length: {region.regionLength} residue(s)
                              {region.sequenceKnown &&
                                region.sequence &&
                                ` · Sequence: ${region.sequence}`}
                              {!region.sequenceKnown && " · Sequence unknown"}
                            </>
                          )}
                          {region.regionType === "partial" &&
                            region.missingAtoms && (
                              <>
                                <span className="inline-flex items-center gap-1">
                                  <span className="inline-block h-2 w-2 rounded-full bg-red-400"></span>
                                  {region.missingAtoms.length} atom(s) missing
                                </span>
                                <span className="ml-2 text-xs text-muted-foreground/70">
                                  ({region.missingAtoms.join(", ")})
                                </span>
                              </>
                            )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
