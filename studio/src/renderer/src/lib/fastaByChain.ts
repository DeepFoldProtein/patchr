// Parses a per-chain FASTA (">Chain A" headers, as produced by the UniProt
// reference loader and the inpainting run's custom-sequence path) into a
// chain id -> sequence map.
export function parseFastaByChain(fasta: string): Map<string, string> {
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
