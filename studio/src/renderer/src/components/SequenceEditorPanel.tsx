// Residue editor — embedded in the Repair tab's "Sequence" section. Shows the
// resolved per-chain sequence of the loaded structure and lets the user select
// residues (click, shift-click, or drag) to stage one of three actions, each of
// which hands off to the inpainting run in the same tab:
//   - Erase & Regenerate: strip the residues from the CIF and re-inpaint them.
//   - Mutate: change a residue's identity via the custom-sequence path.
//   - PTM: add a modified residue (SEP/TPO/PTR/MLY/…) via the backend
//     modifications field.
import React, { useEffect, useMemo, useState } from "react";
import { useAtom, useAtomValue, useSetAtom } from "jotai";
import {
  RefreshCw,
  Eraser,
  FlaskConical,
  Atom,
  Undo2,
  Search
} from "lucide-react";
import { pluginAtom } from "../store/mol-viewer-atoms";
import {
  missingRegionsDetectedAtom,
  erasedRegionsAtom,
  erasedResidueKeysAtom,
  pendingPtmAtom,
  fastaInputAtom,
  enableSequenceMappingAtom,
  skipTerminalAtom
} from "../store/repair-atoms";
import { useStructureContent } from "../store/project-store";
import {
  getChainSequences,
  selectResiduesInViewer,
  type ChainSequence,
  type ResidueCell
} from "../lib/chainSequences";
import { parsePolySeqScheme } from "../lib/polySeq";
import { parseUniProtRefs } from "../lib/structRef";
import { cn } from "../lib/utils";
import { logger } from "../lib/logger";

interface Selection {
  anchor: number;
  focus: number;
}

// A cell in the rendered sequence: either a resolved structure residue
// (interactive) or a position that will be inpainted (residue === null).
interface DisplayCell {
  key: string;
  code: string;
  residue: ResidueCell | null;
  authLabel?: number; // author number for the tick marks
}

// Parse a multi-chain FASTA (">Chain A\nSEQ" or ">A\nSEQ") into chain -> seq.
function parseFastaByChain(fasta: string): Map<string, string> {
  const map = new Map<string, string>();
  if (!fasta) return map;
  let chain: string | null = null;
  let seq: string[] = [];
  for (const line of fasta.split("\n")) {
    if (line.startsWith(">")) {
      if (chain) map.set(chain, seq.join(""));
      const m = line.match(/Chain[_\s]+(\S+)/i) || line.match(/^>(\S+)/);
      chain = m ? m[1] : null;
      seq = [];
    } else if (chain) {
      seq.push(line.trim());
    }
  }
  if (chain) map.set(chain, seq.join(""));
  return map;
}

// Standard amino acids offered as mutation targets.
const AA_TARGETS = [
  "A",
  "R",
  "N",
  "D",
  "C",
  "Q",
  "E",
  "G",
  "H",
  "I",
  "L",
  "K",
  "M",
  "F",
  "P",
  "S",
  "T",
  "W",
  "Y",
  "V"
];

// PTMs offered per residue one-letter code → CCD component ids.
const PTM_OPTIONS: Record<string, { label: string; ccd: string }[]> = {
  S: [{ label: "Phosphoserine (SEP)", ccd: "SEP" }],
  T: [{ label: "Phosphothreonine (TPO)", ccd: "TPO" }],
  Y: [{ label: "Phosphotyrosine (PTR)", ccd: "PTR" }],
  K: [
    { label: "N6-methyllysine (MLY)", ccd: "MLY" },
    { label: "N6,N6,N6-trimethyllysine (M3L)", ccd: "M3L" }
  ]
};

export function SequenceEditorPanel(): React.ReactElement {
  const plugin = useAtomValue(pluginAtom);
  // Re-detection of missing regions is a reliable "structure is ready" signal.
  const missingRegions = useAtomValue(missingRegionsDetectedAtom);
  const [erasedRegions, setErasedRegions] = useAtom(erasedRegionsAtom);
  const erasedKeys = useAtomValue(erasedResidueKeysAtom);
  const [fastaInput, setFastaInput] = useAtom(fastaInputAtom);
  const [enableSequenceMapping, setEnableSequenceMapping] = useAtom(
    enableSequenceMappingAtom
  );
  const [skipTerminal, setSkipTerminal] = useAtom(skipTerminalAtom);
  const setPendingPtm = useSetAtom(pendingPtmAtom);
  const structureContent = useStructureContent();
  const polySeq = useMemo(
    () => parsePolySeqScheme(structureContent),
    [structureContent]
  );
  // UniProt reference (accession + structure alignment) per author chain, from
  // the CIF's _struct_ref. Used to prefill the search and to align a loaded
  // reference sequence back onto the structure for the full-sequence view.
  const uniprotRefs = useMemo(
    () => parseUniProtRefs(structureContent),
    [structureContent]
  );
  // Reference sequences currently loaded into the inpainting run, per chain.
  const loadedTargets = useMemo(
    () => parseFastaByChain(fastaInput),
    [fastaInput]
  );

  const [chains, setChains] = useState<ChainSequence[]>([]);
  const [activeChainId, setActiveChainId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [staged, setStaged] = useState<string | null>(null);
  const [mutateOpen, setMutateOpen] = useState(false);
  const [ptmOpen, setPtmOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uniprotId, setUniprotId] = useState("");
  const [uniprotStatus, setUniprotStatus] = useState<
    "idle" | "searching" | "success" | "error"
  >("idle");

  const refresh = React.useCallback(() => {
    const next = getChainSequences(plugin);
    setChains(next);
    setActiveChainId(prev =>
      prev && next.some(c => c.authChainId === prev)
        ? prev
        : (next[0]?.authChainId ?? null)
    );
    setSelection(null);
  }, [plugin]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plugin, missingRegions]);

  // Prefill the search with the active chain's UniProt accession (updates when
  // the active chain or structure changes).
  const detectedUniprotId = activeChainId
    ? (uniprotRefs.get(activeChainId)?.accession ?? "")
    : "";
  useEffect(() => {
    setUniprotId(detectedUniprotId);
    setUniprotStatus("idle");
  }, [detectedUniprotId]);

  const activeChain = useMemo(
    () => chains.find(c => c.authChainId === activeChainId) ?? null,
    [chains, activeChainId]
  );

  // The sequence rendered in the grid. When a reference sequence is loaded for
  // the active chain (UniProt/mutation) and we know its structure alignment,
  // show the FULL reference with structure-resolved residues interactive and
  // the rest marked to-inpaint. Otherwise show the resolved residues as-is.
  const displayCells = useMemo<DisplayCell[]>(() => {
    if (!activeChain) return [];
    const resolvedByAuth = new Map<number, ResidueCell>();
    for (const r of activeChain.residues) {
      if (r.insCode === "") resolvedByAuth.set(r.authSeqId, r);
    }

    const ref = uniprotRefs.get(activeChain.authChainId);
    const target = loadedTargets.get(activeChain.authChainId);
    const aligned = ref && ref.dbEnd >= ref.dbBeg;

    if (enableSequenceMapping && target && aligned) {
      const cells: DisplayCell[] = [];
      for (let p = 1; p <= target.length; p++) {
        let residue: ResidueCell | null = null;
        let authLabel: number | undefined;
        if (p >= ref.dbBeg && p <= ref.dbEnd) {
          const authNum = ref.authBeg + (p - ref.dbBeg);
          authLabel = authNum;
          residue = resolvedByAuth.get(authNum) ?? null;
        }
        cells.push({ key: `u${p}`, code: target[p - 1], residue, authLabel });
      }
      return cells;
    }

    // Default: resolved residues, with ghosted terminal-missing cells at ends.
    const termCode = (
      region: (typeof missingRegions)[number] | undefined
    ): string[] => {
      if (!region) return [];
      if (region.sequenceKnown && region.sequence) {
        return region.sequence.split("");
      }
      return Array.from({ length: region.regionLength ?? 0 }, () => "·");
    };
    const chainRegions = missingRegions.filter(
      r => r.chainId === activeChain.authChainId
    );
    const nterm = chainRegions.find(r => r.terminalType === "nterm");
    const cterm = chainRegions.find(r => r.terminalType === "cterm");

    const cells: DisplayCell[] = [];
    termCode(nterm).forEach((code, i) =>
      cells.push({ key: `nt${i}`, code, residue: null })
    );
    for (const r of activeChain.residues) {
      cells.push({
        key: `${r.authSeqId}|${r.insCode}`,
        code: r.code,
        residue: r,
        authLabel: r.insCode === "" ? r.authSeqId : undefined
      });
    }
    termCode(cterm).forEach((code, i) =>
      cells.push({ key: `ct${i}`, code, residue: null })
    );
    return cells;
  }, [
    activeChain,
    uniprotRefs,
    loadedTargets,
    enableSequenceMapping,
    missingRegions
  ]);

  const range = useMemo(() => {
    if (!selection) return null;
    const lo = Math.min(selection.anchor, selection.focus);
    const hi = Math.max(selection.anchor, selection.focus);
    return { lo, hi };
  }, [selection]);

  // Selected structure residues (only resolved cells in range are actionable).
  const selectedResidues = useMemo<ResidueCell[]>(() => {
    if (!range) return [];
    const out: ResidueCell[] = [];
    for (let i = range.lo; i <= range.hi && i < displayCells.length; i++) {
      const res = displayCells[i]?.residue;
      if (res) out.push(res);
    }
    return out;
  }, [range, displayCells]);

  // N/C-terminal missing regions for the active chain (shown ghosted).
  const chainMissing = useMemo(
    () =>
      activeChain
        ? missingRegions.filter(r => r.chainId === activeChain.authChainId)
        : [],
    [missingRegions, activeChain]
  );

  // Mirror the sequence selection into the 3D viewer (highlight + zoom).
  // Skip while dragging so a fast range-drag doesn't re-scan atoms on every
  // step; the highlight applies once when the drag ends (dragging -> false).
  useEffect(() => {
    if (!activeChain || dragging) return;
    selectResiduesInViewer(plugin, activeChain.authChainId, selectedResidues);
  }, [plugin, activeChain, selectedResidues, dragging]);

  // Selection: click a residue, shift-click to extend, or drag across residues
  // to select a range (for multi-residue erase).
  const handleResidueMouseDown = (index: number, e: React.MouseEvent): void => {
    e.preventDefault();
    if (e.shiftKey && selection) {
      setSelection({ anchor: selection.anchor, focus: index });
    } else {
      setSelection({ anchor: index, focus: index });
    }
    setDragging(true);
  };

  const handleResidueMouseEnter = (index: number): void => {
    if (!dragging) return;
    setSelection(prev =>
      prev
        ? { anchor: prev.anchor, focus: index }
        : { anchor: index, focus: index }
    );
  };

  // End a drag anywhere on the document (even outside the grid).
  useEffect(() => {
    if (!dragging) return;
    const stop = (): void => setDragging(false);
    window.addEventListener("mouseup", stop);
    return () => window.removeEventListener("mouseup", stop);
  }, [dragging]);

  const handleErase = (): void => {
    if (!activeChain || selectedResidues.length === 0) return;
    const first = selectedResidues[0];
    const last = selectedResidues[selectedResidues.length - 1];
    const label = `${activeChain.authChainId} ${first.authSeqId}${first.insCode}–${last.authSeqId}${last.insCode} (${selectedResidues.length})`;
    setErasedRegions(prev => [
      ...prev,
      {
        id: crypto.randomUUID(),
        chainId: activeChain.authChainId,
        residues: selectedResidues.map(r => ({
          authSeqId: r.authSeqId,
          insCode: r.insCode
        })),
        label
      }
    ]);
    // Clear the working selection so the next region can be marked.
    setSelection(null);
  };

  const handleRestore = (id: string): void => {
    setErasedRegions(prev => prev.filter(r => r.id !== id));
  };

  const handleClearErased = (): void => {
    setErasedRegions([]);
  };

  // Mutation is available when exactly one protein residue is selected and its
  // position is resolvable in the CIF's poly_seq_scheme (full, gap-aware seq).
  const singleResidue =
    selectedResidues.length === 1 ? selectedResidues[0] : null;
  const chainPoly = activeChain
    ? polySeq.get(activeChain.authChainId)
    : undefined;
  const mutationIndex =
    singleResidue && chainPoly
      ? chainPoly.keyToIndex.get(
          `${singleResidue.authSeqId}|${singleResidue.insCode}`
        )
      : undefined;
  const canMutate =
    !!activeChain &&
    !activeChain.isNucleic &&
    !!chainPoly &&
    mutationIndex !== undefined;

  const handleMutate = (target: string): void => {
    if (
      !activeChain ||
      !chainPoly ||
      mutationIndex === undefined ||
      !singleResidue
    ) {
      return;
    }
    const original = chainPoly.oneLetter[mutationIndex];
    if (original === target) {
      setMutateOpen(false);
      return;
    }
    const seq = chainPoly.oneLetter.split("");
    seq[mutationIndex] = target;
    const mutatedSeq = seq.join("");
    // Feed the mutated full sequence through the existing custom-sequence
    // (sequence-mapping) upload path; the backend strips the mismatched residue
    // and regenerates it as the target identity.
    setFastaInput(`>${activeChain.authChainId}\n${mutatedSeq}`);
    setEnableSequenceMapping(true);
    const label = `${activeChain.authChainId}/${singleResidue.authSeqId}${singleResidue.insCode} ${original}→${target}`;
    setStaged(`Mutation ${label}`);
    setMutateOpen(false);
  };

  // PTM options for the selected residue (by its one-letter code), plus the
  // entity seq_id the backend needs to target the modification.
  const ptmSeqId =
    singleResidue && chainPoly
      ? chainPoly.keyToSeqId.get(
          `${singleResidue.authSeqId}|${singleResidue.insCode}`
        )
      : undefined;
  const ptmChoices = singleResidue
    ? PTM_OPTIONS[singleResidue.code]
    : undefined;
  const canPtm =
    !!activeChain &&
    !activeChain.isNucleic &&
    !!ptmChoices &&
    ptmSeqId !== undefined;

  const handlePtm = (ccd: string, ptmLabel: string): void => {
    if (!activeChain || !singleResidue || ptmSeqId === undefined) return;
    setPendingPtm({
      chainId: activeChain.authChainId,
      seqId: ptmSeqId,
      ccd,
      label: `${activeChain.authChainId}/${singleResidue.authSeqId}${singleResidue.insCode} ${ptmLabel}`
    });
    // PTM is its own staged action — clear any prior sequence-mapping edit.
    setEnableSequenceMapping(false);
    setFastaInput("");
    setStaged(
      `PTM ${activeChain.authChainId}/${singleResidue.authSeqId}${singleResidue.insCode} → ${ccd}`
    );
    setPtmOpen(false);
  };

  // Load full reference sequences to fill missing regions during inpainting.
  // Each protein chain is fetched by its UniProt accession (from the CIF, with
  // the field value overriding the active chain in case it was edited); nucleic
  // chains fall back to their full poly_seq_scheme sequence.
  const handleUniprotSearch = async (): Promise<void> => {
    if (chains.length === 0) return;
    setUniprotStatus("searching");
    try {
      if (!window.api?.uniprot?.fetchById) {
        throw new Error("UniProt API not available");
      }
      const fastaLines: string[] = [];

      for (const c of chains) {
        if (c.isNucleic) {
          const seq = polySeq.get(c.authChainId)?.oneLetter;
          if (seq) fastaLines.push(`>Chain ${c.authChainId}\n${seq}`);
          continue;
        }
        const acc =
          c.authChainId === activeChainId
            ? uniprotId.trim()
            : (uniprotRefs.get(c.authChainId)?.accession ?? "");
        if (!acc) continue;
        const res = await window.api.uniprot.fetchById(acc);
        if (res.success && res.fasta) {
          fastaLines.push(`>Chain ${c.authChainId}\n${res.fasta}`);
        }
      }

      if (fastaLines.length === 0) {
        throw new Error("No sequences returned");
      }
      setFastaInput(fastaLines.join("\n"));
      setEnableSequenceMapping(true);
      setUniprotStatus("success");
      setStaged("UniProt reference sequences loaded");
    } catch (err) {
      logger.error("[Sequence Editor] UniProt fetch failed:", err);
      setUniprotStatus("error");
    }
  };

  const hasTerminals = chainMissing.some(
    r => r.terminalType === "nterm" || r.terminalType === "cterm"
  );
  // Terminals are inpainted when the user opts in, or when a full sequence is
  // provided (UniProt/mutation), since terminals then come from that sequence.
  const terminalsIncluded = enableSequenceMapping || !skipTerminal;
  // Whether the grid is showing a loaded reference (full) sequence.
  const showingReference =
    enableSequenceMapping &&
    !!loadedTargets.get(activeChain?.authChainId ?? "") &&
    (uniprotRefs.get(activeChain?.authChainId ?? "")?.dbEnd ?? 0) >=
      (uniprotRefs.get(activeChain?.authChainId ?? "")?.dbBeg ?? 1);

  if (!activeChain) {
    return (
      <div className="py-4 text-center text-sm text-muted-foreground">
        <p className="text-xs">
          Load a structure to select residues for erase / mutate / PTM.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Select residues (drag for a range) to erase, mutate, or add a PTM.
        </p>
        <button
          onClick={refresh}
          title="Reload sequences from the current structure"
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
        >
          <RefreshCw className="h-3 w-3" />
          Refresh
        </button>
      </div>

      {/* UniProt reference-sequence search */}
      <div className="flex items-center gap-2">
        <input
          value={uniprotId}
          onChange={e => {
            setUniprotId(e.target.value);
            setUniprotStatus("idle");
          }}
          placeholder="UniProt ID (e.g. P01241)"
          title="UniProt accession for the active chain (auto-filled from the structure)"
          className="h-7 w-32 rounded-md border border-border bg-transparent px-2 font-mono text-xs outline-none focus:border-blue-500"
        />
        <button
          onClick={handleUniprotSearch}
          disabled={uniprotStatus === "searching"}
          title="Load full reference sequences from UniProt to fill missing regions"
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50"
        >
          <Search className="h-3 w-3" />
          {uniprotStatus === "searching" ? "Loading…" : "UniProt"}
        </button>
        {uniprotStatus === "success" && (
          <span className="text-xs text-green-600 dark:text-green-400">
            loaded
          </span>
        )}
        {uniprotStatus === "error" && (
          <span className="text-xs text-red-500">not found</span>
        )}
      </div>

      {/* Chain selector */}
      <div className="flex flex-wrap gap-1">
        {chains.map(c => (
          <button
            key={c.authChainId}
            onClick={() => {
              setActiveChainId(c.authChainId);
              setSelection(null);
            }}
            className={cn(
              "rounded px-2 py-0.5 font-mono text-xs transition-colors",
              c.authChainId === activeChainId
                ? "bg-primary text-primary-foreground"
                : "bg-muted hover:bg-accent"
            )}
          >
            {c.authChainId}
            <span className="ml-1 opacity-60">
              {c.isNucleic ? "nt" : "aa"} · {c.residues.length}
            </span>
          </button>
        ))}
      </div>

      {/* Residue grid */}
      <div className="max-h-56 overflow-auto rounded-md border border-border p-2">
        <div className="select-none font-mono text-xs leading-6">
          {displayCells.map((cell, i) => {
            const inRange = range ? i >= range.lo && i <= range.hi : false;
            const res = cell.residue;
            const isErased =
              res != null &&
              (erasedKeys
                .get(activeChain.authChainId)
                ?.has(`${res.authSeqId}|${res.insCode}`) ??
                false);
            const showNumber =
              cell.authLabel !== undefined && cell.authLabel % 10 === 0;
            const title =
              res != null
                ? `${res.resName} ${res.authSeqId}${res.insCode}${isErased ? " (erased)" : ""}`
                : terminalsIncluded
                  ? "Missing — will be inpainted"
                  : "Missing — skipped";
            return (
              <span
                key={cell.key}
                onMouseDown={
                  res ? e => handleResidueMouseDown(i, e) : undefined
                }
                onMouseEnter={
                  res ? () => handleResidueMouseEnter(i) : undefined
                }
                title={title}
                className={cn(
                  "relative inline-block w-[0.85rem] text-center",
                  res
                    ? inRange
                      ? "cursor-pointer rounded-sm bg-blue-500 text-white"
                      : isErased
                        ? "cursor-pointer text-red-400/60 line-through"
                        : "cursor-pointer hover:bg-accent"
                    : terminalsIncluded
                      ? "text-green-500/70"
                      : "text-muted-foreground/30"
                )}
              >
                {cell.code}
                {showNumber && (
                  <span className="pointer-events-none absolute -top-3 left-1/2 -translate-x-1/2 text-[0.6rem] text-blue-500">
                    {cell.authLabel}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      </div>
      {showingReference && (
        <p className="text-[0.7rem] text-muted-foreground">
          Showing the loaded reference sequence — green residues are missing
          from the structure and will be inpainted.
        </p>
      )}

      {/* N/C-terminal inpainting toggle */}
      {hasTerminals && (
        <label
          className={cn(
            "flex items-center gap-2 text-xs",
            enableSequenceMapping && "opacity-50"
          )}
          title={
            enableSequenceMapping
              ? "Terminals come from the loaded reference sequence"
              : "Ghosted terminal residues are only regenerated when this is on"
          }
        >
          <input
            type="checkbox"
            checked={terminalsIncluded}
            disabled={enableSequenceMapping}
            onChange={e => setSkipTerminal(!e.target.checked)}
          />
          Include N/C-terminal residues in inpainting
        </label>
      )}

      {/* Selection summary + actions */}
      <div>
        {range && selectedResidues.length > 0 ? (
          <div className="mb-2 text-xs">
            <span className="font-semibold">Selected:</span> Chain{" "}
            <span className="font-mono">{activeChain.authChainId}</span> ·{" "}
            <span className="font-mono">
              {selectedResidues[0].authSeqId}
              {selectedResidues[0].insCode}–
              {selectedResidues[selectedResidues.length - 1].authSeqId}
              {selectedResidues[selectedResidues.length - 1].insCode}
            </span>{" "}
            ({selectedResidues.length} residue
            {selectedResidues.length > 1 ? "s" : ""})
          </div>
        ) : (
          <div className="mb-2 text-xs text-muted-foreground">
            Click a residue to select; shift-click to extend the range.
          </div>
        )}
        <div className="flex gap-2">
          <button
            onClick={handleErase}
            disabled={selectedResidues.length === 0}
            title="Mark the selected residues for erasure (shown ghosted; restore anytime)"
            className="inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-50 disabled:hover:bg-transparent"
          >
            <Eraser className="h-3 w-3" />
            Erase
          </button>
          <button
            onClick={() => setMutateOpen(o => !o)}
            disabled={!canMutate}
            title={
              canMutate
                ? "Substitute the selected residue and rebuild it via inpainting"
                : "Select a single protein residue (requires mmCIF poly_seq_scheme)"
            }
            className="inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-50 disabled:hover:bg-transparent"
          >
            <FlaskConical className="h-3 w-3" />
            Mutate…
          </button>
          <button
            onClick={() => setPtmOpen(o => !o)}
            disabled={!canPtm}
            title={
              canPtm
                ? "Add a post-translational modification to the selected residue"
                : "Select a single Ser/Thr/Tyr/Lys residue"
            }
            className="inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-50 disabled:hover:bg-transparent"
          >
            <Atom className="h-3 w-3" />
            PTM…
          </button>
        </div>

        {/* Contextual hint for why Mutate/PTM may be unavailable */}
        {singleResidue && !chainPoly && (
          <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
            Mutate / PTM need an mmCIF with poly_seq_scheme (load the full CIF).
          </p>
        )}
        {singleResidue && chainPoly && !activeChain.isNucleic && !canPtm && (
          <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
            PTM applies to Ser/Thr/Tyr/Lys — {singleResidue.resName} has none.
          </p>
        )}

        {ptmOpen && canPtm && singleResidue && ptmChoices && (
          <div className="mt-2 rounded-md border border-border p-2">
            <div className="mb-1.5 text-xs text-muted-foreground">
              Modify{" "}
              <span className="font-mono">
                {singleResidue.resName} {singleResidue.authSeqId}
                {singleResidue.insCode}
              </span>
              :
            </div>
            <div className="flex flex-col gap-1">
              {ptmChoices.map(choice => (
                <button
                  key={choice.ccd}
                  onClick={() => handlePtm(choice.ccd, choice.label)}
                  className="rounded bg-muted px-2 py-1 text-left text-xs transition-colors hover:bg-blue-500 hover:text-white"
                >
                  {choice.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {mutateOpen && canMutate && singleResidue && (
          <div className="mt-2 rounded-md border border-border p-2">
            <div className="mb-1.5 text-xs text-muted-foreground">
              Mutate{" "}
              <span className="font-mono">
                {singleResidue.resName} {singleResidue.authSeqId}
                {singleResidue.insCode}
              </span>{" "}
              to:
            </div>
            <div className="grid grid-cols-10 gap-1">
              {AA_TARGETS.map(aa => {
                const isCurrent =
                  chainPoly?.oneLetter[mutationIndex ?? -1] === aa;
                return (
                  <button
                    key={aa}
                    onClick={() => handleMutate(aa)}
                    disabled={isCurrent}
                    title={isCurrent ? "Current residue" : `Mutate to ${aa}`}
                    className={cn(
                      "rounded py-1 font-mono text-xs transition-colors",
                      isCurrent
                        ? "bg-muted opacity-40"
                        : "bg-muted hover:bg-blue-500 hover:text-white"
                    )}
                  >
                    {aa}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {staged && (
          <div className="mt-2 rounded-md bg-blue-500/10 px-2 py-1.5 text-xs text-blue-600 dark:text-blue-400">
            Staged <span className="font-mono">{staged}</span>. Press{" "}
            <span className="font-semibold">Start Inference</span> below to
            regenerate.
          </div>
        )}
      </div>

      {/* Erased regions — ghosted in 3D, restorable, regenerated on run */}
      {erasedRegions.length > 0 && (
        <div className="rounded-md border border-red-400/30 bg-red-500/5 p-2">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-semibold text-red-500 dark:text-red-400">
              Erased ({erasedRegions.length})
            </span>
            <button
              onClick={handleClearErased}
              title="Restore all erased residues"
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Clear all
            </button>
          </div>
          <ul className="space-y-1">
            {erasedRegions.map(region => (
              <li
                key={region.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="truncate font-mono text-muted-foreground line-through">
                  {region.label}
                </span>
                <button
                  onClick={() => handleRestore(region.id)}
                  title="Restore this region"
                  className="inline-flex shrink-0 items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[0.7rem] hover:bg-accent"
                >
                  <Undo2 className="h-3 w-3" />
                  Restore
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
            Erased residues are regenerated when you press{" "}
            <span className="font-semibold">Start Inference</span>.
          </p>
        </div>
      )}
    </div>
  );
}
