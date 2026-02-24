# DNA/RNA Missing Region Detection 구현 완료

## 개요

DNA/RNA 구조의 missing residues 및 missing atoms를 전문가적 관점에서 분석하기 위한 missing region detection 로직을 확장했습니다.

---

## 주요 변경 사항

### 1. Residue Type 분류 (Protein/DNA/RNA)

#### 새로운 상수 정의

**DNA Nucleotide Backbone Atoms:**

- `P` (인산, Phosphate)
- `O5'`, `C5'` (5' sugar)
- `C4'`, `O4'` (4' carbon, anomeric carbon for RNA)
- `C3'`, `O3'` (3' sugar)
- `C2'` (2' carbon - RNA에만 O2' 존재)
- `C1'` (1' carbon)

**DNA Nucleotides (표준 PDB 명명법):**

```
DA (2'-Deoxyadenosine): P, O1P, O2P, O5', C5', C4', O4', C3', O3', C2', C1', [Adenine base atoms...]
DG (2'-Deoxyguanosine)
DC (2'-Deoxycytidine)
DT (2'-Deoxythymidine)
```

**RNA Nucleotides:**

```
A (Adenosine): P, O1P, O2P, O5', C5', C4', O4', C3', O3', C2', O2', C1', [Adenine base atoms...]
G (Guanosine)
C (Cytidine)
U (Uridine) - DNA는 T(thymine), RNA는 U(uracil)
```

### 2. Residue Type 판별 함수

#### `getResidueType(compId: string)`

- **용도**: 간단한 component ID 기반 판별
- **반환값**: `"protein" | "dna" | "rna" | "unknown"`

```typescript
// 예시
getResidueType("ALA") → "protein"
getResidueType("DA")  → "dna"
getResidueType("U")   → "rna"
```

#### `getResidueTypeFromAtoms(compId: string, atomNames: Set<string>)`

- **용도**: backbone atoms 존재 여부를 기반으로 더 신뢰도 높은 판별
- **DNA vs RNA 구분 기준**:
  - RNA: `O2'` (2'-hydroxyl) 또는 `U` (uracil) 존재
  - DNA: `O2'` 없음, `T` (thymine) 존재
- **반환값**: `"protein" | "dna" | "rna" | "unknown"`

```typescript
// 예시: 불명확한 nucleotide 판별
const atoms = new Set(["P", "C5'", "O2'", ...]);
getResidueTypeFromAtoms("A", atoms) → "rna"  // O2' 있음

const atoms = new Set(["P", "C5'", ...]);
getResidueTypeFromAtoms("T", atoms) → "dna"  // O2' 없고 T 있음
```

### 3. Improved 3-letter to 1-letter 변환

기존 `threeToOne()` 함수를 확장하여 DNA/RNA 지원:

```typescript
// Protein
threeToOne("ALA") → "A"
threeToOne("GLY") → "G"

// DNA
threeToOne("DA") → "A"
threeToOne("DG") → "G"
threeToOne("DC") → "C"
threeToOne("DT") → "T"

// RNA
threeToOne("A") → "A"
threeToOne("G") → "G"
threeToOne("C") → "C"
threeToOne("U") → "U"
```

### 4. Residue 데이터 구조 확장

```typescript
interface ResidueData {
  chainId: string; // auth_asym_id
  authSeqId: number; // auth_seq_id
  insCode: string; // pdbx_PDB_ins_code
  resId: number; // label_seq_id
  resName: string; // comp_id (e.g., "ALA", "DA", "A")
  resType: "protein" | "dna" | "rna" | "unknown"; // NEW: 잔기 타입
  atomNames: Set<string>; // 실제 존재하는 atom 이름
}
```

---

## Missing Region Detection 알고리즘 개선

### 1. Complete Missing Region (전체 Residue 누락)

**기존**: 모든 chain에서 동일하게 처리
**개선**: Residue type 별로 다른 backbone 기준 적용

```
Protein missing region:  residue position에 아무 atom도 없음
DNA/RNA missing region:  nucleotide position에 아무 atom도 없음
```

### 2. Partial Missing Region (Atom 누락)

#### Protein - Sidechain 누락

```
Expected: N, CA, C, O, CB, ... (amino acid 표준 atoms)
Missing: CB, CG, ... (sidechain)
Status:  ⚠ Partial - backbone 완전하지만 sidechain 누락
```

#### DNA/RNA - Base 또는 Backbone 원자 누락

**Case 1: Backbone 완전, Base 누락**

```
Expected: P, O1P, O2P, O5', C5', C4', O4', C3', O3', C2'(O2'), C1', N9, C8, ... (base atoms)
Missing: N9, C8, ... (base atoms)
Status: ⚠ [DNA/RNA] Partial - backbone은 완전하지만 base 부분 누락

예: DA 핵산이 설탕-인산 backbone은 있지만 adenine base 없음
```

**Case 2: Backbone 일부 누락**

```
Expected: P, O5', C5', C4', O4', C3', O3', C2', C1'
Missing: P, O3' (인산 없음, 3' hydroxyl 없음)
Status: ⚠⚠ [DNA/RNA] Incomplete backbone - 구조적 문제 심각

예: 핵산의 backbone 자체가 파괴되어 있음 (매우 드문 경우)
```

### 3. 개선된 로깅

**Before:**

```
[Missing Region Detection] Chain A: 150 residues, SEQRES length: 150
  ✗ Gap: between ALA45 and ALA48 (2 residues missing)
  ⚠ Partial: GLY67 missing 1 sidechain atoms: CB
```

**After:**

```
[Missing Region Detection] Chain A: 150 residues (protein: 150), SEQRES length: 150
  ✗ [protein→protein] Missing region: between ALA45 and ALA48 (2 residues missing)
  ⚠ [protein] Partial: GLY67 missing 1 sidechain atoms: CB

[Missing Region Detection] Chain B: 50 nucleotides (dna: 50), SEQRES length: 50
  ✗ [dna→dna] Missing region: between DA5 and DA10 (4 residues missing)
  ⚠ [DNA] Partial: DA15 missing 9 base atoms: N9, C8, N7, ...

[Missing Region Detection] Chain C: 40 nucleotides (rna: 40), SEQRES length: 40
  ⚠⚠ [RNA] Incomplete backbone: A25 missing backbone atoms: O3', C1' and base atoms: ...
```

---

## 전문가적 분석 관점

### DNA/RNA의 특수한 Missing 패턴

#### 1. **완전 nucleotide 누락** (Complete Missing Region)

- **원인**: 구조 결정 중 electron density 부족
- **영향도**: ★★★★★ (높음)
- **복구 난이도**: 높음 (전체 구조 복원 필요)

#### 2. **Sugar-Phosphate Backbone 부분 누락** (Incomplete Backbone)

- **원인**:
  - Flexible loop region
  - 결정화 중 부분적 손상
  - Mobile region의 불완전한 electron density
- **영향도**: ★★★★ (높음)
- **복구 난이도**: 높음 (backbone 기하학 제약)
- **예시**:
  - 인산(`P`) 없음 → backbone 연결성 끊김
  - `O3'` 또는 `C3'` 없음 → nucleotide linkage 불완전

#### 3. **Nitrogenous Base 누락** (Partial Missing Region)

- **원인**:
  - Base pairing region의 flexibility
  - ssDNA/ssRNA의 base 내부 이동
  - B-factor 높은 영역
- **영향도**: ★★★ (중간)
- **복구 난이도**: 중간 (backbone 기하학으로 base 위치 제약)
- **예시**:
  - Adenine의 imidazole ring(`N9, C8, N7, ...`) 없음
  - Base 전체 누락되지만 backbone은 존재

#### 4. **2'-OH Group 누락 (RNA only)**

- **원인**: RNA의 `O2'`는 hydrophobic environment에서 수화화 환경에 따라 보존 여부 결정
- **영향도**: ★★ (낮음-중간)
- **의미**: 단순히 원자 누락이 아니라 RNA의 구조적 특성 반영
- **참고**: 2'-OH는 RNA의 catalytic activity 및 구조안정성에 중요

---

## 기술적 세부사항

### Atom Name 표준화 (PDB Format)

**Protein backbone:**

- `N`: Nitrogen (backbone)
- `CA`: Alpha carbon
- `C`: Carbonyl carbon
- `O`: Carbonyl oxygen

**DNA/RNA backbone:**

- `P`: Phosphorus (인산)
- `O1P`, `O2P`: Phosphate oxygens
- `O5'`: 5' hydroxyl oxygen
- `C5'`: 5' carbon
- `C4'`: 4' carbon (anomeric carbon)
- `O4'`: Ether oxygen
- `C3'`: 3' carbon
- `O3'`: 3' hydroxyl oxygen
- `C2'`: 2' carbon (sugar)
- `O2'`: 2' hydroxyl (RNA only)
- `C1'`: 1' carbon (anomeric carbon)

**Base atoms (Purine - Adenine/Guanine):**

```
Adenine: N9, C8, N7, C5, C6, N6, N1, C2, N3, C4
Guanine: N9, C8, N7, C5, C6, O6, N1, C2, N2, N3, C4
```

**Base atoms (Pyrimidine - Cytosine/Uracil/Thymine):**

```
Cytosine: N1, C2, O2, N3, C4, N4, C5, C6
Uracil:   N1, C2, O2, N3, C4, O4, C5, C6
Thymine:  N1, C2, O2, N3, C4, O4, C5, C7, C6
```

---

## 사용 예시

### Missing Region Detection 결과 활용

```typescript
// missing region detection에서 반환된 MissingRegionInfo
const gaps: MissingRegionInfo[] = [
  {
    regionId: "chain_A_gap_10_12",
    chainId: "A",
    startResId: 10,
    endResId: 12,
    startAuthSeqId: 10,
    endAuthSeqId: 12,
    regionLength: 3,
    regionType: "complete",
    sequence: "ALA", // protein 서열
    sequenceKnown: true
  },
  {
    regionId: "chain_B_partial_25",
    chainId: "B",
    startResId: 25,
    endResId: 25,
    startAuthSeqId: 25,
    endAuthSeqId: 25,
    regionLength: 1,
    regionType: "partial",
    missingAtoms: ["N9", "C8", "N7", "..."], // adenine base atoms
    sequence: "DA", // DNA 핵산
    sequenceKnown: true
  }
];

// RepairSegment에서 타입별 처리
repairSegments.forEach(segment => {
  const hasProtein = segment.missingRegions.some(g =>
    g.sequence && ["ALA","GLY",...].includes(g.sequence)
  );
  const hasDNA = segment.missingRegions.some(g =>
    g.sequence && ["DA","DG","DC","DT"].includes(g.sequence)
  );
  const hasRNA = segment.missingRegions.some(g =>
    g.sequence && ["A","G","C","U"].includes(g.sequence) &&
    !["DA","DG","DC","DT"].includes(g.sequence)
  );

  // Mixed 타입에 대한 특별한 처리...
});
```

---

## 향후 개선 사항

1. **Modified Nucleotides 지원**
   - `DUR` (2'-Deoxy uridine)
   - `5MU` (5-Methyluracil)
   - 기타 Chemical Modifications

2. **Base Pairing 분석**
   - DNA double helix의 양 strand 모두에서 동일 위치 missing region 감지
   - RNA의 secondary structure 기반 missing region 중요도 판정

3. **Flexibility 분석**
   - High B-factor 영역에서의 선택적 missing region 처리
   - Mobile loop vs true missing residue 구분

4. **Structure Validation**
   - Backbone geometry 확인 (bond lengths, angles)
   - Van der Waals clash detection

---

## 참고 문헌

- PDB File Format Specification v3.3.0
- International Union of Crystallography (IUCr) Crystallographic Information Framework
- RNA/DNA Backbone Geometry: Saenger, W. (1984). "Principles of Nucleic Acid Structure"
- Nucleotide Nomenclature: IUPAC-IUBMB Joint Commission on Biochemical Nomenclature

---

## 코드 위치

**파일**: `src/renderer/src/components/mol-viewer/useMissingRegionDetection.ts`

**주요 함수**:

- `getResidueType()` - Line ~280
- `getResidueTypeFromAtoms()` - Line ~333
- `threeToOne()` - Line ~383
- Missing region detection loop - Line ~890+

**상수 정의**:

- `NUCLEOTIDE_BACKBONE_ATOMS` - Line ~25
- `DNA_NUCLEOTIDES` - Line ~100
- `RNA_NUCLEOTIDES` - Line ~108
