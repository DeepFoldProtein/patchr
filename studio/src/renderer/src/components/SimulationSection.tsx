import React from "react";
import { useAtom, useAtomValue } from "jotai";
import { Button } from "./ui/button";
import {
  apiUrlAtom,
  apiConnectionStatusAtom,
  panelModeAtom
} from "../store/api-atoms";
import { DisconnectedHint } from "./DisconnectedHint";
import { bus } from "../lib/event-bus";

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
  { value: "tip4pew", label: "TIP4P-Ew" }
] as const;

const LIPID_TYPES = [
  { value: "POPC", label: "POPC" },
  { value: "POPE", label: "POPE" },
  { value: "DLPC", label: "DLPC" },
  { value: "DLPE", label: "DLPE" },
  { value: "DMPC", label: "DMPC" },
  { value: "DOPC", label: "DOPC" },
  { value: "DPPC", label: "DPPC" }
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

type SectionId = "source" | "sim-ready" | "membrane";

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
    <div className="border-b border-slate-200/50 dark:border-slate-800/50">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3.5 text-left hover:bg-slate-100/50 dark:hover:bg-slate-800/30 transition-all group"
      >
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
          {title}
        </h3>
        <span className="text-slate-500 dark:text-slate-500 group-hover:text-slate-700 dark:group-hover:text-slate-400 transition-colors">
          {expanded ? "\u25BC" : "\u25B6"}
        </span>
      </button>
      {expanded && (
        <div className="px-4 py-4 bg-slate-50/50 dark:bg-slate-900/20">
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function SimulationSection({
  results
}: {
  results: RunResult[];
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

  // --- Membrane parameters ---------------------------------------------------
  const [lipidType, setLipidType] = React.useState<string>("POPC");
  const [opmPdbId, setOpmPdbId] = React.useState<string>("");
  const [opmInfo, setOpmInfo] = React.useState<{
    thickness: number;
    tilt_angle: number;
    type: string;
  } | null>(null);
  const [opmLoading, setOpmLoading] = React.useState(false);
  const [opmError, setOpmError] = React.useState<string | null>(null);

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

  // --- Membrane job state ----------------------------------------------------
  const [memJobId, setMemJobId] = React.useState<string | null>(null);
  const [memJobStatus, setMemJobStatus] = React.useState<string>("idle");
  const [memProgress, setMemProgress] = React.useState<string | null>(null);
  const [memError, setMemError] = React.useState<string | null>(null);
  const [memResult, setMemResult] = React.useState<Record<
    string,
    unknown
  > | null>(null);
  const [memSavedDir, setMemSavedDir] = React.useState<string | null>(null);

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

  const handleOpmLookup = React.useCallback(async () => {
    if (!opmPdbId.trim() || opmPdbId.trim().length !== 4) return;
    setOpmLoading(true);
    setOpmError(null);
    setOpmInfo(null);
    try {
      const result = await window.api.boltz.opmLookup(
        apiUrl,
        opmPdbId.trim().toUpperCase()
      );
      if (result.success && result.data) {
        setOpmInfo(
          result.data as { thickness: number; tilt_angle: number; type: string }
        );
      } else {
        setOpmError(result.error || "No OPM data found");
      }
    } catch (err) {
      setOpmError(err instanceof Error ? err.message : "OPM lookup failed");
    } finally {
      setOpmLoading(false);
    }
  }, [opmPdbId, apiUrl]);

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

  const downloadAndView = React.useCallback(
    async (jobId: string, simType: "sim" | "membrane") => {
      const dlResult = await window.api.boltz.downloadAndSaveSimResults(
        apiUrl,
        jobId,
        simType
      );
      if (!dlResult.success) {
        throw new Error(dlResult.error || "Download failed");
      }
      if (dlResult.systemPdbContent && dlResult.systemPdbPath) {
        bus.emit("simulation:load-system", {
          filePath: dlResult.systemPdbPath,
          fileContent: dlResult.systemPdbContent,
          label: dlResult.simId || simType
        });
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
          const dl = await downloadAndView(jobId, "sim");
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
    downloadAndView
  ]);

  const handleMembrane = React.useCallback(async () => {
    if (!selectedCif) return;
    setMemError(null);
    setMemResult(null);
    setMemSavedDir(null);
    setMemJobStatus("submitting");
    setMemProgress(null);
    try {
      const cifContent = await readCifContent(selectedCif);
      const cifFilename = selectedCif.split("/").pop() || "input.cif";
      const payload: Record<string, unknown> = {
        cif_content: cifContent,
        cif_filename: cifFilename,
        lipid_type: lipidType,
        engine,
        forcefield,
        water_model: waterModel,
        ph,
        padding,
        ion_concentration: ionConcentration,
        skip_opm: !opmPdbId.trim()
      };
      if (opmPdbId.trim()) {
        payload.pdb_id = opmPdbId.trim().toUpperCase();
      }
      const result = await window.api.boltz.membrane(apiUrl, payload);
      if (!result.success || !result.data) {
        throw new Error(result.error || "Membrane request failed");
      }
      const jobId = result.data.job_id;
      setMemJobId(jobId);
      setMemJobStatus("running");
      await pollJobStatus(
        jobId,
        setMemJobStatus,
        setMemProgress,
        setMemError,
        setMemResult
      );
      if (jobId) {
        try {
          setMemProgress("Downloading files...");
          const dl = await downloadAndView(jobId, "membrane");
          setMemSavedDir(dl.simDir || null);
        } catch (dlErr) {
          console.warn("Auto-download failed:", dlErr);
        }
      }
    } catch (err) {
      setMemJobStatus("failed");
      setMemError(err instanceof Error ? err.message : "Unknown error");
    }
  }, [
    selectedCif,
    readCifContent,
    lipidType,
    engine,
    forcefield,
    waterModel,
    ph,
    padding,
    ionConcentration,
    opmPdbId,
    apiUrl,
    pollJobStatus,
    downloadAndView
  ]);

  const isSimBusy = simJobStatus === "submitting" || simJobStatus === "running";
  const isMemBusy = memJobStatus === "submitting" || memJobStatus === "running";
  const isDisconnected = connectionStatus !== "connected";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* ── Source Structure ── */}
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
            <select
              value={selectedRunIdx}
              onChange={e => {
                setSelectedRunIdx(Number(e.target.value));
                setSelectedCifIdx(0);
              }}
              className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              disabled={results.length === 0}
            >
              {results.length === 0 ? (
                <option value={-1}>No runs available</option>
              ) : (
                results.map((r, idx) => (
                  <option key={r.runId} value={idx}>
                    {r.runId} ({r.cifFiles.length} file
                    {r.cifFiles.length !== 1 ? "s" : ""})
                  </option>
                ))
              )}
            </select>
          </div>
          {selectedRunCifs.length > 0 && (
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                CIF File
              </label>
              <select
                value={selectedCifIdx}
                onChange={e => setSelectedCifIdx(Number(e.target.value))}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs font-mono"
              >
                {selectedRunCifs.map((cif, idx) => (
                  <option key={cif} value={idx}>
                    {cif.split("/").pop()}
                  </option>
                ))}
              </select>
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

      {/* ── Simulation-Ready Preparation ── */}
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
              <select
                value={engine}
                onChange={e => setEngine(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              >
                {ENGINES.map(e => (
                  <option key={e.value} value={e.value}>
                    {e.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Force Field
              </label>
              <select
                value={forcefield}
                onChange={e => setForcefield(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              >
                {FORCEFIELDS.map(f => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Water Model
              </label>
              <select
                value={waterModel}
                onChange={e => setWaterModel(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              >
                {WATER_MODELS.map(w => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </select>
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
            <input
              type="checkbox"
              id="keep-water"
              checked={keepWater}
              onChange={e => setKeepWater(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-gray-300 text-primary focus:ring-primary"
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
            />
          )}
        </div>
      </Section>

      {/* ── Membrane Embedding ── */}
      <Section
        title="Membrane Embedding"
        expanded={expandedSections.has("membrane")}
        onToggle={() => toggleSection("membrane")}
      >
        <div className="space-y-3">
          <p className="text-[10px] text-muted-foreground">
            Embed the protein in a lipid bilayer membrane for MD simulation.
          </p>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                Lipid Type
              </label>
              <select
                value={lipidType}
                onChange={e => setLipidType(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
              >
                {LIPID_TYPES.map(l => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-medium text-muted-foreground">
                OPM PDB ID
              </label>
              <div className="flex gap-1">
                <input
                  type="text"
                  value={opmPdbId}
                  onChange={e => setOpmPdbId(e.target.value.toUpperCase())}
                  placeholder="e.g. 1OCC"
                  maxLength={4}
                  className="flex-1 rounded-md border border-input bg-background px-2 py-1.5 text-xs uppercase font-mono"
                />
                <Button
                  onClick={handleOpmLookup}
                  disabled={opmLoading || opmPdbId.trim().length !== 4}
                  variant="outline"
                  size="sm"
                  className="h-7 text-[10px] px-2"
                >
                  {opmLoading ? "..." : "Lookup"}
                </Button>
              </div>
            </div>
          </div>

          {opmInfo && (
            <div className="rounded-md border border-blue-500/30 bg-blue-500/5 p-2 text-xs text-muted-foreground">
              <div className="font-medium text-blue-600 dark:text-blue-400 mb-1">
                OPM Data Found
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                <span>Thickness:</span>
                <span className="font-mono">
                  {opmInfo.thickness.toFixed(1)} A
                </span>
                <span>Tilt angle:</span>
                <span className="font-mono">
                  {opmInfo.tilt_angle.toFixed(1)} deg
                </span>
                <span>Type:</span>
                <span>{opmInfo.type}</span>
              </div>
            </div>
          )}

          {opmError && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2">
              <p className="text-[10px] text-amber-600 dark:text-amber-400">
                {opmError}
              </p>
            </div>
          )}

          <Button
            onClick={handleMembrane}
            disabled={isDisconnected || !selectedCif || isMemBusy}
            variant="outline"
            className="w-full"
          >
            {isMemBusy ? "Building..." : "Build Membrane System"}
          </Button>
          {isDisconnected && <DisconnectedHint />}

          <JobStatusCard
            jobId={memJobId}
            status={memJobStatus}
            progress={memProgress}
            error={memError}
            label="Membrane"
          />

          {memResult && (
            <SimResultCard
              title="Membrane System Ready"
              result={memResult}
              savedDir={memSavedDir}
            />
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
  savedDir
}: {
  title: string;
  result: Record<string, unknown>;
  savedDir: string | null;
}): React.ReactElement {
  const handleOpenFolder = React.useCallback(() => {
    if (savedDir) {
      void window.api.project.openFolder(savedDir);
    }
  }, [savedDir]);

  return (
    <div className="rounded-md border border-green-500/30 bg-green-500/5 p-3 space-y-2">
      <div className="text-xs font-semibold text-green-600 dark:text-green-400">
        {title}
      </div>
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
        <div className="mt-2">
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
                  {typeof val === "string" ? val.split("/").pop() : String(val)}
                </div>
              )
            )}
          </div>
        </div>
      )}

      {savedDir && (
        <div className="mt-2 flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground font-mono truncate flex-1 mr-2">
            {savedDir.split("/").slice(-2).join("/")}
          </p>
          <Button
            onClick={handleOpenFolder}
            variant="outline"
            size="sm"
            className="h-6 text-[10px] px-2 shrink-0"
          >
            Open Folder
          </Button>
        </div>
      )}
    </div>
  );
}
