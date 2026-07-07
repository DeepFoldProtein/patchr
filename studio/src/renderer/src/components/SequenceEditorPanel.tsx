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
  RotateCcw,
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
  stagedMutationsAtom,
  stagedPtmsAtom,
  uniprotReferenceAtom,
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
import { Switch } from "./ui/switch";

interface Selection {
  anchor: number;
  focus: number;
}

// A cell in the rendered full sequence. Missing (to-inpaint) positions have
// resolved === false and residue === null but still carry author/entity ids so
// they can be mutated / PTM'd (they just can't be erased).
interface DisplayCell {
  key: string;
  code: string; // display letter (mutation applied)
  origCode: string; // letter before any staged mutation
  resName?: string; // 3-letter id (for tooltips / PTM eligibility)
  authSeqId?: number;
  insCode: string;
  seqId?: number; // entity seq_id (for PTM / mutation targeting)
  resolved: boolean; // has coordinates in the structure
  residue: ResidueCell | null; // resolved residue, for 3D selection
  authLabel?: number; // author number for the tick marks
  mark?: "mutated" | "ptm"; // staged edit on this residue
  terminal?: boolean; // to-inpaint cell at an N/C terminus (vs internal gap)
}

// Flag to-inpaint cells that sit before the first / after the last resolved
// residue as terminal (internal gaps are always inpainted).
function markTerminals(cells: DisplayCell[]): DisplayCell[] {
  let first = -1;
  let last = -1;
  cells.forEach((c, i) => {
    if (c.resolved) {
      if (first < 0) first = i;
      last = i;
    }
  });
  return cells.map((c, i) =>
    !c.resolved && (first < 0 || i < first || i > last)
      ? { ...c, terminal: true }
      : c
  );
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
  const [stagedMutations, setStagedMutations] = useAtom(stagedMutationsAtom);
  const [stagedPtms, setStagedPtms] = useAtom(stagedPtmsAtom);
  const [uniprotReference, setUniprotReference] = useAtom(uniprotReferenceAtom);
  const setFastaInput = useSetAtom(fastaInputAtom);
  const setEnableSequenceMapping = useSetAtom(enableSequenceMappingAtom);
  const [skipTerminal, setSkipTerminal] = useAtom(skipTerminalAtom);
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

  const [chains, setChains] = useState<ChainSequence[]>([]);
  const [activeChainId, setActiveChainId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
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

  // Reset all staged edits back to the original structure sequence.
  const handleReset = (): void => {
    setErasedRegions([]);
    setStagedMutations([]);
    setStagedPtms([]);
    setUniprotReference("");
    refresh();
  };

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

  // Reference sequences loaded from UniProt, per chain.
  const referenceByChain = useMemo(
    () => parseFastaByChain(uniprotReference),
    [uniprotReference]
  );

  // Effective target per chain = loaded reference (UniProt) if present, else
  // poly_seq_scheme when the chain has staged mutations; mutations applied.
  const effectiveTargets = useMemo<Map<string, string>>(() => {
    const out = new Map<string, string>();
    for (const c of chains) {
      const chainId = c.authChainId;
      const muts = stagedMutations.filter(m => m.chainId === chainId);
      const fromUniProt = referenceByChain.has(chainId);
      const baseStr =
        referenceByChain.get(chainId) ??
        (muts.length ? polySeq.get(chainId)?.oneLetter : undefined);
      if (!baseStr) continue;
      if (muts.length === 0) {
        out.set(chainId, baseStr);
        continue;
      }
      const arr = baseStr.split("");
      const ref = uniprotRefs.get(chainId);
      for (const m of muts) {
        let idx: number | undefined;
        if (fromUniProt && ref && m.authSeqId >= ref.authBeg) {
          idx = ref.dbBeg + (m.authSeqId - ref.authBeg) - 1;
        } else {
          idx = polySeq
            .get(chainId)
            ?.keyToIndex.get(`${m.authSeqId}|${m.insCode}`);
        }
        if (idx !== undefined && idx >= 0 && idx < arr.length) arr[idx] = m.to;
      }
      out.set(chainId, arr.join(""));
    }
    return out;
  }, [chains, referenceByChain, stagedMutations, polySeq, uniprotRefs]);

  // Drive the inpainting run's custom-sequence path from the effective targets.
  useEffect(() => {
    const fasta = Array.from(effectiveTargets.entries())
      .map(([chainId, seq]) => `>Chain ${chainId}\n${seq}`)
      .join("\n");
    setFastaInput(fasta);
    setEnableSequenceMapping(fasta.length > 0);
  }, [effectiveTargets, setFastaInput, setEnableSequenceMapping]);

  // The full sequence rendered in the grid: every polymer position (from the
  // UniProt reference if loaded, else poly_seq_scheme), with residues that are
  // missing from the structure marked to-inpaint (green). Missing positions can
  // still be mutated / PTM'd (they carry author/entity ids); only resolved
  // residues can be erased.
  const displayCells = useMemo<DisplayCell[]>(() => {
    if (!activeChain) return [];
    const chainId = activeChain.authChainId;

    const resolvedByKey = new Map<string, ResidueCell>();
    for (const r of activeChain.residues) {
      resolvedByKey.set(`${r.authSeqId}|${r.insCode}`, r);
    }

    const mutByRes = new Map<string, string>(); // resKey -> target one-letter
    for (const m of stagedMutations) {
      if (m.chainId === chainId)
        mutByRes.set(`${m.authSeqId}|${m.insCode}`, m.to);
    }
    const ptmRes = new Set<string>();
    for (const p of stagedPtms) {
      if (p.chainId === chainId) ptmRes.add(`${p.authSeqId}|${p.insCode}`);
    }

    const makeCell = (opts: {
      key: string;
      origCode: string;
      resName?: string;
      authSeqId?: number;
      insCode: string;
      seqId?: number;
    }): DisplayCell => {
      const { key, origCode, resName, authSeqId, insCode, seqId } = opts;
      const resKey = authSeqId !== undefined ? `${authSeqId}|${insCode}` : "";
      const residue = resKey ? (resolvedByKey.get(resKey) ?? null) : null;
      const mut = resKey ? mutByRes.get(resKey) : undefined;
      const mark: DisplayCell["mark"] =
        resKey && ptmRes.has(resKey)
          ? "ptm"
          : mut !== undefined
            ? "mutated"
            : undefined;
      return {
        key,
        code: mut ?? origCode,
        origCode,
        resName,
        authSeqId,
        insCode,
        seqId,
        resolved: residue != null,
        residue,
        authLabel: insCode === "" ? authSeqId : undefined,
        mark
      };
    };

    const chainPolySeq = polySeq.get(chainId);
    const ref = uniprotRefs.get(chainId);
    const reference = referenceByChain.get(chainId);

    // 1) UniProt reference loaded: render the full reference aligned to authors.
    if (reference && ref && ref.dbEnd >= ref.dbBeg) {
      const authToSeqId = chainPolySeq?.keyToSeqId;
      const cells: DisplayCell[] = [];
      for (let p0 = 0; p0 < reference.length; p0++) {
        const p = p0 + 1;
        const authSeqId =
          p >= ref.dbBeg && p <= ref.dbEnd
            ? ref.authBeg + (p - ref.dbBeg)
            : undefined;
        cells.push(
          makeCell({
            key: `u${p0}`,
            origCode: reference[p0],
            authSeqId,
            insCode: "",
            seqId:
              authSeqId !== undefined
                ? authToSeqId?.get(`${authSeqId}|`)
                : undefined
          })
        );
      }
      return markTerminals(cells);
    }

    // 2) No reference but poly_seq_scheme present: full SEQRES with gaps green.
    if (chainPolySeq && chainPolySeq.positions.length > 0) {
      const cells = chainPolySeq.positions.map((pos, i) =>
        makeCell({
          key: `p${i}`,
          origCode: pos.code,
          resName: pos.resName,
          authSeqId: pos.authSeqId,
          insCode: pos.insCode,
          seqId: pos.seqId
        })
      );
      return markTerminals(cells);
    }

    // 3) Fallback (no poly_seq_scheme): resolved residues only.
    const cells = activeChain.residues.map(r =>
      makeCell({
        key: `${r.authSeqId}|${r.insCode}`,
        origCode: r.code,
        resName: r.resName,
        authSeqId: r.authSeqId,
        insCode: r.insCode
      })
    );
    return markTerminals(cells);
  }, [
    activeChain,
    polySeq,
    uniprotRefs,
    referenceByChain,
    stagedMutations,
    stagedPtms
  ]);

  const range = useMemo(() => {
    if (!selection) return null;
    const lo = Math.min(selection.anchor, selection.focus);
    const hi = Math.max(selection.anchor, selection.focus);
    return { lo, hi };
  }, [selection]);

  // Cells in the current selection range.
  const selectedCells = useMemo<DisplayCell[]>(
    () => (range ? displayCells.slice(range.lo, range.hi + 1) : []),
    [range, displayCells]
  );
  // Resolved residues within the selection (for the 3D highlight).
  const selectedResidues = useMemo<ResidueCell[]>(
    () =>
      selectedCells
        .map(c => c.residue)
        .filter((r): r is ResidueCell => r != null),
    [selectedCells]
  );
  const singleCell = selectedCells.length === 1 ? selectedCells[0] : null;

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

  // Erase / mutate / PTM are mutually exclusive per residue. Drop a residue
  // from any erased region (used when a mutation/PTM is staged on it).
  const unEraseResidue = (
    chainId: string,
    authSeqId: number,
    insCode: string
  ): void => {
    setErasedRegions(prev =>
      prev
        .map(region =>
          region.chainId === chainId
            ? {
                ...region,
                residues: region.residues.filter(
                  res =>
                    !(res.authSeqId === authSeqId && res.insCode === insCode)
                )
              }
            : region
        )
        .filter(region => region.residues.length > 0)
    );
  };

  const handleErase = (): void => {
    if (!activeChain || selectedResidues.length === 0) return;
    const chainId = activeChain.authChainId;
    // Keep any residue that already carries a mutation / PTM (those edits win).
    const edited = new Set<string>();
    for (const m of stagedMutations)
      if (m.chainId === chainId) edited.add(`${m.authSeqId}|${m.insCode}`);
    for (const p of stagedPtms)
      if (p.chainId === chainId) edited.add(`${p.authSeqId}|${p.insCode}`);
    const residues = selectedResidues.filter(
      r => !edited.has(`${r.authSeqId}|${r.insCode}`)
    );
    if (residues.length === 0) return;

    const first = residues[0];
    const last = residues[residues.length - 1];
    const label = `${chainId} ${first.authSeqId}${first.insCode}–${last.authSeqId}${last.insCode} (${residues.length})`;
    setErasedRegions(prev => [
      ...prev,
      {
        id: crypto.randomUUID(),
        chainId,
        residues: residues.map(r => ({
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

  const handleRestoreMutation = (id: string): void => {
    setStagedMutations(prev => prev.filter(m => m.id !== id));
  };

  const handleRestorePtm = (id: string): void => {
    setStagedPtms(prev => prev.filter(p => p.id !== id));
  };

  // Is a resolved cell currently marked erased? (Erased residues are locked
  // until restored: no erase / mutate / PTM on them.)
  const isErasedCell = (c: DisplayCell): boolean =>
    c.resolved &&
    (erasedKeys
      .get(activeChain?.authChainId ?? "")
      ?.has(`${c.authSeqId}|${c.insCode}`) ??
      false);
  const selectionHasErased = selectedCells.some(isErasedCell);

  // Mutation / PTM act on a single selected residue that has an author number —
  // resolved OR to-inpaint (they carry ids from poly_seq_scheme). Erase is
  // limited to resolved residues elsewhere.
  const mutableCell =
    singleCell && singleCell.authSeqId !== undefined ? singleCell : null;

  const canMutate =
    !!activeChain &&
    !activeChain.isNucleic &&
    !!mutableCell &&
    !isErasedCell(mutableCell);

  const handleMutate = (target: string): void => {
    if (!activeChain || !mutableCell || mutableCell.authSeqId === undefined) {
      return;
    }
    const { authSeqId, insCode, origCode } = mutableCell;
    if (origCode === target) {
      setMutateOpen(false);
      return;
    }
    const chainId = activeChain.authChainId;
    const key = `${authSeqId}|${insCode}`;
    setStagedMutations(prev => [
      ...prev.filter(
        m => !(m.chainId === chainId && `${m.authSeqId}|${m.insCode}` === key)
      ),
      {
        id: crypto.randomUUID(),
        chainId,
        authSeqId,
        insCode,
        from: origCode,
        to: target,
        label: `${chainId}/${authSeqId}${insCode} ${origCode}→${target}`
      }
    ]);
    // Mutual exclusivity: drop any erase / PTM on this residue.
    unEraseResidue(chainId, authSeqId, insCode);
    setStagedPtms(prev =>
      prev.filter(
        p => !(p.chainId === chainId && `${p.authSeqId}|${p.insCode}` === key)
      )
    );
    setMutateOpen(false);
  };

  // PTM options for the selected residue (by its one-letter code) + entity id.
  const ptmSeqId = mutableCell?.seqId;
  const ptmChoices = mutableCell
    ? PTM_OPTIONS[mutableCell.origCode]
    : undefined;
  const canPtm =
    !!activeChain &&
    !activeChain.isNucleic &&
    !!ptmChoices &&
    ptmSeqId !== undefined &&
    !!mutableCell &&
    !isErasedCell(mutableCell);

  const handlePtm = (ccd: string): void => {
    if (
      !activeChain ||
      !mutableCell ||
      ptmSeqId === undefined ||
      mutableCell.authSeqId === undefined
    ) {
      return;
    }
    const { authSeqId, insCode } = mutableCell;
    const chainId = activeChain.authChainId;
    const key = `${authSeqId}|${insCode}`;
    setStagedPtms(prev => [
      ...prev.filter(
        p => !(p.chainId === chainId && `${p.authSeqId}|${p.insCode}` === key)
      ),
      {
        id: crypto.randomUUID(),
        chainId,
        seqId: ptmSeqId,
        authSeqId,
        insCode,
        ccd,
        label: `${chainId}/${authSeqId}${insCode} → ${ccd}`
      }
    ]);
    // Mutual exclusivity: drop any erase / mutation on this residue.
    unEraseResidue(chainId, authSeqId, insCode);
    setStagedMutations(prev =>
      prev.filter(
        m => !(m.chainId === chainId && `${m.authSeqId}|${m.insCode}` === key)
      )
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
      setUniprotReference(fastaLines.join("\n"));
      setUniprotStatus("success");
    } catch (err) {
      logger.error("[Sequence Editor] UniProt fetch failed:", err);
      setUniprotStatus("error");
    }
  };

  // N/C-terminal missing residues are inpainted only when the user opts in
  // (independent of whether a reference sequence is loaded).
  const terminalsIncluded = !skipTerminal;
  // Whether the grid is showing a loaded UniProt reference (full) sequence.
  const showingReference = referenceByChain.has(activeChain?.authChainId ?? "");

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
          onClick={handleReset}
          title="Discard all staged edits and reload the original sequence"
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
        >
          <RotateCcw className="h-3 w-3" />
          Reset
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

      {/* N/C-terminal inpainting toggle — applies to all chains */}
      <div
        className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-2.5 py-1.5"
        title="When on, N/C-terminal missing residues are regenerated too (green); when off they stay ghosted and are skipped."
      >
        <label
          htmlFor="include-terminals"
          className="cursor-pointer text-xs font-medium"
        >
          Include N/C-terminal residues
        </label>
        <Switch
          id="include-terminals"
          checked={terminalsIncluded}
          onCheckedChange={checked => setSkipTerminal(!checked)}
        />
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
            const selectable = cell.authSeqId !== undefined;
            const isErased =
              cell.resolved &&
              (erasedKeys
                .get(activeChain.authChainId)
                ?.has(`${cell.authSeqId}|${cell.insCode}`) ??
                false);
            const showNumber =
              cell.authLabel !== undefined && cell.authLabel % 10 === 0;
            // Internal gaps are always inpainted; terminals only when opted in.
            const willInpaint = !cell.terminal || terminalsIncluded;
            const label = cell.resName ?? cell.origCode;
            const status = isErased
              ? " (erased)"
              : cell.mark === "mutated"
                ? ` → ${cell.code} (mutated)`
                : cell.mark === "ptm"
                  ? " (PTM)"
                  : cell.resolved
                    ? ""
                    : willInpaint
                      ? " — will be inpainted"
                      : " — skipped";
            const title =
              cell.authSeqId !== undefined
                ? `${label} ${cell.authSeqId}${cell.insCode}${status}`
                : `${label}${status}`;
            return (
              <span
                key={cell.key}
                onMouseDown={
                  selectable ? e => handleResidueMouseDown(i, e) : undefined
                }
                onMouseEnter={
                  selectable ? () => handleResidueMouseEnter(i) : undefined
                }
                title={title}
                className={cn(
                  "relative inline-block w-[0.85rem] text-center",
                  selectable && "cursor-pointer",
                  inRange
                    ? "rounded-sm bg-blue-500 text-white"
                    : cell.mark === "ptm"
                      ? "rounded-sm bg-purple-500/25 text-purple-600 dark:text-purple-300"
                      : cell.mark === "mutated"
                        ? "rounded-sm bg-amber-500/25 text-amber-700 dark:text-amber-300"
                        : isErased
                          ? "text-red-400/60 line-through"
                          : cell.resolved
                            ? "hover:bg-accent"
                            : willInpaint
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

      {/* Selection summary + actions */}
      <div>
        {(() => {
          const numbered = selectedCells.filter(c => c.authSeqId !== undefined);
          if (!numbered.length) {
            return (
              <div className="mb-2 text-xs text-muted-foreground">
                Click a residue to select; shift-click or drag to extend.
              </div>
            );
          }
          const first = numbered[0];
          const last = numbered[numbered.length - 1];
          return (
            <div className="mb-2 text-xs">
              <span className="font-semibold">Selected:</span> Chain{" "}
              <span className="font-mono">{activeChain.authChainId}</span> ·{" "}
              <span className="font-mono">
                {first.authSeqId}
                {first.insCode}–{last.authSeqId}
                {last.insCode}
              </span>{" "}
              ({numbered.length} residue{numbered.length > 1 ? "s" : ""}
              {selectedResidues.length < numbered.length
                ? `, ${selectedResidues.length} resolved`
                : ""}
              )
            </div>
          );
        })()}
        <div className="flex gap-2">
          <button
            onClick={handleErase}
            disabled={selectedResidues.length === 0 || selectionHasErased}
            title={
              selectionHasErased
                ? "Already erased — restore it first"
                : "Erase resolved residues in the selection (missing residues can't be erased)"
            }
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
                : mutableCell && isErasedCell(mutableCell)
                  ? "Erased — restore it first"
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
                : mutableCell && isErasedCell(mutableCell)
                  ? "Erased — restore it first"
                  : "Select a single Ser/Thr/Tyr/Lys residue"
            }
            className="inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-50 disabled:hover:bg-transparent"
          >
            <Atom className="h-3 w-3" />
            PTM…
          </button>
        </div>

        {/* Contextual hint for why PTM may be unavailable */}
        {mutableCell && !activeChain.isNucleic && !canPtm && (
          <p className="mt-1.5 text-[0.7rem] text-muted-foreground">
            PTM applies to Ser/Thr/Tyr/Lys —{" "}
            {mutableCell.resName ?? mutableCell.origCode} has none.
          </p>
        )}

        {ptmOpen && canPtm && mutableCell && ptmChoices && (
          <div className="mt-2 rounded-md border border-border p-2">
            <div className="mb-1.5 text-xs text-muted-foreground">
              Modify{" "}
              <span className="font-mono">
                {mutableCell.resName ?? mutableCell.origCode}{" "}
                {mutableCell.authSeqId}
                {mutableCell.insCode}
              </span>
              :
            </div>
            <div className="flex flex-col gap-1">
              {ptmChoices.map(choice => (
                <button
                  key={choice.ccd}
                  onClick={() => handlePtm(choice.ccd)}
                  className="rounded bg-muted px-2 py-1 text-left text-xs transition-colors hover:bg-blue-500 hover:text-white"
                >
                  {choice.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {mutateOpen && canMutate && mutableCell && (
          <div className="mt-2 rounded-md border border-border p-2">
            <div className="mb-1.5 text-xs text-muted-foreground">
              Mutate{" "}
              <span className="font-mono">
                {mutableCell.resName ?? mutableCell.origCode}{" "}
                {mutableCell.authSeqId}
                {mutableCell.insCode}
              </span>{" "}
              to:
            </div>
            <div className="grid grid-cols-10 gap-1">
              {AA_TARGETS.map(aa => {
                const isCurrent = mutableCell.origCode === aa;
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

      {/* Staged mutations — marked amber in the grid, restorable */}
      {stagedMutations.length > 0 && (
        <div className="rounded-md border border-amber-400/30 bg-amber-500/5 p-2">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-semibold text-amber-600 dark:text-amber-400">
              Mutations ({stagedMutations.length})
            </span>
            <button
              onClick={() => setStagedMutations([])}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Clear all
            </button>
          </div>
          <ul className="space-y-1">
            {stagedMutations.map(m => (
              <li
                key={m.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="truncate font-mono text-muted-foreground">
                  {m.label}
                </span>
                <button
                  onClick={() => handleRestoreMutation(m.id)}
                  title="Restore this residue"
                  className="inline-flex shrink-0 items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[0.7rem] hover:bg-accent"
                >
                  <Undo2 className="h-3 w-3" />
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Staged PTMs — marked purple in the grid, restorable */}
      {stagedPtms.length > 0 && (
        <div className="rounded-md border border-purple-400/30 bg-purple-500/5 p-2">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-semibold text-purple-600 dark:text-purple-400">
              PTMs ({stagedPtms.length})
            </span>
            <button
              onClick={() => setStagedPtms([])}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Clear all
            </button>
          </div>
          <ul className="space-y-1">
            {stagedPtms.map(p => (
              <li
                key={p.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="truncate font-mono text-muted-foreground">
                  {p.label}
                </span>
                <button
                  onClick={() => handleRestorePtm(p.id)}
                  title="Restore this residue"
                  className="inline-flex shrink-0 items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[0.7rem] hover:bg-accent"
                >
                  <Undo2 className="h-3 w-3" />
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
