const native = window.clawdDesktop || null;
const state = {
  status: null,
  commands: [],
  sessions: [],
  attachments: [],
  pendingPermission: null,
  sending: false,
  currentJob: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const res = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${path}`);
  return data;
}

function renderMarkdown(text) {
  const escaped = String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const withCode = escaped.replace(/```([\s\S]*?)```/g, (_, code) => `<pre class="md-pre"><code>${code}</code></pre>`);
  return withCode
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

function addBubble(role, text, extraClass) {
  const node = document.createElement("article");
  node.className = `bubble ${role} ${extraClass || ""}`.trim();
  if (role === "assistant" || role === "system") {
    node.innerHTML = renderMarkdown(text);
  } else {
    node.textContent = text;
  }
  $("transcript").appendChild(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function addToolCard(event) {
  const node = document.createElement("article");
  node.className = "bubble tool-card";
  const summary = event.summary || event.error || "";
  node.innerHTML = `<strong>${event.tool_name || event.type}</strong><div class="summary">${summary}</div>`;
  $("transcript").appendChild(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function setBusy(busy) {
  state.sending = busy;
  $("send").disabled = busy;
}

function showPermission(event) {
  state.pendingPermission = event;
  $("perm-title").textContent = `Allow ${event.tool_name}?`;
  $("perm-message").textContent = event.message || "";
  $("permission-banner").classList.remove("hidden");
}

function hidePermission() {
  state.pendingPermission = null;
  $("permission-banner").classList.add("hidden");
}

async function decidePermission(decision) {
  if (!state.pendingPermission) return;
  await api("/api/permissions", {
    method: "POST",
    body: JSON.stringify({ request_id: state.pendingPermission.request_id, decision }),
  });
  hidePermission();
}

async function refreshStatus() {
  state.status = await api("/api/status");
  $("workspace-path").textContent = state.status.workspace;
  $("workspace-path").title = state.status.workspace;
  const model = state.status.model || "unconfigured";
  $("model-line").textContent = `${state.status.provider} · ${model}`;
  $("chat-title").textContent = state.status.session?.title || "New chat";
  if (state.status.needs_setup) {
    $("setup-modal").classList.remove("hidden");
  } else {
    $("setup-modal").classList.add("hidden");
  }
  renderUpdate(state.status.update || {});
}

function renderUpdate(update) {
  const node = $("update-status");
  const apply = $("apply-update");
  if (!node) return;
  if (update.error) {
    node.textContent = "Update check failed";
    apply.classList.add("hidden");
    return;
  }
  const short = (update.local_sha || "").slice(0, 7);
  if (update.update_available) {
    node.textContent = `Update available from GoDeskio/Clawd-Code${short ? " · local " + short : ""}`;
    apply.classList.remove("hidden");
  } else {
    node.textContent = short ? `Up to date · ${short}` : "GoDeskio/Clawd-Code";
    apply.classList.add("hidden");
  }
}

async function refreshSessions() {
  const data = await api("/api/sessions");
  state.sessions = data.sessions || [];
  const current = data.current?.session_id;
  const list = $("session-list");
  list.innerHTML = "";
  for (const session of state.sessions) {
    const btn = document.createElement("button");
    btn.className = `session-item${session.session_id === current ? " active" : ""}`;
    btn.innerHTML = `<strong>${session.title || session.session_id}</strong><div class="muted">${session.provider} · ${session.message_count} msgs</div>`;
    btn.addEventListener("click", async () => {
      await api("/api/sessions/load", { method: "POST", body: JSON.stringify({ session_id: session.session_id }) });
      $("transcript").innerHTML = "";
      addBubble("system", `Loaded session ${session.session_id}`);
      await refreshStatus();
      await refreshSessions();
    });
    list.appendChild(btn);
  }
}

async function refreshCommands() {
  const data = await api("/api/commands");
  state.commands = data.commands || [];
}

function fillProviders(select, catalog, selected) {
  select.innerHTML = "";
  for (const [name, info] of Object.entries(catalog)) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = `${info.label} (${name})`;
    if (name === selected) opt.selected = true;
    select.appendChild(opt);
  }
}

async function prepareSetup() {
  const catalog = await api("/api/providers");
  fillProviders($("setup-provider"), catalog, state.status?.provider || "anthropic");
  fillProviders($("settings-provider"), catalog, state.status?.provider || "anthropic");
  const applyDefaults = (providerEl, urlEl, modelEl) => {
    const info = catalog[providerEl.value];
    if (!info) return;
    urlEl.value = info.default_base_url;
    modelEl.value = info.default_model;
  };
  applyDefaults($("setup-provider"), $("setup-url"), $("setup-model"));
  $("setup-provider").onchange = () => applyDefaults($("setup-provider"), $("setup-url"), $("setup-model"));
  $("settings-model").value = state.status?.model || "";
}

function renderAttachments() {
  const box = $("attachments");
  box.innerHTML = "";
  for (const item of state.attachments) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = item.name + (item.omitted ? ` (${item.reason})` : "");
    box.appendChild(chip);
  }
}

async function addAttachmentPayload(payload) {
  const data = await api("/api/attachments", {
    method: "POST",
    body: JSON.stringify({ attachments: payload }),
  });
  state.attachments.push(...(data.attachments || []));
  renderAttachments();
}

function renderPalette(query) {
  const q = (query || "").toLowerCase();
  const matches = state.commands.filter((item) => {
    const hay = `${item.name} ${item.description || ""}`.toLowerCase();
    return !q || hay.includes(q);
  }).slice(0, 20);
  const palette = $("slash-palette");
  palette.innerHTML = "";
  if (!matches.length) {
    palette.classList.add("hidden");
    return;
  }
  for (const item of matches) {
    const btn = document.createElement("button");
    btn.innerHTML = `<strong>${item.name}</strong> <span class="muted">${item.description || ""}</span>`;
    btn.addEventListener("click", () => {
      $("prompt").value = item.name + " ";
      palette.classList.add("hidden");
      $("prompt").focus();
    });
    palette.appendChild(btn);
  }
  palette.classList.remove("hidden");
}

function watchJob(jobId) {
  state.currentJob = jobId;
  let assistant = null;
  const source = new EventSource(`/api/events?job_id=${encodeURIComponent(jobId)}`);
  source.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    if (event.type === "stream_end") {
      source.close();
      setBusy(false);
      refreshSessions();
      refreshStatus();
      return;
    }
    if (event.type === "user") {
      return;
    }
    if (event.type === "token") {
      if (!assistant) assistant = addBubble("assistant", "");
      assistant.dataset.raw = (assistant.dataset.raw || "") + event.text;
      assistant.innerHTML = renderMarkdown(assistant.dataset.raw);
      assistant.scrollIntoView({ block: "end" });
      return;
    }
    if (event.type === "tool_use" || event.type === "tool_result" || event.type === "tool_error") {
      addToolCard(event);
      return;
    }
    if (event.type === "permission_request") {
      showPermission(event);
      if (native?.notify) native.notify("Jonathan Ai needs permission", event.message || event.tool_name);
      return;
    }
    if (event.type === "done") {
      if (event.text && !(assistant && assistant.dataset.raw)) {
        addBubble(event.kind === "command" ? "system" : "assistant", event.text);
      }
      if (native?.notify && event.kind !== "command") {
        native.notify("Jonathan Ai finished", (event.text || "Done").slice(0, 120));
      }
      return;
    }
    if (event.type === "error") {
      addBubble("system", event.error || "Error");
      if (event.needs_setup) $("setup-modal").classList.remove("hidden");
    }
  };
  source.onerror = () => {
    source.close();
    setBusy(false);
  };
}

async function sendMessage() {
  const text = $("prompt").value;
  if (!text.trim() && !state.attachments.length) return;
  addBubble("user", text || "(attachments)");
  $("prompt").value = "";
  $("slash-palette").classList.add("hidden");
  setBusy(true);
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        text,
        attachments: state.attachments.map((item) => ({
          kind: item.kind,
          path: item.path,
          text: item.text,
          name: item.name,
        })),
      }),
    });
    state.attachments = [];
    renderAttachments();
    watchJob(data.job_id);
  } catch (err) {
    setBusy(false);
    addBubble("system", err.message);
  }
}

function bindUi() {
  $("send").addEventListener("click", sendMessage);
  $("prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  $("prompt").addEventListener("input", () => {
    const value = $("prompt").value;
    if (value.startsWith("/")) renderPalette(value.slice(1));
    else $("slash-palette").classList.add("hidden");
  });
  $("new-chat").addEventListener("click", async () => {
    await api("/api/sessions", { method: "POST" });
    $("transcript").innerHTML = "";
    addBubble("system", "New chat. Pick a workspace and send a message.");
    await refreshStatus();
    await refreshSessions();
  });
  $("save-session").addEventListener("click", async () => {
    const summary = await api("/api/sessions/save", { method: "POST" });
    addBubble("system", `Saved ${summary.session_id}`);
    await refreshSessions();
  });
  $("pick-workspace").addEventListener("click", async () => {
    let path = "";
    if (native?.pickFolder) {
      path = await native.pickFolder();
    } else {
      path = window.prompt("Workspace folder path", state.status?.workspace || "") || "";
    }
    if (!path) return;
    await api("/api/workspace", { method: "POST", body: JSON.stringify({ path }) });
    await refreshStatus();
  });
  $("attach-files").addEventListener("click", async () => {
    if (native?.pickFiles) {
      const paths = await native.pickFiles();
      if (paths?.length) await addAttachmentPayload(paths.map((path) => ({ kind: "file", path })));
      return;
    }
    $("file-input").click();
  });
  $("file-input").addEventListener("change", async (event) => {
    const files = [...event.target.files];
    const payload = [];
    for (const file of files) {
      if (file.path) payload.push({ kind: "file", path: file.path });
      else payload.push({ kind: "text", name: file.name, text: await file.text() });
    }
    if (payload.length) await addAttachmentPayload(payload);
    event.target.value = "";
  });
  $("attach-clipboard").addEventListener("click", async () => {
    let text = "";
    if (native?.readClipboardText) text = await native.readClipboardText();
    else if (navigator.clipboard?.readText) text = await navigator.clipboard.readText();
    if (!text) return;
    await addAttachmentPayload([{ kind: "clipboard", text }]);
  });
  if (native?.captureScreenshot) {
    $("attach-screenshot").classList.remove("hidden");
    $("attach-screenshot").addEventListener("click", async () => {
      const path = await native.captureScreenshot();
      if (path) await addAttachmentPayload([{ kind: "screenshot", path }]);
    });
  }
  ["perm-allow", "perm-deny", "perm-always"].forEach((id) => {
    $(id).addEventListener("click", () => {
      const decision = id === "perm-allow" ? "allow" : id === "perm-deny" ? "deny" : "always";
      decidePermission(decision);
    });
  });
  $("setup-save").addEventListener("click", async () => {
    await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        provider: $("setup-provider").value,
        api_key: $("setup-key").value,
        base_url: $("setup-url").value,
        default_model: $("setup-model").value,
      }),
    });
    $("setup-key").value = "";
    await refreshStatus();
  });
  $("apply-update").addEventListener("click", async () => {
    $("update-status").textContent = "Updating from GoDeskio/Clawd-Code…";
    try {
      const result = await api("/api/update/apply", { method: "POST", body: "{}" });
      $("update-status").textContent = `Updated · ${(result.sha || "").slice(0, 7)} — restart the app`;
      $("apply-update").classList.add("hidden");
    } catch (err) {
      $("update-status").textContent = err.message;
    }
  });
  $("open-settings").addEventListener("click", () => $("settings-modal").classList.remove("hidden"));
  $("settings-close").addEventListener("click", () => $("settings-modal").classList.add("hidden"));
  $("settings-save").addEventListener("click", async () => {
    await api("/api/provider", {
      method: "POST",
      body: JSON.stringify({
        provider: $("settings-provider").value,
        model: $("settings-model").value,
      }),
    });
    $("settings-modal").classList.add("hidden");
    await refreshStatus();
  });

  const composer = document.querySelector(".composer");
  composer.addEventListener("dragover", (event) => {
    event.preventDefault();
    $("drop-hint").classList.remove("hidden");
  });
  composer.addEventListener("dragleave", () => $("drop-hint").classList.add("hidden"));
  composer.addEventListener("drop", async (event) => {
    event.preventDefault();
    $("drop-hint").classList.add("hidden");
    const files = [...event.dataTransfer.files];
    const payload = [];
    for (const file of files) {
      if (file.path) payload.push({ kind: "file", path: file.path });
      else payload.push({ kind: "text", name: file.name, text: await file.text() });
    }
    if (payload.length) await addAttachmentPayload(payload);
  });
}

async function boot() {
  bindUi();
  await refreshStatus();
  await prepareSetup();
  await refreshSessions();
  await refreshCommands();
  addBubble("system", "Jonathan Ai is using the existing Python agent loop. Destructive and network tools will ask before they run.");
  try {
    const update = await api("/api/update/check", { method: "POST", body: "{}" });
    renderUpdate(update);
  } catch (_err) {
    renderUpdate({ error: "offline" });
  }
}

boot().catch((err) => addBubble("system", err.message));
