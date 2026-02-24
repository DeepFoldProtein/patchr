# Patchr Studio 기능 명세서

> **목적**: LLM의 context로 사용하기 위한 Patchr Studio의 기능 및 아키텍처 요약

---

## 📋 개요

**Patchr Studio**는 분자 구조 시각화, 편집, 인페인팅을 위한 Electron 기반 데스크톱 애플리케이션입니다. Windows, macOS, Linux 등 모든 주요 플랫폼을 지원합니다.

### 핵심 목표
- 분자 구조의 missing region 자동 감지 및 시각화
- AI 기반 구조 생성 (Boltz-Inpainting)
- 멀티체인, DNA, RNA, 리간드 지원
- MolViewSpec (MVS) 표준 포맷 지원

---

## 🎯 주요 기능

### 1. 분자 구조 시각화 (Mol* Viewer)

**기능:**
- **Mol* 3D Viewer**: 고성능 분자 구조 3D 시각화
- **구조 로드**: PDB, mmCIF 포맷 지원
- **다중 표현**: Cartoon, ball-and-stick, surface 등
- **체인 색상**: 자동 대비 색상 적용
- **워터 분자 숨기기**: 기본적으로 워터 분자 자동 숨김

**구현 파일:**
- `src/renderer/src/components/mol-viewer/usePluginContext.ts` - Mol* 플러그인 초기화
- `src/renderer/src/components/mol-viewer/useStructure.ts` - 구조 로드
- `src/renderer/src/components/mol-viewer/useRepresentation.ts` - 표현 관리
- `src/renderer/src/components/mol-viewer/useChainColors.ts` - 체인 색상
- `src/renderer/src/components/mol-viewer/useHideWater.ts` - 워터 숨기기

---

### 2. Missing Region 감지 및 시각화

**기능:**
- **자동 감지**: 구조에서 누락된 residue/atom 자동 감지
- **DNA/RNA 지원**: 
  - Nucleotide backbone 원자 정의 (O1P/O2P vs OP1/OP2 자동 처리)
  - Terminal residue 정확한 식별 (phosphate 원자 없이도)
  - Residue type 자동 분류 (protein/DNA/RNA)
- **Multi-chain 분석**: 전체 구조에서 missing region 검색
- **Interactive 시각화**:
  - Missing region 클릭 시 카메라 자동 포커스
  - 거리 측정선 표시 (complete gap)
  - Ball-and-stick 표현 (partial residue)
  - Sequence panel 자동 체인 선택

**구현 파일:**
- `src/renderer/src/components/mol-viewer/useGapDetection.ts` - 감지 로직
- `src/renderer/src/components/mol-viewer/useGapVisuals.ts` - 시각화

**데이터 구조:**
```typescript
interface MissingRegionInfo {
  regionId: string;
  chainId: string;
  startResId: number;
  endResId: number;
  regionLength: number;
  regionType: "complete" | "partial";
  terminalType?: "nterm" | "cterm" | "internal";
  missingAtoms?: string[];
  sequence?: string;
  sequenceKnown: boolean;
}
```

---

### 3. Sequence Viewer 통합

**기능:**
- **별도 패널**: Sequence viewer를 별도 영역에 표시
- **체인 자동 선택**: Missing region 클릭 시 관련 체인 자동 표시
- **연동 선택**: 3D viewer 선택 ↔ Sequence panel 동기화
- **Reference 기반**: Mol* SequenceView ref를 통한 프로그래밍 제어

**구현 파일:**
- `src/renderer/src/components/mol-viewer/useSequenceViewer.tsx`

---

### 4. Repair Console (워크플로우)

**기능:**
- **Missing Region Analysis**: 감지된 missing region 검토 및 선택
- **Sequence Mapping**: UniProt 검색을 통한 서열 정보 제공
- **Inference (Inpainting)**: Boltz-Inpainting 기반 구조 생성
- **Results**: 생성된 결과 관리 및 시각화

**구현 파일:**
- `src/renderer/src/components/ControlPanel.tsx` - 메인 컨트롤 패널
- `src/renderer/src/components/repair/GapReviewSection.tsx` - Missing region 검토

**워크플로우:**
1. Missing Region 선택 → Repair Segment 생성
2. Sequence Mapping (선택적) → FASTA 서열 제공
3. Inference 실행 → Boltz API 호출
4. Results 확인 → 생성된 구조 로드 및 비교

---

### 5. Boltz-Inpainting 통합

**기능:**
- **API 연결**: Boltz 서버 연결 및 헬스 체크
- **템플릿 업로드**: 구조 파일 및 체인 정보 업로드
- **예측 실행**: 
  - Recycling steps: 3
  - Sampling steps: 200
  - Diffusion samples: 1
- **진행률 모니터링**: 실시간 진행률 및 상태 업데이트
- **결과 다운로드**: 생성된 CIF 파일 자동 저장

**파라미터:**
```typescript
interface InpaintParams {
  seeds: number[]; // 생성할 시드 목록
  temperature: number; // 생성 다양성 (0.0-2.0)
  confidence_threshold: number; // 신뢰도 필터링 (0.0-1.0)
}
```

**구현 위치:**
- `src/renderer/src/components/ControlPanel.tsx` - ContextInpaintSection

---

### 6. 결과 관리 및 시각화

**기능:**
- **결과 목록**: 모든 inpainting 실행 결과 표시
- **품질 지표**: 
  - pLDDT 평균값 (인페인팅된 residue에 대해서만)
  - MolProbability (사용 가능한 경우)
- **정렬**: pLDDT 또는 Run 순서로 정렬
- **구조 로드**: 결과 CIF 파일 로드 및 superposition
- **Base Structure**: 원본 구조와 비교
- **YAML 보기**: 실행에 사용된 YAML 설정 확인

**구현 위치:**
- `src/renderer/src/components/ControlPanel.tsx` - Results 섹션

---

### 7. 프로젝트 관리

**기능:**
- **프로젝트 생성/열기**: `.patchrproj` 포맷 지원
- **구조 파일 관리**: Original structures 저장 및 관리
- **결과 저장**: Inpainting 결과 자동 저장
- **YAML 자동 생성**: Missing region 기반 YAML 설정 자동 생성

**구현 파일:**
- `src/renderer/src/components/ProjectManager.tsx`
- `src/renderer/src/components/ProjectWelcome.tsx`
- `src/renderer/src/store/project-store.ts`

---

### 8. Superposition (구조 정렬)

**기능:**
- **자동 정렬**: 인페인팅 결과를 원본 구조와 자동 정렬
- **다중 구조 비교**: 여러 결과를 동시에 로드하여 비교
- **가시성 토글**: 각 구조의 표시/숨김 제어

**구현 파일:**
- `src/renderer/src/components/mol-viewer/useSuperpose.ts`

---

## 🏗️ 기술 스택

### 프론트엔드
- **Framework**: Electron + React 19 + TypeScript + Vite
- **UI 라이브러리**:
  - Radix UI + shadcn/ui (접근성 컴포넌트)
  - TailwindCSS (스타일링)
  - react-resizable-panels (레이아웃)
  - lucide-react (아이콘)
- **상태 관리**:
  - **Jotai**: 컴포넌트 레벨 상태 (UI 입력값, 탭 선택 등)
  - **Zustand**: 전역 상태 (프리뷰 스트리밍, 진행률)
  - **TanStack Query**: 서버 데이터 캐싱
  - **mitt**: 이벤트 버스 (컴포넌트 간 통신)
- **3D Viewer**: 
  - **molstar** ^5.0.0 (고성능 분자 시각화)
  - **PluginUIContext**: React 통합
- **폼 관리**: React Hook Form + Zod (검증)

### 백엔드 통합
- **Boltz API**: HTTP 기반 구조 생성 API
- **UniProt API**: PDB ID 기반 서열 검색

---

## 📐 상태 관리 아키텍처

### 계층별 상태 관리

**1. Component-Level State (Jotai)**
- UI 입력값 (seeds, temperature, confidence_threshold)
- 탭 선택
- 로컬 UI 상호작용
- 마스크 명세

**2. Global State (Zustand)**
- 프리뷰 스트리밍 (isRunning, progress, elapsed_s, remaining_s)
- 생성된 프레임 캐시
- Run ID 및 에러 상태
- **독립적인 interval 관리** (React 라이프사이클 무관)

**3. Project State (Jotai)**
- 현재 프로젝트 정보
- 구조 파일 내용
- 프로젝트 메타데이터

**4. Event Bus (mitt)**
- 컴포넌트 간 이벤트 통신
- `inpainting:load-result` - 결과 로드
- `inpainting:remove-result` - 결과 제거
- `inpainting:structure-loaded` - 구조 로드 완료

---

## 🔌 API 통합

### Boltz API

**엔드포인트:**
- `POST /health` - 헬스 체크
- `POST /upload_template` - 템플릿 업로드
- `GET /job/{job_id}/status` - 작업 상태 조회
- `POST /run_prediction` - 예측 실행
- `GET /job/{job_id}/download` - 결과 다운로드

**구현 위치:**
- `src/main/index.ts` - Electron main process에서 API 호출

### UniProt API

**기능:**
- PDB ID 기반 서열 검색
- 체인별 서열 정보 반환

**구현 위치:**
- `src/main/index.ts` - Electron main process에서 API 호출

---

## 📁 주요 컴포넌트 구조

```
src/renderer/src/
├── components/
│   ├── AppLayout.tsx              # 메인 레이아웃
│   ├── Toolbar.tsx                 # 상단 툴바
│   ├── StatusBar.tsx               # 하단 상태바
│   ├── MolViewerPanel.tsx          # Mol* 뷰어 패널
│   ├── ControlPanel.tsx            # 우측 컨트롤 패널 (Repair Console)
│   ├── ProjectManager.tsx          # 프로젝트 관리
│   ├── ProjectWelcome.tsx          # 프로젝트 환영 화면
│   ├── StructureUploadModal.tsx   # 구조 업로드 모달
│   ├── mol-viewer/                 # Mol* 관련 훅
│   │   ├── usePluginContext.ts     # 플러그인 초기화
│   │   ├── useStructure.ts         # 구조 로드
│   │   ├── useGapDetection.ts      # Missing region 감지
│   │   ├── useGapVisuals.ts        # Missing region 시각화
│   │   ├── useSequenceViewer.tsx   # Sequence viewer
│   │   ├── useHideWater.ts         # 워터 숨기기
│   │   ├── useSuperpose.ts         # 구조 정렬
│   │   ├── useChainColors.ts       # 체인 색상
│   │   ├── useAutoYAMLGeneration.ts # YAML 자동 생성
│   │   └── useCanonicalMapping.ts  # Canonical mapping
│   ├── repair/
│   │   └── GapReviewSection.tsx    # Missing region 검토
│   └── ui/                         # shadcn/ui 컴포넌트
├── store/
│   ├── app-atoms.ts                # 앱 전역 상태 (Jotai)
│   ├── mol-viewer-atoms.ts         # Mol* 뷰어 상태 (Jotai)
│   ├── project-store.ts            # 프로젝트 상태 (Jotai)
│   ├── repair-atoms.ts             # Repair 상태 (Jotai)
│   └── preview-store.ts            # 프리뷰 상태 (Zustand)
├── types/
│   └── index.ts                    # TypeScript 타입 정의
└── lib/
    ├── event-bus.ts                # 이벤트 버스
    └── utils.ts                    # 유틸리티 함수
```

---

## 🔄 주요 워크플로우

### 1. Missing Region 감지 및 수리

```
1. 구조 파일 로드
   ↓
2. Missing Region 자동 감지
   ↓
3. Missing Region 시각화 (거리선, 하이라이트)
   ↓
4. 사용자가 Repair Segment 선택
   ↓
5. Sequence Mapping (선택적, UniProt 검색)
   ↓
6. Inference 실행 (Boltz API)
   ↓
7. 결과 다운로드 및 자동 로드
   ↓
8. Superposition으로 원본과 비교
```

### 2. 결과 관리

```
1. Inference 완료
   ↓
2. 결과 CIF 파일 자동 저장
   ↓
3. 품질 지표 계산 (pLDDT, MolProbability)
   ↓
4. Results 섹션에 표시
   ↓
5. 사용자가 결과 선택하여 로드
   ↓
6. 3D 뷰어에서 원본과 비교
```

---

## 📊 데이터 타입

### RepairSegment
```typescript
interface RepairSegment {
  segmentId: string;
  missingRegions: MissingRegionInfo[];
  chainIds: string[];
  repairType: "backbone" | "sidechain" | "full";
  contextChains?: string[];
  contextRadius: number;
  autoGenerated: boolean;
  needsSequenceInput: boolean;
}
```

### InpaintParams
```typescript
interface InpaintParams {
  seeds: number[];
  temperature: number;
  confidence_threshold: number;
}
```

### RepairResult
```typescript
interface RepairResult {
  resultId: string;
  segmentId: string;
  timestamp: string;
  structure: ArrayBuffer;
  confidence: number;
  plddt_mean?: number;
  parameters: {
    seeds: number[];
    temperature: number;
    steps: number;
  };
}
```

---

## 🎨 UI 레이아웃

```
┌─────────────────────────────────────────────────┐
│  Toolbar (Open, Save, Theme, etc.)            │
├──────────────────────┬──────────────────────────┤
│  Sequence Viewer     │   Control Panel          │
│  (Chain/Entity view)  │   ┌──────────────────┐   │
├──────────────────────┤   │ • Missing Region  │   │
│                      │   │   Analysis        │   │
│   Mol* 3D Viewer     │   │ • Sequence        │   │
│                      │   │   Mapping         │   │
│   (Resizable)        │   │ • Inference       │   │
│                      │   │ • Results         │   │
│                      │   └──────────────────┘   │
├──────────────────────┴──────────────────────────┤
│  Status Bar (FPS, GPU, Progress, Project Info) │
└─────────────────────────────────────────────────┘
```

---

## 🔑 핵심 기능 요약

### ✅ 완료된 기능

1. **Mol* 뷰어 통합** - 구조 로드 및 시각화
2. **Missing Region 감지** - 자동 감지 (Protein, DNA, RNA 지원)
3. **Missing Region 시각화** - Interactive 시각화 및 카메라 포커스
4. **Sequence Viewer** - 체인별 서열 표시 및 연동
5. **워터 숨기기** - 기본적으로 워터 분자 숨김
6. **Repair Console** - Missing Region 검토, Sequence Mapping, Inference
7. **Boltz API 통합** - 구조 생성 및 결과 다운로드
8. **결과 관리** - 품질 지표 계산 및 구조 비교
9. **프로젝트 관리** - 프로젝트 생성, 열기, 저장
10. **Superposition** - 구조 정렬 및 비교

### 📝 진행 중 / 계획된 기능

1. **실시간 프리뷰 스트리밍** - WebSocket 기반 실시간 프리뷰
2. **다중 프로젝트 탭** - 여러 프로젝트 동시 작업
3. **Command Palette** - ⌘K 단축키 지원
4. **Undo/Redo 시스템** - 작업 히스토리 관리
5. **구조 정제** - OpenMM 통합
6. **MVS 지원** - MolViewSpec 포맷 저장/로드

---

## 🛠️ 개발 가이드

### 주요 패턴

1. **React 18 HMR 안정성**: ref callback 패턴 사용
2. **DOM 격리**: Mol*와 React DOM 조작 분리
3. **상태 관리**: Jotai (컴포넌트) + Zustand (전역) 분리
4. **이벤트 통신**: mitt 이벤트 버스 사용

### 파일 구조 규칙

- `/ui`: 재사용 가능한 UI 컴포넌트
- `/components`: 기능별 컴포넌트
- `/mol-viewer`: Mol* 관련 훅 함수
- `/store`: 상태 관리 (Jotai atoms, Zustand stores)

---

## 📚 참고 문서

- [README.md](../README.md) - 프로젝트 개요
- [docs/INDEX.md](INDEX.md) - 문서 인덱스
- [docs/guides/mol-viewer-integration.md](guides/mol-viewer-integration.md) - Mol* 통합 가이드
- [docs/guides/IMPLEMENTATION_NOTES.md](guides/IMPLEMENTATION_NOTES.md) - 구현 노트
- [docs/completed/gap-visualization-complete.md](completed/gap-visualization-complete.md) - Missing region 시각화 완료 보고서

---

**Last Updated**: 2025-01-27
**Version**: 1.0.0

