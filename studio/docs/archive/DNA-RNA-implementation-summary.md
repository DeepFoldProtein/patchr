# DNA/RNA Missing Region Detection 구현 완료 - 최종 요약

## 📋 개요

**Protein** 뿐만 아니라 **DNA/RNA**의 missing residues 및 missing atoms를 전문가적 관점에서 분석하는 missing region detection 시스템을 구현했습니다.

---

## 🎯 핵심 문제와 해결책

### 문제점

기존 missing region detection은 **단백질(amino acids)만 처리**하고 DNA/RNA를 완전히 무시했습니다.

```typescript
// 이전 코드
const expectedAtoms = STANDARD_AA_ATOMS[residue.resName];
if (!expectedAtoms) continue; // DNA/RNA는 여기서 스킵됨!
```

### 해결책

Residue type을 판별하여 각각 다른 backbone 및 expected atoms으로 처리합니다.

```typescript
// 개선된 코드
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

---

## 🔬 구현 상세

### 1. Nucleotide Backbone 정의

DNA/RNA의 sugar-phosphate backbone을 정확히 정의했습니다:

| Atom         | 의미                 | 필수성 |
| ------------ | -------------------- | ------ |
| `P`          | 인산 (Phosphate)     | ★★★★★  |
| `O1P`, `O2P` | 인산 산소            | ★★★★★  |
| `O5'`        | 5' 수산기            | ★★★★★  |
| `C5'`        | 5' 탄소              | ★★★★★  |
| `C4'`        | 4' 탄소 (이상중심)   | ★★★★★  |
| `O4'`        | 에터 산소            | ★★★★★  |
| `C3'`        | 3' 탄소              | ★★★★★  |
| `O3'`        | 3' 수산기            | ★★★★★  |
| `C2'`        | 2' 탄소 (설탕)       | ★★★★★  |
| `O2'`        | 2' 수산기 (RNA only) | ★★★    |
| `C1'`        | 1' 탄소 (이상중심)   | ★★★★★  |

### 2. DNA vs RNA 구분

**핵심 차이점**:

```
DNA:
- O2' 없음
- T (thymine) 포함
- 2'-deoxy sugar

RNA:
- O2' 있음
- U (uracil) 포함
- Ribose sugar (2'-OH)
```

**자동 판별 로직**:

```typescript
function getResidueTypeFromAtoms(compId: string, atomNames: Set<string>) {
  // 1. D prefix 확인 (DA, DG, DC, DT)
  if (compId.startsWith("D") && [...].includes(compId)) return "dna";

  // 2. 특수 원자 확인
  if (compId === "U" || atomNames.has("O2'")) return "rna"; // U 또는 O2'
  if (compId === "T") return "dna"; // T는 DNA

  // 3. Backbone atoms 기반 판별
  const hasBackbone = Array.from(NUCLEOTIDE_BACKBONE_ATOMS)
    .some(atom => atomNames.has(atom));
  if (hasBackbone) {
    return atomNames.has("O2'") ? "rna" : "dna";
  }

  // 4. Protein 판별
  if (Array.from(BACKBONE_ATOMS).every(atom => atomNames.has(atom))) {
    return "protein";
  }
}
```

### 3. Base Atoms 정의

**Purine (A, G):**

```
Adenine (A): N9, C8, N7, C5, C6, N6, N1, C2, N3, C4
Guanine (G): N9, C8, N7, C5, C6, O6, N1, C2, N2, N3, C4
```

**Pyrimidine (C, U/T):**

```
Cytosine (C): N1, C2, O2, N3, C4, N4, C5, C6
Uracil (U):   N1, C2, O2, N3, C4, O4, C5, C6
Thymine (T):  N1, C2, O2, N3, C4, O4, C5, C7, C6
```

---

## 📊 Missing Region Detection 결과 분석

### Case 1: Complete Gap (전체 Nucleotide 누락)

```
Input:  DA5 존재, DA10 존재 → DA6, DA7, DA8, DA9 누락
Output:
  ✗ [dna→dna] Gap: between DA5 and DA10 (4 residues missing)

Impact: ★★★★★ - 가장 심각한 결손
Cause:  Electron density 부족 (결정화 문제)
```

### Case 2: Incomplete Backbone (Backbone 일부 원자 누락)

```
Input:  DA25: P, O5', C5', C4', O4' 있음 / C3', O3' 없음
Output:
  ⚠⚠ [DNA] Incomplete backbone: DA25
     missing backbone atoms: C3', O3'

Impact: ★★★★ - 구조적 문제
Cause:  Mobile region / 불완전한 electron density
Info:   Backbone connectivity 끊어짐
```

### Case 3: Missing Base (Base 원자 누락)

```
Input:  DA15: P, O5', C5', ... C1' 모두 있음 / N9, C8, ... 없음
Output:
  ⚠ [DNA] Partial: DA15
    missing 10 base atoms: N9, C8, N7, C5, C6, N6, N1, C2, N3, C4

Impact: ★★★ - 중간 정도
Cause:  Base flexibility / high B-factor region
Info:   Backbone geometry로 base 위치 제약 가능
```

### Case 4: RNA의 2'-OH 누락 (RNA only)

```
Input:  A5: 모든 backbone atoms 있음 / O2' 없음
Output:
  ⚠ [RNA] Partial: A5
    missing 1 base/sidechain atoms: O2'

Impact: ★★ - 낮음
Cause:  Hydration environment / dynamics
Info:   RNA의 특성 반영, 복구 난이도 낮음
```

---

## 🔧 기술 구현

### 파일 수정 위치

**파일**: `src/renderer/src/components/mol-viewer/useMissingRegionDetection.ts`

### 추가된 구성 요소

1. **상수**:
   - `NUCLEOTIDE_BACKBONE_ATOMS` (Line 25-36)
   - `DNA_NUCLEOTIDES` (Line 100-132)
   - `RNA_NUCLEOTIDES` (Line 134-156)

2. **함수**:
   - `getResidueType()` (Line ~280) - 단순 comp_id 기반
   - `getResidueTypeFromAtoms()` (Line ~333) - backbone atoms 기반 (더 신뢰도 높음)
   - `threeToOne()` 확장 (Line ~383) - DNA/RNA 코드 변환

3. **데이터 구조 확장**:

   ```typescript
   interface ResidueData {
     // ... 기존 필드
     resType: "protein" | "dna" | "rna" | "unknown"; // NEW
   }
   ```

4. **Missing Region Detection 로직**:
   - Line 760+: Chain type 정보 로깅
   - Line 880+: Residue type별 expected atoms 처리
   - Line 914+: Backbone atoms 확인 (type 별로 다른 기준)
   - Line 921+: Missing atoms 감지 (residue type에 따른 분류)

---

## 📈 향상된 로깅

### Before (기존)

```
[Missing Region Detection] Chain A: 150 residues, SEQRES length: 150
  ✗ Gap: between ALA45 and ALA48 (2 residues missing)
  ⚠ Partial: GLY67 missing 1 sidechain atoms: CB
```

### After (개선)

```
[Missing Region Detection] Chain A: 150 residues (protein: 150), SEQRES length: 150
  ✗ [protein→protein] Gap: between ALA45 and ALA48 (2 residues missing)
  ⚠ [protein] Partial: GLY67 missing 1 sidechain atoms: CB

[Missing Region Detection] Chain B: 50 residues (dna: 50), SEQRES length: 50
  ✗ [dna→dna] Gap: between DA5 and DA10 (4 residues missing)
  ⚠ [DNA] Partial: DA15 missing 10 base atoms: N9, C8, N7, C5, C6, N6, N1, C2, N3, C4
  ⚠⚠ [DNA] Incomplete backbone: DA25 missing backbone atoms: C3', O3'

[Missing Region Detection] Chain C: 40 residues (rna: 40), SEQRES length: 40
  ✗ [rna→rna] Gap: between A3 and A8 (4 residues missing)
  ⚠ [RNA] Partial: A15 missing 1 base/sidechain atoms: O2'
```

---

## 🧬 전문가 분석: DNA/RNA의 특수한 Missing 패턴

### 1. 완전 Nucleotide 누락 (Complete Gap)

- **Structural Impact**: ★★★★★
- **Biological Significance**: 높음 (순서 정보 손실)
- **Recovery Difficulty**: 높음 (전체 구조 복원 필요)
- **Common Causes**:
  - Crystal packing 불량
  - Electron density 매우 약함
  - Loop region의 구조 유동성

### 2. Backbone 부분 누락 (Incomplete Backbone)

- **Structural Impact**: ★★★★
- **Biological Significance**: 매우 높음 (연결성 끊김)
- **Recovery Difficulty**: 매우 높음 (기하학 제약 엄격)
- **Examples**:
  - `P` 없음 → 인산 연결 손실
  - `O3'` 없음 → 3'-5' 연결고리 불완전
  - `C3'`, `C4'` 없음 → backbone sugar 손상

### 3. Base 누락 (Partial Gap)

- **Structural Impact**: ★★★
- **Biological Significance**: 중간-높음 (서열정보는 있음)
- **Recovery Difficulty**: 중간 (backbone으로 제약 가능)
- **Examples**:
  - Imidazole ring 없음 (purine)
  - Pyrimidine ring 누락
  - Sidechain 원소 부분 누락

### 4. RNA 2'-OH 누락 (RNA specific)

- **Structural Impact**: ★★
- **Biological Significance**: 낮음-중간
- **Recovery Difficulty**: 낮음
- **Why**:
  - RNA의 catalytic activity와 관련
  - Hydration dynamics 반영
  - 단순히 원자 누락이 아니라 구조적 특성

---

## ✅ 검증 및 테스트

### 코드 검증

```bash
✓ TypeScript 컴파일 성공
✓ ESLint 통과 (prettier 포맷 적용)
✓ 타입 안전성 확보
```

### 테스트 대상

실제 구조 데이터에서 테스트 예정:

- Mixed protein-DNA structures (e.g., DNA-binding proteins)
- RNA structures (tRNA, rRNA, mRNA)
- Protein-RNA complexes
- Double helix DNA with gaps

---

## 📚 참고 자료

### PDB 포맷

- **인산**: P, O1P/OP1, O2P/OP2
- **설탕**: C1', C2', C3', C4', C5'
- **수산기**: O2', O3', O4', O5'
- **염기**: N9(purine), N1(pyrimidine) 등

### DNA vs RNA 특성

| 특성        | DNA                 | RNA                             |
| ----------- | ------------------- | ------------------------------- |
| Sugar       | 2'-Deoxy            | 2'-OH                           |
| Base        | A,G,C,T             | A,G,C,U                         |
| Structure   | Double helix (주로) | Various (often single-stranded) |
| Flexibility | Lower               | Higher                          |

### 참고 논문

- Saenger, W. (1984). "Principles of Nucleic Acid Structure"
- IUCr Crystallographic Information Framework
- PDB File Format Specification v3.30

---

## 🚀 다음 단계

### Phase 2: 추가 기능

1. **Modified Nucleotides**: DUR, 5MU, 2MG 등 화학적 수정
2. **Double Helix Analysis**: 양 strand의 동시 missing region 감지
3. **Base Pairing Validation**: Watson-Crick pairing 확인
4. **B-factor Analysis**: 유동성 vs true missing residue 구분
5. **Secondary Structure**: RNA의 secondary structure 기반 분석

### Phase 3: 복구 알고리즘

1. Nucleotide backbone geometry 제약
2. Base pairing 정보 활용
3. van der Waals interaction 계산
4. Dihedral angle 최적화

---

## 📝 코드 사용 예시

```typescript
// useMissingRegionDetection 훅 사용
useMissingRegionDetection(plugin, true);

// 결과: missingRegionsDetectedAtom에 저장된 MissingRegionInfo[]
// - Complete gaps (entire nucleotides missing)
// - Partial gaps (backbone or base atoms missing)
// - RNA-specific gaps (2'-OH missing)

// RepairSegment 생성:
repairSegments = [
  {
    segmentId: "segment_0",
    chainId: "A",
    gaps: [...], // protein gaps
    repairType: "full", // complete gap이므로
    contextRadius: 6.0,
    needsSequenceInput: false
  },
  {
    segmentId: "segment_1",
    chainId: "B",
    gaps: [...], // DNA gaps
    repairType: "full",
    contextRadius: 6.0,
    needsSequenceInput: false
  },
  {
    segmentId: "segment_2",
    chainId: "C",
    gaps: [...], // RNA gaps including partial O2'
    repairType: "full",
    contextRadius: 6.0,
    needsSequenceInput: false
  }
];
```

---

## 📄 문서 위치

최상세 문서: `docs/DNA-RNA-missing-region-detection.md`
