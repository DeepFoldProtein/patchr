import { useEffect, useCallback } from "react";
import { useSetAtom } from "jotai";
import type { PluginContext } from "molstar/lib/mol-plugin/context";
import { selectionAtom } from "../../store/mol-viewer-atoms";
import { bus } from "../../lib/event-bus";
import type { SelectionInfo } from "../../types/mol-viewer";

/**
 * Handle user selection events in Mol* viewer
 * Tracks picked atoms, residues, and chains
 */
export function useSelection(plugin: PluginContext | null): {
  clearSelection: () => void;
} {
  const setSelection = useSetAtom(selectionAtom);

  const clearSelection = useCallback(() => {
    setSelection(null);
    plugin?.managers.interactivity.lociSelects.deselectAll();
    bus.emit("selection:cleared");
  }, [plugin, setSelection]);

  useEffect(() => {
    if (!plugin) return;

    // Subscribe to Mol* selection events
    const subscription = plugin.behaviors.interaction.click.subscribe(event => {
      const loci = event.current.loci;

      if (loci.kind === "element-loci" && loci.elements.length > 0) {
        // TODO: Extract proper selection info from Mol* loci
        // This requires understanding Mol* data structures better
        const selectionInfo: SelectionInfo = {
          residues: [],
          atoms: [],
          chains: []
        };

        setSelection(selectionInfo);
        bus.emit("selection:changed", selectionInfo);
      }
    });

    return () => {
      subscription.unsubscribe();
    };
  }, [plugin, setSelection]);

  // Listen for external selection commands
  useEffect(() => {
    const handleClearSelection = (): void => {
      clearSelection();
    };

    bus.on("selection:clear", handleClearSelection);

    return () => {
      bus.off("selection:clear", handleClearSelection);
    };
  }, [clearSelection]);

  return { clearSelection };
}
