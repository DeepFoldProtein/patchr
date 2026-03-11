import { app, shell, BrowserWindow, ipcMain, nativeTheme, Menu } from "electron";
import { join } from "path";
import { electronApp, optimizer, is } from "@electron-toolkit/utils";
import icon from "../../resources/logo.png?asset";
import { registerProjectIPC } from "./project-manager";

const WINDOW_WIDTH = 1536;
const WINDOW_HEIGHT = 652;
const DARK_BG = "#0a0a0a"; // neutral-950
const LIGHT_BG = "#ffffff";

let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  // Create the browser window.
  mainWindow = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    show: false,
    autoHideMenuBar: true,
    title: "Patchr Studio",
    frame: true, // Enable default title bar for window dragging
    ...(process.platform === "linux" ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: true,
      contextIsolation: true
    }
  });

  // Set initial theme to dark (app default)
  nativeTheme.themeSource = "dark";

  mainWindow.on("ready-to-show", () => {
    if (mainWindow) {
      mainWindow.maximize();
      mainWindow.show();
    }
  });

  // Catch Cmd+- at the highest level before renderer can swallow it
  mainWindow.webContents.on("before-input-event", (event, input) => {
    if (!mainWindow) return;
    const isMeta = process.platform === "darwin" ? input.meta : input.control;
    if (isMeta && !input.shift && !input.alt) {
      if (input.key === "-") {
        event.preventDefault();
        const level = mainWindow.webContents.getZoomLevel();
        mainWindow.webContents.setZoomLevel(level - 0.5);
      } else if (input.key === "=" || input.key === "+") {
        event.preventDefault();
        const level = mainWindow.webContents.getZoomLevel();
        mainWindow.webContents.setZoomLevel(level + 0.5);
      } else if (input.key === "0") {
        event.preventDefault();
        mainWindow.webContents.setZoomLevel(0);
      }
    }
  });

  mainWindow.webContents.setWindowOpenHandler(details => {
    try {
      const url = new URL(details.url);
      if (["http:", "https:"].includes(url.protocol)) {
        shell.openExternal(details.url);
      }
    } catch {
      // Invalid URL, ignore
    }
    return { action: "deny" };
  });

  // HMR for renderer base on electron-vite cli.
  // Load the remote URL for development or the local html file for production.
  if (is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(() => {
  // Set app name and user model id
  app.setName("Patchr Studio");
  electronApp.setAppUserModelId("com.patchr.studio");

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production.
  // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
  app.on("browser-window-created", (_, window) => {
    optimizer.watchWindowShortcuts(window);
  });

  // Set up application menu with standard zoom shortcuts
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(process.platform === "darwin"
      ? [
          {
            label: app.name,
            submenu: [
              { role: "about" as const },
              { type: "separator" as const },
              { role: "hide" as const },
              { role: "hideOthers" as const },
              { role: "unhide" as const },
              { type: "separator" as const },
              { role: "quit" as const }
            ]
          }
        ]
      : []),
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" }
      ]
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" }
      ]
    },
    {
      label: "Window",
      submenu: [
        { role: "minimize" },
        { role: "close" },
        ...(process.platform === "darwin"
          ? [{ type: "separator" as const }, { role: "front" as const }]
          : [])
      ]
    }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));

  // Handle theme change for title bar
  ipcMain.handle("app:set-theme", (_event, theme: "light" | "dark") => {
    // Set nativeTheme to update system appearance (macOS, Windows, Linux)
    nativeTheme.themeSource = theme;

    // Also set background color for better visual consistency
    const windows = BrowserWindow.getAllWindows();
    const isDark = theme === "dark";

    windows.forEach(window => {
      window.setBackgroundColor(isDark ? DARK_BG : LIGHT_BG);
    });

    return { success: true };
  });

  // Register project management IPC handlers
  registerProjectIPC();

  createWindow();

  app.on("activate", function () {
    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and require them here.
