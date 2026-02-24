// useAutoYAMLGeneration.ts - Automatically generate YAML after missing region detection
import { useEffect } from "react";
import { useAtom } from "jotai";
import { bus } from "../../lib/event-bus";
import { logger } from "../../lib/logger";
import {
  missingRegionsDetectedAtom,
  repairSegmentsAtom
} from "../../store/repair-atoms";
import { useCurrentProject, useProjectStore } from "../../store/project-store";
import type { InpaintingYAML } from "../../types/project";
import type { RepairSegment, MissingRegionInfo } from "../../types";

/**
 * Hook that listens to missing region detection completion
 * and automatically generates project YAML file
 */
export function useAutoYAMLGeneration(enabled: boolean = true): void {
  const [missingRegions] = useAtom(missingRegionsDetectedAtom);
  const [repairSegments] = useAtom(repairSegmentsAtom);
  const currentProject = useCurrentProject();
  const setCurrentYAML = useProjectStore(state => state.setCurrentYAML);
  const setError = useProjectStore(state => state.setError);

  useEffect(() => {
    if (!enabled || !currentProject) return;

    const handleMissingRegionsReady = async (
      segments: RepairSegment[]
    ): Promise<void> => {
      logger.log(
        "[Auto YAML] Missing regions detected, generating YAML...",
        segments
      );

      try {
        // Generate YAML from detected missing regions
        const yaml = generateYAMLFromMissingRegions(
          segments,
          missingRegions,
          currentProject.name
        );

        // Save YAML to project
        const result = await window.api.project.saveYAML(yaml);
        if (result.success) {
          setCurrentYAML(yaml);
          logger.log("✅ [Auto YAML] YAML file generated and saved");
          // Notify other components
          // bus.emit("project:yaml-generated", yaml);
        } else {
          throw new Error(result.error || "Failed to save YAML");
        }
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to generate YAML";
        setError(message);
        logger.error("❌ [Auto YAML] Error:", message);
      }
    };

    // Listen to missing regions ready event
    bus.on("repair:missing-regions-ready", handleMissingRegionsReady);

    return () => {
      bus.off("repair:missing-regions-ready", handleMissingRegionsReady);
    };
  }, [
    enabled,
    currentProject,
    missingRegions,
    repairSegments,
    setCurrentYAML,
    setError
  ]);
}

/**
 * Generate InpaintingYAML from detected missing regions
 */
function generateYAMLFromMissingRegions(
  segments: RepairSegment[],
  _missingRegions: MissingRegionInfo[],
  projectName: string
): InpaintingYAML {
  // Collect all unique chains from segments
  const allChainIds = new Set<string>();
  for (const segment of segments) {
    for (const chainId of segment.chainIds) {
      allChainIds.add(chainId);
    }
  }

  // Group segments by chain (a segment can belong to multiple chains)
  const chainMap = new Map<string, RepairSegment[]>();
  for (const chainId of allChainIds) {
    chainMap.set(
      chainId,
      segments.filter(segment => segment.chainIds.includes(chainId))
    );
  }

  // Build sequences array
  const sequences: InpaintingYAML["sequences"] = [];
  const inpainting: InpaintingYAML["inpainting"] = [];

  for (const [chainId, chainSegments] of chainMap.entries()) {
    // Extract full sequence from segments
    // For now, use a placeholder - in production, extract from structure
    const fullSequence = extractSequenceFromSegments();

    sequences.push({
      protein: {
        id: chainId,
        author_chain_id: chainId,
        full_sequence: fullSequence || "PLACEHOLDER_SEQUENCE",
        residue_mapping_ref: `mappings/residue_mapping_${chainId}.json`,
        msa: "empty"
      }
    });

    // Build residue ranges for inpainting
    // Only include regions from this specific chain
    const residueRanges = chainSegments.flatMap(segment => {
      // Filter regions to only include those from this chain
      return segment.missingRegions
        .filter(region => region.chainId === chainId)
        .map(region => {
          return {
            start: region.startResId,
            end: region.endResId,
            type:
              region.regionType === "complete"
                ? ("complete_missing" as const)
                : ("partial" as const),
            author_id_range:
              region.startAuthSeqId && region.endAuthSeqId
                ? ([region.startAuthSeqId, region.endAuthSeqId] as [
                    number,
                    number
                  ])
                : null,
            generated_ids: generateInsertionIds(
              region.startResId,
              region.endResId
            )
          };
        });
    });

    if (residueRanges.length > 0) {
      inpainting.push({
        input_cif: `structures/canonical/${projectName}_canonical_${chainId}.cif`,
        chain_id: chainId,
        residue_ranges: residueRanges,
        context: {
          include_neighbors: true,
          radius_Ang: 6.0,
          soft_shell_Ang: 3.0
        }
      });
    }
  }

  const yaml: InpaintingYAML = {
    version: 1,
    metadata: {
      original_pdb: `${projectName}_original.cif`,
      created: new Date().toISOString(),
      modified: new Date().toISOString()
    },
    sequences,
    inpainting
  };

  return yaml;
}

/**
 * Extract sequence string from segments
 * Sequence extraction from structure is not yet implemented
 */
function extractSequenceFromSegments(): string | null {
  // Placeholder - return null for now
  // In production, this should extract the actual sequence from the structure
  return null;
}

/**
 * Generate insertion IDs for missing residues
 */
function generateInsertionIds(startResId: number, endResId: number): string[] {
  const count = endResId - startResId + 1;
  const ids: string[] = [];

  for (let i = 1; i <= count; i++) {
    ids.push(`I${i}`);
  }

  return ids;
}
