// MissingRegionReviewSection.tsx - Missing Region Review 섹션 (체인별 coverage + Repair Segments)
import React from "react";
import { useAtom } from "jotai";
import {
  missingRegionsDetectedAtom,
  repairSegmentsAtom,
  selectedSegmentIdsAtom,
  missingRegionDetectionLoadingAtom
} from "../../store/repair-atoms";
import { CheckCircle, AlertTriangle } from "lucide-react";
import { bus } from "../../lib/event-bus";
import { logger } from "../../lib/logger";

export function MissingRegionReviewSection(): React.ReactElement {
  const [missingRegions] = useAtom(missingRegionsDetectedAtom);
  const [repairSegments] = useAtom(repairSegmentsAtom);
  const [selectedSegmentIds, setSelectedSegmentIds] = useAtom(
    selectedSegmentIdsAtom
  );
  const [loading] = useAtom(missingRegionDetectionLoadingAtom);

  const handleRegionClick = (regionId: string): void => {
    logger.log(`[Missing Region Review] Region clicked: ${regionId}`);
    // Emit region focus event to trigger camera zoom
    bus.emit("missing-region:focus", regionId);
    logger.log(`[Missing Region Review] missing-region:focus event emitted`);
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
                // Author's residue ID 표시 (insertion code 포함)
                const startAuthDisplay = region.startAuthSeqId
                  ? `${region.startAuthSeqId}${region.insertionCode || ""}`
                  : region.startResId.toString();
                const endAuthDisplay = region.endAuthSeqId
                  ? `${region.endAuthSeqId}${region.endInsertionCode || ""}`
                  : region.endResId.toString();

                // Complete region의 경우 범위 표시 (예: "95C - 95K")
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

      {/* Repair Groups - Chain 기반 표시 */}
      {repairSegments.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold">Repair Groups</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            Select chains to configure inpainting parameters.
          </p>

          <div className="space-y-2">
            {Array.from(chainGroups.keys())
              .sort()
              .map(chainId => {
                // Find segments that include this chain
                const chainSegments = repairSegments.filter(segment =>
                  segment.chainIds.includes(chainId)
                );
                const allSegmentIds = chainSegments.map(s => s.segmentId);
                const isSelected = allSegmentIds.some(id =>
                  selectedSegmentIds.includes(id)
                );

                return (
                  <button
                    key={chainId}
                    onClick={e => {
                      // Toggle all segments for this chain
                      e.preventDefault();
                      setSelectedSegmentIds(prev => {
                        const newIds = [...prev];
                        if (isSelected) {
                          // Remove all segments for this chain
                          allSegmentIds.forEach(id => {
                            const index = newIds.indexOf(id);
                            if (index > -1) newIds.splice(index, 1);
                          });
                        } else {
                          // Add all segments for this chain
                          allSegmentIds.forEach(id => {
                            if (!newIds.includes(id)) newIds.push(id);
                          });
                        }
                        return newIds;
                      });
                      // Emit event for first segment
                      if (chainSegments.length > 0) {
                        bus.emit(
                          "repair:segment-selected",
                          chainSegments[0].segmentId
                        );
                      }
                    }}
                    className={`w-full rounded-lg border p-3 text-left transition-colors ${
                      isSelected
                        ? "border-primary bg-primary/10"
                        : "border-border bg-background hover:bg-accent"
                    }`}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-xs font-medium">
                        Chain {chainId}
                      </span>
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          chainSegments.some(s => s.repairType === "full")
                            ? "bg-orange-500/20 text-orange-400"
                            : chainSegments.some(
                                  s => s.repairType === "backbone"
                                )
                              ? "bg-blue-500/20 text-blue-400"
                              : "bg-yellow-500/20 text-yellow-400"
                        }`}
                      >
                        {chainSegments[0]?.repairType || "full"}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {chainSegments.reduce(
                        (sum, s) => sum + s.missingRegions.length,
                        0
                      )}{" "}
                      region(s)
                      {chainSegments.some(s => s.needsSequenceInput) && (
                        <span className="inline-flex items-center gap-0.5">
                          {" · "}
                          <AlertTriangle className="inline h-3 w-3 text-amber-500" />
                          {" Sequence needed"}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
