import { contextBridge, ipcRenderer } from "electron";
import { electronAPI } from "@electron-toolkit/preload";

// Custom APIs for renderer
const api = {
  // Project management
  project: {
    create: (projectName: string, parentDir?: string) =>
      ipcRenderer.invoke("project:create", projectName, parentDir),
    open: (projectPath: string) =>
      ipcRenderer.invoke("project:open", projectPath),
    openDialog: () => ipcRenderer.invoke("project:open-dialog"),
    createDialog: (defaultName?: string) =>
      ipcRenderer.invoke("project:create-dialog", defaultName),
    saveYAML: (yaml: unknown) => ipcRenderer.invoke("project:save-yaml", yaml),
    loadYAML: () => ipcRenderer.invoke("project:load-yaml"),
    saveMapping: (mapping: unknown) =>
      ipcRenderer.invoke("project:save-mapping", mapping),
    loadMapping: () => ipcRenderer.invoke("project:load-mapping"),
    importStructure: (sourcePath: string, type: "original" | "canonical") =>
      ipcRenderer.invoke("project:import-structure", sourcePath, type),
    importStructureDialog: () =>
      ipcRenderer.invoke("project:import-structure-dialog"),
    listOriginalStructures: () =>
      ipcRenderer.invoke("project:list-original-structures"),
    readStructureFile: (type: "original" | "canonical", filename: string) =>
      ipcRenderer.invoke("project:read-structure-file", type, filename),
    saveStructureContent: (
      type: "original" | "canonical",
      filename: string,
      content: string
    ) =>
      ipcRenderer.invoke(
        "project:save-structure-content",
        type,
        filename,
        content
      ),
    getCurrent: () => ipcRenderer.invoke("project:get-current"),
    close: () => ipcRenderer.invoke("project:close"),
    openFolder: (folderPath?: string) =>
      ipcRenderer.invoke("project:open-folder", folderPath),
    readFileByPath: (filePath: string) =>
      ipcRenderer.invoke("project:read-file-by-path", filePath),
    listResults: () => ipcRenderer.invoke("project:list-results"),
    listSimulations: () => ipcRenderer.invoke("project:list-simulations"),
    listDirectory: (dirPath: string) =>
      ipcRenderer.invoke("project:list-directory", dirPath)
  },
  // UniProt search
  uniprot: {
    searchByPdb: (pdbId: string, chainIds: string[]) =>
      ipcRenderer.invoke("uniprot:search-by-pdb", pdbId, chainIds)
  },
  // Boltz API
  boltz: {
    healthCheck: (apiUrl: string) =>
      ipcRenderer.invoke("boltz:health-check", apiUrl),
    uploadTemplate: (
      apiUrl: string,
      cifContent: string,
      cifFilename: string,
      chainIds: string[],
      customSequences: string
    ) =>
      ipcRenderer.invoke(
        "boltz:upload-template",
        apiUrl,
        cifContent,
        cifFilename,
        chainIds,
        customSequences
      ),
    getJobStatus: (apiUrl: string, jobId: string) =>
      ipcRenderer.invoke("boltz:get-job-status", apiUrl, jobId),
    runPrediction: (apiUrl: string, payload: unknown) =>
      ipcRenderer.invoke("boltz:run-prediction", apiUrl, payload),
    downloadAndSaveResults: (apiUrl: string, jobId: string) =>
      ipcRenderer.invoke("boltz:download-and-save-results", apiUrl, jobId),
    simReady: (apiUrl: string, payload: unknown) =>
      ipcRenderer.invoke("boltz:sim-ready", apiUrl, payload),
    simResult: (apiUrl: string, jobId: string) =>
      ipcRenderer.invoke("boltz:sim-result", apiUrl, jobId),
    downloadAndSaveSimResults: (apiUrl: string, jobId: string) =>
      ipcRenderer.invoke("boltz:download-and-save-sim-results", apiUrl, jobId)
  },
  // App settings
  app: {
    setTheme: (theme: "light" | "dark") =>
      ipcRenderer.invoke("app:set-theme", theme),
    readSample: (filename: string) =>
      ipcRenderer.invoke("app:read-sample", filename)
  }
};

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("electron", electronAPI);
    contextBridge.exposeInMainWorld("api", api);
  } catch (error) {
    console.error(error);
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI;
  // @ts-ignore (define in dts)
  window.api = api;
}
