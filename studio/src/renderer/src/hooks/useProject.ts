import { useCallback } from "react";
import type {
  ProjectInfo,
  InpaintingYAML,
  ResidueMapping
} from "../types/project";

/**
 * Hook for project management operations
 */
export function useProject(): {
  createProject: (
    projectName: string,
    parentDir?: string
  ) => Promise<ProjectInfo | null>;
  openProject: (projectPath: string) => Promise<ProjectInfo | null>;
  openProjectDialog: () => Promise<ProjectInfo | null>;
  createProjectDialog: (defaultName?: string) => Promise<ProjectInfo | null>;
  saveYAML: (yaml: InpaintingYAML) => Promise<boolean>;
  loadYAML: () => Promise<InpaintingYAML | null>;
  saveMapping: (mapping: ResidueMapping) => Promise<boolean>;
  loadMapping: () => Promise<ResidueMapping | null>;
  importStructure: (
    sourcePath: string,
    type: "original" | "canonical"
  ) => Promise<string | null>;
  getCurrentProject: () => Promise<ProjectInfo | null>;
  closeProject: () => Promise<boolean>;
  openProjectFolder: () => Promise<boolean>;
} {
  const createProject = useCallback(
    async (
      projectName: string,
      parentDir?: string
    ): Promise<ProjectInfo | null> => {
      const result = await window.api.project.create(projectName, parentDir);
      if (!result.success || !result.project) {
        console.error("Failed to create project:", result.error);
        return null;
      }
      return result.project;
    },
    []
  );

  const openProject = useCallback(
    async (projectPath: string): Promise<ProjectInfo | null> => {
      const result = await window.api.project.open(projectPath);
      if (!result.success || !result.project) {
        console.error("Failed to open project:", result.error);
        return null;
      }
      return result.project;
    },
    []
  );

  const openProjectDialog =
    useCallback(async (): Promise<ProjectInfo | null> => {
      const result = await window.api.project.openDialog();
      if (!result.success || !result.project) {
        if (result.error) {
          console.error("Failed to open project:", result.error);
        }
        return null;
      }
      return result.project;
    }, []);

  const createProjectDialog = useCallback(
    async (defaultName?: string): Promise<ProjectInfo | null> => {
      const result = await window.api.project.createDialog(defaultName);
      if (!result.success || !result.project) {
        if (result.error) {
          console.error("Failed to create project:", result.error);
        }
        return null;
      }
      return result.project;
    },
    []
  );

  const saveYAML = useCallback(
    async (yaml: InpaintingYAML): Promise<boolean> => {
      const result = await window.api.project.saveYAML(yaml);
      if (!result.success) {
        console.error("Failed to save YAML:", result.error);
        return false;
      }
      return true;
    },
    []
  );

  const loadYAML = useCallback(async (): Promise<InpaintingYAML | null> => {
    const result = await window.api.project.loadYAML();
    if (!result.success || !result.yaml) {
      console.error("Failed to load YAML:", result.error);
      return null;
    }
    return result.yaml as InpaintingYAML;
  }, []);

  const saveMapping = useCallback(
    async (mapping: ResidueMapping): Promise<boolean> => {
      const result = await window.api.project.saveMapping(mapping);
      if (!result.success) {
        console.error("Failed to save mapping:", result.error);
        return false;
      }
      return true;
    },
    []
  );

  const loadMapping = useCallback(async (): Promise<ResidueMapping | null> => {
    const result = await window.api.project.loadMapping();
    if (!result.success || !result.mapping) {
      console.error("Failed to load mapping:", result.error);
      return null;
    }
    return result.mapping as ResidueMapping;
  }, []);

  const importStructure = useCallback(
    async (
      sourcePath: string,
      type: "original" | "canonical"
    ): Promise<string | null> => {
      const result = await window.api.project.importStructure(sourcePath, type);
      if (!result.success || !result.destPath) {
        console.error("Failed to import structure:", result.error);
        return null;
      }
      return result.destPath;
    },
    []
  );

  const getCurrentProject =
    useCallback(async (): Promise<ProjectInfo | null> => {
      const result = await window.api.project.getCurrent();
      if (!result.success) {
        return null;
      }
      return result.project || null;
    }, []);

  const closeProject = useCallback(async (): Promise<boolean> => {
    const result = await window.api.project.close();
    return result.success;
  }, []);

  const openProjectFolder = useCallback(async (): Promise<boolean> => {
    const result = await window.api.project.openFolder();
    if (!result.success) {
      console.error("Failed to open project folder:", result.error);
      return false;
    }
    return true;
  }, []);

  return {
    createProject,
    openProject,
    openProjectDialog,
    createProjectDialog,
    saveYAML,
    loadYAML,
    saveMapping,
    loadMapping,
    importStructure,
    getCurrentProject,
    closeProject,
    openProjectFolder
  };
}
