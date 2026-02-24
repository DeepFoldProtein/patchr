/// <reference types="vite/client" />

// Import preload types
import type { ProjectAPI, UniProtAPI, BoltzAPI } from "../../preload/index.d";

declare global {
  interface Window {
    electron: import("@electron-toolkit/preload").ElectronAPI;
    api: {
      project: ProjectAPI;
      uniprot: UniProtAPI;
      boltz: BoltzAPI;
    };
  }
}
