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
      console.log(
        "[Canonical Mapping] Missing regions detected, generating mapping...",
        segments
      );

      try {
        // Get current structure
        const structures =
          plugin.managers.structure.hierarchy.current.structures;
        if (!structures || structures.length === 0) {
          console.warn("[Canonical Mapping] No structure loaded");
          return;
        }

        const structureRef = structures[0];
        const structure = structureRef.cell.obj?.data as Structure | undefined;
        if (!structure) {
          console.warn("[Canonical Mapping] Structure data not available");
          return;
        }

        // Generate mapping from structure and missing regions
        const mapping = generateMapping(structure, missingRegions);
        console.log("✅ [Canonical Mapping] Mapping generated");
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to generate mapping";
        setError(message);
        console.error("❌ [Canonical Mapping] Error:", message);
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

    // Convert elements to array for iteration
    const elementsArray = Array.from(unit.elements);
    for (const element of elementsArray) {
      const loc = StructureElement.Location.create(structure, unit, element);
      const labelSeqId = StructureProperties.residue.label_seq_id(loc);
      const authSeqId = StructureProperties.residue.auth_seq_id(loc);
      const insCode = StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";

      // Check if we already have this residue
      const existing = residues.find(
        r =>
          r.labelSeqId === labelSeqId &&
          r.authSeqId === authSeqId &&
          r.insCode === insCode
      );
      if (!existing) {
        residues.push({ labelSeqId, authSeqId, insCode });
      }
    }

    // Sort by label_seq_id
    residues.sort((a, b) => a.labelSeqId - b.labelSeqId);

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
    const maxResId = Math.max(
      ...residues.map(r => r.labelSeqId),
      ...sortedMissingRegions.map(r => r.endResId)
    );

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
        const residue = residues.find(r => r.labelSeqId === pos);
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
