import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  ProjectInfo,
  InpaintingYAML,
  ResidueMapping
} from "../types/project";

/**
 * Project State Management with Zustand
 *
 * This store handles:
 * - Current project info (path, name, directories)
 * - Project YAML configuration
 * - Residue mapping data
 * - Project history/snapshots
 */

interface ProjectState {
  // Current project info
  currentProject: ProjectInfo | null;
  currentYAML: InpaintingYAML | null;
  currentMapping: ResidueMapping | null;

  // Structure state
  hasStructure: boolean;
  structureContent: string | null;
  structureFilename: string | null;

  // Loading states
  isLoading: boolean;
  error: string | null;

  // Recent projects
  recentProjects: ProjectInfo[];

  // Actions
  setCurrentProject: (project: ProjectInfo | null) => void;
  setCurrentYAML: (yaml: InpaintingYAML | null) => void;
  setCurrentMapping: (mapping: ResidueMapping | null) => void;
  setStructure: (content: string | null, filename: string | null) => void;
  setError: (error: string | null) => void;
  setLoading: (loading: boolean) => void;
  addRecentProject: (project: ProjectInfo) => void;
  removeRecentProject: (path: string) => void;
  clearProject: () => void;
}

/**
 * Main project store
 * Persists recent projects to localStorage
 */
export const useProjectStore = create<ProjectState>()(
  persist(
    set => ({
      currentProject: null,
      currentYAML: null,
      currentMapping: null,
      hasStructure: false,
      structureContent: null,
      structureFilename: null,
      isLoading: false,
      error: null,
      recentProjects: [],

      setCurrentProject: (project: ProjectInfo | null) => {
        set({
          currentProject: project,
          error: null,
          // Reset structure state when changing project
          hasStructure: false,
          structureContent: null,
          structureFilename: null
        });
        // Add to recent projects if opening a project
        if (project) {
          set(state => {
            const existing = state.recentProjects.find(
              p => p.path === project.path
            );
            if (existing) {
              // Move to front
              return {
                recentProjects: [
                  project,
                  ...state.recentProjects.filter(p => p.path !== project.path)
                ]
              };
            }
            // Add new
            return {
              recentProjects: [project, ...state.recentProjects].slice(0, 10)
            };
          });
        }
      },

      setCurrentYAML: (yaml: InpaintingYAML | null) => {
        set({ currentYAML: yaml });
      },

      setCurrentMapping: (mapping: ResidueMapping | null) => {
        set({ currentMapping: mapping });
      },

      setStructure: (content: string | null, filename: string | null) => {
        set({
          structureContent: content,
          structureFilename: filename,
          hasStructure: content !== null
        });
      },

      setError: (error: string | null) => {
        set({ error });
      },

      setLoading: (loading: boolean) => {
        set({ isLoading: loading });
      },

      addRecentProject: (project: ProjectInfo) => {
        set(state => {
          const existing = state.recentProjects.find(
            p => p.path === project.path
          );
          if (existing) {
            // Move to front
            return {
              recentProjects: [
                project,
                ...state.recentProjects.filter(p => p.path !== project.path)
              ]
            };
          }
          // Add new, keep last 10
          return {
            recentProjects: [project, ...state.recentProjects].slice(0, 10)
          };
        });
      },

      removeRecentProject: (path: string) => {
        set(state => ({
          recentProjects: state.recentProjects.filter(p => p.path !== path)
        }));
      },

      clearProject: () => {
        set({
          currentProject: null,
          currentYAML: null,
          currentMapping: null,
          hasStructure: false,
          structureContent: null,
          structureFilename: null,
          error: null
        });
      }
    }),
    {
      name: "patchr-project-store",
      partialize: state => ({
        recentProjects: state.recentProjects
      })
    }
  )
);

/**
 * Derived state selectors
 */
export const useCurrentProject = (): ProjectInfo | null =>
  useProjectStore(
    (state: ProjectState): ProjectInfo | null => state.currentProject
  );
export const useCurrentYAML = (): InpaintingYAML | null =>
  useProjectStore(
    (state: ProjectState): InpaintingYAML | null => state.currentYAML
  );
export const useCurrentMapping = (): ResidueMapping | null =>
  useProjectStore(
    (state: ProjectState): ResidueMapping | null => state.currentMapping
  );
export const useHasStructure = (): boolean =>
  useProjectStore((state: ProjectState): boolean => state.hasStructure);
export const useStructureContent = (): string | null =>
  useProjectStore(
    (state: ProjectState): string | null => state.structureContent
  );
export const useStructureFilename = (): string | null =>
  useProjectStore(
    (state: ProjectState): string | null => state.structureFilename
  );
export const useProjectLoading = (): boolean =>
  useProjectStore((state: ProjectState): boolean => state.isLoading);
export const useProjectError = (): string | null =>
  useProjectStore((state: ProjectState): string | null => state.error);
export const useRecentProjects = (): ProjectInfo[] =>
  useProjectStore((state: ProjectState): ProjectInfo[] => state.recentProjects);
