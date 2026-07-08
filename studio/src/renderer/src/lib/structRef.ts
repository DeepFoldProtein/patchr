// Parses UniProt accessions per author chain from an mmCIF's _struct_ref /
// _struct_ref_seq categories, so the Sequence editor can prefill the UniProt id
// of the loaded structure before any network lookup. Handles both the loop form
// (multi-entity structures) and the single-row key/value form.

// Tokenize a whitespace-delimited CIF row honoring single/double quotes.
function tokenize(line: string): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === " " || ch === "\t") {
      i++;
      continue;
    }
    if (ch === "'" || ch === '"') {
      const end = line.indexOf(ch, i + 1);
      if (end === -1) {
        out.push(line.slice(i + 1));
        break;
      }
      out.push(line.slice(i + 1, end));
      i = end + 1;
      continue;
    }
    let j = i;
    while (j < line.length && line[j] !== " " && line[j] !== "\t") j++;
    out.push(line.slice(i, j));
    i = j;
  }
  return out;
}

function unquote(v: string): string {
  const t = v.trim();
  if (
    (t.startsWith("'") && t.endsWith("'")) ||
    (t.startsWith('"') && t.endsWith('"'))
  ) {
    return t.slice(1, -1).trim();
  }
  return t;
}

// Read all rows of a `_<category>.` block as objects keyed by item name.
// Supports the loop_ form and the single-row (one item per line) form.
function readCategory(
  content: string,
  category: string
): Record<string, string>[] {
  const prefix = `_${category}.`;
  const lines = content.split("\n");

  // --- loop form ---
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() !== "loop_") continue;
    const cols: string[] = [];
    let j = i + 1;
    while (j < lines.length && lines[j].trim().startsWith("_")) {
      cols.push(lines[j].trim());
      j++;
    }
    if (!cols.length || !cols[0].startsWith(prefix)) continue;
    const items = cols.map(c => c.slice(prefix.length));

    // Collect a flat token stream, honoring multi-line `;` text blocks (a value
    // that spans lines, e.g. pdbx_seq_one_letter_code), then chunk into rows.
    const tokens: string[] = [];
    let inText = false;
    let textBuf = "";
    for (; j < lines.length; j++) {
      const raw = lines[j];
      if (inText) {
        if (raw.startsWith(";")) {
          tokens.push(textBuf.trim());
          inText = false;
        } else {
          textBuf += (textBuf ? "\n" : "") + raw;
        }
        continue;
      }
      const t = raw.trim();
      if (raw.startsWith(";")) {
        inText = true;
        textBuf = raw.slice(1);
        continue;
      }
      if (!t) continue;
      if (t === "loop_" || t.startsWith("#") || t.startsWith("_")) break;
      tokens.push(...tokenize(t));
    }

    const rows: Record<string, string>[] = [];
    for (let k = 0; k + items.length <= tokens.length; k += items.length) {
      const row: Record<string, string> = {};
      items.forEach((it, idx) => (row[it] = unquote(tokens[k + idx])));
      rows.push(row);
    }
    if (rows.length) return rows;
  }

  // --- single-row form (`_category.item  value` lines) ---
  const single: Record<string, string> = {};
  const re = new RegExp(`^\\s*${prefix.replace(/\./g, "\\.")}(\\S+)\\s+(.+)$`);
  for (const line of lines) {
    const m = line.match(re);
    if (m) single[m[1]] = unquote(m[2]);
  }
  return Object.keys(single).length ? [single] : [];
}

export interface UniProtRef {
  accession: string;
  /** UniProt sequence position where the structure alignment begins. */
  dbBeg: number;
  /** UniProt sequence position where the structure alignment ends. */
  dbEnd: number;
  /** Author residue number aligned to dbBeg. */
  authBeg: number;
  /** Author residue number aligned to dbEnd. */
  authEnd: number;
}

function toInt(v: string | undefined): number | undefined {
  if (!v || v === "?" || v === ".") return undefined;
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : undefined;
}

/**
 * Map author chain id -> UniProt reference (accession + alignment offset),
 * from _struct_ref (db_name UNP) joined to _struct_ref_seq. Empty when absent.
 */
export function parseUniProtRefs(
  content: string | null | undefined
): Map<string, UniProtRef> {
  const result = new Map<string, UniProtRef>();
  if (!content) return result;

  const refs = readCategory(content, "struct_ref");
  const refIdToAcc = new Map<string, string>();
  for (const r of refs) {
    const db = (r["db_name"] || "").toUpperCase();
    const acc = r["pdbx_db_accession"] || r["db_code"] || "";
    if (db === "UNP" && acc && acc !== "?" && acc !== ".") {
      if (r["id"]) refIdToAcc.set(r["id"], acc);
    }
  }
  if (refIdToAcc.size === 0) return result;

  const refSeq = readCategory(content, "struct_ref_seq");
  for (const rs of refSeq) {
    const chain = rs["pdbx_strand_id"];
    const acc = rs["ref_id"] ? refIdToAcc.get(rs["ref_id"]) : undefined;
    if (!chain || !acc || result.has(chain)) continue;
    const dbBeg = toInt(rs["db_align_beg"]);
    const dbEnd = toInt(rs["db_align_end"]);
    const authBeg = toInt(rs["pdbx_auth_seq_align_beg"]);
    const authEnd = toInt(rs["pdbx_auth_seq_align_end"]);
    if (
      dbBeg === undefined ||
      dbEnd === undefined ||
      authBeg === undefined ||
      authEnd === undefined
    ) {
      // Accession known but no usable alignment — still record accession.
      result.set(chain, {
        accession: acc,
        dbBeg: 1,
        dbEnd: 0,
        authBeg: 1,
        authEnd: 0
      });
      continue;
    }
    result.set(chain, { accession: acc, dbBeg, dbEnd, authBeg, authEnd });
  }
  return result;
}

/** Convenience: author chain id -> UniProt accession only. */
export function parseUniProtByChain(
  content: string | null | undefined
): Map<string, string> {
  const out = new Map<string, string>();
  for (const [chain, ref] of parseUniProtRefs(content)) {
    out.set(chain, ref.accession);
  }
  return out;
}
