// Extracts a small set of header fields from raw PDB/mmCIF text for display
// in the Project Information panel. Intentionally regex-based — Mol*'s parsed
// model already exists for rendering, but accessing it from the project store
// layer would couple unrelated concerns.

export interface StructureHeader {
  pdbId?: string;
  title?: string;
  classification?: string;
  molecules?: string;
  organism?: string;
  experimentalMethod?: string;
  resolution?: string;
  spaceGroup?: string;
  rWork?: string;
  rFree?: string;
  depositionDate?: string;
  releaseDate?: string;
  keywords?: string;
  authors?: string[];
}

// Trim, drop blanks, and de-duplicate while preserving order.
function dedupe(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values) {
    const v = raw.trim();
    if (v && !seen.has(v)) {
      seen.add(v);
      out.push(v);
    }
  }
  return out;
}

function detectFormat(content: string): "pdb" | "mmcif" | "unknown" {
  const head = content.trimStart().slice(0, 200);
  if (
    head.startsWith("data_") ||
    /\n_[A-Za-z]/.test(head) ||
    head.startsWith("_")
  ) {
    return "mmcif";
  }
  if (
    head.startsWith("HEADER") ||
    head.startsWith("ATOM") ||
    head.startsWith("HETATM") ||
    head.startsWith("TITLE") ||
    head.startsWith("REMARK")
  ) {
    return "pdb";
  }
  return "unknown";
}

function unquote(value: string): string {
  const v = value.trim();
  if (
    (v.startsWith("'") && v.endsWith("'")) ||
    (v.startsWith('"') && v.endsWith('"'))
  ) {
    return v.slice(1, -1).trim();
  }
  if (v === "?" || v === "." || v === "") return "";
  return v;
}

// Match `_category.item  value` on a single line. Quoted values handled.
function matchSingleItem(content: string, key: string): string | undefined {
  const re = new RegExp(
    `(?:^|\\n)\\s*${key.replace(/\./g, "\\.")}\\s+([^\\n]+)`,
    "i"
  );
  const m = content.match(re);
  if (!m) return undefined;
  const value = unquote(m[1]);
  return value || undefined;
}

// Match a multi-line `;...;` value following a `_category.item` line.
function matchSemicolonBlock(content: string, key: string): string | undefined {
  const re = new RegExp(
    `(?:^|\\n)\\s*${key.replace(/\./g, "\\.")}\\s*\\n;\\s*([\\s\\S]*?)\\n;`,
    "i"
  );
  const m = content.match(re);
  if (!m) return undefined;
  const value = m[1].replace(/\s+/g, " ").trim();
  return value || undefined;
}

function getCifItem(content: string, key: string): string | undefined {
  return matchSingleItem(content, key) ?? matchSemicolonBlock(content, key);
}

// Tokenize a CIF line respecting single/double quotes.
function tokenizeCifLine(line: string): string[] {
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

// Extract values for a single column from a CIF loop_ block.
function extractLoopColumn(
  content: string,
  category: string,
  item: string
): string[] {
  const lines = content.split("\n");
  const results: string[] = [];
  const itemPath = `_${category}.${item}`.toLowerCase();
  const categoryPrefix = `_${category}.`.toLowerCase();

  let inHeader = false;
  let columns: string[] = [];
  let columnIndex = -1;

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const trimmed = raw.trim();

    if (trimmed === "loop_") {
      inHeader = true;
      columns = [];
      columnIndex = -1;
      continue;
    }

    if (inHeader && trimmed.startsWith("_")) {
      columns.push(trimmed.toLowerCase());
      continue;
    }

    if (inHeader && !trimmed.startsWith("_")) {
      // Header section finished — check this loop is the one we want.
      inHeader = false;
      if (!columns.some(c => c.startsWith(categoryPrefix))) {
        continue;
      }
      columnIndex = columns.indexOf(itemPath);
      if (columnIndex < 0) continue;
    }

    if (columnIndex < 0) continue;
    if (!trimmed || trimmed.startsWith("#") || trimmed === "loop_") {
      if (trimmed === "loop_") {
        // Re-enter header parsing for the next loop.
        inHeader = true;
        columns = [];
        columnIndex = -1;
      }
      continue;
    }
    if (trimmed.startsWith("_")) {
      // New category started — stop reading this loop.
      columnIndex = -1;
      continue;
    }
    if (trimmed === ";" || trimmed.startsWith(";")) {
      // Semicolon block — skip until closing ;.
      i++;
      while (i < lines.length && lines[i].trim() !== ";") i++;
      continue;
    }

    const tokens = tokenizeCifLine(trimmed);
    if (tokens.length === columns.length) {
      const value = unquote(tokens[columnIndex]);
      if (value) results.push(value);
    }
  }

  return results;
}

function parseMmcif(content: string): StructureHeader {
  const header: StructureHeader = {};

  header.pdbId = getCifItem(content, "_entry.id")?.toUpperCase();
  header.title = getCifItem(content, "_struct.title");
  header.keywords =
    getCifItem(content, "_struct_keywords.pdbx_keywords") ??
    getCifItem(content, "_struct_keywords.text");
  header.depositionDate = getCifItem(
    content,
    "_pdbx_database_status.recvd_initial_deposition_date"
  );
  // Release date = first entry of the revision history (initial release).
  const revDates = extractLoopColumn(
    content,
    "pdbx_audit_revision_history",
    "revision_date"
  );
  header.releaseDate =
    revDates[0] ??
    getCifItem(content, "_pdbx_audit_revision_history.revision_date");

  // Molecule / entity descriptions (one per polymer entity).
  const entityDescs = dedupe(
    extractLoopColumn(content, "entity", "pdbx_description")
  );
  header.molecules =
    entityDescs.length > 0
      ? entityDescs.join(", ")
      : getCifItem(content, "_entity.pdbx_description");

  // Source organism — may live in several source categories.
  const organisms = dedupe([
    ...extractLoopColumn(
      content,
      "entity_src_gen",
      "pdbx_gene_src_scientific_name"
    ),
    ...extractLoopColumn(content, "entity_src_nat", "pdbx_organism_scientific"),
    ...extractLoopColumn(content, "pdbx_entity_src_syn", "organism_scientific")
  ]);
  if (organisms.length === 0) {
    const singleOrg =
      getCifItem(content, "_entity_src_gen.pdbx_gene_src_scientific_name") ??
      getCifItem(content, "_entity_src_nat.pdbx_organism_scientific");
    if (singleOrg) organisms.push(singleOrg);
  }
  if (organisms.length > 0) header.organism = organisms.join(", ");

  // Crystallographic space group and refinement R-factors.
  header.spaceGroup = getCifItem(content, "_symmetry.space_group_name_H-M");
  header.rWork = getCifItem(content, "_refine.ls_R_factor_R_work");
  header.rFree = getCifItem(content, "_refine.ls_R_factor_R_free");

  // Experimental method — may be a single item or a single-row loop.
  const exptlSingle = getCifItem(content, "_exptl.method");
  if (exptlSingle) {
    header.experimentalMethod = exptlSingle;
  } else {
    const methods = extractLoopColumn(content, "exptl", "method");
    if (methods.length > 0) header.experimentalMethod = methods.join(", ");
  }

  // Resolution — try multiple sources.
  const refineRes = getCifItem(content, "_refine.ls_d_res_high");
  const reflnsRes = getCifItem(content, "_reflns.d_resolution_high");
  const emRes = getCifItem(content, "_em_3d_reconstruction.resolution");
  const resolution = refineRes ?? reflnsRes ?? emRes;
  if (resolution) header.resolution = resolution;

  // Authors — usually a loop on _audit_author.name.
  const authorLoop = extractLoopColumn(content, "audit_author", "name");
  if (authorLoop.length > 0) header.authors = authorLoop;
  else {
    const single = getCifItem(content, "_audit_author.name");
    if (single) header.authors = [single];
  }

  // Trim empties.
  for (const key of Object.keys(header) as (keyof StructureHeader)[]) {
    const v = header[key];
    if (typeof v === "string" && !v) delete header[key];
    if (Array.isArray(v) && v.length === 0) delete header[key];
  }
  return header;
}

function parsePdb(content: string): StructureHeader {
  const header: StructureHeader = {};
  const lines = content.split("\n");

  const collect = (record: string): string => {
    const parts: string[] = [];
    for (const line of lines) {
      if (line.startsWith(record)) {
        // Records use columns 11–80 for payload (1-indexed).
        parts.push(line.slice(10, 80).trim());
      }
    }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };

  for (const line of lines) {
    if (line.startsWith("HEADER")) {
      // Columns: classification (11-50), depDate (51-59), idCode (63-66)
      const classification = line.slice(10, 50).trim();
      const depDate = line.slice(50, 59).trim();
      const idCode = line.slice(62, 66).trim();
      if (classification) header.classification = classification;
      if (depDate) header.depositionDate = depDate;
      if (idCode) header.pdbId = idCode.toUpperCase();
      break;
    }
  }

  const title = collect("TITLE");
  if (title) header.title = title;

  const expdta = collect("EXPDTA");
  if (expdta) header.experimentalMethod = expdta;

  const keywords = collect("KEYWDS");
  if (keywords) header.keywords = keywords;

  // REMARK 2 RESOLUTION.    2.10 ANGSTROMS.
  for (const line of lines) {
    if (line.startsWith("REMARK   2 RESOLUTION.")) {
      const m = line.match(/RESOLUTION\.\s+([\d.]+)/);
      if (m) {
        header.resolution = m[1];
        break;
      }
    }
  }

  const authorLine = collect("AUTHOR");
  if (authorLine) {
    header.authors = authorLine
      .split(",")
      .map(s => s.trim())
      .filter(Boolean);
  }

  // COMPND: MOLECULE: <name>; (one per entity)
  const compnd = collect("COMPND");
  const molecules = dedupe(
    [...compnd.matchAll(/MOLECULE:\s*([^;]+)/gi)].map(m => m[1])
  );
  if (molecules.length > 0) header.molecules = molecules.join(", ");

  // SOURCE: ORGANISM_SCIENTIFIC: <name>;
  const source = collect("SOURCE");
  const organisms = dedupe(
    [...source.matchAll(/ORGANISM_SCIENTIFIC:\s*([^;]+)/gi)].map(m => m[1])
  );
  if (organisms.length > 0) header.organism = organisms.join(", ");

  // Release date: original release is REVDAT with the highest modNum ("1").
  for (const line of lines) {
    if (/^REVDAT\s+1\s/.test(line)) {
      const d = line.slice(13, 22).trim();
      if (d) header.releaseDate = d;
      break;
    }
  }

  // CRYST1: space group in columns 56–66.
  for (const line of lines) {
    if (line.startsWith("CRYST1")) {
      const sg = line.slice(55, 66).trim();
      if (sg) header.spaceGroup = sg;
      break;
    }
  }

  // REMARK 3 refinement R-factors (best-effort).
  for (const line of lines) {
    if (!line.startsWith("REMARK   3")) continue;
    if (/R VALUE\s+\(WORKING SET\)\s*:/.test(line)) {
      const m = line.match(/:\s*([\d.]+)/);
      if (m) header.rWork = m[1];
    } else if (
      /FREE R VALUE\s*:/.test(line) &&
      !/TEST|ERROR|SET|BIN/i.test(line)
    ) {
      const m = line.match(/:\s*([\d.]+)/);
      if (m) header.rFree = m[1];
    }
  }

  return header;
}

export function parseStructureHeader(
  content: string | null | undefined
): StructureHeader | null {
  if (!content) return null;
  const format = detectFormat(content);
  if (format === "mmcif") return parseMmcif(content);
  if (format === "pdb") return parsePdb(content);
  return null;
}
