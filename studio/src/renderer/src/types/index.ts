// MaskSpec - 마스크 영역 정의
export interface MaskSpec {
  version: number;
  units: "residue" | "atom";
  include: Array<{
    chain: string;
    residues?: number[];
    atomIds?: number[];
  }>;
  exclude: Array<{
    chain: string;
    residues?: number[];
    atomIds?: number[];
  }>;
  fixed: Array<{
    chain: string;
    residues?: number[];
  }>;
  soft_shell_Ang: number;
}

// InpaintParams - 인페인팅 파라미터 (Boltz-Inpainting 기반)
export interface InpaintParams {
  seeds: number[]; // 생성할 시드 목록 (e.g., [42, 43, 44])
  temperature: number; // 생성 다양성 (0.0-2.0, 기본값: 1.0)
  confidence_threshold: number; // 신뢰도 필터링 (0.0-1.0, 기본값: 0.5)
}

// RunStatus - 실행 상태
export interface RunStatus {
  step: number;
  of: number;
  eta_s: number;
  running: boolean;
  message?: string;
  error?: string;
}

// MVS (MolViewSpec) - 뷰 상태
export interface MVS {
  version: string;
  _molviewspec_version?: string;
  nodes: MVSNode[];
  metadata?: {
    timestamp: string;
    description?: string;
    author?: string;
  };
}

export interface MVSNode {
  type:
    | "data"
    | "representation"
    | "shape"
    | "annotation"
    | "component"
    | "symmetry";
  id: string;
  params?: Record<string, unknown>;
  children?: MVSNode[];
}

// ProjectState - 프로젝트 전체 상태
export interface ProjectState {
  id: string;
  name: string;
  version: string;
  created: string;
  modified: string;
  structure?: {
    path: string;
    format: "pdb" | "cif" | "mmcif";
  };
  mask?: MaskSpec;
  inpaintParams?: InpaintParams;
  currentView?: MVS;
  history: ProjectHistoryEntry[];
}

export interface ProjectHistoryEntry {
  id: string;
  timestamp: string;
  type: "mask" | "inpaint" | "refine" | "import" | "export";
  description: string;
  data?: Record<string, unknown>;
}

// AppSession - 앱 세션 정보
export interface AppSession {
  port: number;
  token: string;
  version: string;
  backendReady: boolean;
}

// PreviewFrame - 프리뷰 프레임 (Boltz-Inpainting 결과)
export interface PreviewFrame {
  frameId: string; // "frame-0", "frame-1", ...
  frameIndex: number; // seed 인덱스
  totalFrames: number; // 총 seed 개수
  structure: ArrayBuffer; // PDB 데이터 (바이너리)
  confidence: number; // 0.0-1.0
  temperature: number; // 생성 시 사용된 temperature
  plddt_mean?: number; // pLDDT 평균값
  timestamp: number;
}

// PreviewState - 실시간 프리뷰 상태
export interface PreviewState {
  isRunning: boolean;
  progress: number; // 0-100 (시간 기반)
  elapsed_s: number; // 경과 시간
  remaining_s: number; // 남은 시간 (예상)
  currentFrame: PreviewFrame | null;
  frames: PreviewFrame[]; // 모든 생성된 프레임
  error: string | null;
  runId: string | null;
}

// ========================================
// Simulation-related types
// ========================================

export interface SimReadyRequest {
  job_id?: string;
  cif_path?: string;
  engine: "gromacs" | "amber" | "openmm";
  forcefield: string;
  water_model: string;
  ph: number;
  padding: number;
  ion_concentration: number;
  keep_water: boolean;
}

export interface MembraneRequest {
  job_id?: string;
  cif_path?: string;
  pdb_id?: string;
  lipid_type: string;
  engine: "gromacs" | "amber" | "openmm";
  forcefield: string;
  water_model: string;
  ph: number;
  padding: number;
  ion_concentration: number;
  skip_opm: boolean;
  center_z?: number;
}

export interface SimReadyResult {
  atom_count?: number;
  box_size?: [number, number, number];
  files?: string[];
  output_dir?: string;
  engine?: string;
  forcefield?: string;
  water_model?: string;
  n_waters?: number;
  n_ions?: { positive: number; negative: number };
  total_charge?: number;
}

export interface OpmInfo {
  pdb_id: string;
  thickness: number;
  tilt_angle: number;
  type: string;
  topology: string;
  family: string;
  superfamily: string;
  has_coordinates: boolean;
}

// Command for undo/redo
export interface Command {
  id: string;
  timestamp: string;
  description: string;
  do: () => void | Promise<void>;
  undo: () => void | Promise<void>;
}

// ========================================
// Repair-related types (plan.md section 3)
// ========================================

// MissingRegionInfo - 단일 Missing Region 정보
export interface MissingRegionInfo {
  regionId: string; // "chain_A_region_100_105"
  chainId: string; // auth_asym_id
  startResId: number; // label_seq_id 시작
  endResId: number; // label_seq_id 끝
  startAuthSeqId?: number; // auth_seq_id 시작
  endAuthSeqId?: number; // auth_seq_id 끝
  insertionCode?: string; // pdbx_PDB_ins_code (region 시작점)
  endInsertionCode?: string; // pdbx_PDB_ins_code (region 끝점)
  regionLength: number; // 누락된 residue 수
  regionType: "complete" | "partial"; // complete: 전체 residue 누락, partial: 일부 atom 누락
  terminalType?: "nterm" | "cterm" | "internal"; // terminal 여부
  missingAtoms?: string[]; // partial인 경우 누락된 atom 이름
  sequence?: string; // 해당 구간의 아미노산 서열 (알려진 경우)
  sequenceKnown: boolean; // SEQRES 등에서 서열 정보 확보 여부
}

// RepairSegment - Repair Group (인페인팅 단위)
export interface RepairSegment {
  segmentId: string; // "segment_1"
  missingRegions: MissingRegionInfo[]; // 이 segment에 포함된 missing region들
  chainIds: string[]; // 이 segment에 포함된 체인들 (여러 체인 선택 가능)
  repairType: "backbone" | "sidechain" | "full"; // 수선 타입
  contextChains?: string[]; // 컨텍스트로 포함할 체인들 (멀티머)
  contextRadius: number; // Å 단위
  templateChain?: string; // 멀티머 대칭 체인에서 템플릿으로 사용할 체인
  interactsWith?: Array<{
    type: "chain" | "ligand" | "dna" | "rna" | "metal";
    id: string;
  }>; // 인접 분자들
  autoGenerated: boolean; // 자동 생성 여부
  needsSequenceInput: boolean; // 사용자 FASTA 입력 필요 여부
}

// SequenceMapping - 서열 매핑 정보
export interface SequenceMapping {
  chainId: string;
  entityId: string;
  sequence: string; // full SEQRES 또는 제공된 서열
  source: "seqres" | "fasta" | "dbref" | "uniprot" | "unknown";
  mappedRanges: Array<{
    startSeqId: number;
    endSeqId: number;
    hasStructure: boolean;
  }>;
  unmappedRanges: Array<{
    startSeqId: number;
    endSeqId: number;
    reason: "gap" | "missing_coords" | "no_sequence_info";
  }>;
  // UniProt 정보 (PDB ID를 통해 검색한 경우)
  uniprotInfo?: {
    accession: string; // P12345
    name: string; // PROTEIN_NAME
    organism: string;
    pdbMapping?: {
      pdbId: string;
      chainId: string;
      uniprotStart: number;
      uniprotEnd: number;
      pdbStart: number;
      pdbEnd: number;
    };
  };
}

// RepairContext - Context & Inpaint 설정
export interface RepairContext {
  segmentId: string;
  includeContext: boolean;
  contextRadius: number; // Å
  softShellRadius: number; // Å
  fixedResidues: Array<{
    chain: string;
    residues: number[];
  }>;
  contextPreviewSnapshot?: string; // MVS snapshot ID
}

// RepairResult - Repair 결과
export interface RepairResult {
  resultId: string;
  segmentId: string;
  timestamp: string;
  structure: ArrayBuffer; // PDB/mmCIF data
  confidence: number;
  plddt_mean?: number;
  clashscore?: number;
  ramachandran_favored?: number; // %
  rmsd?: number; // 원본 대비
  parameters: {
    seeds: number[];
    temperature: number;
    steps: number;
  };
}
