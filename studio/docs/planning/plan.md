# Renderer 기획서 — Patchr Studio (로컬 GUI 앱, MolViewSpec 통합 + UI 컴포넌트 설계)

> 목표: 웹서버 호스팅이 아닌 **로컬 GUI 앱(Electron + React + Mol\*)** 형태로 동작. 포토샵/ComfyUI 같은 **시각 편집형 워크플로우** 제공. 기능은 **multimer, DNA, ligand 지원**, **자동 결손부 감지 및 인페인팅**, **부분 서열 수정(local edit) 재생성**을 포함하며, **MolViewSpec(MVS)** 포맷을 통합하여 뷰 상태의 표준화·저장·공유를 지원한다.

---

## 1. 전반 개요

- **플랫폼**: Electron (Main/Renderer), 로컬 FastAPI 백엔드와 WS/HTTP 통신
- **렌더러 스택**: React + TypeScript + Vite
- **UI 라이브러리 조합**:
  - **Radix UI + shadcn/ui + TailwindCSS** → 접근성, 다크테마, 헤드리스 컴포넌트 기반으로 커스터마이징 용이
  - **react-resizable-panels** → 우측 패널 분할/리사이즈
  - **cmdk** → 커맨드 팔레트 (⌘K)
  - **AG Grid + ECharts** → 리포트용 대규모 데이터 시각화
  - **react-virtual + react-arborist** → 트리/리스트 가상화
  - **Jotai** → 전역 상태 관리
  - **React Hook Form + Zod** → 파라미터 폼 관리 및 검증
  - **Radix Popover/Dialog/Menu/Slider** → 세부 툴 UI 구성
  - **sonner** → 토스트 알림
  - **react-i18next** → 다국어(i18n)

- **MolViewSpec 통합**: 뷰 상태(View State)를 표준 JSON(MVS)으로 직렬화/역직렬화하여 시각적 재현성 확보
- **핵심 UX**: 중앙 Mol\* 3D 뷰어 / 우측 Repair Console(섹션: Missing Region Review, Sequence Mapping, Context & Inpaint, Relax/QA) / 상단 툴바 / 하단 상태바
- **목표 사용자**: 구조생물/컴퓨테이셔널 바이오/신약 탐색 연구자, 모델 개발자

---

## 2. 주요 화면 레이아웃

```
┌───────────────────────────────────────────────────────────────┐
│ [상단 툴바]  Open  Save  Undo/Redo  Snapshot  Compare  Settings │
├───────────────────────┬───────────────────────────────────────┤
│       Mol* Viewer     │   [Repair Console] [Export Manager]   │
│  - 체인 커버리지 맵    │  - Repair: Missing Region Review / Mapping /     │
│  - 마스크 오버레이     │          Context & Inpaint / QA       │
│  - 인터페이스 하이라이트│  - Export: 프로젝트 히스토리, 버전관리  │
│                       │          파일 불러오기/내보내기       │
├───────────────────────────────────────────────────────────────┤
│ [하단 상태바] FPS | GPU | 진행률 | 메시지/로그 | 파일/프로젝트 상태  │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Repair 워크플로우 요약 (Mask + Inpaint + Refine 통합)

1. **PDB Intake & Validation**
   - PDB/mmCIF 업로드 시 `ATOM/HETATM`, `SEQRES`, `DBREF`, `REMARK 465`를 동시에 스캔해 결손 서열, 누락 원자, 부분 점유(occupancy < 1.0) 정보를 추출한다.
   - 체인·레지듀 단위 topology를 표준 사전(chemical component dictionary)과 대조하여 missing side-chain/bond를 식별한다.
   - 인서션 코드, 단절된 residue 번호, altLoc, biological assembly vs asymmetric unit 여부를 메타데이터로 기록하여 후속 단계에 전달한다.

2. **Missing Region Review 패널**
   - 각 체인 별로 residue coverage 타임라인을 렌더링하고, `missing segment`(완전 누락)와 `incomplete residue`(원자 누락)를 서로 다른 마커로 표시한다.
   - 자동으로 Repair Group(인페인팅 단위)을 생성하여 길이, 화학 타입(주사슬/사이드체인), 주변 접촉(chain/ligand)을 요약한다.
   - 멀티머 대칭 체인의 경우 대응 체인을 자동 매핑해 재사용 가능한 수선 계획을 제안한다.

3. **Sequence Mapping & Annotation**
   - `SEQRES` 또는 외부 FASTA를 기준으로 구조에 매핑된 서열/미매핑 서열을 시각화한다.
   - 서열 정보가 없는 segment는 `UNK` placeholder로 표시하고, 사용자가 FASTA를 제공하거나 아미노산 타입을 직접 지정할 수 있도록 한다.
   - numbering gap, insertion code, chain break를 정규화한 canonical index를 유지해 인페인팅과 후처리가 일관되도록 한다.

4. **Context & Inpaint Controls**
   - Repair Group 별로 인접 체인/ligand/금속 등을 context로 포함할지 설정하고, radius/soft-shell 파라미터를 제어한다.
   - Inpainting은 Repair Console 내부에서 호출되는 함수형 액션으로 노출하며, seed/temperature/confidence 등 파라미터를 수집한다.
   - 자동/수동 마스킹(브러시, 라쏘)은 해당 Repair Group 설정 안에 포함되어 독립 탭 없이 관리된다.

5. **Relax / QA**
   - 인페인팅 결과에 대해 PDBFixer 기반 누락 원자 보정 → OpenMM 미세 에너지 최소화 → `MolProbity` 스타일 clash/Ramachandran 검사 순으로 실행한다.
   - 결과 히스토리를 저장하여 원본 ↔ refined 모델 간 RMSD, pLDDT(옵션), clashscore 비교를 지원한다.
   - 멀티머의 경우 대칭 적용 후 인터페이스 clash 검사 및 assembly-level metrics를 추가한다.

### 3.1 결손/누락 감지 로직 (Edge Cases 포함)

| 케이스                          | 설명                                                                            | 처리 전략                                                        |
| ------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Residue missing region + sequence known    | `SEQRES`/`_entity_poly_seq` 기준으로 존재해야 하는 residue가 `ATOM` 섹션에 없음 | missing region 길이, 예상 residue 타입을 기록하고 default mask로 생성       |
| Residue missing region + sequence unknown  | 서열 정보 자체가 누락, `REMARK 999: SEQRES MISSING` 등                          | 사용자 FASTA 입력을 요청하거나 `UNK` 패딩으로 임시 인페인팅 수행 |
| Partial residue (missing atoms) | `REMARK 470`, occupancy < 1.0, side-chain 원자 누락                             | backbone anchor 유지, side-chain rebuild 태스크로 분류           |
| altLoc 분지                     | 동일 residue에 altLoc, 최고 occupancy 선택                                      | 기본 구조는 max occupancy, 나머지는 context 보존으로 태깅        |
| Insertion code / 번호 리셋      | residue 번호가 점프, 예: 100, 100A, 101                                         | canonical index를 생성하고 원본 번호를 매핑 테이블로 유지        |
| Multimer symmetry reuse         | 체인 A와 B가 동일 서열, A에만 missing region 존재                                          | B의 해당 구간을 템플릿으로 제안, context 자동 포함               |
| Ligand/DNA 인접 missing region             | gap이 ligand 또는 핵산에 접함                                                   | ligand/핵산을 강제 context로 포함, 소프트셸 반지름 확장          |

감지 로직은 `Biopython` + `gemmi` 조합을 사용해 빠르게 시행하고, 결과는 Repair store에 `RepairSegment[]` 형태로 넣는다.

### 3.2 Sequence 정보 확보 우선순위

1. mmCIF `_entity_poly_seq` → residue type + auth_seq_id + label_seq_id
2. `SEQRES` vs `ATOM` alignment → canonical numbering 확보
3. `DBREF`, `DBSEQ` → Uniprot/GenBank 매핑 시퀀스 추출
4. 사용자 제공 FASTA (drag&drop, 텍스트 입력)
5. 최종적으로도 모를 경우 `UNK` 시퀀스로 간주하되, inpainting inference에 residue 타입을 샘플링하도록 태깅

### 3.3 멀티머 컨텍스트 결정 규칙

- Biological assembly 정보를 사용해 동일 체인 타입을 그룹화하고, 지정된 gap이 multimer 인터페이스에 위치하면 파트너 체인을 자동 context로 포함한다.
- 기본 radius는 6 Å, 멀티머 인터페이스에서는 8 Å 이상으로 확장하며, user override가 가능하다.
- Inter-chain hydrogen bond/π-π 상호작용이 존재하면 해당 인터랙션 파트너 residue를 강제 고정(fixed)으로 마킹한다.
- `Context Preview` 스냅샷을 Mol\*에서 확인하면서 필요 시 브러시로 추가/삭제할 수 있다.

### 3.4 Mol\* API 기반 결손 감지/컨텍스트 파이프라인

1. **구조 접근**
   - `plugin.managers.structure.hierarchy.current.structures[0]` 에서 `Structure` 객체를 가져오고, `Structure.models[0]` 으로 `Model` 참조.
   - 중복 방지를 위해 `structure.unitSymmetryGroups` 를 순회하면서 `Unit.isAtomic(unit)` & `unit.invariantId` 기준으로 1회만 처리.

2. **Gap 추출**
   - `unit.gapElements` (짝수 인덱스 = missing region 시작, 홀수 인덱스 = missing region 종료)로 anchor residue 선택.
   - 각 anchor에 대해 `StructureElement.Location.create(structure, unit, elementIndex)` 호출 후 `StructureProperties.residue.label_seq_id`, `StructureProperties.residue.auth_seq_id`, `StructureProperties.residue.pdbx_PDB_ins_code` 로 numbering 확보.
   - 연속 missing region 길이는 anchor 사이 `label_seq_id` 차이 및 `Model.atomicHierarchy.derived.residue.traceElementIndex` 를 사용해 계산.

3. **서열 가용성 판단**
   - `Model.sequence.byEntityKey[entityKey]` 의 `sequence.seqId` / `Sequence.getSequenceString` 으로 `SEQRES` 정보 조회.
   - missing region 범위 내 seqId 가 `sequence.index(seqId)` 호출에서 실패하면 **sequence missing** 플래그로 설정 → Repair Console에서 FASTA 입력 요구.

4. **부분 residue / missing atom 기록**
   - `Model.sourceData.data.frame.categories['_pdbx_unobs_or_zero_occ_residues']` 와 `['_pdbx_unobs_or_zero_occ_atoms']` 를 읽어 partial residue 및 zero occupancy atom 목록을 매칭.
   - 매칭은 `auth_asym_id`, `auth_seq_id`, `label_atom_id` 등을 통해 수행하고, `StructureProperties.atom.occupancy` < 1.0 인 경우도 보완 플래그로 추가.

5. **컨텍스트 파트너 탐색**
   - missing region anchor 주변 3D 이웃은 `structure.lookup3d.find(StructureElement.Location, radius, callback)` 를 활용.
   - ligand/DNA 판별은 `StructureProperties.residue.chem_comp_type` 또는 `model.properties.chemicalComponentMap` 데이터를 사용한다.
   - 멀티머 템플릿은 `StructureSymmetry.assemblies` 와 `structure.unitSymmetryGroups` 의 `operators` 를 비교하여 동일 체인 타입을 감지하고, 해당 체인의 동일 구간에 gap이 없는 경우 `RepairSegment.templateChain` 으로 연결.

6. **결과 전파**
   - 감지된 `RepairSegment[]` 를 Repair store에 저장; `bus.emit("repair:gaps-ready", segments)` 이벤트를 정의하여 UI 섹션과 연동.
   - 이후 마스크 생성은 `plugin.managers.structure.selection.fromLoci` 를 이용해 Mol\* loci로 변환, `StructureSelection` API와 ShapeBuilder 기반 오버레이로 시각화.

### 3.5 Export Manager (프로젝트 히스토리 & 배포)

- **역할**: Repair Console에서 생성한 마스크/컨텍스트/서열/결과 구조를 버전 타임라인으로 관리하고, `.patchrproj`/`.msvj`/PDB/mmCIF 패키지화를 담당한다.
- **주요 기능**
  - `ProjectTimeline` 뷰: 각 인페인팅/리파인 런을 메타데이터(시간, 파라미터, pLDDT, clashscore)와 함께 카드로 저장.
  - `Snapshot` 액션: 현재 Repair 상태를 `app://projects/{id}/snapshots/{timestamp}` 로 직렬화, `MolViewSpec`와 프로젝트 상태를 묶어서 보관.
  - `Import` 액션: 기존 `.patchrproj` 로드 시 Repair Console에 해당 상태를 리스토어하며, 누락된 파일은 사용자에게 경고.
  - `Publish` 액션: 선택한 스냅샷을 `.zip` 패키지(PDB/mmCIF + `.patchrproj` + `.msvj`)로 묶어 외부 배포.
- **데이터 연동**
  - Zustand `projectHistoryStore`에서 타임라인 상태를 관리하고, 파일 IO는 Electron IPC(`ipcRenderer.invoke("project:save")`)를 통해 수행.
  - Mol\* 구조는 `plugin.managers.structure.hierarchy.setStructure` 를 사용해 스냅샷 복원 시 즉시 반영한다.
- **UI 흐름**
  - 우측 패널 상단 토글에서 `Export Manager` 선택 → 타임라인 리스트 + 상세 패널 표시.
  - Repair Console에서 `Commit to History` 액션 호출 시 이벤트 버스로 Export Manager가 새 항목을 추가.

---

## 4. MolViewSpec(MVS) 연동 설계

### 4.1 개요

Patchr Studio는 **MolViewSpec 포맷(.msvj)** 을 통해 뷰 상태를 표준화·보존한다.

| 구분              | 포맷            | 설명                                                            |
| ----------------- | --------------- | --------------------------------------------------------------- |
| **프로젝트 상태** | `.patchrproj` | 알고리즘 관련 상태(마스크, 인페인팅 파라미터, 로그 등) 포함     |
| **뷰 상태**       | `.msvj`         | MolViewSpec 기반 뷰/표현/라벨/색상/대칭 상태 저장 (시각 재현용) |

### 4.2 사용 흐름

1. 구조/마스크 변경 시 → 렌더러가 MVS 빌더를 통해 View State 자동 생성
2. 프리뷰 또는 Snapshot 시 → `.msvj` 동시 저장, 재현 가능한 시각 장면 보존
3. Export 시 → `.patchrproj` + `.msvj` 동시 포함(ZIP 패키징)
4. Import 시 → `.patchrproj` 복원 후 `.msvj` 적용하여 동일한 장면 렌더링

### 4.3 MVS 매핑 테이블 (렌더러 UI ↔ MVS)

| UI 요소              | MolViewSpec 노드            | 속성                                              |
| -------------------- | --------------------------- | ------------------------------------------------- |
| Mol\* 표시 스타일    | Representation node         | cartoon, surface, ball&stick, colorTheme          |
| 마스크 표시          | Shape node (region overlay) | color, opacity, selectionExpr                     |
| 고정/soft-shell 경계 | Annotation node             | type: boundary, radiusÅ                           |
| DNA/Ligand 강조      | Component node              | selectionExpr, style: outline/glow                |
| 프리뷰 구조          | Data node                   | source: ws, format: cif, label: “inpaint preview” |
| 대칭/멀티머 표시     | Symmetry node               | symmetryGroup, colorByChain                       |

### 4.4 기술 구현

- **렌더러**: `@rcsb/mvs` TypeScript SDK 사용 → MVS 빌더/검증기 포함
- **백엔드**: Python `molviewspec` 패키지 활용 → MVS 검증 및 자동 리포트 생성
- **저장 위치**: 프로젝트 루트 `/views/view_<timestamp>.msvj`
- **MVS 버전 호환성**: 버전 메타 유지(`_molviewspec_version` 필드)

---

## 5. 상태관리 / 데이터 모델 (전역 최소화 원칙)

### 5.1 원칙

- **전역 상태를 최소화**한다. “앱 전체에 항상 살아야 하는 데이터” 외에는 **프로젝트(문서) 범위**나 **컴포넌트 로컬**로 한정한다.
- **UI 일시 상태**(워크플로우 섹션 토글, 폼 값, 패널 열림 등)는 `useState/useReducer` 로컬 관리.
- **서버 데이터**는 전역 스토어가 아닌 **캐시(요청-응답)** 로 다룬다 → TanStack Query 권장.
- **크로스 패널 통신**은 전역 데이터 공유 대신 **이벤트 버스(예: mitt)** 또는 **명령(Command) 패턴**으로 처리.
- **Undo/Redo**는 **프로젝트 단위 커맨드 스택**으로 유지(전역 금지).

### 5.2 전역으로 남기는 최소 항목 (App-scope)

- **세션 정보**: 백엔드 프로세스 포트/토큰, 앱 버전, 테마(light/dark)
- **최근 열기 목록**: 파일 경로/프로젝트 메타(옵션)
- **키바인딩 맵**: 사용자 오버라이드(선택)

> 위 항목들은 Jotai의 **앱 루트 Provider**에 두되, 나머지는 프로젝트 스코프로 격리한다.

### 5.3 프로젝트 스코프 스토어 (Jotai Provider 분리)

- 프로젝트를 열 때마다 **독립 Jotai store**를 생성하고, 닫을 때 폐기한다.
- 프로젝트 간 메모리/사이드이펙트가 섞이지 않음.

```tsx
import { Provider as JotaiProvider, createStore } from "jotai";

export function ProjectProvider({
  projectId,
  children
}: {
  projectId: string;
  children: React.ReactNode;
}) {
  const store = React.useMemo(() => createStore(), [projectId]);
  return <JotaiProvider store={store}>{children}</JotaiProvider>;
}
```

- **Atom 팩토리 패턴**: 프로젝트 스토어 내부에서만 쓰는 atom을 팩토리로 선언해 누수 방지.

```ts
export function createProjectAtoms() {
  const maskAtom = atom<MaskSpec>({
    version: 1,
    units: "residue",
    include: [],
    exclude: [],
    fixed: [],
    soft_shell_Ang: 3
  });
  const inpaintParamsAtom = atom<InpaintParams>({
    steps: 60,
    tau: 0.7,
    seeds: 4
  });
  const runStatusAtom = atom<RunStatus>({
    step: 0,
    of: 0,
    eta_s: 0,
    running: false
  });
  const currentViewAtom = atom<MVS | null>(null);
  return { maskAtom, inpaintParamsAtom, runStatusAtom, currentViewAtom };
}
```

### 5.4 서버 데이터는 캐시로 (TanStack Query)

- WS/HTTP로 오는 **서버-소유 데이터**는 **Query 캐시**로 관리하고, 필요 시 UI 파생값만 atom으로 노출.
- 예: 프리뷰 프레임 → `queryClient.setQueryData(['preview', projectId, runId], frames)`

```ts
const { data: previewFrames } = useQuery({
  queryKey: ["preview", projectId, runId],
  queryFn: fetchPreview,
  staleTime: 0
});
```

### 5.5 이벤트 지향 통신 (전역 상태 대체)

- 패널 간 상호작용: **mitt** 기반 이벤트 버스 또는 RxJS Subject.
- 예: Missing Region Review 섹션이 "마스크 업데이트" 이벤트를 발행 → Context & Inpaint 컨트롤 섹션이 구독하고 UI만 갱신.

```ts
import mitt from "mitt";
export const bus = mitt<{
  maskUpdated: MaskSpec;
  runStarted: { runId: string };
}>();
```

### 5.6 Undo/Redo — 커맨드 스택(문서 범위)

- 각 변경을 **Command 객체**로 기록(`do/undo/redo`).
- 스택은 **프로젝트 스토어 내부**에 존재 → 문서 교체 시 초기화.

### 5.7 퍼시스턴스 정책

- 문서 관련 상태: `.patchrproj` 에 직렬화(마스크/파라미터/MVS 스냅샷).
- UI 레이아웃/최근 파일: `appData` 또는 `localStorage` (프로젝트와 분리).

### 5.8 최소 App-scope atom 예시

```ts
export const appSessionAtom = atom<AppSession>({
  port: 0,
  token: "",
  version: "0.1.0"
});
export const themeAtom = atom<"dark" | "light">("dark");
export const recentFilesAtom = atom<string[]>([]);
```

## 6. 백엔드 Mock 계획

### 6.1 목적

- 초기 개발 단계에서는 백엔드(PyTorch + FastAPI) 연결 전, **프론트엔드 개발 속도와 UI 검증**을 위해 **Mock 서버**로 대체한다.
- 실제 백엔드와의 API 인터페이스는 그대로 유지하되, 응답을 로컬에서 시뮬레이션한다.

### 6.2 구현 방식

- **msw (Mock Service Worker)** 사용 → Electron 환경에서도 작동 가능.
- `src/mocks/handlers.ts` 내에 FastAPI 엔드포인트를 그대로 모사.

예시:

```ts
import { http, HttpResponse } from "msw";

export const handlers = [
  http.post("/api/inpaint/run", async ({ request }) => {
    const body = await request.json();
    // dummy progress
    for (let i = 0; i < 5; i++) {
      console.log(`mock step ${i}/5`);
      await new Promise(r => setTimeout(r, 300));
    }
    return HttpResponse.json({
      run_id: "mock-run",
      preview: "/mock/preview.pdb",
      log: "Mock run complete"
    });
  }),

  http.get("/api/view/export", () =>
    HttpResponse.json({ view: { version: "mock", nodes: [] } })
  )
];
```

- `src/main.tsx`:

```ts
if (process.env.NODE_ENV === "development") {
  const { worker } = await import("./mocks/browser");
  worker.start();
}
```

### 6.3 Mock 데이터 구성

- `/mock` 폴더에 샘플 데이터 포함:
  - `mock_structure.pdb`
  - `mock_mask.json`
  - `mock_inpaint_result.pdb`
  - `mock_view.msvj`

- API별 응답 시나리오를 설정해, 인페인트 진행률 / 결과 / 로그 / 오류 케이스를 재현.

### 6.4 통합 원칙

- 백엔드 교체 시 FastAPI endpoint와 **경로·스키마 동일 유지** → mock만 제거.
- 백엔드 준비 후, mock handler는 테스트용 옵션으로 유지(`DEV_MOCK=true`).

### 6.5 장점

- 프론트엔드 개발 독립성 확보, UI 테스트 병렬 진행 가능
- FastAPI 설계 완성 전에도 Renderer의 상태 흐름·이벤트·로딩UI 검증 가능
- QA 환경에서도 mock 모드로 리그레션 테스트 용이

---

## 7. IPC / Networking 업데이트

- **WS/HTTP 추가 엔드포인트**
  - `GET /view/export` → 현재 MVS JSON 반환
  - `POST /view/import` → MVS JSON 적용
  - `POST /view/validate` → 백엔드 MVS 빌더 검증 후 결과 반환

---

## 7. 장점 요약

- **전역 최소화**로 리렌더/결합도 감소, 메모리 관리 용이
- **프로젝트 격리**로 다중 문서 동시 편집 시 상태 충돌 방지
- **Query 캐시**로 서버 데이터 일관성 유지
- **이벤트 지향**으로 패널 간 의존성 축소

---

## 8. 향후 확장

- 프로젝트 탭 다중 오픈(각 탭별 ProjectProvider)
- 명령 팔레트에서 **Command 스택 항목** 노출/검색
- WS 스트림을 Query 캐시와 동기화하는 어댑터 모듈 IPC / Networking 업데이트
- **WS/HTTP 추가 엔드포인트**
  - `GET /view/export` → 현재 MVS JSON 반환
  - `POST /view/import` → MVS JSON 적용
  - `POST /view/validate` → 백엔드 MVS 빌더 검증 후 결과 반환

---

## 7. 장점 요약

- **재현성**: 구조·색상·표현이 표준화된 형태로 보존되어 실험 반복/공유 용이
- **상호운용성**: Mol\* Viewer, MolViewSpec 호환 앱과 뷰 상태 교환 가능
- **분리성**: 알고리즘 상태(.patchrproj)와 시각 상태(.msvj)를 분리해 유지
- **협업성**: 연구자 간 `.msvj` 공유로 동일 뷰 재현 가능

---

## 8. 향후 확장

- MVS 기반 **다중 뷰 비교(variant overlay)** 지원
- MVS→GLB 변환(3D viewer export)
- Cloud 저장(MVS snapshot history 공유)
- UI 컴포넌트 확장: Docking Panel / Theme Editor / Command Palette 개선

---

## Appendix: Diff vs previous plan

```diff
diff --git a/docs/plan.md b/docs/plan.md
index b131890..e74e824 100644
--- a/docs/plan.md
+++ b/docs/plan.md
@@ -21,7 +21,7 @@
   - **react-i18next** → 다국어(i18n)
 
 - **MolViewSpec 통합**: 뷰 상태(View State)를 표준 JSON(MVS)으로 직렬화/역직렬화하여 시각적 재현성 확보
-- **핵심 UX**: 중앙 Mol\* 3D 뷰어 / 우측 컨트롤 패널(탭: Mask, Inpaint, Refine, Export) / 상단 툴바 / 하단 상태바
+- **핵심 UX**: 중앙 Mol\* 3D 뷰어 / 우측 Repair Console(섹션: Missing Region Review, Sequence Mapping, Context & Inpaint, Relax/QA) / 상단 툴바 / 하단 상태바
 - **목표 사용자**: 구조생물/컴퓨테이셔널 바이오/신약 탐색 연구자, 모델 개발자
 
 ---
@@ -32,23 +32,116 @@
 ┌───────────────────────────────────────────────────────────────┐
 │ [상단 툴바]  Open  Save  Undo/Redo  Snapshot  Compare  Settings │
 ├───────────────────────┬───────────────────────────────────────┤
-│       Mol* Viewer     │     우측 패널(탭 구조)                  │
-│  - 구조 표시/선택      │  [Mask] [Inpaint] [Refine] [Export]  │
-│  - 마스크 브러시/라쏘   │                                       │
-│  - 고스트/AB 비교       │                                       │
-├───────────────────────┴───────────────────────────────────────┤
+│       Mol* Viewer     │   [Repair Console] [Export Manager]   │
+│  - 체인 커버리지 맵    │  - Repair: Missing Region Review / Mapping /     │
+│  - 마스크 오버레이     │          Context & Inpaint / QA       │
+│  - 인터페이스 하이라이트│  - Export: 프로젝트 히스토리, 버전관리  │
+│                       │          파일 불러오기/내보내기       │
+├───────────────────────────────────────────────────────────────┤
 │ [하단 상태바] FPS | GPU | 진행률 | 메시지/로그 | 파일/프로젝트 상태  │
 └───────────────────────────────────────────────────────────────┘
 ```
 
 ---
 
-## 3. 탭별 기능 요약
-
-- **Mask 탭**: 구조 영역 선택, 자동 결손부 감지, multimer/DNA/ligand별 마스킹
-- **Inpaint 탭**: 인페인팅 실행, Local edit(부분 서열 교체), seed/τ 제어, 프리뷰 스트리밍
-- **Refine 탭**: 구조 후처리(OpenMM, Side-chain 재배치, Clash score 분석)
-- **Export 탭**: PDB/mmCIF/프로젝트(.patchrproj) 내보내기 + MVS(.msvj) 뷰 상태 저장
+## 3. Repair 워크플로우 요약 (Mask + Inpaint + Refine 통합)
+
+1. **PDB Intake & Validation**
+   - PDB/mmCIF 업로드 시 `ATOM/HETATM`, `SEQRES`, `DBREF`, `REMARK 465`를 동시에 스캔해 결손 서열, 누락 원자, 부분 점유(occupancy < 1.0) 정보를 추출한다.
+   - 체인·레지듀 단위 topology를 표준 사전(chemical component dictionary)과 대조하여 missing side-chain/bond를 식별한다.
+   - 인서션 코드, 단절된 residue 번호, altLoc, biological assembly vs asymmetric unit 여부를 메타데이터로 기록하여 후속 단계에 전달한다.
+
+2. **Missing Region Review 패널**
+   - 각 체인 별로 residue coverage 타임라인을 렌더링하고, `missing segment`(완전 누락)와 `incomplete residue`(원자 누락)를 서로 다른 마커로 표시한다.
+   - 자동으로 Repair Group(인페인팅 단위)을 생성하여 길이, 화학 타입(주사슬/사이드체인), 주변 접촉(chain/ligand)을 요약한다.
+   - 멀티머 대칭 체인의 경우 대응 체인을 자동 매핑해 재사용 가능한 수선 계획을 제안한다.
+
+3. **Sequence Mapping & Annotation**
+   - `SEQRES` 또는 외부 FASTA를 기준으로 구조에 매핑된 서열/미매핑 서열을 시각화한다.
+   - 서열 정보가 없는 segment는 `UNK` placeholder로 표시하고, 사용자가 FASTA를 제공하거나 아미노산 타입을 직접 지정할 수 있도록 한다.
+   - numbering gap, insertion code, chain break를 정규화한 canonical index를 유지해 인페인팅과 후처리가 일관되도록 한다.
+
+4. **Context & Inpaint Controls**
+   - Repair Group 별로 인접 체인/ligand/금속 등을 context로 포함할지 설정하고, radius/soft-shell 파라미터를 제어한다.
+   - Inpainting은 Repair Console 내부에서 호출되는 함수형 액션으로 노출하며, seed/temperature/confidence 등 파라미터를 수집한다.
+   - 자동/수동 마스킹(브러시, 라쏘)은 해당 Repair Group 설정 안에 포함되어 독립 탭 없이 관리된다.
+
+5. **Relax / QA**
+   - 인페인팅 결과에 대해 PDBFixer 기반 누락 원자 보정 → OpenMM 미세 에너지 최소화 → `MolProbity` 스타일 clash/Ramachandran 검사 순으로 실행한다.
+   - 결과 히스토리를 저장하여 원본 ↔ refined 모델 간 RMSD, pLDDT(옵션), clashscore 비교를 지원한다.
+   - 멀티머의 경우 대칭 적용 후 인터페이스 clash 검사 및 assembly-level metrics를 추가한다.
+
+### 3.1 결손/누락 감지 로직 (Edge Cases 포함)
+
+| 케이스                          | 설명                                                                            | 처리 전략                                                        |
+| ------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
+| Residue missing region + sequence known    | `SEQRES`/`_entity_poly_seq` 기준으로 존재해야 하는 residue가 `ATOM` 섹션에 없음 | missing region 길이, 예상 residue 타입을 기록하고 default mask로 생성       |
+| Residue missing region + sequence unknown  | 서열 정보 자체가 누락, `REMARK 999: SEQRES MISSING` 등                          | 사용자 FASTA 입력을 요청하거나 `UNK` 패딩으로 임시 인페인팅 수행 |
+| Partial residue (missing atoms) | `REMARK 470`, occupancy < 1.0, side-chain 원자 누락                             | backbone anchor 유지, side-chain rebuild 태스크로 분류           |
+| altLoc 분지                     | 동일 residue에 altLoc, 최고 occupancy 선택                                      | 기본 구조는 max occupancy, 나머지는 context 보존으로 태깅        |
+| Insertion code / 번호 리셋      | residue 번호가 점프, 예: 100, 100A, 101                                         | canonical index를 생성하고 원본 번호를 매핑 테이블로 유지        |
+| Multimer symmetry reuse         | 체인 A와 B가 동일 서열, A에만 missing region 존재                                          | B의 해당 구간을 템플릿으로 제안, context 자동 포함               |
+| Ligand/DNA 인접 missing region             | gap이 ligand 또는 핵산에 접함                                                   | ligand/핵산을 강제 context로 포함, 소프트셸 반지름 확장          |
+
+감지 로직은 `Biopython` + `gemmi` 조합을 사용해 빠르게 시행하고, 결과는 Repair store에 `RepairSegment[]` 형태로 넣는다.
+
+### 3.2 Sequence 정보 확보 우선순위
+
+1. mmCIF `_entity_poly_seq` → residue type + auth_seq_id + label_seq_id
+2. `SEQRES` vs `ATOM` alignment → canonical numbering 확보
+3. `DBREF`, `DBSEQ` → Uniprot/GenBank 매핑 시퀀스 추출
+4. 사용자 제공 FASTA (drag&drop, 텍스트 입력)
+5. 최종적으로도 모를 경우 `UNK` 시퀀스로 간주하되, inpainting inference에 residue 타입을 샘플링하도록 태깅
+
+### 3.3 멀티머 컨텍스트 결정 규칙
+
+- Biological assembly 정보를 사용해 동일 체인 타입을 그룹화하고, 지정된 gap이 multimer 인터페이스에 위치하면 파트너 체인을 자동 context로 포함한다.
+- 기본 radius는 6 Å, 멀티머 인터페이스에서는 8 Å 이상으로 확장하며, user override가 가능하다.
+- Inter-chain hydrogen bond/π-π 상호작용이 존재하면 해당 인터랙션 파트너 residue를 강제 고정(fixed)으로 마킹한다.
+- `Context Preview` 스냅샷을 Mol\*에서 확인하면서 필요 시 브러시로 추가/삭제할 수 있다.
+
+### 3.4 Mol\* API 기반 결손 감지/컨텍스트 파이프라인
+
+1. **구조 접근**
+   - `plugin.managers.structure.hierarchy.current.structures[0]` 에서 `Structure` 객체를 가져오고, `Structure.models[0]` 으로 `Model` 참조.
+   - 중복 방지를 위해 `structure.unitSymmetryGroups` 를 순회하면서 `Unit.isAtomic(unit)` & `unit.invariantId` 기준으로 1회만 처리.
+
+2. **Gap 추출**
+   - `unit.gapElements` (짝수 인덱스 = missing region 시작, 홀수 인덱스 = missing region 종료)로 anchor residue 선택.
+   - 각 anchor에 대해 `StructureElement.Location.create(structure, unit, elementIndex)` 호출 후 `StructureProperties.residue.label_seq_id`, `StructureProperties.residue.auth_seq_id`, `StructureProperties.residue.pdbx_PDB_ins_code` 로 numbering 확보.
+   - 연속 missing region 길이는 anchor 사이 `label_seq_id` 차이 및 `Model.atomicHierarchy.derived.residue.traceElementIndex` 를 사용해 계산.
+
+3. **서열 가용성 판단**
+   - `Model.sequence.byEntityKey[entityKey]` 의 `sequence.seqId` / `Sequence.getSequenceString` 으로 `SEQRES` 정보 조회.
+   - missing region 범위 내 seqId 가 `sequence.index(seqId)` 호출에서 실패하면 **sequence missing** 플래그로 설정 → Repair Console에서 FASTA 입력 요구.
+
+4. **부분 residue / missing atom 기록**
+   - `Model.sourceData.data.frame.categories['_pdbx_unobs_or_zero_occ_residues']` 와 `['_pdbx_unobs_or_zero_occ_atoms']` 를 읽어 partial residue 및 zero occupancy atom 목록을 매칭.
+   - 매칭은 `auth_asym_id`, `auth_seq_id`, `label_atom_id` 등을 통해 수행하고, `StructureProperties.atom.occupancy` < 1.0 인 경우도 보완 플래그로 추가.
+
+5. **컨텍스트 파트너 탐색**
+   - missing region anchor 주변 3D 이웃은 `structure.lookup3d.find(StructureElement.Location, radius, callback)` 를 활용.
+   - ligand/DNA 판별은 `StructureProperties.residue.chem_comp_type` 또는 `model.properties.chemicalComponentMap` 데이터를 사용한다.
+   - 멀티머 템플릿은 `StructureSymmetry.assemblies` 와 `structure.unitSymmetryGroups` 의 `operators` 를 비교하여 동일 체인 타입을 감지하고, 해당 체인의 동일 구간에 gap이 없는 경우 `RepairSegment.templateChain` 으로 연결.
+
+6. **결과 전파**
+   - 감지된 `RepairSegment[]` 를 Repair store에 저장; `bus.emit("repair:gaps-ready", segments)` 이벤트를 정의하여 UI 섹션과 연동.
+   - 이후 마스크 생성은 `plugin.managers.structure.selection.fromLoci` 를 이용해 Mol\* loci로 변환, `StructureSelection` API와 ShapeBuilder 기반 오버레이로 시각화.
+
+### 3.5 Export Manager (프로젝트 히스토리 & 배포)
+
+- **역할**: Repair Console에서 생성한 마스크/컨텍스트/서열/결과 구조를 버전 타임라인으로 관리하고, `.patchrproj`/`.msvj`/PDB/mmCIF 패키지화를 담당한다.
+- **주요 기능**
+  - `ProjectTimeline` 뷰: 각 인페인팅/리파인 런을 메타데이터(시간, 파라미터, pLDDT, clashscore)와 함께 카드로 저장.
+  - `Snapshot` 액션: 현재 Repair 상태를 `app://projects/{id}/snapshots/{timestamp}` 로 직렬화, `MolViewSpec`와 프로젝트 상태를 묶어서 보관.
+  - `Import` 액션: 기존 `.patchrproj` 로드 시 Repair Console에 해당 상태를 리스토어하며, 누락된 파일은 사용자에게 경고.
+  - `Publish` 액션: 선택한 스냅샷을 `.zip` 패키지(PDB/mmCIF + `.patchrproj` + `.msvj`)로 묶어 외부 배포.
+- **데이터 연동**
+  - Zustand `projectHistoryStore`에서 타임라인 상태를 관리하고, 파일 IO는 Electron IPC(`ipcRenderer.invoke("project:save")`)를 통해 수행.
+  - Mol\* 구조는 `plugin.managers.structure.hierarchy.setStructure` 를 사용해 스냅샷 복원 시 즉시 반영한다.
+- **UI 흐름**
+  - 우측 패널 상단 토글에서 `Export Manager` 선택 → 타임라인 리스트 + 상세 패널 표시.
+  - Repair Console에서 `Commit to History` 액션 호출 시 이벤트 버스로 Export Manager가 새 항목을 추가.
 
 ---
 
@@ -95,7 +188,7 @@ Patchr Studio는 **MolViewSpec 포맷(.msvj)** 을 통해 뷰 상태를 표준
 ### 5.1 원칙
 
 - **전역 상태를 최소화**한다. “앱 전체에 항상 살아야 하는 데이터” 외에는 **프로젝트(문서) 범위**나 **컴포넌트 로컬**로 한정한다.
-- **UI 일시 상태**(탭 선택, 폼 값, 패널 열림 등)는 `useState/useReducer` 로컬 관리.
+- **UI 일시 상태**(워크플로우 섹션 토글, 폼 값, 패널 열림 등)는 `useState/useReducer` 로컬 관리.
 - **서버 데이터**는 전역 스토어가 아닌 **캐시(요청-응답)** 로 다룬다 → TanStack Query 권장.
 - **크로스 패널 통신**은 전역 데이터 공유 대신 **이벤트 버스(예: mitt)** 또는 **명령(Command) 패턴**으로 처리.
 - **Undo/Redo**는 **프로젝트 단위 커맨드 스택**으로 유지(전역 금지).
@@ -172,7 +265,7 @@ const { data: previewFrames } = useQuery({
 ### 5.5 이벤트 지향 통신 (전역 상태 대체)
 
 - 패널 간 상호작용: **mitt** 기반 이벤트 버스 또는 RxJS Subject.
-- 예: Mask 패널이 "마스크 업데이트" 이벤트를 발행 → Inpaint 패널이 구독하고 UI만 갱신.
+- 예: Missing Region Review 섹션이 "마스크 업데이트" 이벤트를 발행 → Context & Inpaint 컨트롤 섹션이 구독하고 UI만 갱신.
 
 ```ts
 import mitt from "mitt";
```
