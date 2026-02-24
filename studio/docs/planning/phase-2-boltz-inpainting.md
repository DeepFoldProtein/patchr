# Phase 2: Real-time Inpainting Preview (Boltz-Inpainting 기반)

> **핵심 변경**: Diffusion-based 다단계 생성 → **한 번의 추론으로 최종 결과 반환** (Boltz 방식)

## 1. Boltz-Inpainting vs Diffusion 비교

| 구분          | Diffusion Inpainting                | Boltz-Inpainting                         |
| ------------- | ----------------------------------- | ---------------------------------------- |
| **추론 방식** | 반복적 노이즈 제거 (Denoising loop) | 한 번의 포워드 패스                      |
| **진행률**    | 각 스텝마다 중간 이미지 생성        | 전체 시간 (고정)                         |
| **스트리밍**  | 매 스텝마다 프레임 업데이트         | 최종 결과만 반환                         |
| **파라미터**  | steps, tau (timescale), guidance    | seeds, temperature, confidence_threshold |
| **결과 개수** | 1개 (또는 multiple seeds로 여러 개) | N개 (seed별 병렬 생성)                   |
| **속도**      | 느림 (스텝 수에 비례)               | 빠름 (고정 시간)                         |

## 2. Phase 2 워크플로우

```
사용자 인터페이스 (React)
┌────────────────────────────────┐
│  InpaintTab                    │
│  - 마스크 선택 (Mask Tab)     │
│  - 파라미터 설정:              │
│    • Seeds: [42, 43, 44]      │
│    • Temperature: 1.0          │
│    • Confidence threshold: 0.5 │
│  - "Generate" 버튼            │
└────────────────┬────────────────┘
                 │ (Click)
                 ▼
┌────────────────────────────────┐
│  usePreviewManager 훅           │
│  - 요청 생성                    │
│  - WebSocket 연결              │
│  - 프레임 처리                  │
└────────────────┬────────────────┘
                 │ WS: /api/inpaint/preview
                 ▼
┌────────────────────────────────┐
│  FastAPI 백엔드                │
│  - Boltz 모델 로드             │
│  - 마스크 적용                 │
│  - 병렬 추론 (seed별)          │
│  - 결과 스트리밍               │
└────────────────┬────────────────┘
                 │ WS: start → progress → frame(s) → complete
                 ▼
┌────────────────────────────────┐
│  MolViewerPanel                │
│  - 현재 프레임 표시            │
│  - 신뢰도 기반 시각화          │
│  - 진행률 바 (시간 기반)       │
└────────────────────────────────┘
```

## 3. API 프로토콜 설계

### 3.1 WebSocket 엔드포인트

```
WS ws://localhost:8000/api/inpaint/preview
```

#### 요청 (클라이언트 → 서버, JSON)

```json
{
  "project_id": "proj-123",
  "mask": {
    "version": 1,
    "units": "residue",
    "include": [{ "chain": "A", "residues": [10, 11, 12] }],
    "exclude": [],
    "fixed": [{ "chain": "B", "residues": [] }],
    "soft_shell_Ang": 3.0
  },
  "seeds": [42, 43, 44],
  "temperature": 1.0,
  "confidence_threshold": 0.5
}
```

#### 응답 시퀀스 (서버 → 클라이언트)

**1. 시작 메시지** (JSON)

```json
{
  "type": "start",
  "run_id": "run-20251025-abc123",
  "total_seeds": 3,
  "estimated_duration_s": 45,
  "timestamp": "2025-10-25T12:00:00Z"
}
```

**2. 진행 메시지** (JSON, 주기적 업데이트 - 예: 1초마다)

```json
{
  "type": "progress",
  "run_id": "run-20251025-abc123",
  "elapsed_s": 15,
  "remaining_s": 30,
  "progress_percent": 33,
  "current_seed_index": 0,
  "timestamp": "2025-10-25T12:00:15Z"
}
```

**3. 프레임 데이터** (바이너리, 각 seed별로 순차 전송)

```
[0-3]     : frameIndex (uint32_le, 0=seed[0], 1=seed[1], ...)
[4-7]     : totalFrames (uint32_le, total seeds)
[8-11]    : confidence (float32_le, 0.0-1.0)
[12-15]   : temperature (float32_le)
[16-19]   : plddt_mean (float32_le, 선택사항)
[20-255]  : 패딩
[256+]    : PDB 구조 데이터 (텍스트 형식)
```

**4. 완료 메시지** (JSON)

```json
{
  "type": "complete",
  "run_id": "run-20251025-abc123",
  "total_duration_s": 45,
  "frames_count": 3,
  "total_plddt": [0.82, 0.79, 0.85],
  "status": "success",
  "timestamp": "2025-10-25T12:00:45Z"
}
```

**5. 오류 메시지** (JSON)

```json
{
  "type": "error",
  "run_id": "run-20251025-abc123",
  "error": "Invalid mask specification",
  "details": "Residue range exceeds chain length",
  "timestamp": "2025-10-25T12:00:05Z"
}
```

### 3.2 주요 특징

- **단일 라운드 추론**: "시작 → 진행률 → 결과들 → 완료" (선형 흐름)
- **진행률은 시간 기반**: 남은 시간(ETA)을 표시
- **여러 결과**: seed별로 순차적으로 프레임 스트리밍
- **신뢰도 점수**: 각 구조의 pLDDT 스코어 포함

## 4. 프론트엔드 구현

### 4.0 상태 관리 아키텍처

**핵심 원칙**: 컴포넌트 상태(Jotai) vs 전역 상태(Zustand) 분리

```
┌─────────────────────────────────────────┐
│     InpaintTab Component (React)        │
│  ┌───────────────────────────────────┐  │
│  │ Component State (useState/Jotai)  │  │
│  │ - seeds (input value)             │  │
│  │ - temperature (slider)            │  │
│  │ - confidenceThreshold (slider)    │  │
│  │ - selectedFrameId (gallery)       │  │
│  └───────────────────────────────────┘  │
│              │                           │
│              ▼ (handleGenerate)          │
├─────────────────────────────────────────┤
│      Zustand Preview Store              │
│  (React 라이프사이클 독립적)             │
│  ┌───────────────────────────────────┐  │
│  │ Global State                      │  │
│  │ - isRunning                       │  │
│  │ - progress                        │  │
│  │ - elapsed_s, remaining_s          │  │
│  │ - frames[], currentFrame          │  │
│  │ - error, runId                    │  │
│  │                                   │  │
│  │ Interval Management               │  │
│  │ - progressInterval (Window scope) │  │
│  │ - 탭 전환해도 계속 진행           │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**이점**:

- ✅ 탭 전환해도 progress 계속 업데이트 (React 렌더링 독립)
- ✅ 자동 cleanup (cancelPreview, completePreview에서 interval 정리)
- ✅ 여러 컴포넌트에서 상태 구독 가능
- ✅ 복잡한 useEffect/useRef 로직 불필요

### 4.1 타입 정의 업데이트

```typescript
// types/index.ts

export interface InpaintParams {
  seeds: number[]; // 생성할 시드 목록
  temperature: number; // 생성 다양성 (0.0-2.0)
  confidence_threshold: number; // 신뢰도 필터링
}

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

export interface PreviewState {
  isRunning: boolean;
  progress: number; // 0-100 (시간 기반)
  elapsed_s: number; // 경과 시간
  remaining_s: number; // 남은 시간
  currentFrame: PreviewFrame | null;
  frames: PreviewFrame[]; // 모든 생성된 프레임
  error: string | null;
  runId: string | null;
}
```

### 4.2 Zustand Preview Store

```typescript
// store/preview-store.ts

export interface PreviewState {
  isRunning: boolean;
  progress: number;
  elapsed_s: number;
  remaining_s: number;
  currentFrame: PreviewFrame | null;
  frames: PreviewFrame[];
  error: string | null;
  runId: string | null;
}

interface PreviewActions {
  startPreview: (
    runId: string,
    totalDuration: number,
    onComplete: (frames: PreviewFrame[]) => void
  ) => void;
  updateProgress: (
    elapsed: number,
    remaining: number,
    progress: number
  ) => void;
  addFrame: (frame: PreviewFrame) => void;
  completePreview: (frames?: PreviewFrame[]) => void;
  cancelPreview: () => void;
  setError: (error: string) => void;
  reset: () => void;
}

export const usePreviewStore = create<PreviewStore>((set, get) => ({
  ...initialState,

  startPreview: (runId, totalDuration, onComplete) => {
    // Interval 자체가 Zustand 내부에서 관리됨
    // React 라이프사이클과 완전히 독립적
    let progressInterval: number | null = window.setInterval(() => {
      const state = get();
      const newElapsed = state.elapsed_s + 1;
      const newRemaining = Math.max(0, totalDuration - newElapsed);
      const newProgress = Math.min(100, (newElapsed / totalDuration) * 100);

      if (newElapsed >= totalDuration) {
        clearInterval(progressInterval);
        progressInterval = null;
        onComplete(state.frames);
      } else {
        set({
          elapsed_s: newElapsed,
          remaining_s: newRemaining,
          progress: newProgress
        });
      }
    }, 1000);

    set({
      isRunning: true,
      progress: 0,
      elapsed_s: 0,
      remaining_s: totalDuration,
      frames: [],
      error: null,
      runId
    });
  },

  completePreview: frames => {
    set(state => ({
      isRunning: false,
      progress: 100,
      remaining_s: 0,
      frames: frames || state.frames
    }));
  },

  cancelPreview: () => {
    set(state => ({
      isRunning: false,
      progress: state.progress
    }));
  }
  // ... 기타 액션
}));
```

**Zustand vs Jotai 비교**:

| 구분         | Jotai             | Zustand             |
| ------------ | ----------------- | ------------------- |
| **스코프**   | 컴포넌트 내 상태  | 전역 상태           |
| **구독**     | Hook 기반         | Hook 또는 직접 접근 |
| **Interval** | React 렌더링 의존 | 완전히 독립적       |
| **Cleanup**  | useEffect 필요    | 액션에서 관리       |
| **탭 전환**  | 상태 손실 위험    | 상태 유지           |

### 4.3 usePreviewManager Hook

```typescript
// components/mol-viewer/usePreviewManager.ts

export function usePreviewManager(plugin: PluginContext | null) {
  const wsRef = useRef<WebSocket | null>(null);

  /**
   * 바이너리 프레임 파싱
   */
  const parseFrame = useCallback((buffer: ArrayBuffer): PreviewFrame | null => {
    try {
      if (buffer.byteLength < 256) return null;

      const header = new DataView(buffer, 0, 256);
      const frameIndex = header.getUint32(0, true);
      const totalFrames = header.getUint32(4, true);
      const confidence = header.getFloat32(8, true);
      const temperature = header.getFloat32(12, true);
      const plddt_mean = header.getFloat32(16, true);

      const structureData = buffer.slice(256);

      return {
        frameId: `frame-${frameIndex}`,
        frameIndex,
        totalFrames,
        structure: structureData,
        confidence,
        temperature,
        plddt_mean: isNaN(plddt_mean) ? undefined : plddt_mean,
        timestamp: Date.now()
      };
    } catch (err) {
      console.error("Frame parsing error:", err);
      return null;
    }
  }, []);

  /**
   * WebSocket 연결 및 스트리밍
   */
  const startPreview = useCallback(
    async (params: InpaintParams) => {
      return new Promise<void>((resolve, reject) => {
        try {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.close();
          }

          const ws = new WebSocket("ws://localhost:8000/api/inpaint/preview");
          ws.binaryType = "arraybuffer";

          ws.onopen = () => {
            ws.send(
              JSON.stringify({
                project_id: "current-project",
                mask: {
                  /* mask spec */
                },
                ...params
              })
            );
          };

          ws.onmessage = event => {
            if (typeof event.data === "string") {
              // JSON 메시지 (progress, error 등)
              const msg = JSON.parse(event.data);
              // Zustand 액션 호출
            } else if (event.data instanceof ArrayBuffer) {
              // 바이너리 프레임 (PDB 데이터)
              const frame = parseFrame(event.data);
              if (frame) {
                // Zustand에 프레임 추가
              }
            }
          };

          ws.onerror = () => {
            reject(new Error("WebSocket error"));
            ws.close();
          };

          ws.onclose = () => {
            resolve();
          };

          wsRef.current = ws;
        } catch (err) {
          reject(err);
        }
      });
    },
    [parseFrame]
  );

  const cancelPreview = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.close();
    }
  }, []);

  useEffect(() => {
    return () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, []);

  return { startPreview, cancelPreview };
}
```

### 4.4 InpaintTab UI 컴포넌트 (Zustand 통합)

```tsx
// components/ControlPanel/InpaintTab.tsx

export function InpaintTab(): React.ReactElement {
  // 1. 전역 상태 구독 (Zustand)
  const {
    isRunning,
    progress,
    elapsed_s,
    remaining_s,
    frames,
    error,
    startPreview,
    completePreview,
    cancelPreview
  } = usePreviewStore();

  // 2. 컴포넌트 로컬 상태 (useState)
  const [seeds, setSeeds] = React.useState([42, 43, 44]);
  const [temperature, setTemperature] = React.useState(1.0);
  const [confidenceThreshold, setConfidenceThreshold] = React.useState(0.5);
  const [selectedFrameId, setSelectedFrameId] = React.useState<string | null>(
    null
  );

  // 3. 생성 핸들러
  const handleGenerate = (): void => {
    if (isRunning) return; // 이미 실행 중이면 무시

    const runId = `mock-${Date.now()}`;

    // Zustand에서 interval 자동 관리됨
    startPreview(runId, 5, () => {
      // 완료 콜백에서 모의 프레임 생성
      const mockFrames: PreviewFrame[] = seeds.map((_seed, idx) => ({
        frameId: `frame-${idx}`,
        frameIndex: idx,
        totalFrames: seeds.length,
        structure: new ArrayBuffer(256),
        confidence: 0.7 + Math.random() * 0.3,
        temperature,
        plddt_mean: 60 + Math.random() * 30,
        timestamp: Date.now()
      }));

      completePreview(mockFrames);
    });
  };

  return (
    <div className="flex max-h-[600px] flex-col gap-4 overflow-y-auto p-4">
      {/* 파라미터 컨트롤 */}
      <div className="space-y-3 border-b border-border pb-4">
        <div>
          <label className="text-xs font-medium">Seeds (쉼표 분리)</label>
          <input
            type="text"
            value={seeds.join(", ")}
            onChange={e => {
              const parsed = e.target.value
                .split(",")
                .map(s => parseInt(s.trim()))
                .filter(n => !isNaN(n));
              setSeeds(parsed);
            }}
            disabled={isRunning}
            className="mt-1 w-full rounded-md border px-3 py-2 text-sm disabled:opacity-50"
          />
        </div>

        <div>
          <label className="text-xs font-medium">
            Temperature: {temperature.toFixed(2)}
          </label>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={temperature}
            onChange={e => setTemperature(parseFloat(e.target.value))}
            disabled={isRunning}
            className="w-full"
          />
        </div>

        <div>
          <label className="text-xs font-medium">
            Confidence Threshold: {confidenceThreshold.toFixed(2)}
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={confidenceThreshold}
            onChange={e => setConfidenceThreshold(parseFloat(e.target.value))}
            disabled={isRunning}
            className="w-full"
          />
        </div>
      </div>

      {/* 진행률 표시 (탭 전환해도 계속 업데이트됨) */}
      {isRunning && (
        <div className="space-y-2 rounded bg-slate-900 p-3">
          <div className="flex justify-between text-xs">
            <span>Generating...</span>
            <span className="text-cyan-400">{Math.round(progress)}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-700">
            <div
              className="h-full bg-gradient-to-r from-cyan-500 to-blue-500"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-400">
            <span>Elapsed: {elapsed_s}s</span>
            <span>Remaining: {remaining_s}s</span>
          </div>
        </div>
      )}

      {/* 오류 표시 */}
      {error && (
        <div className="rounded bg-red-900/50 p-3 text-xs text-red-200">
          ⚠ {error}
        </div>
      )}

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        <button
          onClick={handleGenerate}
          disabled={isRunning || seeds.length === 0}
          className="flex-1 rounded-md bg-primary px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Generate Preview
        </button>
        {isRunning && (
          <button
            onClick={cancelPreview}
            className="rounded-md border border-border px-4 py-2 text-sm"
          >
            Cancel
          </button>
        )}
      </div>

      {/* 결과 갤러리 */}
      {frames.length > 0 && (
        <SampleGallery
          frames={frames}
          onSelectFrame={frame => {
            setSelectedFrameId(frame.frameId);
            usePreviewStore.setState({ currentFrame: frame });
          }}
          selectedFrameId={selectedFrameId ?? undefined}
        />
      )}
    </div>
  );
}
```

**주요 특징**:

1. **상태 구독**: `usePreviewStore()`로 직접 구독 - 자동 리렌더
2. **Interval 투명성**: 내부에서 자동 관리 - 개발자가 신경 쓸 필요 없음
3. **탭 지속성**: `isRunning`, `progress`, `elapsed_s` 상태 유지
4. **간결한 코드**: useEffect, useRef 제거 - 복잡도 대폭 감소

## 5. Mock API 구현

### 5.1 시간 기반 진행률 시뮬레이션

Mock API는 Zustand store의 `startPreview()` 액션에 의해 자동으로 관리됩니다:

```typescript
// store/preview-store.ts의 startPreview 액션 내부

let progressInterval: number | null = window.setInterval(() => {
  const state = get();
  const newElapsed = state.elapsed_s + 1; // 1초씩 증가
  const newRemaining = Math.max(0, totalDuration - newElapsed);
  const newProgress = Math.min(100, (newElapsed / totalDuration) * 100);

  if (newElapsed >= totalDuration) {
    clearInterval(progressInterval);
    onComplete(state.frames); // 완료 콜백 실행
  } else {
    set({
      elapsed_s: newElapsed,
      remaining_s: newRemaining,
      progress: newProgress
    });
  }
}, 1000);
```

**특징**:

- ✅ 탭 전환해도 interval 계속 실행 (Window 스코프)
- ✅ 정확한 1초 간격 (0초 → 1초 → 2초 ... → 5초)
- ✅ 자동 cleanup (completePreview, cancelPreview에서 처리)

## 6. Jotai Atoms (선택사항)

## 7. 구현 체크리스트

- [x] 타입 정의 업데이트 (`InpaintParams`, `PreviewFrame`, `PreviewState`)
- [x] Zustand preview store 구현 (전역 상태 + interval 관리)
- [x] InpaintTab UI 컴포넌트 (Zustand 통합)
- [x] SampleGallery 컴포넌트 (여러 seed 결과 표시, pLDDT 신뢰도)
- [x] 시간 기반 진행률 표시 (탭 전환 후에도 계속 진행)
- [x] 상태 아키텍처 분리 (컴포넌트 상태 vs 전역 상태)
- [ ] usePreviewManager 훅 구현 (바이너리 파싱 + WebSocket)
- [ ] Mock WebSocket 서버 구현
- [ ] 백엔드 FastAPI 엔드포인트 (`/api/inpaint/preview` WebSocket)
- [ ] 단위 테스트
- [ ] 통합 테스트

## 8. 핵심 차이점 요약

| 항목                | 기존 (Diffusion)            | 새 설계 (Boltz)                          |
| ------------------- | --------------------------- | ---------------------------------------- |
| **진행률 업데이트** | 매 diffusion step           | 시간 기반 (1초마다)                      |
| **프레임 수**       | ~20-50개 (step 수)          | 3-5개 (seed 수)                          |
| **파라미터**        | steps, tau, guidance_scale  | seeds, temperature, confidence_threshold |
| **API 응답**        | 각 step마다 프레임 스트리밍 | 각 seed마다 최종 결과 스트리밍           |
| **추론 시간**       | step 수에 비례              | 고정 (약 30-60초)                        |
