import React, { useEffect, useCallback, useRef } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useSetAtom } from "jotai";
import { Toolbar } from "./Toolbar";
import { StatusBar } from "./StatusBar";
import { MolViewerPanel } from "./MolViewerPanel";
import { ControlPanel } from "./ControlPanel";
import { ProjectWelcome } from "./ProjectWelcome";
import { StructureUploadModal } from "./StructureUploadModal";
import {
  useCurrentProject,
  useProjectStore,
  useHasStructure
} from "../store/project-store";
import { useProject } from "../hooks/useProject";
import { resetRepairStateAtom } from "../store/repair-atoms";

export function AppLayout(): React.ReactElement {
  const currentProject = useCurrentProject();
  const hasStructure = useHasStructure();
  const { getCurrentProject, closeProject } = useProject();
  const setCurrentProject = useProjectStore(state => state.setCurrentProject);
  const clearProject = useProjectStore(state => state.clearProject);
  const setStructure = useProjectStore(state => state.setStructure);
  const resetRepairState = useSetAtom(resetRepairStateAtom);
  const prevProjectPathRef = useRef<string | null>(null);
  const [isCheckingStructure, setIsCheckingStructure] = React.useState(false);

  // Check if there's a previously opened project on mount
  useEffect(() => {
    const loadLastProject = async (): Promise<void> => {
      const project = await getCurrentProject();
      if (project) {
        setCurrentProject(project);
        console.log("Restored previous project:", project.name);
      }
    };
    void loadLastProject();
  }, [getCurrentProject, setCurrentProject]);

  // Reset repair state when project changes
  useEffect(() => {
    const currentPath = currentProject?.path ?? null;
    if (
      prevProjectPathRef.current !== null &&
      currentPath !== prevProjectPathRef.current
    ) {
      // Project changed, reset repair state
      console.log("[AppLayout] Project changed, resetting repair state");
      resetRepairState();
    }
    prevProjectPathRef.current = currentPath;
  }, [currentProject?.path, resetRepairState]);

  // Check if project already has a structure file loaded
  useEffect(() => {
    if (!currentProject || hasStructure) {
      setIsCheckingStructure(false);
      return;
    }

    const checkExistingStructure = async (): Promise<void> => {
      setIsCheckingStructure(true);
      try {
        const result = await window.api.project.listOriginalStructures();
        if (result.success && result.files && result.files.length > 0) {
          // Load existing structure
          const firstFile = result.files[0];
          const structureResult = await window.api.project.readStructureFile(
            "original",
            firstFile
          );
          if (structureResult.success && structureResult.content) {
            setStructure(structureResult.content, firstFile);
            console.log("Loaded existing structure from project:", firstFile);
          }
        }
      } catch (error) {
        console.error("Failed to check existing structure:", error);
      } finally {
        setIsCheckingStructure(false);
      }
    };

    void checkExistingStructure();
  }, [currentProject, hasStructure, setStructure]);

  // Handle structure loaded from modal
  const handleStructureLoaded = useCallback(
    (content: string, filename: string) => {
      setStructure(content, filename);
      console.log("Structure loaded:", filename);
    },
    [setStructure]
  );

  // Handle modal close - go back to home
  const handleModalClose = useCallback(async () => {
    try {
      await closeProject();
      clearProject();
      resetRepairState();
      console.log("Project closed, returning to home");
    } catch (error) {
      console.error("Failed to close project:", error);
    }
  }, [closeProject, clearProject, resetRepairState]);

  // Show welcome screen if no project is open
  if (!currentProject) {
    return <ProjectWelcome />;
  }

  // Show main layout when project is open
  // Use project path as key to remount components when project changes
  const projectKey = currentProject.path;

  return (
    <div className="relative flex h-screen flex-col overflow-hidden">
      {/* Animated gradient background */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-50 via-slate-100 to-slate-50 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950 -z-10">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] dark:[mask-image:radial-gradient(ellipse_80%_50%_at_50%_0%,#000_70%,transparent_110%)]" />
        <div className="absolute inset-0 bg-gradient-to-t from-slate-50/50 via-transparent to-transparent dark:from-slate-950/50" />
      </div>

      <div className="relative z-10 flex h-screen flex-col">
        <Toolbar />
        <div className="flex-1 overflow-hidden">
          <PanelGroup direction="horizontal">
            <Panel defaultSize={65} minSize={30}>
              <MolViewerPanel key={projectKey} />
            </Panel>
            <PanelResizeHandle className="w-1 bg-slate-200/50 dark:bg-slate-800/50 hover:bg-blue-400/30 dark:hover:bg-blue-500/30 transition-colors" />
            <Panel defaultSize={35} minSize={20} maxSize={50}>
              <ControlPanel key={projectKey} />
            </Panel>
          </PanelGroup>
        </div>
        <StatusBar />

        {/* Structure Upload Modal - shown when project is open but no structure (only after checking) */}
        <StructureUploadModal
          open={!hasStructure && !isCheckingStructure}
          onStructureLoaded={handleStructureLoaded}
          onClose={handleModalClose}
        />
      </div>
    </div>
  );
}
