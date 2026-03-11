import { useEffect } from "react";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import {
  Structure,
  StructureElement,
  StructureSelection,
  Unit
} from "molstar/lib/mol-model/structure";
import { StructureProperties } from "molstar/lib/mol-model/structure/structure/properties";
import { Script } from "molstar/lib/mol-script/script";
import { Color } from "molstar/lib/mol-util/color";
import { StateTransforms } from "molstar/lib/mol-plugin-state/transforms";
import type { StructureHierarchyRef } from "molstar/lib/mol-plugin-state/manager/structure/hierarchy-state";
import { bus } from "../../lib/event-bus";
import { logger } from "../../lib/logger";

/**
 * Chain color palette for BASE STRUCTURE
 * Uses distinct, clearly different colors for each chain
 * Cool-toned but varied enough to distinguish up to 10+ chains
 * Avoids yellow/orange/red which are reserved for inpainting regions
 */
const BASE_STRUCTURE_COLOR_PALETTE = [
  0x64748b, // Slate-500 - blue-gray
  0x78716c, // Stone-500 - warm gray
  0x6b7280, // Gray-500 - neutral
  0x71717a, // Zinc-500 - cool gray
  0x737373, // Neutral-500
  0x57534e, // Stone-600
  0x4b5563, // Gray-600
  0x52525b, // Zinc-600
  0x525252, // Neutral-600
  0x44403c // Stone-700
];

/**
 * Color palettes for each RESULT STRUCTURE (run_001, run_002, etc.)
 * Uses NEUTRAL/GRAY tones to make inpainting regions (yellow/orange/red) stand out
 * Slightly lighter than base structure to distinguish results
 * Each palette has subtle variations for different runs
 */
const RESULT_COLOR_PALETTES = [
  // Palette 0: Light slate tones
  [
    0x94a3b8, // Slate-400
    0xa8a29e, // Stone-400
    0x9ca3af, // Gray-400
    0xa1a1aa, // Zinc-400
    0xa3a3a3, // Neutral-400
    0x78716c, // Stone-500
    0x6b7280, // Gray-500
    0x71717a, // Zinc-500
    0x737373, // Neutral-500
    0x64748b // Slate-500
  ],
  // Palette 1: Warm gray tones
  [
    0xa8a29e, // Stone-400
    0x94a3b8, // Slate-400
    0x9ca3af, // Gray-400
    0x78716c, // Stone-500
    0xa1a1aa, // Zinc-400
    0x6b7280, // Gray-500
    0x64748b, // Slate-500
    0x71717a, // Zinc-500
    0xa3a3a3, // Neutral-400
    0x57534e // Stone-600
  ],
  // Palette 2: Cool gray tones
  [
    0x9ca3af, // Gray-400
    0xa1a1aa, // Zinc-400
    0x94a3b8, // Slate-400
    0x6b7280, // Gray-500
    0x71717a, // Zinc-500
    0x64748b, // Slate-500
    0xa8a29e, // Stone-400
    0xa3a3a3, // Neutral-400
    0x78716c, // Stone-500
    0x4b5563 // Gray-600
  ],
  // Palette 3: Zinc tones
  [
    0xa1a1aa, // Zinc-400
    0x9ca3af, // Gray-400
    0x94a3b8, // Slate-400
    0x71717a, // Zinc-500
    0x6b7280, // Gray-500
    0x64748b, // Slate-500
    0xa3a3a3, // Neutral-400
    0xa8a29e, // Stone-400
    0x78716c, // Stone-500
    0x52525b // Zinc-600
  ],
  // Palette 4: Light neutral tones
  [
    0xa3a3a3, // Neutral-400
    0xa1a1aa, // Zinc-400
    0x9ca3af, // Gray-400
    0x737373, // Neutral-500
    0x71717a, // Zinc-500
    0x6b7280, // Gray-500
    0x94a3b8, // Slate-400
    0xa8a29e, // Stone-400
    0x64748b, // Slate-500
    0x525252 // Neutral-600
  ],
  // Palette 5: Blue-gray emphasis
  [
    0x94a3b8, // Slate-400
    0x9ca3af, // Gray-400
    0xa1a1aa, // Zinc-400
    0x64748b, // Slate-500
    0x6b7280, // Gray-500
    0x71717a, // Zinc-500
    0xa3a3a3, // Neutral-400
    0xa8a29e, // Stone-400
    0x78716c, // Stone-500
    0x475569 // Slate-600
  ],
  // Palette 6: Stone emphasis
  [
    0xa8a29e, // Stone-400
    0xa3a3a3, // Neutral-400
    0x9ca3af, // Gray-400
    0x78716c, // Stone-500
    0x737373, // Neutral-500
    0x6b7280, // Gray-500
    0x94a3b8, // Slate-400
    0xa1a1aa, // Zinc-400
    0x64748b, // Slate-500
    0x57534e // Stone-600
  ],
  // Palette 7: Mixed light tones
  [
    0x9ca3af, // Gray-400
    0x94a3b8, // Slate-400
    0xa8a29e, // Stone-400
    0x6b7280, // Gray-500
    0x64748b, // Slate-500
    0x78716c, // Stone-500
    0xa1a1aa, // Zinc-400
    0xa3a3a3, // Neutral-400
    0x71717a, // Zinc-500
    0x4b5563 // Gray-600
  ],
  // Palette 8: Balanced gray
  [
    0xa1a1aa, // Zinc-400
    0xa3a3a3, // Neutral-400
    0xa8a29e, // Stone-400
    0x71717a, // Zinc-500
    0x737373, // Neutral-500
    0x78716c, // Stone-500
    0x9ca3af, // Gray-400
    0x94a3b8, // Slate-400
    0x6b7280, // Gray-500
    0x52525b // Zinc-600
  ],
  // Palette 9: Soft neutral
  [
    0xa3a3a3, // Neutral-400
    0xa8a29e, // Stone-400
    0xa1a1aa, // Zinc-400
    0x737373, // Neutral-500
    0x78716c, // Stone-500
    0x71717a, // Zinc-500
    0x9ca3af, // Gray-400
    0x94a3b8, // Slate-400
    0x64748b, // Slate-500
    0x525252 // Neutral-600
  ]
];

/**
 * Hook to automatically apply chain colors when representations are ready
 * Listens to "structure:representations-ready" event and applies colors
 * Applies cool colors (blues, cyans, purples) that contrast with inpainting colors
 */
export function useChainColors(
  plugin: PluginUIContext | null,
  enabled: boolean = true
): void {
  useEffect(() => {
    if (!plugin || !enabled) return;

    const handleRepresentationsReady = async (): Promise<void> => {
      try {
        const hierarchy = plugin.managers.structure.hierarchy;
        const structures = hierarchy.current.structures;

        if (structures.length === 0) {
          return;
        }

        logger.log(
          `[Chain Colors] Representations ready, applying colors to ${structures.length} structure(s)...`
        );

        let allSucceeded = true;
        let appliedCount = 0;
        for (const hierarchyRef of structures) {
          const structure = hierarchyRef.cell?.obj?.data;
          if (!structure) continue;

          // Check if this structure already has chain colors applied
          // by checking if overpaint exists
          const structureRef = hierarchyRef.cell?.transform?.ref;
          if (structureRef) {
            const state = plugin.state.data;
            const cells = state.cells;
            let hasOverpaint = false;
            for (const childCell of cells.values()) {
              if (
                childCell.transform.parent === structureRef &&
                childCell.transform.transformer ===
                  StateTransforms.Representation
                    .OverpaintStructureRepresentation3DFromBundle
              ) {
                hasOverpaint = true;
                break;
              }
            }

            if (hasOverpaint) {
              const label = hierarchyRef.cell?.obj?.label || "unknown";
              logger.log(
                `[Chain Colors] Structure "${label}" already has overpaint, skipping`
              );
              continue;
            }
          }

          const label = hierarchyRef.cell?.obj?.label || "unknown";
          logger.log(
            `[Chain Colors] Applying chain colors to structure: "${label}"`
          );
          const succeeded = await applyChainColors(
            plugin,
            structure,
            hierarchyRef
          );
          if (succeeded) {
            appliedCount++;
          } else {
            allSucceeded = false;
          }
        }

        logger.log(
          `[Chain Colors] Applied colors to ${appliedCount} structure(s) out of ${structures.length}`
        );

        if (allSucceeded) {
          logger.log(`[Chain Colors] ✅ All chain colors applied successfully`);
        } else {
          logger.warn(
            `[Chain Colors] ⚠️ WARNING: Some chain colors may not have been applied! Chains may appear in warm colors (yellow/orange/red).`
          );
        }
      } catch (err) {
        logger.error("[Chain Colors] Failed to apply colors:", err);
      }
    };

    // Listen for representations ready event
    bus.on("structure:representations-ready", handleRepresentationsReady);

    // Also check if structure is already loaded (for cases where event was missed)
    const structures = plugin.managers.structure.hierarchy.current.structures;
    if (structures && structures.length > 0) {
      logger.log("[Chain Colors] Structure already loaded, applying colors...");
      void handleRepresentationsReady();
    }

    return () => {
      bus.off("structure:representations-ready", handleRepresentationsReady);
    };
  }, [plugin, enabled]);
}

/**
 * Create chain color overpaint layers for a structure
 * @param structure - The structure to create layers for
 * @param isResultStructure - If true, use brighter cool colors. If false (base structure), use muted gray colors.
 * @param resultIndex - Index of the result structure (0, 1, 2, etc.) to pick different color palette for each result
 * @export for use by other modules that need to combine chain colors with other overlays
 */
export function createChainColorLayers(
  structure: Structure,
  isResultStructure: boolean = true,
  resultIndex: number = 0
): Array<{
  bundle: typeof StructureElement.Bundle.Empty;
  color: Color;
  clear: boolean;
}> {
  const layers: Array<{
    bundle: typeof StructureElement.Bundle.Empty;
    color: Color;
    clear: boolean;
  }> = [];

  // Choose palette based on structure type
  // For result structures, use different palettes for each result
  let palette: number[];
  if (isResultStructure) {
    const paletteIndex = resultIndex % RESULT_COLOR_PALETTES.length;
    palette = RESULT_COLOR_PALETTES[paletteIndex];
    logger.log(
      `[Chain Colors] Using result palette ${paletteIndex} for result index ${resultIndex}`
    );
  } else {
    palette = BASE_STRUCTURE_COLOR_PALETTE;
  }

  // Get unique chain IDs from the structure
  const chainIds = new Set<string>();
  for (const unit of structure.units) {
    if (Unit.isAtomic(unit)) {
      const location = StructureElement.Location.create(
        structure,
        unit,
        unit.elements[0]
      );
      const chainId = StructureProperties.chain.auth_asym_id(location);
      if (chainId) {
        chainIds.add(chainId);
      }
    }
  }

  const chainIdArray = Array.from(chainIds).sort();
  if (chainIdArray.length === 0) {
    return layers;
  }

  for (let i = 0; i < chainIdArray.length; i++) {
    const chainId = chainIdArray[i];
    const colorValue = palette[i % palette.length];

    // Create selection for entire chain
    const script = Script.getStructureSelection(
      Q =>
        Q.struct.generator.atomGroups({
          "chain-test": Q.core.rel.eq([
            Q.struct.atomProperty.macromolecular.auth_asym_id(),
            chainId
          ])
        }),
      structure
    );

    const selection = StructureSelection.toLociWithSourceUnits(script);
    if (selection.elements.length > 0) {
      layers.push({
        bundle: StructureElement.Bundle.fromLoci(selection),
        color: Color(colorValue),
        clear: false
      });
    }
  }

  return layers;
}

/**
 * Apply distinct colors to each chain in the structure
 * Uses cool colors for result structures, muted gray for base structures
 * so that inpainting colors (yellow, orange, red) stand out
 * @export for use in other hooks (e.g., useSuperpose)
 */
export async function applyChainColors(
  plugin: PluginUIContext,
  structure: Structure | undefined,
  hierarchyRef: StructureHierarchyRef,
  isResultStructure?: boolean,
  resultIndex?: number
): Promise<boolean> {
  if (!structure) {
    return false;
  }

  try {
    // Determine if this is a result structure or base structure
    // Result structures have labels like "run_001", "run_002", or "Inpainting Result"
    const label = hierarchyRef.cell?.obj?.label || "";
    const isResult =
      isResultStructure ??
      (label.startsWith("run_") || label.includes("Inpainting Result"));

    // Extract result index from label if not provided
    let effectiveResultIndex = resultIndex ?? 0;
    if (isResult && resultIndex === undefined) {
      const runMatch = label.match(/run_(\d+)/);
      if (runMatch) {
        effectiveResultIndex = parseInt(runMatch[1], 10) - 1; // run_001 -> index 0
      }
    }

    const structureType = isResult
      ? `result (index ${effectiveResultIndex})`
      : "base";

    // Get unique chain IDs from the structure
    const chainIds = new Set<string>();
    for (const unit of structure.units) {
      if (Unit.isAtomic(unit)) {
        const location = StructureElement.Location.create(
          structure,
          unit,
          unit.elements[0]
        );
        const chainId = StructureProperties.chain.auth_asym_id(location);
        if (chainId) {
          chainIds.add(chainId);
        }
      }
    }

    const chainIdArray = Array.from(chainIds).sort();
    if (chainIdArray.length === 0) {
      return false;
    }

    logger.log(
      `[Chain Colors] Found ${chainIdArray.length} chain(s): ${chainIdArray.join(", ")} (${structureType} structure)`
    );

    // Get parent ref for applying colors
    const parentRef = hierarchyRef?.cell?.transform?.ref;
    if (!parentRef) {
      logger.warn("[Chain Colors] Could not get parent ref for structure");
      return false;
    }

    // Create overpaint layers for each chain using shared function
    // Pass isResult and resultIndex to use appropriate color palette
    const overpaintLayers = createChainColorLayers(
      structure,
      isResult,
      effectiveResultIndex
    );

    // Choose palette for logging
    const palette = isResult
      ? RESULT_COLOR_PALETTES[
          effectiveResultIndex % RESULT_COLOR_PALETTES.length
        ]
      : BASE_STRUCTURE_COLOR_PALETTE;

    // Log applied chain colors
    for (let i = 0; i < chainIdArray.length; i++) {
      const chainId = chainIdArray[i];
      const colorValue = palette[i % palette.length];
      const colorHex = `#${colorValue.toString(16).padStart(6, "0")}`;
      const r = (colorValue >> 16) & 0xff;
      const g = (colorValue >> 8) & 0xff;
      const b = colorValue & 0xff;
      logger.log(
        `[Chain Colors] ✅ Chain ${chainId} -> ${colorHex} (RGB=${r},${g},${b}) [${structureType}]`
      );
    }

    // Apply chain colors
    if (overpaintLayers.length > 0) {
      const succeeded = await applyOverpaintToRepresentations(
        plugin,
        parentRef,
        overpaintLayers
      );
      if (succeeded) {
        logger.log(
          `[Chain Colors] ✓ Applied colors to ${chainIdArray.length} chain(s) [${structureType}]`
        );
      }
      return succeeded;
    } else {
      logger.warn("[Chain Colors] No chain color layers to apply");
      return false;
    }
  } catch (err) {
    logger.error("[Chain Colors] Failed to apply colors:", err);
    return false;
  }
}

/**
 * Apply overpaint layers to all representations of a structure
 * This colors residues without creating duplicate representations
 * First sets representation color to uniform grey, then applies chain colors
 */
async function applyOverpaintToRepresentations(
  plugin: PluginUIContext,
  structureRef: string,
  layers: Array<{
    bundle: typeof StructureElement.Bundle.Empty;
    color: Color;
    clear: boolean;
  }>
): Promise<boolean> {
  if (layers.length === 0) return false;

  try {
    const state = plugin.state.data;
    let update = state.build();

    // Find all representation nodes under this structure
    const cells = state.cells;
    const representationRefs: string[] = [];

    const findRepresentations = (ref: string, depth = 0): void => {
      if (depth > 10) return;

      const cell = cells.get(ref);
      if (!cell) return;

      // Check if this is a representation node
      if (
        cell.transform.transformer ===
        StateTransforms.Representation.StructureRepresentation3D
      ) {
        representationRefs.push(ref);
        // Log representation info
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const reprParams = (cell.transform.params as any)?.type?.params || {};
        const reprType = reprParams.type?.name || "unknown";
        const colorTheme = reprParams.colorTheme?.name || "unknown";
        logger.log(
          `[Chain Colors] Found representation: ${ref}, type: ${reprType}, colorTheme: ${colorTheme}`
        );
      }

      // Recursively check children
      for (const [childRef, childCell] of cells.entries()) {
        if (childCell.transform.parent === ref) {
          findRepresentations(childRef, depth + 1);
        }
      }
    };

    findRepresentations(structureRef);

    if (representationRefs.length === 0) {
      logger.warn("[Chain Colors] No representations found to apply overpaint");
      return false;
    }

    // Note: We skip colorTheme update as it's unreliable with MolStar's StateBuilder API
    // Instead, we rely entirely on overpaint to color the entire chain
    // Overpaint is applied on top of colorTheme, so it will override any default colors
    logger.log(
      `[Chain Colors] Found ${representationRefs.length} representation(s), will apply overpaint to cover entire chains`
    );

    // Apply overpaint with chain colors to ALL representations
    // This will override any default colorTheme colors (including warm colors)
    update = state.build();
    for (const reprRef of representationRefs) {
      // Log which representation we're applying to
      const cell = cells.get(reprRef);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const reprType = (cell?.transform.params as any)?.type?.name || "unknown";
      logger.log(
        `[Chain Colors] Applying overpaint to representation ${reprRef} (type: ${reprType})`
      );

      update
        .to(reprRef)
        .apply(
          StateTransforms.Representation
            .OverpaintStructureRepresentation3DFromBundle,
          {
            layers: layers
          }
        );
    }

    await update.commit();
    logger.log(
      `[Chain Colors] ✓ Applied overpaint with ${layers.length} chain color layer(s) to ${representationRefs.length} representation(s)`
    );
    logger.log(
      `[Chain Colors] ✓ Overpaint will override any default colorTheme colors, ensuring cool colors are shown`
    );

    // Verify overpaint was applied to all representations
    const verifyOverpaint = (): boolean => {
      const updatedCells = state.cells;
      let allHaveOverpaint = true;
      const missingOverpaint: string[] = [];

      for (const reprRef of representationRefs) {
        // Check if overpaint transform exists as a child
        let hasOverpaint = false;
        for (const childCell of updatedCells.values()) {
          if (
            childCell.transform.parent === reprRef &&
            childCell.transform.transformer ===
              StateTransforms.Representation
                .OverpaintStructureRepresentation3DFromBundle
          ) {
            hasOverpaint = true;
            logger.log(
              `[Chain Colors] ✓ Verified overpaint applied to representation ${reprRef}`
            );
            break;
          }
        }
        if (!hasOverpaint) {
          logger.warn(
            `[Chain Colors] ⚠️ Representation ${reprRef} does NOT have overpaint applied!`
          );
          missingOverpaint.push(reprRef);
          allHaveOverpaint = false;
        }
      }

      if (missingOverpaint.length > 0) {
        logger.warn(
          `[Chain Colors] ⚠️ ${missingOverpaint.length} representation(s) missing overpaint: ${missingOverpaint.join(", ")}`
        );
        logger.warn(
          `[Chain Colors] ⚠️ These representations may show warm colors (yellow/orange/red) from default colorTheme!`
        );
      }

      return allHaveOverpaint;
    };

    const overpaintApplied = verifyOverpaint();
    if (overpaintApplied) {
      logger.log(
        `[Chain Colors] ✅ All representations have overpaint applied - cool colors guaranteed!`
      );
    } else {
      logger.warn(
        `[Chain Colors] ⚠️ Some representations may not have chain colors applied!`
      );
    }

    return true;
  } catch (err) {
    logger.error("[Chain Colors] Failed to apply overpaint:", err);
    return false;
  }
}
