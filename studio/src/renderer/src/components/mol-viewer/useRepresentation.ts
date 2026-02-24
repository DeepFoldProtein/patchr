import { useEffect } from "react";
import { useAtom } from "jotai";
import type { PluginContext } from "molstar/lib/mol-plugin/context";
import { viewerSettingsAtom } from "../../store/mol-viewer-atoms";

/**
 * Apply visual representations to the loaded structure
 * Manages Cartoon/Surface/Ball-and-Stick styles with color schemes
 */
export function useRepresentation(
  plugin: PluginContext | null,
  structureRef: unknown
): void {
  const [settings] = useAtom(viewerSettingsAtom);

  useEffect(() => {
    if (!plugin || !structureRef) return;

    const applyRepresentation = async (): Promise<void> => {
      try {
        // TODO: Implement representation change using Mol* API
        // This requires deeper understanding of Mol* StateBuilder and representation types
        console.log("Applying representation:", settings);
      } catch (error) {
        console.error("Failed to apply representation:", error);
      }
    };

    void applyRepresentation();
  }, [plugin, structureRef, settings]);
}
