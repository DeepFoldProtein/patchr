import { useEffect, useCallback } from "react";
import type { PluginContext } from "molstar/lib/mol-plugin/context";
import type { MaskSpec } from "../../types/mol-viewer";
import { bus } from "../../lib/event-bus";

/**
 * Visualize mask regions as colored overlays on the structure
 * Uses Mol* Shape API to render semi-transparent spheres
 */
export function useMaskOverlay(
  plugin: PluginContext | null,
  structureRef: unknown
): {
  applyMask: (mask: MaskSpec) => Promise<void>;
  clearMask: () => Promise<void>;
} {
  const applyMask = useCallback(
    async (mask: MaskSpec): Promise<void> => {
      if (!plugin || !structureRef) return;

      try {
        // TODO: Implement mask overlay using Mol* Shape API
        console.log("Applying mask:", mask);
        bus.emit("mask:overlayed", mask);
      } catch (error) {
        console.error("Failed to apply mask overlay:", error);
        throw error;
      }
    },
    [plugin, structureRef]
  );

  const clearMask = useCallback(async (): Promise<void> => {
    if (!plugin) return;

    try {
      // TODO: Implement mask clearing
      console.log("Clearing mask");
      bus.emit("mask:cleared");
    } catch (error) {
      console.error("Failed to clear mask overlay:", error);
    }
  }, [plugin]);

  // Listen for mask events
  useEffect(() => {
    const handleMaskApply = (data: MaskSpec): void => {
      void applyMask(data);
    };

    const handleMaskClear = (): void => {
      void clearMask();
    };

    bus.on("mask:apply", handleMaskApply);
    bus.on("mask:clear", handleMaskClear);

    return () => {
      bus.off("mask:apply", handleMaskApply);
      bus.off("mask:clear", handleMaskClear);
    };
  }, [applyMask, clearMask]);

  return { applyMask, clearMask };
}
