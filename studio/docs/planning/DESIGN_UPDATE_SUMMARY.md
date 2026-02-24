# 설계 문서 업데이트 요약

## 📋 변경 사항

### 1. Mol\* Viewer Integration 재작성

**파일**: `docs/mol-viewer-integration.md`

#### 주요 개선사항

✅ **실제 존재하는 라이브러리 기반**

- ❌ `@rcsb/mvs` → ✅ `molstar` 내장 MVS 익스텐션 사용
- ❌ `mol-draw` → ✅ `pdbe-molstar` (높은 수준의 API) 또는 `molstar` 직접 사용

✅ **기술 스택 명시**

- `molstar` ^5.0.0 (npm 17.7K 주간 다운로드)
- `pdbe-molstar` ^3.8.0 (React 친화적, 선택사항)
- Python: `molviewspec` (백엔드)

✅ **구현 패턴 제공**

- `usePluginContext`: PluginContext 초기화
- `useStructure`: PDB/mmCIF/CIF/BinaryCIF 로드
- `useRepresentation`: Cartoon/Surface/Ball&Stick 적용
- `useMaskOverlay`: Shape 기반 마스크 표시
- `useSelection`: 원자/잔기 선택 처리
- `useMVSExport`: MVS JSON 직렬화

✅ **실제 Mol\* 모듈 구조**

```
molstar/lib/
├── mol-plugin/          # PluginContext
├── mol-plugin-ui/       # React UI
├── mol-canvas3d/        # WebGL 렌더링
├── mol-io/              # 파일 파서
└── mol-repr/            # 표현 시스템
```

✅ **MVS 지원**

- Mol\* 내장 `.mvsj` 로더
- Drag-and-drop, URL parameter 지원
- Python 백엔드 `molviewspec` 패키지

#### 코드 예제 추가

- PluginContext 초기화 (완전한 코드)
- 구조 로드 + 파일 형식 감지
- Cartoon/Surface 표현 적용
- Shape 기반 마스크 오버레이
- 선택 처리 및 이벤트 발행
- MVS 내보내기

---

### 2. Real-time Inpainting Preview 재작성

**파일**: `docs/real-time-inpainting-preview.md`

#### 주요 개선사항

✅ **완전한 usePreviewManager 구현**

- WebSocket 스트림 처리
- 프레임 메타데이터 파싱 (바이너리 포맷)
- Debounce 500ms (파라미터 변경 시)
- 중복 요청 방지
- 오류 처리 및 자동 정리

✅ **UI 컴포넌트**

- InpaintTab: 파라미터 슬라이더 + 진행률
- ProgressBar: 애니메이션 진행률 표시
- FrameGallery: 프레임 선택 및 신뢰도 표시

✅ **백엔드 API 명세**

- WebSocket 엔드포인트 및 메시지 스키마
- 바이너리 프레임 포맷 (256 바이트 메타 + PDB 데이터)
- JSON 메타 메시지 (start, progress, complete, error)

✅ **성능 최적화**
| 기법 | 효과 |
|-----|-----|
| Debounce | 불필요한 요청 제거 |
| Frame Cache | 메모리 사용량 제한 (최근 5프레임) |
| Binary Format | 대역폭 40-50% 감소 |
| Selective Render | 렌더링 시간 단축 |

✅ **오류 처리**

- WS 재연결 정책 (Exponential Backoff)
- 타임아웃 처리
- 프레임 파싱 오류 처리

---

## 📊 라이브러리 비교

### Mol\* 시각화 옵션

| 라이브러리             | 특징                          | 권장                    |
| ---------------------- | ----------------------------- | ----------------------- |
| **molstar** (핵심)     | 저수준 API, 완전한 제어       | ✅ 커스터마이징 필요 시 |
| **pdbe-molstar**       | 높은 수준의 API, React 친화적 | ⭐ 권장                 |
| **@rcsb/rcsb-molstar** | RCSB 특화 기능                | ⭐ RCSB 기능 필요 시    |

### MVS 지원

- ✅ Mol\* 내장 익스텐션 (JavaScript/TypeScript)
- ✅ Python `molviewspec` 패키지 (백엔드)
- ✅ `.mvsj` 표준 포맷
- ✅ Drag-drop, URL parameter, 프로그래매틱 로드

---

## 🎯 주요 개선 사항 (기존 vs 신규)

| 항목           | 기존               | 신규                           |
| -------------- | ------------------ | ------------------------------ |
| MVS 라이브러리 | `@rcsb/mvs` (없음) | `molstar` 내장                 |
| 마스크 브러시  | `mol-draw` (없음)  | `pdbe-molstar` 또는 직접 Shape |
| 구현 코드      | 의사 코드          | **완전한 TypeScript 코드**     |
| 훅 상세도      | 기본               | **세부 로직 + 에러 처리**      |
| 백엔드 API     | 기본 스키마        | **바이너리 프레임 포맷 정의**  |
| 성능 최적화    | 나열               | **표로 정리 + 구현 코드**      |

---

## 📁 문서 구조

```
docs/
├── plan.md                              (기존 전체 계획)
├── linting-rules.md                    (기존 린팅 규칙)
├── mol-viewer-integration.md           ✨ (재작성)
├── real-time-inpainting-preview.md    ✨ (재작성)
├── mol-viewer-integration-old.md       (백업)
└── real-time-inpainting-preview-old.md (백업)
```

---

## 🚀 다음 단계 (구현)

### Phase 1: 기본 Mol\* 통합

1. usePluginContext 구현 + 테스트
2. useStructure (PDB 로드) + 테스트
3. useRepresentation (Cartoon) + 테스트
4. MolViewerPanel 컴포넌트 완성

### Phase 2: 마스크 표시

1. useMaskOverlay 구현 (Shape)
2. 색상 코딩 (include/exclude/fixed)
3. 선택 인터랙션 (useSelection)

### Phase 3: 실시간 프리뷰

1. usePreviewManager 구현
2. WebSocket 스트림 처리
3. InpaintTab UI 완성
4. 프레임 렌더링 (Mol\* 통합)

### Phase 4: MVS 지원

1. MVS 내보내기 (useMVSExport)
2. MVS 임포트 (상태 복원)
3. 백엔드 `molviewspec` 통합

---

## 📚 참고 자료

### 공식 문서

- https://molstar.org/docs/
- https://molstar.org/viewer-docs/extensions/mvs/
- https://github.com/molstar/molstar

### PDBe Molstar (권장)

- https://github.com/molstar/pdbe-molstar
- https://www.npmjs.com/package/pdbe-molstar
- Wiki: https://github.com/molstar/pdbe-molstar/wiki

### MVS

- Python: https://pypi.org/project/molviewspec/
- Examples: https://github.com/molstar/molstar/tree/master/examples/mvs

---

## ✅ 완료 항목

- [x] 웹 조사 (npm packages, GitHub repos)
- [x] 실제 라이브러리 식별
- [x] Mol\* Viewer 기획서 재작성
- [x] Real-time Preview 기획서 재작성
- [x] 완전한 TypeScript 코드 예제 추가
- [x] 백엔드 API 스키마 정의
- [x] 참고 자료 정리

---

**생성 날짜**: 2025-10-25  
**상태**: ✅ 완료  
**다음 마일스톤**: Phase 1 Mol\* 통합 구현
