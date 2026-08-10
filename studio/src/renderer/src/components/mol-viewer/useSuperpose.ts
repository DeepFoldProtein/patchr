import { useEffect, useCallback, useRef } from "react";
import { useAtomValue } from "jotai";
import { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { bus } from "../../lib/event-bus";
import {
  stagedMutationsAtom,
  type StagedMutation
} from "../../store/repair-atoms";
import {
  pathBasename,
  pathDirname,
  pathSplit,
  pathIncludes,
  pathJoin
} from "../../lib/path-utils";
import {
  Structure,
  StructureElement,
  StructureSelection,
  QueryContext,
  Unit
} from "molstar/lib/mol-model/structure";
import { StructureProperties } from "molstar/lib/mol-model/structure/structure/properties";
import { StructureSelectionQueries } from "molstar/lib/mol-plugin-state/helpers/structure-selection-query";
import { StateTransforms } from "molstar/lib/mol-plugin-state/transforms";
import { StateObjectRef } from "molstar/lib/mol-state/index";
import {
  superpose as superposeStructures,
  alignAndSuperpose
} from "molstar/lib/mol-model/structure/structure/util/superposition";
import { Mat4 } from "molstar/lib/mol-math/linear-algebra";
import { OrderedSet } from "molstar/lib/mol-data/int";
import type { StructureHierarchyRef } from "molstar/lib/mol-plugin-state/manager/structure/hierarchy-state";
import { Script } from "molstar/lib/mol-script/script";
import { Color } from "molstar/lib/mol-util/color";
import { clearStructureTransparency } from "molstar/lib/mol-plugin-state/helpers/structure-transparency";
import { createChainColorLayers } from "./useChainColors";
import { logger } from "../../lib/logger";

/**
 * Hook to handle loading inpainting results and superposing them with the original structure
 * Uses Molstar's built-in superposition API for accurate RMSD-based alignment
 */
// Map to track loaded structures by filePath
// Store hierarchy ref for visibility control
const loadedStructures = new Map<string, StructureHierarchyRef | null>();

export function useSuperpose(plugin: PluginUIContext | null): void {
  // Staged mutations aren't structurally identifiable in a result (a mutated
  // residue just looks like a normal amino acid), so we highlight them from the
  // staged list. A ref keeps the latest value without recreating the loader.
  const stagedMutations = useAtomValue(stagedMutationsAtom);
  const mutationsRef = useRef<StagedMutation[]>(stagedMutations);
  mutationsRef.current = stagedMutations;

  const loadAndSuperpose = useCallback(
    async (filePath: string, fileContent: string, superpose: boolean) => {
      if (!plugin) {
        logger.error("Plugin not initialized");
        return;
      }

      try {
        logger.log("🔬 Loading inpainting result:", filePath);
        logger.log("Superpose:", superpose);

        // Extract run ID from file path (e.g., run_001, run_002)
        const pathParts = pathSplit(filePath);
        const runIdIndex = pathParts.findIndex(part => part.startsWith("run_"));
        const runId = runIdIndex >= 0 ? pathParts[runIdIndex] : null;

        // Create unique label based on file path
        const fileName = pathBasename(filePath) || "result";
        const uniqueLabel = runId ? runId : `Inpainting Result: ${fileName}`;

        // Modify CIF file content: replace _entry.id value with run ID
        let modifiedFileContent = fileContent;
        if (runId) {
          // Replace _entry.id line in CIF format
          // Pattern: _entry.id    MODEL or _entry.id MODEL
          modifiedFileContent = fileContent.replace(
            /_entry\.id\s+(MODEL|model|Model|\w+)/gi,
            `_entry.id    ${runId}`
          );
          logger.log(
            `✓ Modified CIF _entry.id to: ${runId} for sequence panel`
          );
        }

        // Boltz emits modified residues (PTMs: SEP/TPO/PTR/MLY/M3L/…) into
        // `_chem_comp` with `.type = ?`. Mol* uses that type to classify a
        // residue as polymer vs. ligand — with `?` it can't tell MLY is a peptide
        // residue, so it drops it from the polymer cartoon, leaving an empty gap
        // at the PTM site (the cartoon-only result preset shows nothing there).
        // Restore the type so the modified residue is traced as part of the chain.
        modifiedFileContent =
          fixModifiedResidueChemCompType(modifiedFileContent);

        // Load result structure using Molstar's standard loading method
        const resultDataNode = await plugin.builders.data.rawData({
          data: modifiedFileContent,
          label: uniqueLabel
        });

        logger.log("✓ Result data node created");

        const resultTrajectory =
          await plugin.builders.structure.parseTrajectory(
            resultDataNode,
            "mmcif"
          );

        logger.log("✓ Result trajectory parsed");

        // Use Molstar's standard hierarchy preset - this creates proper representations
        // without duplicates
        const preset = await plugin.builders.structure.hierarchy.applyPreset(
          resultTrajectory,
          "default",
          {
            showUnitcell: false,
            representationPreset: "polymer-cartoon" // Use simple cartoon preset
          }
        );

        logger.log("✓ Structure loaded with standard preset");

        // Get the structure from the preset result
        const resultStructure = preset?.structure;
        if (!resultStructure) {
          logger.warn("No structure created from preset");
          return;
        }

        // Get the current structure (original/template) for superposition
        const structureHierarchy = plugin.managers.structure.hierarchy;
        const originalStructureRef = structureHierarchy.current.structures[0];
        let originalStructure: Structure | null = null;

        // Find the newly loaded structure (should be the last one)
        const allStructures = structureHierarchy.current.structures;
        const resultHierarchyRef = allStructures.find(
          s =>
            s.cell?.obj?.label === uniqueLabel ||
            s === allStructures[allStructures.length - 1]
        );

        // The original structure should be a different one
        if (allStructures.length >= 2 && originalStructureRef?.cell.obj) {
          // Make sure we're not comparing the same structure
          if (originalStructureRef !== resultHierarchyRef) {
            originalStructure = originalStructureRef.cell.obj.data;
            logger.log("✓ Original structure found for superposition");
          }
        }

        // Apply superposition if requested and original structure exists
        const resultStructureData = StateObjectRef.resolveAndCheck(
          plugin.state.data,
          resultStructure
        )?.obj?.data;

        if (superpose && originalStructure && resultStructureData) {
          logger.log("🔄 Performing superposition using Molstar API...");

          try {
            // Create loci for both structures (protein CA atoms only)
            const originalLoci = createStructureLoci(originalStructure);
            const resultLoci = createStructureLoci(resultStructureData);

            if (originalLoci && resultLoci) {
              // Count atoms in each loci
              const originalAtomCount = countLociAtoms(originalLoci);
              const resultAtomCount = countLociAtoms(resultLoci);

              logger.log(
                `[Superposition] Original: ${originalAtomCount} atoms, Result: ${resultAtomCount} atoms`
              );

              let transforms: Array<{
                bTransform: Mat4;
                rmsd: number;
              }> = [];

              if (
                originalAtomCount === resultAtomCount &&
                originalAtomCount > 0
              ) {
                // Same number of atoms - use direct superposition
                logger.log(
                  "[Superposition] Using direct superposition (same atom count)"
                );
                transforms = superposeStructures([originalLoci, resultLoci]);
              } else if (originalAtomCount > 0 && resultAtomCount > 0) {
                // Different number of atoms - use sequence alignment
                logger.log(
                  "[Superposition] Using sequence alignment (different atom counts)"
                );
                transforms = alignAndSuperpose([originalLoci, resultLoci]);
              }

              if (transforms.length > 0) {
                const { bTransform, rmsd } = transforms[0];
                logger.log(
                  `✓ Superposition calculated: RMSD = ${rmsd.toFixed(2)} Å`
                );

                // Apply transformation to result structure
                await applyStructureTransform(
                  plugin,
                  resultStructure,
                  bTransform
                );

                logger.log("✓ Transformation applied to result structure");
              } else {
                logger.warn(
                  "⚠ Superposition returned no transforms - structures may not align"
                );
              }
            } else {
              logger.warn("⚠ Could not create loci for superposition");
              if (!originalLoci) logger.warn("  - Original loci is null");
              if (!resultLoci) logger.warn("  - Result loci is null");
            }
          } catch (superposeErr) {
            logger.error("Failed to perform superposition:", superposeErr);
            // Continue loading without superposition
          }
        } else {
          logger.warn(
            `[Superposition] SKIPPED — superpose=${superpose}, originalStructureFound=${!!originalStructure}, resultData=${!!resultStructureData}, structuresInScene=${allStructures.length}. ` +
              `Result stays in its own coordinate frame (may sit far from the base → empty-middle framing).`
          );
        }

        plugin.canvas3d?.requestCameraReset();

        // Update trajectory label for sequence panel display
        const trajectoryRef = (resultTrajectory as { ref?: string })?.ref;
        if (trajectoryRef) {
          try {
            const state = plugin.state.data;
            const update = state.build().to(trajectoryRef).update({
              label: uniqueLabel
            });
            await plugin.runTask(plugin.state.data.updateTree(update));
            logger.log(
              `✓ Trajectory label updated to: ${uniqueLabel} for sequence panel`
            );
          } catch (err) {
            logger.warn("Failed to update trajectory label:", err);
          }
        }

        // Store hierarchy ref for visibility control
        loadedStructures.set(filePath, resultHierarchyRef || null);
        logger.log(
          `✓ Structure ref stored: ${filePath} (label: ${uniqueLabel})`
        );

        // Wait for representations to be created before applying colors
        if (resultHierarchyRef && resultStructureData) {
          await waitForRepresentations(plugin, resultHierarchyRef);

          // Apply combined colors (chain colors as base + inpainting metadata overlays)
          // This ensures chain colors are visible except where inpainting regions override them
          logger.log(
            `[Superpose] Applying combined colors to ${uniqueLabel}...`
          );
          await applyInpaintingMetadataColors(
            plugin,
            filePath,
            resultStructureData,
            resultHierarchyRef,
            mutationsRef.current
          );
          logger.log(`[Superpose] ✓ Combined colors applied`);
        }

        // Clear any lingering erase-ghosting transparency so the result (and the
        // base) render fully opaque. The erased residues are regenerated in the
        // result, so ghosting them would obscure exactly what the user wants to
        // see (Mol* selection renders opaque over transparent geometry, which is
        // why clicking a residue "revealed" it). The staged erase list is left
        // intact — only the stale 3D ghosting is dropped.
        try {
          const allStructures =
            plugin.managers.structure.hierarchy.current.structures;
          for (const s of allStructures) {
            if (s.components?.length) {
              await clearStructureTransparency(plugin, s.components);
            }
          }
        } catch (transpErr) {
          logger.warn(
            "Failed to clear erase transparency on result load:",
            transpErr
          );
        }

        // Frame the RESULT explicitly. requestCameraReset() fits *all* structures
        // — including the hidden base and, when superposition is skipped, a result
        // that sits far from it — which leaves the result off-center in empty
        // space (the "empty middle"). Re-fetch the current (post-transform) result
        // structure and focus only it, at its actual rendered position. Deferred a
        // frame so the transform / representation updates have settled.
        requestAnimationFrame(() => {
          try {
            const cur = plugin.managers.structure.hierarchy.current.structures;
            const rr =
              cur.find(s => s.cell?.obj?.label === uniqueLabel) ??
              cur[cur.length - 1];
            const data = rr?.cell?.obj?.data;
            if (data) {
              plugin.managers.camera.focusLoci(
                Structure.toStructureElementLoci(data)
              );
              const sph = data.boundary?.sphere;
              logger.log(
                `[Camera] focused on result "${uniqueLabel}" (radius=${sph ? sph.radius.toFixed(0) : "?"}Å, center=${sph ? sph.center.map((v: number) => v.toFixed(0)).join(",") : "?"})`
              );
            } else {
              logger.warn("[Camera] no result structure to focus");
            }
          } catch (e) {
            logger.warn("[Camera] focus on result failed:", e);
          }
        });

        // Emit event that structure is loaded (for tracking in UI)
        bus.emit("inpainting:structure-loaded", { filePath });

        logger.log("✅ Result loaded successfully");
      } catch (err) {
        logger.error("Failed to load result:", err);
        throw err;
      }
    },
    [plugin]
  );

  const toggleStructureVisibility = useCallback(
    async (filePath: string, visible: boolean) => {
      if (!plugin) {
        logger.error("[Visibility] Plugin not initialized");
        return;
      }

      // Try to get cached reference first, but validate it's still in the current hierarchy
      const hierarchy = plugin.managers.structure.hierarchy;
      const structures = hierarchy.current.structures;
      let hierarchyRef = loadedStructures.get(filePath);

      // Validate cached ref is still present in the current hierarchy
      if (
        hierarchyRef &&
        !structures.some(s => s.cell === hierarchyRef!.cell)
      ) {
        logger.log(
          `[Visibility] Cached ref stale for: ${filePath}, re-searching`
        );
        loadedStructures.delete(filePath);
        hierarchyRef = undefined;
      }

      // If not cached, find in current hierarchy
      if (!hierarchyRef) {
        const fileName = pathBasename(filePath) || "";
        const fileNameWithoutExt = fileName.replace(/\.[^.]*$/, "");
        const isBaseStructure = pathIncludes(filePath, "/structures/original/");

        logger.log(
          `[Visibility] Finding structure for: ${fileName} (${structures.length} structures, isBase: ${isBaseStructure})`
        );

        if (isBaseStructure) {
          // Base structures: try multiple matching strategies
          // 1. Exact label match
          // 2. Label contains filename
          // 3. First structure if no results loaded yet
          const hasResults = structures.some(s => {
            const label = s.cell?.obj?.label || "";
            const trajLabel = s.model?.trajectory?.cell?.obj?.label || "";
            return (
              label.startsWith("run_") ||
              label.includes("Inpainting Result") ||
              trajLabel.startsWith("run_") ||
              trajLabel.includes("Inpainting Result")
            );
          });

          hierarchyRef =
            structures.find(s => {
              const label = s.cell?.obj?.label || "";
              const trajLabel = s.model?.trajectory?.cell?.obj?.label || "";
              return (
                label === fileName ||
                label.includes(fileNameWithoutExt) ||
                fileNameWithoutExt.includes(label.replace(/\.[^.]*$/, "")) ||
                trajLabel === fileName ||
                trajLabel.includes(fileNameWithoutExt)
              );
            }) ||
            // Fallback: find the structure that is NOT a result (no run_ prefix in trajectory label)
            structures.find(s => {
              const trajLabel = s.model?.trajectory?.cell?.obj?.label || "";
              return (
                !trajLabel.startsWith("run_") &&
                !trajLabel.includes("Inpainting Result")
              );
            }) ||
            // Last resort: first structure if no results loaded
            (!hasResults && structures.length > 0 ? structures[0] : null);
        } else {
          // Inpainting results: match by label or run_XXX pattern
          // Check both the structure label and the parent trajectory label
          // (the custom label is applied to the trajectory node, not the structure)
          hierarchyRef =
            structures.find(s => {
              const label = s.cell?.obj?.label || "";
              const trajectoryLabel =
                s.model?.trajectory?.cell?.obj?.label || "";
              return (
                label === fileName ||
                label.includes(fileNameWithoutExt) ||
                trajectoryLabel.includes(fileNameWithoutExt) ||
                (filePath.includes("run_") &&
                  (label.startsWith(filePath.match(/run_\d+/)?.[0] || "") ||
                    trajectoryLabel.startsWith(
                      filePath.match(/run_\d+/)?.[0] || ""
                    )))
              );
            }) || null;
        }

        if (hierarchyRef) {
          loadedStructures.set(filePath, hierarchyRef);
          logger.log(
            `[Visibility] ✓ Found structure: ${filePath} -> ${hierarchyRef.cell?.obj?.label}`
          );
        } else {
          logger.warn(`[Visibility] ✗ Structure not found: ${filePath}`);
          logger.log(
            `[Visibility] Available:`,
            structures.map(s => ({
              label: s.cell?.obj?.label,
              trajectory: s.model?.trajectory?.cell?.obj?.label
            }))
          );
          return;
        }
      }

      try {
        const action = visible ? "show" : "hide";
        logger.log(`[Visibility] ${action}: ${filePath}`);

        plugin.managers.structure.hierarchy.toggleVisibility(
          [hierarchyRef],
          action
        );

        logger.log(`[Visibility] ✓ ${action} successful`);
      } catch (err) {
        logger.error("[Visibility] Toggle failed:", err);
      }
    },
    [plugin]
  );

  // Load simulation system PDB (solvated box) into viewer
  const loadSimulationSystem = useCallback(
    async (_filePath: string, fileContent: string, label: string) => {
      if (!plugin) return;
      try {
        logger.log("Loading simulation system:", label);

        const dataNode = await plugin.builders.data.rawData({
          data: fileContent,
          label: `Sim: ${label}`
        });

        const trajectory = await plugin.builders.structure.parseTrajectory(
          dataNode,
          "pdb"
        );

        await plugin.builders.structure.hierarchy.applyPreset(
          trajectory,
          "default",
          {
            showUnitcell: false,
            representationPreset: "polymer-cartoon"
          }
        );

        plugin.canvas3d?.requestCameraReset();
        logger.log("Simulation system loaded:", label);
      } catch (err) {
        logger.error("Failed to load simulation system:", err);
      }
    },
    [plugin]
  );

  useEffect(() => {
    const handleLoadResult = (event: {
      filePath: string;
      fileContent: string;
      superpose?: boolean;
    }): void => {
      void loadAndSuperpose(
        event.filePath,
        event.fileContent,
        event.superpose ?? true
      );
    };

    const handleRemoveResult = (event: {
      filePath: string;
      visible?: boolean;
    }): void => {
      void toggleStructureVisibility(event.filePath, event.visible ?? false);
    };

    const handleLoadSimSystem = (event: {
      filePath: string;
      fileContent: string;
      label: string;
    }): void => {
      void loadSimulationSystem(event.filePath, event.fileContent, event.label);
    };

    bus.on("inpainting:load-result", handleLoadResult);
    bus.on("inpainting:remove-result", handleRemoveResult);
    bus.on("simulation:load-system", handleLoadSimSystem);

    return () => {
      bus.off("inpainting:load-result", handleLoadResult);
      bus.off("inpainting:remove-result", handleRemoveResult);
      bus.off("simulation:load-system", handleLoadSimSystem);
    };
  }, [loadAndSuperpose, toggleStructureVisibility, loadSimulationSystem]);
}

/**
 * Create StructureElement.Loci for the entire structure
 * Uses trace atoms (CA for proteins) for better superposition
 */
/**
 * Create loci for superposition - ONLY using protein chains
 * DNA/RNA chains are excluded to ensure proper alignment
 */
/**
 * Standard amino acid 3-letter codes
 */
const AMINO_ACID_CODES = new Set([
  "ALA",
  "ARG",
  "ASN",
  "ASP",
  "CYS",
  "GLN",
  "GLU",
  "GLY",
  "HIS",
  "ILE",
  "LEU",
  "LYS",
  "MET",
  "PHE",
  "PRO",
  "SER",
  "THR",
  "TRP",
  "TYR",
  "VAL",
  "SEC",
  "PYL",
  "ASX",
  "GLX",
  "UNK"
]);

/**
 * Count total atoms in a Loci
 */
function countLociAtoms(loci: StructureElement.Loci): number {
  let count = 0;
  for (const element of loci.elements) {
    count += OrderedSet.size(element.indices);
  }
  return count;
}

/**
 * Extract protein CA atoms from a structure.
 * Returns a Loci containing only CA atoms from protein chains.
 */
function createStructureLoci(
  structure: Structure
): StructureElement.Loci | null {
  try {
    // Collect CA atoms from protein residues only
    const elements: Array<{
      unit: Unit;
      indices: OrderedSet<StructureElement.UnitIndex>;
    }> = [];
    let totalCaAtoms = 0;
    const chainCounts = new Map<string, number>();

    for (const unit of structure.units) {
      if (!Unit.isAtomic(unit)) continue;

      const atomicUnit = unit as Unit.Atomic;
      const caIndices: StructureElement.UnitIndex[] = [];

      // One Location per unit, mutated in place — allocating one per atom made
      // this scan dominate superposition setup on large structures.
      const loc = StructureElement.Location.create(structure, atomicUnit);

      // Iterate through all atoms in the unit
      for (let i = 0; i < atomicUnit.elements.length; i++) {
        loc.element = atomicUnit.elements[i];

        const atomName = StructureProperties.atom.label_atom_id(loc);
        const compId = StructureProperties.atom.label_comp_id(loc);
        const chainId = StructureProperties.chain.auth_asym_id(loc);

        // Only select CA atoms from amino acids
        if (atomName === "CA" && AMINO_ACID_CODES.has(compId.toUpperCase())) {
          caIndices.push(i as StructureElement.UnitIndex);
          chainCounts.set(chainId, (chainCounts.get(chainId) || 0) + 1);
        }
      }

      if (caIndices.length > 0) {
        elements.push({
          unit: atomicUnit,
          indices: OrderedSet.ofSortedArray(caIndices)
        });
        totalCaAtoms += caIndices.length;
      }
    }

    // Log chain information
    const chainInfo = Array.from(chainCounts.entries())
      .map(([chain, count]) => `${chain}:${count}`)
      .join(", ");
    logger.log(
      `[Superposition] Found ${totalCaAtoms} CA atoms from protein chains: ${chainInfo}`
    );

    if (elements.length > 0) {
      return StructureElement.Loci(structure, elements);
    }

    // Fallback: try to use trace atoms if no CA found
    logger.warn(
      "[Superposition] No protein CA atoms found, trying trace atoms"
    );
    const { query: traceQuery } = StructureSelectionQueries.trace;
    const queryContext = new QueryContext(structure);
    const traceLoci = StructureSelection.toLociWithSourceUnits(
      traceQuery(queryContext)
    );

    if (!StructureElement.Loci.isEmpty(traceLoci)) {
      return traceLoci;
    }

    return null;
  } catch (err) {
    logger.error("Failed to create structure loci:", err);
    return null;
  }
}

/**
 * Apply transformation matrix to a structure using Molstar's transform API
 */
async function applyStructureTransform(
  plugin: PluginUIContext,
  structureRef: StateObjectRef,
  transform: Mat4
): Promise<void> {
  try {
    // Resolve structure ref
    const r = StateObjectRef.resolveAndCheck(plugin.state.data, structureRef);
    if (!r) {
      throw new Error("Could not resolve structure ref");
    }

    // Check if transform already exists
    const existingTransform = plugin.state.data.selectQ(q =>
      q
        .byRef(r.transform.ref)
        .subtree()
        .withTransformer(StateTransforms.Model.TransformStructureConformation)
    )[0];

    // Use the transform directly (coordinate system handling can be added later if needed)
    const finalTransform = transform;

    const params = {
      transform: {
        name: "matrix" as const,
        params: {
          data: finalTransform,
          transpose: false
        }
      }
    };

    const update = existingTransform
      ? plugin.state.data.build().to(existingTransform).update(params)
      : plugin.state.data
          .build()
          .to(structureRef)
          .insert(
            StateTransforms.Model.TransformStructureConformation,
            params,
            {
              tags: "SuperpositionTransform"
            }
          );

    await plugin.runTask(plugin.state.data.updateTree(update));
  } catch (err) {
    logger.error("Failed to apply structure transform:", err);
    throw err;
  }
}

/**
 * Wait for representations to be created after preset is applied
 * Polls until representations are found or timeout
 */
async function waitForRepresentations(
  plugin: PluginUIContext,
  hierarchyRef: StructureHierarchyRef | null,
  maxAttempts: number = 50
): Promise<boolean> {
  if (!hierarchyRef) return false;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const parentRef = (hierarchyRef as any).cell?.transform?.ref;
  if (!parentRef) return false;

  const state = plugin.state.data;
  const cells = state.cells;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    // Check if representations exist
    let foundRepresentations = false;

    const checkRepresentations = (ref: string, depth = 0): boolean => {
      if (depth > 10) return false;
      const cell = cells.get(ref);
      if (!cell) return false;

      if (
        cell.transform.transformer ===
        StateTransforms.Representation.StructureRepresentation3D
      ) {
        return true;
      }

      for (const [childRef, childCell] of cells.entries()) {
        if (childCell.transform.parent === ref) {
          if (checkRepresentations(childRef, depth + 1)) {
            return true;
          }
        }
      }
      return false;
    };

    foundRepresentations = checkRepresentations(parentRef);

    if (foundRepresentations) {
      logger.log(
        `[Superpose] ✓ Representations ready after ${attempt} attempt(s)`
      );
      return true;
    }

    // Use requestAnimationFrame for non-blocking delay instead of setTimeout
    await new Promise(resolve => requestAnimationFrame(resolve));
  }

  logger.warn(
    `[Superpose] ⚠️ Timeout waiting for representations after ${maxAttempts} attempts`
  );
  return false;
}

/**
 * Apply chain colors only (when no inpainting metadata is available)
 * Uses the same overpaint mechanism for consistency
 */
async function applyChainColorsOnly(
  plugin: PluginUIContext,
  structure: Structure,
  hierarchyRef: StructureHierarchyRef | null,
  resultIndex: number = 0,
  mutations: StagedMutation[] = []
): Promise<void> {
  try {
    // Get parent ref
    let parentRef: string | null = null;
    if (hierarchyRef) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      parentRef = (hierarchyRef as any).cell?.transform?.ref || null;
    }
    if (!parentRef) {
      const hierarchy = plugin.managers.structure.hierarchy;
      const structures = hierarchy.current.structures;
      const targetStructure = structures.find(
        s => s.cell?.obj?.data === structure
      );
      if (targetStructure) {
        parentRef = targetStructure.cell?.transform?.ref || null;
      }
    }
    if (!parentRef) {
      logger.warn("[Chain Colors Fallback] Could not get parent ref");
      return;
    }

    // Create chain color layers and apply (result structure = true for brighter colors)
    const chainColorLayers = createChainColorLayers(
      structure,
      true,
      resultIndex
    );
    // Edits on top of the chain colors: mutation teal + PTM purple.
    const layers = [
      ...chainColorLayers,
      ...createMutationTealLayers(structure, mutations),
      ...createPtmPurpleLayers(structure)
    ];
    if (layers.length > 0) {
      await applyOverpaintToRepresentations(plugin, parentRef, layers);
      logger.log(
        `[Chain Colors Fallback] ✓ Applied ${layers.length} layer(s) (chain colors + edits) with palette index ${resultIndex}`
      );
    }
  } catch (err) {
    logger.error("[Chain Colors Fallback] Failed to apply colors:", err);
  }
}

/**
 * Load inpainting metadata and apply colors to residues
 * - Partially fixed residues: Orange
 * - Fully inpainted residues: Red
 */
async function applyInpaintingMetadataColors(
  plugin: PluginUIContext,
  filePath: string,
  structure: Structure | undefined,
  hierarchyRef: StructureHierarchyRef | null,
  mutations: StagedMutation[] = []
): Promise<void> {
  if (!structure) {
    logger.warn("[Inpainting Metadata] No structure available for coloring");
    return;
  }

  // Extract result index from file path (run_001 -> 0, run_002 -> 1, etc.)
  const runMatch = filePath.match(/run_(\d+)/);
  const resultIndex = runMatch ? parseInt(runMatch[1], 10) - 1 : 0;
  logger.log(
    `[Inpainting Metadata] Result index: ${resultIndex} (from path: ${filePath})`
  );

  try {
    // Find metadata JSON file path
    // Metadata is in the same directory as the CIF file
    // Path format: .../run_XXX/predictions/predictions/chain_id/1ton_A_model_0.cif
    // Metadata: .../run_XXX/predictions/predictions/chain_id/inpainting_metadata_1ton_A.json
    const pathParts = pathSplit(filePath);
    const cifFileName = pathParts[pathParts.length - 1];
    const cifDir = pathDirname(filePath);

    // Extract chain ID from filename (e.g., "A" from "1ton_A_model_0.cif")
    const chainMatch =
      cifFileName.match(/_([A-Z])_/) || cifFileName.match(/_([A-Z])\./);
    const chainId = chainMatch ? chainMatch[1] : "A";

    // Use the parent directory name as chain prefix (e.g., "4j76_ABCDEF" from
    // ".../4j76_ABCDEF/file.cif", or "1a22" from ".../1a22/file.cif").
    const parentDirName =
      pathParts.length >= 2 ? pathParts[pathParts.length - 2] : null;
    const chainPrefixFromDir =
      parentDirName &&
      !parentDirName.startsWith("run_") &&
      parentDirName !== "predictions"
        ? parentDirName
        : null;

    // Chain prefix from filename (e.g., "4j76_ABCDEF" from "4j76_ABCDEF_model_0.cif")
    const chainPrefixFromFile = cifFileName.includes("_")
      ? cifFileName.split("_").slice(0, 2).join("_")
      : null;

    // Parent directory (one level above cifDir)
    const parentDir = pathParts.slice(0, -2).join("/");

    // Try multiple possible metadata file names (most specific first)
    const possibleMetadataPaths = [
      // 1. Same directory, prefix from parent dir name (e.g., inpainting_metadata_4j76_ABCDEF.json)
      chainPrefixFromDir
        ? pathJoin(cifDir, `inpainting_metadata_${chainPrefixFromDir}.json`)
        : null,
      // 2. Same directory, prefix from filename (e.g., inpainting_metadata_4j76_ABCDEF.json)
      chainPrefixFromFile
        ? pathJoin(cifDir, `inpainting_metadata_${chainPrefixFromFile}.json`)
        : null,
      // 3. Same directory with chain ID only (e.g., inpainting_metadata_a.json)
      pathJoin(cifDir, `inpainting_metadata_${chainId.toLowerCase()}.json`),
      // 4. Parent directory with prefix
      chainPrefixFromDir && parentDir
        ? pathJoin(parentDir, `inpainting_metadata_${chainPrefixFromDir}.json`)
        : null,
      // 5. Parent directory with chain ID
      parentDir
        ? pathJoin(
            parentDir,
            `inpainting_metadata_${chainId.toLowerCase()}.json`
          )
        : null
    ].filter((path): path is string => path !== null);
    // Deduplicate
    const uniqueMetadataPaths = Array.from(new Set(possibleMetadataPaths));

    logger.log(
      `[Inpainting Metadata] Searching for metadata file. CIF dir: ${cifDir}, chainId: ${chainId}, dirPrefix: ${chainPrefixFromDir || "none"}, filePrefix: ${chainPrefixFromFile || "none"}`
    );
    logger.log(`[Inpainting Metadata] Trying paths:`, uniqueMetadataPaths);

    let metadataContent: string | null = null;
    for (const metadataPath of uniqueMetadataPaths) {
      try {
        const result = await window.api.project.readFileByPath(metadataPath);
        if (result.success && result.content) {
          metadataContent = result.content;
          logger.log(
            `[Inpainting Metadata] ✓ Found metadata at: ${metadataPath}`
          );
          break;
        } else {
          logger.log(
            `[Inpainting Metadata] ✗ Not found: ${metadataPath} (success: ${result.success})`
          );
        }
      } catch (err) {
        logger.log(
          `[Inpainting Metadata] ✗ Error reading: ${metadataPath}`,
          err
        );
      }
    }

    if (!metadataContent) {
      logger.warn(
        "[Inpainting Metadata] Could not find metadata file for:",
        filePath
      );
      // Still apply chain colors even if no metadata found
      await applyChainColorsOnly(
        plugin,
        structure,
        hierarchyRef,
        resultIndex,
        mutations
      );
      return;
    }

    // Parse metadata
    const metadata = JSON.parse(metadataContent) as {
      chains?: {
        [chainId: string]: {
          partially_fixed_residues?: Array<{
            residue: number;
            fixed_atoms: number;
            total_atoms: number;
          }>;
          fully_inpainted_residues?: number[];
        };
      };
      lrd_boundary?: {
        residues_by_chain?: { [chainId: string]: number[] };
      };
    };

    // Check if metadata has chains data
    if (!metadata.chains || Object.keys(metadata.chains).length === 0) {
      logger.warn(`[Inpainting Metadata] No chains data in metadata`);
      // Still apply chain colors even if no chain data in metadata
      await applyChainColorsOnly(
        plugin,
        structure,
        hierarchyRef,
        resultIndex,
        mutations
      );
      return;
    }

    // Use the provided hierarchy ref or try to find it
    let parentRef: string | null = null;

    if (hierarchyRef) {
      // Use the provided hierarchy ref's cell transform ref
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      parentRef = (hierarchyRef as any).cell?.transform?.ref || null;
    }

    if (!parentRef) {
      // Fallback: try to find structure in hierarchy
      const hierarchy = plugin.managers.structure.hierarchy;
      const structures = hierarchy.current.structures;
      const targetStructure = structures.find(
        s => s.cell?.obj?.data === structure
      );

      if (targetStructure) {
        parentRef = targetStructure.cell?.transform?.ref || null;
      }
    }

    if (!parentRef) {
      logger.warn(
        "[Inpainting Metadata] Could not get parent ref for structure"
      );
      return;
    }

    // Check if representation colorTheme is safe (not using chain-id which may have warm colors)
    const checkRepresentationColorTheme = (): void => {
      const state = plugin.state.data;
      const cells = state.cells;
      const representationRefs: string[] = [];

      const findRepresentations = (ref: string, depth = 0): void => {
        if (depth > 10) return;
        const cell = cells.get(ref);
        if (!cell) return;

        if (
          cell.transform.transformer ===
          StateTransforms.Representation.StructureRepresentation3D
        ) {
          representationRefs.push(ref);
        }

        for (const [childRef, childCell] of cells.entries()) {
          if (childCell.transform.parent === ref) {
            findRepresentations(childRef, depth + 1);
          }
        }
      };

      findRepresentations(parentRef);

      for (const reprRef of representationRefs) {
        const cell = cells.get(reprRef);
        if (cell) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const colorTheme = (cell.transform.params as any)?.type?.params
            ?.colorTheme;
          if (colorTheme) {
            const themeName = colorTheme.name || "";
            if (themeName === "chain-id" || themeName === "chain-name") {
              logger.warn(
                `[Inpainting Metadata] ⚠️ WARNING: Representation uses ${themeName} color theme, which may include warm colors (yellow/orange/red)!`
              );
              logger.warn(
                `[Inpainting Metadata] ⚠️ Chain colors should be applied first to use cool colors (blue/cyan/purple).`
              );
            } else if (themeName === "uniform") {
              const uniformValue = colorTheme.params?.value || 0;
              const r = (uniformValue >> 16) & 0xff;
              const g = (uniformValue >> 8) & 0xff;
              const b = uniformValue & 0xff;
              // Check if uniform color is warm
              if (r > 200 || (r > 150 && g > 150 && b < 150)) {
                const colorHex = `#${uniformValue.toString(16).padStart(6, "0")}`;
                logger.warn(
                  `[Inpainting Metadata] ⚠️ WARNING: Representation uniform color ${colorHex} (RGB=${r},${g},${b}) is warm!`
                );
              }
            }
          }
        }
      }
    };

    checkRepresentationColorTheme();

    // Apply colors in priority order (lowest to highest)
    // This ensures that if residues overlap, the higher priority color is shown
    // Using overpaint to color existing representations (no duplicate geometry)

    // IMPORTANT: First add chain color layers as the base, then inpainting colors on top
    // This ensures chain colors are visible for non-inpainting regions
    // Result structure = true for brighter cool colors, with resultIndex for different palettes per result
    const chainColorLayers = createChainColorLayers(
      structure,
      true,
      resultIndex
    );
    logger.log(
      `[Inpainting Metadata] Created ${chainColorLayers.length} chain color layer(s) as base (palette index: ${resultIndex})`
    );

    // Collect all overpaint layers: chain colors first, then inpainting overlays
    const overpaintLayers: Array<{
      bundle: typeof StructureElement.Bundle.Empty;
      color: Color;
      clear: boolean;
    }> = [...chainColorLayers]; // Start with chain colors as base

    // Process all chains in metadata, not just the one from filename
    const allChainIds = Object.keys(metadata.chains);
    logger.log(
      `[Inpainting Metadata] Processing ${allChainIds.length} chain(s): ${allChainIds.join(", ")}`
    );

    for (const currentChainId of allChainIds) {
      const chainData = metadata.chains[currentChainId];
      if (!chainData) {
        logger.warn(
          `[Inpainting Metadata] No data for chain ${currentChainId}`
        );
        continue;
      }

      // 1. Color LRD boundary residues first (Yellow: #eab308) - Lowest priority
      const boundaryResidues =
        metadata.lrd_boundary?.residues_by_chain?.[currentChainId];
      if (boundaryResidues && boundaryResidues.length > 0) {
        const colorValue = 0xeab308; // Yellow
        const colorHex = `#${colorValue.toString(16).padStart(6, "0")}`;
        const r = (colorValue >> 16) & 0xff;
        const g = (colorValue >> 8) & 0xff;
        const b = colorValue & 0xff;
        const layer = createOverpaintLayer(
          structure,
          currentChainId,
          boundaryResidues,
          colorValue
        );
        if (layer) {
          overpaintLayers.push(layer);
          logger.log(
            `[Inpainting Metadata] Added boundary exclusion layer for chain ${currentChainId}: ${boundaryResidues.length} residues -> ${colorHex} (RGB=${r},${g},${b}) [Yellow]`
          );
        }
      }

      // 2. Partially fixed residues (Orange: #f97316)
      if (
        chainData.partially_fixed_residues &&
        chainData.partially_fixed_residues.length > 0
      ) {
        const partialResidues = chainData.partially_fixed_residues.map(
          (r: { residue: number } | number) =>
            typeof r === "number" ? r : r.residue
        );
        const colorValue = 0xf97316; // Orange
        const colorHex = `#${colorValue.toString(16).padStart(6, "0")}`;
        const r = (colorValue >> 16) & 0xff;
        const g = (colorValue >> 8) & 0xff;
        const b = colorValue & 0xff;
        const layer = createOverpaintLayer(
          structure,
          currentChainId,
          partialResidues,
          colorValue
        );
        if (layer) {
          overpaintLayers.push(layer);
          logger.log(
            `[Inpainting Metadata] Added partially fixed layer for chain ${currentChainId}: ${partialResidues.length} residues -> ${colorHex} (RGB=${r},${g},${b}) [Orange]`
          );
        }
      }

      // 3. Color fully inpainted residues last (Red: #ef4444) - Highest priority
      if (
        chainData.fully_inpainted_residues &&
        chainData.fully_inpainted_residues.length > 0
      ) {
        const colorValue = 0xef4444; // Red
        const colorHex = `#${colorValue.toString(16).padStart(6, "0")}`;
        const r = (colorValue >> 16) & 0xff;
        const g = (colorValue >> 8) & 0xff;
        const b = colorValue & 0xff;
        const layer = createOverpaintLayer(
          structure,
          currentChainId,
          chainData.fully_inpainted_residues,
          colorValue
        );
        if (layer) {
          overpaintLayers.push(layer);
          logger.log(
            `[Inpainting Metadata] Added fully inpainted layer for chain ${currentChainId}: ${chainData.fully_inpainted_residues.length} residues -> ${colorHex} (RGB=${r},${g},${b}) [Red]`
          );
        }
      }
    }

    // Edits (mutation teal + PTM purple) last → top priority: PTM = Mutation >
    // Fully Inpainted = Partially Fixed = Boundary. A mutated / modified residue
    // keeps its edit color even when it overlaps an inpainting region. (A residue
    // can't be both mutated and PTM'd, so their relative order is irrelevant.)
    overpaintLayers.push(...createMutationTealLayers(structure, mutations));
    overpaintLayers.push(...createPtmPurpleLayers(structure));

    // Apply all overpaint layers to existing representations
    if (overpaintLayers.length > 0) {
      await applyOverpaintToRepresentations(plugin, parentRef, overpaintLayers);
    }

    // Summary of colors applied
    const colorSummary = {
      boundary: { hex: "#eab308", name: "Yellow", rgb: "234,179,8" },
      partiallyFixed: { hex: "#f97316", name: "Orange", rgb: "249,115,22" },
      fullyInpainted: { hex: "#ef4444", name: "Red", rgb: "239,68,68" }
    };

    logger.log(
      `[Inpainting Metadata] ✓ Applied colors to ${allChainIds.length} chain(s) (${allChainIds.join(", ")}) using overpaint`
    );
    logger.log(
      `[Inpainting Metadata] Color scheme: Boundary=${colorSummary.boundary.hex} (${colorSummary.boundary.name}), Partially Fixed=${colorSummary.partiallyFixed.hex} (${colorSummary.partiallyFixed.name}), Fully Inpainted=${colorSummary.fullyInpainted.hex} (${colorSummary.fullyInpainted.name})`
    );
  } catch (err) {
    logger.error("[Inpainting Metadata] Failed to apply colors:", err);
  }
}

/**
 * Collect overpaint layers for residues (doesn't create new representations)
 * Returns an overpaint layer that can be applied to existing representations
 */
function createOverpaintLayer(
  structure: Structure,
  chainId: string,
  residueNumbers: number[],
  colorValue: number
): {
  bundle: typeof StructureElement.Bundle.Empty;
  color: Color;
  clear: boolean;
} | null {
  try {
    // Create selection for residues using Script
    // Use core.set.has for efficient set membership test (much faster than nested or)
    const script = Script.getStructureSelection(
      Q =>
        Q.struct.generator.atomGroups({
          "chain-test": Q.core.rel.eq([
            Q.struct.atomProperty.macromolecular.auth_asym_id(),
            chainId
          ]),
          "residue-test":
            residueNumbers.length === 1
              ? Q.core.rel.eq([
                  Q.struct.atomProperty.macromolecular.auth_seq_id(),
                  residueNumbers[0]
                ])
              : Q.core.set.has([
                  Q.core.type.set(residueNumbers),
                  Q.struct.atomProperty.macromolecular.auth_seq_id()
                ])
        }),
      structure
    );

    const selection = StructureSelection.toLociWithSourceUnits(script);
    if (selection.elements.length === 0) {
      return null;
    }

    return {
      bundle: StructureElement.Bundle.fromLoci(selection),
      color: Color(colorValue),
      clear: false
    };
  } catch (err) {
    logger.error(
      `[Inpainting Metadata] Failed to create overpaint layer:`,
      err
    );
    return null;
  }
}

/**
 * Restore `_chem_comp.type` for modified amino-acid residues that Boltz writes
 * with an unknown type (`?`). Without a peptide-linking type, Mol* treats the
 * residue as a non-polymer ligand and omits it from the polymer cartoon, so the
 * PTM site renders as an empty gap. We rewrite the type to `'L-peptide linking'`
 * (`peptide linking` for glycine-like) so the residue is traced with the chain.
 * Matches `_chem_comp` loop rows, which begin with the component id.
 */
const MODIFIED_AA_CCDS = [
  "SEP",
  "TPO",
  "PTR",
  "MLY",
  "M3L",
  "ALY",
  "MSE",
  "HYP",
  "CSO",
  "KCX",
  "SAC",
  "CAS",
  "PCA",
  "CME",
  "OCS",
  "CSD",
  "SAH",
  "MLZ"
];
function fixModifiedResidueChemCompType(cif: string): string {
  const pattern = new RegExp(
    `^([ \\t]*)(${MODIFIED_AA_CCDS.join("|")})([ \\t]+)\\?`,
    "gm"
  );
  let n = 0;
  const out = cif.replace(pattern, (_m, indent, ccd, sp) => {
    n++;
    return `${indent}${ccd}${sp}'L-peptide linking'`;
  });
  if (n > 0) {
    logger.log(
      `[CIF Fix] Set _chem_comp.type='L-peptide linking' for ${n} modified residue(s) so they render in the cartoon`
    );
  }
  return out;
}

// Post-translational-modification CCDs the studio can introduce (matches the
// Sequence editor's PTM_OPTIONS). Residues carrying one of these in a result
// structure are painted purple so PTM sites are visually distinct — purple == PTM.
const PTM_CCDS = new Set(["SEP", "TPO", "PTR", "MLY", "M3L", "ALY"]);
const PTM_PURPLE = 0xa855f7; // Tailwind purple-500, matches the sequence panel

/**
 * Scan the loaded structure for residues whose component id is a known PTM CCD
 * and build purple overpaint layers for them (one per chain). Independent of the
 * inpainting metadata so PTM sites are highlighted in every result view.
 */
function createPtmPurpleLayers(structure: Structure): Array<{
  bundle: typeof StructureElement.Bundle.Empty;
  color: Color;
  clear: boolean;
}> {
  const byChain = new Map<string, Set<number>>();
  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;
    const loc = StructureElement.Location.create(structure, unit);
    for (let i = 0; i < unit.elements.length; i++) {
      loc.element = unit.elements[i];
      const comp = StructureProperties.atom.label_comp_id(loc).toUpperCase();
      if (!PTM_CCDS.has(comp)) continue;
      const chainId = StructureProperties.chain.auth_asym_id(loc);
      const seqId = StructureProperties.residue.auth_seq_id(loc);
      let set = byChain.get(chainId);
      if (!set) {
        set = new Set();
        byChain.set(chainId, set);
      }
      set.add(seqId);
    }
  }

  const layers: Array<{
    bundle: typeof StructureElement.Bundle.Empty;
    color: Color;
    clear: boolean;
  }> = [];
  for (const [chainId, seqIds] of byChain) {
    const layer = createOverpaintLayer(
      structure,
      chainId,
      Array.from(seqIds),
      PTM_PURPLE
    );
    if (layer) {
      layers.push(layer);
      logger.log(
        `[PTM] Painted chain ${chainId} residues [${Array.from(seqIds).join(", ")}] purple (#a855f7)`
      );
    }
  }
  return layers;
}

const MUTATION_TEAL = 0x14b8a6; // Tailwind teal-500, matches the sequence panel

/**
 * Build teal overpaint layers for staged mutations. Mutated residues aren't
 * structurally distinguishable in the result, so we color them from the staged
 * list (chain + author residue number). Applied at the same top priority as PTM.
 */
function createMutationTealLayers(
  structure: Structure,
  mutations: StagedMutation[]
): Array<{
  bundle: typeof StructureElement.Bundle.Empty;
  color: Color;
  clear: boolean;
}> {
  const byChain = new Map<string, number[]>();
  for (const m of mutations) {
    const arr = byChain.get(m.chainId) ?? [];
    arr.push(m.authSeqId);
    byChain.set(m.chainId, arr);
  }

  const layers: Array<{
    bundle: typeof StructureElement.Bundle.Empty;
    color: Color;
    clear: boolean;
  }> = [];
  for (const [chainId, seqIds] of byChain) {
    const layer = createOverpaintLayer(
      structure,
      chainId,
      seqIds,
      MUTATION_TEAL
    );
    if (layer) {
      layers.push(layer);
      logger.log(
        `[Mutation] Painted chain ${chainId} residues [${seqIds.join(", ")}] teal (#14b8a6)`
      );
    }
  }
  return layers;
}

/**
 * Apply overpaint layers to all representations of a structure
 * This colors residues without creating duplicate representations
 */
async function applyOverpaintToRepresentations(
  plugin: PluginUIContext,
  structureRef: string,
  layers: Array<{
    bundle: typeof StructureElement.Bundle.Empty;
    color: Color;
    clear: boolean;
  }>
): Promise<void> {
  if (layers.length === 0) return;

  try {
    const state = plugin.state.data;
    const update = state.build();

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
      logger.warn(
        "[Inpainting Metadata] No representations found to apply overpaint"
      );
      return;
    }

    // Apply overpaint to each representation
    for (const reprRef of representationRefs) {
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
      `[Inpainting Metadata] ✓ Applied overpaint with ${layers.length} layer(s) to ${representationRefs.length} representation(s)`
    );
  } catch (err) {
    logger.error("[Inpainting Metadata] Failed to apply overpaint:", err);
  }
}
