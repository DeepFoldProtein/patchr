import { useAtomValue, useSetAtom } from "jotai";
import { apiConnectionStatusAtom, panelModeAtom } from "../store/api-atoms";

/** Inline hint shown below disabled action buttons when API is not connected. */
export function DisconnectedHint(): React.ReactElement | null {
  const connectionStatus = useAtomValue(apiConnectionStatusAtom);
  const setPanelMode = useSetAtom(panelModeAtom);

  if (connectionStatus === "connected") return null;

  return (
    <button
      onClick={() => setPanelMode("project")}
      className="w-full rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-left hover:bg-amber-500/10 transition-colors"
    >
      <p className="text-xs text-amber-600 dark:text-amber-400">
        {connectionStatus === "error"
          ? "Server connection failed."
          : "Server not connected."}
        <span className="ml-1 underline underline-offset-2 font-medium">
          Set up connection →
        </span>
      </p>
    </button>
  );
}
