// Auto-update via electron-updater, backed by GitHub Releases (see the
// `publish` block in electron-builder.yml → generates app-update.yml in the
// packaged app). On startup a packaged build checks the repo's latest release,
// downloads it in the background, and tells the renderer when it's ready so the
// user can restart into the new version. In dev (unpackaged) this is a no-op
// unless FORCE_UPDATE_CHECK=1 is set (uses dev-app-update.yml).
import { app, ipcMain, type BrowserWindow } from "electron";
import electronUpdater from "electron-updater";

const { autoUpdater } = electronUpdater;

let initialized = false;

export function initAutoUpdater(getWindow: () => BrowserWindow | null): void {
  if (initialized) return;
  initialized = true;

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  const send = (channel: string, payload?: unknown): void => {
    getWindow()?.webContents.send(channel, payload);
  };

  autoUpdater.on("checking-for-update", () => send("updater:checking"));
  autoUpdater.on("update-available", info =>
    send("updater:available", { version: info.version })
  );
  autoUpdater.on("update-not-available", () => send("updater:not-available"));
  autoUpdater.on("download-progress", p =>
    send("updater:progress", { percent: Math.round(p.percent) })
  );
  autoUpdater.on("update-downloaded", info =>
    send("updater:downloaded", { version: info.version })
  );
  autoUpdater.on("error", err =>
    send("updater:error", { message: err?.message ?? String(err) })
  );

  // Renderer-triggered: quit and install the downloaded update now.
  ipcMain.handle("updater:quit-and-install", () => {
    autoUpdater.quitAndInstall();
  });

  // Renderer-triggered manual check (e.g. a "Check for updates" menu item).
  ipcMain.handle("updater:check", async () => {
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

  const forceDev = process.env.FORCE_UPDATE_CHECK === "1";
  if (app.isPackaged || forceDev) {
    if (forceDev) autoUpdater.forceDevUpdateConfig = true;
    // Check shortly after startup so it never blocks window creation.
    setTimeout(() => {
      autoUpdater.checkForUpdatesAndNotify().catch(() => {
        /* offline / no release yet — ignore */
      });
    }, 3000);
  }
}
