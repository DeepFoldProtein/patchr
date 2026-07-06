// Sequence editor tab. Shows the resolved per-chain sequence of the loaded
// structure and lets the user select a residue range. Selected ranges feed two
// actions (wired in later slices):
//   - Erase & Regenerate: strip the residues from the CIF and re-inpaint them.
//   - Mutate: change residue identities and re-run via the custom-sequence path.
import React, { useEffect, useMemo, useState } from "react";
import { useAtomValue, useSetAtom } from "jotai";
import { RefreshCw, Eraser, FlaskConical } from "lucide-react";
import { pluginAtom } from "../store/mol-viewer-atoms";
import {
  missingRegionsDetectedAtom,
  pendingEraseAtom,
  fastaInputAtom,
  enableSequenceMappingAtom
} from "../store/repair-atoms";
import { panelModeAtom } from "../store/api-atoms";
import { useStructureContent } from "../store/project-store";
import {
  getChainSequences,
  selectResiduesInViewer,
  type ChainSequence,
  type ResidueCell
} from "../lib/chainSequences";
import { parsePolySeqScheme } from "../lib/polySeq";
import { cn } from "../lib/utils";

interface Selection {
  anchor: number;
  focus: number;
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

export function SequenceEditorPanel(): React.ReactElement {
  const plugin = useAtomValue(pluginAtom);
  // Re-detection of missing regions is a reliable "structure is ready" signal.
  const missingRegions = useAtomValue(missingRegionsDetectedAtom);
  const setPendingErase = useSetAtom(pendingEraseAtom);
  const setPanelMode = useSetAtom(panelModeAtom);
  const setFastaInput = useSetAtom(fastaInputAtom);
  const setEnableSequenceMapping = useSetAtom(enableSequenceMappingAtom);
  const structureContent = useStructureContent();
  const polySeq = useMemo(
    () => parsePolySeqScheme(structureContent),
    [structureContent]
  );

  const [chains, setChains] = useState<ChainSequence[]>([]);
  const [activeChainId, setActiveChainId] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [staged, setStaged] = useState<string | null>(null);
  const [mutateOpen, setMutateOpen] = useState(false);

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

  const activeChain = useMemo(
    () => chains.find(c => c.authChainId === activeChainId) ?? null,
    [chains, activeChainId]
  );

  const range = useMemo(() => {
    if (!selection) return null;
    const lo = Math.min(selection.anchor, selection.focus);
    const hi = Math.max(selection.anchor, selection.focus);
    return { lo, hi };
  }, [selection]);

  const selectedResidues = useMemo<ResidueCell[]>(
    () =>
      range && activeChain
        ? activeChain.residues.slice(range.lo, range.hi + 1)
        : [],
    [range, activeChain]
  );

  // Mirror the sequence selection into the 3D viewer (highlight + zoom).
  useEffect(() => {
    if (!activeChain) return;
    selectResiduesInViewer(plugin, activeChain.authChainId, selectedResidues);
  }, [plugin, activeChain, selectedResidues]);

  const handleResidueClick = (index: number, e: React.MouseEvent): void => {
    if (e.shiftKey && selection) {
      setSelection({ anchor: selection.anchor, focus: index });
    } else {
      setSelection({ anchor: index, focus: index });
    }
  };

  const handleErase = (): void => {
    if (!activeChain || selectedResidues.length === 0) return;
    const first = selectedResidues[0];
    const last = selectedResidues[selectedResidues.length - 1];
    const label = `${activeChain.authChainId} ${first.authSeqId}${first.insCode}–${last.authSeqId}${last.insCode} (${selectedResidues.length})`;
    setPendingErase({
      chainId: activeChain.authChainId,
      residues: selectedResidues.map(r => ({
        authSeqId: r.authSeqId,
        insCode: r.insCode
      })),
      label
    });
    setStaged(label);
    // Hand off to the Repair tab where the inpainting run lives.
    setPanelMode("repair");
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
    // Mutation and erase are distinct staged actions — don't let a prior erase
    // also fire on the next run.
    setPendingErase(null);
    const label = `${activeChain.authChainId}/${singleResidue.authSeqId}${singleResidue.insCode} ${original}→${target}`;
    setStaged(`Mutation ${label}`);
    setMutateOpen(false);
    setPanelMode("repair");
  };

  if (!activeChain) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        <p className="mb-1 font-medium">No structure loaded</p>
        <p className="text-xs">
          Open a project with a structure to edit its sequence.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <div>
          <h3 className="text-sm font-semibold">Sequence Editor</h3>
          <p className="text-xs text-muted-foreground">
            Select residues to erase &amp; regenerate or mutate.
          </p>
        </div>
        <button
          onClick={refresh}
          title="Reload sequences from the current structure"
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
        >
          <RefreshCw className="h-3 w-3" />
          Refresh
        </button>
      </div>

      {/* Chain selector */}
      <div className="flex flex-wrap gap-1 border-b border-border px-4 py-2">
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
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        <div className="font-mono text-xs leading-6">
          {activeChain.residues.map((r, i) => {
            const inRange = range ? i >= range.lo && i <= range.hi : false;
            const showNumber = r.authSeqId % 10 === 0 && r.insCode === "";
            return (
              <span
                key={`${r.authSeqId}|${r.insCode}`}
                onClick={e => handleResidueClick(i, e)}
                title={`${r.resName} ${r.authSeqId}${r.insCode}`}
                className={cn(
                  "relative inline-block w-[0.85rem] cursor-pointer text-center",
                  inRange
                    ? "rounded-sm bg-blue-500 text-white"
                    : "hover:bg-accent"
                )}
              >
                {r.code}
                {showNumber && (
                  <span className="pointer-events-none absolute -top-3 left-1/2 -translate-x-1/2 text-[0.6rem] text-blue-500">
                    {r.authSeqId}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      </div>

      {/* Selection summary + actions */}
      <div className="border-t border-border px-4 py-2">
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
            title="Strip the selected residues and regenerate them via inpainting"
            className="inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-50 disabled:hover:bg-transparent"
          >
            <Eraser className="h-3 w-3" />
            Erase &amp; Regenerate
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
        </div>

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
            Staged <span className="font-mono">{staged}</span>. Open the{" "}
            <span className="font-semibold">Repair</span> tab and press{" "}
            <span className="font-semibold">Start</span> to regenerate.
          </div>
        )}
      </div>
    </div>
  );
}
