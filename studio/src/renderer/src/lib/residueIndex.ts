// residueIndex.ts - O(1) residue -> loci lookup for a loaded structure.
//
// Locating a residue by scanning every atom of every unit is O(atoms) per
// lookup. Gap visualisation does that up to 62 times per gap (both boundaries,
// each retrying 5 offsets x 6 insertion codes), so the cost grows as
// gaps x atoms and freezes the UI on large, gap-rich targets. Building one
// index per structure collapses every lookup to a map read.
import {
  Structure,
  StructureElement,
  Unit
} from "molstar/lib/mol-model/structure";
import { StructureProperties } from "molstar/lib/mol-model/structure/structure/properties";
import { OrderedSet } from "molstar/lib/mol-data/int";

interface ResidueEntry {
  unit: Unit.Atomic;
  indices: StructureElement.UnitIndex[];
}

interface ResidueIndex {
  /** `${authChainId}|${authSeqId}|${insCode}` -> elements of the first matching unit */
  byAuth: Map<string, ResidueEntry>;
  /** `${authChainId}|${labelSeqId}` -> elements of the first matching unit */
  byLabel: Map<string, ResidueEntry>;
}

// Structures are replaced wholesale on reload, so a weak cache never goes stale.
const cache = new WeakMap<Structure, ResidueIndex>();

function authKey(
  chainId: string,
  authSeqId: number,
  insCode: string | undefined
): string {
  return `${chainId}|${authSeqId}|${insCode || ""}`;
}

function labelKey(chainId: string, labelSeqId: number): string {
  return `${chainId}|${labelSeqId}`;
}

/**
 * Collect an entry, keeping only the elements of the first unit that matched.
 * This mirrors the previous scan, which returned as soon as one unit yielded
 * hits rather than merging elements across units.
 */
function push(
  map: Map<string, ResidueEntry>,
  key: string,
  unit: Unit.Atomic,
  index: number
): void {
  const existing = map.get(key);
  if (!existing) {
    map.set(key, { unit, indices: [index as StructureElement.UnitIndex] });
    return;
  }
  if (existing.unit !== unit) return;
  existing.indices.push(index as StructureElement.UnitIndex);
}

function build(structure: Structure): ResidueIndex {
  const byAuth = new Map<string, ResidueEntry>();
  const byLabel = new Map<string, ResidueEntry>();

  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;

    // One Location per unit, mutated in place — allocating one per atom is
    // what made the original scans so expensive.
    const loc = StructureElement.Location.create(structure, unit);

    for (let i = 0; i < unit.elements.length; i++) {
      loc.element = unit.elements[i];

      const chainId = StructureProperties.chain.auth_asym_id(loc);
      const authSeqId = StructureProperties.residue.auth_seq_id(loc);
      const insCode = StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";
      const labelSeqId = StructureProperties.residue.label_seq_id(loc);

      push(byAuth, authKey(chainId, authSeqId, insCode), unit, i);
      push(byLabel, labelKey(chainId, labelSeqId), unit, i);
    }
  }

  return { byAuth, byLabel };
}

function getIndex(structure: Structure): ResidueIndex {
  let index = cache.get(structure);
  if (!index) {
    index = build(structure);
    cache.set(structure, index);
  }
  return index;
}

function toLoci(
  structure: Structure,
  entry: ResidueEntry | undefined
): StructureElement.Loci | null {
  if (!entry || entry.indices.length === 0) return null;
  return StructureElement.Loci(structure, [
    {
      unit: entry.unit,
      // Element indices are collected in ascending order per unit.
      indices: OrderedSet.ofSortedArray(entry.indices)
    }
  ]);
}

/** Find a residue by auth_seq_id (+ insertion code). */
export function findResidueLoci(
  structure: Structure,
  chainId: string,
  authSeqId: number,
  insCode: string | undefined
): StructureElement.Loci | null {
  const index = getIndex(structure);
  return toLoci(
    structure,
    index.byAuth.get(authKey(chainId, authSeqId, insCode))
  );
}

/** Find a residue by label_seq_id. */
export function findResidueLociByLabelSeqId(
  structure: Structure,
  chainId: string,
  labelSeqId: number
): StructureElement.Loci | null {
  const index = getIndex(structure);
  return toLoci(structure, index.byLabel.get(labelKey(chainId, labelSeqId)));
}

/**
 * Find the residue at `seqId`, else the nearest one within 5 positions in
 * `direction`, trying common insertion codes at each offset.
 */
export function findNearbyResidueLoci(
  structure: Structure,
  chainId: string,
  seqId: number,
  insCode: string | undefined,
  direction: "before" | "after"
): StructureElement.Loci | null {
  const exact = findResidueLoci(structure, chainId, seqId, insCode);
  if (exact) return exact;

  const step = direction === "before" ? -1 : 1;

  for (let offset = 1; offset <= 5; offset++) {
    const nearbySeqId = seqId + step * offset;

    const plain = findResidueLoci(structure, chainId, nearbySeqId, undefined);
    if (plain) return plain;

    for (const tryInsCode of ["A", "B", "C", "D", "E"]) {
      const withIns = findResidueLoci(
        structure,
        chainId,
        nearbySeqId,
        tryInsCode
      );
      if (withIns) return withIns;
    }
  }

  return null;
}
