const { app, BrowserWindow, Tray, Menu, Notification, dialog, clipboard, desktopCapturer, nativeImage, ipcMain } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const HOST = "127.0.0.1";
const PORT = Number(process.env.CLAWD_DESKTOP_PORT || 8765);
const TOKEN = process.env.CLAWD_DESKTOP_TOKEN || require("crypto").randomBytes(18).toString("hex");

app.setName("Jonathan Ai");

function resolveRoot() {
  if (process.env.CLAWD_SOURCE_DIR) return path.resolve(process.env.CLAWD_SOURCE_DIR);
  try {
    const recordPath = path.join(os.homedir(), ".clawd", "install.json");
    const record = JSON.parse(fs.readFileSync(recordPath, "utf8"));
    if (record.source_dir && fs.existsSync(path.join(record.source_dir, "src", "cli.py"))) {
      return record.source_dir;
    }
  } catch (_err) {
    // Fall back to the checkout that shipped this Electron shell.
  }
  return path.resolve(__dirname, "..");
}

const ROOT = resolveRoot();

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
      dialog.showErrorBox("Jonathan Ai backend stopped", `Python host exited with code ${code}`);
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

function iconPath() {
  const candidates = [
    path.join(ROOT, "src", "desktop", "web", "robot.png"),
    path.join(__dirname, "icons", "jonathan-ai-robot.png"),
    path.join(__dirname, "icons", "icon.ico"),
  ];
  return candidates.find((item) => fs.existsSync(item)) || "";
}

function createWindow() {
  const icon = iconPath();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 880,
    minHeight: 600,
    title: "Jonathan Ai 0.2.1",
    backgroundColor: "#0b0c0f",
    autoHideMenuBar: true,
    icon: icon || undefined,
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
  const icon = nativeImage.createFromPath(iconPath() || path.join(ROOT, "src", "desktop", "web", "icon.svg"));
  tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);
  tray.setToolTip("Jonathan Ai");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Show Jonathan Ai", click: () => { mainWindow?.show(); mainWindow?.focus(); } },
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
  new Notification({ title: title || "Jonathan Ai", body: body || "" }).show();
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
