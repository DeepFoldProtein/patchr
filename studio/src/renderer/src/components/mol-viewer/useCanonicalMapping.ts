// useCanonicalMapping.ts - Generate mapping after missing region detection
import { useEffect } from "react";
import { useAtom } from "jotai";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import {
  Structure,
  StructureElement,
  Unit
} from "molstar/lib/mol-model/structure";
import { StructureProperties } from "molstar/lib/mol-model/structure/structure/properties";
import { bus } from "../../lib/event-bus";
import { logger } from "../../lib/logger";
import { missingRegionsDetectedAtom } from "../../store/repair-atoms";
import { useCurrentProject, useProjectStore } from "../../store/project-store";
import type { ResidueMapping } from "../../types/project";
import type { RepairSegment, MissingRegionInfo } from "../../types";

/**
 * Hook that generates mapping after missing region detection
 */
export function useCanonicalMapping(
  plugin: PluginUIContext | null,
  enabled: boolean = true
): void {
  const [missingRegions] = useAtom(missingRegionsDetectedAtom);
  const currentProject = useCurrentProject();
  const setError = useProjectStore(state => state.setError);

  useEffect(() => {
    if (!enabled || !currentProject || !plugin) return;

    const handleMissingRegionsReady = async (
      segments: RepairSegment[]
    ): Promise<void> => {
      logger.log(
        "[Canonical Mapping] Missing regions detected, generating mapping...",
        segments
      );

      try {
        // Get current structure
        const structures =
          plugin.managers.structure.hierarchy.current.structures;
        if (!structures || structures.length === 0) {
          logger.warn("[Canonical Mapping] No structure loaded");
          return;
        }

        const structureRef = structures[0];
        const structure = structureRef.cell.obj?.data as Structure | undefined;
        if (!structure) {
          logger.warn("[Canonical Mapping] Structure data not available");
          return;
        }

        // Generate mapping from structure and missing regions
        generateMapping(structure, missingRegions);
        logger.log("✅ [Canonical Mapping] Mapping generated");
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to generate mapping";
        setError(message);
        logger.error("❌ [Canonical Mapping] Error:", message);
      }
    };

    // Listen to missing regions ready event
    bus.on("repair:missing-regions-ready", handleMissingRegionsReady);

    return () => {
      bus.off("repair:missing-regions-ready", handleMissingRegionsReady);
    };
  }, [enabled, currentProject, plugin, missingRegions, setError]);
}

/**
 * Generate ResidueMapping from structure and missing regions
 */
function generateMapping(
  structure: Structure,
  missingRegions: MissingRegionInfo[]
): ResidueMapping {
  const chainMapping: ResidueMapping["chain_mapping"] = {};
  const residueMappings: ResidueMapping["residue_mappings"] = {};

  // Group missing regions by chain
  const missingByChain = new Map<string, MissingRegionInfo[]>();
  for (const region of missingRegions) {
    if (!missingByChain.has(region.chainId)) {
      missingByChain.set(region.chainId, []);
    }
    missingByChain.get(region.chainId)!.push(region);
  }

  // Process each chain
  const processedChains = new Set<string>();

  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;

    const location = StructureElement.Location.create(
      structure,
      unit,
      unit.elements[0]
    );
    const chainId = StructureProperties.chain.auth_asym_id(location);

    if (processedChains.has(chainId)) continue;
    processedChains.add(chainId);

    // Chain mapping
    chainMapping[chainId] = {
      author_id: chainId,
      canonical_id: chainId
    };

    // Collect all residues in this chain
    const residues: Array<{
      labelSeqId: number;
      authSeqId: number;
      insCode: string;
    }> = [];

    // One Location per unit, mutated in place; a Set for dedupe. Allocating a
    // Location per atom and scanning `residues` per atom made this O(atoms x
    // residues) and blocked the UI on large chains.
    const seen = new Set<string>();
    const loc = StructureElement.Location.create(structure, unit);
    for (let i = 0; i < unit.elements.length; i++) {
      loc.element = unit.elements[i];
      const labelSeqId = StructureProperties.residue.label_seq_id(loc);
      const authSeqId = StructureProperties.residue.auth_seq_id(loc);
      const insCode = StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";

      const key = `${labelSeqId}|${authSeqId}|${insCode}`;
      if (seen.has(key)) continue;
      seen.add(key);
      residues.push({ labelSeqId, authSeqId, insCode });
    }

    // Sort by label_seq_id
    residues.sort((a, b) => a.labelSeqId - b.labelSeqId);

    // First residue per label_seq_id, matching the previous `find` semantics.
    const residueByLabelSeqId = new Map<number, (typeof residues)[number]>();
    for (const residue of residues) {
      if (!residueByLabelSeqId.has(residue.labelSeqId)) {
        residueByLabelSeqId.set(residue.labelSeqId, residue);
      }
    }

    // Get missing regions for this chain
    const chainMissingRegions = missingByChain.get(chainId) || [];

    // Build residue mappings with canonical indexing
    // Canonical index includes missing residues in sequence order
    const chainResidueMappings: ResidueMapping["residue_mappings"][string] = {};
    let canonicalIndex = 1;

    // Sort missing regions by start position
    const sortedMissingRegions = [...chainMissingRegions].sort(
      (a, b) => a.startResId - b.startResId
    );

    // Create a map of missing region positions for quick lookup
    const missingRegionMap = new Map<number, MissingRegionInfo>();
    for (const region of sortedMissingRegions) {
      for (let pos = region.startResId; pos <= region.endResId; pos++) {
        missingRegionMap.set(pos, region);
      }
    }

    // Process residues in canonical order (label_seq_id order)
    // Insert missing residues at their positions
    // Folded rather than spread: `Math.max(...arr)` throws RangeError once the
    // array exceeds the argument limit, which large chains do.
    let maxResId = 0;
    for (const r of residues) {
      if (r.labelSeqId > maxResId) maxResId = r.labelSeqId;
    }
    for (const r of sortedMissingRegions) {
      if (r.endResId > maxResId) maxResId = r.endResId;
    }

    for (let pos = 1; pos <= maxResId; pos++) {
      // Check if there's a missing region at this position
      const missingRegion = missingRegionMap.get(pos);
      if (missingRegion) {
        // This is a missing residue position
        const offsetInRegion = pos - missingRegion.startResId;
        const generatedId = `I${offsetInRegion + 1}`;
        const missingKey = `null_${missingRegion.regionId}_${offsetInRegion}`;

        chainResidueMappings[missingKey] = {
          canonical_index: canonicalIndex,
          author_id: null,
          generated_id: generatedId,
          type:
            missingRegion.regionType === "complete"
              ? "complete_missing"
              : "partial"
        };

        canonicalIndex++;
      } else {
        // Find existing residue at this label_seq_id
        const residue = residueByLabelSeqId.get(pos);
        if (residue) {
          const authResIdKey = residue.insCode
            ? `${residue.authSeqId}${residue.insCode}`
            : String(residue.authSeqId);

          chainResidueMappings[authResIdKey] = {
            canonical_index: canonicalIndex,
            author_id: String(residue.authSeqId),
            insertion_code: residue.insCode || undefined
          };

          canonicalIndex++;
        }
      }
    }

    residueMappings[chainId] = chainResidueMappings;
  }

  return {
    chain_mapping: chainMapping,
    residue_mappings: residueMappings
  };
}
