import React, { useState, useCallback } from "react";
import {
  Upload,
  File,
  X,
  Download,
  Check,
  Square,
  CheckSquare
} from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription
} from "./ui/dialog";

interface ChainInfo {
  id: string;
  entityId: string;
  type: string;
  description: string;
  residueCount: number;
}

interface StructureUploadModalProps {
  open: boolean;
  onStructureLoaded: (content: string, filename: string) => void;
  onClose?: () => void;
}

/**
 * Parse mmCIF content to extract chain information
 */
function parseCifChains(content: string): ChainInfo[] {
  const chainMap = new Map<string, ChainInfo>();

  // Parse _entity category for descriptions and types
  const entityDescriptions = new Map<string, string>();
  const entityTypes = new Map<string, string>();

  // Parse _entity_poly for polymer type
  const entityPolyTypes = new Map<string, string>();
  const entityPolyMatch = content.match(
    /loop_\s*\n_entity_poly\.[\s\S]*?(?=loop_|data_|#\s*\n|$)/
  );
  if (entityPolyMatch) {
    const lines = entityPolyMatch[0].split("\n");
    const headers: string[] = [];
    let inData = false;

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("_entity_poly.")) {
        headers.push(trimmed.replace("_entity_poly.", ""));
      } else if (
        trimmed &&
        !trimmed.startsWith("loop_") &&
        !trimmed.startsWith("#") &&
        headers.length > 0
      ) {
        inData = true;
        const parts = trimmed.split(/\s+/);
        const entityIdIdx = headers.indexOf("entity_id");
        const typeIdx = headers.indexOf("type");

        if (entityIdIdx >= 0 && parts[entityIdIdx]) {
          const entityId = parts[entityIdIdx];
          if (typeIdx >= 0 && parts[typeIdx]) {
            entityPolyTypes.set(entityId, parts[typeIdx]);
          }
        }
      } else if (inData && (!trimmed || trimmed.startsWith("#"))) {
        break;
      }
    }
  }

  // Parse _entity for descriptions
  const entityMatch = content.match(
    /loop_\s*\n_entity\.[\s\S]*?(?=loop_|data_|#\s*\n|$)/
  );
  if (entityMatch) {
    const lines = entityMatch[0].split("\n");
    const headers: string[] = [];
    let inData = false;

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("_entity.")) {
        headers.push(trimmed.replace("_entity.", ""));
      } else if (
        trimmed &&
        !trimmed.startsWith("loop_") &&
        !trimmed.startsWith("#") &&
        headers.length > 0
      ) {
        inData = true;
        const idIdx = headers.indexOf("id");
        const descIdx = headers.indexOf("pdbx_description");
        const typeIdx = headers.indexOf("type");

        if (idIdx >= 0) {
          // Handle quoted strings properly
          const parts: string[] = [];
          let current = "";
          let inQuote = false;
          let quoteChar = "";

          for (const char of trimmed) {
            if ((char === "'" || char === '"') && !inQuote) {
              inQuote = true;
              quoteChar = char;
            } else if (char === quoteChar && inQuote) {
              inQuote = false;
              quoteChar = "";
            } else if (char === " " && !inQuote) {
              if (current) {
                parts.push(current);
                current = "";
              }
            } else {
              current += char;
            }
          }
          if (current) parts.push(current);

          const entityId = parts[idIdx];
          if (entityId) {
            if (descIdx >= 0 && parts[descIdx]) {
              entityDescriptions.set(entityId, parts[descIdx]);
            }
            if (typeIdx >= 0 && parts[typeIdx]) {
              entityTypes.set(entityId, parts[typeIdx]);
            }
          }
        }
      } else if (inData && (!trimmed || trimmed.startsWith("#"))) {
        break;
      }
    }
  }

  // Parse _atom_site to get chain IDs and entity mappings
  const lines = content.split("\n");
  let inAtomSite = false;
  const atomSiteHeaders: string[] = [];
  const residueCounts = new Map<string, Set<string>>();

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("_atom_site.")) {
      inAtomSite = true;
      atomSiteHeaders.push(trimmed.replace("_atom_site.", ""));
    } else if (
      inAtomSite &&
      trimmed &&
      !trimmed.startsWith("_") &&
      !trimmed.startsWith("#") &&
      !trimmed.startsWith("loop_")
    ) {
      const parts = trimmed.split(/\s+/);
      const chainIdx = atomSiteHeaders.indexOf("auth_asym_id");
      const entityIdx = atomSiteHeaders.indexOf("label_entity_id");
      const resSeqIdx = atomSiteHeaders.indexOf("label_seq_id");

      if (chainIdx >= 0 && parts[chainIdx]) {
        const chainId = parts[chainIdx];
        const entityId = entityIdx >= 0 ? parts[entityIdx] : "?";
        const resSeq = resSeqIdx >= 0 ? parts[resSeqIdx] : "?";

        if (!chainMap.has(chainId)) {
          const entityType = entityTypes.get(entityId) || "polymer";
          const polyType = entityPolyTypes.get(entityId) || "";
          let displayType = entityType;
          if (polyType.includes("ribonucleotide")) {
            displayType = polyType.includes("deoxy") ? "DNA" : "RNA";
          } else if (polyType.includes("peptide")) {
            displayType = "protein";
          }

          const description = entityDescriptions.get(entityId) || "";

          chainMap.set(chainId, {
            id: chainId,
            entityId,
            type: displayType,
            description,
            residueCount: 0
          });
          residueCounts.set(chainId, new Set());
        }

        // Count unique residues
        if (resSeq !== "." && resSeq !== "?") {
          residueCounts.get(chainId)!.add(resSeq);
        }
      }
    } else if (
      inAtomSite &&
      (trimmed.startsWith("loop_") || trimmed.startsWith("#") || !trimmed)
    ) {
      if (atomSiteHeaders.length > 0 && chainMap.size > 0) break;
    }
  }

  // Update residue counts
  for (const [chainId, resSet] of residueCounts.entries()) {
    const chain = chainMap.get(chainId);
    if (chain) {
      chain.residueCount = resSet.size;
    }
  }

  return Array.from(chainMap.values()).sort((a, b) => a.id.localeCompare(b.id));
}

/**
 * Filter CIF content to include only selected chains
 */
function filterCifByChains(
  content: string,
  selectedChains: Set<string>
): string {
  const lines = content.split("\n");
  const filteredLines: string[] = [];
  let inAtomSite = false;
  const atomSiteHeaders: string[] = [];
  let chainIdx = -1;
  let headersDone = false;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("_atom_site.")) {
      inAtomSite = true;
      atomSiteHeaders.push(trimmed.replace("_atom_site.", ""));
      filteredLines.push(line);
    } else if (inAtomSite && !headersDone && atomSiteHeaders.length > 0) {
      if (!trimmed.startsWith("_")) {
        headersDone = true;
        chainIdx = atomSiteHeaders.indexOf("auth_asym_id");
        const parts = trimmed.split(/\s+/);
        if (
          chainIdx >= 0 &&
          parts[chainIdx] &&
          selectedChains.has(parts[chainIdx])
        ) {
          filteredLines.push(line);
        }
      } else {
        filteredLines.push(line);
      }
    } else if (
      inAtomSite &&
      headersDone &&
      chainIdx >= 0 &&
      trimmed &&
      !trimmed.startsWith("_") &&
      !trimmed.startsWith("#") &&
      !trimmed.startsWith("loop_")
    ) {
      const parts = trimmed.split(/\s+/);
      if (parts[chainIdx] && selectedChains.has(parts[chainIdx])) {
        filteredLines.push(line);
      }
    } else if (
      inAtomSite &&
      (trimmed.startsWith("loop_") || trimmed.startsWith("#") || !trimmed)
    ) {
      inAtomSite = false;
      headersDone = false;
      chainIdx = -1;
      filteredLines.push(line);
    } else {
      filteredLines.push(line);
    }
  }

  return filteredLines.join("\n");
}

export function StructureUploadModal({
  open,
  onStructureLoaded,
  onClose
}: StructureUploadModalProps): React.ReactElement {
  const [isDragging, setIsDragging] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pdbId, setPdbId] = useState("");

  // Chain selection state
  const [fetchedContent, setFetchedContent] = useState<string | null>(null);
  const [availableChains, setAvailableChains] = useState<ChainInfo[]>([]);
  const [selectedChains, setSelectedChains] = useState<Set<string>>(new Set());

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const processFile = useCallback(
    async (file: File) => {
      const filename = file.name.toLowerCase();
      if (
        !filename.endsWith(".pdb") &&
        !filename.endsWith(".cif") &&
        !filename.endsWith(".mmcif")
      ) {
        setError("Please select a PDB or mmCIF file");
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const content = await file.text();

        // Save to project's original folder
        const saveResult = await window.api.project.saveStructureContent(
          "original",
          file.name,
          content
        );

        if (!saveResult.success) {
          throw new Error(saveResult.error || "Failed to save structure file");
        }

        onStructureLoaded(content, file.name);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to load structure file";
        setError(message);
      } finally {
        setIsLoading(false);
      }
    },
    [onStructureLoaded]
  );

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      const files = e.dataTransfer.files;
      if (files.length > 0) {
        await processFile(files[0]);
      }
    },
    [processFile]
  );

  const handleFileSelect = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await window.api.project.importStructureDialog();
      if (result.success && result.content && result.filename) {
        onStructureLoaded(result.content, result.filename);
      } else if (result.error) {
        setError(result.error);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to import structure";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [onStructureLoaded]);

  const handleFetchPdb = useCallback(async () => {
    const id = pdbId.trim().toUpperCase();
    if (!id) {
      setError("Please enter a PDB ID");
      return;
    }

    if (!/^[A-Z0-9]{4}$/i.test(id)) {
      setError(
        "Invalid PDB ID format. Please enter a 4-character ID (e.g., 1TON)"
      );
      return;
    }

    setIsLoading(true);
    setError(null);
    setFetchedContent(null);
    setAvailableChains([]);
    setSelectedChains(new Set());

    try {
      const url = `https://files.rcsb.org/download/${id}.cif`;
      const response = await fetch(url);

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error(`PDB ID "${id}" not found`);
        }
        throw new Error(`Failed to fetch structure: ${response.statusText}`);
      }

      const content = await response.text();
      const chains = parseCifChains(content);

      if (chains.length === 0) {
        throw new Error("No chains found in structure");
      }

      // Store fetched content and show chain selection
      setFetchedContent(content);
      setAvailableChains(chains);
      setSelectedChains(new Set(chains.map(c => c.id)));
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Failed to fetch structure from PDB";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [pdbId]);

  const handleConfirmChainSelection = useCallback(async () => {
    if (!fetchedContent || selectedChains.size === 0) {
      setError("Please select at least one chain");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const id = pdbId.trim().toUpperCase();
      let content = fetchedContent;

      // Filter content if not all chains are selected
      if (selectedChains.size < availableChains.length) {
        content = filterCifByChains(fetchedContent, selectedChains);
      }

      const chainSuffix =
        selectedChains.size < availableChains.length
          ? `_${Array.from(selectedChains).sort().join("")}`
          : "";
      const filename = `${id}${chainSuffix}.cif`;

      const saveResult = await window.api.project.saveStructureContent(
        "original",
        filename,
        content
      );

      if (!saveResult.success) {
        throw new Error(saveResult.error || "Failed to save structure file");
      }

      // Reset state
      setFetchedContent(null);
      setAvailableChains([]);
      setSelectedChains(new Set());
      setPdbId("");

      onStructureLoaded(content, filename);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to save structure";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [
    fetchedContent,
    selectedChains,
    availableChains.length,
    pdbId,
    onStructureLoaded
  ]);

  const handleToggleChain = useCallback((chainId: string) => {
    setSelectedChains(prev => {
      const next = new Set(prev);
      if (next.has(chainId)) {
        next.delete(chainId);
      } else {
        next.add(chainId);
      }
      return next;
    });
  }, []);

  const handleSelectAllChains = useCallback(() => {
    setSelectedChains(new Set(availableChains.map(c => c.id)));
  }, [availableChains]);

  const handleDeselectAllChains = useCallback(() => {
    setSelectedChains(new Set());
  }, []);

  const handleCancelChainSelection = useCallback(() => {
    setFetchedContent(null);
    setAvailableChains([]);
    setSelectedChains(new Set());
  }, []);

  const handlePdbIdKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        void handleFetchPdb();
      }
    },
    [handleFetchPdb]
  );

  const handleClose = useCallback(
    (openState: boolean) => {
      // Only handle close (when openState becomes false)
      if (!openState && onClose) {
        onClose();
      }
    },
    [onClose]
  );

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className="sm:max-w-lg max-h-[90vh] flex flex-col overflow-visible"
        onPointerDownOutside={e => {
          e.preventDefault();
          handleClose(false);
        }}
        onEscapeKeyDown={e => {
          e.preventDefault();
          handleClose(false);
        }}
      >
        <DialogHeader className="shrink-0">
          <DialogTitle className="text-xl">Load Structure</DialogTitle>
          <DialogDescription>
            Import a molecular structure file (DNA, RNA, protein, or complex) to
            begin analysis
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4 overflow-y-auto overflow-x-visible flex-1 min-h-0">
          {/* Chain Selection View */}
          {availableChains.length > 0 ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  Select chains to import from {pdbId.toUpperCase()}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSelectAllChains}
                    className="h-7 text-xs"
                  >
                    Select All
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleDeselectAllChains}
                    className="h-7 text-xs"
                  >
                    Deselect All
                  </Button>
                </div>
              </div>

              <div className="max-h-60 overflow-y-auto rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
                {availableChains.map(chain => (
                  <div
                    key={chain.id}
                    className={`flex items-center gap-3 px-3 py-2 border-b border-neutral-200 dark:border-neutral-700/50 last:border-b-0 cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors ${
                      selectedChains.has(chain.id)
                        ? "bg-neutral-100 dark:bg-neutral-700/30"
                        : ""
                    }`}
                    onClick={() => handleToggleChain(chain.id)}
                  >
                    {selectedChains.has(chain.id) ? (
                      <CheckSquare className="h-5 w-5 text-primary shrink-0" />
                    ) : (
                      <Square className="h-5 w-5 text-neutral-400 dark:text-neutral-500 shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-semibold text-neutral-900 dark:text-neutral-200">
                          Chain {chain.id}
                        </span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-neutral-200 dark:bg-neutral-600 text-neutral-700 dark:text-neutral-300">
                          {chain.type}
                        </span>
                        <span className="text-xs text-neutral-600 dark:text-neutral-500">
                          {chain.residueCount} residues
                        </span>
                      </div>
                      {chain.description && (
                        <p className="text-xs text-neutral-600 dark:text-neutral-500 truncate">
                          {chain.description}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {/* Error Message */}
              {error && (
                <div className="flex items-center gap-2 rounded-md bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm text-red-600 dark:text-red-400">
                  <X className="h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={handleCancelChainSelection}
                  disabled={isLoading}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleConfirmChainSelection}
                  disabled={isLoading || selectedChains.size === 0}
                  className="flex-1"
                >
                  <Check className="mr-2 h-4 w-4" />
                  Load {selectedChains.size} Chain
                  {selectedChains.size !== 1 ? "s" : ""}
                </Button>
              </div>
            </div>
          ) : (
            <>
              {/* Drag and Drop Area */}
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`
                  relative flex flex-col items-center justify-center
                  rounded-lg border-2 border-dashed p-8
                  transition-all duration-200
                  ${
                    isDragging
                      ? "border-primary bg-primary/10"
                      : "border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-800/50 hover:border-neutral-400 dark:hover:border-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
                  }
                  ${isLoading ? "pointer-events-none opacity-50" : "cursor-pointer"}
                `}
                onClick={handleFileSelect}
              >
                {isLoading ? (
                  <div className="flex flex-col items-center gap-3">
                    <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
                    <p className="text-sm text-neutral-400">
                      Loading structure...
                    </p>
                  </div>
                ) : (
                  <>
                    <div
                      className={`mb-4 rounded-full p-4 ${isDragging ? "bg-primary/20" : "bg-neutral-200 dark:bg-neutral-700"}`}
                    >
                      {isDragging ? (
                        <File className="h-8 w-8 text-primary" />
                      ) : (
                        <Upload className="h-8 w-8 text-neutral-500 dark:text-neutral-400" />
                      )}
                    </div>
                    <p className="mb-1 text-sm font-medium text-neutral-900 dark:text-neutral-200">
                      {isDragging
                        ? "Drop file here"
                        : "Drag and drop structure file"}
                    </p>
                    <p className="text-xs text-neutral-600 dark:text-neutral-500">
                      or click to browse files
                    </p>
                    <p className="mt-3 text-xs text-neutral-500 dark:text-neutral-600">
                      Supported formats: PDB, mmCIF
                    </p>
                  </>
                )}
              </div>

              {/* Error Message */}
              {error && (
                <div className="flex items-center gap-2 rounded-md bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm text-red-600 dark:text-red-400">
                  <X className="h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Divider */}
              <div className="flex items-center justify-center gap-4 pt-2">
                <div className="h-px flex-1 bg-neutral-200 dark:bg-neutral-700" />
                <span className="text-xs text-neutral-500">or</span>
                <div className="h-px flex-1 bg-neutral-200 dark:bg-neutral-700" />
              </div>

              {/* Fetch from PDB */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  Fetch from RCSB PDB
                </label>
                <div className="flex gap-2 px-2">
                  <Input
                    placeholder="Enter PDB ID (e.g., 1TON)"
                    value={pdbId}
                    onChange={e => setPdbId(e.target.value.toUpperCase())}
                    onKeyDown={handlePdbIdKeyDown}
                    disabled={isLoading}
                    className="flex-1 bg-white dark:bg-neutral-800 border-neutral-300 dark:border-neutral-600 uppercase focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-0 focus-visible:border-primary"
                    maxLength={4}
                  />
                  <Button
                    onClick={handleFetchPdb}
                    disabled={isLoading || !pdbId.trim()}
                    className="shrink-0"
                  >
                    <Download className="mr-2 h-4 w-4" />
                    Fetch
                  </Button>
                </div>
              </div>

              {/* Divider */}
              <div className="flex items-center justify-center gap-4 pt-2">
                <div className="h-px flex-1 bg-neutral-200 dark:bg-neutral-700" />
                <span className="text-xs text-neutral-500">or</span>
                <div className="h-px flex-1 bg-neutral-200 dark:bg-neutral-700" />
              </div>

              {/* Browse Files Button */}
              <Button
                onClick={handleFileSelect}
                variant="outline"
                className="w-full"
                disabled={isLoading}
              >
                <File className="mr-2 h-4 w-4" />
                Browse Files
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
