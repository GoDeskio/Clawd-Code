const { app, BrowserWindow, Tray, Menu, Notification, dialog, clipboard, desktopCapturer, nativeImage, ipcMain, shell } = require("electron");
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");

const HOST = "127.0.0.1";
let PORT = Number(process.env.CLAWD_DESKTOP_PORT || 8765);
const TOKEN = process.env.CLAWD_DESKTOP_TOKEN || require("crypto").randomBytes(18).toString("hex");

app.setName("Jonathan Ai");
// The packaged shell must also run on Windows systems where Chromium's GPU
// helper DLL/runtime is unavailable. This UI is lightweight and needs no GPU.
app.disableHardwareAcceleration();
app.commandLine.appendSwitch("in-process-gpu");
// Keep Electron's singleton lock/cache beside Jonathan's local configuration.
// Some Windows profiles deny lock-file creation in the legacy roaming AppData
// directory, which made the launcher silently fall back to a browser window.
const USER_DATA = path.join(os.homedir(), ".clawd", "electron");
fs.mkdirSync(USER_DATA, { recursive: true });
app.setPath("userData", USER_DATA);

function hasCliAndRuntime(dir) {
  const cli = path.join(dir, "src", "cli.py");
  if (!fs.existsSync(cli)) return false;
  const py = process.platform === "win32"
    ? path.join(dir, ".venv", "Scripts", "python.exe")
    : path.join(dir, ".venv", "bin", "python");
  const electron = path.join(dir, "desktop", "node_modules", "electron", "dist", process.platform === "win32" ? "electron.exe" : "electron");
  return fs.existsSync(py) || fs.existsSync(electron);
}

function resolveRoot() {
  const candidates = [];
  if (process.env.CLAWD_SOURCE_DIR) candidates.push(path.resolve(process.env.CLAWD_SOURCE_DIR));
  try {
    const recordPath = path.join(os.homedir(), ".clawd", "install.json");
    const record = JSON.parse(fs.readFileSync(recordPath, "utf8"));
    if (record.source_dir) candidates.push(record.source_dir);
  } catch (_err) {
    // Fall back to the checkout that shipped this Electron shell.
  }
  candidates.push(path.resolve(__dirname, ".."));
  candidates.push(path.join(os.homedir(), "Jonathan", "Jonathan-Ai"));
  candidates.push(process.cwd());
  for (const dir of candidates) {
    if (dir && hasCliAndRuntime(dir)) return dir;
  }
  return path.resolve(__dirname, "..");
}

const ROOT = resolveRoot();
const PROCESS_RECORD = path.join(ROOT, ".jonathan-ai-processes.json");
const RUN_DIR = path.join(os.homedir(), ".clawd", "run");
const LOG_PATH = path.join(RUN_DIR, "desktop.log");

fs.mkdirSync(RUN_DIR, { recursive: true });

function logRuntime(event, details = {}) {
  const payload = {
    at: new Date().toISOString(),
    event,
    pid: process.pid,
    ...details,
  };
  try {
    fs.appendFileSync(LOG_PATH, `${JSON.stringify(payload)}\n`, "utf8");
  } catch (_err) {
    // Logging must never prevent the desktop from starting.
  }
}

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

function runtimeReady() {
  try {
    const version = fs.readFileSync(path.join(ROOT, "VERSION"), "utf8").trim();
    const marker = path.join(ROOT, `.jonathan-ai-runtime-${version}.ready`);
    const electron = path.join(ROOT, "desktop", "node_modules", "electron", "dist", process.platform === "win32" ? "electron.exe" : "electron");
    return fs.existsSync(pythonCommand()) && fs.existsSync(electron) && fs.existsSync(marker);
  } catch (_err) {
    return false;
  }
}

function bootstrapDeps() {
  if (runtimeReady()) {
    logRuntime("bootstrap_skipped", { reason: "runtime marker present" });
    return true;
  }
  logRuntime("bootstrap_started");
  try {
    const result = spawnSync(pythonCommand(), ["-m", "src.install.bootstrap", "--source-dir", ROOT], {
      cwd: ROOT,
      env: { ...process.env, CLAWD_SOURCE_DIR: ROOT },
      timeout: 7200000,
      stdio: "ignore",
    });
    const ok = result.status === 0;
    logRuntime("bootstrap_finished", { ok, status: result.status, signal: result.signal || "" });
    return ok;
  } catch (error) {
    logRuntime("bootstrap_failed", { error: String(error?.message || error) });
    // Setup can still repair the venv. Chat host starts anyway.
    return false;
  }
}

function startPython() {
  const args = ["-m", "src.cli", "desktop", "--host", HOST, "--port", String(PORT), "--no-browser", "--token", TOKEN];
  python = spawn(pythonCommand(), args, {
    cwd: ROOT,
    env: { ...process.env, CLAWD_DESKTOP_TOKEN: TOKEN, CLAWD_DESKTOP_MANAGED_BY_ELECTRON: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  logRuntime("backend_spawned", { backend_pid: python.pid || null, port: PORT });
  python.stdout.on("data", (chunk) => {
    process.stdout.write(chunk);
    logRuntime("backend_stdout", { text: String(chunk).trim().slice(0, 4000) });
  });
  python.stderr.on("data", (chunk) => {
    process.stderr.write(chunk);
    logRuntime("backend_stderr", { text: String(chunk).trim().slice(0, 4000) });
  });
  python.on("error", (error) => {
    logRuntime("backend_spawn_error", { error: String(error?.message || error) });
  });
  python.on("exit", (code) => {
    logRuntime("backend_exited", { code });
    if (!app.isQuiting && code) {
      dialog.showErrorBox("Jonathan Ai backend stopped", `Python host exited with code ${code}`);
    }
  });
  writeProcessRecord();
}

function writeProcessRecord() {
  const payload = {
    source_dir: ROOT,
    owner_pid: process.pid,
    backend_pid: python?.pid || null,
    kind: "electron",
    port: PORT,
    owner_executable: process.execPath,
    updated_at: new Date().toISOString(),
  };
  const temp = `${PROCESS_RECORD}.${process.pid}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(payload, null, 2), "utf8");
  fs.renameSync(temp, PROCESS_RECORD);
}

function removeProcessRecord() {
  try {
    const payload = JSON.parse(fs.readFileSync(PROCESS_RECORD, "utf8"));
    if (Number(payload.owner_pid) === process.pid) fs.unlinkSync(PROCESS_RECORD);
  } catch (_err) {
    // Missing/stale process records are repaired on the next launch or upgrade.
  }
}

function waitForHealth(timeoutMs = 60000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    let settled = false;
    let retryTimer = null;
    const attempt = () => {
      if (settled) return;
      const req = http.get({
        host: HOST,
        port: PORT,
        path: "/api/ready",
        timeout: 1000,
        headers: { "X-Clawd-Token": TOKEN },
      }, (res) => {
        if (res.statusCode === 200) {
          settled = true;
          if (retryTimer) clearTimeout(retryTimer);
          logRuntime("backend_ready", { port: PORT, elapsed_ms: Date.now() - started });
          resolve();
          return;
        }
        retry();
      });
      req.once("error", retry);
      req.on("timeout", () => {
        req.destroy();
      });
    };
    const retry = () => {
      if (settled) return;
      if (Date.now() - started > timeoutMs) {
        settled = true;
        reject(new Error("desktop host did not become ready"));
        return;
      }
      if (retryTimer) clearTimeout(retryTimer);
      retryTimer = setTimeout(attempt, 250);
    };
    attempt();
  });
}

function canBind(port) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.unref();
    probe.once("error", () => resolve(false));
    probe.listen({ host: HOST, port, exclusive: true }, () => {
      probe.close(() => resolve(true));
    });
  });
}

async function chooseAvailablePort(preferred, attempts = 20) {
  for (let offset = 0; offset < attempts; offset += 1) {
    const candidate = preferred + offset;
    if (await canBind(candidate)) {
      if (candidate !== preferred) {
        logRuntime("port_conflict_avoided", { preferred, selected: candidate });
      }
      return candidate;
    }
  }
  throw new Error(`No free localhost port between ${preferred} and ${preferred + attempts - 1}`);
}

function iconPath() {
  const candidates = [
    path.join(ROOT, "src", "desktop", "web", "robot.png"),
    path.join(__dirname, "icons", "jonathan-ai-robot.png"),
    path.join(__dirname, "icons", "icon.ico"),
  ];
  return candidates.find((item) => fs.existsSync(item)) || "";
}

function createWindow({ loading = false } = {}) {
  const icon = iconPath();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 880,
    minHeight: 600,
    title: "Jonathan Ai 0.4.9",
    backgroundColor: "#0b0c0f",
    show: true,
    autoHideMenuBar: true,
    icon: icon || undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  logRuntime("window_created", { loading });
  mainWindow.webContents.on("did-fail-load", (_event, code, description, url) => {
    logRuntime("window_load_failed", { code, description, url });
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    logRuntime("window_renderer_gone", { reason: details.reason, exit_code: details.exitCode });
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  if (loading) {
    const startupHtml = `<!doctype html><html><head><meta charset="utf-8"><title>Starting Jonathan Ai</title><style>
      html,body{height:100%;margin:0;background:#0b0c0f;color:#f4f6f8;font:14px system-ui,sans-serif}
      body{display:grid;place-items:center}.card{text-align:center;padding:36px 48px;border:1px solid #30343b;border-radius:18px;background:#121419}
      .ring{width:38px;height:38px;margin:0 auto 18px;border:3px solid #343943;border-top-color:#e6f4ff;border-radius:50%;animation:spin .8s linear infinite}
      h1{font-size:20px;margin:0 0 8px}.muted{color:#9da5b1}@keyframes spin{to{transform:rotate(360deg)}}
    </style></head><body><div class="card"><div class="ring"></div><h1>Starting Jonathan Ai</h1><div class="muted">Preparing your conversations and local tools…</div></div></body></html>`;
    mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(startupHtml)}`);
  } else {
    mainWindow.loadURL(`http://${HOST}:${PORT}/`);
  }
  mainWindow.show();
  mainWindow.focus();
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

ipcMain.handle("clawd:restartApp", async () => {
  logRuntime("update_restart_requested");
  app.relaunch({ execPath: process.execPath, args: process.argv.slice(1) });
  app.isQuiting = true;
  app.quit();
  return true;
});

ipcMain.handle("clawd:installUpdate", async (_event, installerPath) => {
  const updatesDir = path.resolve(os.homedir(), ".clawd", "updates");
  const candidate = path.resolve(String(installerPath || ""));
  const prefix = `${updatesDir}${path.sep}`.toLowerCase();
  if (!candidate.toLowerCase().startsWith(prefix) || path.extname(candidate).toLowerCase() !== ".exe") {
    throw new Error("Refusing installer outside Jonathan's update folder");
  }
  const header = fs.readFileSync(candidate).subarray(0, 2).toString("ascii");
  if (header !== "MZ") throw new Error("Downloaded update is not a Windows executable");

  const helper = path.join(updatesDir, `apply-${Date.now()}.ps1`);
  const helperSource = `param(
  [Parameter(Mandatory=$true)][string]$Installer,
  [Parameter(Mandatory=$true)][string]$Root,
  [Parameter(Mandatory=$true)][int]$ParentPid
)
$ErrorActionPreference = "Stop"
$log = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".clawd\\run\\update.log"
try {
  Add-Content -LiteralPath $log -Encoding utf8 -Value "$(Get-Date -Format o) waiting for Jonathan process $ParentPid"
  Wait-Process -Id $ParentPid -Timeout 90 -ErrorAction SilentlyContinue
  $installed = Start-Process -FilePath $Installer -ArgumentList @("/S", ("/D=" + $Root)) -WindowStyle Hidden -Wait -PassThru
  Add-Content -LiteralPath $log -Encoding utf8 -Value "$(Get-Date -Format o) installer exit $($installed.ExitCode)"
  if ($installed.ExitCode -eq 0) {
    Start-Process -FilePath (Join-Path $Root "JonathanAi.exe") -WorkingDirectory $Root -WindowStyle Hidden
  }
} catch {
  Add-Content -LiteralPath $log -Encoding utf8 -Value "$(Get-Date -Format o) update failed: $($_.Exception.Message)"
}
`;
  fs.writeFileSync(helper, helperSource, "utf8");
  const updater = spawn("powershell.exe", [
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", helper,
    "-Installer", candidate, "-Root", ROOT, "-ParentPid", String(process.pid),
  ], { detached: true, stdio: "ignore", windowsHide: true });
  updater.unref();
  logRuntime("installer_update_started", { installer: candidate, helper });
  app.isQuiting = true;
  setImmediate(() => app.quit());
  return true;
});

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  // Keep the handoff process alive past the native launcher's settle window.
  // The existing instance has already received second-instance and focused;
  // delaying this clean exit prevents older launchers from opening Chrome.
  setTimeout(() => app.quit(), 2500);
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
  app.whenReady().then(async () => {
    createWindow({ loading: true });
    createTray();
    bootstrapDeps();
    PORT = await chooseAvailablePort(PORT);
    startPython();
    await waitForHealth();
    await mainWindow.loadURL(`http://${HOST}:${PORT}/`);
  }).catch((error) => {
    logRuntime("desktop_start_failed", { error: String(error?.stack || error?.message || error) });
    dialog.showErrorBox("Jonathan Ai could not start", String(error?.message || error));
    app.isQuiting = true;
    app.quit();
  });
}

app.on("before-quit", () => {
  app.isQuiting = true;
  logRuntime("desktop_stopping", { backend_pid: python?.pid || null });
  removeProcessRecord();
  if (python && !python.killed) {
    if (process.platform === "win32" && python.pid) {
      spawnSync("taskkill", ["/PID", String(python.pid), "/T", "/F"], { windowsHide: true });
    } else {
      python.kill();
    }
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.isQuiting = true;
    app.quit();
  }
});
