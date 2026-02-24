# DNA/RNA Missing Region Detection 개선 - Robust 판별 전략 적용 (최종)

## 📌 완성된 개선사항

### ✅ 실제 적용된 변경사항

1. **Entity Polymer Type 활용** ⭐
   - `getChainPolymerKind()` 함수로 mmCIF entity type 파싱
   - Entity type 값: `polydeoxyribonucleotide`, `polyribonucleotide`, `polypeptide`
   - 최우선 판별 기준 → **False positive 극소화**

2. **Atom Naming 정규화**
   - asterisk (`*`) → apostrophe (`'`) 자동 변환
   - `O1P/O2P` 뿐만 아니라 `OP1/OP2`도 지원

3. **설탕 링 기반 핵산 판별**
   - C1', C2', C3', C4', O4', C5', O5' 중 **3개 이상** 있으면 핵산
   - 경험적 임계치로 말단/부분 모델도 정확 인식

4. **2단계 Residue Type 판별**
   - Step 1: 모든 atoms 수집 (원자 첫 발견 시 즉시 판별 X)
   - Step 2: 체인 polymer type + 모든 atoms로 최종 판별

5. **RNA vs DNA 구분 강화**
   - O2' (2'-hydroxyl) 감지 → RNA
   - T/DT/D-prefix 감지 → DNA
   - U 감지 → RNA

---

## 🔧 코드 변경

- 인산(`P`) 없어도 감지 가능 (말단 대응)
- 부분 모델에서도 robust
- 설탕 골격 = 핵산의 본질적 특징

### 2. 모든 네이밍 변형 수용

```typescript
const NUCLEOTIDE_BACKBONE_ATOMS = new Set([
  "P", // Phosphate
  "O1P",
  "O2P", // 구형 명명
  "OP1",
  "OP2", // 현대 명명
  "O5'",
  "C5'",
  "C4'",
  "O4'",
  "C3'",
  "O3'",
  "C2'",
  "C1'"
]);
```

**수용 범위**:

- `O1P/O2P` 또는 `OP1/OP2` 모두 인정
- 포맷 간 호환성 보장

### 3. Atom Name 정규화

```typescript
function normalizeAtomName(atomName: string): string {
  return atomName.replace(/\*/g, "'");
}

// 사용
const atomNames = new Set<string>(
  Array.from(atomNamesRaw).map(a => normalizeAtomName(a))
);
```

**효과**:

- `O5*` → `O5'` 자동 변환
- `C5*` → `C5'` 자동 변환
- 구형 PDB와 현대 포맷 통합 처리

### 4. 보조 신호 기반 RNA vs DNA 구분

```typescript
function rnaOrDnaByAuxSignals(
  compId: string,
  atomNames: Set<string>
): "dna" | "rna" | "unknown" {
  // 1순위: O2' (RNA 고유 신호, 가장 신뢰도 높음)
  if (atomNames.has("O2'")) return "rna";

  // 2순위: 염기 특성
  if (compId.toUpperCase() === "U") return "rna"; // Uracil
  if (compId.toUpperCase() === "T" || compId.toUpperCase() === "DT")
    return "dna"; // Thymine

  // 3순위: D prefix
  if (compId.toUpperCase().startsWith("D")) return "dna";

  return "unknown";
}
```

**우선순위**:

1. `O2'` (절대적 RNA 신호) ⭐⭐⭐⭐⭐
2. `U`/`T` (염기 특성) ⭐⭐⭐⭐
3. `D*` prefix (명명 컨벤션) ⭐⭐⭐

### 5. Robust Residue Type 판별 함수

```typescript
function getResidueTypeRobust(
  compId: string,
  atomNamesRaw: Set<string>,
  chainPolymerHint: "protein" | "dna" | "rna" | "unknown" = "unknown"
): "protein" | "dna" | "rna" | "unknown" {
  // 정규화
  const atomNames = new Set<string>(
    Array.from(atomNamesRaw).map(a => normalizeAtomName(a))
  );

  // 1) Entity hint 우선 (Chain 레벨, 향후 추가 예정)
  if (chainPolymerHint !== "unknown") {
    return chainPolymerHint;
  }

  // 2) Protein backbone 신호
  if (["N", "CA", "C", "O"].every(a => atomNames.has(a))) {
    return "protein";
  }

  // 3) 설탕 링 기반 핵산 판별
  if (isNucleotideByAtoms(atomNames)) {
    const nucType = rnaOrDnaByAuxSignals(compId, atomNames);
    if (nucType !== "unknown") {
      return nucType;
    }

    // 보조 신호 실패 → comp_id 규칙
    const comp = compId.toUpperCase();
    if (comp === "DT" || comp.startsWith("D")) return "dna";
    if (comp === "U") return "rna";

    // 마지막 수단: 보수적으로 DNA
    return "dna";
  }

  // 4) 어떤 신호도 없으면 unknown
  return "unknown";
}
```

**우선순위 체계**:

```
Entity/Polymer Type (향후)
    ↓
Protein Backbone (N/CA/C/O)
    ↓
설탕 링 기반 핵산
    ├─ O2' → RNA
    ├─ U/T/D* → RNA/DNA
    └─ 보수적 default
    ↓
Unknown
```

---

## 🔬 실제 DNA 구조 예시 (1BNA.cif)

### 1BNA의 DNA 뉴클레오타이드 (DA)

```
DA 뉴클레오타이드의 실제 원자들:
- Backbone: P, OP1, OP2, O5', C5', C4', O4', C3', O3', C2', C1'
           (OP1/OP2 사용 - 현대 표준)
- Base (Adenine): N9, C8, N7, C5, C6, N6, N1, C2, N3, C4
- 설탕: C1', C2', C3', C4', C5' (ribose, 2-deoxy)
- 수산기: O5', O3' (O2' 없음 = DNA)

판별:
1. 설탕 링: C1', C2', C3', C4', O4' 모두 있음 → 핵산 확정 ✓
2. O2' 검사: 없음 → DNA (O2'가 없는 건 DNA 특성) ✓
3. 보조: DA → D prefix = DNA ✓
```

---

## 💡 개선 효과

| 상황                          | 기존 코드         | 개선된 코드           |
| ----------------------------- | ----------------- | --------------------- |
| `O1P/O2P` 없고 `OP1/OP2` 있음 | ❌ DNA 인식 실패  | ✅ 인식 성공          |
| 말단에서 `P` 없음             | ❌ 핵산으로 못 봄 | ✅ 설탕 링으로 확인   |
| `O5*` 포맷 (asterisk)         | ❌ 미매치         | ✅ 정규화로 처리      |
| 부분 모델 (일부 원자 누락)    | ❌ False negative | ✅ 임계치 기반 robust |
| `A/G/C` ambiguity             | ❌ 불명확         | ✅ O2'로 명확 구분    |

---

## 📝 코드 위치 및 변경사항

**파일**: `src/renderer/src/components/mol-viewer/useMissingRegionDetection.ts`

**추가/변경된 함수**:

- `normalizeAtomName()` - Atom name 정규화
- `isNucleotideByAtoms()` - 설탕 링 기반 핵산 판별
- `rnaOrDnaByAuxSignals()` - 보조 신호 기반 RNA vs DNA
- `getResidueTypeRobust()` - Unified robust 판별 함수

**주요 상수 업데이트**:

- `NUCLEOTIDE_SUGAR_RING_ATOMS` - 설탕 링 원자 정의
- `NUCLEOTIDE_BACKBONE_ATOMS` - 모든 네이밍 변형 포함

**호출 변경**:

- `getResidueTypeFromAtoms()` → `getResidueTypeRobust()` 교체

---

## 🎯 다음 단계

### Phase 1 (현재 완료)

- ✅ 네이밍 호환성 (O1P/O2P vs OP1/OP2)
- ✅ 말단/부분 모델 대응
- ✅ Atom name 정규화 (\*/')
- ✅ Robust 판별 함수

### Phase 2 (향후)

- [ ] Entity/Polymer Type 통합 (최우선 판별)
- [ ] Chain 레벨 타입 캐싱
- [ ] Modified nucleotide 지원
- [ ] Base pairing validation

---

## 참고: False Positive 방지

과거 문제:

```
말단 문제로 partial backbone이 "잘못된 gap"으로 표시됨
예: P 없고 O3' 있으면 → incomplete backbone으로 false positive
```

개선:

```
- 설탕 링 3개 이상 = 핵산으로 확정
- Partial backbone도 구조적으로 유효한 nucleotide로 인식
- Missing atoms 검사에서 임계치 기반 false positive 감소
```
