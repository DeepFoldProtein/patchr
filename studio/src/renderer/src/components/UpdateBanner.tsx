// Update affordance for the welcome screen. The status bar only exists once a
// project is open, so without this the app offers no way to see or take an
// update from Home.
//
// Checks on mount (throttled in useUpdater) and stays hidden unless there is
// something to act on, so the welcome screen is not cluttered when up to date.
import React from "react";
import { Download, ArrowUpCircle, AlertTriangle } from "lucide-react";
import { useUpdater } from "../hooks/useUpdater";

export function UpdateBanner(): React.JSX.Element | null {
  const { state, unavailable, download, restart, check } = useUpdater({
    autoCheck: true
  });

  if (unavailable) return null;

  const shell =
    "flex items-center gap-3 rounded-xl border px-4 py-3 backdrop-blur-xl";

  if (state.type === "downloaded") {
    return (
      <div
        className={`${shell} border-blue-500/30 bg-blue-500/10`}
        role="status"
      >
        <ArrowUpCircle className="h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-neutral-900 dark:text-white">
            Update {state.version ? `v${state.version}` : ""} is ready
          </p>
          <p className="text-xs text-neutral-600 dark:text-neutral-400">
            Restart Patchr Studio to finish installing.
          </p>
        </div>
        <button
          onClick={restart}
          className="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-500"
        >
          Restart
        </button>
      </div>
    );
  }

  if (state.type === "available") {
    return (
      <div
        className={`${shell} border-blue-500/30 bg-blue-500/10`}
        role="status"
      >
        <Download className="h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-neutral-900 dark:text-white">
            Update {state.version ? `v${state.version}` : ""} available
          </p>
          <p className="text-xs text-neutral-600 dark:text-neutral-400">
            Download it now — nothing installs until you restart.
          </p>
        </div>
        <button
          onClick={download}
          className="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-500"
        >
          Download
        </button>
      </div>
    );
  }

  if (state.type === "progress") {
    const percent = state.percent ?? 0;
    return (
      <div
        className={`${shell} border-blue-500/30 bg-blue-500/10`}
        role="status"
      >
        <Download className="h-5 w-5 shrink-0 animate-pulse text-blue-600 dark:text-blue-400" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-neutral-900 dark:text-white">
            Downloading update… {percent}%
          </p>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-blue-500/20">
            <div
              className="h-full rounded-full bg-blue-600 transition-[width] duration-300"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      </div>
    );
  }

  // Surface a failed check or download; the status bar reports the same thing
  // but does not exist on this screen.
  if (state.type === "error") {
    return (
      <div
        className={`${shell} border-amber-500/30 bg-amber-500/10`}
        role="status"
      >
        <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-neutral-900 dark:text-white">
            Could not check for updates
          </p>
          <p className="truncate text-xs text-neutral-600 dark:text-neutral-400">
            {state.message || "Check your connection and try again."}
          </p>
        </div>
        <button
          onClick={check}
          className="shrink-0 rounded-lg border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-500/10 dark:border-neutral-700 dark:text-neutral-200"
        >
          Retry
        </button>
      </div>
    );
  }

  // idle / checking / uptodate — nothing worth showing on the welcome screen.
  return null;
}
