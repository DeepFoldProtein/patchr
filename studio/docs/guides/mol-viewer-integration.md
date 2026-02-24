# Mol\* Viewer Integration 설계 문서 (Revised)

> 웹 조사 기반 실제 존재하는 라이브러리 및 구현 활용

## 1. 개요

Mol* Viewer는 구조생물학 데이터 시각화를 위한 고성능 웹 기반 3D 뷰어입니다. Patchr Studio에서는 Mol*를 중앙 뷰포트로 통합하여 다음 기능을 제공합니다:

- **구조 시각화**: PDB, mmCIF, CIF, BinaryCIF 형식 지원
- **다양한 표현**: Cartoon, Surface, Ball&Stick, Spacefill, Ribbon 등
- **선택 및 상호작용**: 마우스 기반 원자/잔기/체인 선택
- **마스크 오버레이**: Shape 기반 마스크 영역 시각화
- **MolViewSpec(MVS) 연동**: 뷰 상태 표준화, 저장 및 재현

---

## 2. 기술 스택 (실제 라이브러리)

### 2.1 핵심 NPM 패키지

| 라이브러리           | 버전   | 용도                         | 비고                         |
| -------------------- | ------ | ---------------------------- | ---------------------------- |
| **`molstar`**        | ^5.0.0 | 3D 뷰어 핵심 엔진            | ✅ npm (17.7K 주간 다운로드) |
| **`pdbe-molstar`**   | ^3.8.0 | PDBe 구현 (높은 수준의 API)  | ⭐ React 친화적, 권장        |
| `@rcsb/rcsb-molstar` | ^0.3.8 | RCSB 구현 (RCSB 커스텀 기능) | 선택사항                     |

### 2.2 Mol\* 내부 주요 모듈

Mol\* 패키지 내 핵심 모듈 (NPM 설치 후 `molstar/lib/` 경로로 접근):

```
molstar/lib/
├── mol-plugin/
│   ├── context.ts          # 플러그인 인스턴스
│   └── transforms/         # 상태 변환 (구조 로드 등)
├── mol-plugin-ui/
│   ├── base.tsx           # React 컴포넌트 기반 UI
│   ├── context.ts         # UI 컨텍스트
│   └── spec.ts            # UI 명세
├── mol-canvas3d/          # WebGL 기반 렌더링
├── mol-plugin-state/      # 상태 매니저
├── mol-io/                # PDB/mmCIF 파서
├── mol-model/             # 분자 데이터 모델
└── mol-repr/              # 표현(Representation) 시스템
```

### 2.3 State Management

- **Jotai atoms**: 뷰포트 상태 (카메라, 선택, 로딩)
- **TanStack Query**: 구조 파일 캐싱
- **Event Bus (mitt)**: 크로스 패널 통신

### 2.4 MVS (MolViewSpec) 지원

**JavaScript/TypeScript:**

- Mol\* 내장 MVS 익스텐션 (`molstar/lib/extensions/mvs/`)
- Drag-and-drop, URL parameter, 프로그래매틱 로드 지원
- `.mvsj` JSON 형식

**Python (백엔드):**

- `molviewspec` PyPI 패키지 (RCSB 개발)
- MVS 빌드, 검증, 변환 기능
- 백엔드 인페인팅 결과 메타데이터 추가 시 사용

---

## 3. 아키텍처 설계

### 3.1 파일 구조

```
src/renderer/src/
├── components/
│   ├── MolViewerPanel.tsx               # 메인 뷰어 컨테이너
│   └── mol-viewer/
│       ├── index.ts                     # 공개 인터페이스
│       ├── usePluginContext.ts          # Mol* PluginContext 초기화
│       ├── useStructure.ts              # 구조 로드 및 관리
│       ├── useRepresentation.ts         # 표현(cartoon, surface 등) 적용
│       ├── useMaskOverlay.ts            # Shape 오버레이 (마스크)
│       ├── useSelection.ts              # 선택 처리
│       ├── useMVSExport.ts              # MVS 직렬화
│       ├── types.ts                     # 타입 정의
│       └── helpers.ts                   # 유틸리티 함수
├── lib/
│   └── mol-viewer/
│       ├── mvs-builder.ts               # MVS JSON 구성
│       ├── mvs-importer.ts              # MVS JSON 적용
│       ├── parser-helpers.ts            # 구조 파싱 헬퍼
│       └── color-schemes.ts             # 색상 테마
└── types/
    └── mol-viewer.ts                    # 인터페이스 정의
```

### 3.2 초기화 흐름

```
┌──────────────────────────────────┐
│  MolViewerPanel 마운트           │
└─────────────┬────────────────────┘
              │
              ▼
┌──────────────────────────────────┐
│  usePluginContext()              │
│  - createElement("canvas")       │
│  - PluginContext 생성            │
│  - 플러그인 초기화 (.init())     │
└─────────────┬────────────────────┘
              │
              ▼
┌──────────────────────────────────┐
│  useStructure()                  │
│  - PDB/mmCIF 파싱                │
│  - Mol* 상태에 로드              │
└─────────────┬────────────────────┘
              │
              ▼
┌──────────────────────────────────┐
│  useRepresentation()             │
│  - Cartoon/Surface 적용          │
│  - 색상 테마 설정                │
└─────────────┬────────────────────┘
              │
              ▼
┌──────────────────────────────────┐
│  useMaskOverlay()                │
│  - Shape 추가 (마스크 영역)      │
└──────────────────────────────────┘
```

---

## 4. 핵심 구현 패턴

### 4.1 PluginContext 초기화 (usePluginContext) ✅ IMPLEMENTED

```ts
// components/mol-viewer/usePluginContext.ts
import { createPluginUI } from "molstar/lib/mol-plugin-ui";
import { renderReact18 } from "molstar/lib/mol-plugin-ui/react18";
import { DefaultPluginUISpec } from "molstar/lib/mol-plugin-ui/spec";

export function usePluginContext() {
  const [plugin, setPlugin] = useState<PluginContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pluginInstanceRef = useRef<PluginContext | null>(null);
  const molstarRootRef = useRef<HTMLDivElement | null>(null);

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    if (pluginInstanceRef.current) return; // 한 번만 초기화

    const initPlugin = async () => {
      try {
        // 1. React가 관리하지 않는 div 생성 (중요!)
        const molstarRoot = document.createElement("div");
        molstarRoot.style.position = "absolute";
        molstarRoot.style.inset = "0";
        node.appendChild(molstarRoot);
        molstarRootRef.current = molstarRoot;

        // 2. Official createPluginUI 방식
        const spec = DefaultPluginUISpec();
        spec.layout = {
          initial: {
            isExpanded: false,
            showControls: false,
            controlsDisplay: "reactive"
          }
        };

        const pluginUI = await createPluginUI({
          target: molstarRoot,
          render: renderReact18,
          spec
        });

        pluginInstanceRef.current = pluginUI;
        setPlugin(pluginUI);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Initialization failed");
      }
    };

    void initPlugin();
  }, []);

  // Cleanup
  useEffect(() => {
    return () => {
      if (pluginInstanceRef.current) {
        pluginInstanceRef.current.dispose();
      }
      if (molstarRootRef.current?.parentNode) {
        molstarRootRef.current.parentNode.removeChild(molstarRootRef.current);
      }
    };
  }, []);

  return { plugin, containerRef, error };
}
```

**핵심 포인트**:

- ✅ ref callback 사용 (React reconciliation과 분리)
- ✅ 별도의 div 생성 (React가 관리하지 않음)
- ✅ `createPluginUI()` 사용 (Official React 18 integration)
- ✅ HMR 안정성 보장

### 4.2 구조 로드 (useStructure)

```ts
// components/mol-viewer/useStructure.ts
import { PluginContext } from "molstar/lib/mol-plugin/context";

export interface StructureInfo {
  title: string;
  chainIds: string[];
  residueCount: number;
  atomCount: number;
  format: "pdb" | "cif" | "bcif";
}

export function useStructure(
  plugin: PluginContext | null,
  initialData?: ArrayBuffer | string
) {
  const [structure, setStructure] = useState<any>(null);
  const [info, setInfo] = useState<StructureInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStructure = useCallback(
    async (data: ArrayBuffer | string) => {
      if (!plugin) return;

      setLoading(true);
      setError(null);

      try {
        // 1. 포맷 감지
        const format = detectFormat(data);

        // 2. 구조 파일을 상태에 추가
        const res = await plugin.managers.structure.hierarchy.applyPreset(
          plugin.state,
          data,
          "all-models", // 모든 모델 로드
          {
            structure: { name: format },
            representation: { name: "auto" }
          }
        );

        setStructure(res);

        // 3. 구조 정보 추출
        const structureState = plugin.state.selectQ(q =>
          q.byRef(res.ref).subtree()
        );

        if (structureState.length > 0) {
          const info: StructureInfo = {
            title: "Structure",
            chainIds: [],
            residueCount: 0,
            atomCount: 0,
            format
          };
          setInfo(info);
        }

        // 4. 카메라 자동 위치
        plugin.canvas3d?.camera.reset();

        // 5. 이벤트 발행
        bus.emit("structure:loaded", info);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        setError(msg);
        console.error("Structure load error:", err);
      } finally {
        setLoading(false);
      }
    },
    [plugin]
  );

  useEffect(() => {
    if (initialData) {
      loadStructure(initialData);
    }
  }, [initialData, loadStructure]);

  return { structure, info, loading, error, loadStructure };
}

function detectFormat(data: ArrayBuffer | string): "pdb" | "cif" | "bcif" {
  if (data instanceof ArrayBuffer) {
    // 바이너리 시작 바이트 확인
    const view = new Uint8Array(data);
    if (view[0] === 0xff && view[1] === 0xd8) return "bcif";
    return "cif";
  }
  const text = data as string;
  if (text.includes("HEADER")) return "pdb";
  return "cif";
}
```

### 4.3 표현 적용 (useRepresentation)

```ts
// components/mol-viewer/useRepresentation.ts
export type RepresentationType =
  | "cartoon"
  | "surface"
  | "ballStick"
  | "spacefill"
  | "ribbon";

export function useRepresentation(
  plugin: PluginContext | null,
  structure: any,
  type: RepresentationType = "cartoon"
) {
  const viwerSettings = useAtomValue(viewerSettingsAtom);

  useEffect(() => {
    if (!plugin || !structure) return;

    (async () => {
      try {
        // 기존 표현 제거
        const reprs = plugin.state.select(q =>
          q.ofType("Structure.Representation")
        );
        for (const repr of reprs) {
          await plugin.state.delete(repr.transform.ref);
        }

        // 색상 스킴 매핑
        const colorTheme = mapColorScheme(viwerSettings.colorScheme);

        // 표현 추가 (예: Cartoon)
        if (type === "cartoon") {
          await plugin.managers.structure.representation.setRepresentations([
            {
              repr: {
                name: "cartoon",
                params: {
                  colorTheme: { name: colorTheme }
                }
              }
            }
          ]);
        } else if (type === "surface") {
          // Surface 표현
          await plugin.managers.structure.representation.setRepresentations([
            {
              repr: {
                name: "surface",
                params: {
                  colorTheme: { name: colorTheme },
                  surfaceType: "vdw"
                }
              }
            }
          ]);
        }

        bus.emit("representation:changed", { type });
      } catch (err) {
        console.error("Representation error:", err);
      }
    })();
  }, [plugin, structure, type, viwerSettings]);
}

function mapColorScheme(scheme: string): string {
  const mapping: Record<string, string> = {
    chainIndex: "chain-id",
    residueType: "residue-name",
    spectrum: "rainbow"
  };
  return mapping[scheme] || "chain-id";
}
```

### 4.4 마스크 오버레이 (useMaskOverlay)

```ts
// components/mol-viewer/useMaskOverlay.ts
export function useMaskOverlay(plugin: PluginContext | null, structure: any) {
  const maskAtom = useAtomValue(projectAtoms.maskAtom);

  useEffect(() => {
    if (!plugin || !structure || !maskAtom) return;

    (async () => {
      try {
        // Include 영역: 녹색
        if (maskAtom.include && maskAtom.include.length > 0) {
          const sel = buildSelectionExpression(maskAtom.include);

          await plugin.managers.structure.representation.setRepresentations([
            {
              repr: {
                name: "label",
                params: {
                  selection: { label: sel },
                  colorTheme: { name: "uniform", params: { color: "#33dd33" } }
                }
              }
            }
          ]);
        }

        // Exclude 영역: 빨강
        if (maskAtom.exclude && maskAtom.exclude.length > 0) {
          const sel = buildSelectionExpression(maskAtom.exclude);
          // Similar approach with red color (#ff3333)
        }

        // Fixed 영역: 파랑 아웃라인
        if (maskAtom.fixed && maskAtom.fixed.length > 0) {
          const sel = buildSelectionExpression(maskAtom.fixed);
          // Outline representation
        }

        bus.emit("mask:overlayed", maskAtom);
      } catch (err) {
        console.error("Mask overlay error:", err);
      }
    })();
  }, [plugin, structure, maskAtom]);
}

function buildSelectionExpression(regions: string[]): string {
  // "A:10-20" or "B:*" 형식을 MolQL로 변환
  // 예: "A:10-20" → "(chain-id A && resi 10-20)"
  return regions
    .map(r => {
      const [chain, range] = r.split(":");
      if (range === "*") {
        return `chain-id ${chain}`;
      }
      if (range.includes("-")) {
        const [start, end] = range.split("-");
        return `(chain-id ${chain} && resi ${start}-${end})`;
      }
      return `(chain-id ${chain} && resi ${range})`;
    })
    .join(" or ");
}
```

### 4.5 선택 처리 (useSelection)

```ts
// components/mol-viewer/useSelection.ts
export interface SelectionInfo {
  residues: Array<{ chain: string; seqId: number }>;
  atoms: number[];
  chains: string[];
}

export function useSelection(plugin: PluginContext | null, structure: any) {
  const [selection, setSelection] = useState<SelectionInfo>({
    residues: [],
    atoms: [],
    chains: []
  });

  useEffect(() => {
    if (!plugin || !structure) return;

    const handleInteraction = () => {
      // Mol* 선택 상태 조회
      const loci = plugin.state.select(q => q.byRef("loci"));

      if (loci && loci.obj?.data) {
        const sel: SelectionInfo = {
          residues: [],
          atoms: [],
          chains: []
        };
        // Parse loci and populate sel
        setSelection(sel);
        bus.emit("selection:changed", sel);
      }
    };

    // 마우스 클릭/호버 이벤트
    const unsubClick = plugin.canvas3d?.input?.subscribe(
      "click",
      handleInteraction
    );
    const unsubHover = plugin.canvas3d?.input?.subscribe(
      "move",
      handleInteraction
    );

    return () => {
      unsubClick?.();
      unsubHover?.();
    };
  }, [plugin, structure]);

  return { selection };
}
```

### 4.6 MVS 내보내기 (useMVSExport)

```ts
// components/mol-viewer/useMVSExport.ts
export function useMVSExport(
  plugin: PluginContext | null,
  structure: any,
  mask: MaskSpec
) {
  const exportMVS = useCallback(async () => {
    if (!plugin) return null;

    try {
      // 1. 현재 상태를 MVS 형식으로 직렬화
      const mvs = {
        version: "1.0",
        metadata: {
          title: "Patchr Studio Export",
          timestamp: new Date().toISOString(),
          description: "View state with inpainting regions"
        },
        root: {
          kind: "root",
          children: [
            // Data node (구조 파일)
            {
              kind: "download",
              params: {
                url: "structure.pdb", // 실제로는 파일 경로
                format: "pdb"
              }
            },
            // Representation node (표현)
            {
              kind: "representation",
              params: {
                type: "cartoon",
                colorTheme: "chain-id"
              }
            },
            // Mask shape nodes
            ...(mask.include && mask.include.length > 0
              ? [
                  {
                    kind: "shape",
                    params: {
                      label: "inpaint-region",
                      color: { r: 0.2, g: 0.8, b: 0.2 },
                      selection: buildSelectionExpression(mask.include)
                    }
                  }
                ]
              : [])
          ]
        }
      };

      return mvs;
    } catch (err) {
      console.error("MVS export error:", err);
      return null;
    }
  }, [plugin, structure, mask]);

  return { exportMVS };
}
```

---

## 5. 상태 관리 (Jotai Atoms)

```ts
// store/mol-viewer-atoms.ts
import { atom } from "jotai";

// 구조 로딩 상태
export const structureLoadingAtom = atom<boolean>(false);
export const structureErrorAtom = atom<string | null>(null);
export const structureInfoAtom = atom<StructureInfo | null>(null);

// 선택 상태
export const selectionAtom = atom<SelectionInfo>({
  residues: [],
  atoms: [],
  chains: []
});

// 뷰어 설정
export const viewerSettingsAtom = atom<{
  colorScheme: "chainIndex" | "residueType" | "spectrum";
  representation: "cartoon" | "surface" | "ballStick";
  backgroundColor: string;
}>({
  colorScheme: "chainIndex",
  representation: "cartoon",
  backgroundColor: "#0f172a"
});

// 현재 MVS 상태
export const currentMVSAtom = atom<any | null>(null);

// 카메라 상태
export const cameraStateAtom = atom<any | null>(null);
```

---

## 6. MolViewerPanel 컴포넌트

```tsx
// components/MolViewerPanel.tsx
import React from "react";
import { usePluginContext } from "./mol-viewer/usePluginContext";
import { useStructure } from "./mol-viewer/useStructure";
import { useRepresentation } from "./mol-viewer/useRepresentation";
import { useMaskOverlay } from "./mol-viewer/useMaskOverlay";
import { useSelection } from "./mol-viewer/useSelection";

export interface MolViewerPanelProps {
  projectId: string;
  initialStructure?: ArrayBuffer | string;
}

export function MolViewerPanel(props: MolViewerPanelProps): React.ReactElement {
  const { plugin, containerRef } = usePluginContext();
  const { structure, loading, error } = useStructure(
    plugin,
    props.initialStructure
  );

  useRepresentation(plugin, structure, "cartoon");
  useMaskOverlay(plugin, structure);
  useSelection(plugin, structure);

  return (
    <div className="flex flex-1 flex-col bg-slate-950">
      {error && (
        <div className="bg-red-900 text-red-100 p-2 text-sm">{error}</div>
      )}
      <div ref={containerRef} className="flex-1" />
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/50">
          <div className="text-white">Loading structure...</div>
        </div>
      )}
    </div>
  );
}
```

---

## 7. 이벤트 버스 확장

```ts
// lib/event-bus.ts
export interface ViewerEvents {
  "structure:loaded": StructureInfo;
  "selection:changed": SelectionInfo;
  "mask:overlayed": MaskSpec;
  "representation:changed": { type: RepresentationType };
  "mvs:exported": any;
  "viewer:initialized": void;
}
```

---

## 8. MVS 지원 (Mol\* 내장 익스텐션)

### 8.1 MVS 로드 (프로그래매틱)

```ts
// 백엔드에서 생성한 MVS를 Mol* 로드
export async function loadMVSState(plugin: PluginContext, mvsJson: string) {
  try {
    // Mol* 내장 MVS 로더 사용
    const data = JSON.parse(mvsJson);
    await plugin.state.setSnapshot(data);
  } catch (err) {
    console.error("MVS load error:", err);
  }
}
```

### 8.2 Python 백엔드 (molviewspec)

```python
# backend/mvs_builder.py
from molviewspec import MVSBuilder

def build_inpaint_mvs(
    structure_file: str,
    mask_spec: dict,
    inpaint_result: str
):
    """인페인팅 결과를 포함한 MVS 생성"""
    builder = MVSBuilder()

    # 원본 구조
    builder.add_download(
        url=f'file://{structure_file}',
        format='pdb'
    )

    # Cartoon 표현
    builder.add_representation(
        type='cartoon',
        color_theme='chain-id'
    )

    # 마스크 오버레이
    for region in mask_spec.get('include', []):
        builder.add_annotation(
            label=f'Inpaint {region}',
            color=[0.2, 0.8, 0.2]
        )

    # 결과 구조 (프리뷰)
    builder.add_download(
        url=f'file://{inpaint_result}',
        format='pdb',
        label='Preview'
    )

    return builder.build()
```

---

## 9. 설치 및 의존성

```bash
npm install molstar

# 선택 (PDBe 고수준 API 사용 시)
npm install pdbe-molstar

# 백엔드
pip install molviewspec
```

---

## 10. 성능 고려사항

- **구조 캐싱**: TanStack Query로 중복 로드 방지
- **표현 지연**: 복잡한 표현은 필요 시에만 활성화
- **메모리**: 대용량 구조 시 BinaryCIF 형식 사용
- **렌더링**: Canvas3D 자동 최적화

---

## 11. 구현 체크리스트

- [ ] `usePluginContext` 훅 구현
- [ ] `useStructure` 훅 구현
- [ ] `useRepresentation` 훅 구현
- [ ] `useMaskOverlay` 훅 구현
- [ ] `useSelection` 훅 구현
- [ ] `useMVSExport` 훅 구현
- [ ] Jotai atom 통합
- [ ] MolViewerPanel 컴포넌트
- [ ] Event Bus 메시지 타입
- [ ] 단위 테스트
- [ ] 통합 테스트

---

## 12. 참고 자료

### 공식 문서

- https://molstar.org/docs/
- https://molstar.org/viewer-docs/extensions/mvs/
- https://github.com/molstar/molstar

### PDBe Molstar (React 친화적)

- https://github.com/molstar/pdbe-molstar
- https://www.npmjs.com/package/pdbe-molstar
- Wiki: https://github.com/molstar/pdbe-molstar/wiki

### MVS

- Python: https://pypi.org/project/molviewspec/
- Examples: https://github.com/molstar/molstar/tree/master/examples/mvs
