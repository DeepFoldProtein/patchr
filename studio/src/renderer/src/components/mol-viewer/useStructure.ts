// useStructure - 구조 로드 및 관리 (Mol* 공식 Builder API)
import { useState, useCallback, useEffect } from "react";
import { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import type { StructureInfo } from "../../types/mol-viewer";
import { bus } from "../../lib/event-bus";
import { StateTransforms } from "molstar/lib/mol-plugin-state/transforms";
import { logger } from "../../lib/logger";

/**
 * Wait for representations to be created after preset is applied
 */
async function waitForRepresentations(
  plugin: PluginUIContext,
  maxAttempts: number = 50
): Promise<boolean> {
  const state = plugin.state.data;
  const cells = state.cells;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    // Check if any representations exist
    let foundRepresentations = false;

    for (const [_ref, cell] of cells.entries()) {
      if (
        cell.transform.transformer ===
        StateTransforms.Representation.StructureRepresentation3D
      ) {
        foundRepresentations = true;
        break;
      }
    }

    if (foundRepresentations) {
      logger.log(`✓ Representations ready after ${attempt} attempt(s)`);
      return true;
    }

    // Use requestAnimationFrame for non-blocking delay instead of setTimeout
    await new Promise(resolve => requestAnimationFrame(resolve));
  }

  logger.warn(
    `⚠️ Timeout waiting for representations after ${maxAttempts} attempts`
  );
  return false;
}

/**
 * Filter out water residues (HOH, WAT, SOL, H2O) from structure data
 */
function filterWaterResidues(
  dataString: string,
  format: "pdb" | "mmcif" | "bcif"
): string {
  if (format === "pdb") {
    // Filter PDB format: remove ATOM/HETATM lines where residue name is water
    const waterResidues = ["HOH", "WAT", "SOL", "H2O"];
    const lines = dataString.split("\n");
    const filteredLines = lines.filter(line => {
      if (line.startsWith("ATOM") || line.startsWith("HETATM")) {
        // PDB format: columns 17-20 contain residue name
        const resName = line.substring(17, 20).trim();
        return !waterResidues.includes(resName);
      }
      return true;
    });
    return filteredLines.join("\n");
  } else if (format === "mmcif") {
    // Filter mmCIF format: remove lines for water residues
    const lines = dataString.split("\n");
    let inAtomSite = false;
    const waterResidues = ["HOH", "WAT", "SOL", "H2O"];
    const filteredLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith("loop_")) {
        inAtomSite = false;
        filteredLines.push(line);
      } else if (line.startsWith("_atom_site")) {
        inAtomSite = true;
        filteredLines.push(line);
      } else if (inAtomSite && !line.startsWith("_") && line.trim()) {
        // Check if this is a water residue line
        const parts = line.split(/\s+/);
        // In mmCIF, residue name is typically in the format entries
        // We'll be conservative and keep most lines, filtering only obvious water entries
        let isWater = false;
        for (const part of parts) {
          if (waterResidues.includes(part.toUpperCase())) {
            isWater = true;
            break;
          }
        }
        if (!isWater) {
          filteredLines.push(line);
        }
      } else {
        filteredLines.push(line);
      }
    }

    return filteredLines.join("\n");
  }

  // For bcif or unknown, return as-is
  return dataString;
}

export function useStructure(
  plugin: PluginUIContext | null,
  initialData?: ArrayBuffer | string
): {
  structure: unknown;
  info: StructureInfo | null;
  loading: boolean;
  error: string | null;
  loadStructure: (data: ArrayBuffer | string) => Promise<void>;
} {
  const [structure, setStructure] = useState<unknown>(null);
  const [info, setInfo] = useState<StructureInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const detectFormat = (
    data: ArrayBuffer | string
  ): "pdb" | "mmcif" | "bcif" => {
    if (data instanceof ArrayBuffer) {
      const view = new Uint8Array(data);
      // Check for BCIF magic bytes
      if (
        view[0] === 0x42 &&
        view[1] === 0x43 &&
        view[2] === 0x49 &&
        view[3] === 0x46
      ) {
        return "bcif";
      }
      return "mmcif";
    }

    const text = data as string;
    const trimmed = text.trim();

    // CIF/mmCIF starts with 'data_' or has '_' prefixed fields
    if (
      trimmed.startsWith("data_") ||
      trimmed.includes("\n_") ||
      trimmed.startsWith("_")
    ) {
      return "mmcif";
    }

    // PDB format indicators
    if (
      trimmed.startsWith("HEADER") ||
      trimmed.startsWith("ATOM") ||
      trimmed.startsWith("HETATM")
    ) {
      return "pdb";
    }

    // Default to mmcif for unknown
    return "mmcif";
  };

  const loadStructure = useCallback(
    async (data: ArrayBuffer | string) => {
      if (!plugin) return;

      setLoading(true);
      setError(null);

      try {
        // 1. 포맷 감지
        const format = detectFormat(data);
        let dataString =
          data instanceof ArrayBuffer ? new TextDecoder().decode(data) : data;

        logger.log("📥 Loading structure...", {
          format,
          dataLength: dataString.length
        });

        // 2. 물 분자(HOH, WAT, SOL, H2O) 필터링
        logger.log("Filtering out water molecules...");
        dataString = filterWaterResidues(dataString, format);

        // Clear existing structures
        await plugin.clear();

        // 3. 공식 builder API 사용 (download와 동일한 패턴)
        const formatType = format === "pdb" ? "pdb" : "mmcif";

        logger.log("Creating rawData node with format:", formatType);

        // rawData로 Data.String/Binary 노드 생성
        const dataNode = await plugin.builders.data.rawData({
          data: dataString,
          label: `Structure.${format}`
        });

        logger.log("✓ Data node created:", {
          ref: dataNode.ref,
          cell: dataNode.cell,
          obj: dataNode.cell?.obj
        });

        // parseTrajectory로 파싱
        logger.log("Calling parseTrajectory with:", formatType);
        const trajectory = await plugin.builders.structure.parseTrajectory(
          dataNode,
          formatType
        );

        logger.log("✓ Trajectory parsed:", {
          ref: trajectory.ref,
          cell: trajectory.cell,
          frameCount: trajectory.cell?.obj?.data?.frameCount
        });

        // Apply preset (자동으로 모든 설정 적용)
        logger.log("Applying preset...");
        await plugin.builders.structure.hierarchy.applyPreset(
          trajectory,
          "default"
        );

        logger.log("✓ Preset applied");

        // Wait for representations to be created
        await waitForRepresentations(plugin);
        logger.log("✓ Representations ready");

        // Emit event that representations are ready for coloring
        bus.emit("structure:representations-ready", { isBaseStructure: true });

        // Camera focus
        if (plugin.canvas3d) {
          await plugin.canvas3d.requestCameraReset({ durationMs: 300 });
          logger.log("✓ Camera reset");
        }

        const structInfo: StructureInfo = {
          title: "Structure",
          chainIds: [],
          residueCount: 0,
          atomCount: 0,
          format
        };

        setStructure(trajectory);
        setInfo(structInfo);

        // 이벤트 발행
        bus.emit("structure:loaded", structInfo);

        logger.log(`✅ Structure loaded and rendered (${format})`);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        setError(msg);
        logger.error("Structure load error:", err);
      } finally {
        setLoading(false);
      }
    },
    [plugin]
  );

  useEffect(() => {
    if (initialData) {
      loadStructure(initialData);
    }
  }, [initialData, loadStructure]);

  return { structure, info, loading, error, loadStructure };
}
