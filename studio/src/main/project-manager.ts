import { app, dialog, ipcMain, shell, net } from "electron";
import { join, basename } from "path";
import { promises as fs } from "fs";
import { existsSync } from "fs";

/**
 * Project structure:
 *
 * {projectPath}/
 *   ├── project.yaml              # Main inpainting configuration
 *   ├── structures/
 *   │   └── original/
 *   │       └── *.cif, *.pdb     # Original structure files
 *   └── results/
 *       ├── run_001/
 *       │   ├── predictions/
 *       │   │   ├── *.cif         # Prediction result CIF files
 *       │   │   └── *.yaml        # YAML configuration for this run
 *       │   └── *_predictions.zip  # Downloaded prediction archive
 *       └── run_002/
 */

export interface ProjectInfo {
  path: string;
  name: string;
  yamlPath: string;
  structuresPath: string;
  mappingsPath: string;
  resultsPath: string;
}

export interface ResidueMapping {
  chain_mapping: {
    [authorChainId: string]: {
      author_id: string;
      canonical_id: string;
    };
  };
  residue_mappings: {
    [chainId: string]: {
      [authorResId: string]: {
        canonical_index: number;
        author_id: string | null;
        generated_id?: string; // "I1", "I2", ...
        type?: "complete_missing" | "partial" | "sidechain_rebuild";
        insertion_code?: string;
      };
    };
  };
}

export interface InpaintingYAML {
  version: number;
  metadata: {
    original_pdb: string;
    created: string;
    modified: string;
  };
  sequences: Array<{
    protein: {
      id: string; // Canonical chain ID
      author_chain_id: string;
      full_sequence: string;
      residue_mapping_ref: string; // Reference to mapping file
      msa: "empty" | string;
    };
  }>;
  inpainting: Array<{
    input_cif: string; // Path to canonical CIF
    chain_id: string;
    residue_ranges: Array<{
      start: number;
      end: number;
      type: "complete_missing" | "partial" | "sidechain_rebuild";
      author_id_range: [number, number] | null;
      generated_ids?: string[];
    }>;
    context?: {
      include_neighbors: boolean;
      radius_Ang: number;
      soft_shell_Ang?: number;
    };
  }>;
}

class ProjectManager {
  private currentProject: ProjectInfo | null = null;

  /**
   * Get default projects directory (~/Documents/PatchrProjects)
   */
  getDefaultProjectsDir(): string {
    const documentsPath = app.getPath("documents");
    return join(documentsPath, "PatchrProjects");
  }

  /**
   * Ensure default projects directory exists
   */
  async ensureProjectsDir(): Promise<void> {
    const projectsDir = this.getDefaultProjectsDir();
    if (!existsSync(projectsDir)) {
      await fs.mkdir(projectsDir, { recursive: true });
    }
  }

  /**
   * Create new project structure
   */
  async createProject(
    projectName: string,
    parentDir?: string
  ): Promise<ProjectInfo> {
    await this.ensureProjectsDir();

    const baseDir = parentDir || this.getDefaultProjectsDir();
    const projectPath = join(baseDir, projectName);

    // Check if project already exists
    if (existsSync(projectPath)) {
      throw new Error(
        `Project "${projectName}" already exists at ${projectPath}`
      );
    }

    // Create directory structure
    const dirs = [
      projectPath,
      join(projectPath, "structures", "original"),
      join(projectPath, "structures", "canonical"),
      join(projectPath, "mappings"),
      join(projectPath, "results")
    ];

    for (const dir of dirs) {
      await fs.mkdir(dir, { recursive: true });
    }

    const projectInfo: ProjectInfo = {
      path: projectPath,
      name: projectName,
      yamlPath: join(projectPath, "project.yaml"),
      structuresPath: join(projectPath, "structures"),
      mappingsPath: join(projectPath, "mappings"),
      resultsPath: join(projectPath, "results")
    };

    // Create initial YAML
    const initialYAML: InpaintingYAML = {
      version: 1,
      metadata: {
        original_pdb: "",
        created: new Date().toISOString(),
        modified: new Date().toISOString()
      },
      sequences: [],
      inpainting: []
    };

    await this.saveYAML(projectInfo, initialYAML);

    this.currentProject = projectInfo;
    return projectInfo;
  }

  /**
   * Open existing project
   */
  async openProject(projectPath: string): Promise<ProjectInfo> {
    // Validate project structure
    const yamlPath = join(projectPath, "project.yaml");
    if (!existsSync(yamlPath)) {
      throw new Error(
        `Invalid project: project.yaml not found at ${projectPath}`
      );
    }

    const projectName = basename(projectPath);
    const projectInfo: ProjectInfo = {
      path: projectPath,
      name: projectName,
      yamlPath,
      structuresPath: join(projectPath, "structures"),
      mappingsPath: join(projectPath, "mappings"),
      resultsPath: join(projectPath, "results")
    };

    this.currentProject = projectInfo;
    return projectInfo;
  }

  /**
   * Show open project dialog
   */
  async showOpenDialog(): Promise<ProjectInfo | null> {
    const result = await dialog.showOpenDialog({
      title: "Open Patchr Project",
      defaultPath: this.getDefaultProjectsDir(),
      properties: ["openDirectory"]
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    return this.openProject(result.filePaths[0]);
  }

  /**
   * Show create project dialog
   */
  async showCreateDialog(
    defaultName: string = "Untitled"
  ): Promise<ProjectInfo | null> {
    await this.ensureProjectsDir();

    const result = await dialog.showSaveDialog({
      title: "Create Patchr Project",
      defaultPath: join(this.getDefaultProjectsDir(), defaultName),
      properties: ["createDirectory", "showOverwriteConfirmation"]
    });

    if (result.canceled || !result.filePath) {
      return null;
    }

    const projectName = basename(result.filePath);
    const parentDir = join(result.filePath, "..");

    return this.createProject(projectName, parentDir);
  }

  /**
   * Save YAML to project
   */
  async saveYAML(project: ProjectInfo, yaml: InpaintingYAML): Promise<void> {
    yaml.metadata.modified = new Date().toISOString();
    const yamlContent = this.stringifyYAML(yaml);
    await fs.writeFile(project.yamlPath, yamlContent, "utf-8");
  }

  /**
   * Load YAML from project
   */
  async loadYAML(project: ProjectInfo): Promise<InpaintingYAML> {
    const content = await fs.readFile(project.yamlPath, "utf-8");
    return this.parseYAML(content);
  }

  /**
   * Save residue mapping
   */
  async saveMapping(
    project: ProjectInfo,
    mapping: ResidueMapping
  ): Promise<void> {
    const mappingPath = join(project.mappingsPath, "residue_mapping.json");
    await fs.writeFile(mappingPath, JSON.stringify(mapping, null, 2), "utf-8");
  }

  /**
   * Load residue mapping
   */
  async loadMapping(project: ProjectInfo): Promise<ResidueMapping> {
    const mappingPath = join(project.mappingsPath, "residue_mapping.json");
    const content = await fs.readFile(mappingPath, "utf-8");
    return JSON.parse(content);
  }

  /**
   * Copy structure file to project
   */
  async importStructure(
    project: ProjectInfo,
    sourcePath: string,
    type: "original" | "canonical"
  ): Promise<string> {
    const filename = basename(sourcePath);
    const destDir = join(project.structuresPath, type);
    const destPath = join(destDir, filename);

    await fs.copyFile(sourcePath, destPath);
    return destPath;
  }

  /**
   * Show import structure dialog and copy to project
   */
  async importStructureDialog(): Promise<{
    filename: string;
    content: string;
  } | null> {
    const project = this.getCurrentProject();
    if (!project) {
      throw new Error("No project is currently open");
    }

    const result = await dialog.showOpenDialog({
      title: "Import Structure File",
      defaultPath: app.getPath("home"),
      properties: ["openFile"],
      filters: [
        { name: "Structure Files", extensions: ["pdb", "cif", "mmcif"] },
        { name: "All Files", extensions: ["*"] }
      ]
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    const sourcePath = result.filePaths[0];
    const filename = basename(sourcePath);
    const destDir = join(project.structuresPath, "original");
    const destPath = join(destDir, filename);

    // Copy file
    await fs.copyFile(sourcePath, destPath);

    // Read and return content
    const content = await fs.readFile(destPath, "utf-8");
    return { filename, content };
  }

  /**
   * List structure files in original folder
   */
  async listOriginalStructures(project: ProjectInfo): Promise<string[]> {
    const originalDir = join(project.structuresPath, "original");

    if (!existsSync(originalDir)) {
      return [];
    }

    const files = await fs.readdir(originalDir);
    return files.filter(
      f => f.endsWith(".pdb") || f.endsWith(".cif") || f.endsWith(".mmcif")
    );
  }

  /**
   * Read structure file content
   */
  async readStructureFile(
    project: ProjectInfo,
    type: "original" | "canonical",
    filename: string
  ): Promise<string> {
    const filePath = join(project.structuresPath, type, filename);
    return await fs.readFile(filePath, "utf-8");
  }

  /**
   * Save structure file content
   */
  async saveStructureContent(
    project: ProjectInfo,
    type: "original" | "canonical",
    filename: string,
    content: string
  ): Promise<void> {
    const filePath = join(project.structuresPath, type, filename);
    await fs.writeFile(filePath, content, "utf-8");
  }

  /**
   * Get current project
   */
  getCurrentProject(): ProjectInfo | null {
    return this.currentProject;
  }

  /**
   * Close current project
   */
  closeProject(): void {
    this.currentProject = null;
  }

  /**
   * Simple YAML stringify (for basic structure)
   */
  private stringifyYAML(obj: InpaintingYAML): string {
    let yaml = `version: ${obj.version}\n\n`;

    yaml += "metadata:\n";
    yaml += `  original_pdb: "${obj.metadata.original_pdb}"\n`;
    yaml += `  created: "${obj.metadata.created}"\n`;
    yaml += `  modified: "${obj.metadata.modified}"\n\n`;

    yaml += "sequences:\n";
    if (obj.sequences.length === 0) {
      yaml += "  []\n\n";
    } else {
      for (const seq of obj.sequences) {
        yaml += "  - protein:\n";
        yaml += `      id: ${seq.protein.id}\n`;
        yaml += `      author_chain_id: ${seq.protein.author_chain_id}\n`;
        yaml += `      full_sequence: |\n`;
        // Wrap sequence at 80 chars
        const seqLines = seq.protein.full_sequence.match(/.{1,80}/g) || [];
        for (const line of seqLines) {
          yaml += `        ${line}\n`;
        }
        yaml += `      residue_mapping_ref: "${seq.protein.residue_mapping_ref}"\n`;
        yaml += `      msa: ${seq.protein.msa}\n`;
      }
      yaml += "\n";
    }

    yaml += "inpainting:\n";
    if (obj.inpainting.length === 0) {
      yaml += "  []\n";
    } else {
      for (const inp of obj.inpainting) {
        yaml += "  - input_cif: " + inp.input_cif + "\n";
        yaml += `    chain_id: ${inp.chain_id}\n`;
        yaml += "    residue_ranges:\n";
        for (const range of inp.residue_ranges) {
          yaml += `      - start: ${range.start}\n`;
          yaml += `        end: ${range.end}\n`;
          yaml += `        type: ${range.type}\n`;
          yaml += `        author_id_range: ${range.author_id_range ? `[${range.author_id_range.join(", ")}]` : "null"}\n`;
          if (range.generated_ids && range.generated_ids.length > 0) {
            yaml += `        generated_ids: [${range.generated_ids.join(", ")}]\n`;
          }
        }
        if (inp.context) {
          yaml += "    context:\n";
          yaml += `      include_neighbors: ${inp.context.include_neighbors}\n`;
          yaml += `      radius_Ang: ${inp.context.radius_Ang}\n`;
          if (inp.context.soft_shell_Ang) {
            yaml += `      soft_shell_Ang: ${inp.context.soft_shell_Ang}\n`;
          }
        }
      }
    }

    return yaml;
  }

  /**
   * Simple YAML parser (for basic structure)
   * Note: For production, use a proper YAML library like 'yaml' or 'js-yaml'
   */
  private parseYAML(content: string): InpaintingYAML {
    // For now, return a placeholder - in production, use proper YAML parser
    // This is just to satisfy TypeScript
    const lines = content.split("\n");
    const versionLine = lines.find(l => l.startsWith("version:"));
    const version = versionLine
      ? parseInt(versionLine.split(":")[1].trim())
      : 1;

    return {
      version,
      metadata: {
        original_pdb: "",
        created: new Date().toISOString(),
        modified: new Date().toISOString()
      },
      sequences: [],
      inpainting: []
    };
  }
}

// Singleton instance
export const projectManager = new ProjectManager();

// IPC handlers
export function registerProjectIPC(): void {
  ipcMain.handle(
    "project:create",
    async (_event, projectName: string, parentDir?: string) => {
      try {
        const project = await projectManager.createProject(
          projectName,
          parentDir
        );
        return { success: true, project };
      } catch (error) {
        return { success: false, error: (error as Error).message };
      }
    }
  );

  ipcMain.handle("project:open", async (_event, projectPath: string) => {
    try {
      const project = await projectManager.openProject(projectPath);
      return { success: true, project };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  ipcMain.handle("project:open-dialog", async () => {
    try {
      const project = await projectManager.showOpenDialog();
      return { success: true, project };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  ipcMain.handle(
    "project:create-dialog",
    async (_event, defaultName?: string) => {
      try {
        const project = await projectManager.showCreateDialog(defaultName);
        return { success: true, project };
      } catch (error) {
        return { success: false, error: (error as Error).message };
      }
    }
  );

  ipcMain.handle("project:save-yaml", async (_event, yaml: InpaintingYAML) => {
    try {
      const project = projectManager.getCurrentProject();
      if (!project) {
        throw new Error("No project is currently open");
      }
      await projectManager.saveYAML(project, yaml);
      return { success: true };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  ipcMain.handle("project:load-yaml", async () => {
    try {
      const project = projectManager.getCurrentProject();
      if (!project) {
        throw new Error("No project is currently open");
      }
      const yaml = await projectManager.loadYAML(project);
      return { success: true, yaml };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  ipcMain.handle(
    "project:save-mapping",
    async (_event, mapping: ResidueMapping) => {
      try {
        const project = projectManager.getCurrentProject();
        if (!project) {
          throw new Error("No project is currently open");
        }
        await projectManager.saveMapping(project, mapping);
        return { success: true };
      } catch (error) {
        return { success: false, error: (error as Error).message };
      }
    }
  );

  ipcMain.handle("project:load-mapping", async () => {
    try {
      const project = projectManager.getCurrentProject();
      if (!project) {
        throw new Error("No project is currently open");
      }
      const mapping = await projectManager.loadMapping(project);
      return { success: true, mapping };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  ipcMain.handle(
    "project:import-structure",
    async (_event, sourcePath: string, type: "original" | "canonical") => {
      try {
        const project = projectManager.getCurrentProject();
        if (!project) {
          throw new Error("No project is currently open");
        }
        const destPath = await projectManager.importStructure(
          project,
          sourcePath,
          type
        );
        return { success: true, destPath };
      } catch (error) {
        return { success: false, error: (error as Error).message };
      }
    }
  );

  ipcMain.handle("project:get-current", () => {
    const project = projectManager.getCurrentProject();
    return { success: true, project };
  });

  ipcMain.handle("project:close", () => {
    projectManager.closeProject();
    return { success: true };
  });

  ipcMain.handle("project:import-structure-dialog", async () => {
    try {
      const result = await projectManager.importStructureDialog();
      if (!result) {
        return { success: true, content: null, filename: null };
      }
      return { success: true, ...result };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  ipcMain.handle("project:list-original-structures", async () => {
    try {
      const project = projectManager.getCurrentProject();
      if (!project) {
        throw new Error("No project is currently open");
      }
      const files = await projectManager.listOriginalStructures(project);
      return { success: true, files };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  ipcMain.handle(
    "project:read-structure-file",
    async (_event, type: "original" | "canonical", filename: string) => {
      try {
        const project = projectManager.getCurrentProject();
        if (!project) {
          throw new Error("No project is currently open");
        }
        const content = await projectManager.readStructureFile(
          project,
          type,
          filename
        );
        return { success: true, content };
      } catch (error) {
        return { success: false, error: (error as Error).message };
      }
    }
  );

  ipcMain.handle(
    "project:save-structure-content",
    async (
      _event,
      type: "original" | "canonical",
      filename: string,
      content: string
    ) => {
      try {
        const project = projectManager.getCurrentProject();
        if (!project) {
          throw new Error("No project is currently open");
        }
        await projectManager.saveStructureContent(
          project,
          type,
          filename,
          content
        );
        return { success: true };
      } catch (error) {
        return { success: false, error: (error as Error).message };
      }
    }
  );

  // List all results in results folder
  ipcMain.handle("project:list-results", async () => {
    const project = projectManager.getCurrentProject();
    if (!project) {
      return { success: false, error: "No project is currently open" };
    }

    try {
      const resultsDir = project.resultsPath;
      if (!existsSync(resultsDir)) {
        return { success: true, results: [] };
      }

      const entries = await fs.readdir(resultsDir, { withFileTypes: true });
      const results: Array<{
        runId: string;
        runPath: string;
        predictionsPath: string;
        cifFiles: string[];
      }> = [];

      for (const entry of entries) {
        if (entry.isDirectory() && entry.name.startsWith("run_")) {
          const runPath = join(resultsDir, entry.name);
          const predictionsDir = join(runPath, "predictions");

          // Find all CIF files in this run and locate model CIF folder
          let modelCifFolderPath: string | null = null;
          const findCifFiles = async (dir: string): Promise<string[]> => {
            if (!existsSync(dir)) return [];
            const cifFiles: string[] = [];
            const dirEntries = await fs.readdir(dir, { withFileTypes: true });

            for (const dirEntry of dirEntries) {
              const fullPath = join(dir, dirEntry.name);
              if (dirEntry.isDirectory()) {
                const subFiles = await findCifFiles(fullPath);
                cifFiles.push(...subFiles);
              } else if (
                dirEntry.name.endsWith(".cif") ||
                dirEntry.name.endsWith(".mmcif")
              ) {
                // Check if this is a model CIF file
                const isModelFile =
                  dirEntry.name.toLowerCase().includes("model") &&
                  !dirEntry.name.toLowerCase().includes("template");

                // If it's a model file and we haven't found a model folder yet, save this folder
                if (isModelFile && modelCifFolderPath === null) {
                  modelCifFolderPath = dir;
                }

                // Return relative path from project root
                const relative = fullPath.replace(
                  project.path + join("", ""),
                  ""
                );
                cifFiles.push(
                  relative.startsWith(join("", ""))
                    ? relative.slice(1)
                    : relative
                );
              }
            }
            return cifFiles;
          };

          const cifFiles = await findCifFiles(predictionsDir);

          // Use model CIF folder if found, otherwise fall back to predictions folder
          const folderToOpen = modelCifFolderPath || predictionsDir;

          results.push({
            runId: entry.name,
            runPath,
            predictionsPath: folderToOpen,
            cifFiles
          });
        }
      }

      // Sort by run ID (run_001, run_002, etc.)
      results.sort((a, b) => a.runId.localeCompare(b.runId));

      return { success: true, results };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error"
      };
    }
  });

  ipcMain.handle("project:list-directory", async (_event, dirPath: string) => {
    try {
      const files = await fs.readdir(dirPath);
      return { success: true, files };
    } catch (error) {
      return { success: false, files: [], error: (error as Error).message };
    }
  });

  ipcMain.handle("project:open-folder", async (_event, folderPath?: string) => {
    try {
      if (folderPath) {
        await shell.openPath(folderPath);
        return { success: true };
      }
      const project = projectManager.getCurrentProject();
      if (!project) {
        throw new Error("No project is currently open");
      }
      await shell.openPath(project.path);
      return { success: true };
    } catch (error) {
      return { success: false, error: (error as Error).message };
    }
  });

  // UniProt search handlers
  ipcMain.handle(
    "uniprot:search-by-pdb",
    async (_event, pdbId: string, chainIds: string[]) => {
      try {
        // Step 1: Get UniProt mapping from SIFTS API
        const siftsUrl = `https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/${pdbId.toUpperCase()}`;
        const siftsResponse = await net.fetch(siftsUrl);

        if (!siftsResponse.ok) {
          throw new Error(`SIFTS API error: ${siftsResponse.statusText}`);
        }

        const siftsData = await siftsResponse.json();
        const pdbIdLower = pdbId.toLowerCase();

        if (!siftsData[pdbIdLower] || !siftsData[pdbIdLower].UniProt) {
          throw new Error(`No UniProt mapping found for PDB ID ${pdbId}`);
        }

        const uniprotMappings = siftsData[pdbIdLower].UniProt;

        // Step 2: Build chain to UniProt ID mapping
        const chainToUniprot: Map<string, string> = new Map();

        for (const [uniprotId, uniprotData] of Object.entries(
          uniprotMappings
        )) {
          const mappings =
            (uniprotData as { mappings?: Array<{ chain_id: string }> })
              .mappings || [];

          for (const mapping of mappings) {
            const chainId = mapping.chain_id;
            if (chainIds.includes(chainId)) {
              if (!chainToUniprot.has(chainId)) {
                chainToUniprot.set(chainId, uniprotId);
              }
            }
          }
        }

        if (chainToUniprot.size === 0) {
          throw new Error(
            `No UniProt mapping found for chains: ${chainIds.join(", ")}`
          );
        }

        // Step 3: Fetch sequences from UniProt
        const results: Array<{
          chainId: string;
          uniprotId: string | null;
          fasta: string | null;
          error?: string;
        }> = [];

        for (const chainId of chainIds) {
          const uniprotId = chainToUniprot.get(chainId);

          if (!uniprotId) {
            results.push({
              chainId,
              uniprotId: null,
              fasta: null,
              error: "No UniProt mapping found"
            });
            continue;
          }

          try {
            // Fetch FASTA from UniProt
            const uniprotFastaUrl = `https://www.uniprot.org/uniprot/${uniprotId}.fasta`;
            const fastaResponse = await net.fetch(uniprotFastaUrl);

            if (!fastaResponse.ok) {
              throw new Error(
                `Failed to fetch UniProt sequence: ${fastaResponse.statusText}`
              );
            }

            const fastaText = await fastaResponse.text();
            const lines = fastaText.trim().split("\n");

            if (lines.length > 0) {
              const sequence = lines.slice(1).join("");

              // Simple header format: >Chain A, >Chain B, etc.
              const simpleHeader = `>Chain ${chainId}`;

              // Format FASTA (wrap sequence at 60 chars per line)
              const fastaLines = [simpleHeader];
              for (let i = 0; i < sequence.length; i += 60) {
                fastaLines.push(sequence.substring(i, i + 60));
              }

              results.push({
                chainId,
                uniprotId,
                fasta: fastaLines.join("\n")
              });
            } else {
              results.push({
                chainId,
                uniprotId,
                fasta: null,
                error: "No sequence in response"
              });
            }
          } catch (error) {
            results.push({
              chainId,
              uniprotId,
              fasta: null,
              error: error instanceof Error ? error.message : "Unknown error"
            });
          }
        }

        return { success: true, results };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error"
        };
      }
    }
  );

  // Boltz API handlers
  ipcMain.handle("boltz:health-check", async (_event, apiUrl: string) => {
    try {
      const response = await net.fetch(`${apiUrl}/api/v1/health`);
      if (response.ok) {
        const data = await response.json();
        return { success: true, data };
      } else {
        return {
          success: false,
          error: `Server returned: ${response.statusText}`
        };
      }
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error"
      };
    }
  });

  ipcMain.handle(
    "boltz:upload-template",
    async (
      _event,
      apiUrl: string,
      cifContent: string,
      cifFilename: string,
      chainIds: string[],
      customSequences: string
    ) => {
      try {
        // Create multipart/form-data manually (matching Python requests format)
        // Use a simpler boundary format that matches common implementations
        const boundary = `----formdata-${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
        const formDataParts: Buffer[] = [];

        // Add chain_ids field
        formDataParts.push(
          Buffer.from(
            `--${boundary}\r\nContent-Disposition: form-data; name="chain_ids"\r\n\r\n${chainIds.join(",")}\r\n`
          )
        );

        // Add custom_sequences field
        formDataParts.push(
          Buffer.from(
            `--${boundary}\r\nContent-Disposition: form-data; name="custom_sequences"\r\n\r\n${customSequences}\r\n`
          )
        );

        // Add cif_file field
        // cifContent is already a string from readStructureFile
        const cifBuffer = Buffer.from(cifContent, "utf-8");
        formDataParts.push(
          Buffer.from(
            `--${boundary}\r\nContent-Disposition: form-data; name="cif_file"; filename="${cifFilename}"\r\nContent-Type: application/octet-stream\r\n\r\n`
          )
        );
        formDataParts.push(cifBuffer);
        formDataParts.push(Buffer.from(`\r\n--${boundary}--\r\n`));

        const formDataBuffer = Buffer.concat(formDataParts);

        const response = await net.fetch(`${apiUrl}/api/v1/template/upload`, {
          method: "POST",
          headers: {
            "Content-Type": `multipart/form-data; boundary=${boundary}`
          },
          body: formDataBuffer
        });

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(
            `Upload failed: ${response.statusText} - ${errorText}`
          );
        }

        const data = await response.json();
        return { success: true, data };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error"
        };
      }
    }
  );

  ipcMain.handle(
    "boltz:get-job-status",
    async (_event, apiUrl: string, jobId: string) => {
      try {
        const response = await net.fetch(`${apiUrl}/api/v1/jobs/${jobId}`);
        if (!response.ok) {
          throw new Error(`Status check failed: ${response.statusText}`);
        }
        const data = await response.json();
        return { success: true, data };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error"
        };
      }
    }
  );

  ipcMain.handle(
    "boltz:run-prediction",
    async (_event, apiUrl: string, payload: unknown) => {
      try {
        const response = await net.fetch(`${apiUrl}/api/v1/predict/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!response.ok) {
          throw new Error(`Prediction start failed: ${response.statusText}`);
        }

        const data = await response.json();
        return { success: true, data };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error"
        };
      }
    }
  );

  // Read file by absolute path
  ipcMain.handle(
    "project:read-file-by-path",
    async (_event, filePath: string) => {
      try {
        const content = await fs.readFile(filePath, "utf-8");
        return { success: true, content };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error"
        };
      }
    }
  );

  // Download and save prediction results
  ipcMain.handle(
    "boltz:download-and-save-results",
    async (_event, apiUrl: string, jobId: string) => {
      const project = projectManager.getCurrentProject();
      if (!project) {
        return { success: false, error: "No project is currently open" };
      }

      try {
        // Download results from API
        const response = await net.fetch(
          `${apiUrl}/api/v1/jobs/${jobId}/files/prediction`
        );

        if (!response.ok) {
          throw new Error(`Download failed: ${response.statusText}`);
        }

        // Get buffer from response
        const arrayBuffer = await response.arrayBuffer();
        const buffer = Buffer.from(arrayBuffer);

        // Create directories in results folder with run_XXX format
        const projectDir = project.path;
        const resultsDir = join(projectDir, "results");
        await fs.mkdir(resultsDir, { recursive: true });

        // Find next available run number
        const existingRuns = await fs.readdir(resultsDir, {
          withFileTypes: true
        });
        const runNumbers = existingRuns
          .filter(entry => entry.isDirectory() && entry.name.startsWith("run_"))
          .map(entry => {
            const match = entry.name.match(/^run_(\d+)$/);
            return match ? parseInt(match[1], 10) : 0;
          })
          .filter(num => num > 0);
        const nextRunNumber =
          runNumbers.length > 0 ? Math.max(...runNumbers) + 1 : 1;
        const runDir = join(
          resultsDir,
          `run_${String(nextRunNumber).padStart(3, "0")}`
        );
        await fs.mkdir(runDir, { recursive: true });

        // Save ZIP file
        const zipPath = join(runDir, `${jobId}_predictions.zip`);
        await fs.writeFile(zipPath, buffer);

        // Extract ZIP using adm-zip
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const AdmZip = require("adm-zip");
        const zip = new AdmZip(zipPath);
        const extractDir = join(runDir, "predictions");
        zip.extractAllTo(extractDir, true);

        // Find CIF files in extracted directory
        const findCifFiles = async (dir: string): Promise<string[]> => {
          const cifFiles: string[] = [];
          const entries = await fs.readdir(dir, { withFileTypes: true });

          for (const entry of entries) {
            const fullPath = join(dir, entry.name);
            if (entry.isDirectory()) {
              const subFiles = await findCifFiles(fullPath);
              cifFiles.push(...subFiles);
            } else if (
              entry.name.endsWith(".cif") ||
              entry.name.endsWith(".mmcif")
            ) {
              cifFiles.push(fullPath);
            }
          }
          return cifFiles;
        };

        const cifFiles = await findCifFiles(extractDir);

        // Return relative paths from project root for easier access
        const relativeCifFiles = cifFiles.map(file => {
          const relative = file.replace(projectDir + join("", ""), "");
          return relative.startsWith(join("", ""))
            ? relative.slice(1)
            : relative;
        });

        return {
          success: true,
          runId: `run_${String(nextRunNumber).padStart(3, "0")}`,
          runPath: runDir,
          extractDir,
          cifFiles: relativeCifFiles,
          absoluteCifFiles: cifFiles
        };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error"
        };
      }
    }
  );
}
