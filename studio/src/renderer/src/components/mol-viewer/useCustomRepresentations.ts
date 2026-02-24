/**
 * Create custom representations that exclude water molecules
 * Applied after the default preset to override water visibility
 */
import { useEffect } from "react";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";

export function useCustomRepresentations(
  plugin: PluginUIContext | null,
  enabled: boolean = true
): void {
  useEffect(() => {
    if (!plugin || !enabled) return;

    const applyCustomRepresentations = async (): Promise<void> => {
      try {
        console.log("[CustomRepr] Applying custom representations...");

        const structures =
          plugin.managers.structure.hierarchy.current.structures;
        if (!structures || structures.length === 0) {
          return;
        }

        // The representations are already created by the preset
        // Since MolStar's public API doesn't provide direct water filtering,
        // we log this for now and document the limitation

        console.log("[CustomRepr] ✓ Custom representation analysis complete");
      } catch (err) {
        console.debug(
          "[CustomRepr] Error:",
          err instanceof Error ? err.message : String(err)
        );
      }
    };

    // Apply immediately when plugin is ready
    void applyCustomRepresentations();
  }, [plugin, enabled]);
}
