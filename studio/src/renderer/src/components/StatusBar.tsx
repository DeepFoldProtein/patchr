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
        return "text-neutral-400";
      case "testing":
        return "text-yellow-400";
      case "error":
        return "text-red-400";
      default:
        return "text-neutral-500";
    }
  };

  const getConnectionStatusDot = (): string => {
    switch (connectionStatus) {
      case "connected":
        return "bg-neutral-400";
      case "testing":
        return "bg-yellow-500 animate-pulse";
      case "error":
        return "bg-red-500";
      default:
        return "bg-neutral-500";
    }
  };

  return (
    <div className="flex h-9 items-center gap-4 border-t border-neutral-200/50 dark:border-neutral-800/50 bg-white/60 dark:bg-neutral-900/40 backdrop-blur-xl px-6 text-xs text-neutral-600 dark:text-neutral-400 shadow-sm">
      <div className="flex items-center gap-2">
        <div className={`h-2 w-2 rounded-full ${getConnectionStatusDot()}`} />
        <span className={getConnectionStatusColor()}>
          {getConnectionStatusText()}
        </span>
      </div>
      <div className="flex-1" />
      {currentProject && (
        <div className="flex items-center gap-2 text-neutral-600 dark:text-neutral-400">
          <span className="text-neutral-500 dark:text-neutral-500">
            Project:
          </span>
          <span className="font-medium text-neutral-700 dark:text-neutral-300">
            {currentProject.name}
          </span>
        </div>
      )}
    </div>
  );
}
