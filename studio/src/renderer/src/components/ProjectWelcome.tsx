import React, { useState } from "react";
import {
  FolderOpen,
  FolderPlus,
  FlaskConical,
  Clock,
  ArrowRight
} from "lucide-react";
import logoIcon from "@/assets/logo.png";
import { Card, CardContent } from "./ui/card";
import { useProject } from "../hooks/useProject";
import { useProjectStore, useRecentProjects } from "../store/project-store";

// Sample structures available
const SAMPLE_STRUCTURES = [
  {
    id: "4j76",
    name: "4J76",
    description: "multimer protein",
    file: "4J76.cif"
  },
  {
    id: "1ton",
    name: "1TON",
    description: "monomer protein",
    file: "1TON.cif"
  },
  {
    id: "1de9",
    name: "1DE9",
    description: "protein, DNA complex",
    file: "1DE9.cif"
  }
];

export function ProjectWelcome(): React.ReactElement {
  const { createProjectDialog, openProjectDialog } = useProject();
  const setCurrentProject = useProjectStore(state => state.setCurrentProject);
  const setStructure = useProjectStore(state => state.setStructure);
  const setLoading = useProjectStore(state => state.setLoading);
  const setError = useProjectStore(state => state.setError);
  const recentProjects = useRecentProjects();
  const [showSamples, setShowSamples] = useState(recentProjects.length === 0);

  const handleCreateProject = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const project = await createProjectDialog();
      if (project) {
        setCurrentProject(project);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to create project";
      setError(message);
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
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to open project";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenRecent = async (projectPath: string): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const result = await window.api.project.open(projectPath);
      if (result.success && result.project) {
        setCurrentProject(result.project);
      } else {
        setError(result.error || "Failed to open project");
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to open project";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenSample = async (sampleFile: string): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      // Create a temporary project for the sample
      const sampleName = sampleFile.replace(".cif", "");
      const project = await window.api.project.create(
        `Sample_${sampleName}_${Date.now()}`
      );

      if (!project.success || !project.project) {
        throw new Error(project.error || "Failed to create sample project");
      }

      // Load the sample structure via IPC (works in both dev and production)
      const sampleResult = await window.api.app.readSample(sampleFile);
      if (!sampleResult.success || !sampleResult.content) {
        throw new Error(sampleResult.error || "Failed to load sample structure");
      }
      const content = sampleResult.content;

      // Save to project's original folder
      const saveResult = await window.api.project.saveStructureContent(
        "original",
        sampleFile,
        content
      );

      if (!saveResult.success) {
        throw new Error(saveResult.error || "Failed to save sample structure");
      }

      // Set structure in store so modal doesn't show
      setStructure(content, sampleFile);
      setCurrentProject(project.project);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to open sample";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen overflow-y-auto">
      {/* Animated gradient background */}
      <div className="fixed inset-0 bg-gradient-to-br from-neutral-50 via-neutral-100 to-neutral-50 dark:from-neutral-950 dark:via-neutral-900 dark:to-neutral-950">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] dark:[mask-image:radial-gradient(ellipse_80%_50%_at_50%_0%,#000_70%,transparent_110%)]" />
        <div className="absolute inset-0 bg-gradient-to-t from-neutral-50/50 via-transparent to-transparent dark:from-neutral-950/50" />
      </div>

      {/* Content */}
      <div className="relative z-10 w-full space-y-8 px-6 py-16 md:max-w-4xl mx-auto">
        {/* Hero Section */}
        <div className="text-center space-y-4 opacity-0 animate-[fadeInUp_0.7s_ease-out_0.1s_forwards]">
          <div className="relative w-16 h-16 rounded-2xl overflow-hidden shadow-2xl mb-4 mx-auto group">
            <img src={logoIcon} alt="Patchr" className="w-full h-full" />
            <div className="absolute inset-0 bg-gradient-to-b from-white/30 via-transparent to-transparent" />
            <div className="absolute inset-0 bg-gradient-to-br from-white/10 via-transparent to-black/10" />
            <div className="absolute inset-0 rounded-2xl ring-1 ring-inset ring-white/20" />
            <div className="absolute -inset-full bg-gradient-to-r from-transparent via-white/20 to-transparent rotate-12 translate-x-[-200%] group-hover:translate-x-[200%] transition-transform duration-1000" />
          </div>
          <h1 className="text-5xl md:text-6xl font-bold text-neutral-900 dark:text-white">
            Patchr Studio
          </h1>
          <p className="text-lg text-neutral-600 dark:text-neutral-400 max-w-xl mx-auto">
            AI-powered molecular structure inpainting for DNA, RNA, and protein
            complexes
          </p>
        </div>

        {/* Main Actions */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 opacity-0 animate-[fadeInUp_0.7s_ease-out_0.3s_forwards]">
          <button
            onClick={handleCreateProject}
            className="group relative overflow-hidden rounded-xl border border-neutral-200 dark:border-neutral-800 bg-gradient-to-br from-white/80 to-neutral-50/80 dark:from-neutral-900/80 dark:to-neutral-800/80 backdrop-blur-xl p-6 text-left transition-all duration-300 hover:border-neutral-400/50 hover:shadow-lg hover:shadow-neutral-500/10 hover:-translate-y-1"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-neutral-500/0 to-neutral-400/0 group-hover:from-neutral-500/5 group-hover:to-neutral-400/5 transition-all duration-300" />
            <div className="relative">
              <div className="mb-4 inline-flex items-center justify-center w-12 h-12 rounded-lg bg-neutral-500/10 border border-neutral-500/20 group-hover:bg-neutral-500/20 group-hover:border-neutral-500/30 transition-colors">
                <FolderPlus className="h-6 w-6 text-neutral-600 dark:text-neutral-300" />
              </div>
              <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-1">
                New Project
              </h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                Start a new molecular structure project
              </p>
            </div>
          </button>

          <button
            onClick={handleOpenProject}
            className="group relative overflow-hidden rounded-xl border border-neutral-200 dark:border-neutral-800 bg-gradient-to-br from-white/80 to-neutral-50/80 dark:from-neutral-900/80 dark:to-neutral-800/80 backdrop-blur-xl p-6 text-left transition-all duration-300 hover:border-neutral-400/50 hover:shadow-lg hover:shadow-neutral-500/10 hover:-translate-y-1"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-neutral-500/0 to-neutral-400/0 group-hover:from-neutral-500/5 group-hover:to-neutral-400/5 transition-all duration-300" />
            <div className="relative">
              <div className="mb-4 inline-flex items-center justify-center w-12 h-12 rounded-lg bg-neutral-500/10 border border-neutral-500/20 group-hover:bg-neutral-500/20 group-hover:border-neutral-500/30 transition-colors">
                <FolderOpen className="h-6 w-6 text-neutral-600 dark:text-neutral-300" />
              </div>
              <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-1">
                Open Project
              </h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                Continue working on an existing project
              </p>
            </div>
          </button>

          <button
            onClick={() => setShowSamples(!showSamples)}
            className="group relative overflow-hidden rounded-xl border border-neutral-200 dark:border-neutral-800 bg-gradient-to-br from-white/80 to-neutral-50/80 dark:from-neutral-900/80 dark:to-neutral-800/80 backdrop-blur-xl p-6 text-left transition-all duration-300 hover:border-neutral-400/50 hover:shadow-lg hover:shadow-neutral-500/10 hover:-translate-y-1"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-neutral-500/0 to-neutral-400/0 group-hover:from-neutral-500/5 group-hover:to-neutral-400/5 transition-all duration-300" />
            <div className="relative">
              <div className="mb-4 inline-flex items-center justify-center w-12 h-12 rounded-lg bg-neutral-500/10 border border-neutral-500/20 group-hover:bg-neutral-500/20 group-hover:border-neutral-500/30 transition-colors">
                <FlaskConical className="h-6 w-6 text-neutral-600 dark:text-neutral-300" />
              </div>
              <h3 className="text-lg font-semibold text-neutral-900 dark:text-white mb-1">
                Sample Projects
              </h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                Explore example molecular structures
              </p>
            </div>
          </button>
        </div>

        {/* Sample Projects */}
        {showSamples && (
          <Card className="border-neutral-200/50 dark:border-neutral-800/50 bg-white/60 dark:bg-neutral-900/40 backdrop-blur-xl shadow-xl opacity-0 animate-[fadeInUp_0.5s_ease-out_forwards]">
            <CardContent className="p-6">
              <div className="flex items-center gap-2 mb-6">
                <FlaskConical className="h-5 w-5 text-neutral-500 dark:text-neutral-400" />
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-white">
                  Sample Projects
                </h3>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {SAMPLE_STRUCTURES.map((sample, index) => (
                  <button
                    key={sample.id}
                    onClick={() => handleOpenSample(sample.file)}
                    className="group relative overflow-hidden rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white/50 dark:bg-neutral-900/50 px-4 py-4 text-left transition-all duration-300 hover:border-neutral-400/50 hover:bg-neutral-100/70 dark:hover:bg-neutral-800/70 hover:shadow-lg hover:shadow-neutral-500/5 hover:-translate-y-0.5"
                    style={{
                      animationDelay: `${index * 100}ms`
                    }}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="font-semibold text-neutral-900 dark:text-white mb-1 group-hover:text-neutral-700 dark:group-hover:text-neutral-200 transition-colors">
                          {sample.name}
                        </div>
                        <div className="text-xs text-neutral-400">
                          {sample.description}
                        </div>
                      </div>
                      <ArrowRight className="h-4 w-4 text-neutral-600 group-hover:text-neutral-300 group-hover:translate-x-1 transition-all" />
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Recent Projects */}
        {recentProjects.length > 0 && (
          <Card className="border-neutral-200/50 dark:border-neutral-800/50 bg-white/60 dark:bg-neutral-900/40 backdrop-blur-xl shadow-xl opacity-0 animate-[fadeInUp_0.5s_ease-out_forwards]">
            <CardContent className="p-6">
              <div className="flex items-center gap-2 mb-6">
                <Clock className="h-5 w-5 text-neutral-500 dark:text-neutral-400" />
                <h3 className="text-lg font-semibold text-neutral-900 dark:text-white">
                  Recent Projects
                </h3>
              </div>
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {recentProjects.slice(0, 5).map((project, index) => (
                  <button
                    key={project.path}
                    onClick={() => handleOpenRecent(project.path)}
                    className="group w-full rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white/50 dark:bg-neutral-900/50 px-4 py-3 text-left transition-all duration-300 hover:border-neutral-400/50 hover:bg-neutral-100/70 dark:hover:bg-neutral-800/70 hover:shadow-md"
                    style={{
                      animationDelay: `${index * 50}ms`
                    }}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-neutral-900 dark:text-white truncate group-hover:text-neutral-700 dark:group-hover:text-neutral-200 transition-colors">
                          {project.name}
                        </div>
                        <div
                          className="text-xs text-neutral-500 truncate mt-1"
                          title={project.path}
                        >
                          {project.path}
                        </div>
                      </div>
                      <ArrowRight className="h-4 w-4 text-neutral-600 group-hover:text-neutral-300 group-hover:translate-x-1 transition-all flex-shrink-0" />
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Getting Started Info */}
        <div className="text-center space-y-2 opacity-0 animate-[fadeInUp_0.7s_ease-out_0.5s_forwards]">
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Create a new project to start inpainting missing regions in DNA,
            RNA, and protein complexes
          </p>
          <p className="text-xs text-neutral-500 dark:text-neutral-500">
            or open an existing project to continue your work
          </p>
        </div>
      </div>
    </div>
  );
}
