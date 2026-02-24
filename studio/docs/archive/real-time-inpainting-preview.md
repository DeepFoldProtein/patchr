# Real-time Inpainting Preview 설계 문서 (Revised)

> 웹 조사 기반 실제 구현 패턴 활용

## 1. 개요

Real-time Inpainting Preview는 사용자가 인페인팅 파라미터를 조정하면서 **실시간으로 결과를 프리뷰**할 수 있는 기능입니다. 이를 통해:

- **빠른 피드백**: 스텝/τ/시드 변경 시 500ms 내 프리뷰 갱신
- **반복적 정제**: 여러 시도를 통한 최적 파라미터 탐색
- **대역폭 효율성**: WebSocket 스트림 + 바이너리 전송
- **사용자 경험**: 진행률/ETA/신뢰도 표시

---

## 2. 아키텍처 흐름

```
UI 레이어 (React)
┌─────────────────────────────────────┐
│  InpaintTab                         │
│  - 파라미터 슬라이더 (Steps/Tau)   │
│  - "Generate Preview" 버튼         │
└─────────────┬───────────────────────┘
              │ onChange (debounce 500ms)
              ▼
┌─────────────────────────────────────┐
│  usePreviewManager 훅               │
│  - 요청 생성                        │
│  - 중복 방지                        │
│  - 상태 업데이트                    │
└─────────────┬───────────────────────┘
              │ POST /api/inpaint/preview
              ▼ WebSocket 연결
┌─────────────────────────────────────┐
│  FastAPI 백엔드                     │
│  - 인페인팅 실행 (PyTorch)         │
│  - 프레임 스트리밍                  │
└─────────────┬───────────────────────┘
              │ WS Message (JSON + Binary)
              ▼
┌─────────────────────────────────────┐
│  MolViewerPanel                     │
│  - 프레임 구조 로드                 │
│  - 마스크 오버레이 표시             │
│  - 신뢰도 기반 투명도               │
└─────────────────────────────────────┘
```

---

## 3. 구현 상세

### 3.1 usePreviewManager 훅

```ts
// components/InpaintPreview/usePreviewManager.ts
import { useCallback, useEffect, useRef, useState } from "react";
import { useAtomValue, useSetAtom } from "jotai";
import { projectAtoms } from "../../store/project-atoms";
import { bus } from "../../lib/event-bus";

export interface PreviewFrame {
  frameId: string;
  frameIndex: number;
  totalFrames: number;
  structure: ArrayBuffer; // PDB 바이너리
  confidence?: number;
  timestamp: number;
}

export interface PreviewState {
  isRunning: boolean;
  progress: number; // 0-100
  currentFrame: PreviewFrame | null;
  frames: PreviewFrame[];
  error: string | null;
  eta: number; // 초 단위
}

const INITIAL_STATE: PreviewState = {
  isRunning: false,
  progress: 0,
  currentFrame: null,
  frames: [],
  error: null,
  eta: 0
};

export function usePreviewManager(projectId: string) {
  const inpaintParams = useAtomValue(projectAtoms.inpaintParamsAtom);
  const maskSpec = useAtomValue(projectAtoms.maskAtom);
  const setPreviewState = useSetAtom(projectAtoms.previewStateAtom);

  const [state, setState] = useState<PreviewState>(INITIAL_STATE);

  const wsRef = useRef<WebSocket | null>(null);
  const paramsHashRef = useRef<string>("");
  const requestIdRef = useRef<string | null>(null);

  /**
   * 요청 ID 생성
   */
  const generateRequestId = (): string => {
    return `req-${Date.now()}-${Math.random().toString(36).substring(7)}`;
  };

  /**
   * 파라미터 해시 (변경 감지용)
   */
  const hashParams = (): string => {
    return JSON.stringify({ inpaintParams, maskSpec });
  };

  /**
   * 프리뷰 요청
   */
  const requestPreview = useCallback(async () => {
    // 이미 실행 중이거나 파라미터 미변경
    const newHash = hashParams();
    if (state.isRunning || newHash === paramsHashRef.current) {
      return;
    }
    paramsHashRef.current = newHash;

    setState(prev => ({ ...prev, isRunning: true, error: null }));

    try {
      const requestId = generateRequestId();
      requestIdRef.current = requestId;

      // WS 연결
      connectPreviewStream(
        {
          project_id: projectId,
          mask: maskSpec,
          inpaint_params: inpaintParams,
          stream: true
        },
        requestId
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Preview failed";
      setState(prev => ({ ...prev, isRunning: false, error: msg }));
    }
  }, [inpaintParams, maskSpec, projectId, state.isRunning]);

  /**
   * WebSocket 스트림 연결
   */
  const connectPreviewStream = (request: any, requestId: string) => {
    return new Promise<void>((resolve, reject) => {
      try {
        // 기존 WS 종료
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.close();
        }

        const ws = new WebSocket(
          `ws://localhost:8000/api/inpaint/preview?project_id=${request.project_id}`
        );
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
          ws.send(JSON.stringify(request));
          bus.emit("preview:started", { requestId });
        };

        ws.onmessage = event => {
          if (requestIdRef.current !== requestId) {
            ws.close();
            return;
          }

          if (typeof event.data === "string") {
            // JSON 메시지 (메타)
            handlePreviewMessage(JSON.parse(event.data));
          } else if (event.data instanceof ArrayBuffer) {
            // 바이너리 메시지 (프레임 구조)
            handlePreviewFrame(event.data);
          }
        };

        ws.onerror = error => {
          console.error("WebSocket error:", error);
          reject(new Error(`WS error`));
          ws.close();
        };

        ws.onclose = () => {
          if (requestIdRef.current === requestId) {
            requestIdRef.current = null;
            setState(prev => ({ ...prev, isRunning: false }));
          }
          resolve();
        };

        wsRef.current = ws;
      } catch (err) {
        reject(err);
      }
    });
  };

  /**
   * 메시지 처리 (JSON)
   */
  const handlePreviewMessage = (msg: any) => {
    switch (msg.type) {
      case "start":
        setState(prev => ({
          ...prev,
          progress: 0,
          frames: [],
          eta: msg.eta_s || 0
        }));
        break;

      case "progress":
        setState(prev => ({
          ...prev,
          progress: msg.progress || 0,
          eta: msg.eta_s || 0
        }));
        bus.emit("preview:progress", {
          progress: msg.progress,
          eta: msg.eta_s,
          step: msg.step,
          total: msg.total
        });
        break;

      case "complete":
        setState(prev => ({
          ...prev,
          isRunning: false,
          progress: 100
        }));
        bus.emit("preview:complete", {
          totalFrames: msg.frame_count
        });
        break;

      case "error":
        setState(prev => ({
          ...prev,
          isRunning: false,
          error: msg.error || "Unknown error"
        }));
        break;
    }
  };

  /**
   * 프레임 처리 (바이너리)
   */
  const handlePreviewFrame = (data: ArrayBuffer) => {
    try {
      // 메타데이터 파싱 (처음 256 바이트)
      const metaView = new DataView(data, 0, 256);
      const frameIndex = metaView.getUint32(0, true);
      const totalFrames = metaView.getUint32(4, true);
      const confidence = metaView.getFloat32(8, true);

      // 구조 데이터
      const structureData = data.slice(256);

      const frame: PreviewFrame = {
        frameId: `frame-${frameIndex}`,
        frameIndex,
        totalFrames,
        structure: structureData,
        confidence,
        timestamp: Date.now()
      };

      setState(prev => {
        // 최근 5프레임만 유지
        const newFrames = [
          ...prev.frames.filter(f => f.frameIndex !== frameIndex),
          frame
        ].slice(-5);

        return {
          ...prev,
          currentFrame: frame,
          frames: newFrames
        };
      });

      bus.emit("preview:frameUpdated", frame);
    } catch (err) {
      console.error("Frame parsing error:", err);
      setState(prev => ({
        ...prev,
        error: "Frame parsing failed"
      }));
    }
  };

  /**
   * Debounce된 요청
   */
  useEffect(() => {
    const timer = setTimeout(() => {
      requestPreview();
    }, 500);

    return () => clearTimeout(timer);
  }, [inpaintParams, maskSpec, requestPreview]);

  /**
   * 정리
   */
  useEffect(() => {
    return () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    };
  }, []);

  /**
   * Jotai 동기화
   */
  useEffect(() => {
    setPreviewState(state);
  }, [state, setPreviewState]);

  return {
    previewState: state,
    requestPreview,
    cancelPreview: () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
    }
  };
}
```

### 3.2 Inpaint Tab 컴포넌트

```tsx
// components/ControlPanel/tabs/InpaintTab.tsx
import React from "react";
import { useAtomValue, useSetAtom } from "jotai";
import { projectAtoms } from "../../../store/project-atoms";
import { usePreviewManager } from "../../InpaintPreview/usePreviewManager";
import { Button } from "../../ui/button";
import { ProgressBar } from "../../ui/progress-bar";
import { FrameGallery } from "../../InpaintPreview/FrameGallery";

export interface InpaintTabProps {
  projectId: string;
}

export function InpaintTab({ projectId }: InpaintTabProps): React.ReactElement {
  const inpaintParams = useAtomValue(projectAtoms.inpaintParamsAtom);
  const setInpaintParams = useSetAtom(projectAtoms.inpaintParamsAtom);

  const { previewState, cancelPreview } = usePreviewManager(projectId);

  return (
    <div className="flex flex-col gap-4 p-4 max-h-[600px] overflow-y-auto">
      {/* 파라미터 폼 */}
      <div className="space-y-3 border-b pb-4">
        <div>
          <label className="text-xs font-medium text-gray-300">
            Steps ({inpaintParams.steps})
          </label>
          <input
            type="range"
            min="10"
            max="100"
            value={inpaintParams.steps}
            onChange={e =>
              setInpaintParams(prev => ({
                ...prev,
                steps: parseInt(e.target.value)
              }))
            }
            className="w-full"
            disabled={previewState.isRunning}
          />
        </div>

        <div>
          <label className="text-xs font-medium text-gray-300">
            Tau τ ({inpaintParams.tau.toFixed(2)})
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={inpaintParams.tau}
            onChange={e =>
              setInpaintParams(prev => ({
                ...prev,
                tau: parseFloat(e.target.value)
              }))
            }
            className="w-full"
            disabled={previewState.isRunning}
          />
        </div>

        <div>
          <label className="text-xs font-medium text-gray-300">
            Seeds ({inpaintParams.seeds})
          </label>
          <input
            type="range"
            min="1"
            max="16"
            value={inpaintParams.seeds}
            onChange={e =>
              setInpaintParams(prev => ({
                ...prev,
                seeds: parseInt(e.target.value)
              }))
            }
            className="w-full"
            disabled={previewState.isRunning}
          />
        </div>
      </div>

      {/* 진행률 */}
      {previewState.isRunning && (
        <div className="space-y-2 bg-slate-900 p-2 rounded">
          <div className="flex justify-between text-xs">
            <span>Preview Running...</span>
            <span className="text-cyan-400">
              {Math.round(previewState.progress)}%
            </span>
          </div>
          <ProgressBar value={previewState.progress} />
          {previewState.eta > 0 && (
            <p className="text-xs text-gray-400">
              ETA: {Math.ceil(previewState.eta)}s
            </p>
          )}
        </div>
      )}

      {/* 오류 */}
      {previewState.error && (
        <div className="bg-red-900/50 text-red-200 p-2 rounded text-xs">
          ⚠ {previewState.error}
        </div>
      )}

      {/* 현재 프레임 정보 */}
      {previewState.currentFrame && (
        <div className="bg-slate-800 p-2 rounded text-xs space-y-1">
          <p>
            Frame {previewState.currentFrame.frameIndex + 1} /{" "}
            {previewState.currentFrame.totalFrames}
          </p>
          {previewState.currentFrame.confidence !== undefined && (
            <p>
              Confidence:{" "}
              {(previewState.currentFrame.confidence * 100).toFixed(1)}%
            </p>
          )}
        </div>
      )}

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        <Button
          onClick={() => usePreviewManager(projectId).requestPreview()}
          disabled={previewState.isRunning}
          className="flex-1"
        >
          Generate Preview
        </Button>
        {previewState.isRunning && (
          <Button onClick={cancelPreview} variant="secondary">
            Cancel
          </Button>
        )}
      </div>

      {/* 프레임 갤러리 */}
      {previewState.frames.length > 0 && (
        <FrameGallery frames={previewState.frames} />
      )}
    </div>
  );
}
```

### 3.3 Progress Bar 컴포넌트

```tsx
// components/ui/progress-bar.tsx
export interface ProgressBarProps {
  value: number; // 0-100
  animated?: boolean;
}

export function ProgressBar({
  value,
  animated = true
}: ProgressBarProps): React.ReactElement {
  return (
    <div className="w-full bg-slate-700 rounded h-2 overflow-hidden">
      <div
        className={`h-full bg-gradient-to-r from-cyan-500 to-blue-500 ${
          animated ? "animate-pulse" : ""
        } transition-all duration-300`}
        style={{ width: `${value}%` }}
      />
    </div>
  );
}
```

### 3.4 Frame Gallery 컴포넌트

```tsx
// components/InpaintPreview/FrameGallery.tsx
import React, { useState } from "react";
import { PreviewFrame } from "./usePreviewManager";

export interface FrameGalleryProps {
  frames: PreviewFrame[];
  onSelectFrame?: (frame: PreviewFrame) => void;
}

export function FrameGallery({
  frames,
  onSelectFrame
}: FrameGalleryProps): React.ReactElement {
  const [selectedIdx, setSelectedIdx] = useState(-1);

  return (
    <div className="space-y-2 border-t pt-2">
      <p className="text-xs font-medium text-gray-300">Preview Frames</p>
      <div className="flex gap-1 overflow-x-auto pb-2">
        {frames.map((frame, idx) => (
          <button
            key={frame.frameId}
            onClick={() => {
              setSelectedIdx(idx);
              onSelectFrame?.(frame);
            }}
            className={`
              flex-shrink-0 w-12 h-12 rounded border-2 flex items-center justify-center
              transition-colors text-xs
              ${
                selectedIdx === idx
                  ? "border-cyan-500 bg-cyan-500/20"
                  : "border-slate-600 bg-slate-700 hover:border-slate-500"
              }
            `}
            title={`Frame ${frame.frameIndex}, Confidence: ${(
              (frame.confidence || 0) * 100
            ).toFixed(0)}%`}
          >
            <span className="text-center">
              {frame.frameIndex + 1}
              {frame.confidence && (
                <div className="text-[10px] text-gray-300">
                  {((frame.confidence || 0) * 100).toFixed(0)}%
                </div>
              )}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

### 3.5 MolViewer 프리뷰 렌더러

```ts
// components/MolViewer/usePreviewRenderer.ts
import { useEffect } from "react";
import { useAtomValue } from "jotai";
import { projectAtoms } from "../../store/project-atoms";
import { bus } from "../../lib/event-bus";
import { PreviewFrame } from "../InpaintPreview/usePreviewManager";

export function usePreviewRenderer(plugin: PluginContext | null) {
  const previewState = useAtomValue(projectAtoms.previewStateAtom);

  useEffect(() => {
    const handleFrameUpdate = async (frame: PreviewFrame) => {
      if (!plugin) return;

      try {
        // 프리뷰 구조 로드
        const pdbText = new TextDecoder().decode(frame.structure);

        await plugin.managers.structure.hierarchy.applyPreset(
          plugin.state,
          pdbText,
          "all-models",
          {
            structure: {
              name: "pdb",
              label: `Preview Frame ${frame.frameIndex}`
            },
            representation: { name: "auto" }
          }
        );

        // 신뢰도 기반 투명도
        if (frame.confidence !== undefined) {
          const opacity = 0.3 + frame.confidence * 0.7;
          // 투명도 조정 로직
        }

        bus.emit("preview:rendered", {
          frameIndex: frame.frameIndex,
          confidence: frame.confidence
        });
      } catch (err) {
        console.error("Preview render error:", err);
      }
    };

    bus.on("preview:frameUpdated", handleFrameUpdate);

    return () => {
      bus.off("preview:frameUpdated", handleFrameUpdate);
    };
  }, [plugin]);
}
```

---

## 4. 백엔드 API 설계

### 4.1 WebSocket 엔드포인트

```
WS ws://localhost:8000/api/inpaint/preview?project_id={projectId}
```

**요청 (텍스트):**

```json
{
  "project_id": "proj-123",
  "mask": {
    "version": 1,
    "units": "residue",
    "include": ["A:10-20"],
    "exclude": [],
    "fixed": ["B:*"],
    "soft_shell_Ang": 3
  },
  "inpaint_params": {
    "steps": 60,
    "tau": 0.7,
    "seeds": 4
  },
  "stream": true
}
```

**응답 시퀀스:**

1. **시작** (JSON):

```json
{
  "type": "start",
  "run_id": "run-xyz",
  "eta_s": 45,
  "total_frames": 4
}
```

2. **진행률** (JSON, 매 스텝):

```json
{
  "type": "progress",
  "progress": 25,
  "step": 15,
  "total": 60,
  "eta_s": 33
}
```

3. **프레임 데이터** (바이너리):

```
[0-3]   : frameIndex (uint32_le)
[4-7]   : totalFrames (uint32_le)
[8-11]  : confidence (float32_le)
[12-255]: padding
[256+]  : PDB 구조 데이터 (텍스트)
```

4. **완료** (JSON):

```json
{
  "type": "complete",
  "frame_count": 4,
  "avg_confidence": 0.87
}
```

5. **오류** (JSON):

```json
{
  "type": "error",
  "error": "Invalid mask specification"
}
```

---

## 5. Jotai Atoms

```ts
// store/project-atoms.ts 에 추가
import { atom } from "jotai";

export const previewStateAtom = atom<PreviewState>({
  isRunning: false,
  progress: 0,
  currentFrame: null,
  frames: [],
  error: null,
  eta: 0
});

export const previewHistoryAtom = atom<{
  [key: string]: PreviewFrame[];
}>({});

export const selectedPreviewFrameAtom = atom<PreviewFrame | null>(null);
```

---

## 6. Event Bus 확장

```ts
// lib/event-bus.ts
export interface PreviewEvents {
  "preview:started": { requestId: string };
  "preview:progress": {
    progress: number;
    eta: number;
    step: number;
    total: number;
  };
  "preview:frameUpdated": PreviewFrame;
  "preview:rendered": {
    frameIndex: number;
    confidence?: number;
  };
  "preview:complete": {
    totalFrames: number;
  };
  "preview:cancelled": void;
}
```

---

## 7. 성능 최적화

| 기법                   | 구현                        | 효과                            |
| ---------------------- | --------------------------- | ------------------------------- |
| **Debounce**           | 500ms 대기 후 요청          | 연속 입력 시 불필요한 요청 제거 |
| **Frame Cache**        | 최근 5프레임만 유지         | 메모리 사용량 제한              |
| **Binary Format**      | 구조 데이터는 바이너리 전송 | 대역폭 40-50% 감소              |
| **Selective Render**   | 선택된 프레임만 뷰어 로드   | 렌더링 시간 단축                |
| **Progressive Update** | 각 프레임마다 갱신          | 즉시 피드백 제공                |

---

## 8. 오류 처리

```ts
// WS 재연결 정책 (Exponential Backoff)
const retryDelays = [1000, 2000, 5000, 10000]; // ms

async function connectWithRetry(url: string, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return new Promise((resolve, reject) => {
        const ws = new WebSocket(url);
        const timeout = setTimeout(() => {
          ws.close();
          reject(new Error("Connection timeout"));
        }, 5000);
        ws.onopen = () => {
          clearTimeout(timeout);
          resolve(ws);
        };
        ws.onerror = err => {
          clearTimeout(timeout);
          reject(err);
        };
      });
    } catch (err) {
      if (i < maxRetries - 1) {
        await new Promise(r => setTimeout(r, retryDelays[i]));
      } else {
        throw err;
      }
    }
  }
}
```

---

## 9. 구현 체크리스트

- [ ] `usePreviewManager` 훅 구현
- [ ] WebSocket 스트림 처리
- [ ] 프레임 메타데이터 파싱 (바이너리)
- [ ] InpaintTab UI 컴포넌트
- [ ] ProgressBar 컴포넌트
- [ ] FrameGallery 컴포넌트
- [ ] MolViewer 프리뷰 렌더러
- [ ] Event Bus 메시지 타입
- [ ] Jotai Atom 정의
- [ ] 오류 처리 및 재시도
- [ ] 메모리 정리 (프레임 캐시)
- [ ] 단위 테스트
- [ ] 통합 테스트
- [ ] 부하 테스트

---

## 10. 향후 개선사항

- **프레임 비교**: Side-by-side 비교 뷰
- **프리셋 저장**: 자주 사용하는 파라미터 조합 저장
- **배치 생성**: 여러 파라미터 조합 동시 실행
- **통계**: 신뢰도/RMSD 분포 차트
- **애니메이션**: 프레임 시퀀스 재생

---

## 11. 참고 자료

- Mol\* 뷰어 통합: `mol-viewer-integration.md`
- WebSocket API: [MDN WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- React Hooks 패턴: [React Hooks Documentation](https://react.dev/reference/react)
