import React from "react";
import { useAtom, useAtomValue } from "jotai";
import { MissingRegionReviewSection } from "./repair/GapReviewSection";
import { ProjectManager } from "./ProjectManager";
import {
  fastaInputAtom,
  enableSequenceMappingAtom,
  skipTerminalAtom,
  erasedRegionsAtom,
  stagedPtmsAtom
} from "../store/repair-atoms";
import { eraseResiduesFromCif } from "../lib/cifErase";
import { countStructureTokens } from "../lib/tokenCount";
import {
  apiUrlAtom,
  apiConnectionStatusAtom,
  panelModeAtom,
  DEFAULT_API_URL,
  DEFAULT_SERVER_TOKEN_LIMIT
} from "../store/api-atoms";
import type { PanelMode } from "../store/api-atoms";
import { missingRegionsDetectedAtom } from "../store/repair-atoms";
import { pluginAtom } from "../store/mol-viewer-atoms";
import { useCurrentProject } from "../store/project-store";
import { bus } from "../lib/event-bus";
import { logger } from "../lib/logger";
import {
  pathBasename,
  pathDirname,
  pathJoin,
  pathIncludes,
  pathSplit
} from "../lib/path-utils";
import {
  Eye,
  EyeOff,
  FileText,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  FolderOpen,
  XCircle
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "./ui/dialog";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";
import { Alert, AlertDescription } from "./ui/alert";
import { Progress } from "./ui/progress";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent
} from "./ui/collapsible";
import { SimulationSection, type SavedSimulation } from "./SimulationSection";
import { ServerConnection } from "./ServerConnection";
import { DisconnectedHint } from "./DisconnectedHint";
import { SequenceEditorPanel } from "./SequenceEditorPanel";

const TAB_ITEMS: { key: PanelMode; label: string }[] = [
  { key: "project", label: "Project" },
  { key: "repair", label: "Repair" },
  { key: "simulation", label: "Simulation" }
];

export function ControlPanel(): React.ReactElement {
  const [panelMode, setPanelMode] = useAtom(panelModeAtom);

  return (
    <div className="relative h-full bg-white/60 dark:bg-neutral-900/40 backdrop-blur-xl">
      <div className="absolute inset-0 flex flex-col">
        {/* Tab bar */}
        <div className="flex w-full shrink-0 items-center justify-center rounded-md border-b bg-neutral-50/80 dark:bg-neutral-900/60 p-1 text-muted-foreground">
          {TAB_ITEMS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setPanelMode(tab.key)}
              className={cn(
                "inline-flex flex-1 items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-xs font-medium transition-all",
                panelMode === tab.key
                  ? "bg-background text-foreground shadow-sm"
                  : "hover:bg-background/50"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content — all panels stay mounted, hidden via CSS */}
        <div
          className="flex-1 overflow-auto p-4 space-y-4"
          style={panelMode === "project" ? undefined : { display: "none" }}
        >
          <ServerConnection />
          <ProjectManager />
        </div>
        {/* Single scroll container for the whole Repair column — the sections
            stack vertically and are reached by scrolling. RepairConsole itself
            must not add a second scroller, or the wheel gets trapped. */}
        <div
          style={panelMode === "repair" ? undefined : { display: "none" }}
          className="flex-1 min-h-0 overflow-auto"
        >
          <RepairConsole />
        </div>
        <div
          className="flex-1 overflow-auto p-4"
          style={panelMode === "simulation" ? undefined : { display: "none" }}
        >
          <SimulationPanel />
        </div>
      </div>
    </div>
  );
}

function RepairConsole(): React.ReactElement {
  type SectionId = "missing-region-review" | "sequence" | "context" | "results";
  const [expandedSections, setExpandedSections] = React.useState<
    Set<SectionId>
  >(new Set(["missing-region-review", "sequence", "context", "results"]));

  const currentProject = useCurrentProject();

  // Results state
  const [results, setResults] = React.useState<
    Array<{
      runId: string;
      runPath: string;
      predictionsPath: string;
      cifFiles: string[];
      quality?: {
        avgPLDDT: number;
        avgMolProbability: number;
        combinedScore: number;
      };
    }>
  >([]);
  const [loadingResults, setLoadingResults] = React.useState(false);
  const [visibleFiles, setVisibleFiles] = React.useState<Set<string>>(
    new Set()
  );
  const [loadedFiles, setLoadedFiles] = React.useState<Set<string>>(new Set());
  const [detailRunId, setDetailRunId] = React.useState<string | null>(null);
  const [detailYaml, setDetailYaml] = React.useState<string | null>(null);
  const [baseStructures, setBaseStructures] = React.useState<string[]>([]);

  // Results sorting state
  type SortField = "plddt" | "run";
  type SortOrder = "asc" | "desc";
  const [sortField, setSortField] = React.useState<SortField>("run");
  const [sortOrder, setSortOrder] = React.useState<SortOrder>("desc");

  // Use ref to track previous results without causing re-renders
  const previousResultsRef = React.useRef<
    Array<{
      runId: string;
      runPath: string;
      cifFiles: string[];
      quality?: {
        avgPLDDT: number;
        avgMolProbability: number;
        combinedScore: number;
      };
    }>
  >([]);

  const toggleSection = (section: SectionId): void => {
    setExpandedSections(current => {
      const newSet = new Set(current);
      if (newSet.has(section)) {
        newSet.delete(section);
      } else {
        newSet.add(section);
      }
      return newSet;
    });
  };

  // Handle superpose for a result file
  const handleSuperpose = React.useCallback(
    async (filePath: string, superpose: boolean = true) => {
      try {
        // Read the result file
        const fileResult = await window.api.project.readFileByPath(filePath);
        if (!fileResult.success || !fileResult.content) {
          logger.error(
            `Failed to read result file: ${fileResult.error || "Unknown error"}`
          );
          return;
        }

        // Emit event to load result with superposition
        bus.emit("inpainting:load-result", {
          filePath,
          fileContent: fileResult.content,
          superpose
        });

        logger.log(
          `✅ Result loaded ${superpose ? "with" : "without"} superposition: ${filePath}`
        );
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to load result";
        logger.error("❌ Error loading result:", message);
      }
    },
    []
  );

  // Load results when project is opened
  // Load base structures
  const loadBaseStructures = React.useCallback(async () => {
    if (!currentProject) {
      setBaseStructures([]);
      return;
    }

    try {
      const result = await window.api.project.listOriginalStructures();
      if (result.success && result.files) {
        // Convert filenames to full paths
        const basePaths = result.files.map(filename =>
          pathJoin(currentProject.structuresPath, "original", filename)
        );
        setBaseStructures(basePaths);

        // Base structures are loaded by MolViewerPanel automatically
        // Mark them as visible and loaded by default
        setVisibleFiles(prev => {
          const newSet = new Set(prev);
          basePaths.forEach(path => newSet.add(path));
          return newSet;
        });
        setLoadedFiles(prev => {
          const newSet = new Set(prev);
          basePaths.forEach(path => newSet.add(path));
          return newSet;
        });
      } else {
        setBaseStructures([]);
      }
    } catch (err) {
      logger.error("Failed to load base structures:", err);
      setBaseStructures([]);
    }
  }, [currentProject]);

  // Extract quality metrics from CIF file for specific inpainted residues
  const extractQualityMetricsFromCIF = React.useCallback(
    (
      cifContent: string,
      inpaintingRegionsByChain: Map<string, Set<number>>
    ): {
      totalPLDDT: number;
      totalMolProb: number;
      pLDDTCount: number;
      molProbCount: number;
    } => {
      let totalPLDDT = 0;
      const totalMolProb = 0; // Not available in Boltz-1 output
      let pLDDTCount = 0;
      const molProbCount = 0; // Not available in Boltz-1 output

      try {
        // Parse CIF file line by line
        // mmCIF format has data blocks like:
        // _atom_site.group_PDB
        // _atom_site.id
        // _atom_site.label_asym_id (chain)
        // _atom_site.label_seq_id (residue number)
        // _atom_site.B_iso_or_equiv (pLDDT for AI models)
        // _atom_site.occupancy (sometimes used for confidence in AI models)
        // ATOM 1 C CA ... 82.5 (last column is often B-factor/pLDDT)

        const lines = cifContent.split("\n");
        let inAtomSiteLoop = false;
        let columnIndices: {
          chainId?: number;
          seqId?: number;
          bFactor?: number;
        } = {};
        let columnNames: string[] = [];

        for (let i = 0; i < lines.length; i++) {
          const line = lines[i].trim();

          // Detect start of _atom_site loop
          if (line.startsWith("loop_")) {
            inAtomSiteLoop = false;
            columnNames = [];
            columnIndices = {};
            continue;
          }

          // Collect column names
          if (line.startsWith("_atom_site.")) {
            const columnName = line.split(/\s+/)[0];
            columnNames.push(columnName);

            if (
              columnName === "_atom_site.label_asym_id" ||
              columnName === "_atom_site.auth_asym_id"
            ) {
              columnIndices.chainId = columnNames.length - 1;
            } else if (
              columnName === "_atom_site.label_seq_id" ||
              columnName === "_atom_site.auth_seq_id"
            ) {
              columnIndices.seqId = columnNames.length - 1;
            } else if (columnName === "_atom_site.B_iso_or_equiv") {
              columnIndices.bFactor = columnNames.length - 1;
            }
            // Note: occupancy field exists but is not used for confidence

            if (columnName.startsWith("_atom_site.")) {
              inAtomSiteLoop = true;
            }
            continue;
          }

          // Parse atom site data
          if (
            inAtomSiteLoop &&
            !line.startsWith("_") &&
            !line.startsWith("#") &&
            line.length > 0
          ) {
            // Check if we have the required columns
            if (
              columnIndices.chainId === undefined ||
              columnIndices.seqId === undefined
            ) {
              continue;
            }

            // Parse the data line
            const tokens = line.match(/(?:[^\s"]+|"[^"]*")+/g);
            if (!tokens || tokens.length < columnNames.length) {
              continue;
            }

            const chainId = tokens[columnIndices.chainId].replace(/"/g, "");
            const seqIdStr = tokens[columnIndices.seqId].replace(/"/g, "");

            const seqId = parseInt(seqIdStr, 10);

            // Extract B-factor (pLDDT) if available
            let bFactor: number | null = null;
            if (columnIndices.bFactor !== undefined) {
              const bFactorStr = tokens[columnIndices.bFactor].replace(
                /"/g,
                ""
              );
              bFactor = parseFloat(bFactorStr);
            }

            // Check if this residue is in the inpainting regions
            const inpaintedResidues = inpaintingRegionsByChain.get(chainId);
            if (inpaintedResidues && inpaintedResidues.has(seqId)) {
              // Add pLDDT (B-factor) if available
              if (bFactor !== null && !isNaN(bFactor) && bFactor > 0) {
                totalPLDDT += bFactor;
                pLDDTCount++;
              }

              // Note: Molprobability is not available in Boltz-1 output CIF files
              // Occupancy field is for atom occupancy (typically 1.0), not confidence
              // We only use pLDDT for now
            }
          }

          // Exit loop when we hit a non-loop line after being in loop
          if (
            inAtomSiteLoop &&
            (line.startsWith("loop_") || line.startsWith("#"))
          ) {
            break;
          }
        }

        logger.log(
          `[Quality Metrics] CIF parsing complete: totalPLDDT=${totalPLDDT.toFixed(1)}, pLDDTCount=${pLDDTCount}, totalMolProb=${totalMolProb.toFixed(3)}, molProbCount=${molProbCount}`
        );

        // For molprobability, if not found in occupancy, it might be in a separate field
        // or not available at all (Boltz may not output this)
      } catch (err) {
        logger.error("[Quality Metrics] CIF parsing error:", err);
      }

      return { totalPLDDT, totalMolProb, pLDDTCount, molProbCount };
    },
    []
  );

  // Calculate quality metrics from metadata JSON files
  const calculateQualityMetrics = React.useCallback(
    async (cifFiles: string[], runPath?: string) => {
      try {
        logger.log(
          `[Quality Metrics] Calculating for ${cifFiles.length} CIF file(s)`
        );

        // First, try to find metadata files by searching directories
        const metadataFiles: string[] = [];

        // Strategy 1: Search in runPath/predictions directory recursively for all JSON files
        if (runPath) {
          try {
            const predictionsPath = pathJoin(runPath, "predictions");
            const searchForMetadataFiles = async (
              dirPath: string,
              depth = 0
            ): Promise<void> => {
              if (depth > 3) return; // Limit recursion depth

              try {
                const listResult =
                  await window.api.project.listDirectory(dirPath);
                if (listResult.success && listResult.files) {
                  for (const file of listResult.files) {
                    const filePath = pathJoin(dirPath, file);

                    // If it's a JSON file, try to read it
                    if (file.endsWith(".json")) {
                      try {
                        const result =
                          await window.api.project.readFileByPath(filePath);
                        if (result.success && result.content) {
                          // Check if it contains quality metrics
                          try {
                            const parsed = JSON.parse(result.content);
                            if (
                              parsed.average_plddt !== undefined ||
                              parsed.average_molprobability !== undefined
                            ) {
                              logger.log(
                                `[Quality Metrics] ✓ Found metadata file: ${filePath}`
                              );
                              metadataFiles.push(result.content);
                            }
                          } catch {
                            // Not valid JSON or not a metadata file
                          }
                        }
                      } catch {
                        // Could not read file
                      }
                    }
                    // If it's a directory, recurse
                    else if (!file.includes(".")) {
                      await searchForMetadataFiles(filePath, depth + 1);
                    }
                  }
                }
              } catch {
                // Could not list directory
              }
            };

            await searchForMetadataFiles(predictionsPath);
          } catch (err) {
            logger.log(
              `[Quality Metrics] Could not search predictions directory:`,
              err instanceof Error ? err.message : String(err)
            );
          }
        }

        // Strategy 2: Try to find metadata files by path matching (original method)
        for (const cifFile of cifFiles) {
          const pathParts = pathSplit(cifFile);
          const cifFileName = pathParts[pathParts.length - 1];
          const cifDir = pathDirname(cifFile);

          logger.log(
            `[Quality Metrics] Searching metadata for: ${cifFileName} in ${cifDir}`
          );

          // Use the directory immediately containing the CIF as the prefix
          // when it isn't a reserved name. Examples:
          // - ".../1kx3_CDEFGHIJAB/file.cif" -> "1kx3_CDEFGHIJAB"
          // - ".../1ton_A/file.cif"          -> "1ton_A"
          // - ".../1a22/file.cif"            -> "1a22"
          const immediateDir =
            pathParts.length >= 2 ? pathParts[pathParts.length - 2] : null;
          const chainPrefixMatch =
            immediateDir &&
            !immediateDir.startsWith("run_") &&
            immediateDir !== "predictions" &&
            immediateDir !== "results"
              ? immediateDir
              : undefined;

          // Try to extract chain prefix from filename itself
          let chainPrefix: string | null = null;
          if (cifFileName.includes("_")) {
            // Try to get prefix like "1kx3_CDEFGHIJAB" or "1ton_A"
            const parts = cifFileName.split("_");
            if (parts.length >= 2) {
              chainPrefix = parts.slice(0, 2).join("_");
            }
          }

          // Try single chain ID (for files like "1ton_A_model_0.cif")
          const singleChainMatch =
            cifFileName.match(/_([A-Z])_/) || cifFileName.match(/_([A-Z])\./);
          const singleChainId = singleChainMatch ? singleChainMatch[1] : null;

          // Build list of possible metadata paths
          const possibleMetadataPaths: string[] = [];

          // 1. Try with chain prefix from path (e.g., "1kx3_CDEFGHIJAB")
          if (chainPrefixMatch) {
            possibleMetadataPaths.push(
              pathJoin(cifDir, `inpainting_metadata_${chainPrefixMatch}.json`)
            );
          }

          // 2. Try with chain prefix from filename (e.g., "1kx3_CDEFGHIJAB")
          if (chainPrefix) {
            possibleMetadataPaths.push(
              pathJoin(cifDir, `inpainting_metadata_${chainPrefix}.json`)
            );
          }

          // 3. Try with single chain ID (e.g., "A")
          if (singleChainId) {
            possibleMetadataPaths.push(
              pathJoin(
                cifDir,
                `inpainting_metadata_${singleChainId.toLowerCase()}.json`
              )
            );
          }

          // 4. Try parent directory (for multi-chain files, metadata might be one level up)
          const parentDir = pathDirname(cifFile);
          if (chainPrefixMatch) {
            possibleMetadataPaths.push(
              pathJoin(
                parentDir,
                `inpainting_metadata_${chainPrefixMatch}.json`
              )
            );
          }
          if (chainPrefix) {
            possibleMetadataPaths.push(
              pathJoin(parentDir, `inpainting_metadata_${chainPrefix}.json`)
            );
          }

          // 5. Try searching in parent directories (up to 3 levels up)
          for (let i = 1; i <= 3; i++) {
            const upDir = pathParts.slice(0, -i - 1).join("/");
            if (upDir && chainPrefixMatch) {
              possibleMetadataPaths.push(
                pathJoin(upDir, `inpainting_metadata_${chainPrefixMatch}.json`)
              );
            }
            if (upDir && chainPrefix) {
              possibleMetadataPaths.push(
                pathJoin(upDir, `inpainting_metadata_${chainPrefix}.json`)
              );
            }
          }

          // 6. Try generic names (for multi-chain files)
          possibleMetadataPaths.push(
            pathJoin(cifDir, "inpainting_metadata.json")
          );
          possibleMetadataPaths.push(
            pathJoin(parentDir, "inpainting_metadata.json")
          );

          // Remove duplicates
          const uniquePaths = Array.from(new Set(possibleMetadataPaths));

          logger.log(
            `[Quality Metrics] Trying ${uniquePaths.length} possible paths:`,
            uniquePaths
          );

          for (const metadataPath of uniquePaths) {
            const result =
              await window.api.project.readFileByPath(metadataPath);
            if (result.success && result.content) {
              logger.log(`[Quality Metrics] ✓ Found metadata: ${metadataPath}`);
              metadataFiles.push(result.content);
              break; // Found one, no need to try others for this CIF file
            } else {
              logger.log(`[Quality Metrics] ✗ Not found: ${metadataPath}`);
            }
          }
        }

        if (metadataFiles.length === 0) {
          logger.warn(
            `[Quality Metrics] No metadata files found for ${cifFiles.length} CIF file(s)`
          );
          return null;
        }

        logger.log(
          `[Quality Metrics] Found ${metadataFiles.length} metadata file(s), extracting inpainting regions...`
        );

        // Parse metadata to get inpainting regions
        const inpaintingRegionsByChain = new Map<
          string,
          Set<number> // Set of residue numbers that were inpainted
        >();

        for (const metadataContent of metadataFiles) {
          try {
            const metadata = JSON.parse(metadataContent);

            logger.log(
              `[Quality Metrics] Metadata structure (first 500 chars):`,
              JSON.stringify(metadata, null, 2).substring(0, 500)
            );

            // Extract inpainting regions from metadata
            if (metadata.chains && typeof metadata.chains === "object") {
              for (const [chainId, chainData] of Object.entries(
                metadata.chains
              )) {
                const chainInfo = chainData as {
                  fully_fixed_residues?: number[];
                  partially_fixed_residues?: Array<{
                    residue: number;
                    fixed_atoms?: number;
                    total_atoms?: number;
                  }>;
                  fully_inpainted_residues?: number[];
                };

                const inpaintedResidues = new Set<number>();

                // Add partially fixed and fully inpainted residues
                // (fully_fixed residues are not inpainted)
                if (chainInfo.partially_fixed_residues) {
                  chainInfo.partially_fixed_residues.forEach(r =>
                    inpaintedResidues.add(typeof r === "number" ? r : r.residue)
                  );
                }
                if (chainInfo.fully_inpainted_residues) {
                  chainInfo.fully_inpainted_residues.forEach(r =>
                    inpaintedResidues.add(r)
                  );
                }

                if (inpaintedResidues.size > 0) {
                  inpaintingRegionsByChain.set(chainId, inpaintedResidues);
                  logger.log(
                    `[Quality Metrics] Chain ${chainId}: ${inpaintedResidues.size} inpainted residues`
                  );
                }
              }
            }
          } catch (err) {
            logger.error(
              "[Quality Metrics] Failed to parse metadata JSON:",
              err
            );
          }
        }

        if (inpaintingRegionsByChain.size === 0) {
          logger.warn(
            `[Quality Metrics] No inpainting regions found in metadata`
          );
          return null;
        }

        logger.log(
          `[Quality Metrics] Found inpainting regions for ${inpaintingRegionsByChain.size} chain(s), reading CIF files...`
        );

        // Read CIF files and extract quality metrics for inpainted residues
        let totalPLDDT = 0;
        let totalMolProb = 0;
        let pLDDTCount = 0;
        let molProbCount = 0;

        for (const cifFile of cifFiles) {
          try {
            logger.log(`[Quality Metrics] Reading CIF file: ${cifFile}`);
            const cifResult = await window.api.project.readFileByPath(cifFile);
            if (!cifResult.success || !cifResult.content) {
              logger.warn(`[Quality Metrics] Failed to read CIF: ${cifFile}`);
              continue;
            }

            const cifContent = cifResult.content;

            // Extract quality metrics from CIF file
            const metrics = extractQualityMetricsFromCIF(
              cifContent,
              inpaintingRegionsByChain
            );

            logger.log(
              `[Quality Metrics] Extracted from ${pathBasename(cifFile)}: ${metrics.pLDDTCount} pLDDT values, ${metrics.molProbCount} molprob values`
            );

            totalPLDDT += metrics.totalPLDDT;
            totalMolProb += metrics.totalMolProb;
            pLDDTCount += metrics.pLDDTCount;
            molProbCount += metrics.molProbCount;
          } catch (err) {
            logger.error(
              `[Quality Metrics] Failed to process CIF file ${cifFile}:`,
              err instanceof Error ? err.message : String(err)
            );
          }
        }

        if (pLDDTCount === 0 && molProbCount === 0) {
          logger.warn(
            `[Quality Metrics] No quality metrics found in metadata files`
          );
          return null;
        }

        const avgPLDDT = pLDDTCount > 0 ? totalPLDDT / pLDDTCount : 0;
        const avgMolProbability =
          molProbCount > 0 ? totalMolProb / molProbCount : 0;

        // Combined score: use only pLDDT since molprobability is not available
        const combinedScore = avgPLDDT;

        logger.log(
          `[Quality Metrics] ✓ Calculated: pLDDT=${avgPLDDT.toFixed(1)}, MP=${avgMolProbability.toFixed(3)}, Score=${combinedScore.toFixed(1)}`
        );

        return {
          avgPLDDT,
          avgMolProbability,
          combinedScore
        };
      } catch (err) {
        logger.error(
          "[Quality Metrics] Failed to calculate quality metrics:",
          err instanceof Error ? err.message : String(err)
        );
        return null;
      }
    },
    [extractQualityMetricsFromCIF]
  );

  const loadResults = React.useCallback(
    async (autoLoadLatest: boolean = false) => {
      if (!currentProject) {
        setResults([]);
        previousResultsRef.current = [];
        return;
      }

      setLoadingResults(true);
      try {
        // Load base structures
        await loadBaseStructures();

        const result = await window.api.project.listResults();
        if (result.success && result.results) {
          const previousResults = previousResultsRef.current;

          // Calculate quality metrics for each result
          const resultsWithQuality = await Promise.all(
            result.results.map(async r => {
              const quality = await calculateQualityMetrics(
                r.cifFiles,
                r.runPath
              );
              return {
                runId: r.runId,
                runPath: r.runPath,
                predictionsPath:
                  (r as { predictionsPath?: string }).predictionsPath ||
                  r.runPath,
                cifFiles: r.cifFiles,
                quality: quality || undefined
              };
            })
          );

          setResults(resultsWithQuality);
          previousResultsRef.current = resultsWithQuality;

          // Auto-load the latest result if requested
          if (autoLoadLatest && resultsWithQuality.length > 0) {
            // Find the latest result (highest run number)
            const latestResult = resultsWithQuality.reduce(
              (latest, current) => {
                const latestNum = parseInt(
                  latest.runId.replace("run_", "") || "0",
                  10
                );
                const currentNum = parseInt(
                  current.runId.replace("run_", "") || "0",
                  10
                );
                return currentNum > latestNum ? current : latest;
              }
            );

            // Check if this is a new result (not in previous results)
            const isNewResult =
              previousResults.length === 0 ||
              !previousResults.some(r => r.runId === latestResult.runId);

            if (isNewResult && latestResult.cifFiles.length > 0) {
              // Auto-load the first CIF file from the latest result
              const firstCifFile =
                latestResult.cifFiles.find(f => f.includes("model")) ||
                latestResult.cifFiles[0];

              logger.log(
                `🔄 Auto-loading latest result: ${latestResult.runId} - ${firstCifFile}`
              );

              // Add to visible files
              setVisibleFiles(prev => new Set(prev).add(firstCifFile));

              // Load and superpose
              await handleSuperpose(firstCifFile, true);
            }
          }
        } else {
          setResults([]);
          previousResultsRef.current = [];
        }
      } catch (err) {
        logger.error("Failed to load results:", err);
        setResults([]);
        previousResultsRef.current = [];
      } finally {
        setLoadingResults(false);
      }
    },
    [
      currentProject,
      handleSuperpose,
      loadBaseStructures,
      calculateQualityMetrics
    ]
  );

  React.useEffect(() => {
    void loadResults();
  }, [loadResults]);

  // Listen for structure loaded events to track loaded files
  React.useEffect(() => {
    const handleStructureLoaded = (event: { filePath: string }): void => {
      setLoadedFiles(prev => new Set(prev).add(event.filePath));
    };

    bus.on("inpainting:structure-loaded", handleStructureLoaded);

    return () => {
      bus.off("inpainting:structure-loaded", handleStructureLoaded);
    };
  }, []);

  // Toggle file visibility (load/hide)
  const toggleFileVisibility = React.useCallback(
    async (filePath: string) => {
      const isVisible = visibleFiles.has(filePath);
      const isLoaded = loadedFiles.has(filePath);

      if (isVisible) {
        // Hide: remove from visible set
        setVisibleFiles(prev => {
          const newSet = new Set(prev);
          newSet.delete(filePath);
          return newSet;
        });
        bus.emit("inpainting:remove-result", { filePath, visible: false });
      } else if (isLoaded) {
        // Show: already loaded, just make visible
        setVisibleFiles(prev => new Set(prev).add(filePath));
        bus.emit("inpainting:remove-result", { filePath, visible: true });
      } else {
        // Load for first time
        setVisibleFiles(prev => new Set(prev).add(filePath));
        setLoadedFiles(prev => new Set(prev).add(filePath));
        const isBaseStructure = pathIncludes(filePath, "/structures/original/");
        await handleSuperpose(filePath, !isBaseStructure);
      }
    },
    [visibleFiles, loadedFiles, handleSuperpose]
  );

  // Hide all visible files
  const hideAll = React.useCallback(async () => {
    if (visibleFiles.size === 0) return;

    const allVisibleFiles = Array.from(visibleFiles);
    setVisibleFiles(new Set());

    // Hide all structures in batch
    for (const filePath of allVisibleFiles) {
      bus.emit("inpainting:remove-result", { filePath, visible: false });
    }

    logger.log(`[Hide All] Hidden ${allVisibleFiles.length} structure(s)`);
  }, [visibleFiles]);

  // Load YAML file for a run
  const loadDetail = React.useCallback(
    async (runId: string, runPath: string) => {
      try {
        // YAML file is in predictions folder: runPath/predictions/*.yaml
        const predictionsPath = pathJoin(runPath, "predictions");
        let yamlContent: string | null = null;

        // First, list all files in predictions folder and find .yaml files
        const listResult =
          await window.api.project.listDirectory(predictionsPath);
        if (listResult.success && listResult.files) {
          // Find .yaml files (e.g., 4j76_AB.yaml, 1ton_A.yaml, project.yaml)
          const yamlFiles = listResult.files.filter(
            (f: string) => f.endsWith(".yaml") || f.endsWith(".yml")
          );

          logger.log(
            `[YAML Load] Found ${yamlFiles.length} YAML files in ${predictionsPath}:`,
            yamlFiles
          );

          // Try to load the first yaml file found
          for (const yamlFile of yamlFiles) {
            const yamlPath = pathJoin(predictionsPath, yamlFile);
            const yamlResult =
              await window.api.project.readFileByPath(yamlPath);
            if (yamlResult.success && yamlResult.content) {
              yamlContent = yamlResult.content;
              logger.log(`[YAML Load] Loaded: ${yamlPath}`);
              break;
            }
          }
        }

        // Fallback: try project.yaml in run directory
        if (!yamlContent) {
          const yamlPath = pathJoin(runPath, "project.yaml");
          const yamlResult = await window.api.project.readFileByPath(yamlPath);
          if (yamlResult.success && yamlResult.content) {
            yamlContent = yamlResult.content;
            logger.log(`[YAML Load] Loaded from run dir: ${yamlPath}`);
          }
        }

        // Fallback: try project root's project.yaml
        if (!yamlContent) {
          const yamlResult = await window.api.project.loadYAML();
          if (yamlResult.success && yamlResult.yaml) {
            // Convert YAML object back to string for display
            yamlContent = JSON.stringify(yamlResult.yaml, null, 2);
            logger.log(`[YAML Load] Loaded from project root`);
          }
        }

        if (yamlContent) {
          setDetailYaml(yamlContent);
          setDetailRunId(runId);
        } else {
          setDetailYaml("YAML file not found in predictions folder");
          setDetailRunId(runId);
        }
      } catch (err) {
        logger.error("Failed to load detail:", err);
        setDetailYaml("Failed to load YAML file");
        setDetailRunId(runId);
      }
    },
    []
  );

  return (
    <div>
      {/* Missing Region Review 섹션 */}
      <Section
        title="Missing & Incomplete Residues"
        expanded={expandedSections.has("missing-region-review")}
        onToggle={() => toggleSection("missing-region-review")}
      >
        <MissingRegionReviewSection />
      </Section>

      {/* Sequence 섹션 — 잔기 편집(Erase/Mutate/PTM) + UniProt 참조 서열.
          가장 키가 큰 섹션이므로 접을 수 있어야 아래 섹션에 닿을 수 있다. */}
      <Section
        title="Sequence"
        expanded={expandedSections.has("sequence")}
        onToggle={() => toggleSection("sequence")}
      >
        <SequenceEditorPanel />
      </Section>

      {/* Context & Inpaint 섹션 */}
      <Section
        title="Inference"
        expanded={expandedSections.has("context")}
        onToggle={() => toggleSection("context")}
      >
        <ContextInpaintSection
          onJobCompleted={() => {
            void loadResults(true); // Auto-load latest result
            bus.emit("results:updated");
          }}
        />
      </Section>

      {/* Results 섹션 */}
      {currentProject && (
        <Section
          title="Results"
          expanded={expandedSections.has("results")}
          onToggle={() => toggleSection("results")}
        >
          <div className="space-y-3">
            {/* Color legend moved to the 3D viewer (single source of truth). */}
            {/* Hide All Button */}
            <div className="flex justify-end">
              <Button
                onClick={hideAll}
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                disabled={visibleFiles.size === 0}
              >
                <EyeOff className="h-3 w-3 mr-1" />
                Hide All
              </Button>
            </div>
            {/* Base Structure Section */}
            {baseStructures.length > 0 && (
              <div className="space-y-2 border-b border-border pb-3">
                <div className="text-xs font-semibold text-foreground">
                  Base Structure
                </div>
                <div className="space-y-1">
                  {baseStructures.map((file, idx) => {
                    const isVisible = visibleFiles.has(file);
                    return (
                      <div
                        key={idx}
                        className="flex items-center justify-between text-xs p-1 rounded hover:bg-muted transition-colors"
                      >
                        <span
                          className="text-muted-foreground truncate flex-1 cursor-pointer"
                          onClick={() => toggleFileVisibility(file)}
                          title={isVisible ? "Click to hide" : "Click to show"}
                        >
                          {pathBasename(file)}
                        </span>
                        <Button
                          onClick={() => toggleFileVisibility(file)}
                          variant="ghost"
                          size="sm"
                          className="h-5 px-1"
                          title={isVisible ? "Click to hide" : "Click to show"}
                        >
                          {isVisible ? (
                            <Eye className="h-3 w-3 text-primary" />
                          ) : (
                            <EyeOff className="h-3 w-3" />
                          )}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs text-muted-foreground">
                Inpainting results
              </div>
              {results.length > 0 && (
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[10px]"
                    onClick={() => {
                      if (sortField === "plddt") {
                        setSortOrder(sortOrder === "asc" ? "desc" : "asc");
                      } else {
                        setSortField("plddt");
                        setSortOrder("desc");
                      }
                    }}
                    title="Sort by pLDDT"
                  >
                    pLDDT
                    {sortField === "plddt" ? (
                      sortOrder === "asc" ? (
                        <ArrowUp className="ml-1 h-3 w-3" />
                      ) : (
                        <ArrowDown className="ml-1 h-3 w-3" />
                      )
                    ) : (
                      <ArrowUpDown className="ml-1 h-3 w-3 opacity-50" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[10px]"
                    onClick={() => {
                      if (sortField === "run") {
                        setSortOrder(sortOrder === "asc" ? "desc" : "asc");
                      } else {
                        setSortField("run");
                        setSortOrder("desc");
                      }
                    }}
                    title="Sort by run order"
                  >
                    Run
                    {sortField === "run" ? (
                      sortOrder === "asc" ? (
                        <ArrowUp className="ml-1 h-3 w-3" />
                      ) : (
                        <ArrowDown className="ml-1 h-3 w-3" />
                      )
                    ) : (
                      <ArrowUpDown className="ml-1 h-3 w-3 opacity-50" />
                    )}
                  </Button>
                </div>
              )}
            </div>
            {loadingResults ? (
              <div className="text-xs text-muted-foreground text-center py-4">
                Loading results...
              </div>
            ) : results.length === 0 ? (
              <div className="text-xs text-muted-foreground text-center py-4">
                No results yet. Run inpainting to generate results.
              </div>
            ) : (
              <div
                className="space-y-2 max-h-96 overflow-y-scroll"
                style={{ scrollbarGutter: "stable" }}
              >
                {results
                  .slice()
                  .sort((a, b) => {
                    if (sortField === "plddt") {
                      const aPLDDT = a.quality?.avgPLDDT ?? 0;
                      const bPLDDT = b.quality?.avgPLDDT ?? 0;
                      return sortOrder === "asc"
                        ? aPLDDT - bPLDDT
                        : bPLDDT - aPLDDT;
                    } else {
                      // Sort by run number
                      const aNum = parseInt(
                        a.runId.replace("run_", "") || "0",
                        10
                      );
                      const bNum = parseInt(
                        b.runId.replace("run_", "") || "0",
                        10
                      );
                      return sortOrder === "asc" ? aNum - bNum : bNum - aNum;
                    }
                  })
                  .map(result => (
                    <div
                      key={result.runId}
                      className="border border-border rounded p-2 bg-background"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <div className="font-mono text-xs font-semibold">
                            {result.runId}
                          </div>
                          {result.quality && (
                            <div className="flex items-center gap-1 text-[10px]">
                              <span
                                className="px-1.5 py-0.5 rounded bg-neutral-500/20 text-neutral-400 font-medium"
                                title={`Average pLDDT: ${result.quality.avgPLDDT.toFixed(1)}`}
                              >
                                pLDDT: {result.quality.avgPLDDT.toFixed(1)}
                              </span>
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-1">
                          <Button
                            onClick={async () => {
                              try {
                                await window.api.project.openFolder(
                                  result.predictionsPath
                                );
                              } catch (error) {
                                logger.error("Failed to open folder:", error);
                              }
                            }}
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2"
                            title="Open CIF files folder"
                          >
                            <FolderOpen className="h-3 w-3" />
                          </Button>
                          <Button
                            onClick={async () => {
                              if (detailRunId === result.runId) {
                                setDetailRunId(null);
                                setDetailYaml(null);
                              } else {
                                await loadDetail(result.runId, result.runPath);
                              }
                            }}
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2"
                            title="View YAML file"
                          >
                            <FileText
                              className={`h-3 w-3 ${
                                detailRunId === result.runId
                                  ? "text-primary"
                                  : ""
                              }`}
                            />
                          </Button>
                        </div>
                      </div>
                      {result.cifFiles.filter(
                        file =>
                          file.toLowerCase().includes("model") &&
                          !file.toLowerCase().includes("template")
                      ).length > 0 ? (
                        <div className="space-y-1">
                          {result.cifFiles
                            .filter(
                              file =>
                                file.toLowerCase().includes("model") &&
                                !file.toLowerCase().includes("template")
                            )
                            .map((file, idx) => {
                              const isVisible = visibleFiles.has(file);
                              return (
                                <div
                                  key={idx}
                                  className="flex items-center justify-between text-xs p-1 rounded hover:bg-muted transition-colors"
                                >
                                  <span
                                    className="text-muted-foreground truncate flex-1 cursor-pointer"
                                    onClick={() => toggleFileVisibility(file)}
                                    title={
                                      isVisible
                                        ? "Click to hide"
                                        : "Click to show"
                                    }
                                  >
                                    {pathBasename(file)}
                                  </span>
                                  <Button
                                    onClick={() => toggleFileVisibility(file)}
                                    variant="ghost"
                                    size="sm"
                                    className="h-5 px-1"
                                    title={
                                      isVisible
                                        ? "Click to hide"
                                        : "Click to show"
                                    }
                                  >
                                    {isVisible ? (
                                      <Eye className="h-3 w-3 text-primary" />
                                    ) : (
                                      <EyeOff className="h-3 w-3" />
                                    )}
                                  </Button>
                                </div>
                              );
                            })}
                        </div>
                      ) : (
                        <div className="text-xs text-muted-foreground">
                          No CIF files found
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>
        </Section>
      )}

      {/* YAML Detail Dialog */}
      <Dialog
        open={detailRunId !== null && detailYaml !== null}
        onOpenChange={open => {
          if (!open) {
            setDetailRunId(null);
            setDetailYaml(null);
          }
        }}
      >
        <DialogContent className="max-w-4xl w-[90vw] max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>YAML Configuration - {detailRunId || ""}</DialogTitle>
            <DialogDescription>
              YAML file used for this inpainting run
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 flex-1 min-h-0 overflow-hidden">
            <pre className="text-xs font-mono overflow-x-auto overflow-y-auto h-full whitespace-pre-wrap break-words p-4 bg-muted rounded border border-border">
              {detailYaml || ""}
            </pre>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

interface SectionProps {
  title: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function Section({
  title,
  expanded,
  onToggle,
  children
}: SectionProps): React.ReactElement {
  return (
    <Collapsible open={expanded} onOpenChange={() => onToggle()}>
      <CollapsibleTrigger>{title}</CollapsibleTrigger>
      <CollapsibleContent className="px-4 pb-4">{children}</CollapsibleContent>
    </Collapsible>
  );
}

function ContextInpaintSection({
  onJobCompleted
}: {
  onJobCompleted?: () => void;
}): React.ReactElement {
  const currentProject = useCurrentProject();
  const [fastaInput] = useAtom(fastaInputAtom);
  const [enableSequenceMapping] = useAtom(enableSequenceMappingAtom);
  const skipTerminal = useAtomValue(skipTerminalAtom);
  const [erasedRegions] = useAtom(erasedRegionsAtom);
  const [stagedPtms] = useAtom(stagedPtmsAtom);
  // Skip-terminal is an independent choice (the Sequence editor's toggle), even
  // when a reference sequence is provided.
  const skipTerminalEffective = skipTerminal;

  const apiUrl = useAtomValue(apiUrlAtom);
  const connectionStatus = useAtomValue(apiConnectionStatusAtom);
  const plugin = useAtomValue(pluginAtom);
  const missingRegions = useAtomValue(missingRegionsDetectedAtom);

  // Estimated model tokens for the loaded structure (protein = per-residue,
  // nucleic/ligand = per-atom). Recompute when a structure loads.
  const tokenCount = React.useMemo(
    () => countStructureTokens(plugin),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [plugin, missingRegions]
  );
  const usingDefaultServer = apiUrl === DEFAULT_API_URL;
  const overTokenLimit =
    tokenCount.total > DEFAULT_SERVER_TOKEN_LIMIT && usingDefaultServer;

  const [jobId, setJobId] = React.useState<string | null>(null);
  const [jobStatus, setJobStatus] = React.useState<string>("idle");
  const [progress, setProgress] = React.useState(0);
  const [progressMessage, setProgressMessage] = React.useState<string | null>(
    null
  );
  // GPU queue position while the job waits for a free GPU (whole-cluster).
  const [queueInfo, setQueueInfo] = React.useState<{
    position: number;
    total: number;
    running: number;
  } | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Always use ALL chains — server resolves automatically
  const availableChains = React.useMemo(() => ["ALL"], []);

  // Parse FASTA sequences
  const parseFastaSequences = React.useCallback(
    (fastaText: string): Map<string, string> => {
      const sequences = new Map<string, string>();
      let currentChain: string | null = null;
      let currentSeq: string[] = [];

      for (const line of fastaText.split("\n")) {
        const trimmed = line.trim();
        if (trimmed.startsWith(">")) {
          // Save previous chain
          if (currentChain && currentSeq.length > 0) {
            sequences.set(currentChain, currentSeq.join(""));
          }

          // Parse chain from header (e.g., ">Chain A" -> "A")
          const header = trimmed.substring(1).trim();
          if (header.includes("Chain")) {
            currentChain = header.split("Chain")[1]?.trim() || null;
          } else {
            const parts = header.split(/\s+/);
            currentChain = parts.length > 0 ? parts[0] : null;
          }
          currentSeq = [];
        } else if (trimmed && currentChain) {
          currentSeq.push(trimmed);
        }
      }

      // Save last chain
      if (currentChain && currentSeq.length > 0) {
        sequences.set(currentChain, currentSeq.join(""));
      }

      return sequences;
    },
    []
  );

  // Start inpainting
  const handleStartInpainting = async (): Promise<void> => {
    if (!currentProject) {
      setError("No project is open");
      return;
    }

    // Check if connection is tested and connected
    if (connectionStatus !== "connected") {
      setError("Please test connection first before starting inpainting.");
      return;
    }

    // The hosted default server (a 3090) tops out around DEFAULT_SERVER_TOKEN_LIMIT
    // tokens. Block bigger structures and tell the user to run their own server.
    if (overTokenLimit) {
      setError(
        `This structure is ~${tokenCount.total} tokens, above the default ` +
          `server's ~${DEFAULT_SERVER_TOKEN_LIMIT}-token limit (protein counts ` +
          `per residue; DNA/RNA/ligands per atom). Start your own inference ` +
          `server and set its URL in the Project tab, then try again.`
      );
      return;
    }

    // availableChains is always ["ALL"] — no need to check

    // Reset state if starting a new job after completion
    if (jobStatus === "completed") {
      setJobId(null);
      // setResultFiles([]); // Result files are managed in Results section
      setProgress(0);
      setProgressMessage(null);
    }

    setError(null);
    setQueueInfo(null);
    setJobStatus("uploading");

    try {
      // 1. Parse FASTA sequences (only if sequence mapping is enabled and FASTA is provided)
      let customSequencesStr = "";
      if (enableSequenceMapping && fastaInput.trim()) {
        const sequences = parseFastaSequences(fastaInput);
        if (sequences.size > 0) {
          customSequencesStr = Array.from(sequences.entries())
            .map(([chain, seq]) => `${chain}:${seq}`)
            .join(",");
        }
      }
      // If sequence mapping is disabled or FASTA is empty, customSequencesStr will be empty string
      // Server will handle it automatically

      // 2. Get CIF file from project
      const structuresResult =
        await window.api.project.listOriginalStructures();
      if (!structuresResult.success || !structuresResult.files?.length) {
        throw new Error("No structure files found in project");
      }

      const cifFile = structuresResult.files[0];
      const cifContentResult = await window.api.project.readStructureFile(
        "original",
        cifFile
      );
      if (!cifContentResult.success || !cifContentResult.content) {
        throw new Error("Failed to read structure file");
      }

      // 2b. Apply erased regions marked in the Sequence editor: strip those
      // residues so the backend re-detects them as missing and regenerates them.
      let cifContent = cifContentResult.content;
      if (erasedRegions.length > 0) {
        let totalAtoms = 0;
        let totalResidues = 0;
        for (const region of erasedRegions) {
          if (region.residues.length === 0) continue;
          const erased = eraseResiduesFromCif(
            cifContent,
            region.chainId,
            region.residues
          );
          if (erased.erasedAtoms === 0) {
            throw new Error(
              `Erase failed: no matching atoms found for ${region.label}. ` +
                `The structure may not be mmCIF.`
            );
          }
          cifContent = erased.content;
          totalAtoms += erased.erasedAtoms;
          totalResidues += erased.erasedResidues;
        }
        logger.log(
          `[Erase] Removed ${totalResidues} residue(s) / ${totalAtoms} atom(s) ` +
            `across ${erasedRegions.length} region(s) before upload`
        );
      }

      // 2c. Apply staged PTMs: forwarded to the backend as a modifications
      // field so Boltz models each modified residue.
      const modificationsStr = stagedPtms
        .map(p => `${p.chainId}:${p.seqId}:${p.ccd}`)
        .join(",");
      if (modificationsStr) {
        logger.log(`[PTM] Requesting modifications ${modificationsStr}`);
      }

      // 3. Upload template
      if (!window.api?.boltz?.uploadTemplate) {
        throw new Error("Boltz API not available");
      }

      const uploadResult = await window.api.boltz.uploadTemplate(
        apiUrl,
        cifContent,
        cifFile,
        availableChains,
        customSequencesStr,
        skipTerminalEffective,
        modificationsStr
      );

      if (!uploadResult.success || !uploadResult.data) {
        const errorMsg = uploadResult.error || "Upload failed";
        const requestInfo = {
          apiUrl,
          chains: availableChains,
          structureFile: cifFile,
          customSequences: customSequencesStr || "(none)"
        };
        const fullErrorMsg =
          `${errorMsg}\n\nRequest details:\n` +
          `  API URL: ${requestInfo.apiUrl}\n` +
          `  Chains: [${requestInfo.chains.join(", ")}]\n` +
          `  Structure file: ${requestInfo.structureFile}\n` +
          `  Custom sequences: ${requestInfo.customSequences}`;

        logger.error("[Template Upload Failed]", {
          error: errorMsg,
          request: requestInfo
        });

        throw new Error(fullErrorMsg);
      }

      const newJobId = uploadResult.data.job_id;
      setJobId(newJobId);
      setJobStatus("template_generating");

      // NOTE: staged edits (erase/mutate/PTM) are intentionally NOT cleared here.
      // They stay visible (with their 3D ghosting) for the duration of the run so
      // the user sees what's being regenerated, and — crucially — so a failed
      // download can be retried without having to re-mark everything. They are
      // cleared only once the job completes and the result is loaded (below).

      // Store request info for error logging
      const requestInfo = {
        apiUrl,
        chains: availableChains,
        customSequences: customSequencesStr || "(none)",
        structureFile: cifFile,
        jobId: newJobId
      };

      // 4. Wait for template generation
      while (true) {
        if (!window.api?.boltz?.getJobStatus) {
          throw new Error("Boltz API not available");
        }

        const statusResult = await window.api.boltz.getJobStatus(
          apiUrl,
          newJobId
        );

        if (!statusResult.success || !statusResult.data) {
          const errorMsg = statusResult.error || "Status check failed";
          const fullErrorMsg =
            `${errorMsg}\n\nRequest details:\n` +
            `  API URL: ${requestInfo.apiUrl}\n` +
            `  Chains: [${requestInfo.chains.join(", ")}]\n` +
            `  Structure file: ${requestInfo.structureFile}\n` +
            `  Custom sequences: ${requestInfo.customSequences}\n` +
            `  Job ID: ${requestInfo.jobId}`;

          logger.error("[Template Status Check Failed]", {
            error: errorMsg,
            request: requestInfo
          });

          throw new Error(fullErrorMsg);
        }

        const status = statusResult.data;

        if (status.status === "completed") {
          setJobStatus("running_prediction");
          break;
        } else if (status.status === "failed") {
          const errorMsg = status.error || "Template generation failed";
          const fullErrorMsg =
            `${errorMsg}\n\nRequest details:\n` +
            `  API URL: ${requestInfo.apiUrl}\n` +
            `  Chains: [${requestInfo.chains.join(", ")}]\n` +
            `  Structure file: ${requestInfo.structureFile}\n` +
            `  Custom sequences: ${requestInfo.customSequences}\n` +
            `  Job ID: ${requestInfo.jobId}`;

          logger.error("[Template Generation Failed]", {
            error: errorMsg,
            request: requestInfo
          });

          throw new Error(fullErrorMsg);
        }

        if (status.progress) {
          const prog: unknown = status.progress;
          if (typeof prog === "string") {
            const percentMatch = prog.match(/\((\d+)%\)/);
            if (percentMatch) {
              setProgress(parseInt(percentMatch[1] || "0", 10));
            }
            setProgressMessage(prog);
          } else if (typeof prog === "number") {
            setProgress(prog);
            setProgressMessage(null);
          }
        }

        // Use requestAnimationFrame for non-blocking delay instead of setTimeout
        await new Promise(resolve => {
          let frames = 0;
          const maxFrames = 120; // ~2 seconds at 60fps
          const checkFrame = (): void => {
            frames++;
            if (frames >= maxFrames) {
              resolve(undefined);
            } else {
              requestAnimationFrame(checkFrame);
            }
          };
          requestAnimationFrame(checkFrame);
        });
      }

      // 5. Run prediction
      if (!window.api?.boltz?.runPrediction) {
        throw new Error("Boltz API not available");
      }

      const predictionPayload = {
        job_id: newJobId,
        recycling_steps: 3,
        sampling_steps: 200,
        diffusion_samples: 1,
        devices: 1,
        accelerator: "gpu",
        use_msa_server: false
      };

      const predictResult = await window.api.boltz.runPrediction(
        apiUrl,
        predictionPayload
      );

      if (!predictResult.success) {
        throw new Error(predictResult.error || "Prediction start failed");
      }

      setJobStatus("running");

      // 6. Monitor progress
      let monitorInterval: NodeJS.Timeout | null = null;
      monitorInterval = setInterval(async () => {
        try {
          if (!window.api?.boltz?.getJobStatus) {
            logger.error("Boltz API not available");
            if (monitorInterval) clearInterval(monitorInterval);
            setJobStatus("failed");
            setError("Boltz API not available");
            return;
          }

          const statusResult = await window.api.boltz.getJobStatus(
            apiUrl,
            newJobId
          );

          if (!statusResult.success || !statusResult.data) {
            logger.error("Status check failed:", statusResult.error);
            if (monitorInterval) clearInterval(monitorInterval);
            setJobStatus("failed");
            setError(statusResult.error || "Status check failed");
            return;
          }

          const status = statusResult.data;

          // While the job is queued (backend "pending"), surface its live
          // whole-cluster GPU queue position instead of a fake progress bar.
          if (status.status === "pending") {
            setJobStatus("queued");
            setProgress(0);
            setProgressMessage(null);
            try {
              const q = await window.api.boltz.queueStatus?.(apiUrl, newJobId);
              const jp = q?.success ? q.data?.job : undefined;
              if (jp && jp.state === "queued" && jp.position) {
                setQueueInfo({
                  position: jp.position,
                  total: q!.data!.total,
                  running: q!.data!.running
                });
              } else {
                setQueueInfo(null);
              }
            } catch {
              setQueueInfo(null);
            }
            return; // don't fall through to progress parsing while queued
          }
          // No longer queued — clear queue info and show real progress.
          setQueueInfo(null);
          if (status.status === "running_prediction") setJobStatus("running");

          // Update progress display
          if (status.progress !== undefined) {
            let progressValue = 0;
            const prog: unknown = status.progress;
            if (typeof prog === "string") {
              // Parse progress from formats like:
              // - "Recycling step 1/4 (20%)"
              // - "Diffusion step 48/592 (44%)"
              // - "Prediction completed successfully"
              const percentMatch = prog.match(/\((\d+)%\)/);
              if (percentMatch) {
                progressValue = parseInt(percentMatch[1] || "0", 10);
              } else {
                // If no percentage found, try to extract any number
                const numberMatch = prog.match(/\d+/);
                if (numberMatch) {
                  progressValue = parseInt(numberMatch[0] || "0", 10);
                }
              }
              setProgressMessage(prog);
            } else if (typeof prog === "number") {
              progressValue = prog;
              setProgressMessage(null);
            }
            setProgress(progressValue);
          }

          if (status.status === "completed") {
            if (monitorInterval) clearInterval(monitorInterval);
            setJobStatus("downloading");
            setProgress(100);
            setProgressMessage("Prediction completed successfully");

            // Download and save results
            try {
              const downloadResult =
                await window.api.boltz.downloadAndSaveResults(apiUrl, newJobId);

              if (!downloadResult.success) {
                throw new Error(
                  downloadResult.error || "Failed to download results"
                );
              }

              setJobStatus("completed");
              setError(null);

              // NOTE: staged edits (erase/mutate/PTM) are intentionally NOT
              // cleared on completion — the user keeps their marks + ghosting so
              // they can compare, re-run, or tweak. They are cleared only via the
              // explicit "Reset" button in the Sequence editor.

              // Results are automatically available in Results section
              // No need to store resultFiles here anymore
              if (
                downloadResult.cifFiles &&
                downloadResult.cifFiles.length > 0
              ) {
                logger.log(
                  `✓ Results saved: ${downloadResult.cifFiles.length} file(s)`
                );
              }

              // Notify parent to refresh results
              if (onJobCompleted) {
                onJobCompleted();
              }
            } catch (err) {
              setJobStatus("failed");
              setError(
                err instanceof Error ? err.message : "Failed to process results"
              );
            }
          } else if (status.status === "failed") {
            if (monitorInterval) clearInterval(monitorInterval);
            setJobStatus("failed");
            setError(status.error || "Prediction failed");
          }
        } catch (err) {
          logger.error("Failed to check status:", err);
          if (monitorInterval) clearInterval(monitorInterval);
          setJobStatus("failed");
          setError(
            err instanceof Error ? err.message : "Failed to check status"
          );
        }
      }, 5000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setJobStatus("failed");
      setProgress(0);
      setProgressMessage(null);
    }
  };

  return (
    <div className="space-y-4 p-4">
      {/* Status Display */}
      {jobStatus !== "idle" && (
        <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex justify-between text-xs">
            <span className="font-medium">Status:</span>
            <span className="capitalize">
              {jobStatus === "uploading"
                ? "Uploading structure..."
                : jobStatus === "template_generating"
                  ? "Generating template..."
                  : jobStatus === "queued"
                    ? "Waiting in queue..."
                    : jobStatus === "running_prediction"
                      ? "Starting prediction..."
                      : jobStatus === "running"
                        ? "Running prediction..."
                        : jobStatus === "downloading"
                          ? "Downloading results..."
                          : jobStatus === "completed"
                            ? "Completed"
                            : jobStatus === "failed"
                              ? "Failed"
                              : jobStatus.replace("_", " ")}
            </span>
          </div>
          {jobId && (
            <div className="text-xs text-muted-foreground">Job ID: {jobId}</div>
          )}
          {jobStatus === "queued" && (
            <div className="mt-2 rounded-md border border-blue-400/30 bg-blue-500/5 px-3 py-2">
              {queueInfo ? (
                <>
                  <div className="text-sm font-semibold text-blue-600 dark:text-blue-400">
                    #{queueInfo.position} in queue
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {queueInfo.position <= 1
                      ? "You're next — waiting for a free GPU."
                      : `${queueInfo.position - 1} job${
                          queueInfo.position - 1 === 1 ? "" : "s"
                        } ahead of you.`}
                    {` · ${queueInfo.running} running now.`}
                  </div>
                </>
              ) : (
                <div className="text-xs text-muted-foreground">
                  Waiting for a free GPU…
                </div>
              )}
            </div>
          )}
          {jobStatus !== "queued" && (progress > 0 || jobStatus === "running") && (
            <div className="mt-2">
              <Progress value={progress} className="h-2" />
              <div className="mt-1 text-xs text-muted-foreground">
                {progressMessage ? (
                  <div>
                    <div className="font-medium">{progressMessage}</div>
                    {progress > 0 && (
                      <div className="mt-0.5">{Math.round(progress)}%</div>
                    )}
                  </div>
                ) : (
                  <div>
                    {Math.round(progress)}%
                    {jobStatus === "running" &&
                      progress < 100 &&
                      " - This may take a while..."}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Error Display */}
      {error && (
        <Alert variant="destructive">
          <XCircle className="h-3 w-3" />
          <AlertDescription className="text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {/* Token estimate + over-limit warning */}
      {tokenCount.total > 0 && (
        <div
          className={cn(
            "rounded-md border px-3 py-2 text-xs",
            overTokenLimit
              ? "border-red-400/40 bg-red-500/5 text-red-600 dark:text-red-400"
              : "border-border bg-muted/20 text-muted-foreground"
          )}
        >
          <div className="flex items-center justify-between">
            <span>
              Estimated tokens:{" "}
              <span className="font-mono font-semibold">
                {tokenCount.total}
              </span>
              {usingDefaultServer && ` / ${DEFAULT_SERVER_TOKEN_LIMIT}`}
            </span>
            <span className="opacity-70">
              {tokenCount.proteinResidues} res + {tokenCount.atomTokens} atoms
            </span>
          </div>
          {overTokenLimit && (
            <p className="mt-1">
              Above the default server's ~{DEFAULT_SERVER_TOKEN_LIMIT}-token
              limit (3090).{" "}
              <a
                href="https://github.com/DeepFoldProtein/patchr"
                target="_blank"
                rel="noreferrer"
                className="font-medium underline underline-offset-2 hover:opacity-80"
              >
                Start your own inference server
              </a>{" "}
              and set its URL in the Project tab.
            </p>
          )}
        </div>
      )}

      {/* Action Buttons */}
      <div className="space-y-2">
        <button
          onClick={handleStartInpainting}
          disabled={
            connectionStatus !== "connected" ||
            overTokenLimit ||
            (jobStatus !== "idle" &&
              jobStatus !== "failed" &&
              jobStatus !== "completed") ||
            (enableSequenceMapping && !fastaInput.trim())
          }
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {jobStatus === "idle" ||
          jobStatus === "failed" ||
          jobStatus === "completed"
            ? "Start Patch"
            : "Running..."}
        </button>
        <DisconnectedHint />
      </div>

      {/* Info */}
      <div className="rounded-md border border-border bg-muted/20 p-3">
        <p className="text-xs text-muted-foreground">
          Chains: All (auto-detected by server)
        </p>
        {!currentProject && (
          <p className="mt-1 text-xs text-red-400">
            Please open a project first
          </p>
        )}
      </div>
    </div>
  );
}

// ========================================
// Simulation Panel (separate tab)
// ========================================

function SimulationPanel(): React.ReactElement {
  const currentProject = useCurrentProject();
  const [results, setResults] = React.useState<
    Array<{
      runId: string;
      runPath: string;
      predictionsPath: string;
      cifFiles: string[];
    }>
  >([]);
  const [savedSims, setSavedSims] = React.useState<SavedSimulation[]>([]);

  const loadData = React.useCallback(async () => {
    if (!currentProject) {
      setResults([]);
      setSavedSims([]);
      return;
    }
    try {
      const [resultRes, simRes] = await Promise.all([
        window.api.project.listResults(),
        window.api.project.listSimulations()
      ]);
      if (resultRes.success && resultRes.results) {
        setResults(
          resultRes.results.map(r => ({
            runId: r.runId,
            runPath: r.runPath,
            predictionsPath:
              (r as { predictionsPath?: string }).predictionsPath || r.runPath,
            cifFiles: r.cifFiles
          }))
        );
      }
      if (simRes.success && simRes.simulations) {
        setSavedSims(simRes.simulations);
      }
    } catch {
      // ignore
    }
  }, [currentProject]);

  React.useEffect(() => {
    void loadData();
  }, [loadData]);

  // Reload when inpainting results are updated
  React.useEffect(() => {
    const handler = (): void => {
      void loadData();
    };
    bus.on("results:updated", handler);
    return () => {
      bus.off("results:updated", handler);
    };
  }, [loadData]);

  if (!currentProject) {
    return (
      <div className="text-sm text-muted-foreground text-center py-8">
        Open a project to access simulation tools.
      </div>
    );
  }

  return <SimulationSection results={results} savedSims={savedSims} />;
}
