// Shared updater state, subscribed to the main-process electron-updater events.
//
// Both the status bar (UpdateStatus) and the welcome screen render update
// affordances, so the state machine lives here rather than in either component.
// The preload bridge registers one ipcRenderer listener per subscriber and
// hands back an unsubscribe, so several components can listen at once and stay
// in sync — every one of them sees the same events.
import { useCallback, useEffect, useRef, useState } from "react";

export type UpdaterState =
  | { type: "idle" }
  | { type: "checking" }
  | { type: "uptodate" }
  | { type: "available"; version?: string }
  | { type: "progress"; version?: string; percent?: number }
  | { type: "downloaded"; version?: string }
  | { type: "error"; phase: "check" | "download"; message?: string };

export interface Updater {
  /** Running app version, without a leading "v". Empty until it resolves. */
  version: string;
  state: UpdaterState;
  /** True when the updater bridge is unavailable (e.g. running in a browser). */
  unavailable: boolean;
  check: () => void;
  download: () => void;
  restart: () => void;
}

// The main process already checks ~3s after launch. Anything that opts into
// autoCheck piggybacks on that rather than firing its own request, and later
// mounts are throttled so returning to the welcome screen does not spam GitHub.
const AUTO_CHECK_INTERVAL_MS = 60_000;
let lastAutoCheck = 0;

export function useUpdater(options?: { autoCheck?: boolean }): Updater {
  const autoCheck = options?.autoCheck ?? false;
  const [version, setVersion] = useState<string>("");
  const [state, setState] = useState<UpdaterState>({ type: "idle" });
  // Remembered so a failed download can fall back to "available" rather than
  // dropping the user back to a bare version label with no way to retry.
  const offeredVersion = useRef<string | undefined>(undefined);

  useEffect(() => {
    window.api?.updater
      ?.getVersion?.()
      .then(setVersion)
      .catch(() => {});

    if (!window.api?.updater?.onEvent) return;
    return window.api.updater.onEvent((type, payload) => {
      switch (type) {
        case "checking":
          setState({ type: "checking" });
          break;
        case "available":
          offeredVersion.current = payload?.version;
          setState({ type: "available", version: payload?.version });
          break;
        case "not-available":
          setState({ type: "uptodate" });
          window.setTimeout(() => setState({ type: "idle" }), 3000);
          break;
        case "progress":
          setState(prev => ({
            type: "progress",
            version: "version" in prev ? prev.version : undefined,
            percent: payload?.percent
          }));
          break;
        case "downloaded":
          offeredVersion.current = payload?.version;
          setState({ type: "downloaded", version: payload?.version });
          break;
        case "error": {
          const phase = payload?.phase === "download" ? "download" : "check";
          setState({ type: "error", phase, message: payload?.message });
          // A failed download does not make the release go away, so return to
          // the available state and let the user try again.
          const retry = offeredVersion.current;
          window.setTimeout(
            () =>
              setState(
                phase === "download" && retry
                  ? { type: "available", version: retry }
                  : { type: "idle" }
              ),
            4000
          );
          break;
        }
      }
    });
  }, []);

  useEffect(() => {
    if (!autoCheck || !window.api?.updater) return;
    const now = Date.now();
    if (now - lastAutoCheck < AUTO_CHECK_INTERVAL_MS) return;
    lastAutoCheck = now;
    void window.api.updater.check();
  }, [autoCheck]);

  const check = useCallback((): void => void window.api?.updater?.check(), []);
  const download = useCallback(
    (): void => void window.api?.updater?.download(),
    []
  );
  const restart = useCallback(
    (): void => void window.api?.updater?.quitAndInstall(),
    []
  );

  return {
    version,
    state,
    unavailable: !window.api?.updater,
    check,
    download,
    restart
  };
}
