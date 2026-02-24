// useSequenceViewer - Render Mol* sequence viewer in a custom location
import { useEffect, useRef } from "react";
import { useAtom } from "jotai";
import { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { createRoot, Root } from "react-dom/client";
import { PluginContextContainer } from "molstar/lib/mol-plugin-ui/plugin";
import { SequenceView } from "molstar/lib/mol-plugin-ui/sequence";
import {
  getChainOptions,
  getModelEntityOptions
} from "molstar/lib/mol-plugin-ui/sequence";
import { bus } from "../../lib/event-bus";
import { missingRegionsDetectedAtom } from "../../store/repair-atoms";
import {
  Structure,
  StructureElement,
  Unit
} from "molstar/lib/mol-model/structure";
import { StructureProperties } from "molstar/lib/mol-model/structure/structure/properties";
import { OrderedSet } from "molstar/lib/mol-data/int";
import { Loci } from "molstar/lib/mol-model/loci";

/**
 * Mol* sequence viewer hook with chain highlighting support
 * - Renders sequence viewer in custom container
 * - Listens to missing-region:focus events to highlight relevant chain residues
 */
export function useSequenceViewer(
  plugin: PluginUIContext | null,
  containerId: string
): void {
  const [missingRegions] = useAtom(missingRegionsDetectedAtom);
  const rootRef = useRef<Root | null>(null);
  const sequenceViewRef = useRef<SequenceView | null>(null);
  const isConvertingRef = useRef<boolean>(false);

  useEffect(() => {
    console.log(
      `[Sequence Viewer] Setting up sequence viewer (plugin=${!!plugin})`
    );

    if (!plugin) return;

    const container = document.getElementById(containerId);
    if (!container) {
      console.warn(`Sequence container ${containerId} not found`);
      return;
    }

    // Clear existing content
    container.innerHTML = "";

    // Render sequence viewer using Mol*'s React components
    const root = createRoot(container);
    rootRef.current = root;

    root.render(
      <PluginContextContainer plugin={plugin}>
        <SequenceView
          ref={(ref: SequenceView | null) => {
            sequenceViewRef.current = ref;
            console.log(`[Sequence Viewer] SequenceView ref set:`, !!ref);
          }}
        />
      </PluginContextContainer>
    );

    return () => {
      root.unmount();
      rootRef.current = null;
      sequenceViewRef.current = null;
    };
  }, [plugin, containerId]);

  // Listen to gap focus events to highlight chain in sequence viewer
  useEffect(() => {
    console.log(
      `[Sequence Viewer] Setting up missing-region:focus listener (plugin=${!!plugin}, gaps=${missingRegions.length})`
    );

    if (!plugin || missingRegions.length === 0) return;

    const handleGapFocus = (gapId: string): void => {
      console.log(
        `[Sequence Viewer] === missing-region:focus event received ===`
      );
      console.log(`[Sequence Viewer] Looking for gap ID: ${gapId}`);
      console.log(
        `[Sequence Viewer] Available gaps:`,
        missingRegions.map(g => g.regionId)
      );

      const gap = missingRegions.find(g => g.regionId === gapId);
      if (!gap) {
        console.warn(`[Sequence Viewer] Gap ${gapId} not found in gaps array`);
        return;
      }

      console.log(
        `[Sequence Viewer] Found gap: chainId=${gap.chainId}, startAuthSeqId=${gap.startAuthSeqId}, endAuthSeqId=${gap.endAuthSeqId}, type=${gap.regionType}`
      );

      // Get structure
      const structures = plugin.managers.structure.hierarchy.current.structures;
      console.log(
        `[Sequence Viewer] Structures available: ${structures?.length || 0}`
      );

      if (!structures || structures.length === 0) {
        console.warn(`[Sequence Viewer] No structures available`);
        return;
      }

      const structure = structures[0].cell.obj?.data;
      if (!structure) {
        console.warn(`[Sequence Viewer] Structure data is undefined`);
        return;
      }

      console.log(
        `[Sequence Viewer] Structure loaded, units: ${structure.units.length}`
      );

      // Find a residue near the gap to select and zoom to (using auth_seq_id)
      // Try to find the residue before the gap, or after if before doesn't exist
      let targetAuthSeqId: number | null = null;
      let targetInsCode = "";

      if (gap.startAuthSeqId && gap.startAuthSeqId > 1) {
        // Try residue before gap
        targetAuthSeqId = gap.startAuthSeqId - 1;
        targetInsCode = ""; // Usually the previous residue doesn't have ins code
        console.log(
          `[Sequence Viewer] Targeting residue before gap: auth_seq_id=${targetAuthSeqId}`
        );
      } else if (gap.endAuthSeqId) {
        // Try residue after gap
        targetAuthSeqId = gap.endAuthSeqId + 1;
        targetInsCode = "";
        console.log(
          `[Sequence Viewer] Targeting residue after gap: auth_seq_id=${targetAuthSeqId}`
        );
      }

      // If we found a target residue, select and zoom to it
      if (targetAuthSeqId !== null) {
        const targetLoci = findResidueLociByAuthSeqId(
          structure,
          gap.chainId,
          targetAuthSeqId,
          targetInsCode
        );

        if (targetLoci) {
          console.log(
            `[Sequence Viewer] Found target residue at auth_seq_id=${targetAuthSeqId}`
          );

          // Clear and select the target residue
          plugin.managers.structure.selection.clear();
          plugin.managers.interactivity.lociSelects.selectOnly(
            { loci: targetLoci },
            false
          );

          // Zoom to the residue
          const bounds = Loci.getBoundingSphere(targetLoci);
          if (bounds) {
            plugin.canvas3d?.camera.focus(bounds.center, 15, 500);
            console.log(
              `[Sequence Viewer] ✓ Zoomed to auth_seq_id=${targetAuthSeqId}`
            );
          }
        } else {
          console.warn(
            `[Sequence Viewer] Could not find residue with auth_seq_id=${targetAuthSeqId}`
          );
        }
      }

      // Try to change sequence viewer to show the target chain
      console.log(
        `[Sequence Viewer] Attempting to change sequence view to chain ${gap.chainId}`
      );
      console.log(
        `[Sequence Viewer] SequenceView ref available:`,
        !!sequenceViewRef.current
      );

      if (sequenceViewRef.current) {
        try {
          const sequenceView = sequenceViewRef.current;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const currentState = (sequenceView as any).state;
          console.log(`[Sequence Viewer] Current state:`, currentState);

          // Find the chain group ID for the target chain
          const modelEntityOptions = getModelEntityOptions(structure);
          console.log(
            `[Sequence Viewer] Model entity options:`,
            modelEntityOptions
          );

          for (const [modelEntityId] of modelEntityOptions) {
            const chainOptions = getChainOptions(structure, modelEntityId);
            console.log(
              `[Sequence Viewer] Chain options for entity ${modelEntityId}:`,
              chainOptions
            );

            for (const [chainGroupId, chainLabel] of chainOptions) {
              console.log(
                `[Sequence Viewer] Checking chain: ${chainLabel} (ID: ${chainGroupId})`
              );

              // Parse chain label to extract auth chain ID
              // Format: "A [auth B]" or just "A" if label and auth are the same
              const authMatch = chainLabel.match(/\[auth ([^\]]+)\]/);
              const authChainId = authMatch ? authMatch[1] : chainLabel.trim();

              console.log(
                `[Sequence Viewer] Extracted auth chain ID: ${authChainId}`
              );

              // Match against auth chain ID
              if (authChainId === gap.chainId) {
                console.log(
                  `[Sequence Viewer] Found matching chain! Setting state...`
                );

                // Call setState directly on the SequenceView instance
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                (sequenceView as any).setState({
                  modelEntityId,
                  chainGroupId,
                  mode: "single"
                });

                console.log(
                  `[Sequence Viewer] ✓ Changed sequence view to chain ${gap.chainId}`
                );
                return;
              }
            }
          }

          console.warn(
            `[Sequence Viewer] Could not find chain ${gap.chainId} in sequence options`
          );
        } catch (error) {
          console.error(
            `[Sequence Viewer] Error changing sequence view:`,
            error
          );
        }
      } else {
        console.warn(`[Sequence Viewer] SequenceView ref not available`);
      }
    };

    bus.on("missing-region:focus", handleGapFocus);
    console.log(`[Sequence Viewer] missing-region:focus listener registered`);

    return () => {
      bus.off("missing-region:focus", handleGapFocus);
      console.log(`[Sequence Viewer] Event listeners unregistered`);
    };
  }, [plugin, missingRegions]);

  // Handle sequence viewer selection - always use author id for zoom
  useEffect(() => {
    if (!plugin) return;

    const handleSelectionChange = async (): Promise<void> => {
      try {
        // Prevent infinite loop - if we're already converting, ignore this event
        if (isConvertingRef.current) {
          return;
        }

        // Get current selection
        const selectionEntries = Array.from(
          plugin.managers.structure.selection.entries.entries()
        );

        if (selectionEntries.length === 0) return;

        // Get structure
        const structures =
          plugin.managers.structure.hierarchy.current.structures;
        if (!structures || structures.length === 0) return;

        const structure = structures[0].cell.obj?.data as Structure | undefined;
        if (!structure) return;

        // Find the first selected residue and convert from label_seq_id to auth_seq_id
        for (const [, entry] of selectionEntries) {
          const selection = entry.selection;
          if (selection.elements.length === 0) continue;

          // Get the first element to find the residue
          const firstElement = selection.elements[0];
          if (!firstElement) continue;

          // Get the unit from the element
          const unit = firstElement.unit;
          if (!Unit.isAtomic(unit)) continue;

          // Get the first atom index from the selected indices
          const firstSelectedIndex = OrderedSet.getAt(firstElement.indices, 0);
          if (firstSelectedIndex === undefined) continue;

          // Create location and set unit and element
          // Use the pattern from useGapDetection.ts
          const loc = StructureElement.Location.create(structure);
          loc.unit = unit;
          // firstSelectedIndex is already a UnitIndex from the selection
          loc.element = firstSelectedIndex as any; // eslint-disable-line @typescript-eslint/no-explicit-any

          // Get chain and residue IDs
          const chainId = StructureProperties.chain.auth_asym_id(loc);
          const labelSeqId = StructureProperties.residue.label_seq_id(loc);
          const authSeqId = StructureProperties.residue.auth_seq_id(loc);
          const insCode =
            StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";

          // If label_seq_id and auth_seq_id are different, we need to convert
          if (labelSeqId !== authSeqId) {
            console.log(
              `[Sequence Viewer] Converting selection from label_seq_id=${labelSeqId} to auth_seq_id=${authSeqId}`
            );

            // Set converting flag to prevent infinite loop
            isConvertingRef.current = true;

            try {
              // Find all residues with the same auth_seq_id in this chain
              const targetLoci = findResidueLociByAuthSeqId(
                structure,
                chainId,
                authSeqId,
                insCode
              );

              if (targetLoci) {
                // Clear current selection
                await plugin.managers.structure.selection.clear();

                // Select using auth_seq_id
                plugin.managers.interactivity.lociSelects.selectOnly(
                  { loci: targetLoci },
                  false
                );

                // Zoom to the residue
                const bounds = Loci.getBoundingSphere(targetLoci);
                if (bounds) {
                  plugin.canvas3d?.camera.focus(bounds.center, 8, 500);
                }

                console.log(
                  `[Sequence Viewer] ✓ Converted selection to auth_seq_id=${authSeqId} and zoomed`
                );
              }
            } finally {
              // Reset converting flag after a short delay to allow selection to settle
              setTimeout(() => {
                isConvertingRef.current = false;
              }, 100);
            }
          }

          // Only process the first selected residue
          return;
        }
      } catch (error) {
        console.error(
          "[Sequence Viewer] Error handling selection change:",
          error
        );
        isConvertingRef.current = false;
      }
    };

    // Subscribe to selection changes
    const subscription =
      plugin.managers.structure.selection.events.changed.subscribe(() => {
        void handleSelectionChange();
      });

    return () => {
      subscription.unsubscribe();
    };
  }, [plugin]);
}

/**
 * Find residue loci by auth_seq_id
 */
function findResidueLociByAuthSeqId(
  structure: Structure,
  chainId: string,
  authSeqId: number,
  insCode: string
): StructureElement.Loci | null {
  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;

    const elements: StructureElement.UnitIndex[] = [];

    for (let i = 0; i < unit.elements.length; i++) {
      const loc = StructureElement.Location.create(
        structure,
        unit,
        unit.elements[i]
      );
      const elemChainId = StructureProperties.chain.auth_asym_id(loc);
      const elemAuthSeqId = StructureProperties.residue.auth_seq_id(loc);
      const elemInsCode =
        StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";

      if (
        elemChainId === chainId &&
        elemAuthSeqId === authSeqId &&
        elemInsCode === insCode
      ) {
        elements.push(i as StructureElement.UnitIndex);
      }
    }

    if (elements.length > 0) {
      return StructureElement.Loci(structure, [
        { unit, indices: OrderedSet.ofSortedArray(elements) }
      ]);
    }
  }

  return null;
}
