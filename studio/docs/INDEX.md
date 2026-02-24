# 📚 Patchr Studio 문서 인덱스# 📚 Patchr Studio 문서 인덱스

> **Last Updated**: 2025-10-26 > **Last Updated**: 2025-10-26

> **문서 관리 규칙**: [DOC_GUIDELINES.md](./DOC_GUIDELINES.md) 참고> **문서 관리 규칙**: [DOC_GUIDELINES.md](./DOC_GUIDELINES.md) 참고

---

## 🚀 빠른 시작## � 빠른 시작

### 처음 프로젝트를 접하는 경우### 처음 프로젝트를 접하는 경우

1. 📖 [프로젝트 계획](./planning/plan.md) - 전체 로드맵 이해

2. 🎨 [디자인 요약](./planning/DESIGN_UPDATE_SUMMARY.md) - UI/UX 설계1. 📖 [프로젝트 계획](./planning/plan.md) - 전체 로드맵 이해

3. ⚡ [Mol\* 통합 가이드](./guides/mol-viewer-integration.md) - 뷰어 아키텍처2. 🎨 [디자인 요약](./planning/DESIGN_UPDATE_SUMMARY.md) - UI/UX 설계

4. ⚡ [Mol\* 통합 가이드](./guides/mol-viewer-integration.md) - 뷰어 아키텍처

### Mol\* 뷰어를 개발/수정하는 경우

1. ⭐ [개발자 필독 노트](./guides/IMPLEMENTATION_NOTES.md) - 필수 패턴 및 주의사항### Mol\* 뷰어를 개발/수정하는 경우

2. 📘 [Mol\* 통합 가이드](./guides/mol-viewer-integration.md) - API 레퍼런스

3. 💻 코드: `src/renderer/src/components/mol-viewer/`1. ⭐ [개발자 필독 노트](./guides/IMPLEMENTATION_NOTES.md) - 필수 패턴 및 주의사항

4. 📘 [Mol\* 통합 가이드](./guides/mol-viewer-integration.md) - API 레퍼런스

### 인페인팅 기능을 개발하는 경우3. 💻 코드: `src/renderer/src/components/mol-viewer/`

1. 🔬 [Phase 2 Boltz 인페인팅](./planning/phase-2-boltz-inpainting.md) - 최신 설계

2. 🔌 [Backend API 명세](./api/phase-2-backend-api.md) - WebSocket API### 인페인팅 기능을 개발하는 경우

3. 💾 [상태 관리](./guides/IMPLEMENTATION_NOTES.md#11-상태-관리-아키텍처) - Jotai + Zustand

4. 🔬 [Phase 2 Boltz 인페인팅](./planning/phase-2-boltz-inpainting.md) - 최신 설계

---2. 🔌 [Backend API 명세](./api/phase-2-backend-api.md) - WebSocket API

3. 💾 [상태 관리](./guides/IMPLEMENTATION_NOTES.md#11-상태-관리-아키텍처) - Jotai + Zustand

## 📁 문서 구조

---

````

docs/## 📁 문서 구조

├── guides/          # 개발 가이드 및 통합 방법

├── api/             # API 명세```

├── planning/        # 프로젝트 기획 및 설계docs/

├── completed/       # 완료 기능 보고서├── guides/          # 개발 가이드 및 통합 방법

└── archive/         # 구버전 문서├── api/             # API 명세

```├── planning/        # 프로젝트 기획 및 설계

├── completed/       # 완료 기능 보고서

---└── archive/         # 구버전 문서

````

## 📖 개발 가이드 (guides/)

---

### ⭐ 핵심 가이드

## 📖 개발 가이드 (guides/)

| 문서 | 설명 | 상태 |

|------|------|------|### ⭐ 핵심 가이드

| **[IMPLEMENTATION_NOTES.md](./guides/IMPLEMENTATION_NOTES.md)** | 개발자 필독! React 18 HMR, 상태 관리, 성능 최적화 | ✅ COMPLETED |

| **[mol-viewer-integration.md](./guides/mol-viewer-integration.md)** | Mol\* 아키텍처, 훅 함수, MVS 지원 | ✅ COMPLETED || 문서 | 설명 | 상태 |

| [sequence-viewer-integration.md](./guides/sequence-viewer-integration.md) | 시퀀스 뷰어 통합 및 연동 | ✅ COMPLETED || ------------------------------------------------------------------------- | ------------------------------------------------- | ------------ |

| [linting-rules.md](./guides/linting-rules.md) | ESLint, Prettier, TypeScript strict | ✅ COMPLETED || **[IMPLEMENTATION_NOTES.md](./guides/IMPLEMENTATION_NOTES.md)** | 개발자 필독! React 18 HMR, 상태 관리, 성능 최적화 | ✅ COMPLETED |

| **[mol-viewer-integration.md](./guides/mol-viewer-integration.md)** | Mol\* 아키텍처, 훅 함수, MVS 지원 | ✅ COMPLETED |

### 주요 내용| [sequence-viewer-integration.md](./guides/sequence-viewer-integration.md) | 시퀀스 뷰어 통합 및 연동 | ✅ COMPLETED |

| [linting-rules.md](./guides/linting-rules.md) | ESLint, Prettier, TypeScript strict | ✅ COMPLETED |

#### IMPLEMENTATION_NOTES.md

- ✅ React 18 HMR 안정성 패턴### 주요 내용

- ✅ DOM 격리 (ref callback)

- ✅ 구조 로드 베스트 프랙티스#### IMPLEMENTATION_NOTES.md

- ✅ **상태 관리 아키텍처** (Jotai + Zustand)

- ✅ 성능 최적화 및 디버깅- ✅ React 18 HMR 안정성 패턴

- ✅ DOM 격리 (ref callback)

#### mol-viewer-integration.md- ✅ 구조 로드 베스트 프랙티스

- ✅ Mol\* Plugin 초기화- ✅ **상태 관리 아키텍처** (Jotai + Zustand)

- ✅ 훅 함수들: `usePluginContext`, `useStructure`, `useRepresentation`- ✅ 성능 최적화 및 디버깅

- ✅ MVS (MolViewSpec) 지원

- ✅ 실제 코드 예제#### mol-viewer-integration.md

---- ✅ Mol\* Plugin 초기화

- ✅ 훅 함수들: `usePluginContext`, `useStructure`, `useRepresentation`

## 🔌 API 명세 (api/)- ✅ MVS (MolViewSpec) 지원

- ✅ 실제 코드 예제

| 문서 | 설명 | 상태 |

|------|------|------|---

| **[phase-2-backend-api.md](./api/phase-2-backend-api.md)** | WebSocket API, 프레임 포맷, 오류 처리 | 📝 PLANNED |

## 🔌 API 명세 (api/)

### 주요 내용

- WebSocket 엔드포인트 정의| 문서 | 설명 | 상태 |

- 바이너리 프레임 프로토콜| ---------------------------------------------------------- | ------------------------------------- | ---------- |

- FastAPI 구현 예시| **[phase-2-backend-api.md](./api/phase-2-backend-api.md)** | WebSocket API, 프레임 포맷, 오류 처리 | 📝 PLANNED |

- 테스트 시나리오

### 주요 내용

---

- WebSocket 엔드포인트 정의

## 🎨 기획 및 설계 (planning/)- 바이너리 프레임 프로토콜

- FastAPI 구현 예시

| 문서 | 설명 | 상태 |- 테스트 시나리오

|------|------|------|

| **[plan.md](./planning/plan.md)** | 프로젝트 전체 로드맵, Phase별 구현 계획 | ✅ COMPLETED |---

| [DESIGN_UPDATE_SUMMARY.md](./planning/DESIGN_UPDATE_SUMMARY.md) | UI 컴포넌트 구조, 상태 관리 전략 | ✅ COMPLETED |

| [phase-2-boltz-inpainting.md](./planning/phase-2-boltz-inpainting.md) | Boltz 기반 인페인팅 설계 (최신) | 📝 PLANNED |## 🎨 기획 및 설계 (planning/)

| [PROJECT_MANAGEMENT_ARCHITECTURE.md](./planning/PROJECT_MANAGEMENT_ARCHITECTURE.md) | 프로젝트 관리 시스템 아키텍처 | ✅ COMPLETED |

| 문서 | 설명 | 상태 |

### 주요 내용| ----------------------------------------------------------------------------------- | --------------------------------------- | ------------ |

| **[plan.md](./planning/plan.md)** | 프로젝트 전체 로드맵, Phase별 구현 계획 | ✅ COMPLETED |

#### plan.md| [DESIGN_UPDATE_SUMMARY.md](./planning/DESIGN_UPDATE_SUMMARY.md) | UI 컴포넌트 구조, 상태 관리 전략 | ✅ COMPLETED |

- ✅ Electron + React + Mol\* 스택| [phase-2-boltz-inpainting.md](./planning/phase-2-boltz-inpainting.md) | Boltz 기반 인페인팅 설계 (최신) | 📝 PLANNED |

- ✅ Repair 워크플로우 (Mask + Inpaint + Refine 통합)| [PROJECT_MANAGEMENT_ARCHITECTURE.md](./planning/PROJECT_MANAGEMENT_ARCHITECTURE.md) | 프로젝트 관리 시스템 아키텍처 | ✅ COMPLETED |

- ✅ MolViewSpec 통합

- ✅ 상태 관리 원칙 (전역 최소화)### 주요 내용

- ✅ Mock 서버 계획

#### plan.md

#### phase-2-boltz-inpainting.md

- 📝 Boltz-Inpainting 기반 실시간 프리뷰- ✅ Electron + React + Mol\* 스택

- 📝 시간 기반 진행률- ✅ Repair 워크플로우 (Mask + Inpaint + Refine 통합)

- 📝 Zustand 상태 관리- ✅ MolViewSpec 통합

- 📝 다중 seed 결과 처리- ✅ 상태 관리 원칙 (전역 최소화)

- ✅ Mock 서버 계획

---

#### phase-2-boltz-inpainting.md

## ✅ 완료 기능 (completed/)

- 📝 Boltz-Inpainting 기반 실시간 프리뷰

| 문서 | 기능 | 완료일 |- 📝 시간 기반 진행률

|------|------|--------|- 📝 Zustand 상태 관리

| **[gap-visualization-complete.md](./completed/gap-visualization-complete.md)** | Missing Region 시각화 | 2025-10-26 |- 📝 다중 seed 결과 처리

| [WATER-HIDING-COMPLETED.md](./completed/WATER-HIDING-COMPLETED.md) | 워터 분자 숨기기 | 2025-10-25 |

| [COMPLETION_REPORT.md](./completed/COMPLETION_REPORT.md) | DNA/RNA Missing Region Detection | 2025-10-26 |---

| [SEQUENCE-VIEWER-UPDATE-2025-10-26.md](./completed/SEQUENCE-VIEWER-UPDATE-2025-10-26.md) | 시퀀스 뷰어 자동 체인 선택 | 2025-10-26 |

## ✅ 완료 기능 (completed/)

### 주요 완료 기능

| 문서 | 기능 | 완료일 |

#### gap-visualization-complete.md| ---------------------------------------------------------------------------------------- | -------------------------------- | ---------- |

- ✅ Partial residue 시각화 (ball-and-stick)| **[gap-visualization-complete.md](./completed/gap-visualization-complete.md)** | Missing Region 시각화 | 2025-10-26 |

- ✅ Complete gap 거리 측정선| [WATER-HIDING-COMPLETED.md](./completed/WATER-HIDING-COMPLETED.md) | 워터 분자 숨기기 | 2025-10-25 |

- ✅ 선택 관리 (empty space click 시 clear)| [COMPLETION_REPORT.md](./completed/COMPLETION_REPORT.md) | DNA/RNA Missing Region Detection | 2025-10-26 |

- ✅ Loci 기반 residue 검색| [SEQUENCE-VIEWER-UPDATE-2025-10-26.md](./completed/SEQUENCE-VIEWER-UPDATE-2025-10-26.md) | 시퀀스 뷰어 자동 체인 선택 | 2025-10-26 |

- ✅ 카메라 자동 포커스

### 주요 완료 기능

#### COMPLETION_REPORT.md (DNA/RNA Detection)

- ✅ DNA/RNA residue type 자동 분류#### gap-visualization-complete.md

- ✅ Nucleotide backbone 원자 정의

- ✅ Missing base/backbone 감지- ✅ Partial residue 시각화 (ball-and-stick)

- ✅ RNA 2'-OH 특수 처리- ✅ Complete gap 거리 측정선

- ✅ 선택 관리 (empty space click 시 clear)

---- ✅ Loci 기반 residue 검색

- ✅ 카메라 자동 포커스

## 🗄️ 아카이브 (archive/)

#### COMPLETION_REPORT.md (DNA/RNA Detection)

구버전 및 레거시 문서들입니다. 참고용으로만 사용하세요.

- ✅ DNA/RNA residue type 자동 분류

### 레거시 Gap Detection (archive/legacy-gap-detection/)- ✅ Nucleotide backbone 원자 정의

- `gap-detection-implementation.md` (빈 파일)- ✅ Missing base/backbone 감지

- `gap-detection-구현완료.md` (한글, 구버전)- ✅ RNA 2'-OH 특수 처리

- `gap-visualization.md` (초기 버전)

- `gap-visualization-summary.md` (중간 버전)---

→ **최신 문서**: [completed/gap-visualization-complete.md](./completed/gap-visualization-complete.md)## 🗄️ 아카이브 (archive/)

### 기타 아카이브구버전 및 레거시 문서들입니다. 참고용으로만 사용하세요.

- `IMPLEMENTATION_UPDATE.md` - 구식 업데이트 노트

- `real-time-inpainting-preview.md` - 레거시 Diffusion 기반 설계### 레거시 Gap Detection (archive/legacy-gap-detection/)

- `DNA-RNA-implementation-summary.md` - COMPLETION_REPORT로 대체됨

- `gap-detection-implementation.md` (빈 파일)

---- `gap-detection-구현완료.md` (한글, 구버전)

- `gap-visualization.md` (초기 버전)

## 🔄 최근 변경사항- `gap-visualization-summary.md` (중간 버전)

상세 내역: [LATEST_UPDATE_SUMMARY.md](./LATEST_UPDATE_SUMMARY.md)→ **최신 문서**: [completed/gap-visualization-complete.md](./completed/gap-visualization-complete.md)

### 2025-10-26: 문서 구조 대대적 정리 ✨### 기타 아카이브

- ✅ 폴더 구조 개편 (guides/, api/, planning/, completed/, archive/)

- ✅ 중복 문서 아카이브 (gap detection 관련 4개)- `IMPLEMENTATION_UPDATE.md` - 구식 업데이트 노트

- ✅ 문서 작성 가이드라인 생성 ([DOC_GUIDELINES.md](./DOC_GUIDELINES.md))- `real-time-inpainting-preview.md` - 레거시 Diffusion 기반 설계

- ✅ 파일명 정규화 (kebab-case, 영어)- `DNA-RNA-implementation-summary.md` - COMPLETION_REPORT로 대체됨

### 2025-10-26: Missing Region Visualization 완료 ✅---

- ✅ Partial residue + Complete gap 시각화

- ✅ Loci 기반 정확한 residue 선택## 🔄 최근 변경사항

- ✅ Empty space click 시 selection clear

- ✅ Ball-and-stick 표현 + 거리 측정선상세 내역: [LATEST_UPDATE_SUMMARY.md](./LATEST_UPDATE_SUMMARY.md)

### 2025-10-26: DNA/RNA Detection 완료 ✅### 2025-10-26: 문서 구조 대대적 정리 ✨

- ✅ Residue type 자동 분류 (protein/DNA/RNA)

- ✅ Nucleotide backbone 및 base 원자 정의- ✅ 폴더 구조 개편 (guides/, api/, planning/, completed/, archive/)

- ✅ Missing atom 전문가 분석 지표- ✅ 중복 문서 아카이브 (gap detection 관련 4개)

- ✅ 문서 작성 가이드라인 생성 ([DOC_GUIDELINES.md](./DOC_GUIDELINES.md))

### 2025-10-26: Sequence Viewer 통합 완료 ✅- ✅ 파일명 정규화 (kebab-case, 영어)

- ✅ Missing region 클릭 시 자동 체인 선택

- ✅ 3D viewer ↔ Sequence panel 동기화### 2025-10-26: Missing Region Visualization 완료 ✅

---- ✅ Partial residue + Complete gap 시각화

- ✅ Loci 기반 정확한 residue 선택

## 📊 구현 현황- ✅ Empty space click 시 selection clear

- ✅ Ball-and-stick 표현 + 거리 측정선

| 기능 | 상태 | 파일 | 문서 |

|------|------|------|------|### 2025-10-26: DNA/RNA Detection 완료 ✅

| Mol\* 뷰어 초기화 | ✅ | `mol-viewer/usePluginContext.ts` | [guide](./guides/mol-viewer-integration.md) |

| 구조 로드 | ✅ | `mol-viewer/useStructure.ts` | [guide](./guides/mol-viewer-integration.md) |- ✅ Residue type 자동 분류 (protein/DNA/RNA)

| Missing Region Detection | ✅ | `mol-viewer/useMissingRegionDetection.ts` | [completed](./completed/COMPLETION_REPORT.md) |- ✅ Nucleotide backbone 및 base 원자 정의

| Gap Visualization | ✅ | `mol-viewer/useMissingRegionVisuals.ts` | [completed](./completed/gap-visualization-complete.md) |- ✅ Missing atom 전문가 분석 지표

| Sequence Viewer | ✅ | `mol-viewer/useSequenceViewer.tsx` | [guide](./guides/sequence-viewer-integration.md) |

| Water Hiding | ✅ | `mol-viewer/useHideWater.ts` | [completed](./completed/WATER-HIDING-COMPLETED.md) |### 2025-10-26: Sequence Viewer 통합 완료 ✅

| 표현 관리 | ✅ | `mol-viewer/useRepresentation.ts` | [guide](./guides/mol-viewer-integration.md) |

| Inpainting Preview | 📝 | - | [planning](./planning/phase-2-boltz-inpainting.md) |- ✅ Missing region 클릭 시 자동 체인 선택

| Backend API | 📝 | - | [api](./api/phase-2-backend-api.md) |- ✅ 3D viewer ↔ Sequence panel 동기화

---

## 🐛 알려진 이슈## 📊 구현 현황

### ✅ 해결됨| 기능 | 상태 | 파일 | 문서 |

1. ~~HMR 중 removeChild 에러~~ → ref callback 패턴으로 해결| ------------------------ | ---- | ----------------------------------------- | ------------------------------------------------------ |

2. ~~Canvas3D가 null로 반환~~ → createPluginUI() 사용으로 해결| Mol\* 뷰어 초기화 | ✅ | `mol-viewer/usePluginContext.ts` | [guide](./guides/mol-viewer-integration.md) |

3. ~~CSP 위반 경고~~ → rawData() API로 해결| 구조 로드 | ✅ | `mol-viewer/useStructure.ts` | [guide](./guides/mol-viewer-integration.md) |

4. ~~Empty space click 시 selection 안 해제~~ → Direct event subscription으로 해결| Missing Region Detection | ✅ | `mol-viewer/useMissingRegionDetection.ts` | [completed](./completed/COMPLETION_REPORT.md) |

| Gap Visualization | ✅ | `mol-viewer/useMissingRegionVisuals.ts` | [completed](./completed/gap-visualization-complete.md) |

### 🔧 진행중| Sequence Viewer | ✅ | `mol-viewer/useSequenceViewer.tsx` | [guide](./guides/sequence-viewer-integration.md) |

- 없음| Water Hiding | ✅ | `mol-viewer/useHideWater.ts` | [completed](./completed/WATER-HIDING-COMPLETED.md) |

| 표현 관리 | ✅ | `mol-viewer/useRepresentation.ts` | [guide](./guides/mol-viewer-integration.md) |

---| Inpainting Preview | 📝 | - | [planning](./planning/phase-2-boltz-inpainting.md) |

| Backend API | 📝 | - | [api](./api/phase-2-backend-api.md) |

## 🔗 외부 참고 자료

---

- [Mol\* 공식 문서](https://molstar.org/)

- [Mol\* GitHub](https://github.com/molstar/molstar)## 🐛 알려진 이슈

- [Electron 가이드](https://www.electronjs.org/docs)

- [React 18 마이그레이션](https://react.dev/blog/2022/03/29/react-v18)### ✅ 해결됨

- [Jotai 문서](https://jotai.org/)

- [Zustand 문서](https://zustand-demo.pmnd.rs/)1. ~~HMR 중 removeChild 에러~~ → ref callback 패턴으로 해결

2. ~~Canvas3D가 null로 반환~~ → createPluginUI() 사용으로 해결

---3. ~~CSP 위반 경고~~ → rawData() API로 해결

4. ~~Empty space click 시 selection 안 해제~~ → Direct event subscription으로 해결

## 📝 문서 작성 규칙

### 🔧 진행중

새 문서를 작성하거나 기존 문서를 수정할 때는 반드시 [DOC_GUIDELINES.md](./DOC_GUIDELINES.md)를 참고하세요.

- 없음

**핵심 원칙**:

1. ✅ 동일 주제는 하나의 문서만 유지---

2. ✅ 상태 표시 필수 (Status, Date)

3. ✅ 적절한 폴더 배치## 🔗 외부 참고 자료

4. ✅ kebab-case 파일명

5. ✅ 구버전은 archive로 이동- [Mol\* 공식 문서](https://molstar.org/)

- [Mol\* GitHub](https://github.com/molstar/molstar)

---- [Electron 가이드](https://www.electronjs.org/docs)

- [React 18 마이그레이션](https://react.dev/blog/2022/03/29/react-v18)

**Maintained by**: Patchr Studio Team - [Jotai 문서](https://jotai.org/)

**Questions?** See [DOC_GUIDELINES.md](./DOC_GUIDELINES.md) FAQ section- [Zustand 문서](https://zustand-demo.pmnd.rs/)

---

## 📝 문서 작성 규칙

새 문서를 작성하거나 기존 문서를 수정할 때는 반드시 [DOC_GUIDELINES.md](./DOC_GUIDELINES.md)를 참고하세요.

**핵심 원칙**:

1. ✅ 동일 주제는 하나의 문서만 유지
2. ✅ 상태 표시 필수 (Status, Date)
3. ✅ 적절한 폴더 배치
4. ✅ kebab-case 파일명
5. ✅ 구버전은 archive로 이동

---

**Maintained by**: Patchr Studio Team  
**Questions?** See [DOC_GUIDELINES.md](./DOC_GUIDELINES.md) FAQ section

---

## 🎯 어떤 문서를 먼저 읽을까?

### 처음 프로젝트를 접하는 경우

1. **README.md** (프로젝트 개요)
2. **[DESIGN_UPDATE_SUMMARY.md](DESIGN_UPDATE_SUMMARY.md)** (전체 설계)
3. **[mol-viewer-integration.md](mol-viewer-integration.md)** (Mol\* 아키텍처)

### Mol\* 뷰어를 개발/수정하는 경우

1. **[IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md)** (필수!)
2. **[mol-viewer-integration.md](mol-viewer-integration.md)** (API 레퍼런스)
3. 코드: `src/renderer/src/components/mol-viewer/`

### 인페인팅 프리뷰를 개발하는 경우 (Boltz-Inpainting)

1. **[phase-2-boltz-inpainting.md](phase-2-boltz-inpainting.md)** ⭐ (시작하기)
2. **[phase-2-backend-api.md](phase-2-backend-api.md)** (API 명세)
3. **[IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md)** - WebSocket 섹션 (필요시)

### 백엔드를 개발하는 경우

1. **[plan.md](plan.md)** - 백엔드 스펙
2. **[real-time-inpainting-preview.md](real-time-inpainting-preview.md)** - API 프로토콜

---

## 🔄 최근 변경사항

### Oct 26, 2025 - Missing Region Visualization 완전 구현 ✅ (NEW!)

**구현 완료:**

- ✅ **Partial residue visualization** - 불완전한 residues 시각화
- ✅ **Complete missing region visualization** - 빠진 residues 범위 표시
- ✅ **Distance measurement lines** - Molstar Measurement API 활용
- ✅ **Selection management** - Empty space click 시 자동 clear
- ✅ **Ball-and-stick representation** - Sidechain 원자 표시
- ✅ **Nearby residue search** - ±5 residues 검색 + insertion code 처리
- ✅ **Comprehensive logging** - 상세한 디버그 정보

**핵심 기능:**

```typescript
// Gap click → Focus on gap
- Partial: Selection + ball-and-stick + zoom (radius=8)
- Complete: Both boundaries + distance line + zoom (0.8x distance)

// Empty space click → Clear all visualizations
plugin.managers.interactivity.lociSelects.deselectAll();
// + 모든 representations 제거

// Other residue click → Molstar native behavior (auto-managed)
```

**문서:**

- ✨ **[missing-region-visualization-complete.md](missing-region-visualization-complete.md)** - 완전 구현 가이드 (NEW!)
  - 선택 관리 (Selection lifecycle)
  - Loci 개념 및 사용법
  - 모든 Molstar API 상세 설명
  - 코드 예제 및 성능 최적화
  - 테스트 체크리스트

**해결한 이슈:**

- ❌ ~~Empty space 클릭해도 selection 안 됨~~ → **SOLVED**
  - 해결책: Direct event subscription + `deselectAll()`
  - 상세: [missing-region-visualization-complete.md](missing-region-visualization-complete.md) - Selection Management

**파일:**

- `src/renderer/src/components/mol-viewer/useMissingRegionVisuals.ts` (579 lines)
- `src/renderer/src/components/MolViewerPanel.tsx`
- `src/renderer/src/types/index.ts`

### Oct 25, 2025 - Phase 2: Zustand 상태 관리 및 탭 지속성 구현 ✅

**구현 완료:**

- ✅ **Zustand preview store** - React 라이프사이클 독립적 상태 관리
- ✅ **시간 기반 진행률** - interval이 탭 전환해도 계속 진행
- ✅ **SampleGallery 컴포넌트** - 다중 seed 결과 표시 + pLDDT 신뢰도
- ✅ **InpaintTab UI** - 파라미터 컨트롤 + 진행률 표시 (완전 동작)
- ✅ **상태 아키텍처** - Jotai (컴포넌트) + Zustand (전역) 분리

**문서 업데이트:**

- ✨ `IMPLEMENTATION_NOTES.md` - #11 상태 관리 아키텍처 추가
- ✨ `phase-2-boltz-inpainting.md` - 4.0~4.4 완전 재작성 (Zustand 기반)
- ✨ `README.md` - 상태 관리 섹션 업데이트 + Phase 2 진행률 반영

**핵심 개선사항:**

```typescript
// Before: 탭 전환하면 progress 멈춤
const [elapsed, setElapsed] = useState(0);
useEffect(() => {
  const timer = setInterval(() => setElapsed(e => e + 1), 1000);
  // unmount되면 timer 정지 ❌
}, []);

// After: 탭 전환해도 계속 진행 ✅
const { elapsed_s, startPreview } = usePreviewStore();
startPreview(runId, 5, () => {
  // Zustand 내부에서 interval 관리
});
```

### Oct 24, 2025 - Phase 2 설계: Boltz-Inpainting 기반 프리뷰 📝

**새로 작성된 문서:**

- ✨ **[phase-2-boltz-inpainting.md](phase-2-boltz-inpainting.md)** - 프론트엔드 설계 및 구현 가이드
- ✨ **[phase-2-backend-api.md](phase-2-backend-api.md)** - WebSocket API 명세 및 구현 예시

**주요 변경사항:**

- ✅ Diffusion 기반에서 **Boltz-Inpainting** 기반으로 변경
- ✅ 다단계 프레임 스트리밍 → **시간 기반 진행률 + 최종 결과 스트리밍**
- ✅ 파라미터 변경: `steps, tau, guidance` → `seeds[], temperature, confidence_threshold`
- ✅ 결과 처리: 중간 프레임 제거 → **seed별 단일 결과 처리**

**영향 받는 타입들:**

- `InpaintParams`: seeds, temperature, confidence_threshold
- `PreviewFrame`: plddt_mean, seed index 추가
- `PreviewState`: elapsed_s, remaining_s 추가

### Oct 24, 2025 - Mol\* React 18 통합 완료 ✅

**구현 완료:**

- ✅ Mol\* viewer 초기화 및 canvas3d 생성
- ✅ PDB 구조 로드 및 렌더링
- ✅ React 18 HMR 안정성 확보
- ✅ DOM 격리 패턴 적용

**해결한 이슈:**

- ❌ ~~NotFoundError: Failed to execute 'removeChild'~~ → **SOLVED**
  - 해결책: ref callback + 별도 DOM 생성
  - 상세 내용: [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) #1.2

**다음 단계:**

- WebSocket 기반 인페인팅 프리뷰 (현재 진행 중)
- 마스크 오버레이 시각화
- 구조 표현 (cartoon, surface, etc.)

---

## 📋 실제 구현 현황

| 기능                         | 상태         | 파일                                      | 비고                   |
| ---------------------------- | ------------ | ----------------------------------------- | ---------------------- |
| Mol\* 뷰어 초기화            | ✅ 완료      | `mol-viewer/usePluginContext.ts`          | ref callback 패턴      |
| 구조 로드                    | ✅ 완료      | `mol-viewer/useStructure.ts`              | rawData() 사용         |
| **Missing Region Detection** | ✅ 완료      | `mol-viewer/useMissingRegionDetection.ts` | Molstar Query API      |
| **Gap Visuals**              | ✅ 완료      | `mol-viewer/useMissingRegionVisuals.ts`   | **NEW**: 완전 구현! ✨ |
| 표현 적용                    | ✅ 완료      | `mol-viewer/useRepresentation.ts`         | ball-and-stick, 등     |
| 마스크 오버레이              | ⏳ 진행 중   | `mol-viewer/useMaskOverlay.ts`            | 이벤트 기반            |
| 선택 처리                    | ✅ 완료      | `mol-viewer/useSelection.ts`              | Event-based handling   |
| **Preview Store**            | ✅ 완료      | `store/preview-store.ts`                  | Zustand                |
| **InpaintTab UI**            | ✅ 완료      | `components/ControlPanel.tsx`             | Zustand 통합           |
| **SampleGallery**            | ✅ 완료      | `components/inpaint/SampleGallery.tsx`    | pLDDT 신뢰도 표시      |
| 인페인팅 프리뷰              | 🔧 진행 중   | -                                         | mock API 기본 동작 중  |
| usePreviewManager            | 📝 설계 완료 | -                                         | WebSocket 구현 대기    |
| MVS 지원                     | 📝 설계 완료 | -                                         | 구현 대기              |

---

## 🐛 알려진 이슈 및 해결책

### 1. HMR 중 removeChild 에러 ✅ FIXED

- **원인**: React와 Mol\*의 DOM 조작 충돌
- **해결책**: ref callback + 별도 div 생성
- **상세**: [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) #1

### 2. Canvas3D가 null로 반환됨 ✅ FIXED

- **원인**: DefaultPluginSpec() 대신 DefaultPluginUISpec() 필요
- **해결책**: createPluginUI() 사용
- **상세**: [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) #2

### 3. CSP 위반 경고 ✅ FIXED

- **원인**: Blob URL 사용
- **해결책**: rawData() API 사용
- **상세**: [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) #3.1

### 4. Empty Space Click 시 Selection 안 해제됨 ✅ FIXED

- **원인**: Molstar `SelectLoci` behavior가 programmatic selection을 auto-deselect하지 않음
- **해결책**: Direct event subscription + `deselectAll()` 호출
  ```typescript
  plugin.behaviors.interaction.click.subscribe(({ current }) => {
    if (current.loci.kind === "empty-loci") {
      plugin.managers.interactivity.lociSelects.deselectAll();
    }
  });
  ```
- **상세**: [missing-region-visualization-complete.md](missing-region-visualization-complete.md) - Selection Management

---

## 🔗 유용한 링크

- [Mol\* 공식 문서](https://molstar.org/)
- [Mol\* GitHub](https://github.com/molstar/molstar)
- [Electron 가이드](https://www.electronjs.org/docs)
- [React 18 마이그레이션](https://react.dev/blog/2022/03/29/react-v18)
- [Jotai 문서](https://jotai.org/)
