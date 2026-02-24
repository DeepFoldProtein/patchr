# Phase 2: Backend API Specification

> Boltz-Inpainting 기반 실시간 프리뷰 API 스펙

## 1. 엔드포인트 개요

| 엔드포인트                   | 타입      | 설명                         |
| ---------------------------- | --------- | ---------------------------- |
| `/api/inpaint/preview`       | WebSocket | 실시간 추론 및 결과 스트리밍 |
| `/api/inpaint/cancel`        | POST      | 진행 중인 추론 취소          |
| `/api/inpaint/status/:runId` | GET       | 추론 상태 조회 (선택사항)    |

## 2. WebSocket: /api/inpaint/preview

### 2.1 연결 초기화

```bash
# 클라이언트
ws://localhost:8000/api/inpaint/preview
```

### 2.2 클라이언트 요청 (JSON, 연결 직후 전송)

```json
{
  "project_id": "proj-abc123",
  "structure_file": "/path/to/structure.pdb",
  "mask": {
    "version": 1,
    "units": "residue",
    "include": [{ "chain": "A", "residues": [10, 11, 12, 13, 14, 15] }],
    "exclude": [{ "chain": "B", "residues": [] }],
    "fixed": [{ "chain": "B", "residues": [] }],
    "soft_shell_Ang": 3.0
  },
  "seeds": [42, 43, 44],
  "temperature": 1.0,
  "confidence_threshold": 0.5
}
```

### 2.3 서버 응답 시퀀스

#### Phase 1: 시작 알림 (JSON)

```json
{
  "type": "start",
  "run_id": "run-20251025-xyz789",
  "total_seeds": 3,
  "estimated_duration_s": 45,
  "timestamp": "2025-10-25T12:00:00.000Z"
}
```

**필드 설명:**

- `run_id`: 이번 추론 세션의 고유 ID (취소/상태 조회 시 사용)
- `total_seeds`: 생성할 총 seed 개수
- `estimated_duration_s`: 예상 소요 시간 (초)

#### Phase 2: 진행률 업데이트 (JSON, 주기적)

**빈도**: 약 1초마다 업데이트

```json
{
  "type": "progress",
  "run_id": "run-20251025-xyz789",
  "elapsed_s": 10,
  "remaining_s": 35,
  "progress_percent": 22,
  "current_seed_index": 0,
  "status": "processing",
  "timestamp": "2025-10-25T12:00:10.000Z"
}
```

**필드 설명:**

- `elapsed_s`: 시작 후 경과 시간
- `remaining_s`: 예상 남은 시간
- `progress_percent`: 0-100 진행률
- `current_seed_index`: 현재 처리 중인 seed 인덱스 (정보성)
- `status`: "processing", "waiting", "cleanup" 등

#### Phase 3: 프레임 데이터 (바이너리)

**각 seed 완료마다 1번씩 전송** (순차적)

```
바이너리 형식 (256 바이트 헤더 + PDB 데이터):

Offset  | Size | Type     | 필드명                  | 설명
--------|------|----------|----------------------|----------
0-3     | 4    | uint32   | frameIndex            | seed 인덱스 (0, 1, 2, ...)
4-7     | 4    | uint32   | totalFrames           | 총 seed 개수
8-11    | 4    | float32  | confidence            | 신뢰도 (0.0-1.0)
12-15   | 4    | float32  | temperature           | 생성 시 사용된 temperature
16-19   | 4    | float32  | plddt_mean            | pLDDT 평균값
20-23   | 4    | float32  | pae_max               | PAE 최대값 (선택사항)
24-255  | 232  | -        | 예약 (padding)        | 향후 확장용
256+    | var  | text/bin | structure_data        | PDB 형식 구조 데이터
```

**예시:**

- seed[0] → frameIndex=0, confidence=0.82, plddt_mean=82.1
- seed[1] → frameIndex=1, confidence=0.79, plddt_mean=79.5
- seed[2] → frameIndex=2, confidence=0.85, plddt_mean=85.3

#### Phase 4: 완료 메시지 (JSON)

```json
{
  "type": "complete",
  "run_id": "run-20251025-xyz789",
  "total_duration_s": 45,
  "frames_count": 3,
  "plddt_scores": [82.1, 79.5, 85.3],
  "pae_scores": [10.5, 11.2, 9.8],
  "status": "success",
  "timestamp": "2025-10-25T12:00:45.000Z"
}
```

**필드 설명:**

- `frames_count`: 성공적으로 생성된 프레임 개수
- `plddt_scores`: 각 seed별 pLDDT 평균값
- `pae_scores`: 각 seed별 예상 오류(PAE) 최대값
- `status`: "success", "partial", "failed"

#### Phase 5 (오류): 오류 메시지 (JSON)

```json
{
  "type": "error",
  "run_id": "run-20251025-xyz789",
  "error_code": "INVALID_MASK",
  "error_message": "Residue range A:10-20 exceeds chain length",
  "details": {
    "field": "mask.include[0].residues",
    "reason": "Out of bounds",
    "chain_length": 15
  },
  "status": "failed",
  "timestamp": "2025-10-25T12:00:02.000Z"
}
```

**오류 코드:**

- `INVALID_MASK`: 마스크 사양 불량
- `INVALID_STRUCTURE`: 구조 파일 문제
- `GPU_ERROR`: GPU 관련 오류
- `TIMEOUT`: 타임아웃
- `INTERNAL_ERROR`: 기타 서버 오류

### 2.4 연결 종료

```
정상 종료: WebSocket이 close 프레임 수신
강제 종료: 클라이언트가 ws.close() 호출
```

## 3. POST: /api/inpaint/cancel

### 요청

```http
POST /api/inpaint/cancel HTTP/1.1
Content-Type: application/json

{
  "run_id": "run-20251025-xyz789"
}
```

### 응답

```json
{
  "run_id": "run-20251025-xyz789",
  "status": "cancelled",
  "frames_received": 1,
  "timestamp": "2025-10-25T12:00:20.000Z"
}
```

## 4. GET: /api/inpaint/status/:runId (선택)

최근 완료된 추론 상태 조회 (WebSocket 연결 없이)

### 요청

```http
GET /api/inpaint/status/run-20251025-xyz789 HTTP/1.1
```

### 응답

```json
{
  "run_id": "run-20251025-xyz789",
  "status": "completed",
  "elapsed_s": 45,
  "total_duration_s": 45,
  "frames_count": 3,
  "plddt_scores": [82.1, 79.5, 85.3],
  "timestamp": "2025-10-25T12:00:45.000Z",
  "result_location": "/tmp/inpaint_results/run-20251025-xyz789"
}
```

## 5. 성능 특성

| 항목                     | 값                       |
| ------------------------ | ------------------------ |
| **평균 추론 시간**       | 30-60초                  |
| **배치 처리**            | seed별 병렬 실행         |
| **메모리 사용**          | ~4-6 GB (구조 크기 의존) |
| **최대 동시 요청**       | 2-4개 (GPU 수에 의존)    |
| **진행률 업데이트 빈도** | ~1초마다                 |
| **프레임 스트리밍 속도** | 각 seed당 0.5-1초        |

## 6. 오류 처리 및 재시도 정책

### 클라이언트 재시도

```typescript
// exponential backoff
const retryDelays = [1000, 2000, 5000];

async function connectWithRetry(
  wsUrl: string,
  maxRetries = 3
): Promise<WebSocket> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const ws = new WebSocket(wsUrl);
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

### 서버 재시도 (Boltz 모델 로드 실패 시)

```
시도 1: 즉시 재시도
시도 2: 1초 대기 후 재시도
시도 3: 2초 대기 후 재시도
실패: 클라이언트에 오류 반환
```

## 7. 보안 고려사항

### 입력 검증

- **마스크 범위**: 구조 내 유효한 범위 확인
- **seed 값**: 1-2^31 범위 검증
- **파일 경로**: 경로 traversal 공격 방지

### 타임아웃

- **총 추론 시간**: 최대 120초 (예상 45초 + 버퍼)
- **WebSocket 무응답**: 10초 이상 진행률 업데이트 없으면 연결 종료

### 리소스 제한

- **동시 WebSocket 연결**: 최대 10개
- **GPU 메모리**: 구조당 최대 8GB 제한

## 8. 서버 구현 예시 (FastAPI + Boltz)

```python
# backend/api/inpaint.py
import asyncio
import json
from fastapi import WebSocket
from boltz import BoltzInpainting

@app.websocket("/api/inpaint/preview")
async def websocket_preview(websocket: WebSocket):
    await websocket.accept()

    try:
        # 클라이언트 요청 수신
        request_data = await websocket.receive_text()
        request = json.loads(request_data)

        run_id = f"run-{datetime.now().isoformat()}"
        seeds = request.get("seeds", [42, 43, 44])
        temperature = request.get("temperature", 1.0)

        # 시작 알림
        await websocket.send_text(json.dumps({
            "type": "start",
            "run_id": run_id,
            "total_seeds": len(seeds),
            "estimated_duration_s": 45
        }))

        # 병렬 추론
        start_time = time.time()
        results = []

        for idx, seed in enumerate(seeds):
            # 진행률 업데이트
            elapsed = time.time() - start_time
            remaining = 45 - elapsed

            await websocket.send_text(json.dumps({
                "type": "progress",
                "run_id": run_id,
                "elapsed_s": int(elapsed),
                "remaining_s": max(0, int(remaining)),
                "progress_percent": int((idx / len(seeds)) * 100),
                "current_seed_index": idx
            }))

            # Boltz 추론
            output_structure, metrics = boltz_model.inpaint(
                structure=request["structure_file"],
                mask=request["mask"],
                seed=seed,
                temperature=temperature
            )

            # 결과 스트리밍 (바이너리)
            binary_frame = pack_frame(
                frameIndex=idx,
                totalFrames=len(seeds),
                confidence=metrics["confidence"],
                temperature=temperature,
                plddt_mean=metrics["plddt"],
                structure_data=output_structure.encode()
            )
            await websocket.send_bytes(binary_frame)

            results.append(metrics)

        # 완료 알림
        await websocket.send_text(json.dumps({
            "type": "complete",
            "run_id": run_id,
            "total_duration_s": int(time.time() - start_time),
            "frames_count": len(seeds),
            "plddt_scores": [r["plddt"] for r in results],
            "status": "success"
        }))

    except Exception as e:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error_message": str(e),
            "status": "failed"
        }))

    finally:
        await websocket.close()
```

## 9. 클라이언트 구현 예시 (React)

기본 구현은 `docs/phase-2-boltz-inpainting.md` 섹션 4.2 참고

## 10. 테스트 시나리오

### 1. 정상 경로 (Happy Path)

```
1. 클라이언트: 요청 전송
2. 서버: start 메시지
3. 서버: 진행률 업데이트 (5회)
4. 서버: 프레임 데이터 (3개)
5. 서버: complete 메시지
6. 클라이언트: 결과 표시
```

### 2. 취소 시나리오

```
1. 클라이언트: 요청 전송
2. 서버: start 메시지
3. 서버: 진행률 업데이트 (2회)
4. 클라이언트: 취소 버튼 클릭 (WebSocket close)
5. 서버: 추론 중단
6. 클라이언트: 현재까지의 프레임만 표시
```

### 3. 타임아웃 시나리오

```
1. 클라이언트: 요청 전송
2. 서버: start 메시지
3. [GPU 오류 발생, 진행률 업데이트 중단]
4. 클라이언트: 10초 타임아웃 감지
5. 클라이언트: 연결 강제 종료
6. 서버: 추론 정리
```

---

**다음**: 실제 서버 구현을 `backend/` 폴더에 진행하기
