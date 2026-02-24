// @refresh reset
import React, { useEffect, useState } from "react";
import { useSetAtom } from "jotai";
import { usePluginContext } from "./mol-viewer/usePluginContext";
import { useStructure } from "./mol-viewer/useStructure";
import { useMissingRegionDetection } from "./mol-viewer/useGapDetection";
import { useMissingRegionVisuals } from "./mol-viewer/useGapVisuals";
import { useSequenceViewer } from "./mol-viewer/useSequenceViewer";
import { useHideWater } from "./mol-viewer/useHideWater";
import { useAutoYAMLGeneration } from "./mol-viewer/useAutoYAMLGeneration";
import { useCanonicalMapping } from "./mol-viewer/useCanonicalMapping";
import { useSuperpose } from "./mol-viewer/useSuperpose";
import { useChainColors } from "./mol-viewer/useChainColors";
import { ErrorBoundary } from "./ErrorBoundary";
import { useCurrentProject, useStructureContent } from "../store/project-store";
import { pluginAtom } from "../store/mol-viewer-atoms";

export interface MolViewerPanelProps {
  projectId?: string;
  initialStructure?: ArrayBuffer | string;
}

function MolViewerPanelInner({
  initialStructure
}: MolViewerPanelProps): React.ReactElement {
  const { plugin, containerRef, error: pluginError } = usePluginContext();
  const setGlobalPlugin = useSetAtom(pluginAtom);
  const currentProject = useCurrentProject();
  const structureContent = useStructureContent();

  // Use structure from store (set by StructureUploadModal) or initial prop
  const structureData = structureContent || initialStructure;

  // Store plugin in global atom so other components can access it
  useEffect(() => {
    setGlobalPlugin(plugin);
    return () => {
      setGlobalPlugin(null);
    };
  }, [plugin, setGlobalPlugin]);

  const { loading, error: structureError } = useStructure(
    plugin,
    structureData
  );

  // Missing Region Detection 자동 실행
  useMissingRegionDetection(plugin, !loading && !!structureData);

  // Missing Region Visualization (distance lines & colors)
  useMissingRegionVisuals(plugin, !loading && !!structureData);

  // Hide water molecules by default
  useHideWater(plugin, !loading && !!structureData);

  // Apply chain colors (contrasting with inpainting colors)
  useChainColors(plugin, !loading && !!structureData);

  // Auto-generate YAML after missing region detection
  useAutoYAMLGeneration(!!currentProject);

  // Generate mapping after missing region detection
  useCanonicalMapping(plugin, !!currentProject && !loading && !!structureData);

  // Handle inpainting result loading and superposition
  useSuperpose(plugin);

  // Render sequence viewer in separate container
  useSequenceViewer(plugin, "sequence-panel-container");

  const error = pluginError || structureError;

  return (
    <div className="flex h-full flex-col bg-slate-950">
      {error && (
        <div className="bg-red-900/50 text-red-100 p-2 text-sm border-b border-red-800">
          ⚠️ {error}
        </div>
      )}

      {/* Sequence panel container - 별도 영역에 표시 */}
      <div
        id="sequence-panel-container"
        className="bg-slate-900 border-b border-slate-700"
        style={{ minHeight: "100px", maxHeight: "150px", overflow: "auto" }}
      />

      {/* Mol* container - 3D viewer only */}
      <div
        ref={containerRef}
        className="flex-1 relative overflow-hidden"
        style={{ isolation: "isolate" }}
        suppressHydrationWarning
      >
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-sm z-10 pointer-events-none">
            <div className="text-white text-center">
              <div className="mb-2 animate-spin rounded-full h-8 w-8 border-b-2 border-white mx-auto"></div>
              <p className="text-sm">Loading structure...</p>
            </div>
          </div>
        )}

        {!plugin && !loading && !error && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center text-muted-foreground">
              <h2 className="mb-2 text-lg font-semibold">Mol* Viewer</h2>
              <p className="text-sm">Initializing molecular viewer...</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function MolViewerPanel(props: MolViewerPanelProps): React.ReactElement {
  // Use a stable key to prevent unnecessary remounts but allow recovery
  const [key, setKey] = useState(0);

  return (
    <ErrorBoundary
      key={key}
      fallback={
        <div className="flex h-full items-center justify-center bg-slate-950">
          <div className="max-w-md rounded-lg border border-red-900/50 bg-red-950/20 p-6 text-center">
            <div className="mb-4 text-4xl">⚠️</div>
            <h2 className="mb-2 text-lg font-semibold text-red-400">
              Viewer Error
            </h2>
            <p className="mb-4 text-sm text-slate-400">
              Failed to initialize the molecular viewer. Please try reloading
              the application.
            </p>
            <button
              onClick={() => setKey(k => k + 1)}
              className="mr-2 rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-slate-600 transition-colors"
            >
              Retry
            </button>
            <button
              onClick={() => window.location.reload()}
              className="rounded-md bg-red-900/50 px-4 py-2 text-sm font-medium text-red-100 hover:bg-red-900/70 transition-colors"
            >
              Reload App
            </button>
          </div>
        </div>
      }
    >
      <MolViewerPanelInner key={key} {...props} />
    </ErrorBoundary>
  );
}
