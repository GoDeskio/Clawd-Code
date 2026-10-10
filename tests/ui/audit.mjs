/**
 * Headless check: every desktop and installer route, then every visible control.
 * Fails on an uncaught page error or a console error. Browser "Failed to load
 * resource" lines are the network log for handled 4xx responses the UI already
 * shows in a status line.
 */
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const home = mkdtempSync(path.join(tmpdir(), "jonathan-ui-"));
const workspace = path.join(home, "workspace");
const sample = path.join(home, "note.txt");
writeFileSync(sample, "audit\n");
const desktopPort = 8875;
const installPort = 8876;
const chrome = process.env.CHROME_PATH || "";

const desktopRoutes = ["/", "/index.html", "/#/chat", "/#/settings", "/#/connectors", "/#/setup", "/#/library"];
const installRoutes = ["/", "/index.html", "/#/install", "/#/model", "/#/git", "/#/agents"];
const problems = [];
let clicked = 0;

function startPython(args, ready) {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", args, {
      cwd: root,
      env: { ...process.env, HOME: home, PYTHONUNBUFFERED: "1" },
    });
    let buffer = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      reject(new Error(`timed out waiting for ${ready}\n${buffer}`));
    }, 20000);
    const take = (chunk) => {
      buffer += chunk.toString();
      if (!settled && buffer.includes(ready)) {
        settled = true;
        clearTimeout(timer);
        resolve(child);
      }
    };
    child.stdout.on("data", take);
    child.stderr.on("data", take);
    child.on("exit", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new Error(`python exited ${code}\n${buffer}`));
    });
  });
}

function track(page) {
  const bucket = { page: [], console: [] };
  page.on("pageerror", (err) => bucket.page.push(String(err)));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (text.startsWith("Failed to load resource:")) return;
    if (text.includes("net::ERR_ABORTED")) return;
    bucket.console.push(text);
  });
  return bucket;
}

function assertClean(bucket, label) {
  const rows = [...bucket.page.map((item) => `page: ${item}`), ...bucket.console.map((item) => `console: ${item}`)];
  if (rows.length) problems.push(`${label}\n${rows.join("\n")}`);
  bucket.page.length = 0;
  bucket.console.length = 0;
}

async function visit(page, bucket, base, routes) {
  for (const route of routes) {
    const url = new URL(route, base).toString();
    const response = await page.goto(url, { waitUntil: "networkidle" });
    const hash = route.startsWith("/#/") ? route.slice(3) : "";
    if (hash) {
      await page.waitForFunction((name) => document.body.dataset.route === name, hash);
    } else if (!response || !response.ok()) {
      problems.push(`${url} returned ${response ? response.status() : "no response"}`);
    }
    await page.waitForTimeout(150);
    assertClean(bucket, url);
  }
}

async function actionableIds(page) {
  return page.locator("button").evaluateAll((nodes) =>
    nodes
      .map((node) => {
        if (!node.id || node.disabled) return "";
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden") return "";
        const rect = node.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) return "";
        if (rect.bottom < 0 || rect.right < 0 || rect.top > innerHeight || rect.left > innerWidth) return "";
        const cx = Math.min(innerWidth - 1, Math.max(0, rect.left + rect.width / 2));
        const cy = Math.min(innerHeight - 1, Math.max(0, rect.top + rect.height / 2));
        const top = document.elementFromPoint(cx, cy);
        if (!top || (top !== node && !node.contains(top))) return "";
        return node.id;
      })
      .filter(Boolean),
  );
}

async function clickVisible(page, bucket, label, resetUrl) {
  await page.goto(resetUrl, { waitUntil: "networkidle" });
  const ids = await actionableIds(page);
  for (const id of ids) {
    if (id === "apply-update") continue;
    await page.goto(resetUrl, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(80);
    const still = await actionableIds(page);
    if (!still.includes(id)) continue;
    const button = page.locator(`#${id}`);
    try {
      await button.click({ timeout: 8000 });
      clicked += 1;
      await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
    } catch (err) {
      problems.push(`${label} #${id} click failed: ${err.message || err}`);
    }
    assertClean(bucket, `${label} #${id}`);
  }
}

const desktop = await startPython(
  [
    "-c",
    `from pathlib import Path
Path(${JSON.stringify(workspace)}).mkdir(parents=True, exist_ok=True)
from src.desktop.server import create_server
server = create_server(host="127.0.0.1", port=${desktopPort}, workspace=${JSON.stringify(workspace)}, token="ui-audit")
server.start()
print("READY " + server.url, flush=True)
import time
while True:
    time.sleep(3600)
`,
  ],
  "READY ",
);
const installer = await startPython(
  ["-m", "src.install", "--ui", "--no-browser", "--port", String(installPort)],
  "Install wizard:",
);

const launchOptions = {
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
};
if (chrome) launchOptions.executablePath = chrome;
const browser = await chromium.launch(launchOptions);
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const bucket = track(page);
  page.on("dialog", (dialog) => {
    const message = dialog.message().toLowerCase();
    if (message.includes("folder") || message.includes("workspace")) dialog.accept(workspace);
    else if (message.includes("repository")) dialog.accept("audit-repo");
    else if (message.includes("forge")) dialog.accept("github");
    else if (message.includes("branch")) dialog.accept("");
    else dialog.dismiss();
  });
  page.on("filechooser", (chooser) => chooser.setFiles(sample));

  const base = `http://127.0.0.1:${desktopPort}/`;
  await visit(page, bucket, base, desktopRoutes);
  const declared = await page.evaluate(() => window.JONATHAN_UI_ROUTES);
  if (JSON.stringify(declared) !== JSON.stringify(desktopRoutes)) {
    problems.push(`desktop routes ${JSON.stringify(declared)} != ${JSON.stringify(desktopRoutes)}`);
  }
  for (const asset of ["/styles.css", "/app.js", "/robot.png", "/favicon.ico"]) {
    const response = await page.request.get(new URL(asset, base).toString());
    if (!response.ok()) problems.push(`${asset} returned ${response.status()}`);
  }
  await page.evaluate(async () => {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: "local",
        api_key: "",
        base_url: "http://127.0.0.1:11434/v1",
        default_model: "llama3.2",
      }),
    });
    if (!response.ok) throw new Error(await response.text());
  });
  await page.goto(`${base}#/chat`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForFunction(() => document.body.dataset.route === "chat");
  assertClean(bucket, "chat after login");
  if (await page.locator("#setup-modal").isVisible()) problems.push("setup modal still open after login");
  for (const route of ["#/chat", "#/settings", "#/connectors", "#/setup", "#/library"]) {
    await clickVisible(page, bucket, `desktop ${route}`, `${base}${route}`);
  }
  await page.goto(`${base}#/chat`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "networkidle" });
  const session = page.locator(".session-item").first();
  if ((await session.count()) && (await session.isVisible())) {
    try {
      await session.click({ timeout: 5000 });
      await page.waitForTimeout(150);
    } catch (err) {
      problems.push(`session click failed: ${err.message || err}`);
    }
    assertClean(bucket, "session click");
  }
  await page.evaluate(() => {
    document.getElementById("perm-title").textContent = "Allow Bash?";
    document.getElementById("perm-message").textContent = "Held until you approve this command.";
    document.getElementById("permission-banner").classList.remove("hidden");
  });
  for (const id of ["perm-deny", "perm-always", "perm-allow"]) {
    await page.locator(`#${id}`).click();
    assertClean(bucket, id);
  }
  await page.goto(`${base}#/settings`, { waitUntil: "networkidle" });
  await page.selectOption("#settings-provider", "huggingface");
  await page.locator("#settings-hf-test").click();
  await page.selectOption("#settings-provider", "local");
  await page.locator("#settings-local-scan").click({ timeout: 20000 });
  assertClean(bucket, "settings providers");
  const providerOptions = await page.locator("#settings-provider option").allTextContents();
  if (providerOptions.some((text) => /glm|minimax|zhipu/i.test(text))) {
    problems.push(`hidden provider still listed: ${providerOptions.join(" | ")}`);
  }

  const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const narrowBucket = track(narrow);
  await narrow.goto(`${base}#/chat`, { waitUntil: "networkidle" });
  await narrow.locator("#nav-toggle").click();
  if (!(await narrow.locator(".sidebar").isVisible())) problems.push("mobile menu did not open the sidebar");
  await narrow.locator("#open-settings").click();
  await narrow.waitForFunction(() => document.body.dataset.route === "settings");
  assertClean(narrowBucket, "mobile");

  const installPage = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const installBucket = track(installPage);
  const installBase = `http://127.0.0.1:${installPort}/`;
  await visit(installPage, installBucket, installBase, installRoutes);
  const installDeclared = await installPage.evaluate(() => window.JONATHAN_UI_ROUTES);
  if (JSON.stringify(installDeclared) !== JSON.stringify(installRoutes)) {
    problems.push(`install routes ${JSON.stringify(installDeclared)}`);
  }
  await installPage.route("**/api/start", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ job_id: "audit-job" }) }),
  );
  await installPage.route("**/api/jobs/**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        events: [{ type: "done", message: "Installed.", source_dir: "/tmp/jonathan-audit" }],
        done: true,
        result: { ok: true },
      }),
    }),
  );
  for (const route of ["#/install", "#/model", "#/git", "#/agents"]) {
    await clickVisible(installPage, installBucket, `install ${route}`, `${installBase}${route}`);
  }
} finally {
  await browser.close();
  desktop.kill("SIGTERM");
  installer.kill("SIGTERM");
}

if (problems.length) {
  console.error(problems.join("\n\n"));
  process.exit(1);
}
console.log(`ui audit ok (${clicked} controls)`);
