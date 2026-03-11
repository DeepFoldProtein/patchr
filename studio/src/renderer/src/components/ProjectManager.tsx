import React, { useCallback } from "react";
import { useProject } from "../hooks/useProject";
import {
  useProjectStore,
  useCurrentProject,
  useProjectLoading,
  useProjectError
} from "../store/project-store";
import { Button } from "./ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "./ui/card";
import { Alert, AlertDescription } from "./ui/alert";
import {
  FolderOpen,
  FolderPlus,
  X,
  Folder,
  AlertTriangle,
  Loader2,
  FolderTree,
  FileText
} from "lucide-react";

export function ProjectManager(): React.ReactElement {
  // Zustand store selectors
  const currentProject = useCurrentProject();
  const isLoading = useProjectLoading();
  const error = useProjectError();

  // Get action methods directly from store
  const store = useProjectStore();
  const setCurrentProject = useCallback(
    project => store.setCurrentProject(project),
    [store]
  );
  const setLoading = useCallback(loading => store.setLoading(loading), [store]);
  const setError = useCallback(error => store.setError(error), [store]);
  const clearProject = useCallback(() => store.clearProject(), [store]);

  const {
    createProjectDialog,
    openProjectDialog,
    closeProject,
    openProjectFolder
  } = useProject();

  const handleCreateProject = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const project = await createProjectDialog();
      if (project) {
        setCurrentProject(project);
        console.log("✅ Project created:", project);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to create project";
      setError(message);
      console.error("❌ Error creating project:", message);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenProject = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const project = await openProjectDialog();
      if (project) {
        setCurrentProject(project);
        console.log("✅ Project opened:", project);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to open project";
      setError(message);
      console.error("❌ Error opening project:", message);
    } finally {
      setLoading(false);
    }
  };

  const handleCloseProject = async (): Promise<void> => {
    try {
      await closeProject();
      clearProject();
      console.log("🔒 Project closed");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to close project";
      setError(message);
      console.error("❌ Error closing project:", message);
    }
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>Current Project</CardTitle>
        <CardDescription>Project structure and configuration</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Error Display */}
        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Loading State */}
        {isLoading && (
          <Alert>
            <Loader2 className="h-4 w-4 animate-spin" />
            <AlertDescription>Loading...</AlertDescription>
          </Alert>
        )}

        {/* Current Project Info */}
        {currentProject ? (
          <div className="space-y-4">
            <div className="p-4 bg-muted rounded-lg space-y-2">
              <div className="font-semibold text-sm text-muted-foreground">
                Project Information
              </div>
              <div className="font-mono text-sm space-y-1">
                <div>
                  <span className="font-semibold">Name:</span>{" "}
                  {currentProject.name}
                </div>
                <div>
                  <span className="font-semibold">Path:</span>{" "}
                  <span className="text-xs break-all">
                    {currentProject.path}
                  </span>
                </div>
              </div>
            </div>

            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="text-xs text-muted-foreground space-y-1">
                <div className="font-semibold mb-2">Project Structure:</div>
                <div className="flex items-center gap-1.5">
                  <FolderTree className="h-3 w-3 shrink-0" />
                  structures/original/ - Original PDB/CIF files
                </div>
                <div className="flex items-center gap-1.5">
                  <FolderTree className="h-3 w-3 shrink-0" />
                  results/ - Inpainting results
                </div>
                <div className="ml-4 mt-1 space-y-0.5 text-xs">
                  <div>└── run_XXX/ - Individual run directories</div>
                  <div className="ml-4">
                    └── predictions/ - Prediction CIF files and YAML
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <FolderTree className="h-3 w-3 shrink-0" />
                  simulations/ - Simulation output files
                </div>
                <div className="ml-4 mt-1 space-y-0.5 text-xs">
                  <div>├── sim_XXX/ - Sim-ready preparation results</div>
                  <div>└── mem_XXX/ - Membrane embedding results</div>
                </div>
                <div className="flex items-center gap-1.5">
                  <FileText className="h-3 w-3 shrink-0" />
                  project.yaml - Configuration file
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-2">
              <Button
                onClick={async () => {
                  const success = await openProjectFolder();
                  if (!success) {
                    setError("Failed to open project folder");
                  }
                }}
                variant="outline"
                size="sm"
                className="flex-1"
              >
                <Folder className="mr-2 h-4 w-4" />
                Open Folder
              </Button>
              <Button
                onClick={handleCloseProject}
                variant="destructive"
                size="sm"
                className="flex-1"
              >
                <X className="mr-2 h-4 w-4" />
                Close Project
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="p-8 bg-muted rounded-lg text-center text-sm text-muted-foreground">
              No project open
            </div>

            {/* Action Buttons */}
            <div className="grid grid-cols-2 gap-3">
              <Button
                onClick={handleCreateProject}
                variant="default"
                disabled={isLoading}
              >
                <FolderPlus className="mr-2 h-4 w-4" />
                New Project
              </Button>
              <Button
                onClick={handleOpenProject}
                variant="outline"
                disabled={isLoading}
              >
                <FolderOpen className="mr-2 h-4 w-4" />
                Open Project
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
