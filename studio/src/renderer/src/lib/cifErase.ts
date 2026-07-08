// Removes selected residues' atoms from an mmCIF so the inpainting backend
// re-detects them as a missing region and regenerates ("erases") them. Mirrors
// the _atom_site loop parsing used by filterCifByChains in StructureUploadModal.
//
// Only mmCIF _atom_site loops are handled. For any other input the content is
// returned unchanged (with erased = 0) so callers can surface a clear message
// rather than silently corrupting the structure.

export interface ResidueKey {
  authSeqId: number;
  insCode: string; // "" when absent
}

export interface EraseResult {
  content: string;
  erasedAtoms: number;
  erasedResidues: number;
}

/**
 * Drop all _atom_site rows for `chainId` whose (auth_seq_id, ins_code) is in
 * `residues`. Returns the rewritten CIF and how much was removed.
 */
export function eraseResiduesFromCif(
  content: string,
  chainId: string,
  residues: ResidueKey[]
): EraseResult {
  const wanted = new Set(
    residues.map(r => `${r.authSeqId}|${normalizeIns(r.insCode)}`)
  );
  if (wanted.size === 0) {
    return { content, erasedAtoms: 0, erasedResidues: 0 };
  }

  const lines = content.split("\n");
  const out: string[] = [];

  let inAtomSite = false;
  let headersDone = false;
  const headers: string[] = [];
  let chainIdx = -1;
  let seqIdx = -1;
  let insIdx = -1;

  let erasedAtoms = 0;
  const erasedResidueKeys = new Set<string>();

  const rowMatches = (line: string): boolean => {
    const parts = line.trim().split(/\s+/);
    if (chainIdx < 0 || seqIdx < 0) return false;
    if (parts[chainIdx] !== chainId) return false;
    const seq = parts[seqIdx];
    const ins = insIdx >= 0 ? normalizeIns(parts[insIdx]) : "";
    const key = `${seq}|${ins}`;
    if (wanted.has(key)) {
      erasedAtoms++;
      erasedResidueKeys.add(key);
      return true;
    }
    return false;
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("_atom_site.")) {
      inAtomSite = true;
      headersDone = false;
      headers.push(trimmed.replace("_atom_site.", ""));
      out.push(line);
      continue;
    }

    if (inAtomSite && !headersDone && headers.length > 0) {
      if (!trimmed.startsWith("_")) {
        // First data row — resolve column indices once.
        headersDone = true;
        chainIdx = headers.indexOf("auth_asym_id");
        seqIdx = headers.indexOf("auth_seq_id");
        insIdx = headers.indexOf("pdbx_PDB_ins_code");
        if (!rowMatches(line)) out.push(line);
      } else {
        out.push(line);
      }
      continue;
    }

    if (
      inAtomSite &&
      headersDone &&
      trimmed &&
      !trimmed.startsWith("_") &&
      !trimmed.startsWith("#") &&
      !trimmed.startsWith("loop_")
    ) {
      if (!rowMatches(line)) out.push(line);
      continue;
    }

    if (
      inAtomSite &&
      (trimmed.startsWith("loop_") || trimmed.startsWith("#") || !trimmed)
    ) {
      inAtomSite = false;
      headersDone = false;
      headers.length = 0;
      chainIdx = seqIdx = insIdx = -1;
    }
    out.push(line);
  }

  return {
    content: out.join("\n"),
    erasedAtoms,
    erasedResidues: erasedResidueKeys.size
  };
}

// mmCIF uses "." or "?" for an absent insertion code.
function normalizeIns(ins: string | undefined): string {
  if (!ins || ins === "." || ins === "?") return "";
  return ins;
}
