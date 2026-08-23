const { app, BrowserWindow, Tray, Menu, Notification, dialog, clipboard, desktopCapturer, nativeImage, ipcMain } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const HOST = "127.0.0.1";
const PORT = Number(process.env.CLAWD_DESKTOP_PORT || 8765);
const TOKEN = process.env.CLAWD_DESKTOP_TOKEN || require("crypto").randomBytes(18).toString("hex");
const ROOT = path.resolve(__dirname, "..");

let mainWindow = null;
let tray = null;
let python = null;

function pythonCommand() {
  if (process.env.CLAWD_PYTHON) return process.env.CLAWD_PYTHON;
  const venv = process.platform === "win32"
    ? path.join(ROOT, ".venv", "Scripts", "python.exe")
    : path.join(ROOT, ".venv", "bin", "python");
  if (fs.existsSync(venv)) return venv;
  return process.platform === "win32" ? "python" : "python3";
}

function startPython() {
  const args = ["-m", "src.cli", "desktop", "--host", HOST, "--port", String(PORT), "--no-browser", "--token", TOKEN];
  python = spawn(pythonCommand(), args, {
    cwd: ROOT,
    env: { ...process.env, CLAWD_DESKTOP_TOKEN: TOKEN },
    stdio: ["ignore", "pipe", "pipe"],
  });
  python.stdout.on("data", (chunk) => process.stdout.write(chunk));
  python.stderr.on("data", (chunk) => process.stderr.write(chunk));
  python.on("exit", (code) => {
    if (!app.isQuiting && code) {
      dialog.showErrorBox("Clawd backend stopped", `Python host exited with code ${code}`);
    }
  });
}

function waitForHealth(timeoutMs = 20000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get({ host: HOST, port: PORT, path: "/api/health", timeout: 1000 }, (res) => {
        if (res.statusCode === 200) {
          resolve();
          return;
        }
        retry();
      });
      req.on("error", retry);
      req.on("timeout", () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error("desktop host did not become ready"));
        return;
      }
      setTimeout(attempt, 250);
    };
    attempt();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 880,
    minHeight: 600,
    title: "Clawd Code",
    backgroundColor: "#10140f",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.loadURL(`http://${HOST}:${PORT}/`);
  mainWindow.on("close", (event) => {
    if (!app.isQuiting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(ROOT, "src", "desktop", "web", "icon.svg"));
  tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);
  tray.setToolTip("Clawd Code");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Show Clawd", click: () => { mainWindow?.show(); mainWindow?.focus(); } },
    { label: "New chat", click: () => { mainWindow?.show(); mainWindow?.webContents.send("clawd:new-chat"); } },
    { type: "separator" },
    { label: "Quit", click: () => { app.isQuiting = true; app.quit(); } },
  ]));
  tray.on("click", () => mainWindow?.show());
}

ipcMain.handle("clawd:pickFolder", async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory", "createDirectory"] });
  return result.canceled ? "" : result.filePaths[0];
});

ipcMain.handle("clawd:pickFiles", async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ["openFile", "multiSelections"] });
  return result.canceled ? [] : result.filePaths;
});

ipcMain.handle("clawd:readClipboardText", async () => {
  // Only runs when the user clicks Clipboard in the UI.
  return clipboard.readText() || "";
});

ipcMain.handle("clawd:captureScreenshot", async () => {
  const sources = await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: 1600, height: 900 } });
  const source = sources[0];
  if (!source) return "";
  const destDir = path.join(os.homedir(), ".clawd", "captures");
  fs.mkdirSync(destDir, { recursive: true });
  const dest = path.join(destDir, `screen-${Date.now()}.png`);
  fs.writeFileSync(dest, source.thumbnail.toPNG());
  return dest;
});

ipcMain.handle("clawd:notify", async (_event, { title, body }) => {
  if (!Notification.isSupported()) return false;
  new Notification({ title: title || "Clawd", body: body || "" }).show();
  return true;
});

app.whenReady().then(async () => {
  startPython();
  await waitForHealth();
  createWindow();
  createTray();
});

app.on("before-quit", () => {
  app.isQuiting = true;
  if (python && !python.killed) python.kill();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.isQuiting = true;
    app.quit();
  }
});
