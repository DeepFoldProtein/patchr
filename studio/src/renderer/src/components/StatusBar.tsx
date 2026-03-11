import React from "react";
import { useAtomValue } from "jotai";
import { apiConnectionStatusAtom } from "../store/api-atoms";
import { useCurrentProject } from "../store/project-store";

export function StatusBar(): React.ReactElement {
  const connectionStatus = useAtomValue(apiConnectionStatusAtom);
  const currentProject = useCurrentProject();

  const getConnectionStatusText = (): string => {
    switch (connectionStatus) {
      case "connected":
        return "API: Connected";
      case "testing":
        return "API: Testing...";
      case "error":
        return "API: Error";
      default:
        return "API: Disconnected";
    }
  };

  const getConnectionStatusColor = (): string => {
    switch (connectionStatus) {
      case "connected":
        return "text-emerald-400";
      case "testing":
        return "text-yellow-400";
      case "error":
        return "text-red-400";
      default:
        return "text-slate-500";
    }
  };

  const getConnectionStatusDot = (): string => {
    switch (connectionStatus) {
      case "connected":
        return "bg-emerald-500";
      case "testing":
        return "bg-yellow-500 animate-pulse";
      case "error":
        return "bg-red-500";
      default:
        return "bg-slate-500";
    }
  };

  return (
    <div className="flex h-9 items-center gap-4 border-t border-slate-200/50 dark:border-slate-800/50 bg-white/60 dark:bg-slate-900/40 backdrop-blur-xl px-6 text-xs text-slate-600 dark:text-slate-400 shadow-sm">
      <div className="flex items-center gap-2">
        <div className={`h-2 w-2 rounded-full ${getConnectionStatusDot()}`} />
        <span className={getConnectionStatusColor()}>
          {getConnectionStatusText()}
        </span>
      </div>
      <div className="flex-1" />
      {currentProject && (
        <div className="flex items-center gap-2 text-slate-600 dark:text-slate-400">
          <span className="text-slate-500 dark:text-slate-500">Project:</span>
          <span className="font-medium text-slate-700 dark:text-slate-300">
            {currentProject.name}
          </span>
        </div>
      )}
    </div>
  );
}
