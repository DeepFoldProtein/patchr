import React from "react";
import { useAtom } from "jotai";
import {
  Monitor,
  Cloud,
  ExternalLink,
  ChevronRight,
  ServerOff
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";
import { apiUrlAtom, apiConnectionStatusAtom } from "../store/api-atoms";
import { logger } from "../lib/logger";

const COLAB_NOTEBOOK_URL =
  "https://colab.research.google.com/github/DeepFoldProtein/patchr/blob/main/colab_server.ipynb";

export function ServerConnection(): React.ReactElement {
  const [apiUrl, setApiUrl] = useAtom(apiUrlAtom);
  const [connectionStatus, setConnectionStatus] = useAtom(
    apiConnectionStatusAtom
  );

  // Auto-detect server on mount
  React.useEffect(() => {
    if (connectionStatus !== "idle") return;

    let cancelled = false;
    const autoDetect = async (): Promise<void> => {
      try {
        if (!window.api?.boltz?.healthCheck) return;
        const result = await window.api.boltz.healthCheck(
          "http://localhost:31212"
        );
        if (cancelled) return;
        if (result.success) {
          setConnectionStatus("connected");
          logger.log("[Auto-detect] Server found at localhost:31212");
        } else {
          logger.log("[Auto-detect] Server not responding");
        }
      } catch {
        if (cancelled) return;
        logger.log("[Auto-detect] Server not found at localhost:31212");
      }
    };

    void autoDetect();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleTestConnection = async (): Promise<void> => {
    const startTime = Date.now();
    logger.log(
      `[Test Connection] Starting health check to ${apiUrl} at ${new Date().toISOString()}`
    );
    setConnectionStatus("testing");

    try {
      if (!window.api?.boltz?.healthCheck) {
        throw new Error("Boltz API not available");
      }

      const abortController = new AbortController();
      const timeoutSignal = abortController.signal;
      let healthCheckCompleted = false;

      const timeoutPromise = new Promise<never>((_, reject) => {
        const checkTimeout = (): void => {
          if (timeoutSignal.aborted) return;
          const elapsed = Date.now() - startTime;
          if (elapsed >= 5000) {
            if (!healthCheckCompleted) {
              logger.log(`[Test Connection] Timeout fired after ${elapsed}ms`);
              abortController.abort();
              reject(new Error("Connection timeout (5s)"));
            }
          } else {
            requestAnimationFrame(checkTimeout);
          }
        };
        requestAnimationFrame(checkTimeout);
      });

      const healthCheckPromise = window.api.boltz.healthCheck(apiUrl).then(
        result => {
          healthCheckCompleted = true;
          if (!timeoutSignal.aborted) abortController.abort();
          return result;
        },
        error => {
          healthCheckCompleted = true;
          if (!timeoutSignal.aborted) abortController.abort();
          throw error;
        }
      );

      const result = await Promise.race([healthCheckPromise, timeoutPromise]);

      if (result.success) {
        logger.log(`[Test Connection] Connection successful`);
        setConnectionStatus("connected");
      } else {
        logger.log(`[Test Connection] Connection failed: ${result.error}`);
        setConnectionStatus("error");
      }
    } catch (err) {
      const totalElapsed = Date.now() - startTime;
      logger.log(`[Test Connection] Exception after ${totalElapsed}ms:`, err);
      setConnectionStatus("error");
    }
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <label className="text-xs font-medium">API Server URL</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={apiUrl}
            onChange={e => setApiUrl(e.target.value)}
            placeholder="http://localhost:31212"
            className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-xs"
          />
          <button
            onClick={() => void handleTestConnection()}
            disabled={connectionStatus === "testing"}
            className={`rounded-md px-3 py-2 text-xs font-medium ${
              connectionStatus === "connected"
                ? "bg-green-600 text-white"
                : connectionStatus === "error"
                  ? "bg-red-600 text-white hover:bg-red-700"
                  : "bg-primary text-primary-foreground hover:bg-primary/90"
            } disabled:opacity-50`}
          >
            {connectionStatus === "testing"
              ? "Testing..."
              : connectionStatus === "connected"
                ? "Connected"
                : connectionStatus === "error"
                  ? "Try Again"
                  : "Connect"}
          </button>
        </div>
      </div>

      {/* Always show setup guide when not connected */}
      {connectionStatus !== "connected" && (
        <ServerSetupGuide onUrlChange={url => setApiUrl(url)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function ServerSetupGuide({
  onUrlChange
}: {
  onUrlChange: (url: string) => void;
}): React.ReactElement {
  const [colabUrl, setColabUrl] = React.useState("");

  const handleColabUrlApply = (): void => {
    const trimmed = colabUrl.trim().replace(/\/+$/, "");
    if (trimmed) onUrlChange(trimmed);
  };

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
      <div className="flex items-center px-3 py-2 bg-amber-500/10 border-b border-amber-500/20">
        <div className="flex items-center gap-1.5">
          <ServerOff className="h-3.5 w-3.5 text-amber-500" />
          <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
            Server not detected
          </span>
        </div>
      </div>

      <Tabs defaultValue="colab">
        <TabsList className="w-full rounded-none border-b border-neutral-200/50 dark:border-neutral-800/50 bg-transparent p-0 h-auto">
          <TabsTrigger
            value="colab"
            className="flex-1 gap-1.5 rounded-none border-b-2 border-transparent py-2 text-xs data-[state=active]:border-neutral-500 data-[state=active]:text-neutral-700 dark:data-[state=active]:text-neutral-300 data-[state=active]:shadow-none"
          >
            <Cloud className="h-3 w-3" />
            Google Colab
          </TabsTrigger>
          <TabsTrigger
            value="local"
            className="flex-1 gap-1.5 rounded-none border-b-2 border-transparent py-2 text-xs data-[state=active]:border-neutral-500 data-[state=active]:text-neutral-700 dark:data-[state=active]:text-neutral-300 data-[state=active]:shadow-none"
          >
            <Monitor className="h-3 w-3" />
            Local Setup
          </TabsTrigger>
        </TabsList>

        <TabsContent value="colab" className="mt-0 p-3">
          <div className="space-y-2.5">
            <p className="text-xs text-neutral-600 dark:text-neutral-400">
              Use a free GPU on Google Colab:
            </p>
            <div className="rounded px-2 py-1.5 bg-orange-500/10 border border-orange-500/20">
              <p className="text-[10px] text-orange-600 dark:text-orange-400">
                Large targets may fail on Colab free tier due to limited GPU
                memory (T4 15GB). For large complexes, use Local Setup or Colab
                Pro.
              </p>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-500/20 text-[10px] font-bold text-neutral-500">
                  1
                </span>
                <div className="text-xs text-neutral-600 dark:text-neutral-400">
                  <span className="font-medium text-neutral-700 dark:text-neutral-300">
                    Open the Colab notebook
                  </span>
                  <button
                    onClick={() => window.open(COLAB_NOTEBOOK_URL, "_blank")}
                    className="flex items-center gap-1 mt-1 px-2 py-1 rounded bg-amber-500/10 border border-amber-500/20 text-[10px] font-medium text-amber-600 dark:text-amber-400 hover:bg-amber-500/20 transition-colors"
                  >
                    Open in Colab
                    <ExternalLink className="h-2.5 w-2.5" />
                  </button>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-500/20 text-[10px] font-bold text-neutral-500">
                  2
                </span>
                <p className="text-xs text-neutral-600 dark:text-neutral-400">
                  <span className="font-medium text-neutral-700 dark:text-neutral-300">
                    Run all cells
                  </span>{" "}
                  and copy the public URL
                </p>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-500/20 text-[10px] font-bold text-neutral-500">
                  3
                </span>
                <div className="flex-1 text-xs text-neutral-600 dark:text-neutral-400">
                  <span className="font-medium text-neutral-700 dark:text-neutral-300">
                    Paste the URL here
                  </span>
                  <div className="flex gap-1.5 mt-1">
                    <input
                      type="text"
                      value={colabUrl}
                      onChange={e => setColabUrl(e.target.value)}
                      placeholder="https://xxx.trycloudflare.com"
                      className="flex-1 rounded border border-input bg-background px-2 py-1 text-[10px] font-mono"
                      onKeyDown={e => {
                        if (e.key === "Enter") handleColabUrlApply();
                      }}
                    />
                    <button
                      onClick={handleColabUrlApply}
                      disabled={!colabUrl.trim()}
                      className="rounded bg-neutral-600 px-2 py-1 text-[10px] font-medium text-white hover:bg-neutral-700 disabled:opacity-40 transition-colors flex items-center gap-0.5"
                    >
                      Apply
                      <ChevronRight className="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="local" className="mt-0 p-3">
          <div className="space-y-2.5">
            <p className="text-xs text-neutral-600 dark:text-neutral-400">
              Run the PATCHR server locally (requires GPU):
            </p>
            <div className="space-y-1.5">
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-500/20 text-[10px] font-bold text-neutral-500">
                  1
                </span>
                <div className="text-xs text-neutral-600 dark:text-neutral-400">
                  <span className="font-medium text-neutral-700 dark:text-neutral-300">
                    Clone &amp; install
                  </span>
                  <code className="block mt-1 px-2 py-1 rounded bg-neutral-100 dark:bg-neutral-800/80 text-[10px] font-mono text-neutral-700 dark:text-neutral-300 select-all whitespace-pre-wrap">
                    {`git clone https://github.com/DeepFoldProtein/patchr.git\ncd patchr && pip install -e .`}
                  </code>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-500/20 text-[10px] font-bold text-neutral-500">
                  2
                </span>
                <div className="text-xs text-neutral-600 dark:text-neutral-400">
                  <span className="font-medium text-neutral-700 dark:text-neutral-300">
                    Start the server
                  </span>
                  <code className="block mt-1 px-2 py-1 rounded bg-neutral-100 dark:bg-neutral-800/80 text-[10px] font-mono text-neutral-700 dark:text-neutral-300 select-all">
                    patchr serve --model boltz2
                  </code>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 mt-0.5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-500/20 text-[10px] font-bold text-neutral-500">
                  3
                </span>
                <p className="text-xs text-neutral-600 dark:text-neutral-400">
                  <span className="font-medium text-neutral-700 dark:text-neutral-300">
                    Click &quot;Connect&quot;
                  </span>{" "}
                  above with the default URL
                </p>
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
