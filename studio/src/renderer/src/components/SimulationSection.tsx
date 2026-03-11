import React from "react";
import { useAtom, useAtomValue } from "jotai";
import { Button } from "./ui/button";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem
} from "./ui/select";
import { Switch } from "./ui/switch";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent
} from "./ui/collapsible";
import { apiUrlAtom, apiConnectionStatusAtom } from "../store/api-atoms";
import { DisconnectedHint } from "./DisconnectedHint";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ENGINES = [
  { value: "gromacs", label: "GROMACS" },
  { value: "amber", label: "Amber" },
  { value: "openmm", label: "OpenMM" }
] as const;

const FORCEFIELDS = [
  { value: "charmm36m", label: "CHARMM36m" },
  { value: "charmm36", label: "CHARMM36" },
  { value: "amber14sb", label: "Amber14SB" },
  { value: "amber99sbildn", label: "Amber99SB-ILDN" },
  { value: "amber19sb", label: "Amber19SB" }
] as const;

const WATER_MODELS = [
  { value: "tip3p", label: "TIP3P" },
  { value: "tip3pfb", label: "TIP3P-FB" },
  { value: "spce", label: "SPC/E" },
  { value: "tip4pew", label: "TIP4P-Ew" },
  { value: "tip5p", label: "TIP5P" }
] as const;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RunResult {
  runId: string;
  runPath: string;
  predictionsPath: string;
  cifFiles: string[];
}

export interface SavedSimulation {
  id: string;
  path: string;
  files: string[];
  engine?: string;
  forcefield?: string;
  n_atoms?: number;
  n_waters?: number;
  box_size?: number[];
}

type SectionId = "source" | "sim-ready";

// ---------------------------------------------------------------------------
// Collapsible Section
// ---------------------------------------------------------------------------

function Section({
  title,
  expanded,
  onToggle,
  children
}: {
  title: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <Collapsible open={expanded} onOpenChange={() => onToggle()}>
      <CollapsibleTrigger>{title}</CollapsibleTrigger>
      <CollapsibleContent className="px-4 pb-4">{children}</CollapsibleContent>
    </Collapsible>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function SimulationSection({
  results,
  savedSims
}: {
  results: RunResult[];
  savedSims: SavedSimulation[];
}): React.ReactElement {
  const apiUrl = useAtomValue(apiUrlAtom);
  const [connectionStatus] = useAtom(apiConnectionStatusAtom);

  // --- Section toggle --------------------------------------------------------
  const [expandedSections, setExpandedSections] = React.useState<
    Set<SectionId>
  >(new Set(["source", "sim-ready"]));

  const toggleSection = React.useCallback((id: SectionId) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // --- Sim-ready parameters --------------------------------------------------
  const [engine, setEngine] = React.useState<string>("gromacs");
  const [forcefield, setForcefield] = React.useState<string>("charmm36m");
  const [waterModel, setWaterModel] = React.useState<string>("tip3p");
  const [ph, setPh] = React.useState<number>(7.0);
  const [padding, setPadding] = React.useState<number>(1.0);
  const [ionConcentration, setIonConcentration] = React.useState<number>(0.15);
  const [keepWater, setKeepWater] = React.useState<boolean>(false);

  // --- Sim-ready job state ---------------------------------------------------
  const [simJobId, setSimJobId] = React.useState<string | null>(null);
  const [simJobStatus, setSimJobStatus] = React.useState<string>("idle");
  const [simProgress, setSimProgress] = React.useState<string | null>(null);
  const [simError, setSimError] = React.useState<string | null>(null);
  const [simResult, setSimResult] = React.useState<Record<
    string,
    unknown
  > | null>(null);
  const [simSavedDir, setSimSavedDir] = React.useState<string | null>(null);
  // --- Run & CIF selection ---------------------------------------------------
  const [selectedRunIdx, setSelectedRunIdx] = React.useState<number>(-1);
  const [selectedCifIdx, setSelectedCifIdx] = React.useState<number>(0);

  React.useEffect(() => {
    if (results.length > 0) {
      setSelectedRunIdx(results.length - 1);
      setSelectedCifIdx(0);
    } else {
      setSelectedRunIdx(-1);
      setSelectedCifIdx(0);
    }
  }, [results.length]);

  const selectedRunCifs = React.useMemo(() => {
    if (selectedRunIdx < 0 || selectedRunIdx >= results.length) return [];
    const run = results[selectedRunIdx];
    return [...run.cifFiles].sort((a, b) => {
      const aModel =
        a.toLowerCase().includes("model") &&
        !a.toLowerCase().includes("template");
      const bModel =
        b.toLowerCase().includes("model") &&
        !b.toLowerCase().includes("template");
      if (aModel && !bModel) return -1;
      if (!aModel && bModel) return 1;
      return 0;
    });
  }, [results, selectedRunIdx]);

  const selectedCif = React.useMemo(() => {
    if (selectedRunCifs.length === 0) return null;
    const idx = Math.min(selectedCifIdx, selectedRunCifs.length - 1);
    return selectedRunCifs[idx] || null;
  }, [selectedRunCifs, selectedCifIdx]);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  const readCifContent = React.useCallback(
    async (cifPath: string): Promise<string> => {
      const readResult = await window.api.project.readFileByPath(cifPath);
      if (!readResult.success || !readResult.content) {
        throw new Error(
          `Failed to read CIF file: ${readResult.error || cifPath}`
        );
      }
      return readResult.content;
    },
    []
  );

  const pollJobStatus = React.useCallback(
    async (
      jobId: string,
      setStatus: (s: string) => void,
      setProgressFn: (s: string | null) => void,
      setErrorFn: (s: string | null) => void,
      setResultFn: (r: Record<string, unknown> | null) => void
    ) => {
      const poll = async (): Promise<void> => {
        try {
          const statusResult = await window.api.boltz.getJobStatus(
            apiUrl,
            jobId
          );
          if (!statusResult.success || !statusResult.data) {
            setStatus("failed");
            setErrorFn(statusResult.error || "Status check failed");
            return;
          }
          const status = statusResult.data;
          if (typeof status.progress === "string") {
            setProgressFn(status.progress);
          }
          if (status.status === "completed") {
            setStatus("completed");
            setProgressFn("Completed");
            try {
              const simResResult = await window.api.boltz.simResult(
                apiUrl,
                jobId
              );
              if (simResResult.success && simResResult.data) {
                setResultFn(simResResult.data as Record<string, unknown>);
              }
            } catch {
              /* optional */
            }
            return;
          } else if (status.status === "failed") {
            setStatus("failed");
            setErrorFn(status.error || "Job failed");
            return;
          }
          await new Promise(resolve => {
            let frames = 0;
            const maxFrames = 180;
            const checkFrame = (): void => {
              frames++;
              if (frames >= maxFrames) resolve(undefined);
              else requestAnimationFrame(checkFrame);
            };
            requestAnimationFrame(checkFrame);
          });
          await poll();
        } catch (err) {
          setStatus("failed");
          setErrorFn(err instanceof Error ? err.message : "Polling failed");
        }
      };
      await poll();
    },
    [apiUrl]
  );

  const downloadResults = React.useCallback(
    async (jobId: string) => {
      const dlResult = await window.api.boltz.downloadAndSaveSimResults(
        apiUrl,
        jobId
      );
      if (!dlResult.success) {
        throw new Error(dlResult.error || "Download failed");
      }
      return dlResult;
    },
    [apiUrl]
  );

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleSimReady = React.useCallback(async () => {
    if (!selectedCif) return;
    setSimError(null);
    setSimResult(null);
    setSimSavedDir(null);
    setSimJobStatus("submitting");
    setSimProgress(null);
    try {
      const cifContent = await readCifContent(selectedCif);
      const cifFilename = selectedCif.split("/").pop() || "input.cif";
      const payload = {
        cif_content: cifContent,
        cif_filename: cifFilename,
        engine,
        forcefield,
        water_model: waterModel,
        ph,
        padding,
        ion_concentration: ionConcentration,
        keep_water: keepWater
      };
      const result = await window.api.boltz.simReady(apiUrl, payload);
      if (!result.success || !result.data) {
        throw new Error(result.error || "Sim-ready request failed");
      }
      const jobId = result.data.job_id;
      setSimJobId(jobId);
      setSimJobStatus("running");
      await pollJobStatus(
        jobId,
        setSimJobStatus,
        setSimProgress,
        setSimError,
        setSimResult
      );
      if (jobId) {
        try {
          setSimProgress("Downloading files...");
          const dl = await downloadResults(jobId);
          setSimSavedDir(dl.simDir || null);
        } catch (dlErr) {
          console.warn("Auto-download failed:", dlErr);
        }
      }
    } catch (err) {
      setSimJobStatus("failed");
      setSimError(err instanceof Error ? err.message : "Unknown error");
    }
  }, [
    selectedCif,
    readCifContent,
    engine,
    forcefield,
    waterModel,
    ph,
    padding,
    ionConcentration,
    keepWater,
    apiUrl,
    pollJobStatus,
    downloadResults
  ]);

  const isSimBusy = simJobStatus === "submitting" || simJobStatus === "running";
  const isDisconnected = connectionStatus !== "connected";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full min-h-0 overflow-auto">
      {/* -- Source Structure -- */}
      <Section
        title="Source Structure"
        expanded={expandedSections.has("source")}
        onToggle={() => toggleSection("source")}
      >
        <div className="space-y-2">
          <div className="space-y-1">
            <label className="text-[10px] font-medium text-muted-foreground">
              Prediction Run
            </label>
            <Select
              value={String(selectedRunIdx)}
              onValueChange={v => {
                setSelectedRunIdx(Number(v));
                setSelectedCifIdx(0);
              }}
              disabled={results.length === 0}
            >
              <SelectTrigger>
                <SelectValue placeholder="No runs available" />
              </SelectTrigger>
              <SelectContent>
                {results.length === 0 ? (
                  <SelectItem value="-1">No runs available</SelectItem>
                ) : (
                  results.map((r, idx) => (
                    <SelectItem key={r.runId} value={String(idx)}>
                      {r.runId} ({r.cifFiles.length} file
                      {r.cifFiles.length !== 1 ? "s" : ""})
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>
          {selectedRunCifs.length > 0 && (
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                CIF File
              </label>
              <Select
                value={String(selectedCifIdx)}
                onValueChange={v => setSelectedCifIdx(Number(v))}
              >
                <SelectTrigger className="font-mono">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {selectedRunCifs.map((cif, idx) => (
                    <SelectItem key={cif} value={String(idx)}>
                      {cif.split("/").pop()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {selectedCif && (
            <p
              className="text-[10px] text-muted-foreground font-mono truncate"
              title={selectedCif}
            >
              {selectedCif}
            </p>
          )}
        </div>
      </Section>

      {/* -- Simulation-Ready Preparation -- */}
      <Section
        title="Simulation-Ready Preparation"
        expanded={expandedSections.has("sim-ready")}
        onToggle={() => toggleSection("sim-ready")}
      >
        <div className="space-y-3">
          {/* Parameters grid */}
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Engine
              </label>
              <Select value={engine} onValueChange={setEngine}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ENGINES.map(e => (
                    <SelectItem key={e.value} value={e.value}>
                      {e.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Force Field
              </label>
              <Select value={forcefield} onValueChange={setForcefield}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FORCEFIELDS.map(f => (
                    <SelectItem key={f.value} value={f.value}>
                      {f.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Water Model
              </label>
              <Select value={waterModel} onValueChange={setWaterModel}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WATER_MODELS.map(w => (
                    <SelectItem key={w.value} value={w.value}>
                      {w.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                pH
              </label>
              <input
                type="number"
                value={ph}
                onChange={e => setPh(parseFloat(e.target.value) || 7.0)}
                step={0.5}
                min={0}
                max={14}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Box Padding (nm)
              </label>
              <input
                type="number"
                value={padding}
                onChange={e => setPadding(parseFloat(e.target.value) || 1.0)}
                step={0.1}
                min={0.5}
                max={5.0}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Ion Conc. (mol/L)
              </label>
              <input
                type="number"
                value={ionConcentration}
                onChange={e =>
                  setIonConcentration(parseFloat(e.target.value) || 0.15)
                }
                step={0.01}
                min={0}
                max={2.0}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              id="keep-water"
              checked={keepWater}
              onCheckedChange={setKeepWater}
            />
            <label htmlFor="keep-water" className="text-xs cursor-pointer">
              Keep crystallographic waters
            </label>
          </div>

          <Button
            onClick={handleSimReady}
            disabled={isDisconnected || !selectedCif || isSimBusy}
            className="w-full"
          >
            {isSimBusy ? "Preparing..." : "Prepare Simulation Files"}
          </Button>
          {isDisconnected && <DisconnectedHint />}

          <JobStatusCard
            jobId={simJobId}
            status={simJobStatus}
            progress={simProgress}
            error={simError}
            label="Sim-Ready"
          />

          {simResult && (
            <SimResultCard
              title="Simulation Files Ready"
              result={simResult}
              savedDir={simSavedDir}
              defaultExpanded
            />
          )}

          {savedSims.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[10px] font-medium text-muted-foreground">
                Saved Runs ({savedSims.length})
              </div>
              {[...savedSims].reverse().map(sim => (
                <SimResultCard
                  key={sim.id}
                  title={sim.id}
                  result={{
                    engine: sim.engine,
                    forcefield: sim.forcefield,
                    n_atoms: sim.n_atoms,
                    n_waters: sim.n_waters,
                    box_size: sim.box_size,
                    files: Object.fromEntries(sim.files.map(f => [f, f]))
                  }}
                  savedDir={sim.path}
                />
              ))}
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Job Status Card (shared)
// ---------------------------------------------------------------------------

function JobStatusCard({
  jobId,
  status,
  progress,
  error,
  label
}: {
  jobId: string | null;
  status: string;
  progress: string | null;
  error: string | null;
  label: string;
}): React.ReactElement | null {
  if (status === "idle") return null;

  return (
    <>
      <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
        <div className="flex justify-between text-xs">
          <span className="font-medium">{label} Status:</span>
          <span
            className={
              status === "completed"
                ? "text-green-500"
                : status === "failed"
                  ? "text-red-500"
                  : "text-muted-foreground"
            }
          >
            {status === "submitting"
              ? "Submitting..."
              : status === "running"
                ? "Running..."
                : status === "completed"
                  ? "Completed"
                  : status === "failed"
                    ? "Failed"
                    : status}
          </span>
        </div>
        {jobId && (
          <div className="text-[10px] text-muted-foreground font-mono truncate">
            Job: {jobId}
          </div>
        )}
        {progress && status === "running" && (
          <div className="text-xs text-muted-foreground">{progress}</div>
        )}
      </div>
      {error && (
        <div className="rounded-md border border-red-500/50 bg-red-500/10 p-3">
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Result Card
// ---------------------------------------------------------------------------

function SimResultCard({
  title,
  result,
  savedDir,
  defaultExpanded = false
}: {
  title: string;
  result: Record<string, unknown>;
  savedDir: string | null;
  defaultExpanded?: boolean;
}): React.ReactElement {
  const [expanded, setExpanded] = React.useState(defaultExpanded);

  const handleOpenFolder = React.useCallback(() => {
    if (savedDir) {
      void window.api.project.openFolder(savedDir);
    }
  }, [savedDir]);

  // Summary line
  const summary = React.useMemo(() => {
    const parts: string[] = [];
    if (result.engine) parts.push(String(result.engine));
    if (result.forcefield) parts.push(String(result.forcefield));
    if (result.n_waters !== undefined)
      parts.push(`${String(result.n_waters)} waters`);
    return parts.join(" · ");
  }, [result]);

  return (
    <div className="rounded-md border border-green-500/30 bg-green-500/5 overflow-hidden">
      {/* Header -- always visible, clickable to toggle */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-green-500/10 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] text-green-600 dark:text-green-400">
            {expanded ? "▼" : "▶"}
          </span>
          <span className="text-xs font-semibold text-green-600 dark:text-green-400 truncate">
            {title}
          </span>
          {!expanded && summary && (
            <span className="text-[10px] text-muted-foreground truncate">
              {summary}
            </span>
          )}
        </div>
        {savedDir && (
          <span
            onClick={e => {
              e.stopPropagation();
              handleOpenFolder();
            }}
            className="shrink-0 ml-2 text-[10px] font-medium text-blue-500 hover:text-blue-400 cursor-pointer"
          >
            Open Folder
          </span>
        )}
      </button>

      {/* Detail -- shown when expanded */}
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {result.n_atoms !== undefined && (
              <>
                <span>Atom count:</span>
                <span className="font-mono">{String(result.n_atoms)}</span>
              </>
            )}
            {!!result.box_size && Array.isArray(result.box_size) && (
              <>
                <span>Box size:</span>
                <span className="font-mono">
                  {(result.box_size as number[])
                    .map(v => (typeof v === "number" ? v.toFixed(2) : v))
                    .join(" x ")}{" "}
                  nm
                </span>
              </>
            )}
            {result.n_waters !== undefined && (
              <>
                <span>Waters:</span>
                <span className="font-mono">{String(result.n_waters)}</span>
              </>
            )}
            {!!result.engine && (
              <>
                <span>Engine:</span>
                <span className="font-mono">{String(result.engine)}</span>
              </>
            )}
            {!!result.forcefield && (
              <>
                <span>Force field:</span>
                <span className="font-mono">{String(result.forcefield)}</span>
              </>
            )}
          </div>

          {!!result.files && typeof result.files === "object" && (
            <div>
              <div className="text-[10px] font-medium text-muted-foreground mb-1">
                Output files:
              </div>
              <div className="space-y-0.5">
                {Object.entries(result.files as Record<string, string>).map(
                  ([key, val]) => (
                    <div
                      key={key}
                      className="text-[10px] font-mono text-muted-foreground truncate"
                    >
                      {typeof val === "string"
                        ? val.split("/").pop()
                        : String(val)}
                    </div>
                  )
                )}
              </div>
            </div>
          )}

          {savedDir && (
            <p className="text-[10px] text-muted-foreground font-mono truncate">
              {savedDir.split("/").slice(-2).join("/")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
