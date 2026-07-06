// useEraseVisuals — renders residues marked for erasure in the Sequence editor
// as semi-transparent ("ghosted") in the 3D viewer, so the user sees exactly
// what will be regenerated and can restore it. Driven by erasedRegionsAtom.
import { useEffect } from "react";
import { useAtomValue } from "jotai";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import {
  setStructureTransparency,
  clearStructureTransparency
} from "molstar/lib/mol-plugin-state/helpers/structure-transparency";
import { erasedResidueKeysAtom } from "../../store/repair-atoms";
import { buildResidueLociByKeys } from "../../lib/chainSequences";
import { logger } from "../../lib/logger";

// Transparency amount for erased residues: 0 = opaque, 1 = invisible.
const ERASE_TRANSPARENCY = 0.65;

/**
 * Apply / clear transparency on erased residues whenever the erase set changes.
 */
export function useEraseVisuals(plugin: PluginUIContext | null): void {
  const keysByChain = useAtomValue(erasedResidueKeysAtom);

  useEffect(() => {
    if (!plugin) return;

    const structures = plugin.managers.structure.hierarchy.current.structures;
    if (!structures || structures.length === 0) return;
    const components = structures[0].components;

    let cancelled = false;

    const apply = async (): Promise<void> => {
      try {
        // Reset any previous erase transparency first.
        await clearStructureTransparency(plugin, components);
        if (cancelled || keysByChain.size === 0) return;

        await setStructureTransparency(
          plugin,
          components,
          ERASE_TRANSPARENCY,
          async structure => buildResidueLociByKeys(structure, keysByChain)
        );
      } catch (err) {
        logger.debug("[Erase Visuals] Failed to update transparency:", err);
      }
    };

    void apply();

    return () => {
      cancelled = true;
    };
  }, [plugin, keysByChain]);
}
