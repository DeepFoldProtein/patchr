import { ElectronAPI } from "@electron-toolkit/preload";

export interface ProjectInfo {
  path: string;
  name: string;
  yamlPath: string;
  structuresPath: string;
  mappingsPath: string;
  resultsPath: string;
}

export interface ProjectAPI {
  create: (
    projectName: string,
    parentDir?: string
  ) => Promise<{ success: boolean; project?: ProjectInfo; error?: string }>;
  open: (
    projectPath: string
  ) => Promise<{ success: boolean; project?: ProjectInfo; error?: string }>;
  openDialog: () => Promise<{
    success: boolean;
    project?: ProjectInfo | null;
    error?: string;
  }>;
  createDialog: (defaultName?: string) => Promise<{
    success: boolean;
    project?: ProjectInfo | null;
    error?: string;
  }>;
  saveYAML: (yaml: unknown) => Promise<{ success: boolean; error?: string }>;
  loadYAML: () => Promise<{ success: boolean; yaml?: unknown; error?: string }>;
  saveMapping: (
    mapping: unknown
  ) => Promise<{ success: boolean; error?: string }>;
  loadMapping: () => Promise<{
    success: boolean;
    mapping?: unknown;
    error?: string;
  }>;
  importStructure: (
    sourcePath: string,
    type: "original" | "canonical"
  ) => Promise<{ success: boolean; destPath?: string; error?: string }>;
  importStructureDialog: () => Promise<{
    success: boolean;
    content?: string;
    filename?: string;
    error?: string;
  }>;
  listOriginalStructures: () => Promise<{
    success: boolean;
    files?: string[];
    error?: string;
  }>;
  readStructureFile: (
    type: "original" | "canonical",
    filename: string
  ) => Promise<{ success: boolean; content?: string; error?: string }>;
  saveStructureContent: (
    type: "original" | "canonical",
    filename: string,
    content: string
  ) => Promise<{ success: boolean; error?: string }>;
  getCurrent: () => Promise<{ success: boolean; project?: ProjectInfo | null }>;
  close: () => Promise<{ success: boolean }>;
  openFolder: (
    folderPath?: string
  ) => Promise<{ success: boolean; error?: string }>;
  readFileByPath: (filePath: string) => Promise<{
    success: boolean;
    content?: string;
    error?: string;
  }>;
  listResults: () => Promise<{
    success: boolean;
    results?: Array<{
      runId: string;
      runPath: string;
      cifFiles: string[];
    }>;
    error?: string;
  }>;
  listDirectory: (dirPath: string) => Promise<{
    success: boolean;
    files?: string[];
    error?: string;
  }>;
}

export interface UniProtSearchResult {
  chainId: string;
  uniprotId: string | null;
  fasta: string | null;
  error?: string;
}

export interface UniProtAPI {
  searchByPdb: (
    pdbId: string,
    chainIds: string[]
  ) => Promise<{
    success: boolean;
    results?: UniProtSearchResult[];
    error?: string;
  }>;
}

export interface BoltzAPI {
  healthCheck: (apiUrl: string) => Promise<{
    success: boolean;
    data?: unknown;
    error?: string;
  }>;
  uploadTemplate: (
    apiUrl: string,
    cifContent: string,
    cifFilename: string,
    chainIds: string[],
    customSequences: string
  ) => Promise<{
    success: boolean;
    data?: { job_id: string; status: string };
    error?: string;
  }>;
  getJobStatus: (
    apiUrl: string,
    jobId: string
  ) => Promise<{
    success: boolean;
    data?: {
      status: string;
      progress?: number;
      error?: string;
    };
    error?: string;
  }>;
  runPrediction: (
    apiUrl: string,
    payload: {
      job_id: string;
      recycling_steps: number;
      sampling_steps: number;
      diffusion_samples: number;
      devices: number;
      accelerator: string;
      use_msa_server: boolean;
    }
  ) => Promise<{
    success: boolean;
    data?: unknown;
    error?: string;
  }>;
  downloadAndSaveResults: (
    apiUrl: string,
    jobId: string
  ) => Promise<{
    success: boolean;
    extractDir?: string;
    cifFiles?: string[];
    error?: string;
  }>;
  simReady: (
    apiUrl: string,
    payload: unknown
  ) => Promise<{
    success: boolean;
    data?: { job_id: string; status: string };
    error?: string;
  }>;
  membrane: (
    apiUrl: string,
    payload: unknown
  ) => Promise<{
    success: boolean;
    data?: { job_id: string; status: string };
    error?: string;
  }>;
  simResult: (
    apiUrl: string,
    jobId: string
  ) => Promise<{
    success: boolean;
    data?: unknown;
    error?: string;
  }>;
  downloadAndSaveSimResults: (
    apiUrl: string,
    jobId: string,
    simType: "sim" | "membrane"
  ) => Promise<{
    success: boolean;
    simId?: string;
    simDir?: string;
    files?: string[];
    systemPdbPath?: string;
    systemPdbContent?: string;
    error?: string;
  }>;
  opmLookup: (
    apiUrl: string,
    pdbId: string
  ) => Promise<{
    success: boolean;
    data?: unknown;
    error?: string;
  }>;
}

export interface AppAPI {
  setTheme: (theme: "light" | "dark") => Promise<{ success: boolean }>;
}

declare global {
  interface Window {
    electron: ElectronAPI;
    api: {
      project: ProjectAPI;
      uniprot: UniProtAPI;
      boltz: BoltzAPI;
      app: AppAPI;
    };
  }
}
