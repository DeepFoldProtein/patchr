// MissingRegionReviewSection.tsx - Missing Region Review 섹션 (체인별 coverage)
import React from "react";
import { useAtom } from "jotai";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  missingRegionsDetectedAtom,
  missingRegionDetectionLoadingAtom
} from "../../store/repair-atoms";
import { CheckCircle, ChevronDown, ChevronRight } from "lucide-react";
import { bus } from "../../lib/event-bus";
import { logger } from "../../lib/logger";
import type { MissingRegionInfo } from "../../types";

// Partial regions are emitted one per residue with missing atoms, so a
// poorly-resolved structure yields thousands of rows. Rendering them all at
// once produced tens of thousands of DOM nodes and an unbounded scroll height,
// so the list is flattened into rows and virtualized inside a fixed viewport.
const LIST_HEIGHT_PX = 420;
const CHAIN_HEADER_HEIGHT_PX = 34;
const PARTIAL_TOGGLE_HEIGHT_PX = 32;
const REGION_ROW_HEIGHT_PX = 62;

type Row =
  | {
      kind: "chain";
      key: string;
      chainId: string;
      completeCount: number;
      partialCount: number;
    }
  | {
      kind: "partial-toggle";
      key: string;
      chainId: string;
      count: number;
      expanded: boolean;
    }
  | { kind: "region"; key: string; region: MissingRegionInfo };

/**
 * Complete gaps are the actionable repair targets, so they are always listed.
 * Partial residues are emitted one per residue and can run into the thousands
 * on low-resolution models (6WBL at 5.13 Å: 1880 of 2182 residues), which
 * makes them noise rather than a list — they sit behind a per-chain toggle.
 */
function buildRows(
  regions: MissingRegionInfo[],
  expandedPartials: ReadonlySet<string>
): { rows: Row[]; chainCount: number; partialTotal: number } {
  const chainGroups = new Map<string, MissingRegionInfo[]>();
  for (const region of regions) {
    const existing = chainGroups.get(region.chainId) ?? [];
    existing.push(region);
    chainGroups.set(region.chainId, existing);
  }

  const rows: Row[] = [];
  let partialTotal = 0;

  for (const [chainId, chainRegions] of chainGroups.entries()) {
    const complete = chainRegions.filter(r => r.regionType === "complete");
    const partial = chainRegions.filter(r => r.regionType === "partial");
    partialTotal += partial.length;

    rows.push({
      kind: "chain",
      key: `chain:${chainId}`,
      chainId,
      completeCount: complete.length,
      partialCount: partial.length
    });

    for (const region of complete) {
      rows.push({ kind: "region", key: `region:${region.regionId}`, region });
    }

    if (partial.length > 0) {
      const expanded = expandedPartials.has(chainId);
      rows.push({
        kind: "partial-toggle",
        key: `partial-toggle:${chainId}`,
        chainId,
        count: partial.length,
        expanded
      });
      if (expanded) {
        for (const region of partial) {
          rows.push({
            kind: "region",
            key: `region:${region.regionId}`,
            region
          });
        }
      }
    }
  }

  return { rows, chainCount: chainGroups.size, partialTotal };
}

function RegionRow({
  region,
  onSelect
}: {
  region: MissingRegionInfo;
  onSelect: (regionId: string) => void;
}): React.ReactElement {
  const startAuthDisplay = region.startAuthSeqId
    ? `${region.startAuthSeqId}${region.insertionCode || ""}`
    : region.startResId.toString();
  const endAuthDisplay = region.endAuthSeqId
    ? `${region.endAuthSeqId}${region.endInsertionCode || ""}`
    : region.endResId.toString();

  const regionRangeDisplay =
    region.regionType === "complete" && startAuthDisplay !== endAuthDisplay
      ? `${startAuthDisplay} - ${endAuthDisplay}`
      : startAuthDisplay;

  // The detail line is truncated to keep row heights uniform, so the full text
  // has to stay reachable on hover.
  const detailTitle =
    region.regionType === "partial" && region.missingAtoms
      ? `${region.missingAtoms.length} atom(s) missing: ${region.missingAtoms.join(", ")}`
      : region.sequenceKnown && region.sequence
        ? `Length: ${region.regionLength} · Sequence: ${region.sequence}`
        : `Length: ${region.regionLength}`;

  return (
    <div
      onClick={() => onSelect(region.regionId)}
      title={`Chain ${region.chainId} ${regionRangeDisplay} — ${detailTitle}`}
      className="ml-3 rounded border border-border/50 bg-background p-2 cursor-pointer hover:bg-accent/50 transition-colors"
    >
      <div className="mb-1 flex items-center gap-2">
        <span
          className={`inline-block h-2 w-2 shrink-0 rounded-full ${
            region.regionType === "complete" ? "bg-orange-500" : "bg-yellow-500"
          }`}
        ></span>
        <span className="text-xs font-medium">
          {region.regionType === "complete"
            ? "Missing Residues"
            : "Incomplete Residues (missing atoms)"}
        </span>
        <span className="text-xs text-muted-foreground font-mono">
          {regionRangeDisplay}
        </span>
      </div>
      <div className="truncate text-xs text-muted-foreground">
        {region.regionType === "complete" && (
          <>
            Length: {region.regionLength} residue(s)
            {region.sequenceKnown &&
              region.sequence &&
              ` · Sequence: ${region.sequence}`}
            {!region.sequenceKnown && " · Sequence unknown"}
          </>
        )}
        {region.regionType === "partial" && region.missingAtoms && (
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
  );
}

export function MissingRegionReviewSection(): React.ReactElement {
  const [missingRegions] = useAtom(missingRegionsDetectedAtom);
  const [loading] = useAtom(missingRegionDetectionLoadingAtom);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const [expandedPartials, setExpandedPartials] = React.useState<Set<string>>(
    () => new Set()
  );

  const { rows, chainCount, partialTotal } = React.useMemo(
    () => buildRows(missingRegions, expandedPartials),
    [missingRegions, expandedPartials]
  );

  const togglePartials = React.useCallback((chainId: string): void => {
    setExpandedPartials(current => {
      const next = new Set(current);
      if (next.has(chainId)) next.delete(chainId);
      else next.add(chainId);
      return next;
    });
  }, []);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: index => {
      const kind = rows[index].kind;
      if (kind === "chain") return CHAIN_HEADER_HEIGHT_PX;
      if (kind === "partial-toggle") return PARTIAL_TOGGLE_HEIGHT_PX;
      return REGION_ROW_HEIGHT_PX;
    },
    overscan: 8
  });

  const handleRegionClick = React.useCallback((regionId: string): void => {
    logger.log(`[Missing Region Review] Region clicked: ${regionId}`);
    bus.emit("missing-region:focus", regionId);
  }, []);

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
          No Missing or Incomplete Residues
        </h3>
        <p className="text-xs text-muted-foreground">
          Structure appears complete. All residues have coordinates.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Found {missingRegions.length - partialTotal} missing region(s) and{" "}
        {partialTotal} incomplete residue(s) in {chainCount} chain(s)
      </p>

      <div
        ref={scrollRef}
        className="overflow-y-auto rounded-lg border border-border bg-muted/20 p-2"
        style={{ height: LIST_HEIGHT_PX }}
      >
        <div
          className="relative w-full"
          style={{ height: virtualizer.getTotalSize() }}
        >
          {virtualizer.getVirtualItems().map(item => {
            const row = rows[item.index];
            return (
              <div
                key={row.key}
                data-index={item.index}
                ref={virtualizer.measureElement}
                className="absolute left-0 top-0 w-full"
                style={{ transform: `translateY(${item.start}px)` }}
              >
                <div className="pb-2">
                  {row.kind === "chain" ? (
                    <div className="flex items-center gap-2 pt-1">
                      <span className="rounded bg-primary px-2 py-0.5 text-xs font-mono text-primary-foreground">
                        Chain {row.chainId}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {row.completeCount} missing
                        {row.partialCount > 0 &&
                          ` · ${row.partialCount} incomplete`}
                      </span>
                    </div>
                  ) : row.kind === "partial-toggle" ? (
                    <button
                      onClick={() => togglePartials(row.chainId)}
                      className="ml-3 flex w-[calc(100%-0.75rem)] items-center gap-1.5 rounded border border-dashed border-border/60 px-2 py-1 text-left text-xs text-muted-foreground transition-colors hover:bg-accent/50"
                    >
                      {row.expanded ? (
                        <ChevronDown className="h-3 w-3 shrink-0" />
                      ) : (
                        <ChevronRight className="h-3 w-3 shrink-0" />
                      )}
                      <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-yellow-500" />
                      {row.count} residue(s) with missing atoms
                    </button>
                  ) : (
                    <RegionRow
                      region={row.region}
                      onSelect={handleRegionClick}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
