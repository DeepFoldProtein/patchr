# 📖 Patchr Studio 문서 작성 가이드라인

> **목적**: 문서의 중복, 상충, 혼란을 방지하고 일관된 문서 관리 체계를 구축

## 🎯 핵심 원칙

### 1. **Single Source of Truth (단일 진실 공급원)**

- 동일한 주제에 대해 **하나의 최신 문서만** 유지
- 업데이트가 필요하면 기존 문서를 수정, 새 문서 생성 금지
- 구버전은 즉시 `archive/` 폴더로 이동

### 2. **명확한 상태 표시**

모든 문서는 반드시 상단에 상태를 표기:

```markdown
> **Status**: ✅ COMPLETED | 🚧 IN PROGRESS | 📝 PLANNED | 🗄️ ARCHIVED  
> **Date**: 2025-10-26  
> **Last Updated**: 2025-10-26
```

### 3. **적절한 폴더 배치**

문서는 생명주기와 목적에 따라 분류:

| 폴더                        | 용도                               | 예시                                  |
| --------------------------- | ---------------------------------- | ------------------------------------- |
| `guides/`                   | 개발 가이드, API 사용법, 통합 방법 | `mol-viewer-integration.md`           |
| `api/`                      | API 명세, 엔드포인트 정의          | `phase-2-backend-api.md`              |
| `planning/`                 | 기획, 설계, 아키텍처               | `plan.md`, `DESIGN_UPDATE_SUMMARY.md` |
| `completed/`                | 완료된 기능의 최종 보고서          | `gap-visualization-complete.md`       |
| `archive/`                  | 구버전, 레거시 문서                | `IMPLEMENTATION_UPDATE.md`            |
| `archive/legacy-{feature}/` | 특정 기능의 구버전들               | `archive/legacy-gap-detection/`       |

### 4. **파일명 규칙**

#### ✅ 좋은 예

```
gap-visualization-complete.md       (명확, 소문자, 하이픈)
mol-viewer-integration.md           (기능 설명)
phase-2-backend-api.md              (버전 포함)
```

#### ❌ 나쁜 예

```
gap-detection-구현완료.md           (한글 사용)
LATEST_UPDATE_SUMMARY.md           (모호함, 항상 "latest"?)
update.md                          (너무 일반적)
gap-viz.md                         (약어 사용)
```

**규칙**:

- **소문자 + 하이픈** (`kebab-case`)
- **영어 파일명** (국제 협업 고려)
- **설명적이고 구체적** (무엇을 다루는지 명확)
- **날짜는 파일명에 넣지 않음** (메타데이터로 관리)

### 5. **업데이트 vs 새 문서**

#### 기존 문서 업데이트 (권장)

- 기능 개선, 버그 수정
- API 변경사항
- 구현 세부사항 추가
- **Last Updated** 날짜 갱신

#### 새 문서 생성 (제한적)

- **완전히 새로운 기능/모듈**
- **Phase 2, 3 등 주요 마일스톤**
- 기존 문서와 **명확히 구분되는 주제**

#### 구버전 처리

```bash
# 1. 최신 문서에 통합
# 2. 구버전 archive로 이동
mv old-doc.md archive/legacy-{feature}/

# 3. 새 문서에 참조 추가
> See also: `archive/legacy-gap-detection/` for historical context
```

## 📁 폴더 구조

```
docs/
├── INDEX.md                      # 📌 문서 전체 목차 (중요!)
├── DOC_GUIDELINES.md             # 📖 이 문서
├── LATEST_UPDATE_SUMMARY.md      # 📅 최신 변경사항 요약
│
├── guides/                       # 개발 가이드
│   ├── mol-viewer-integration.md
│   ├── IMPLEMENTATION_NOTES.md
│   ├── sequence-viewer-integration.md
│   └── linting-rules.md
│
├── api/                          # API 명세
│   └── phase-2-backend-api.md
│
├── planning/                     # 기획/설계
│   ├── plan.md
│   ├── DESIGN_UPDATE_SUMMARY.md
│   ├── PROJECT_MANAGEMENT_ARCHITECTURE.md
│   └── phase-2-boltz-inpainting.md
│
├── completed/                    # 완료 보고서
│   ├── gap-visualization-complete.md
│   ├── WATER-HIDING-COMPLETED.md
│   ├── COMPLETION_REPORT.md      # DNA/RNA detection
│   └── SEQUENCE-VIEWER-UPDATE-2025-10-26.md
│
├── archive/                      # 구버전 문서
│   ├── legacy-gap-detection/     # Gap detection 구버전들
│   │   ├── gap-detection-implementation.md
│   │   ├── gap-detection-구현완료.md
│   │   ├── gap-visualization.md
│   │   └── gap-visualization-summary.md
│   ├── IMPLEMENTATION_UPDATE.md
│   ├── real-time-inpainting-preview.md
│   └── DNA-RNA-implementation-summary.md
│
├── draft_images/                 # 이미지 자료
└── inpainting_examples/          # 예시 파일
```

## 📝 문서 템플릿

### 기능 가이드 (guides/)

```markdown
# {Feature Name} Integration Guide

> **Status**: ✅ COMPLETED | 🚧 IN PROGRESS  
> **Date**: 2025-10-26  
> **Last Updated**: 2025-10-26

## 📋 Overview

{Brief description of the feature}

## 🎯 Features

- Feature 1
- Feature 2

## 🏗️ Architecture

{Architecture diagram or description}

## 💻 Usage

### Basic Example

\`\`\`typescript
// Code example
\`\`\`

## 🔧 API Reference

| Function     | Description | Parameters    |
| ------------ | ----------- | ------------- |
| `funcName()` | Does X      | `param: type` |

## 🐛 Troubleshooting

### Issue 1

- **Problem**: ...
- **Solution**: ...

## 🔗 Related

- [Other Guide](./other-guide.md)
- [API Spec](../api/api-spec.md)
```

### 완료 보고서 (completed/)

```markdown
# {Feature Name} - Completion Report

> **Status**: ✅ COMPLETED  
> **Date**: 2025-10-26  
> **Completion Date**: 2025-10-26

## 📌 Summary

{What was accomplished}

## 🎉 Features Implemented

- [x] Feature 1
- [x] Feature 2

## 📊 Technical Details

### Implementation

- File: `path/to/file.ts`
- Lines: 500
- Key functions: `func1()`, `func2()`

## ✅ Testing

- [x] Unit tests pass
- [x] Integration tests pass
- [x] Manual testing completed

## 📚 Documentation

- Guide: [Link to guide](../guides/feature-guide.md)
- API: [Link to API](../api/feature-api.md)

## 🔮 Future Work

- Enhancement 1
- Enhancement 2
```

### API 명세 (api/)

```markdown
# {API Name} Specification

> **Status**: ✅ COMPLETED | 📝 PLANNED  
> **Date**: 2025-10-26  
> **Version**: 1.0.0

## Endpoints

### POST /api/endpoint

**Description**: Does something

**Request**:
\`\`\`json
{
"param1": "value",
"param2": 123
}
\`\`\`

**Response**:
\`\`\`json
{
"result": "success",
"data": {...}
}
\`\`\`

**Error Codes**:

- `400`: Bad request
- `500`: Internal error
```

## 🔄 문서 생명주기

```
📝 PLANNED          → 기획 단계, 아직 구현 안됨
      ↓
🚧 IN PROGRESS     → 개발 중, 문서 업데이트 중
      ↓
✅ COMPLETED        → 기능 완료, 문서 최종화
      ↓
🔄 UPDATED          → 유지보수로 인한 업데이트
      ↓
🗄️ ARCHIVED         → 더 이상 사용되지 않음, archive로 이동
```

## ⚠️ 안티패턴 (하지 말 것)

### ❌ 1. 중복 문서 생성

```
gap-detection.md
gap-detection-implementation.md
gap-detection-구현완료.md           ← 3개나 필요 없음!
gap-detection-final.md
```

**해결책**: 하나의 `gap-detection.md`만 유지하고 계속 업데이트

### ❌ 2. 모호한 파일명

```
update.md                          ← 무슨 업데이트?
LATEST.md                          ← 항상 "latest"인가?
summary.md                         ← 무엇의 summary?
```

**해결책**: 명확한 파일명 사용

### ❌ 3. 상태 없는 문서

```markdown
# Some Feature

This is documentation... ← 완료? 진행중? 계획?
```

**해결책**: 항상 상단에 상태 표시

### ❌ 4. 오래된 문서 방치

```
docs/
├── old-implementation.md          ← 삭제 안함
├── implementation-v2.md           ← 버전 관리 혼란
└── current-implementation.md
```

**해결책**: 구버전은 `archive/`로 이동

### ❌ 5. INDEX 업데이트 안함

```markdown
# INDEX.md

(작성된지 3개월 지남, 새 문서 10개 추가됨)
```

**해결책**: 문서 추가/이동 시 즉시 INDEX 업데이트

## ✅ 체크리스트

새 문서 작성 시:

- [ ] 상태 표시 추가 (Status, Date)
- [ ] 적절한 폴더에 배치
- [ ] 파일명 규칙 준수 (kebab-case, 영어)
- [ ] INDEX.md 업데이트
- [ ] 관련 문서에 링크 추가
- [ ] 기존 문서와 중복 확인

기존 문서 업데이트 시:

- [ ] Last Updated 날짜 갱신
- [ ] 변경 이력 추가 (선택)
- [ ] 관련 문서 링크 업데이트

문서 아카이브 시:

- [ ] `archive/` 또는 `archive/legacy-{feature}/`로 이동
- [ ] INDEX.md에서 제거 또는 "Archived" 표시
- [ ] 최신 문서에 아카이브 참조 추가

## 📊 문서 리뷰 주기

- **매주**: LATEST_UPDATE_SUMMARY.md 갱신
- **매월**: INDEX.md 전체 리뷰
- **분기마다**: 문서 정리 (archive 이동, 중복 제거)

## 🎓 FAQ

### Q: 문서를 수정해야 할까, 새로 만들어야 할까?

**A**: 95% 경우는 기존 문서 수정. 새 문서는 정말 새로운 주제일 때만.

### Q: 구버전 문서를 삭제해야 할까?

**A**: 삭제하지 말고 `archive/`로 이동. 히스토리 추적에 유용.

### Q: INDEX.md vs README.md?

**A**:

- `README.md`: 프로젝트 개요, 빠른 시작
- `INDEX.md`: 문서 전체 목차, 상세 가이드

### Q: 영어 vs 한국어?

**A**:

- **파일명**: 영어만
- **내용**: 팀 협의 (현재는 한국어 혼용)
- **코드/API**: 영어

### Q: 날짜 포맷은?

**A**: ISO 8601 권장: `2025-10-26`

## 🔧 도구

### 문서 정리 스크립트 (선택)

```bash
# 6개월 이상 업데이트 안된 문서 찾기
find docs/ -type f -mtime +180 -name "*.md"

# archive로 이동
mkdir -p docs/archive/legacy-$(date +%Y%m)
mv old-doc.md docs/archive/legacy-$(date +%Y%m)/
```

## 📚 참고 자료

- [Write the Docs](https://www.writethedocs.org/)
- [Google Developer Documentation Style Guide](https://developers.google.com/style)
- [Markdown Guide](https://www.markdownguide.org/)

---

**Last Updated**: 2025-10-26  
**Maintainer**: Patchr Studio Team
