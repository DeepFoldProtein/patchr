import React from "react";
import { useAtom, useAtomValue } from "jotai";
import { MissingRegionReviewSection } from "./repair/GapReviewSection";
import { ProjectManager } from "./ProjectManager";
import {
  selectedRepairSegmentsAtom,
  fastaInputAtom,
  enableSequenceMappingAtom,
  apiConnectionStatusAtom
} from "../store/repair-atoms";
import { useCurrentProject } from "../store/project-store";
import { pluginAtom } from "../store/mol-viewer-atoms";
import { getSequencePanelData } from "./mol-viewer/useGapDetection";
import { bus } from "../lib/event-bus";
import {
  Eye,
  EyeOff,
  FileText,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  FolderOpen,
  Monitor,
  Cloud,
  ExternalLink,
  ChevronRight,
  ServerOff
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "./ui/dialog";
import { Button } from "./ui/button";

export function ControlPanel(): React.ReactElement {
  const [panelMode, setPanelMode] = React.useState<"project" | "repair">(
    "repair"
  );

  return (
    <div className="flex h-full flex-col bg-white/60 dark:bg-slate-900/40 backdrop-blur-xl">
      {/* 패널 모드 토글 */}
      <div className="flex border-b border-slate-200/50 dark:border-slate-800/50 bg-slate-50/80 dark:bg-slate-900/60">
        <button
          onClick={() => setPanelMode("project")}
          className={`relative flex-1 px-4 py-3 text-sm font-medium transition-all ${
            panelMode === "project"
              ? "text-slate-900 dark:text-white"
              : "text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-300"
          }`}
        >
          <span className="relative z-10">Project</span>
          {panelMode === "project" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500" />
          )}
        </button>
        <button
          onClick={() => setPanelMode("repair")}
          className={`relative flex-1 px-4 py-3 text-sm font-medium transition-all ${
            panelMode === "repair"
              ? "text-slate-900 dark:text-white"
              : "text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-300"
          }`}
        >
          <span className="relative z-10">Repair Console</span>
          {panelMode === "repair" && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500" />
          )}
        </button>
      </div>

      {/* Project Manager - always mounted, hidden with CSS */}
      <div
        className={`flex-1 overflow-auto p-4 ${panelMode === "project" ? "" : "hidden"}`}
      >
        <ProjectManager />
      </div>

      {/* Repair Console - always mounted, hidden with CSS */}
      <div
        className={
          panelMode === "repair"
            ? "flex-1 flex flex-col overflow-hidden"
            : "hidden"
        }
      >
        <RepairConsole />
      </div>
    </div>
  );
}

function RepairConsole(): React.ReactElement {
  type SectionId = "missing-region-review" | "sequence" | "context" | "results";
  const [expandedSections, setExpandedSections] = React.useState<
    Set<SectionId>
  >(new Set(["missing-region-review", "context", "results"]));

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
          console.error(
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

        console.log(
          `✅ Result loaded ${superpose ? "with" : "without"} superposition: ${filePath}`
        );
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to load result";
        console.error("❌ Error loading result:", message);
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
        const basePaths = result.files.map(
          filename => `${currentProject.structuresPath}/original/${filename}`
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
      console.error("Failed to load base structures:", err);
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

        console.log(
          `[Quality Metrics] CIF parsing complete: totalPLDDT=${totalPLDDT.toFixed(1)}, pLDDTCount=${pLDDTCount}, totalMolProb=${totalMolProb.toFixed(3)}, molProbCount=${molProbCount}`
        );

        // For molprobability, if not found in occupancy, it might be in a separate field
        // or not available at all (Boltz may not output this)
      } catch (err) {
        console.error("[Quality Metrics] CIF parsing error:", err);
      }

      return { totalPLDDT, totalMolProb, pLDDTCount, molProbCount };
    },
    []
  );

  // Calculate quality metrics from metadata JSON files
  const calculateQualityMetrics = React.useCallback(
    async (cifFiles: string[], runPath?: string) => {
      try {
        console.log(
          `[Quality Metrics] Calculating for ${cifFiles.length} CIF file(s)`
        );

        // First, try to find metadata files by searching directories
        const metadataFiles: string[] = [];

        // Strategy 1: Search in runPath/predictions directory recursively for all JSON files
        if (runPath) {
          try {
            const predictionsPath = `${runPath}/predictions`;
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
                    const filePath = `${dirPath}/${file}`;

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
                              console.log(
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
            console.log(
              `[Quality Metrics] Could not search predictions directory:`,
              err instanceof Error ? err.message : String(err)
            );
          }
        }

        // Strategy 2: Try to find metadata files by path matching (original method)
        for (const cifFile of cifFiles) {
          const pathParts = cifFile.split("/");
          const cifFileName = pathParts[pathParts.length - 1];
          const cifDir = pathParts.slice(0, -1).join("/");

          console.log(
            `[Quality Metrics] Searching metadata for: ${cifFileName} in ${cifDir}`
          );

          // Extract chain prefix from filename or path
          // Examples:
          // - "1kx3_CDEFGHIJAB_model_0.cif" -> "1kx3_CDEFGHIJAB"
          // - "1KX3_chainCDEFGHIJAB.cif" -> "1KX3_chainCDEFGHIJAB"
          // - "1ton_A_model_0.cif" -> "1ton_A"
          const chainPrefixMatch = pathParts.find(
            part =>
              part.includes("_") &&
              /[A-Z]/.test(part) &&
              !part.includes("run_") &&
              !part.includes("predictions") &&
              !part.endsWith(".cif")
          );

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
              `${cifDir}/inpainting_metadata_${chainPrefixMatch}.json`
            );
          }

          // 2. Try with chain prefix from filename (e.g., "1kx3_CDEFGHIJAB")
          if (chainPrefix) {
            possibleMetadataPaths.push(
              `${cifDir}/inpainting_metadata_${chainPrefix}.json`
            );
          }

          // 3. Try with single chain ID (e.g., "A")
          if (singleChainId) {
            possibleMetadataPaths.push(
              `${cifDir}/inpainting_metadata_${singleChainId.toLowerCase()}.json`
            );
          }

          // 4. Try parent directory (for multi-chain files, metadata might be one level up)
          const parentDir = pathParts.slice(0, -1).join("/");
          if (chainPrefixMatch) {
            possibleMetadataPaths.push(
              `${parentDir}/inpainting_metadata_${chainPrefixMatch}.json`
            );
          }
          if (chainPrefix) {
            possibleMetadataPaths.push(
              `${parentDir}/inpainting_metadata_${chainPrefix}.json`
            );
          }

          // 5. Try searching in parent directories (up to 3 levels up)
          for (let i = 1; i <= 3; i++) {
            const upDir = pathParts.slice(0, -i - 1).join("/");
            if (upDir && chainPrefixMatch) {
              possibleMetadataPaths.push(
                `${upDir}/inpainting_metadata_${chainPrefixMatch}.json`
              );
            }
            if (upDir && chainPrefix) {
              possibleMetadataPaths.push(
                `${upDir}/inpainting_metadata_${chainPrefix}.json`
              );
            }
          }

          // 6. Try generic names (for multi-chain files)
          possibleMetadataPaths.push(`${cifDir}/inpainting_metadata.json`);
          possibleMetadataPaths.push(`${parentDir}/inpainting_metadata.json`);

          // Remove duplicates
          const uniquePaths = Array.from(new Set(possibleMetadataPaths));

          console.log(
            `[Quality Metrics] Trying ${uniquePaths.length} possible paths:`,
            uniquePaths
          );

          for (const metadataPath of uniquePaths) {
            const result =
              await window.api.project.readFileByPath(metadataPath);
            if (result.success && result.content) {
              console.log(
                `[Quality Metrics] ✓ Found metadata: ${metadataPath}`
              );
              metadataFiles.push(result.content);
              break; // Found one, no need to try others for this CIF file
            } else {
              console.log(`[Quality Metrics] ✗ Not found: ${metadataPath}`);
            }
          }
        }

        if (metadataFiles.length === 0) {
          console.warn(
            `[Quality Metrics] No metadata files found for ${cifFiles.length} CIF file(s)`
          );
          return null;
        }

        console.log(
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

            console.log(
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

                // Add all types of inpainted residues
                if (chainInfo.fully_fixed_residues) {
                  chainInfo.fully_fixed_residues.forEach(r =>
                    inpaintedResidues.add(r)
                  );
                }
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
                  console.log(
                    `[Quality Metrics] Chain ${chainId}: ${inpaintedResidues.size} inpainted residues`
                  );
                }
              }
            }
          } catch (err) {
            console.error(
              "[Quality Metrics] Failed to parse metadata JSON:",
              err
            );
          }
        }

        if (inpaintingRegionsByChain.size === 0) {
          console.warn(
            `[Quality Metrics] No inpainting regions found in metadata`
          );
          return null;
        }

        console.log(
          `[Quality Metrics] Found inpainting regions for ${inpaintingRegionsByChain.size} chain(s), reading CIF files...`
        );

        // Read CIF files and extract quality metrics for inpainted residues
        let totalPLDDT = 0;
        let totalMolProb = 0;
        let pLDDTCount = 0;
        let molProbCount = 0;

        for (const cifFile of cifFiles) {
          try {
            console.log(`[Quality Metrics] Reading CIF file: ${cifFile}`);
            const cifResult = await window.api.project.readFileByPath(cifFile);
            if (!cifResult.success || !cifResult.content) {
              console.warn(`[Quality Metrics] Failed to read CIF: ${cifFile}`);
              continue;
            }

            const cifContent = cifResult.content;

            // Extract quality metrics from CIF file
            const metrics = extractQualityMetricsFromCIF(
              cifContent,
              inpaintingRegionsByChain
            );

            console.log(
              `[Quality Metrics] Extracted from ${cifFile.split("/").pop()}: ${metrics.pLDDTCount} pLDDT values, ${metrics.molProbCount} molprob values`
            );

            totalPLDDT += metrics.totalPLDDT;
            totalMolProb += metrics.totalMolProb;
            pLDDTCount += metrics.pLDDTCount;
            molProbCount += metrics.molProbCount;
          } catch (err) {
            console.error(
              `[Quality Metrics] Failed to process CIF file ${cifFile}:`,
              err instanceof Error ? err.message : String(err)
            );
          }
        }

        if (pLDDTCount === 0 && molProbCount === 0) {
          console.warn(
            `[Quality Metrics] No quality metrics found in metadata files`
          );
          return null;
        }

        const avgPLDDT = pLDDTCount > 0 ? totalPLDDT / pLDDTCount : 0;
        const avgMolProbability =
          molProbCount > 0 ? totalMolProb / molProbCount : 0;

        // Combined score: use only pLDDT since molprobability is not available
        const combinedScore = avgPLDDT;

        console.log(
          `[Quality Metrics] ✓ Calculated: pLDDT=${avgPLDDT.toFixed(1)}, MP=${avgMolProbability.toFixed(3)}, Score=${combinedScore.toFixed(1)}`
        );

        return {
          avgPLDDT,
          avgMolProbability,
          combinedScore
        };
      } catch (err) {
        console.error(
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

              console.log(
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
        console.error("Failed to load results:", err);
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
        const isBaseStructure = filePath.includes("/structures/original/");
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

    console.log(`[Hide All] Hidden ${allVisibleFiles.length} structure(s)`);
  }, [visibleFiles]);

  // Load YAML file for a run
  const loadDetail = React.useCallback(
    async (runId: string, runPath: string) => {
      try {
        // YAML file is in predictions folder: runPath/predictions/*.yaml
        const predictionsPath = `${runPath}/predictions`;
        let yamlContent: string | null = null;

        // First, list all files in predictions folder and find .yaml files
        const listResult =
          await window.api.project.listDirectory(predictionsPath);
        if (listResult.success && listResult.files) {
          // Find .yaml files (e.g., 4j76_AB.yaml, 1ton_A.yaml, project.yaml)
          const yamlFiles = listResult.files.filter(
            (f: string) => f.endsWith(".yaml") || f.endsWith(".yml")
          );

          console.log(
            `[YAML Load] Found ${yamlFiles.length} YAML files in ${predictionsPath}:`,
            yamlFiles
          );

          // Try to load the first yaml file found
          for (const yamlFile of yamlFiles) {
            const yamlPath = `${predictionsPath}/${yamlFile}`;
            const yamlResult =
              await window.api.project.readFileByPath(yamlPath);
            if (yamlResult.success && yamlResult.content) {
              yamlContent = yamlResult.content;
              console.log(`[YAML Load] Loaded: ${yamlPath}`);
              break;
            }
          }
        }

        // Fallback: try project.yaml in run directory
        if (!yamlContent) {
          const yamlPath = `${runPath}/project.yaml`;
          const yamlResult = await window.api.project.readFileByPath(yamlPath);
          if (yamlResult.success && yamlResult.content) {
            yamlContent = yamlResult.content;
            console.log(`[YAML Load] Loaded from run dir: ${yamlPath}`);
          }
        }

        // Fallback: try project root's project.yaml
        if (!yamlContent) {
          const yamlResult = await window.api.project.loadYAML();
          if (yamlResult.success && yamlResult.yaml) {
            // Convert YAML object back to string for display
            yamlContent = JSON.stringify(yamlResult.yaml, null, 2);
            console.log(`[YAML Load] Loaded from project root`);
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
        console.error("Failed to load detail:", err);
        setDetailYaml("Failed to load YAML file");
        setDetailRunId(runId);
      }
    },
    []
  );

  return (
    <div className="flex-1 overflow-auto">
      {/* Missing Region Review 섹션 */}
      <Section
        title="Missing Region Analysis"
        expanded={expandedSections.has("missing-region-review")}
        onToggle={() => toggleSection("missing-region-review")}
      >
        <MissingRegionReviewSection />
      </Section>

      {/* Sequence Mapping 섹션 (Optional) */}
      <Section
        title="Sequence Mapping / Uniprot Search (Optional)"
        expanded={expandedSections.has("sequence")}
        onToggle={() => toggleSection("sequence")}
      >
        <SequenceMappingSection />
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
            {/* Legend */}
            <div className="flex items-center gap-4 text-xs border-b border-border pb-2">
              <div className="flex items-center gap-1.5">
                <div
                  className="w-3 h-3 rounded"
                  style={{ backgroundColor: "#eab308" }}
                />
                <span className="text-muted-foreground">
                  Boundary Exclusion (Flexible Region)
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <div
                  className="w-3 h-3 rounded"
                  style={{ backgroundColor: "#f97316" }}
                />
                <span className="text-muted-foreground">Partially Fixed</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div
                  className="w-3 h-3 rounded"
                  style={{ backgroundColor: "#ef4444" }}
                />
                <span className="text-muted-foreground">Fully Inpainted</span>
              </div>
            </div>
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
                          {file.split("/").pop()}
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
                                className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-medium"
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
                                console.error("Failed to open folder:", error);
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
                                    {file.split("/").pop()}
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
    <div className="border-b border-slate-200/50 dark:border-slate-800/50">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3.5 text-left hover:bg-slate-100/50 dark:hover:bg-slate-800/30 transition-all group"
      >
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
          {title}
        </h3>
        <span className="text-slate-500 dark:text-slate-500 group-hover:text-slate-700 dark:group-hover:text-slate-400 transition-colors">
          {expanded ? "▼" : "▶"}
        </span>
      </button>
      {expanded && (
        <div className="px-4 py-4 bg-slate-50/50 dark:bg-slate-900/20">
          {children}
        </div>
      )}
    </div>
  );
}

function SequenceMappingSection(): React.ReactElement {
  const plugin = useAtomValue(pluginAtom);
  const [selectedSegments] = useAtom(selectedRepairSegmentsAtom);
  const [fastaInput, setFastaInput] = useAtom(fastaInputAtom);
  const [enableSequenceMapping, setEnableSequenceMapping] = useAtom(
    enableSequenceMappingAtom
  );
  const [pdbId, setPdbId] = React.useState("");
  const [searchStatus, setSearchStatus] = React.useState<
    "idle" | "searching" | "success" | "error"
  >("idle");
  const [selectedChainsForSearch, setSelectedChainsForSearch] = React.useState<
    Set<string>
  >(new Set());

  // Get chains from selected repair segments (automatically)
  const availableChains = React.useMemo(() => {
    const chainSet = new Set<string>();
    for (const segment of selectedSegments) {
      for (const chainId of segment.chainIds) {
        chainSet.add(chainId);
      }
    }
    return Array.from(chainSet).sort();
  }, [selectedSegments]);

  // Update selected chains when available chains change
  React.useEffect(() => {
    setSelectedChainsForSearch(new Set(availableChains));
  }, [availableChains]);

  // Get sequence data from structure using getSequencePanelData (includes polymerType)
  const chainSequenceData = React.useMemo(() => {
    if (!plugin)
      return new Map<
        string,
        { sequence: string; polymerType: "protein" | "dna" | "rna" | "unknown" }
      >();

    try {
      const sequenceData = getSequencePanelData(plugin);
      const result = new Map<
        string,
        { sequence: string; polymerType: "protein" | "dna" | "rna" | "unknown" }
      >();

      for (const [chainId, data] of sequenceData.entries()) {
        result.set(chainId, {
          sequence: data.sequence,
          polymerType: data.polymerType
        });
      }

      return result;
    } catch (error) {
      console.error("Failed to extract sequences:", error);
      return new Map<
        string,
        { sequence: string; polymerType: "protein" | "dna" | "rna" | "unknown" }
      >();
    }
  }, [plugin]);

  // Simple chainId -> sequence map for backward compatibility
  const chainSequences = React.useMemo(() => {
    const sequences = new Map<string, string>();
    for (const [chainId, data] of chainSequenceData.entries()) {
      sequences.set(chainId, data.sequence);
    }
    return sequences;
  }, [chainSequenceData]);

  // Auto-populate FASTA from selected repair segments' chains
  React.useEffect(() => {
    if (availableChains.length === 0) {
      setFastaInput("");
      return;
    }

    // Build FASTA from available chains
    const fastaLines: string[] = [];
    for (const chainId of availableChains) {
      const sequence = chainSequences.get(chainId) || "";
      if (sequence) {
        fastaLines.push(`>Chain ${chainId}`);
        // Wrap sequence at 60 chars per line
        for (let i = 0; i < sequence.length; i += 60) {
          fastaLines.push(sequence.substring(i, i + 60));
        }
      } else {
        fastaLines.push(`>Chain ${chainId}`);
        fastaLines.push(""); // Empty sequence - user needs to fill
      }
    }
    setFastaInput(fastaLines.join("\n"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableChains, chainSequences]);

  const handleUniprotSearch = async (): Promise<void> => {
    if (!pdbId.trim() || selectedChainsForSearch.size === 0) return;

    setSearchStatus("searching");
    try {
      // Get fresh sequence data directly from plugin (useMemo might be stale)
      const freshSequenceData = new Map<
        string,
        { sequence: string; polymerType: "protein" | "dna" | "rna" | "unknown" }
      >();

      console.log("[UniProt Search] plugin available:", !!plugin);

      if (plugin) {
        try {
          console.log("[UniProt Search] Calling getSequencePanelData...");
          const data = getSequencePanelData(plugin);
          console.log(
            "[UniProt Search] getSequencePanelData returned:",
            data.size,
            "entries"
          );
          for (const [chainId, chainData] of data.entries()) {
            freshSequenceData.set(chainId, {
              sequence: chainData.sequence,
              polymerType: chainData.polymerType
            });
          }
        } catch (e) {
          console.error(
            "[UniProt Search] Failed to get fresh sequence data:",
            e
          );
        }
      } else {
        console.warn("[UniProt Search] Plugin not available!");
      }

      // Separate protein chains from DNA/RNA chains (only for selected chains)
      const proteinChains: string[] = [];
      const nucleotideChains: string[] = [];
      const chainsToSearch = Array.from(selectedChainsForSearch);

      // Debug: Log all chain data
      console.log(
        "[UniProt Search] freshSequenceData entries:",
        Array.from(freshSequenceData.entries()).map(([id, data]) => ({
          chainId: id,
          polymerType: data.polymerType,
          sequenceLength: data.sequence.length
        }))
      );

      for (const chainId of chainsToSearch) {
        const data = freshSequenceData.get(chainId);
        console.log(
          `[UniProt Search] Chain "${chainId}": polymerType="${data?.polymerType || "not found"}", sequence="${data?.sequence?.substring(0, 20) || "none"}..."`
        );
        if (data?.polymerType === "dna" || data?.polymerType === "rna") {
          nucleotideChains.push(chainId);
        } else {
          proteinChains.push(chainId);
        }
      }

      console.log(
        "Searching UniProt for PDB ID:",
        pdbId,
        "protein chains:",
        proteinChains,
        "DNA/RNA chains (will use sequence panel):",
        nucleotideChains
      );

      const fastaLines: string[] = [];

      // For protein chains, search UniProt
      if (proteinChains.length > 0) {
        // Check if API is available
        if (
          !window.api ||
          !window.api.uniprot ||
          !window.api.uniprot.searchByPdb
        ) {
          throw new Error(
            "UniProt API not available. Please restart the application."
          );
        }

        // Call main process to handle API requests (avoids CORS issues)
        const result = await window.api.uniprot.searchByPdb(
          pdbId.toUpperCase(),
          proteinChains
        );

        if (!result.success) {
          throw new Error(result.error || "UniProt search failed");
        }

        if (result.results && result.results.length > 0) {
          for (const chainResult of result.results) {
            if (chainResult.fasta) {
              fastaLines.push(chainResult.fasta);
            } else if (chainResult.error) {
              fastaLines.push(
                `>Chain_${chainResult.chainId} [Error: ${chainResult.error}]`
              );
              fastaLines.push("");
            } else {
              fastaLines.push(
                `>Chain_${chainResult.chainId} [No UniProt mapping found]`
              );
              fastaLines.push("");
            }
          }
        }
      }

      // For DNA/RNA chains, get sequence directly from sequence panel
      for (const chainId of nucleotideChains) {
        const data = freshSequenceData.get(chainId);
        const polymerLabel =
          data?.polymerType === "dna"
            ? "DNA"
            : data?.polymerType === "rna"
              ? "RNA"
              : "nucleotide";

        if (data?.sequence) {
          fastaLines.push(`>Chain ${chainId} [${polymerLabel}]`);
          // Wrap sequence at 60 chars per line
          for (let i = 0; i < data.sequence.length; i += 60) {
            fastaLines.push(data.sequence.substring(i, i + 60));
          }
        } else {
          fastaLines.push(
            `>Chain_${chainId} [${polymerLabel} - sequence not available]`
          );
          fastaLines.push("");
        }
      }

      setFastaInput(fastaLines.join("\n"));
      setSearchStatus("success");
    } catch (error) {
      console.error("UniProt search failed:", error);
      setSearchStatus("error");
    }
  };

  return (
    <div className="space-y-4">
      {/* Enable Sequence Mapping Checkbox */}
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="enable-sequence-mapping"
          checked={enableSequenceMapping}
          onChange={e => setEnableSequenceMapping(e.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
        />
        <label
          htmlFor="enable-sequence-mapping"
          className="text-xs font-medium cursor-pointer"
        >
          Enable Sequence Mapping
        </label>
      </div>

      {enableSequenceMapping && (
        <>
          <p className="text-xs text-muted-foreground">
            Provide sequence information for chains with missing regions.
            Sequences are automatically loaded from selected repair groups.
          </p>

          {/* Show chains with selection checkboxes */}
          {availableChains.length > 0 ? (
            <div className="rounded-md border border-border bg-muted/20 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  Select chains for UniProt search:
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setSelectedChainsForSearch(new Set(availableChains))
                    }
                    className="text-xs text-primary hover:underline"
                  >
                    Select All
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedChainsForSearch(new Set())}
                    className="text-xs text-primary hover:underline"
                  >
                    Deselect All
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {availableChains.map(chainId => {
                  const data = chainSequenceData.get(chainId);
                  const typeLabel =
                    data?.polymerType === "dna"
                      ? "DNA"
                      : data?.polymerType === "rna"
                        ? "RNA"
                        : data?.polymerType === "protein"
                          ? "Protein"
                          : "";
                  return (
                    <label
                      key={chainId}
                      className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs cursor-pointer transition-colors ${
                        selectedChainsForSearch.has(chainId)
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-background text-muted-foreground hover:border-primary/50"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedChainsForSearch.has(chainId)}
                        onChange={e => {
                          const newSet = new Set(selectedChainsForSearch);
                          if (e.target.checked) {
                            newSet.add(chainId);
                          } else {
                            newSet.delete(chainId);
                          }
                          setSelectedChainsForSearch(newSet);
                        }}
                        className="h-3 w-3"
                      />
                      <span className="font-mono font-medium">
                        Chain {chainId}
                      </span>
                      {typeLabel && (
                        <span className="text-[10px] opacity-70">
                          ({typeLabel})
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="rounded-md border border-border bg-muted/20 p-3">
              <p className="text-xs text-muted-foreground">
                No chains available. Select repair groups in Missing Region
                Analysis first.
              </p>
            </div>
          )}

          {/* FASTA Input */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium">FASTA Sequence</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={pdbId}
                  onChange={e => setPdbId(e.target.value.toUpperCase())}
                  placeholder="PDB ID (e.g., 4J76)"
                  maxLength={4}
                  className="w-36 rounded-md border border-input bg-background px-2 py-1 text-xs uppercase"
                />
                <button
                  onClick={handleUniprotSearch}
                  disabled={
                    selectedChainsForSearch.size === 0 ||
                    !pdbId.trim() ||
                    searchStatus === "searching"
                  }
                  className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {searchStatus === "searching"
                    ? "..."
                    : `Search UniProt (${selectedChainsForSearch.size})`}
                </button>
              </div>
            </div>
            <textarea
              value={fastaInput}
              onChange={e => setFastaInput(e.target.value)}
              placeholder="Select chains to auto-load sequences..."
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono"
              rows={10}
            />
            <p className="text-xs text-muted-foreground">
              Sequences are automatically loaded from structure. You can edit
              manually or search UniProt by PDB ID.
            </p>
          </div>

          {/* Search Status */}
          {searchStatus === "success" && (
            <div className="rounded-md border border-green-500/50 bg-green-500/10 p-3">
              <p className="text-xs text-green-400">
                ✓ Found UniProt entries for {pdbId}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Sequences updated in FASTA field above
              </p>
            </div>
          )}
          {searchStatus === "error" && (
            <div className="rounded-md border border-red-500/50 bg-red-500/10 p-3">
              <p className="text-xs text-red-400">
                ✗ Failed to find UniProt entries for {pdbId}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                You can manually edit the FASTA sequence above
              </p>
            </div>
          )}
        </>
      )}

      {!enableSequenceMapping && (
        <p className="text-xs text-muted-foreground">
          Sequence mapping is disabled. The server will use sequences from the
          structure file.
        </p>
      )}
    </div>
  );
}

const COLAB_NOTEBOOK_URL =
  "https://colab.research.google.com/github/DeepFoldProtein/patchr/blob/main/colab_server.ipynb";

function ServerSetupGuide({
  onUrlChange,
  onDismiss
}: {
  onUrlChange: (url: string) => void;
  onDismiss: () => void;
}): React.ReactElement {
  const [activeTab, setActiveTab] = React.useState<"local" | "colab">("colab");
  const [colabUrl, setColabUrl] = React.useState("");

  const handleColabUrlApply = (): void => {
    const trimmed = colabUrl.trim().replace(/\/+$/, "");
    if (trimmed) {
      onUrlChange(trimmed);
    }
  };

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-amber-500/10 border-b border-amber-500/20">
        <div className="flex items-center gap-1.5">
          <ServerOff className="h-3.5 w-3.5 text-amber-500" />
          <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
            Server not detected
          </span>
        </div>
        <button
          onClick={onDismiss}
          className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
        >
          Dismiss
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200/50 dark:border-slate-800/50">
        <button
          onClick={() => setActiveTab("colab")}
          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors ${
            activeTab === "colab"
              ? "text-blue-600 dark:text-blue-400 border-b-2 border-blue-500"
              : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          }`}
        >
          <Cloud className="h-3 w-3" />
          Google Colab
        </button>
        <button
          onClick={() => setActiveTab("local")}
          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors ${
            activeTab === "local"
              ? "text-blue-600 dark:text-blue-400 border-b-2 border-blue-500"
              : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          }`}
        >
          <Monitor className="h-3 w-3" />
          Local Setup
        </button>
      </div>

      {/* Content */}
      <div className="p-3">
        {activeTab === "colab" ? (
          <div className="space-y-2.5">
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Use a free GPU on Google Colab:
            </p>
            <div className="rounded px-2 py-1.5 bg-orange-500/10 border border-orange-500/20">
              <p className="text-[10px] text-orange-600 dark:text-orange-400">
                Large targets may fail on Colab free tier due to limited GPU
                memory (T4 15GB). For large complexes, use Local Setup or Colab
                Pro.
              </p>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-blue-500/20 text-[10px] font-bold text-blue-500">
                  1
                </span>
                <div className="text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    Open the Colab notebook
                  </span>
                  <button
                    onClick={() =>
                      window.open(COLAB_NOTEBOOK_URL, "_blank")
                    }
                    className="flex items-center gap-1 mt-1 px-2 py-1 rounded bg-amber-500/10 border border-amber-500/20 text-[10px] font-medium text-amber-600 dark:text-amber-400 hover:bg-amber-500/20 transition-colors"
                  >
                    Open in Colab
                    <ExternalLink className="h-2.5 w-2.5" />
                  </button>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-blue-500/20 text-[10px] font-bold text-blue-500">
                  2
                </span>
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    Run all cells
                  </span>{" "}
                  and copy the public URL
                </p>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-blue-500/20 text-[10px] font-bold text-blue-500">
                  3
                </span>
                <div className="flex-1 text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    Paste the URL here
                  </span>
                  <div className="flex gap-1.5 mt-1">
                    <input
                      type="text"
                      value={colabUrl}
                      onChange={e => setColabUrl(e.target.value)}
                      placeholder="https://xxx.trycloudflare.com"
                      className="flex-1 rounded border border-input bg-background px-2 py-1 text-[10px] font-mono"
                      onKeyDown={e => {
                        if (e.key === "Enter") handleColabUrlApply();
                      }}
                    />
                    <button
                      onClick={handleColabUrlApply}
                      disabled={!colabUrl.trim()}
                      className="rounded bg-blue-600 px-2 py-1 text-[10px] font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition-colors flex items-center gap-0.5"
                    >
                      Apply
                      <ChevronRight className="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-2.5">
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Run the PATCHR server locally with a GPU:
            </p>
            <div className="space-y-1.5">
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-blue-500/20 text-[10px] font-bold text-blue-500">
                  1
                </span>
                <div className="text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    Clone & install
                  </span>
                  <code className="block mt-1 px-2 py-1 rounded bg-slate-100 dark:bg-slate-800/80 text-[10px] font-mono text-slate-700 dark:text-slate-300 select-all whitespace-pre-wrap">
                    {`git clone https://github.com/DeepFoldProtein/patchr.git && cd patchr && pip install -e .[cuda]`}
                  </code>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-blue-500/20 text-[10px] font-bold text-blue-500">
                  2
                </span>
                <div className="text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    Start the server
                  </span>
                  <code className="block mt-1 px-2 py-1 rounded bg-slate-100 dark:bg-slate-800/80 text-[10px] font-mono text-slate-700 dark:text-slate-300 select-all">
                    python -m boltz.server --port 31212
                  </code>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-blue-500/20 text-[10px] font-bold text-blue-500">
                  3
                </span>
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    Click "Test Connection"
                  </span>{" "}
                  above with the default URL
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ContextInpaintSection({
  onJobCompleted
}: {
  onJobCompleted?: () => void;
}): React.ReactElement {
  const currentProject = useCurrentProject();
  const [selectedSegments] = useAtom(selectedRepairSegmentsAtom);
  const [fastaInput] = useAtom(fastaInputAtom);
  const [enableSequenceMapping] = useAtom(enableSequenceMappingAtom);

  const [apiUrl, setApiUrl] = React.useState("http://localhost:31212");
  const [connectionStatus, setConnectionStatus] = useAtom(
    apiConnectionStatusAtom
  );
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [jobStatus, setJobStatus] = React.useState<string>("idle");
  const [progress, setProgress] = React.useState(0);
  const [progressMessage, setProgressMessage] = React.useState<string | null>(
    null
  );
  const [error, setError] = React.useState<string | null>(null);
  const [showSetupGuide, setShowSetupGuide] = React.useState(false);

  // Auto-detect server on mount
  React.useEffect(() => {
    if (connectionStatus !== "idle") return;

    let cancelled = false;
    const autoDetect = async (): Promise<void> => {
      try {
        if (!window.api?.boltz?.healthCheck) return;
        const result = await window.api.boltz.healthCheck(
          "http://localhost:31212"
        );
        if (cancelled) return;
        if (result.success) {
          setConnectionStatus("connected");
          console.log("[Auto-detect] Server found at localhost:31212");
        } else {
          setShowSetupGuide(true);
          console.log("[Auto-detect] Server not responding");
        }
      } catch {
        if (cancelled) return;
        setShowSetupGuide(true);
        console.log("[Auto-detect] Server not found at localhost:31212");
      }
    };

    void autoDetect();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Get chains from selected repair segments
  const availableChains = React.useMemo(() => {
    const chainSet = new Set<string>();
    for (const segment of selectedSegments) {
      for (const chainId of segment.chainIds) {
        chainSet.add(chainId);
      }
    }
    return Array.from(chainSet).sort();
  }, [selectedSegments]);

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

  // Test connection
  const handleTestConnection = async (): Promise<void> => {
    const startTime = Date.now();
    console.log(
      `[Test Connection] Starting health check to ${apiUrl} at ${new Date().toISOString()}`
    );

    setConnectionStatus("testing");
    setError(null);

    try {
      if (!window.api?.boltz?.healthCheck) {
        throw new Error("Boltz API not available");
      }

      // Use AbortController for timeout instead of setTimeout
      const abortController = new AbortController();
      const timeoutSignal = abortController.signal;
      let healthCheckCompleted = false;
      const startTime = Date.now();

      // Set timeout using AbortController
      const timeoutPromise = new Promise<never>((_, reject) => {
        // Use requestAnimationFrame to check timeout without blocking
        const checkTimeout = (): void => {
          if (timeoutSignal.aborted) {
            return;
          }
          const elapsed = Date.now() - startTime;
          if (elapsed >= 5000) {
            if (!healthCheckCompleted) {
              console.log(
                `[Test Connection] ⏱️ Timeout fired after ${elapsed}ms`
              );
              abortController.abort();
              reject(new Error("Connection timeout (5s)"));
            }
          } else {
            requestAnimationFrame(checkTimeout);
          }
        };
        requestAnimationFrame(checkTimeout);
        console.log(`[Test Connection] ⏱️ Timeout check started (5s limit)`);
      });

      console.log(`[Test Connection] 📡 Calling healthCheck API...`);
      const healthCheckStartTime = Date.now();

      const healthCheckPromise = window.api.boltz.healthCheck(apiUrl).then(
        result => {
          const elapsed = Date.now() - healthCheckStartTime;
          const totalElapsed = Date.now() - startTime;
          healthCheckCompleted = true;
          console.log(
            `[Test Connection] ✅ HealthCheck completed in ${elapsed}ms (total: ${totalElapsed}ms), success: ${result.success}`
          );

          // Abort timeout if still running
          if (!timeoutSignal.aborted) {
            abortController.abort();
            console.log(`[Test Connection] 🧹 Timeout aborted`);
          }

          return result;
        },
        error => {
          const elapsed = Date.now() - healthCheckStartTime;
          const totalElapsed = Date.now() - startTime;
          healthCheckCompleted = true;
          console.log(
            `[Test Connection] ❌ HealthCheck failed after ${elapsed}ms (total: ${totalElapsed}ms):`,
            error
          );

          // Abort timeout if still running
          if (!timeoutSignal.aborted) {
            abortController.abort();
            console.log(`[Test Connection] 🧹 Timeout aborted after error`);
          }

          throw error;
        }
      );

      console.log(`[Test Connection] 🏁 Starting Promise.race...`);
      const result = await Promise.race([healthCheckPromise, timeoutPromise]);
      const totalElapsed = Date.now() - startTime;
      console.log(
        `[Test Connection] 🎯 Promise.race resolved after ${totalElapsed}ms`
      );

      if (result.success) {
        console.log(`[Test Connection] ✅ Connection successful!`);
        setConnectionStatus("connected");
      } else {
        console.log(`[Test Connection] ❌ Connection failed: ${result.error}`);
        setConnectionStatus("error");
        setError(result.error || "Connection failed");
      }
    } catch (err) {
      const totalElapsed = Date.now() - startTime;
      console.log(
        `[Test Connection] 💥 Exception caught after ${totalElapsed}ms:`,
        err
      );
      setConnectionStatus("error");
      setError(
        err instanceof Error ? err.message : "Failed to connect to server"
      );
    }
  };

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

    if (availableChains.length === 0) {
      setError("No chains selected. Please select repair groups first.");
      return;
    }

    // Reset state if starting a new job after completion
    if (jobStatus === "completed") {
      setJobId(null);
      // setResultFiles([]); // Result files are managed in Results section
      setProgress(0);
      setProgressMessage(null);
    }

    setError(null);
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

      // 3. Upload template
      if (!window.api?.boltz?.uploadTemplate) {
        throw new Error("Boltz API not available");
      }

      const uploadResult = await window.api.boltz.uploadTemplate(
        apiUrl,
        cifContentResult.content,
        cifFile,
        availableChains,
        customSequencesStr
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

        console.error("[Template Upload Failed]", {
          error: errorMsg,
          request: requestInfo
        });

        throw new Error(fullErrorMsg);
      }

      const newJobId = uploadResult.data.job_id;
      setJobId(newJobId);
      setJobStatus("template_generating");

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

          console.error("[Template Status Check Failed]", {
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

          console.error("[Template Generation Failed]", {
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
            console.error("Boltz API not available");
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
            console.error("Status check failed:", statusResult.error);
            if (monitorInterval) clearInterval(monitorInterval);
            setJobStatus("failed");
            setError(statusResult.error || "Status check failed");
            return;
          }

          const status = statusResult.data;

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

              // Results are automatically available in Results section
              // No need to store resultFiles here anymore
              if (
                downloadResult.cifFiles &&
                downloadResult.cifFiles.length > 0
              ) {
                console.log(
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
          console.error("Failed to check status:", err);
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
      {/* API Configuration */}
      <div className="space-y-2">
        <label className="text-xs font-medium">API Server URL</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={apiUrl}
            onChange={e => setApiUrl(e.target.value)}
            placeholder="http://localhost:31212"
            className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-xs"
          />
          <button
            onClick={handleTestConnection}
            disabled={connectionStatus === "testing"}
            className={`rounded-md px-3 py-2 text-xs font-medium ${
              connectionStatus === "connected"
                ? "bg-green-600 text-white"
                : connectionStatus === "error"
                  ? "bg-red-600 text-white hover:bg-red-700"
                  : "bg-primary text-primary-foreground hover:bg-primary/90"
            } disabled:opacity-50`}
          >
            {connectionStatus === "testing"
              ? "Testing..."
              : connectionStatus === "connected"
                ? "Connected"
                : connectionStatus === "error"
                  ? "Try Again"
                  : "Test Connection"}
          </button>
        </div>
      </div>

      {/* Server Setup Guide - shown when server not detected */}
      {showSetupGuide && connectionStatus !== "connected" && (
        <ServerSetupGuide
          onUrlChange={url => {
            setApiUrl(url);
          }}
          onDismiss={() => setShowSetupGuide(false)}
        />
      )}

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
                  : jobStatus === "running_prediction"
                    ? "Starting prediction..."
                    : jobStatus === "running"
                      ? "Running prediction..."
                      : jobStatus === "downloading"
                        ? "Downloading results..."
                        : jobStatus === "completed"
                          ? "✓ Completed"
                          : jobStatus === "failed"
                            ? "✗ Failed"
                            : jobStatus.replace("_", " ")}
            </span>
          </div>
          {jobId && (
            <div className="text-xs text-muted-foreground">Job ID: {jobId}</div>
          )}
          {(progress > 0 || jobStatus === "running") && (
            <div className="mt-2">
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-700">
                <div
                  className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
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
        <div className="rounded-md border border-red-500/50 bg-red-500/10 p-3">
          <p className="text-xs text-red-400">✗ {error}</p>
        </div>
      )}

      {/* Action Buttons */}
      <div className="space-y-2">
        <button
          onClick={handleStartInpainting}
          disabled={
            connectionStatus !== "connected" ||
            (jobStatus !== "idle" &&
              jobStatus !== "failed" &&
              jobStatus !== "completed") ||
            availableChains.length === 0 ||
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
      </div>

      {/* Info */}
      <div className="rounded-md border border-border bg-muted/20 p-3">
        <p className="text-xs text-muted-foreground">
          Chains:{" "}
          {availableChains.length > 0
            ? availableChains.join(", ")
            : "None selected"}
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
