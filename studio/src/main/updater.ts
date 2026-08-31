// Explicit update flow via electron-updater, backed by GitHub Releases (see the
// `publish` block in electron-builder.yml → generates app-update.yml in the
// packaged app). Nothing is downloaded or installed silently: the app checks for
// an update (on startup + when the user clicks "Check for updates"), and the
// user explicitly triggers the Download and the Restart from the status bar.
// In dev (unpackaged) checks are a no-op unless FORCE_UPDATE_CHECK=1 is set.
import { app, ipcMain, type BrowserWindow } from "electron";
import electronUpdater from "electron-updater";

const { autoUpdater } = electronUpdater;

let initialized = false;
const isActive = (): boolean =>
  app.isPackaged || process.env.FORCE_UPDATE_CHECK === "1";

export function initAutoUpdater(getWindow: () => BrowserWindow | null): void {
  if (initialized) return;
  initialized = true;

  // Explicit: don't download or install without the user asking.
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;

  const send = (channel: string, payload?: unknown): void => {
    getWindow()?.webContents.send(channel, payload);
  };

  // electron-updater reports every failure through the same "error" event, so
  // the renderer cannot tell a failed check from a failed download. Track which
  // operation is in flight and tag the error with it.
  let phase: "check" | "download" = "check";
  // A check can start while a download is still running (the welcome screen
  // checks on mount), and it must not relabel the download's failure.
  let downloading = false;

  autoUpdater.on("checking-for-update", () => {
    if (!downloading) phase = "check";
    send("updater:checking");
  });
  autoUpdater.on("update-available", info =>
    send("updater:available", { version: info.version })
  );
  autoUpdater.on("update-not-available", () => send("updater:not-available"));
  autoUpdater.on("download-progress", p =>
    send("updater:progress", { percent: Math.round(p.percent) })
  );
  autoUpdater.on("update-downloaded", info => {
    downloading = false;
    send("updater:downloaded", { version: info.version });
  });
  autoUpdater.on("error", err => {
    downloading = false;
    send("updater:error", { message: err?.message ?? String(err), phase });
  });

  // Current app version — shown in the status bar.
  ipcMain.handle("updater:version", () => app.getVersion());

  // User clicked "Check for updates".
  ipcMain.handle("updater:check", async () => {
    if (!isActive()) {
      return { success: false, error: "Updates are disabled in dev mode." };
    }
    try {
      const r = await autoUpdater.checkForUpdates();
      return { success: true, version: r?.updateInfo?.version };
    } catch (e) {
      return {
        success: false,
        error: e instanceof Error ? e.message : String(e)
      };
    }
  });

  // User clicked "Download" — download the available update.
  ipcMain.handle("updater:download", async () => {
    phase = "download";
    downloading = true;
    try {
      await autoUpdater.downloadUpdate();
      return { success: true };
    } catch (e) {
      return {
        success: false,
        error: e instanceof Error ? e.message : String(e)
      };
    }
  });

  // User clicked "Restart" — quit and install the downloaded update.
  ipcMain.handle("updater:quit-and-install", () => {
    autoUpdater.quitAndInstall();
  });

  if (isActive()) {
    if (process.env.FORCE_UPDATE_CHECK === "1")
      autoUpdater.forceDevUpdateConfig = true;
    // A quiet check on startup so the status bar can proactively show
    // "Update available" — but the download stays a deliberate click.
    setTimeout(() => {
      autoUpdater.checkForUpdates().catch(() => {
        /* offline / no release yet — ignore */
      });
    }, 3000);
  }
}
