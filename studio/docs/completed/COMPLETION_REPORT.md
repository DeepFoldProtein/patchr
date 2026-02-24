# 💡 DNA/RNA Missing Region Detection 구현 완료 보고서

## 📌 프로젝트 개요

**기간**: 2024년 10월 26일  
**목표**: DNA/RNA missing residues 및 missing atoms 감지 시스템 구축  
**상태**: ✅ 완료

---

## 🎯 주요 성과

### 1. **Residue Type 자동 분류** ✓

- **Protein** (amino acids): ALA, GLY, PRO 등 20가지
- **DNA** (nucleotides): DA, DG, DC, DT
- **RNA** (nucleotides): A, G, C, U
- **Unknown**: 기타 리간드, modified residues

**자동 판별 기준**:

```
1️⃣  Comp_id 기반: DA → DNA, U → RNA
2️⃣  Backbone atoms: O2' 있음 → RNA, 없음 → DNA
3️⃣  특수 마커: T → DNA, U → RNA
```

### 2. **DNA/RNA 원자 정의** ✓

**Nucleotide Backbone** (11개 필수 원자):

```
P, O1P, O2P, O5', C5', C4', O4', C3', O3', C2', C1'
```

**Base Atoms** (유형별):

- **Adenine (A/DA)**: N9, C8, N7, C5, C6, N6, N1, C2, N3, C4
- **Guanine (G/DG)**: N9, C8, N7, C5, C6, O6, N1, C2, N2, N3, C4
- **Cytosine (C/DC)**: N1, C2, O2, N3, C4, N4, C5, C6
- **Uracil (U)**: N1, C2, O2, N3, C4, O4, C5, C6
- **Thymine (T/DT)**: N1, C2, O2, N3, C4, O4, C5, C7, C6

### 3. **Missing Region Detection 알고리즘 확장** ✓

#### Before ❌

```typescript
const expectedAtoms = STANDARD_AA_ATOMS[residue.resName];
if (!expectedAtoms) continue; // DNA/RNA 무시!
```

#### After ✅

```typescript
if (residue.resType === "protein") {
  expectedAtoms = STANDARD_AA_ATOMS[residue.resName];
  backboneAtoms = BACKBONE_ATOMS;
} else if (residue.resType === "dna") {
  expectedAtoms = DNA_NUCLEOTIDES[residue.resName];
  backboneAtoms = NUCLEOTIDE_BACKBONE_ATOMS;
} else if (residue.resType === "rna") {
  expectedAtoms = RNA_NUCLEOTIDES[residue.resName];
  backboneAtoms = NUCLEOTIDE_BACKBONE_ATOMS;
}
```

### 4. **전문가 분석 지표** ✓

| Gap 타입               | 심각도 | 설명                     | 로그                                   |
| ---------------------- | ------ | ------------------------ | -------------------------------------- |
| Complete Gap           | ★★★★★  | 전체 residue 누락        | `✗ [type→type] Gap: ...`               |
| Incomplete Backbone    | ★★★★   | Backbone 원자 누락       | `⚠⚠ [TYPE] Incomplete backbone: ...` |
| Missing Base/Sidechain | ★★★    | Base/sidechain 원자 누락 | `⚠ [TYPE] Partial: ...`               |
| RNA 2'-OH 누락         | ★★     | RNA 특수 원자            | `⚠ [RNA] Partial: ...`                |

### 5. **개선된 로깅** ✓

```
Before:
[Missing Region Detection] Chain A: 150 residues, SEQRES length: 150
  ✗ Gap: between ALA45 and ALA48 (2 residues missing)

After:
[Missing Region Detection] Chain A: 150 residues (protein: 150), SEQRES length: 150
  ✗ [protein→protein] Gap: between ALA45 and ALA48 (2 residues missing)

[Missing Region Detection] Chain B: 50 residues (dna: 50), SEQRES length: 50
  ✗ [dna→dna] Gap: between DA5 and DA10 (4 residues missing)
  ⚠ [DNA] Partial: DA15 missing 10 base atoms: N9, C8, N7, ...

[Missing Region Detection] Chain C: 40 residues (rna: 40), SEQRES length: 40
  ✗ [rna→rna] Gap: between A3 and A8 (4 residues missing)
  ⚠ [RNA] Partial: A15 missing 1 atom: O2'
```

---

## 🔧 구현 상세

### 파일 수정

**`src/renderer/src/components/mol-viewer/useMissingRegionDetection.ts`**

- **새 상수** (158줄 추가):
  - `NUCLEOTIDE_BACKBONE_ATOMS` (Line 25-36)
  - `DNA_NUCLEOTIDES` (Line 100-132)
  - `RNA_NUCLEOTIDES` (Line 134-156)

- **새 함수** (180줄 추가):
  - `getResidueType()` (Line ~280): Comp_id 기반 판별
  - `getResidueTypeFromAtoms()` (Line ~333): Backbone atoms 기반 판별
  - `threeToOne()` 확장 (Line ~383): DNA/RNA 변환 추가

- **데이터 구조 확장** (1줄 추가):
  - `ResidueData.resType` 필드

- **Missing Region Detection 로직** (~150줄 수정):
  - Chain type 통계 로깅
  - Residue type별 expected atoms 처리
  - Residue type별 backbone 검증
  - 향상된 로그 메시지

**총 변경**: ~490줄 (코멘트 포함)

### 코드 품질

✅ **TypeScript** 컴파일 성공 (타입 안전성)  
✅ **ESLint** 통과 (코드 스타일)  
✅ **Prettier** 포맷팅 완료

---

## 🧬 DNA/RNA 특수성 처리

### DNA vs RNA 구분

```typescript
// RNA 특성
if (atomNames.has("O2'")) {
  return "rna"; // 2'-hydroxyl 있음
}
if (compId === "U") {
  return "rna"; // Uracil
}

// DNA 특성
if (compId === "T" || compId === "DT") {
  return "dna"; // Thymine
}
```

### Missing Pattern 분석

| Pattern       | DNA 빈도 | RNA 빈도  | 의미               |
| ------------- | -------- | --------- | ------------------ |
| Complete missing region  | 높음     | 중간      | Sequence 정보 손실 |
| Backbone 누락 | 낮음     | 중간-높음 | Mobile region      |
| Base 누락     | 중간     | 높음      | Flexibility        |
| O2' 누락      | N/A      | 낮음      | Hydration dynamics |

### 복구 난이도

```
Protein Complete Gap:     ★★★☆☆ (중간)
DNA/RNA Complete Gap:     ★★★★☆ (높음) - backbone geometry 제약
Protein Sidechain:        ★★☆☆☆ (낮음)
DNA/RNA Base:             ★★★☆☆ (중간) - backbone으로 제약
DNA/RNA Backbone:         ★★★★★ (매우 높음) - 구조적 제약 심함
RNA O2':                  ★☆☆☆☆ (매우 낮음)
```

---

## 📊 데이터 구조

### ResidueData (확장)

```typescript
interface ResidueData {
  chainId: string; // 체인 ID
  authSeqId: number; // Sequence 번호
  insCode: string; // Insertion code
  resId: number; // Label sequence ID
  resName: string; // Component ID (ALA, DA, A, ...)
  resType: "protein" | "dna" | "rna" | "unknown"; // ⭐ NEW: 타입 분류
  atomNames: Set<string>; // 존재하는 원자들
}
```

### MissingRegionInfo (기존, 로그 개선)

```typescript
interface MissingRegionInfo {
  regionId: string;
  chainId: string;
  startResId: number;
  endResId: number;
  startAuthSeqId: number;
  endAuthSeqId: number;
  insertionCode?: string;
  regionLength: number;
  regionType: "complete" | "partial"; // 로그에 residue type 추가 표시
  sequence?: string;
  sequenceKnown: boolean;
  missingAtoms?: string[];
}
```

---

## 🔬 과학적 배경

### Nucleotide Backbone

DNA와 RNA의 기본 구조는 sugar-phosphate backbone입니다:

```
    O
    ║
O - P - O  (인산)
    │
    O - C5'  (5' 탄소)
        │
       C4'  (4' 탄소, 이상중심)
       / \
      O   C3'  (3' 탄소)
      │   │
    O-    O-  (3' 수산기)
```

### Base Pairing (Watson-Crick)

```
DNA:  A-T (2 수소결합), G-C (3 수소결합)
RNA:  A-U (2 수소결합), G-C (3 수소결합)
```

### 2'-OH의 의미 (RNA)

- RNA는 2'-OH을 가짐 → **ribose**
- DNA는 2'-H만 가짐 → **2'-deoxyribose**
- 2'-OH은 RNA의 **catalytic activity** 담당
- 따라서 누락 시 구조적/기능적 문제 발생

---

## 📈 테스트 시나리오

### Scenario 1: Mixed Protein-DNA Complex

```
Chain A (Protein): 150 residues
  - Gap at 45-48 (3 missing)
  - Partial at 67 (sidechain missing)

Chain B (DNA): 50 nucleotides
  - Gap at 5-10 (5 missing)
  - Partial at 15 (base missing)
  - Backbone incomplete at 25
```

### Scenario 2: RNA Structure

```
Chain A (RNA): 40 nucleotides
  - Gap at 3-8 (5 missing)
  - Partial at 15 (O2' missing)
  - Partial at 20 (base missing)
```

---

## 📚 문서

### 생성된 문서

1. **`docs/DNA-RNA-missing-region-detection.md`** (1200줄)
   - 상세 기술 설명
   - 전체 원자 정의
   - 알고리즘 상세

2. **`docs/DNA-RNA-implementation-summary.md`** (500줄)
   - 최종 요약
   - Case 분석
   - 다음 단계

---

## ✅ 검증 체크리스트

- [x] TypeScript 타입 안정성
- [x] ESLint 코드 스타일
- [x] Prettier 포맷팅
- [x] 전체 코드 검토
- [x] DNA/RNA 원자 정의 완료
- [x] Residue type 분류 로직
- [x] Gap detection 알고리즘 확장
- [x] 로깅 시스템 개선
- [x] 문서화 완료

---

## 🚀 다음 단계 (Future Work)

### Phase 2: Advanced Features

1. **Modified Nucleotides** (DUR, 5MU, 2MG 등)
2. **Base Pairing Analysis** (Watson-Crick 검증)
3. **Secondary Structure** (RNA의 stem-loop 등)
4. **B-factor Analysis** (유동성 vs 결손 구분)
5. **van der Waals Validation** (원자간 거리)

### Phase 3: Repair Integration

1. Nucleotide backbone 기하학 제약
2. Base pairing 정보 활용
3. dihedral angle 최적화
4. Molecular dynamics 기반 복구

---

## 💬 요약

DNA/RNA의 missing residues와 atoms를 **타입별로 정확하게 분류**하고 **전문가적 관점에서 분석**하는 시스템을 구현했습니다.

**핵심 개선**:

- ❌ 기존: DNA/RNA 무시 → ✅ 개선: DNA/RNA 명시적 처리
- ❌ 기존: 모든 residue 동일 기준 → ✅ 개선: 타입별 맞춤 기준
- ❌ 기존: 단순 로그 → ✅ 개선: 상세한 타입/심각도 정보

이제 **단백질-DNA 복합체, RNA 구조** 등 다양한 생물학적 분자를 정확하게 분석할 수 있습니다.
