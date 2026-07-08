// Small bottom-right toast driven by the main-process auto-updater
// (electron-updater / GitHub Releases). Shows download progress and, once an
// update is downloaded, a "Restart" button to install it.
import { useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";

type UpdateState = {
  type: "available" | "progress" | "downloaded";
  version?: string;
  percent?: number;
} | null;

export function UpdateNotification(): React.JSX.Element | null {
  const [state, setState] = useState<UpdateState>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!window.api?.updater?.onEvent) return;
    return window.api.updater.onEvent((type, payload) => {
      if (type === "available") {
        setDismissed(false);
        setState({ type: "available", version: payload?.version });
      } else if (type === "progress") {
        setState(prev => ({
          type: "progress",
          version: prev?.version ?? payload?.version,
          percent: payload?.percent
        }));
      } else if (type === "downloaded") {
        setState({ type: "downloaded", version: payload?.version });
      } else if (type === "error" || type === "not-available") {
        setState(null);
      }
      // "checking" is ignored (silent).
    });
  }, []);

  if (!state || dismissed) return null;

  const version = state.version ? `v${state.version}` : "update";

  return (
    <div className="fixed bottom-4 right-4 z-50 w-72 rounded-lg border border-border bg-background/95 p-3 shadow-lg backdrop-blur">
      {state.type === "downloaded" ? (
        <>
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Download className="h-4 w-4 text-primary" />
            Update {version} ready
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Restart Patchr Studio to install the latest version.
          </p>
          <div className="mt-2 flex justify-end gap-2">
            <button
              onClick={() => setDismissed(true)}
              className="rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent"
            >
              Later
            </button>
            <button
              onClick={() => window.api.updater.quitAndInstall()}
              className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:opacity-90"
            >
              <RefreshCw className="h-3 w-3" />
              Restart now
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Download className="h-4 w-4 animate-pulse text-primary" />
            Downloading update {version}…
          </div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${state.percent ?? 0}%` }}
            />
          </div>
          <p className="mt-1 text-right text-[0.65rem] text-muted-foreground">
            {state.percent ?? 0}%
          </p>
        </>
      )}
    </div>
  );
}
