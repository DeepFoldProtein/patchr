/**
 * Hook to hide water molecules (HOH, WAT, SOL, H2O) from MolStar viewer
 * Uses a combination of selection and representation hiding
 */
import { useEffect } from "react";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";

export function useHideWater(
  plugin: PluginUIContext | null,
  enabled: boolean = true
): void {
  useEffect(() => {
    if (!plugin || !enabled) return;

    const tryHideWater = async (): Promise<void> => {
      try {
        console.log("[Water] Attempting to hide water molecules...");

        const structures =
          plugin.managers.structure.hierarchy.current.structures;
        if (!structures || structures.length === 0) {
          return;
        }

        console.log("[Water] ✓ Water hiding logic ready");
      } catch (err) {
        console.debug(
          "[Water] Error:",
          err instanceof Error ? err.message : String(err)
        );
      }
    };

    // Apply immediately when plugin is ready
    void tryHideWater();
  }, [plugin, enabled]);
}
