// useMissingRegionDetection.ts - Missing Region 감지 로직 (Mol* Structure API 기반)
import { useEffect } from "react";
import { useAtom } from "jotai";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import {
  missingRegionsDetectedAtom,
  missingRegionDetectionLoadingAtom,
  missingRegionDetectionErrorAtom,
  repairSegmentsAtom,
  selectedSegmentIdsAtom
} from "../../store/repair-atoms";
import type { MissingRegionInfo, RepairSegment } from "../../types";
import { bus } from "../../lib/event-bus";
import {
  Structure,
  StructureElement,
  Unit
} from "molstar/lib/mol-model/structure";
import { StructureProperties } from "molstar/lib/mol-model/structure/structure/properties";

// Standard amino acid backbone atoms
const BACKBONE_ATOMS = new Set(["N", "CA", "C", "O"]);

// Nucleotide sugar-phosphate backbone atoms
// 핵산의 핵심 골격 원자들
const NUCLEOTIDE_SUGAR_RING_ATOMS = new Set([
  "C1'", // 1' carbon (anomeric carbon)
  "C2'", // 2' carbon
  "C3'", // 3' carbon
  "C4'", // 4' carbon
  "O4'", // 4' oxygen (ether in ring)
  "C5'", // 5' carbon
  "O5'" // 5' oxygen
]);

// Nucleotide backbone atoms (sugar-phosphate)
// OP1/OP2와 O1P/O2P 둘 다 허용 (포맷 호환성)
// 말단/부분 모델에서 P/인산 원자가 없을 수 있으므로 필수로 보지 않음
const NUCLEOTIDE_BACKBONE_ATOMS = new Set([
  "P", // Phosphate (인산)
  "O1P", // Phosphate oxygen (old naming)
  "O2P", // Phosphate oxygen (old naming)
  "OP1", // Phosphate oxygen (modern naming)
  "OP2", // Phosphate oxygen (modern naming)
  "O5'", // 5' oxygen
  "C5'", // 5' carbon
  "C4'", // 4' carbon
  "O4'", // 4' oxygen
  "C3'", // 3' carbon
  "O3'", // 3' oxygen
  "C2'", // 2' carbon
  "C1'" // 1' carbon
]);

interface ResidueData {
  chainId: string; // auth_asym_id
  authSeqId: number; // auth_seq_id
  insCode: string; // pdbx_PDB_ins_code
  resId: number; // label_seq_id
  resName: string;
  resType: "protein" | "dna" | "rna" | "unknown"; // 잔기 타입
  atomNames: Set<string>;
}

// Protein: standard amino acid atom definitions (non-hydrogen atoms only)
const STANDARD_AA_ATOMS: Record<string, string[]> = {
  ALA: ["N", "CA", "C", "O", "CB"],
  ARG: ["N", "CA", "C", "O", "CB", "CG", "CD", "NE", "CZ", "NH1", "NH2"],
  ASN: ["N", "CA", "C", "O", "CB", "CG", "OD1", "ND2"],
  ASP: ["N", "CA", "C", "O", "CB", "CG", "OD1", "OD2"],
  CYS: ["N", "CA", "C", "O", "CB", "SG"],
  GLN: ["N", "CA", "C", "O", "CB", "CG", "CD", "OE1", "NE2"],
  GLU: ["N", "CA", "C", "O", "CB", "CG", "CD", "OE1", "OE2"],
  GLY: ["N", "CA", "C", "O"],
  HIS: ["N", "CA", "C", "O", "CB", "CG", "ND1", "CD2", "CE1", "NE2"],
  ILE: ["N", "CA", "C", "O", "CB", "CG1", "CG2", "CD1"],
  LEU: ["N", "CA", "C", "O", "CB", "CG", "CD1", "CD2"],
  LYS: ["N", "CA", "C", "O", "CB", "CG", "CD", "CE", "NZ"],
  MET: ["N", "CA", "C", "O", "CB", "CG", "SD", "CE"],
  PHE: ["N", "CA", "C", "O", "CB", "CG", "CD1", "CD2", "CE1", "CE2", "CZ"],
  PRO: ["N", "CA", "C", "O", "CB", "CG", "CD"],
  SER: ["N", "CA", "C", "O", "CB", "OG"],
  THR: ["N", "CA", "C", "O", "CB", "OG1", "CG2"],
  TRP: [
    "N",
    "CA",
    "C",
    "O",
    "CB",
    "CG",
    "CD1",
    "CD2",
    "NE1",
    "CE2",
    "CE3",
    "CZ2",
    "CZ3",
    "CH2"
  ],
  TYR: [
    "N",
    "CA",
    "C",
    "O",
    "CB",
    "CG",
    "CD1",
    "CD2",
    "CE1",
    "CE2",
    "CZ",
    "OH"
  ],
  VAL: ["N", "CA", "C", "O", "CB", "CG1", "CG2"]
};

// DNA nucleotide atoms (standard PDB names)
// ⚠️ 인산 원자 이름 이형 고려: O1P/O2P (구형) vs OP1/OP2 (현대)
// 실제 구조에서는 하나만 존재하지만, expected atoms 검사에서는 어느 것도 있으면 OK 처리
const DNA_NUCLEOTIDES: Record<string, string[]> = {
  DA: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "C1'",
    "N9",
    "C8",
    "N7",
    "C5",
    "C6",
    "N6",
    "N1",
    "C2",
    "N3",
    "C4"
    // 인산 원자는 제외 (O1P/O2P vs OP1/OP2 선택 사항, backbone 분석에서 별도 처리)
  ],
  DG: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "C1'",
    "N9",
    "C8",
    "N7",
    "C5",
    "C6",
    "O6",
    "N1",
    "C2",
    "N2",
    "N3",
    "C4"
  ],
  DC: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "C1'",
    "N1",
    "C2",
    "O2",
    "N3",
    "C4",
    "N4",
    "C5",
    "C6"
  ],
  DT: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "C1'",
    "N1",
    "C2",
    "O2",
    "N3",
    "C4",
    "O4",
    "C5",
    "C7",
    "C6"
    // 인산 원자 제외
  ]
};

// RNA nucleotide atoms
// ⚠️ RNA는 O2' (2'-hydroxyl) 포함
// 인산 원자 이름: O1P/O2P vs OP1/OP2 선택 사항
const RNA_NUCLEOTIDES: Record<string, string[]> = {
  A: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "O2'",
    "C1'",
    "N9",
    "C8",
    "N7",
    "C5",
    "C6",
    "N6",
    "N1",
    "C2",
    "N3",
    "C4"
    // 인산 원자 제외
  ],
  G: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "O2'",
    "C1'",
    "N9",
    "C8",
    "N7",
    "C5",
    "C6",
    "O6",
    "N1",
    "C2",
    "N2",
    "N3",
    "C4"
  ],
  C: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "O2'",
    "C1'",
    "N1",
    "C2",
    "O2",
    "N3",
    "C4",
    "N4",
    "C5",
    "C6"
    // 인산 원자 제외
  ],
  U: [
    "P",
    "O5'",
    "C5'",
    "C4'",
    "O4'",
    "C3'",
    "O3'",
    "C2'",
    "O2'",
    "C1'",
    "N1",
    "C2",
    "O2",
    "N3",
    "C4",
    "O4",
    "C5",
    "C6"
    // 인산 원자 제외
  ]
};

/**
 * Atom name 정규화: asterisk (*) → apostrophe (')
 * 구형 PDB에서 O5*, C5* 등이 들어올 수 있음
 */
function normalizeAtomName(atomName: string): string {
  return atomName.replace(/\*/g, "'");
}

/**
 * 설탕 링 원자 기반 핵산 판별
 * C1', C2', C3', C4', O4', C5', O5' 중 3개 이상 있으면 핵산으로 간주
 */
function isNucleotideByAtoms(atomNames: Set<string>): boolean {
  const ringHits = Array.from(NUCLEOTIDE_SUGAR_RING_ATOMS).filter(a =>
    atomNames.has(a)
  ).length;
  return ringHits >= 3;
}

/**
 * 보조 신호로 RNA vs DNA 구분
 * 1순위: O2' (RNA 고유)
 * 2순위: U (RNA), T/DT (DNA)
 * 3순위: D prefix (DA/DG/DC/DT → DNA)
 */
function rnaOrDnaByAuxSignals(
  compId: string,
  atomNames: Set<string>
): "dna" | "rna" | "unknown" {
  const comp = compId.toUpperCase();

  // 1순위: O2' (2'-hydroxyl) - RNA 강한 신호
  if (atomNames.has("O2'")) {
    return "rna";
  }

  // 2순위: 염기 특성
  if (comp === "U") return "rna"; // Uracil은 RNA
  if (comp === "T" || comp === "DT") return "dna"; // Thymine은 DNA

  // 3순위: D prefix
  if (comp === "DA" || comp === "DG" || comp === "DC" || comp === "DT") {
    return "dna";
  }

  return "unknown";
}

/**
 * Robust Residue Type 판별
 * 우선순위:
 * 1. Entity/Polymer Type (최우선)
 * 2. Protein backbone 패턴
 * 3. 설탕 링 원자 (핵산 판별)
 * 4. 보조 신호 (O2', U/T/D*)
 */
function getResidueTypeRobust(
  compId: string,
  atomNamesRaw: Set<string>,
  chainPolymerHint: "protein" | "dna" | "rna" | "unknown" = "unknown"
): "protein" | "dna" | "rna" | "unknown" {
  // 정규화: asterisk → apostrophe
  const atomNames = new Set<string>(
    Array.from(atomNamesRaw).map(a => normalizeAtomName(a))
  );

  // 1) Entity hint 우선 - chainPolymerHint를 신뢰
  // 이렇게 하면 incomplete/partial residue도 올바른 타입으로 분류됨
  if (chainPolymerHint !== "unknown") {
    return chainPolymerHint;
  }

  // 2) Protein backbone 신호 (완전한 백본이 있는 경우)
  const hasProteinBackbone = Array.from(BACKBONE_ATOMS).every(a =>
    atomNames.has(a)
  );
  if (hasProteinBackbone) {
    return "protein";
  }

  // 2-1) Protein backbone의 일부라도 있고 표준 아미노산이면 protein으로 분류
  // 이는 partial/incomplete residue를 처리하기 위함
  const hasAnyProteinBackbone = Array.from(BACKBONE_ATOMS).some(a =>
    atomNames.has(a)
  );
  if (hasAnyProteinBackbone) {
    const comp = compId.toUpperCase();
    const standardAA = [
      "ALA",
      "ARG",
      "ASN",
      "ASP",
      "CYS",
      "GLN",
      "GLU",
      "GLY",
      "HIS",
      "ILE",
      "LEU",
      "LYS",
      "MET",
      "PHE",
      "PRO",
      "SER",
      "THR",
      "TRP",
      "TYR",
      "VAL"
    ];
    if (standardAA.includes(comp)) {
      return "protein";
    }
  }

  // 3) 설탕 링 기반 핵산 판별
  if (isNucleotideByAtoms(atomNames)) {
    const nucType = rnaOrDnaByAuxSignals(compId, atomNames);
    if (nucType !== "unknown") {
      return nucType;
    }

    const comp = compId.toUpperCase();
    if (comp === "DT" || comp.startsWith("D")) {
      return "dna";
    }
    if (comp === "U") {
      return "rna";
    }

    return "dna";
  }

  return "unknown";
}
function threeToOne(three: string): string {
  const comp = three.toUpperCase();

  // Standard amino acids
  const aaMap: Record<string, string> = {
    ALA: "A",
    ARG: "R",
    ASN: "N",
    ASP: "D",
    CYS: "C",
    GLN: "Q",
    GLU: "E",
    GLY: "G",
    HIS: "H",
    ILE: "I",
    LEU: "L",
    LYS: "K",
    MET: "M",
    PHE: "F",
    PRO: "P",
    SER: "S",
    THR: "T",
    TRP: "W",
    TYR: "Y",
    VAL: "V"
  };

  if (comp in aaMap) {
    return aaMap[comp];
  }

  // DNA nucleotides
  const dnaMap: Record<string, string> = {
    DA: "A",
    DG: "G",
    DC: "C",
    DT: "T"
  };

  if (comp in dnaMap) {
    return dnaMap[comp];
  }

  // RNA nucleotides (only standard bases - modified forms return N)
  const rnaMap: Record<string, string> = {
    A: "A",
    G: "G",
    C: "C",
    U: "U",
    I: "I", // Inosine
    // With R prefix
    RA: "A",
    RG: "G",
    RC: "C",
    RU: "U"
  };

  if (comp in rnaMap) {
    return rnaMap[comp];
  }

  // Unknown (including modified nucleotides like GTP, ATP, etc.) - return N
  return "N";
}

/**
 * Sequence Panel에서 Chain → Entity 매핑과 SEQRES 정보 추출
 * Ground Truth 데이터로 사용됨
 *
 * @param plugin Mol* PluginUIContext
 * @returns Chain ID → {entityId, sequence, compIds, polymerType} 매핑
 */
export function getSequencePanelData(plugin: PluginUIContext): Map<
  string,
  {
    entityId: string;
    sequence: string;
    compIds: string[];
    polymerType: "protein" | "dna" | "rna" | "unknown";
  }
> {
  console.log("[Sequence Panel GT] >>> getSequencePanelData called <<<");

  const chainData = new Map<
    string,
    {
      entityId: string;
      sequence: string;
      compIds: string[];
      polymerType: "protein" | "dna" | "rna" | "unknown";
    }
  >();

  try {
    const hierarchy = plugin.managers.structure.hierarchy;
    console.log(
      "[Sequence Panel GT] hierarchy:",
      hierarchy ? "exists" : "null"
    );

    const structures = hierarchy.current.structures;

    console.log(
      `[Sequence Panel GT] Starting - found ${structures.length} structure(s)`
    );

    for (const structRef of structures) {
      const structure = structRef.cell.obj?.data as Structure | undefined;
      if (!structure) {
        console.log("[Sequence Panel GT] Structure data is null, skipping");
        continue;
      }

      const model = structure.models[0];
      if (!model?.sequence) {
        console.log("[Sequence Panel GT] No model.sequence, skipping");
        continue;
      }

      console.log(
        `[Sequence Panel GT] Processing structure with ${structure.units.length} units`
      );

      // 1. Chain → Entity 매핑 수집 (Mol* StructureProperties.entity.key 사용)
      // Note: model.sequence.byEntityKey uses entity KEY (0, 1, 2, ...), not entity ID ("1", "2", ...)
      const chainToEntityKeyMap = new Map<string, number>();
      for (const unit of structure.units) {
        if (!Unit.isAtomic(unit)) continue;
        if (unit.elements.length === 0) continue;

        const loc = StructureElement.Location.create(
          structure,
          unit,
          unit.elements[0]
        );
        const chainId = StructureProperties.chain.auth_asym_id(loc);
        const entityKey = StructureProperties.entity.key(loc);
        const entityId = StructureProperties.entity.id(loc);

        if (!chainToEntityKeyMap.has(chainId)) {
          chainToEntityKeyMap.set(chainId, entityKey);
          console.log(
            `[Sequence Panel GT] Chain "${chainId}" → EntityKey=${entityKey}, EntityId="${entityId}" (direct mapping)`
          );
        }
      }

      // 2. 각 entity의 SEQRES와 polymer type 추출 (key는 entity key = number)
      const entityData = new Map<
        number,
        {
          sequence: string;
          compIds: string[];
          polymerType: "protein" | "dna" | "rna" | "unknown";
        }
      >();

      const entityKeys = Object.keys(model.sequence.byEntityKey);
      console.log(
        `[Sequence Panel GT] Available entity keys in model.sequence.byEntityKey: [${entityKeys.join(", ")}]`
      );
      console.log(
        `[Sequence Panel GT] Chain → EntityKey map: ${JSON.stringify(Object.fromEntries(chainToEntityKeyMap))}`
      );

      for (const [entityKeyStr, entitySeq] of Object.entries(
        model.sequence.byEntityKey
      )) {
        const entityKey = parseInt(entityKeyStr, 10);

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const seq = (entitySeq as any).sequence;
        if (!seq) {
          console.log(
            `[Sequence Panel GT] EntityKey ${entityKey}: no sequence`
          );
          continue;
        }

        const compIdArray = seq.compId?.toArray?.() || [];
        if (compIdArray.length === 0) {
          console.log(
            `[Sequence Panel GT] EntityKey ${entityKey}: no compId data`
          );
          continue;
        }

        const fullSequence = compIdArray.map(threeToOne).join("");

        // Determine polymer type from compIds (more reliable than _entity.type which just says "polymer")
        // DNA nucleotides: DA, DT, DG, DC, DU, etc.
        // RNA nucleotides: A, U, G, C (single letter or with R prefix)
        // Protein: standard 3-letter amino acid codes
        let polymerType: "protein" | "dna" | "rna" | "unknown" = "unknown";

        // prettier-ignore
        const dnaCompIds = new Set(["DA", "DT", "DG", "DC", "DU", "DI", "3DR"]);
        // prettier-ignore
        const rnaCompIds = new Set(["A", "U", "G", "C", "I", "RA", "RU", "RG", "RC"]);
        // prettier-ignore
        const proteinCompIds = new Set([
          "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
          "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
          "SEC", "PYL"
        ]);

        let dnaCount = 0;
        let rnaCount = 0;
        let proteinCount = 0;

        for (const compId of compIdArray) {
          const upperCompId = compId.toUpperCase();
          if (dnaCompIds.has(upperCompId)) {
            dnaCount++;
          } else if (rnaCompIds.has(upperCompId)) {
            rnaCount++;
          } else if (proteinCompIds.has(upperCompId)) {
            proteinCount++;
          }
        }

        // Determine type based on majority
        const total = dnaCount + rnaCount + proteinCount;
        if (total > 0) {
          if (dnaCount >= rnaCount && dnaCount >= proteinCount) {
            polymerType = "dna";
          } else if (rnaCount >= dnaCount && rnaCount >= proteinCount) {
            polymerType = "rna";
          } else {
            polymerType = "protein";
          }
        }

        console.log(
          `[Sequence Panel GT] EntityKey ${entityKey}: compId analysis -> dna=${dnaCount}, rna=${rnaCount}, protein=${proteinCount} => polymerType="${polymerType}"`
        );

        entityData.set(entityKey, {
          sequence: fullSequence,
          compIds: compIdArray,
          polymerType
        });

        console.log(
          `[Sequence Panel GT] EntityKey ${entityKey}: ${polymerType}, ${fullSequence.length} residues, seq=${fullSequence.substring(0, 20)}${fullSequence.length > 20 ? "..." : ""}`
        );
      }

      // 3. Chain → Entity 매칭 (직접 매핑 사용, entityKey 기반)
      console.log(
        `[Sequence Panel GT] Mapping ${chainToEntityKeyMap.size} chains to entities...`
      );

      for (const [chainId, entityKey] of chainToEntityKeyMap.entries()) {
        const eData = entityData.get(entityKey);

        if (eData) {
          chainData.set(chainId, {
            entityId: String(entityKey), // entityKey를 문자열로 변환하여 저장
            ...eData
          });
          console.log(
            `[Sequence Panel GT] ✓ Chain "${chainId}" → EntityKey ${entityKey}: ${eData.polymerType}, ${eData.sequence.length} residues, sequence: ${eData.sequence.substring(0, 20)}${eData.sequence.length > 20 ? "..." : ""}`
          );
        } else {
          console.warn(
            `[Sequence Panel GT] ✗ Chain "${chainId}": EntityKey ${entityKey} data not found!`
          );
        }
      }
    }
  } catch (e) {
    console.error("[Sequence Panel GT] Error extracting data:", e);
  }

  return chainData;
}

/**
 * Sequence Panel Plugin State에서 sequence 정보 logging
 */
function logSequencePanelState(plugin: PluginUIContext): void {
  try {
    console.log("[Sequence Panel] ========== PLUGIN STATE LOGGING ==========");

    // 1. Plugin managers에서 structure hierarchy 확인
    const hierarchy = plugin.managers.structure.hierarchy;
    const structures = hierarchy.current.structures;
    console.log("[Sequence Panel] Structures in hierarchy:", structures.length);

    // 2. 각 구조에서 model 정보 추출
    for (let i = 0; i < structures.length; i++) {
      const structRef = structures[i];
      const structure = structRef.cell.obj?.data as Structure | undefined;
      if (!structure) continue;

      console.log(`[Sequence Panel] ---- Structure ${i} ----`);
      console.log(`[Sequence Panel] Units:`, structure.units.length);
      console.log(`[Sequence Panel] Models:`, structure.models.length);

      // Model의 sequence 정보 확인
      const model = structure.models[0];
      if (model?.sequence) {
        console.log(`[Sequence Panel] Model sequence available`);
        console.log(
          `[Sequence Panel] Entity keys in model.sequence.byEntityKey:`,
          Object.keys(model.sequence.byEntityKey)
        );

        // 각 entity의 상세 정보
        for (const [entityId, entitySeq] of Object.entries(
          model.sequence.byEntityKey
        )) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const seq = (entitySeq as any).sequence;
          if (seq) {
            const compIdArray = seq.compId?.toArray?.() || [];
            // 전체 시퀀스를 1-letter code로 변환
            const fullSequence = compIdArray.map(threeToOne).join("");
            console.log(`[Sequence Panel]   Entity "${entityId}":`, {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              label: (entitySeq as any).label,
              length: compIdArray.length,
              sequence: fullSequence,
              seqObjKeys: Object.keys(seq).slice(0, 10)
            });
          } else {
            console.log(
              `[Sequence Panel]   Entity "${entityId}": no sequence object`
            );
          }
        }
      } else {
        console.log(`[Sequence Panel] No model.sequence`);
      }

      // 각 unit에서 chain 정보 추출
      const atomicUnits = structure.units.filter(u => Unit.isAtomic(u));
      console.log(`[Sequence Panel] Atomic units: ${atomicUnits.length}`);

      // 각 chain의 정보 수집
      const chainInfo = new Map<
        string,
        { entityId: string; residueCount: number }
      >();
      for (const unit of atomicUnits) {
        if (unit.elements.length === 0) continue;

        const loc = StructureElement.Location.create(
          structure,
          unit,
          unit.elements[0]
        );
        const chainId = StructureProperties.chain.auth_asym_id(loc);
        const entityId = StructureProperties.entity.id(loc);

        if (!chainInfo.has(chainId)) {
          // 이 chain의 residue count 계산
          const residueIds = new Set<number>();
          for (let j = 0; j < Math.min(1000, unit.elements.length); j++) {
            const l = StructureElement.Location.create(
              structure,
              unit,
              unit.elements[j]
            );
            residueIds.add(StructureProperties.residue.label_seq_id(l));
          }
          chainInfo.set(chainId, {
            entityId,
            residueCount: residueIds.size
          });
        }
      }

      console.log(`[Sequence Panel] Chains in structure:`);
      for (const [chainId, info] of chainInfo.entries()) {
        console.log(
          `[Sequence Panel]   Chain "${chainId}" (Entity "${info.entityId}"): ~${info.residueCount} residues`
        );
      }

      // 첫 atomic unit에서 샘플 residue 정보
      if (atomicUnits.length > 0) {
        const unit = atomicUnits[0];
        console.log(`[Sequence Panel] Sample residues from first unit:`);

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const sampleResidues = new Map<number, any>();
        for (
          let elemIdx = 0;
          elemIdx < Math.min(200, unit.elements.length);
          elemIdx++
        ) {
          const l = StructureElement.Location.create(
            structure,
            unit,
            unit.elements[elemIdx]
          );
          const resId = StructureProperties.residue.label_seq_id(l);
          const authSeqId = StructureProperties.residue.auth_seq_id(l);
          const insCode =
            StructureProperties.residue.pdbx_PDB_ins_code(l) || "";
          const compId = StructureProperties.atom.label_comp_id(l);
          const atomName = StructureProperties.atom.label_atom_id(l);

          if (!sampleResidues.has(resId)) {
            sampleResidues.set(resId, {
              labelSeqId: resId,
              authSeqId,
              insCode,
              compId,
              atoms: new Set<string>()
            });
          }
          sampleResidues.get(resId).atoms.add(atomName);
        }

        const sample = Array.from(sampleResidues.values()).slice(0, 10);
        for (const res of sample) {
          console.log(
            `[Sequence Panel]   label_seq_id=${res.labelSeqId}, auth_seq_id=${res.authSeqId}${res.insCode}, ${res.compId}, atoms=${Array.from(res.atoms).join(",")}`
          );
        }
      }
    }

    console.log("[Sequence Panel] ========== END LOGGING ==========\n");
  } catch (e) {
    console.error("[Sequence Panel] Error logging state:", e);
  }
}

export function useMissingRegionDetection(
  plugin: PluginUIContext | null,
  enabled: boolean = true
): void {
  const [, setMissingRegions] = useAtom(missingRegionsDetectedAtom);
  const [, setLoading] = useAtom(missingRegionDetectionLoadingAtom);
  const [, setError] = useAtom(missingRegionDetectionErrorAtom);
  const [, setRepairSegments] = useAtom(repairSegmentsAtom);
  const [, setSelectedSegmentIds] = useAtom(selectedSegmentIdsAtom);

  useEffect(() => {
    if (!plugin || !enabled) return;

    const detectMissingRegions = async (): Promise<void> => {
      setLoading(true);
      setError(null);

      try {
        // 0. Plugin sequence panel state logging 먼저 실행
        console.log(
          "[Missing Region Detection] ========== SEQUENCE PANEL STATE INFO =========="
        );
        logSequencePanelState(plugin);
        console.log(
          "[Missing Region Detection] ========== START GAP DETECTION ==========\n"
        );

        // 0-1. Sequence Panel Ground Truth 데이터 추출
        console.log(
          "[Missing Region Detection] Extracting Sequence Panel GT..."
        );
        const sequencePanelGT = getSequencePanelData(plugin);
        console.log(
          `[Missing Region Detection] ✓ Extracted ${sequencePanelGT.size} chains from Sequence Panel\n`
        );

        // 1. 구조 접근
        const structures =
          plugin.managers.structure.hierarchy.current.structures;
        if (!structures || structures.length === 0) {
          setError("No structure loaded");
          setLoading(false);
          return;
        }

        console.log("[Missing Region Detection] Starting analysis...");

        const detectedRegions: MissingRegionInfo[] = [];

        // 각 구조 분석
        for (const structureRef of structures) {
          const structure = structureRef.cell.obj?.data as
            | Structure
            | undefined;
          if (!structure) continue;

          // 체인별로 residue 정보 수집
          const chainResidues = new Map<string, ResidueData[]>();

          // Sequence Panel GT를 사용하여 chain별 SEQRES 및 매핑 생성
          const chainSequenceData = new Map<
            string,
            {
              sequence: string;
              compIds: string[];
              polymerType: "protein" | "dna" | "rna" | "unknown";
              mapping: Map<
                number,
                { authSeqId: number; insCode: string; compId: string }
              >;
            }
          >();

          // 각 chain별로 Sequence Panel GT 데이터 적용
          const processedChains = new Set<string>();
          for (const unit of structure.units) {
            if (!Unit.isAtomic(unit)) continue;
            if (unit.elements.length === 0) continue;

            const loc = StructureElement.Location.create(
              structure,
              unit,
              unit.elements[0]
            );
            const chainId = StructureProperties.chain.auth_asym_id(loc);

            if (!processedChains.has(chainId)) {
              processedChains.add(chainId);

              const gtData = sequencePanelGT.get(chainId);
              if (gtData) {
                console.log(
                  `[Missing Region Detection] ✓ Chain ${chainId} GT: ${gtData.polymerType}, ${gtData.sequence.length} residues`
                );

                // 실제 구조에서 label_seq_id → auth_seq_id 매핑 생성
                const mapping = new Map<
                  number,
                  { authSeqId: number; insCode: string; compId: string }
                >();

                // 이 chain의 모든 residue를 순회하며 매핑 생성
                for (let i = 0; i < unit.elements.length; i++) {
                  const l = StructureElement.Location.create(
                    structure,
                    unit,
                    unit.elements[i]
                  );
                  const labelSeqId =
                    StructureProperties.residue.label_seq_id(l);
                  const authSeqId = StructureProperties.residue.auth_seq_id(l);
                  const insCode =
                    StructureProperties.residue.pdbx_PDB_ins_code(l) || "";
                  const compId = StructureProperties.atom.label_comp_id(l);

                  if (!mapping.has(labelSeqId)) {
                    mapping.set(labelSeqId, { authSeqId, insCode, compId });
                  }
                }

                chainSequenceData.set(chainId, {
                  sequence: gtData.sequence,
                  compIds: gtData.compIds,
                  polymerType: gtData.polymerType,
                  mapping
                });
              } else {
                console.warn(
                  `[Missing Region Detection] ✗ No GT data for chain ${chainId}`
                );
              }
            }
          }

          // Location 객체를 재사용하여 성능 향상
          const location = StructureElement.Location.create(structure);

          for (const unit of structure.units) {
            // Atomic unit만 처리
            if (!Unit.isAtomic(unit)) continue;

            const { elements } = unit;

            // 각 원자를 순회하면서 residue별로 그룹화
            for (let i = 0; i < elements.length; i++) {
              const elementIndex = elements[i];
              location.unit = unit;
              location.element = elementIndex;

              // StructureProperties를 사용하여 residue 정보 추출
              const chainId = StructureProperties.chain.auth_asym_id(location);
              const resId = StructureProperties.residue.label_seq_id(location);
              const authSeqId =
                StructureProperties.residue.auth_seq_id(location);
              const insCode =
                StructureProperties.residue.pdbx_PDB_ins_code(location) || "";
              const resName = StructureProperties.atom.label_comp_id(location);
              const atomName = StructureProperties.atom.label_atom_id(location);

              if (!chainResidues.has(chainId)) {
                chainResidues.set(chainId, []);
              }

              const residues = chainResidues.get(chainId)!;
              // Use both authSeqId and insCode for unique identification
              let residueData = residues.find(
                r =>
                  r.chainId === chainId &&
                  r.authSeqId === authSeqId &&
                  r.insCode === insCode
              );

              if (!residueData) {
                // 초기 타입은 일단 "unknown"으로 설정
                // 나중에 모든 atoms 수집 후 재판별
                residueData = {
                  chainId,
                  resId,
                  authSeqId,
                  insCode,
                  resName,
                  resType: "unknown", // 임시 값
                  atomNames: new Set<string>()
                };
                residues.push(residueData);
              }

              // atom 추가
              residueData.atomNames.add(atomName);
            }
          }

          // 각 체인 분석
          for (const [chainId, residues] of chainResidues.entries()) {
            // auth_seq_id로 정렬 (insertion code 고려)
            residues.sort((a, b) => {
              if (a.authSeqId !== b.authSeqId) return a.authSeqId - b.authSeqId;
              return a.insCode.localeCompare(b.insCode);
            });

            // 해당 chain의 GT sequence 데이터 가져오기
            const seqData = chainSequenceData.get(chainId);

            // 1️⃣ 체인의 polymer type은 GT 데이터에서 가져옴
            const chainPolymerType = seqData?.polymerType ?? "unknown";

            console.log(
              `[Missing Region Detection] Chain ${chainId} polymer type: ${chainPolymerType} (from GT)`
            );

            // 2️⃣ 이제 residue type을 다시 보정 (polymer type 정보 활용)
            // residue data를 현재 정보로 업데이트
            for (const residue of residues) {
              // 이미 수집된 atomNames를 사용하여 residue type을 정확히 재판별
              residue.resType = getResidueTypeRobust(
                residue.resName,
                residue.atomNames,
                chainPolymerType
              );
            }

            // Chain의 residue 타입 분류
            const residueTypes = new Map<string, number>();
            for (const res of residues) {
              const typeCount = residueTypes.get(res.resType) ?? 0;
              residueTypes.set(res.resType, typeCount + 1);
            }
            const typeInfo = Array.from(residueTypes.entries())
              .map(([type, count]) => `${type}: ${count}`)
              .join(", ");

            console.log(
              `[Missing Region Detection] Chain ${chainId}: ${residues.length} residues (${typeInfo}), SEQRES length: ${seqData?.sequence.length || "N/A"}`
            );

            // 0. N-terminal 및 C-terminal missing regions 검사 (SEQRES 기반)
            // 중요: 실제 구조의 첫/마지막 residue와 SEQRES를 비교하여 terminal gap만 검출
            if (seqData && residues.length > 0) {
              const firstResId = residues[0].resId;
              const seqresLength = seqData.sequence.length;

              // N-terminal missing region (1부터 firstResId 전까지)
              // SEQRES가 1부터 시작하고, 실제 구조가 1보다 큰 resId에서 시작하는 경우
              if (firstResId > 1) {
                const nTermGap = firstResId - 1;
                const nTermSequence = seqData.sequence.substring(
                  0,
                  firstResId - 1
                );

                // N-terminal의 authSeqId는 SEQRES에서 알 수 없으므로
                // label_seq_id 범위를 authSeqId로도 사용 (UI 표시용)
                const regionInfo: MissingRegionInfo = {
                  regionId: `chain_${chainId}_nterm_1_${firstResId - 1}`,
                  chainId,
                  startResId: 1,
                  endResId: firstResId - 1,
                  startAuthSeqId: 1, // label_seq_id와 동일하게
                  endAuthSeqId: firstResId - 1, // label_seq_id와 동일하게
                  regionLength: nTermGap,
                  regionType: "complete",
                  terminalType: "nterm",
                  sequence: nTermSequence,
                  sequenceKnown: true
                };
                detectedRegions.push(regionInfo);
                console.log(
                  `  ✗ [N-terminal] Missing ${nTermGap} residues (label_seq_id 1-${firstResId - 1}) before ${residues[0].resName}${residues[0].authSeqId}${residues[0].insCode} [SEQRES: ${nTermSequence}]`
                );
              }

              // C-terminal missing region 검사
              // SEQRES mapping을 사용하여 실제 존재하는 가장 큰 label_seq_id 확인
              // mapping에 있는 최대 label_seq_id와 SEQRES 길이 비교
              const maxMappedResId = Math.max(
                ...Array.from(seqData.mapping.keys())
              );

              if (maxMappedResId < seqresLength) {
                const cTermGap = seqresLength - maxMappedResId;
                const cTermSequence =
                  seqData.sequence.substring(maxMappedResId);

                // C-terminal gap의 시작점을 찾기 위해 가장 마지막 존재하는 residue 찾기
                const lastMappedInfo = seqData.mapping.get(maxMappedResId);
                if (lastMappedInfo) {
                  // C-terminal의 authSeqId는 SEQRES에서 알 수 없으므로
                  // label_seq_id 범위를 authSeqId로도 사용 (UI 표시용)
                  const regionInfo: MissingRegionInfo = {
                    regionId: `chain_${chainId}_cterm_${maxMappedResId + 1}_${seqresLength}`,
                    chainId,
                    startResId: maxMappedResId + 1,
                    endResId: seqresLength,
                    startAuthSeqId: maxMappedResId + 1, // label_seq_id와 동일하게
                    endAuthSeqId: seqresLength, // label_seq_id와 동일하게
                    regionLength: cTermGap,
                    regionType: "complete",
                    terminalType: "cterm",
                    sequence: cTermSequence,
                    sequenceKnown: true
                  };
                  detectedRegions.push(regionInfo);
                  console.log(
                    `  ✗ [C-terminal] Missing ${cTermGap} residues (label_seq_id ${maxMappedResId + 1}-${seqresLength}) after label_seq_id=${maxMappedResId} (auth_seq_id=${lastMappedInfo.authSeqId}) [SEQRES: ${cTermSequence}]`
                  );
                }
              }
            }

            // 1. Missing residues 찾기 (sequence gaps based on label_seq_id)
            for (let i = 0; i < residues.length - 1; i++) {
              const curr = residues[i];
              const next = residues[i + 1];
              const gap = next.resId - curr.resId - 1;

              if (gap > 0) {
                const currDisplay = `${curr.authSeqId}${curr.insCode}`;
                const nextDisplay = `${next.authSeqId}${next.insCode}`;

                // SEQRES에서 gap 구간의 서열 추출 (label_seq_id 기반, 1-indexed)
                let gapSequence: string | undefined;
                let sequenceKnown = false;

                if (seqData && curr.resId > 0 && next.resId > 0) {
                  try {
                    // label_seq_id는 1-based이므로 배열 인덱스는 -1
                    const startIdx = curr.resId; // curr 다음부터
                    const endIdx = next.resId - 1; // next 이전까지

                    if (
                      startIdx >= 0 &&
                      endIdx < seqData.sequence.length &&
                      startIdx < endIdx
                    ) {
                      gapSequence = seqData.sequence.substring(
                        startIdx,
                        endIdx
                      );
                      sequenceKnown = true;
                    } else {
                      // Index out of range - fallback으로 진행
                      console.debug(
                        `    Index out of range: startIdx=${startIdx}, endIdx=${endIdx}, length=${seqData.sequence.length}`
                      );
                    }
                  } catch (e) {
                    console.debug(`    Failed to extract sequence:`, e);
                  }
                }

                // Complete gap는 항상 SEQRES에서 가져올 수 있으므로,
                // 없으면 label_seq_id 범위를 기반으로라도 시퀀스를 표시
                if (!gapSequence && seqData) {
                  // SEQRES에서 sequence 정보 재추출 시도
                  // gap 구간: (curr.resId + 1) ~ (next.resId - 1)
                  const gapStart = curr.resId + 1;
                  const gapEnd = next.resId - 1;
                  const gapCount = gapEnd - gapStart + 1;

                  if (
                    gapCount > 0 &&
                    gapStart - 1 >= 0 &&
                    gapEnd - 1 < seqData.sequence.length
                  ) {
                    try {
                      gapSequence = seqData.sequence.substring(
                        gapStart - 1,
                        gapEnd
                      );
                      sequenceKnown = true;
                    } catch (e) {
                      console.debug(`    Failed to extract from SEQRES:`, e);
                    }
                  } else {
                    console.log(
                      `    ✗ Fallback out of range: start-1=${gapStart - 1}, end-1=${gapEnd - 1}, length=${seqData.sequence.length}`
                    );
                  }
                }
                const regionInfo: MissingRegionInfo = {
                  regionId: `chain_${chainId}_gap_${curr.resId + 1}_${next.resId - 1}`,
                  chainId,
                  startResId: curr.resId + 1,
                  endResId: next.resId - 1,
                  startAuthSeqId: curr.authSeqId,
                  endAuthSeqId: next.authSeqId,
                  insertionCode: curr.insCode, // Gap 시작점의 insertion code
                  endInsertionCode: next.insCode, // Gap 끝점의 insertion code
                  regionLength: gap,
                  regionType: "complete",
                  terminalType: "internal",
                  sequence: gapSequence,
                  sequenceKnown
                };
                detectedRegions.push(regionInfo);
                console.log(
                  `  ✗ [${curr.resType}→${next.resType}] Gap: between ${curr.resName}${currDisplay} and ${next.resName}${nextDisplay} (${gap} residues missing)${sequenceKnown ? " [SEQRES]" : " [no SEQRES]"}`
                );
              }
            }

            // 2. Missing atoms 찾기 (partial residues)
            for (
              let residueIdx = 0;
              residueIdx < residues.length;
              residueIdx++
            ) {
              const residue = residues[residueIdx];
              let expectedAtoms: string[] | undefined;
              let backboneAtoms: Set<string> = new Set();
              let residueCategory = "unknown";

              // Residue 타입별로 expected atoms 결정
              if (residue.resType === "protein") {
                expectedAtoms = STANDARD_AA_ATOMS[residue.resName];
                backboneAtoms = BACKBONE_ATOMS;
                residueCategory = "protein";
              } else if (residue.resType === "dna") {
                expectedAtoms = DNA_NUCLEOTIDES[residue.resName];
                backboneAtoms = NUCLEOTIDE_BACKBONE_ATOMS;
                residueCategory = "DNA";
              } else if (residue.resType === "rna") {
                expectedAtoms = RNA_NUCLEOTIDES[residue.resName];
                backboneAtoms = NUCLEOTIDE_BACKBONE_ATOMS;
                residueCategory = "RNA";
              }

              if (!expectedAtoms) {
                // Non-standard residue (unknown, ligand, etc.)
                // 스킵 - 이미 체인의 polymer type으로 분류되므로 여기는 올 수 없음
                continue;
              }

              // 말단 여부 확인 (N-terminal: 첫 번째 잔기, C-terminal: 마지막 잔기)
              const isTerminal =
                residueIdx === 0 || residueIdx === residues.length - 1;

              // 말단 잔기는 P 원자가 없어도 정상 → expected atoms에서 제외
              let adjustedExpectedAtoms = expectedAtoms;
              if (isTerminal && expectedAtoms.includes("P")) {
                adjustedExpectedAtoms = expectedAtoms.filter(a => a !== "P");
              }

              const missingAtoms = adjustedExpectedAtoms.filter(
                atom => !residue.atomNames.has(atom)
              );

              if (missingAtoms.length > 0) {
                const resDisplay = `${residue.resName}${residue.authSeqId}${residue.insCode}`;

                // Backbone atoms 확인
                const hasBackbone = Array.from(backboneAtoms).every(atom =>
                  residue.atomNames.has(atom)
                );

                // Backbone만 있고 base/sidechain이 빠진 경우
                if (hasBackbone && missingAtoms.length > 0) {
                  const regionInfo: MissingRegionInfo = {
                    regionId: `chain_${chainId}_partial_${residue.authSeqId}${residue.insCode}`,
                    chainId,
                    startResId: residue.resId,
                    endResId: residue.resId,
                    startAuthSeqId: residue.authSeqId,
                    endAuthSeqId: residue.authSeqId,
                    insertionCode: residue.insCode || undefined,
                    regionLength: 1,
                    regionType: "partial",
                    missingAtoms,
                    sequence: residue.resName,
                    sequenceKnown: true
                  };
                  detectedRegions.push(regionInfo);
                  console.log(
                    `  ⚠ [${residueCategory}] Partial: ${resDisplay} missing ${missingAtoms.length} base/sidechain atoms: ${missingAtoms.join(", ")}`
                  );
                }
                // Backbone도 일부 빠진 경우 (더 심각) - 이것도 GapInfo로 추가
                else if (!hasBackbone) {
                  const missingBackboneAtoms = Array.from(backboneAtoms).filter(
                    atom => !residue.atomNames.has(atom)
                  );

                  const regionInfo: MissingRegionInfo = {
                    regionId: `chain_${chainId}_incomplete_${residue.authSeqId}${residue.insCode}`,
                    chainId,
                    startResId: residue.resId,
                    endResId: residue.resId,
                    startAuthSeqId: residue.authSeqId,
                    endAuthSeqId: residue.authSeqId,
                    insertionCode: residue.insCode || undefined,
                    regionLength: 1,
                    regionType: "partial",
                    missingAtoms,
                    sequence: residue.resName,
                    sequenceKnown: true
                  };
                  detectedRegions.push(regionInfo);
                  console.log(
                    `  ⚠⚠ [${residueCategory}] Incomplete backbone: ${resDisplay} missing backbone atoms: ${missingBackboneAtoms.join(", ")} and base/sidechain atoms: ${missingAtoms.filter(a => !missingBackboneAtoms.includes(a)).join(", ")}`
                  );
                }
              }
            }
          }
        }

        // 6. RepairSegment 생성 (모든 chain 포함, missing region이 없어도 포함)
        const segmentsByChain = new Map<string, MissingRegionInfo[]>();
        for (const region of detectedRegions) {
          const existing = segmentsByChain.get(region.chainId) ?? [];
          existing.push(region);
          segmentsByChain.set(region.chainId, existing);
        }

        // 모든 chain에 대해 segment 생성 (missing region이 없어도 포함)
        const allChainIds = new Set<string>();
        // Sequence Panel에서 모든 chain ID 수집
        for (const chainId of sequencePanelGT.keys()) {
          allChainIds.add(chainId);
        }
        // Missing region이 있는 chain도 추가
        for (const chainId of segmentsByChain.keys()) {
          allChainIds.add(chainId);
        }

        const repairSegments: RepairSegment[] = [];
        const allSegmentIds: string[] = [];
        let segmentIndex = 0;

        for (const chainId of Array.from(allChainIds).sort()) {
          const regions = segmentsByChain.get(chainId) ?? [];
          const segment: RepairSegment = {
            segmentId: `segment_${segmentIndex++}`,
            missingRegions: regions,
            chainIds: [chainId], // 여러 체인을 배열로 저장
            repairType:
              regions.length === 0
                ? "full" // missing region이 없으면 full로 설정
                : regions.every(r => r.regionType === "partial")
                  ? "sidechain"
                  : "full",
            contextRadius: 6.0, // Å
            autoGenerated: true,
            needsSequenceInput: regions.some(r => !r.sequenceKnown)
          };
          repairSegments.push(segment);
          allSegmentIds.push(segment.segmentId); // 모든 segment ID 수집
        }

        console.log(
          `[Missing Region Detection] Found ${detectedRegions.length} regions, ${repairSegments.length} segments (including ${repairSegments.length - segmentsByChain.size} chains without missing regions)`
        );

        setMissingRegions(detectedRegions);
        setRepairSegments(repairSegments);

        // 모든 segment를 기본적으로 선택
        setSelectedSegmentIds(allSegmentIds);

        // 이벤트 버스로 다른 컴포넌트에 알림
        bus.emit("repair:missing-regions-ready", repairSegments);
      } catch (error) {
        console.error("[Missing Region Detection] Error:", error);
        setError(
          error instanceof Error ? error.message : "Unknown error occurred"
        );
      } finally {
        setLoading(false);
      }
    };

    // Listen for structure representations ready event
    const handleRepresentationsReady = (): void => {
      void detectMissingRegions();
    };

    bus.on("structure:representations-ready", handleRepresentationsReady);

    // Also check if structure is already loaded (for cases where event was missed)
    const structures = plugin.managers.structure.hierarchy.current.structures;
    if (structures && structures.length > 0) {
      // Structure already exists, run detection immediately
      console.log(
        "[Missing Region Detection] Structure already loaded, running analysis..."
      );
      void detectMissingRegions();
    }

    return () => {
      bus.off("structure:representations-ready", handleRepresentationsReady);
    };
  }, [
    plugin,
    enabled,
    setMissingRegions,
    setLoading,
    setError,
    setRepairSegments,
    setSelectedSegmentIds
  ]);
}
