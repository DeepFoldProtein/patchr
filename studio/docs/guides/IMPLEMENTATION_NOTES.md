# Mol\* Viewer 구현 노트

> 실제 구현 경험 기반의 팁, 주의사항, 해결한 이슈들

## 1. React 18 통합 시 주의사항

### 1.1 HMR (Hot Module Replacement) 문제 ⚠️

**문제**: Mol\*가 내부에 자체 React root를 생성하면서 React reconciler와 DOM 조작이 충돌

```
Error: NotFoundError: Failed to execute 'removeChild' on 'Node':
The node to be removed is not a child of this node.
```

**원인**:

- `createPluginUI()`는 Mol\*의 자체 React root를 생성
- React parent와 Mol\*의 내부 React 트리가 같은 DOM에서 경쟁
- HMR 중 React reconciliation과 Mol\*의 DOM 조작이 동시에 발생

### 1.2 해결책: 완전히 격리된 DOM 트리

```typescript
// ✅ 최종 해결책: DOM 생성을 JavaScript로 직접 처리
export function usePluginContext() {
  const pluginInstanceRef = useRef<PluginContext | null>(null);
  const molstarRootRef = useRef<HTMLDivElement | null>(null);

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    if (pluginInstanceRef.current) return; // 한 번만 초기화

    // 1️⃣ React가 관리하지 않는 별도의 div 생성
    const molstarRoot = document.createElement("div");
    molstarRoot.style.position = "absolute";
    molstarRoot.style.inset = "0";

    // 2️⃣ React ref의 div에 직접 추가
    node.appendChild(molstarRoot);
    molstarRootRef.current = molstarRoot;

    // 3️⃣ 이 div에만 Mol* 마운트
    const spec = DefaultPluginUISpec();
    spec.layout = {
      initial: {
        isExpanded: false,
        showControls: false,
        controlsDisplay: "reactive"
      }
    };

    createPluginUI({
      target: molstarRoot, // ← React가 모르는 div!
      render: renderReact18,
      spec
    }).then(plugin => {
      pluginInstanceRef.current = plugin;
      setPlugin(plugin);
    });
  }, []);

  // Cleanup은 useEffect에서만
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

  return { plugin, containerRef };
}
```

**핵심 원리**:

```
React 관리 영역:
<div ref={containerRef}>  ← React가 이 div만 관리
  <div>                   ← JavaScript가 동적 생성
    [Mol* React root]     ← React가 모르는 영역
  </div>
</div>
```

### 1.3 ref callback vs useEffect

❌ **잘못된 방식**: `useEffect` + `useRef`

```typescript
const containerRef = useRef<HTMLDivElement | null>(null);
useEffect(() => {
  if (!containerRef.current) return;
  // 이미 React가 DOM을 관리 중 - 충돌 가능성!
}, []);
```

✅ **올바른 방식**: ref callback

```typescript
const containerRef = useCallback((node: HTMLDivElement | null) => {
  if (!node) return;
  // DOM 생성 직후 즉시 호출되므로 더 안전
  initMolstar(node);
}, []);
```

---

## 2. `createPluginUI()` vs 수동 PluginContext

### 2.1 처음 시도 (실패)

```typescript
// ❌ 이 방식은 canvas3d가 생성되지 않음
const spec = DefaultPluginSpec();
const plugin = new PluginContext(spec);
await plugin.init();
// canvas3d가 null!
```

**이유**: `DefaultPluginSpec()`은 UI 없이 기본 플러그인만 생성

### 2.2 올바른 방식 (성공)

```typescript
// ✅ createPluginUI 사용 - canvas3d 자동 생성
import { createPluginUI } from "molstar/lib/mol-plugin-ui";
import { renderReact18 } from "molstar/lib/mol-plugin-ui/react18";
import { DefaultPluginUISpec } from "molstar/lib/mol-plugin-ui/spec";

const spec = DefaultPluginUISpec();
const plugin = await createPluginUI({
  target: htmlElement,
  render: renderReact18,
  spec
});
// canvas3d가 자동으로 생성됨 ✓
```

**핵심**: `createPluginUI()`는 Mol\*의 **official React integration** 방식

---

## 3. 구조 로드 패턴

### 3.1 rawData() 사용 (CSP 준수)

```typescript
// ❌ Blob URL - CSP 경고
const blob = new Blob([pdbContent], { type: "text/plain" });
const url = URL.createObjectURL(blob);
await plugin.builders.data.download({ url }, { state: { isGhost: true } });

// ✅ rawData() - 직접 데이터 전달
const data = plugin.builders.data.rawData({
  data:
    pdbContent.length > 1000 ? new TextEncoder().encode(pdbContent) : pdbContent
});
```

**이유**: Electron 환경의 Content Security Policy 호환성

### 3.2 구조 파싱 (올바른 순서)

```typescript
// 데이터 → Trajectory → Hierarchy → 카메라 리셋
const data = await plugin.builders.data.rawData({ data: pdbContent });
const trajectory = await plugin.builders.structure.parseTrajectory(data, "pdb");
await plugin.builders.structure.hierarchy.applyPreset(trajectory, "default");
await plugin.canvas3d?.camera.reset();
```

---

## 4. Mol\* UI 패널 숨기기

### 4.1 CSS 규칙 (효과적)

```css
/* src/assets/base.css */
.msp-layout-left,
.msp-layout-right,
.msp-layout-top,
.msp-layout-bottom {
  display: none !important;
}

.msp-layout-main {
  position: absolute !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
}
```

### 4.2 UI Spec 설정 (보완)

```typescript
const spec = DefaultPluginUISpec();
spec.layout = {
  initial: {
    isExpanded: false,
    showControls: false,
    controlsDisplay: "reactive"
  }
};
spec.components = {
  controls: { left: "none", right: "none", top: "none", bottom: "none" }
};
```

---

## 5. 이벤트 처리 및 상태 동기화

### 5.1 Observable 구독 패턴

```typescript
import { useBehavior } from "molstar/lib/mol-plugin-ui/hooks/use-behavior";

// Mol* Behavior (RxJS Observable)를 React state와 동기화
export function useStructureInfo(plugin: PluginContext | null) {
  // Option 1: useBehavior hook 사용
  const loading = useBehavior(plugin?.behaviors.state.isBusy);

  // Option 2: 직접 구독
  useEffect(() => {
    if (!plugin) return;

    const sub = plugin.events.canvas3d.settingsUpdated.subscribe(() => {
      console.log("Canvas settings updated");
    });

    return () => sub.unsubscribe();
  }, [plugin]);
}
```

### 5.2 Mol\* State Tree 구조

```typescript
// Mol* 상태 트리 네비게이션
const root = plugin.state.root;
const children = plugin.state.selectQ(q => q.byRef(root.ref).children());

children.forEach(cell => {
  console.log(`${cell.transform.prettyLabel}:`, cell.obj?.data);
});
```

---

## 6. 마스크 오버레이 구현

### 6.1 선택 표현식 (Selection Expressions)

```typescript
// MolQL 형식으로 원자/잔기 선택
function buildMaskExpression(regions: string[]): string {
  // 예: ["A:10-20", "B:5"] → "(chain-id A && resi 10-20) or (chain-id B && resi 5)"
  return regions
    .map(r => {
      const [chain, range] = r.split(":");
      if (range === "*") return `chain-id ${chain}`;
      if (range.includes("-")) {
        const [start, end] = range.split("-");
        return `(chain-id ${chain} && resi ${start}-${end})`;
      }
      return `(chain-id ${chain} && resi ${range})`;
    })
    .join(" or ");
}

// Mol*에 적용
const expr = buildMaskExpression(["A:10-20", "B:*"]);
const selection = plugin.builders.structure.tryCreateSelection(expr);
```

### 6.2 Shape로 마스크 시각화

```typescript
// Shape API를 사용한 마스크 오버레이
const shapeGroup = plugin.builders.shape.createGroup();

// Include 영역 (녹색)
plugin.builders.shape.addRepresentation("surface", {
  shapeGroup,
  color: 0x33dd33,
  selection: buildMaskExpression(mask.include)
});

// Exclude 영역 (빨강)
plugin.builders.shape.addRepresentation("surface", {
  shapeGroup,
  color: 0xff3333,
  selection: buildMaskExpression(mask.exclude),
  opacity: 0.3
});
```

---

## 7. 성능 최적화

### 7.1 메모리 문제

```typescript
// ❌ 큰 구조 로드 시 메모리 부족
const pdbContent = await response.text(); // 10MB+ 텍스트

// ✅ 바이너리 형식 사용
const bcifContent = await response.arrayBuffer(); // 1-2MB 바이너리
```

### 7.2 표현 체인 최적화

```typescript
// 불필요한 표현 제거
const representations = plugin.state.selectQ(q =>
  q.ofType("Structure.Representation")
);
for (const repr of representations) {
  await plugin.state.delete(repr.transform.ref);
}

// 필요한 표현만 추가
await plugin.builders.structure.representation.addRepresentation(structure, {
  name: "cartoon",
  colorTheme: { name: "chain-id" }
});
```

---

## 8. MSW (Mock Service Worker) 이슈

### 8.1 MIME 타입 에러

```
Error: [MSW] Failed to register the Service Worker:
The script has an unsupported MIME type ('text/html').
```

**해결책**: 개발 중 필요 없으면 비활성화

```typescript
// App.tsx
if (import.meta.env.DEV) {
  // MSW disabled - not needed for molecular viewer development
}
```

---

## 9. 타입 안정성

### 9.1 Mol\* 타입 정의

```typescript
// types/mol-viewer.ts
import type { PluginContext } from "molstar/lib/mol-plugin/context";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";

export interface MolViewerState {
  plugin: PluginContext | null;
  loading: boolean;
  error: string | null;
  structure: any;
  selection: SelectionInfo;
}

export interface SelectionInfo {
  residues: Array<{ chain: string; seqId: number }>;
  atoms: number[];
  chains: string[];
}
```

### 9.2 타입 가드

```typescript
function assertPluginInitialized(
  plugin: PluginContext | null
): asserts plugin is PluginContext {
  if (!plugin) throw new Error("Plugin not initialized");
}
```

---

## 10. 디버깅 팁

### 10.1 콘솔 로그 활용

```typescript
// Mol* 상태 확인
console.log("Plugin initialized:", plugin.isInitialized);
console.log("Canvas3D:", plugin.canvas3d);
console.log("State tree:", plugin.state.root);
console.log("Camera:", plugin.canvas3d?.camera.getState());
```

### 10.2 Electron DevTools

```bash
# Electron main/preload 프로세스 디버깅
# DevTools 자동 열기
npm run dev  # 기본 포함

# 수동 열기: Ctrl+Shift+I (Windows/Linux) 또는 Cmd+Option+I (macOS)
```

---

## 11. 상태 관리 아키텍처 (Jotai + Zustand)

### 11.1 계층적 상태 관리

Patchr Studio는 상태의 생명주기에 따라 다른 도구를 사용합니다:

```
┌─────────────────────────────────────┐
│   React Component Props/State       │
│   (UI 이벤트 핸들링, 입력값)        │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│   Jotai Atoms                       │
│   (컴포넌트 간 상태 공유)            │
│   - Mask specifications             │
│   - Inpaint parameters              │
│   - Tab selection                   │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│   Zustand Stores                    │
│   (전역 상태 + 부수효과)            │
│   - Preview streaming state         │
│   - Interval management             │
│   - Cache & history                 │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│   TanStack Query                    │
│   (서버 데이터 캐싱)                 │
│   - API 응답 캐싱                   │
│   - Background refetch              │
│   - 자동 동기화                     │
└─────────────────────────────────────┘
```

### 11.2 Preview State의 Zustand 관리 (중요!)

**문제**: 다른 탭으로 전환하면 React 컴포넌트가 unmount되어 setInterval도 중단됨

```typescript
// ❌ 잘못된 방식 (InpaintTab component 내부)
export function InpaintTab() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed(prev => prev + 1); // ← unmount되면 멈춤
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  return <div>Elapsed: {elapsed}s</div>;
}
```

**해결책**: Zustand store 내부에서 interval 관리

```typescript
// ✅ 올바른 방식 (preview-store.ts)
export const usePreviewStore = create<PreviewStore>((set, get) => ({
  startPreview: (runId, totalDuration, onComplete) => {
    // interval을 Window 스코프에서 관리 (React와 무관)
    let progressInterval: number | null = window.setInterval(() => {
      const state = get(); // Zustand에서 현재 상태 직접 접근
      const newElapsed = state.elapsed_s + 1;

      if (newElapsed >= totalDuration) {
        clearInterval(progressInterval);
        onComplete(state.frames);
      } else {
        set({
          elapsed_s: newElapsed,
          remaining_s: Math.max(0, totalDuration - newElapsed),
          progress: (newElapsed / totalDuration) * 100
        });
      }
    }, 1000);
  },

  completePreview: frames => {
    // 완료 시 interval 정리 (자동)
    set(state => ({
      isRunning: false,
      progress: 100,
      frames: frames || state.frames
    }));
  }
}));
```

**컴포넌트 사용**:

```typescript
export function InpaintTab() {
  const { isRunning, progress, elapsed_s, startPreview } = usePreviewStore();

  const handleGenerate = () => {
    // Zustand가 자동으로 interval 관리
    startPreview(`run-${Date.now()}`, 5, () => {
      // 완료 콜백
    });
  };

  return (
    <div>
      {isRunning && <div>Progress: {progress}% ({elapsed_s}s)</div>}
      <button onClick={handleGenerate}>Generate</button>
    </div>
  );
}

// 다른 탭으로 전환해도 progress는 계속 진행됨!
```

### 11.3 Jotai vs Zustand 비교

| 구분             | Jotai                 | Zustand                 |
| ---------------- | --------------------- | ----------------------- |
| **스코프**       | 컴포넌트 트리         | 전역 (window)           |
| **마운트**       | 컴포넌트 의존         | 독립적                  |
| **Side effects** | useEffect 필요        | 액션 내부에서 직접 처리 |
| **적합한 용도**  | UI 상태, 폼 입력값    | 전역 상태, async 작업   |
| **번들 크기**    | ~5KB                  | ~3KB                    |
| **예제**         | Tab 선택, 마스크 설정 | Progress 진행률, 캐시   |

### 11.4 계층 결정 기준

```
상태 생성 → 컴포넌트 내 useState
         ↓
         여러 컴포넌트에서 필요?
         ├─ Yes → Jotai atoms
         └─ No → 유지 (useState)
              ↓
              React 라이프사이클 외에서 실행 필요?
              ├─ Yes → Zustand
              └─ No → Jotai로 충분
                   ↓
                   서버에서 데이터?
                   ├─ Yes → TanStack Query
                   └─ No → 위의 선택대로
```

---

## 13. Sequence Viewer 통합

### 13.1 문제: Mol\* 내장 UI와 커스텀 레이아웃의 충돌

**시도한 방법들**:

1. ❌ `spec.layout.regionState.top: "full"` + `isExpanded: false` → `display: none` 문제
2. ❌ `PluginCommands.Layout.Update()` → 여전히 표시 안 됨
3. ❌ CSS `!important` override → toolbar와 겹침

**근본 원인**:

- Mol\*의 sequence panel은 전체 layout 시스템의 일부
- `isExpanded: false`일 때 CSS에서 강제로 `display: none` 적용
- 우리 앱의 Toolbar와 Mol\*의 top region이 같은 z-index에서 충돌

### 13.2 해결책: 별도 컨테이너에 SequenceView 렌더링

```typescript
// useSequenceViewer.tsx - Mol* SequenceView를 커스텀 위치에 렌더링
import { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { createRoot } from "react-dom/client";
import { PluginContextContainer } from "molstar/lib/mol-plugin-ui/plugin";
import { SequenceView } from "molstar/lib/mol-plugin-ui/sequence";

export function useSequenceViewer(
  plugin: PluginUIContext | null,
  containerId: string
) {
  useEffect(() => {
    if (!plugin) return;

    const container = document.getElementById(containerId);
    if (!container) return;

    const root = createRoot(container);
    root.render(
      <PluginContextContainer plugin={plugin}>
        <SequenceView />
      </PluginContextContainer>
    );

    return () => root.unmount();
  }, [plugin, containerId]);
}
```

**사용 예시**:

```tsx
// MolViewerPanel.tsx
function MolViewerPanelInner() {
  const { plugin, containerRef } = usePluginContext();

  // Sequence panel을 별도 영역에 렌더링
  useSequenceViewer(plugin, "sequence-panel-container");

  return (
    <div className="flex h-full flex-col">
      {/* Sequence viewer - 상단 고정 */}
      <div
        id="sequence-panel-container"
        className="bg-slate-900 border-b"
        style={{ minHeight: "100px", maxHeight: "150px" }}
      />

      {/* 3D viewer - 나머지 공간 */}
      <div ref={containerRef} className="flex-1" />
    </div>
  );
}
```

**spec 설정** (Mol\* 내장 controls 모두 숨김):

```typescript
const spec = DefaultPluginUISpec();
spec.layout = {
  initial: {
    isExpanded: false,
    showControls: false // 모든 내장 UI 숨김
  }
};
spec.components = {
  controls: {
    top: "none", // Sequence는 별도로 렌더링
    left: "none",
    right: "none",
    bottom: "none"
  }
};
```

### 13.3 PluginContext vs PluginUIContext

**중요**: Sequence viewer와 같은 UI 컴포넌트를 사용하려면 `PluginUIContext`를 사용해야 합니다.

```typescript
// ❌ 잘못된 타입
import { PluginContext } from "molstar/lib/mol-plugin/context";
export function usePluginContext(): { plugin: PluginContext | null } { ... }

// ✅ 올바른 타입
import { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
export function usePluginContext(): { plugin: PluginUIContext | null } { ... }
```

**이유**:

- `PluginContext`: 기본 플러그인 (UI 없음)
- `PluginUIContext`: UI 컴포넌트 포함 (`customParamEditors`, `customUIState` 등)
- `PluginContextContainer`와 `SequenceView`는 `PluginUIContext` 필요

### 13.4 레이아웃 최종 구조

```
┌─────────────────────────────────────┐
│  App Toolbar (React)                │
├─────────────────────────────────────┤
│  Sequence Viewer (Mol* SequenceView)│  ← 별도 컨테이너
│  Chain A | Chain B | ...            │
├─────────────────────────────────────┤
│  Mol* 3D Viewer (canvas3d)          │
│  (내장 controls 모두 숨김)          │
│                                     │
│                                     │
└─────────────────────────────────────┘
```

**장점**:

- ✅ Toolbar와 겹치지 않음
- ✅ Mol\*의 layout 시스템 우회
- ✅ 커스텀 스타일링 가능
- ✅ React lifecycle과 독립적

---

## 14. Missing Region Detection 구현

### 14.1 자동 Gap 감지

```typescript
// useMissingRegionDetection.ts
export function useMissingRegionDetection(
  plugin: PluginUIContext | null,
  enabled: boolean
) {
  const [gaps, setGaps] = useAtom(missingRegionsDetectedAtom);

  useEffect(() => {
    if (!plugin || !enabled) return;

    // 구조 로드 이벤트 구독
    const sub = bus.on("structure:loaded", async () => {
      const structures = plugin.state.data.select(
        StateSelection.Generators.rootsOfType(PSO.Molecule.Structure)
      );

      for (const structureCell of structures) {
        const structure = structureCell.obj?.data;
        if (!structure) continue;

        // 체인별로 missing residues 확인
        for (const unit of structure.units) {
          if (!Unit.isAtomic(unit)) continue;

          const { residueAtomSegments } = unit.model.atomicHierarchy;
          const gaps = detectMissingResidues(residueAtomSegments);

          setGaps(gaps);
        }
      }
    });

    return () => sub();
  }, [plugin, enabled]);
}
```

### 14.2 Missing Residues/Atoms 감지

```typescript
function detectMissingResidues(segments: SegmentArray): MissingRegionInfo[] {
  const gaps: MissingRegionInfo[] = [];

  for (let i = 0; i < segments.count - 1; i++) {
    const currSeqId = segments.seqId.value(i);
    const nextSeqId = segments.seqId.value(i + 1);

    // Sequence missing region detected
    if (nextSeqId - currSeqId > 1) {
      gaps.push({
        chainId: segments.chainId.value(i),
        startSeqId: currSeqId + 1,
        endSeqId: nextSeqId - 1,
        missingCount: nextSeqId - currSeqId - 1
      });
    }
  }

  return gaps;
}
```

---

## 15. Theme 동적 전환

### 15.1 Mol\* CSS 동적 로딩

```typescript
// usePluginContext.ts
useEffect(() => {
  if (!plugin) return;

  // 기존 CSS 제거
  const oldStyle = document.getElementById("molstar-theme-css");
  if (oldStyle) oldStyle.remove();

  // 테마에 맞는 CSS 동적 로드
  const cssPath = isDarkMode
    ? new URL("molstar/lib/mol-plugin-ui/skin/dark.scss", import.meta.url)
    : new URL("molstar/lib/mol-plugin-ui/skin/light.scss", import.meta.url);

  const link = document.createElement("link");
  link.id = "molstar-theme-css";
  link.rel = "stylesheet";
  link.href = cssPath.href;
  document.head.appendChild(link);

  // Canvas3D 배경색 변경
  const bgColor = isDarkMode
    ? Color.fromRgb(15, 23, 42) // slate-950
    : Color.fromRgb(248, 250, 252); // slate-50

  plugin.canvas3d?.setProps({
    renderer: {
      ...plugin.canvas3d.props.renderer,
      backgroundColor: bgColor
    }
  });
}, [plugin, isDarkMode]);
```

### 15.2 TailwindCSS 테마와 동기화

```typescript
// store/app-atoms.ts
export const themeClassAtom = atom<string>((get) => {
  const theme = get(themeAtom);
  return theme === "dark" ? "dark" : "";
});

// App.tsx
function App() {
  const [themeClass] = useAtom(themeClassAtom);

  return (
    <div className={themeClass}>
      {/* 전체 앱에 dark class 적용 */}
    </div>
  );
}
```

---

## 16. 배포 전 체크리스트

- [ ] ref callback 패턴 확인 (HMR 안정성)
- [ ] Mol\* 패널 CSS 숨김 확인
- [ ] Sequence viewer 별도 렌더링 확인
- [ ] Gap detection 자동 실행 확인
- [ ] 테마 전환 (dark/light) 테스트
- [ ] 메모리 누수 테스트 (여러 번 구조 로드)
- [ ] 타입 체크 완료 (`npm run typecheck`)
- [ ] CSP 호환성 확인 (blob URL 제거)
- [ ] 번들 크기 확인 (molstar ~2.5MB)
- [ ] 각 플랫폼에서 테스트 (macOS, Windows, Linux)

---

## 17. 참고 링크

- [Mol\* 공식 문서](https://molstar.org/docs/)
- [GitHub Issues - Mol\*/React 통합](https://github.com/molstar/molstar/discussions)
- [Electron 가이드](https://www.electronjs.org/docs)
- [React 18 마이그레이션](https://react.dev/blog/2022/03/29/react-v18)
