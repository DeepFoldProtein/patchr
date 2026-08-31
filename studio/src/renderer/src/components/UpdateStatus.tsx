// Explicit update control in the status bar. Shows the current version and,
// when a newer GitHub release is available, lets the user deliberately Download
// and then Restart to install. Nothing happens without a click.
//
// The state machine lives in useUpdater so the welcome screen can render the
// same update affordances.
import React from "react";
import { RefreshCw, Download, ArrowUpCircle } from "lucide-react";
import { useUpdater } from "../hooks/useUpdater";

export function UpdateStatus(): React.JSX.Element | null {
  const { version, state, unavailable, check, download, restart } =
    useUpdater();

  if (unavailable) return null;

  const versionTag = version ? `v${version}` : "";

  // Update ready — highlight + Restart.
  if (state.type === "downloaded") {
    return (
      <button
        onClick={restart}
        title="Restart to install the update"
        className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-blue-500"
      >
        <ArrowUpCircle className="h-3.5 w-3.5" />
        Restart to update {state.version ? `v${state.version}` : ""}
      </button>
    );
  }

  // Update available — offer explicit Download.
  if (state.type === "available") {
    return (
      <button
        onClick={download}
        title="Download the update"
        className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/10 px-2 py-1 text-xs font-medium text-blue-600 transition-colors hover:bg-blue-500/20 dark:text-blue-400"
      >
        <Download className="h-3.5 w-3.5" />
        Update {state.version ? `v${state.version}` : ""} available
      </button>
    );
  }

  // Downloading.
  if (state.type === "progress") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400">
        <Download className="h-3.5 w-3.5 animate-pulse" />
        Downloading… {state.percent ?? 0}%
      </span>
    );
  }

  // Idle / checking / up-to-date / error → version + a check affordance.
  const rightLabel =
    state.type === "checking"
      ? "Checking…"
      : state.type === "uptodate"
        ? "Up to date"
        : state.type === "error"
          ? state.phase === "download"
            ? "Download failed"
            : "Check failed"
          : "";

  return (
    <button
      onClick={check}
      disabled={state.type === "checking"}
      title={
        state.type === "error" && state.phase === "download"
          ? "Download failed — click to check again"
          : "Check for updates"
      }
      className="inline-flex items-center gap-1.5 text-xs text-neutral-500 transition-colors hover:text-neutral-700 disabled:opacity-70 dark:text-neutral-500 dark:hover:text-neutral-300"
    >
      <RefreshCw
        className={
          "h-3 w-3 " + (state.type === "checking" ? "animate-spin" : "")
        }
      />
      <span>{versionTag}</span>
      {rightLabel && (
        <span
          className={
            state.type === "error"
              ? "text-red-500/80"
              : state.type === "uptodate"
                ? "text-emerald-500/80"
                : ""
          }
        >
          · {rightLabel}
        </span>
      )}
    </button>
  );
}
