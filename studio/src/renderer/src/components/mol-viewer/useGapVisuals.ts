// useMissingRegionVisuals.ts - Gap 시각화 (Sequence selection + Measurement)
import { useEffect } from "react";
import { useAtom } from "jotai";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { missingRegionsDetectedAtom } from "../../store/repair-atoms";
import type { MissingRegionInfo } from "../../types";
import { bus } from "../../lib/event-bus";
import {
  Structure,
  StructureElement,
  Unit
} from "molstar/lib/mol-model/structure";
import { StructureProperties } from "molstar/lib/mol-model/structure/structure/properties";
import { Vec3 } from "molstar/lib/mol-math/linear-algebra";
import { OrderedSet } from "molstar/lib/mol-data/int";
import { Loci } from "molstar/lib/mol-model/loci";
import { StateTransforms } from "molstar/lib/mol-plugin-state/transforms";

// Gap boundary representation을 추적하기 위한 label prefix
const GAP_BOUNDARY_LABEL_PREFIX = "Missing Region Boundary";

// 이전 gap boundary representations를 정리하고 selection도 초기화
async function clearPreviousMissingRegionBoundaries(
  plugin: PluginUIContext
): Promise<void> {
  try {
    console.log(
      "[Gap Visuals DEBUG] clearPreviousMissingRegionBoundaries called"
    );

    // Selection 상태 로깅
    const selectionEntries = Array.from(
      plugin.managers.structure.selection.entries.entries()
    );
    console.log(
      "[Gap Visuals DEBUG] Current selection entries:",
      selectionEntries.length
    );
    selectionEntries.forEach(([ref, entry]) => {
      console.log(
        `  - ${ref}: ${entry.selection.elements.length} elements selected`
      );
    });

    // Selection 명시적으로 clear
    const clearedSelections = await plugin.managers.structure.selection.clear();
    console.log(
      "[Gap Visuals DEBUG] Cleared selections:",
      clearedSelections.length
    );

    // Gap boundary representations만 제거
    const state = plugin.state.data;
    const cells = state.cells;
    const toDelete: string[] = [];

    cells.forEach((cell, ref) => {
      if (cell.obj?.label?.startsWith(GAP_BOUNDARY_LABEL_PREFIX)) {
        console.log(
          `[Gap Visuals DEBUG] Found gap boundary to delete: ${cell.obj.label}`
        );
        toDelete.push(ref);
      }
    });

    if (toDelete.length > 0) {
      const update = state.build();
      for (const ref of toDelete) {
        update.delete(ref);
      }
      await update.commit();
      console.log(
        `[Missing Region Visuals] Cleared ${toDelete.length} previous boundary representations`
      );
    } else {
      console.log(
        "[Gap Visuals DEBUG] No previous boundary representations to clear"
      );
    }
  } catch (error) {
    console.error(
      "[Missing Region Visuals] Failed to clear previous boundaries:",
      error
    );
  }
}

/**
 * Gap 시각화 hook
 * - Partial residues: Sequence panel에서 선택 → 자동 zoom + sidechain 표시
 * - Complete gaps: Molstar measurement API로 distance line 표시
 * - Gap 클릭 시 해당 위치로 포커스
 */
export function useMissingRegionVisuals(
  plugin: PluginUIContext | null,
  enabled: boolean = true
): void {
  const [gaps] = useAtom(missingRegionsDetectedAtom);

  useEffect(() => {
    if (!plugin || !enabled || gaps.length === 0) return;

    const applyGapVisuals = async (): Promise<void> => {
      try {
        console.log(
          "[Missing Region Visuals] Applying visualization for",
          gaps.length,
          "gaps"
        );

        const structures =
          plugin.managers.structure.hierarchy.current.structures;
        if (!structures || structures.length === 0) return;

        const structure = structures[0].cell.obj?.data as Structure | undefined;
        if (!structure) return;

        // Partial residues에 대해 text label 추가
        await visualizePartialResidues(plugin, structure, gaps);

        // Complete gaps에 대해 measurement distance lines 생성
        await visualizeCompleteGaps(plugin, structure, gaps);

        console.log(
          "[Missing Region Visuals] Visualization applied successfully"
        );
      } catch (error) {
        console.error("[Missing Region Visuals] Error:", error);
      }
    };

    void applyGapVisuals();

    // Selection 변경 이벤트 모니터링
    const selectionChangeHandler =
      plugin.managers.structure.selection.events.changed.subscribe(() => {
        const entries = Array.from(
          plugin.managers.structure.selection.entries.entries()
        );
        console.log("[Gap Visuals DEBUG] Selection changed event:", {
          entryCount: entries.length,
          entries: entries.map(([ref, entry]) => ({
            ref,
            elementCount: entry.selection.elements.length
          }))
        });
      });

    // User interaction 모니터링 및 빈 공간 클릭 시 selection 해제
    const clickHandler = plugin.behaviors.interaction.click.subscribe(
      ({ current, button, modifiers }) => {
        console.log("[Gap Visuals DEBUG] User click event:", {
          lociKind: current.loci.kind,
          isEmpty: current.loci.kind === "empty-loci",
          button,
          modifiers
        });

        // 빈 공간 클릭 시 selection 및 gap boundary representations 해제
        if (current.loci.kind === "empty-loci") {
          console.log(
            "[Gap Visuals DEBUG] Empty loci clicked - clearing selection and gap boundaries"
          );
          plugin.managers.interactivity.lociSelects.deselectAll();

          // Gap boundary representations도 정리
          const state = plugin.state.data;
          const toDelete: string[] = [];
          state.cells.forEach((cell, ref) => {
            if (cell.obj?.label?.startsWith(GAP_BOUNDARY_LABEL_PREFIX)) {
              toDelete.push(ref);
            }
          });

          if (toDelete.length > 0) {
            const update = state.build();
            for (const ref of toDelete) {
              update.delete(ref);
            }
            update.commit().then(() => {
              console.log(
                `[Gap Visuals DEBUG] Cleared ${toDelete.length} gap boundary representations on empty click`
              );
            });
          }
        }
      }
    );

    // Gap 클릭 이벤트 리스너
    const handleGapClick = (regionId: string): void => {
      console.log(`[Gap Visuals DEBUG] Gap click event received: ${regionId}`);
      const gap = gaps.find(g => g.regionId === regionId);
      if (gap && plugin) {
        if (gap.regionType === "partial") {
          // Partial: Sequence panel에서 선택
          void selectPartialResidue(plugin, gap);
        } else {
          // Complete: 카메라 포커스
          void focusOnGap(plugin, gap);
        }
      }
    };

    bus.on("missing-region:focus", handleGapClick);

    return () => {
      bus.off("missing-region:focus", handleGapClick);
      selectionChangeHandler.unsubscribe();
      clickHandler.unsubscribe();
    };
  }, [plugin, enabled, gaps]);
}

/**
 * Partial residue를 sequence panel에서 선택
 * Molstar가 자동으로 zoom하고 sidechain을 표시함
 */
async function selectPartialResidue(
  plugin: PluginUIContext,
  missingRegion: MissingRegionInfo
): Promise<void> {
  try {
    console.log(
      `[Missing Region Visuals] === Selecting partial residue ${missingRegion.regionId} ===`
    );

    // 이전 gap boundary representations 정리
    await clearPreviousMissingRegionBoundaries(plugin);

    const structures = plugin.managers.structure.hierarchy.current.structures;
    if (!structures || structures.length === 0) return;

    const structure = structures[0].cell.obj?.data as Structure | undefined;
    if (!structure) return;

    // Residue loci 생성
    const loci = findResidueLoci(
      structure,
      missingRegion.chainId,
      missingRegion.startAuthSeqId!,
      missingRegion.insertionCode
    );

    if (!loci) {
      console.warn(
        `[Missing Region Visuals] Could not find residue for ${missingRegion.regionId}`
      );
      return;
    }

    console.log(`[Gap Visuals DEBUG] Found loci:`, {
      structure: loci.structure.label,
      elements: loci.elements.length,
      isEmpty: StructureElement.Loci.isEmpty(loci)
    });

    // Molstar interactivity manager를 통한 selection (이렇게 하면 자동으로 관리됨)
    console.log(`[Gap Visuals DEBUG] Calling selectOnly...`);
    plugin.managers.interactivity.lociSelects.selectOnly({ loci }, false);

    // Selection이 실제로 적용되었는지 확인 (즉시 확인)
    const selectionEntries = Array.from(
      plugin.managers.structure.selection.entries.entries()
    );
    console.log(
      "[Gap Visuals DEBUG] After selectOnly - selection entries:",
      selectionEntries.length
    );
    selectionEntries.forEach(([ref, entry]) => {
      console.log(`  - ${ref}: ${entry.selection.elements.length} elements`);
    });

    // Ball-and-stick representation 추가 (sidechain 표시)
    await addBallAndStickForSelection(plugin, loci, "Partial");

    // Focus on the residue
    const bounds = Loci.getBoundingSphere(loci);
    if (bounds) {
      console.log(`[Gap Visuals DEBUG] Focusing camera on bounds:`, bounds);
      plugin.canvas3d?.camera.focus(bounds.center, 8, 500);
    }

    console.log(
      `[Missing Region Visuals] ✓ Selected residue ${missingRegion.regionId} with sidechain`
    );
  } catch (error) {
    console.error(
      `[Missing Region Visuals] Failed to select residue ${missingRegion.regionId}:`,
      error
    );
  }
}

/**
 * Structure에서 residue의 loci 찾기
 */
function findResidueLoci(
  structure: Structure,
  chainId: string,
  authSeqId: number,
  insCode: string | undefined
): StructureElement.Loci | null {
  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;

    const elements: StructureElement.UnitIndex[] = [];

    for (let i = 0; i < unit.elements.length; i++) {
      const loc = StructureElement.Location.create(
        structure,
        unit,
        unit.elements[i]
      );
      const elemChainId = StructureProperties.chain.auth_asym_id(loc);
      const elemAuthSeqId = StructureProperties.residue.auth_seq_id(loc);
      const elemInsCode =
        StructureProperties.residue.pdbx_PDB_ins_code(loc) || "";

      if (
        elemChainId === chainId &&
        elemAuthSeqId === authSeqId &&
        elemInsCode === (insCode || "")
      ) {
        elements.push(i as StructureElement.UnitIndex);
      }
    }

    if (elements.length > 0) {
      return StructureElement.Loci(structure, [
        { unit, indices: OrderedSet.ofSortedArray(elements) }
      ]);
    }
  }

  return null;
}

/**
 * Structure에서 label_seq_id로 residue의 loci 찾기
 */
function findResidueLociByLabelSeqId(
  structure: Structure,
  chainId: string,
  labelSeqId: number
): StructureElement.Loci | null {
  for (const unit of structure.units) {
    if (!Unit.isAtomic(unit)) continue;

    const elements: StructureElement.UnitIndex[] = [];

    for (let i = 0; i < unit.elements.length; i++) {
      const loc = StructureElement.Location.create(
        structure,
        unit,
        unit.elements[i]
      );
      const elemChainId = StructureProperties.chain.auth_asym_id(loc);
      const elemLabelSeqId = StructureProperties.residue.label_seq_id(loc);

      if (elemChainId === chainId && elemLabelSeqId === labelSeqId) {
        elements.push(i as StructureElement.UnitIndex);
      }
    }

    if (elements.length > 0) {
      return StructureElement.Loci(structure, [
        { unit, indices: OrderedSet.ofSortedArray(elements) }
      ]);
    }
  }

  return null;
}

/**
 * 선택된 residue에 ball-and-stick representation 추가 (sidechain 표시)
 */
async function addBallAndStickForSelection(
  plugin: PluginUIContext,
  loci: StructureElement.Loci,
  tag: string
): Promise<void> {
  try {
    const structure = loci.structure;
    const parent = plugin.helpers.substructureParent.get(structure);
    if (!parent) return;

    const update = plugin.state.data.build();

    // Selection을 위한 transform 생성
    const selection = update
      .to(parent.transform.ref)
      .apply(StateTransforms.Model.StructureSelectionFromBundle, {
        bundle: StructureElement.Bundle.fromLoci(loci),
        label: `Missing Region Boundary ${tag}`
      });

    // Ball-and-stick representation 추가
    selection.apply(StateTransforms.Representation.StructureRepresentation3D, {
      type: { name: "ball-and-stick", params: {} },
      colorTheme: { name: "element-symbol", params: {} },
      sizeTheme: { name: "physical", params: {} }
    });

    await update.commit();

    console.log(
      `[Missing Region Visuals] Added ball-and-stick representation for ${tag}`
    );
  } catch (error) {
    console.error(
      `[Missing Region Visuals] Failed to add representation for ${tag}:`,
      error
    );
  }
}

/**
 * Partial residues에 대해 text label 추가 (MolStar measurement API 사용)
 * 각 partial residue 위에 "N missing atoms" 텍스트 라벨 표시
 */
async function visualizePartialResidues(
  plugin: PluginUIContext,
  structure: Structure,
  gaps: MissingRegionInfo[]
): Promise<void> {
  const partialGaps = gaps.filter(g => g.regionType === "partial");
  if (partialGaps.length === 0) return;

  console.log(
    "[Missing Region Visuals] Adding text labels for",
    partialGaps.length,
    "partial residues"
  );

  for (const gap of partialGaps) {
    try {
      // Partial residue의 loci 찾기
      const loci = findResidueLoci(
        structure,
        gap.chainId,
        gap.startAuthSeqId!,
        gap.insertionCode
      );

      if (!loci) {
        console.warn(
          `[Missing Region Visuals] Could not find residue for partial ${gap.regionId}`
        );
        continue;
      }

      // 누락된 원자 개수 계산
      const missingAtomCount = gap.missingAtoms?.length ?? 0;
      const residueName = gap.sequence || "UNK";

      // 텍스트 라벨 생성: "Residue XYZ: 5 atoms missing"
      const labelText = `${residueName}${gap.startAuthSeqId}${gap.insertionCode || ""}: ${missingAtomCount} atom(s) missing`;

      // Distance API를 사용하여 custom text 표시
      // 같은 residue를 양 끝점으로 사용하면 선 없이 텍스트만 표시됨
      await plugin.managers.structure.measurement.addDistance(loci, loci, {
        customText: labelText,
        visualParams: {
          textSize: 0.8 // 텍스트 크기 조정
        }
      });

      console.log(
        `[Missing Region Visuals] ✓ Added label for partial residue ${gap.regionId}: "${labelText}"`
      );
    } catch (error) {
      console.error(
        `[Missing Region Visuals] Failed to create label for ${gap.regionId}:`,
        error
      );
    }
  }
}

/**
 * Complete gaps에 distance line 그리기 (Molstar measurement API 사용)
 * Terminal gaps (N/C-term)은 텍스트만 표시, internal gaps는 distance line 표시
 */
async function visualizeCompleteGaps(
  plugin: PluginUIContext,
  structure: Structure,
  gaps: MissingRegionInfo[]
): Promise<void> {
  const completeGaps = gaps.filter(g => g.regionType === "complete");
  if (completeGaps.length === 0) return;

  console.log(
    "[Missing Region Visuals] Drawing distance lines for",
    completeGaps.length,
    "complete gaps"
  );

  for (const gap of completeGaps) {
    try {
      // Terminal gaps는 텍스트 라벨 표시
      if (gap.terminalType === "nterm" || gap.terminalType === "cterm") {
        // Terminal gap의 경계 residue 찾기
        const boundaryLoci =
          gap.terminalType === "nterm"
            ? findResidueLociByLabelSeqId(
                structure,
                gap.chainId,
                gap.endResId + 1
              )
            : findResidueLociByLabelSeqId(
                structure,
                gap.chainId,
                gap.startResId - 1
              );

        if (boundaryLoci) {
          // Distance API를 사용하여 custom text 표시
          // 같은 residue를 양 끝점으로 사용하면 선 없이 텍스트만 표시됨
          const labelText =
            gap.terminalType === "nterm"
              ? `N-term: ${gap.regionLength} missing residues`
              : `C-term: ${gap.regionLength} missing residues`;

          await plugin.managers.structure.measurement.addDistance(
            boundaryLoci,
            boundaryLoci,
            {
              customText: labelText,
              visualParams: {
                textSize: 0.8 // 기본값보다 크게
              }
            }
          );

          console.log(
            `[Missing Region Visuals] ✓ Added label for ${gap.terminalType} gap ${gap.regionId}: "${labelText}"`
          );
        } else {
          console.warn(
            `[Missing Region Visuals] Could not find boundary residue for ${gap.terminalType} gap ${gap.regionId}`
          );
        }
        continue;
      }

      // Internal gaps: distance line 표시
      // Gap 경계 residue의 loci 찾기
      const startLoci = findNearbyResidueLoci(
        structure,
        gap.chainId,
        gap.startAuthSeqId!,
        gap.insertionCode,
        "before"
      );

      const endLoci = findNearbyResidueLoci(
        structure,
        gap.chainId,
        gap.endAuthSeqId!,
        gap.endInsertionCode,
        "after"
      );

      if (!startLoci || !endLoci) {
        console.warn(
          `[Missing Region Visuals] Could not find loci for gap ${gap.regionId}`
        );
        continue;
      }

      // Molstar measurement API를 사용하여 distance 추가
      await plugin.managers.structure.measurement.addDistance(
        startLoci,
        endLoci,
        {
          customText: `Gap: ${gap.regionLength} residues`,
          visualParams: {
            textSize: 0.8 // 텍스트 크기 조정
          }
        }
      );

      console.log(
        `[Missing Region Visuals] ✓ Distance line for ${gap.regionId} (${gap.regionLength} residues)`
      );
    } catch (error) {
      console.error(
        `[Missing Region Visuals] Failed to create distance line for ${gap.regionId}:`,
        error
      );
    }
  }
}

/**
 * Residue loci 찾기 (없으면 주변 residue 검색)
 */
function findNearbyResidueLoci(
  structure: Structure,
  chainId: string,
  seqId: number,
  insCode: string | undefined,
  direction: "before" | "after"
): StructureElement.Loci | null {
  // 먼저 정확한 위치 시도
  let loci = findResidueLoci(structure, chainId, seqId, insCode);
  if (loci) return loci;

  // 없으면 주변 검색
  const searchDirection = direction === "before" ? -1 : 1;

  for (let offset = 1; offset <= 5; offset++) {
    const nearbySeqId = seqId + searchDirection * offset;

    // Insertion code 없이 시도
    loci = findResidueLoci(structure, chainId, nearbySeqId, undefined);
    if (loci) {
      console.log(
        `  Found nearby residue at ${nearbySeqId} (offset=${searchDirection * offset})`
      );
      return loci;
    }

    // 일반적인 insertion code들 시도
    for (const tryInsCode of ["A", "B", "C", "D", "E"]) {
      loci = findResidueLoci(structure, chainId, nearbySeqId, tryInsCode);
      if (loci) {
        console.log(
          `  Found nearby residue at ${nearbySeqId}${tryInsCode} (offset=${searchDirection * offset})`
        );
        return loci;
      }
    }
  }

  console.warn(`  Could not find any residue near ${seqId}${insCode || ""}`);
  return null;
}

/**
 * Gap 위치로 카메라 포커스
 * Complete missing-region:
 *   - Terminal gaps (N/C-term): 한쪽 경계 residue만 선택 + 텍스트 라벨
 *   - Internal gaps: 양쪽 경계 residue 선택 + sidechain/heavy atom 표시
 */
async function focusOnGap(
  plugin: PluginUIContext,
  missingRegion: MissingRegionInfo
): Promise<void> {
  try {
    console.log(
      `[Missing Region Visuals] Focusing on gap ${missingRegion.regionId}`
    );

    // 이전 gap boundary representations 정리
    await clearPreviousMissingRegionBoundaries(plugin);

    const structures = plugin.managers.structure.hierarchy.current.structures;
    if (!structures || structures.length === 0) return;

    const structure = structures[0].cell.obj?.data as Structure | undefined;
    if (!structure) return;

    if (missingRegion.regionType === "partial") {
      // Partial residue: 해당 residue 선택 및 ball-and-stick 표시
      const loci = findResidueLoci(
        structure,
        missingRegion.chainId,
        missingRegion.startAuthSeqId!,
        missingRegion.insertionCode
      );
      if (loci) {
        // Interactivity manager를 통한 selection
        plugin.managers.interactivity.lociSelects.selectOnly({ loci }, false);

        // Ball-and-stick representation 추가 (sidechain 표시)
        await addBallAndStickForSelection(plugin, loci, "Partial");

        // 해당 residue로 줌
        const bounds = Loci.getBoundingSphere(loci);
        if (bounds) {
          plugin.canvas3d?.camera.focus(bounds.center, 8, 500);
        }
      }
    } else {
      // Complete missing-region
      // Terminal gaps: 한쪽 경계만 선택
      if (
        missingRegion.terminalType === "nterm" ||
        missingRegion.terminalType === "cterm"
      ) {
        // N-term: 첫 번째 존재하는 residue만 선택
        // C-term: 마지막 존재하는 residue만 선택
        const isNterm = missingRegion.terminalType === "nterm";

        // Terminal gap의 경우, label_seq_id의 경계 residue를 찾음
        let targetLoci: StructureElement.Loci | null = null;

        if (isNterm) {
          // N-term: endResId 다음 residue (첫 번째 존재하는 residue)
          // label_seq_id 기준으로 찾기
          targetLoci = findResidueLociByLabelSeqId(
            structure,
            missingRegion.chainId,
            missingRegion.endResId + 1
          );
        } else {
          // C-term: startResId 이전 residue (마지막 존재하는 residue)
          targetLoci = findResidueLociByLabelSeqId(
            structure,
            missingRegion.chainId,
            missingRegion.startResId - 1
          );
        }

        if (targetLoci) {
          console.log(
            `[Gap Visuals DEBUG] ${missingRegion.terminalType} gap - selecting single boundary residue`
          );

          // 단일 residue 선택
          plugin.managers.interactivity.lociSelects.selectOnly(
            { loci: targetLoci },
            false
          );

          // Ball-and-stick representation 추가
          await addBallAndStickForSelection(
            plugin,
            targetLoci,
            missingRegion.terminalType === "nterm" ? "N-terminal" : "C-terminal"
          );

          // Focus
          const bounds = Loci.getBoundingSphere(targetLoci);
          if (bounds) {
            plugin.canvas3d?.camera.focus(bounds.center, 12, 500);
          }

          console.log(
            `[Missing Region Visuals] ✓ Focused on ${missingRegion.terminalType} gap with single residue (${missingRegion.regionLength} residues missing)`
          );
        } else {
          console.warn(
            `[Missing Region Visuals] Could not find boundary residue for ${missingRegion.terminalType} gap ${missingRegion.regionId}`
          );
        }
      } else {
        // Internal gaps: 양쪽 경계 residue 모두 선택
        const startLoci = findNearbyResidueLoci(
          structure,
          missingRegion.chainId,
          missingRegion.startAuthSeqId!,
          missingRegion.insertionCode,
          "before"
        );
        const endLoci = findNearbyResidueLoci(
          structure,
          missingRegion.chainId,
          missingRegion.endAuthSeqId!,
          missingRegion.endInsertionCode,
          "after"
        );

        if (startLoci && endLoci) {
          console.log(`[Gap Visuals DEBUG] Internal gap - found both loci`);

          // 양쪽 경계 residue 모두 선택 - selectOnly로 먼저 clear, 그 다음 select로 추가
          console.log(
            `[Gap Visuals DEBUG] Calling selectOnly for start loci...`
          );
          plugin.managers.interactivity.lociSelects.selectOnly(
            { loci: startLoci },
            false
          );

          console.log(`[Gap Visuals DEBUG] Calling select for end loci...`);
          plugin.managers.interactivity.lociSelects.select(
            { loci: endLoci },
            false
          );

          // Selection이 실제로 적용되었는지 확인 (즉시 확인)
          const selectionEntries = Array.from(
            plugin.managers.structure.selection.entries.entries()
          );
          console.log(
            "[Gap Visuals DEBUG] After complete gap selection - entries:",
            selectionEntries.length
          );
          selectionEntries.forEach(([ref, entry]) => {
            console.log(
              `  - ${ref}: ${entry.selection.elements.length} elements`
            );
          });

          // Ball-and-stick representation 추가 (sidechain + heavy atoms 표시)
          await addBallAndStickForSelection(plugin, startLoci, "Start");
          await addBallAndStickForSelection(plugin, endLoci, "End");

          // 두 residue의 중간점으로 카메라 포커스 (더 확대)
          const startBounds = Loci.getBoundingSphere(startLoci);
          const endBounds = Loci.getBoundingSphere(endLoci);

          if (startBounds && endBounds) {
            const centerCoord = Vec3.create(
              (startBounds.center[0] + endBounds.center[0]) / 2,
              (startBounds.center[1] + endBounds.center[1]) / 2,
              (startBounds.center[2] + endBounds.center[2]) / 2
            );

            // Gap 크기에 따라 적절한 확대 수준 (더 가까이)
            const distance = Vec3.distance(
              startBounds.center,
              endBounds.center
            );
            const radius = Math.max(8, distance * 0.8); // 이전보다 더 확대 (0.8배)

            plugin.canvas3d?.camera.focus(
              centerCoord,
              radius,
              500 // 0.5초 애니메이션
            );

            console.log(
              `[Missing Region Visuals] ✓ Focused on gap ${missingRegion.regionId} with boundary residues and sidechain displayed`
            );
          }
        } else {
          console.warn(
            `[Missing Region Visuals] Could not find boundary residues for gap ${missingRegion.regionId}`
          );
        }
      }
    }
  } catch (error) {
    console.error(
      `[Missing Region Visuals] Failed to focus on gap ${missingRegion.regionId}:`,
      error
    );
  }
}
