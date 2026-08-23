const native = window.clawdDesktop || null;
const state = {
  status: null,
  commands: [],
  sessions: [],
  attachments: [],
  pendingPermission: null,
  sending: false,
  currentJob: null,
  menuSessionId: null,
  renamingId: null,
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

function renderTranscript(messages) {
  $("transcript").innerHTML = "";
  for (const msg of messages || []) {
    const role = msg.role || "assistant";
    const text = typeof msg.content === "string" ? msg.content : "";
    if (!text.trim()) continue;
    addBubble(role, text);
  }
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
  if ($("app-version")) {
    const ver = state.status.version || "0.2.7";
    $("app-version").textContent = `v${ver} · standalone`;
    document.title = `Jonathan Ai ${ver}`;
  }
  renderUsage(state.status.session);
  const git = state.status.git || {};
  if ($("git-line")) {
    $("git-line").textContent = git.is_repo
      ? `${git.branch || "detached"} · default ${git.default_branch || "main"}${git.dirty ? " · dirty" : ""}`
      : "Not a git repo";
  }
  renderConnectorStatus(state.status.connectors || {});
  if (state.status.needs_setup) {
    $("setup-modal").classList.remove("hidden");
  } else {
    $("setup-modal").classList.add("hidden");
  }
  renderUpdate(state.status.update || {});
}

function formatActivity(iso) {
  if (!iso) return "No activity yet";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "No activity yet";
  const delta = Date.now() - date.getTime();
  if (delta < 60_000) return "Just now";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} min ago`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} h ago`;
  return date.toLocaleDateString();
}

function renderUsage(session) {
  const node = $("usage-line");
  if (!node) return;
  const usage = (session && session.token_usage) || {};
  const inn = usage.input_tokens || 0;
  const out = usage.output_tokens || 0;
  const total = usage.total_tokens || inn + out;
  node.textContent = `${inn} in · ${out} out · ${total} total (informational)`;
  node.title = "Token counts for this chat only. Informational — never a quota, paywall, or purchase path.";
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

function hideSessionMenu() {
  const menu = $("session-menu");
  if (menu) menu.classList.add("hidden");
  state.menuSessionId = null;
}

function showSessionMenu(event, sessionId) {
  const menu = $("session-menu");
  if (!menu) return;
  state.menuSessionId = sessionId;
  menu.classList.remove("hidden");
  const pad = 8;
  const left = Math.min(event.clientX, window.innerWidth - menu.offsetWidth - pad);
  const top = Math.min(event.clientY, window.innerHeight - menu.offsetHeight - pad);
  menu.style.left = `${Math.max(pad, left)}px`;
  menu.style.top = `${Math.max(pad, top)}px`;
}

async function commitRename(sessionId, title) {
  const cleaned = String(title || "").trim();
  if (!cleaned) {
    state.renamingId = null;
    await refreshSessions();
    return;
  }
  await api("/api/sessions/rename", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, title: cleaned }),
  });
  state.renamingId = null;
  await refreshStatus();
  await refreshSessions();
}

function startInlineRename(session) {
  state.renamingId = session.session_id;
  hideSessionMenu();
  refreshSessions();
}

async function refreshSessions() {
  const data = await api("/api/sessions");
  state.sessions = data.sessions || [];
  const current = data.current?.session_id;
  const list = $("session-list");
  list.innerHTML = "";
  for (const session of state.sessions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `session-item${session.session_id === current ? " active" : ""}`;
    btn.dataset.sessionId = session.session_id;
    const tokens = session.token_usage?.total_tokens || 0;
    const title = session.title || session.session_id;
    if (state.renamingId === session.session_id) {
      btn.innerHTML = `<input class="session-rename" type="text" maxlength="120" value="" /><div class="muted">${formatActivity(session.updated_at)} · ${tokens} tok</div>`;
      const input = btn.querySelector("input");
      input.value = title;
      input.addEventListener("click", (event) => event.stopPropagation());
      input.addEventListener("keydown", async (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          await commitRename(session.session_id, input.value);
        } else if (event.key === "Escape") {
          event.preventDefault();
          state.renamingId = null;
          await refreshSessions();
        }
      });
      input.addEventListener("blur", () => {
        if (state.renamingId === session.session_id) {
          commitRename(session.session_id, input.value);
        }
      });
      queueMicrotask(() => {
        input.focus();
        input.select();
      });
    } else {
      const heading = document.createElement("strong");
      heading.className = "session-title";
      heading.textContent = title;
      const meta = document.createElement("div");
      meta.className = "muted";
      meta.textContent = `${formatActivity(session.updated_at)} · ${tokens} tok`;
      btn.appendChild(heading);
      btn.appendChild(meta);
    }
    btn.addEventListener("click", async () => {
      if (state.renamingId === session.session_id) return;
      const loaded = await api("/api/sessions/load", { method: "POST", body: JSON.stringify({ session_id: session.session_id }) });
      renderTranscript(loaded.messages || []);
      await refreshStatus();
      await refreshSessions();
      $("prompt").focus();
    });
    btn.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      startInlineRename(session);
    });
    btn.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      showSessionMenu(event, session.session_id);
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

function fillModelList(listId, models) {
  const list = $(listId);
  if (!list) return;
  list.innerHTML = "";
  for (const name of models || []) {
    const opt = document.createElement("option");
    opt.value = name;
    list.appendChild(opt);
  }
}

function bindConnectorForm(prefix, catalog) {
  const providerEl = $(`${prefix}-provider`);
  const apply = () => {
    const info = catalog[providerEl.value] || {};
    const help = $(`${prefix}-help`);
    if (help) help.textContent = info.help || "";
    const keyLabel = $(`${prefix}-key-label`);
    if (keyLabel) keyLabel.textContent = info.token_label || "API key";
    const keyWrap = $(`${prefix}-key-wrap`);
    if (keyWrap) keyWrap.classList.toggle("hidden", false);
    const urlEl = $(`${prefix}-url`);
    const modelEl = $(`${prefix}-model`);
    if (urlEl && (!urlEl.value || urlEl.dataset.kind !== info.kind)) urlEl.value = info.default_base_url || "";
    if (urlEl) urlEl.dataset.kind = info.kind || "";
    if (modelEl && !modelEl.value) modelEl.value = info.default_model || "";
    fillModelList(`${prefix}-model-list`, info.available_models || []);
    const hf = $(`${prefix}-hf`);
    const local = $(`${prefix}-local`);
    if (hf) hf.classList.toggle("hidden", info.kind !== "huggingface");
    if (local) local.classList.toggle("hidden", info.kind !== "local");
  };
  providerEl.onchange = apply;
  apply();
}

function renderConnectorStatus(connectors) {
  if (!connectors) return;
  if ($("gh-status") && connectors.github) {
    $("gh-status").textContent = connectors.github.configured
      ? `Connected ${connectors.github.login || ""} · owner ${connectors.github.owner}`
      : "Not connected";
    if ($("gh-owner") && connectors.github.owner) $("gh-owner").value = connectors.github.owner;
  }
  if ($("gl-status") && connectors.gitlab) {
    $("gl-status").textContent = connectors.gitlab.configured
      ? `Connected ${connectors.gitlab.login || ""} · ${connectors.gitlab.host}`
      : "Not connected";
    if (connectors.gitlab.host) $("gl-host").value = connectors.gitlab.host;
    if (connectors.gitlab.owner) $("gl-owner").value = connectors.gitlab.owner;
  }
  renderMcpList(connectors.mcp || []);
  renderAgentList(connectors.agents || []);
}

function renderMcpList(items) {
  const box = $("mcp-list");
  if (!box) return;
  box.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "scan-item";
    const label = document.createElement("div");
    label.textContent = `${item.name} · ${item.transport}${item.enabled ? "" : " · disabled"}`;
    const actions = document.createElement("div");
    actions.className = "row";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "ghost";
    toggle.textContent = item.enabled ? "Disable" : "Enable";
    toggle.addEventListener("click", async () => {
      await api("/api/connectors/mcp/enable", {
        method: "POST",
        body: JSON.stringify({ id: item.id || item.name, enabled: !item.enabled }),
      });
      await refreshStatus();
    });
    const test = document.createElement("button");
    test.type = "button";
    test.className = "ghost";
    test.textContent = "Test";
    test.addEventListener("click", async () => {
      try {
        const data = await api("/api/connectors/mcp/test", {
          method: "POST",
          body: JSON.stringify({ id: item.id, name: item.name }),
        });
        $("mcp-status").textContent = `Tools: ${(data.tools || []).join(", ") || "(none listed)"}`;
      } catch (err) {
        $("mcp-status").textContent = err.message;
      }
    });
    actions.append(toggle, test);
    row.append(label, actions);
    box.appendChild(row);
  }
}

function renderAgentList(items) {
  const box = $("agent-list");
  if (!box) return;
  box.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "scan-item";
    const label = document.createElement("div");
    label.textContent = `${item.name} · ${item.base_url}${item.enabled === false ? " · disabled" : ""}`;
    const actions = document.createElement("div");
    actions.className = "row";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "ghost";
    toggle.textContent = item.enabled === false ? "Enable" : "Disable";
    toggle.addEventListener("click", async () => {
      await api("/api/connectors/agents/enable", {
        method: "POST",
        body: JSON.stringify({ id: item.id || item.name, enabled: item.enabled === false }),
      });
      await refreshStatus();
    });
    const test = document.createElement("button");
    test.type = "button";
    test.className = "ghost";
    test.textContent = "Test";
    test.addEventListener("click", async () => {
      try {
        const data = await api("/api/connectors/agents/test", {
          method: "POST",
          body: JSON.stringify({ id: item.id, name: item.name }),
        });
        const tools = (data.tools || []).map((entry) => entry.name || entry).join(", ");
        $("agent-status").textContent = `Reachable. Tools: ${tools || "(chat completions only)"}`;
      } catch (err) {
        $("agent-status").textContent = err.message;
      }
    });
    actions.append(toggle, test);
    row.append(label, actions);
    box.appendChild(row);
  }
}

function renderRepoList(box, repos, forge) {
  box.innerHTML = "";
  for (const repo of repos) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "scan-item";
    btn.textContent = repo.full_name || repo.clone_url;
    btn.addEventListener("click", async () => {
      try {
        await api("/api/git/clone", {
          method: "POST",
          body: JSON.stringify({ forge, repo: repo.full_name || repo.clone_url }),
        });
        addBubble("system", `Cloned ${repo.full_name} and opened it.`);
        await refreshStatus();
      } catch (err) {
        addBubble("system", err.message);
      }
    });
    box.appendChild(btn);
  }
}

function renderScanResults(box, endpoints, onPick) {
  box.innerHTML = "";
  for (const item of endpoints || []) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `scan-item${item.reachable ? "" : " muted"}`;
    const models = (item.models || []).slice(0, 6).join(", ") || (item.reachable ? "reachable" : (item.error || "offline"));
    btn.innerHTML = `<strong>${item.label}</strong><div class="muted">${item.base_url}<br>${models}</div>`;
    btn.disabled = !item.reachable;
    btn.addEventListener("click", () => onPick(item));
    box.appendChild(btn);
  }
}

async function prepareSetup() {
  const catalog = await api("/api/providers");
  state.catalog = catalog;
  fillProviders($("setup-provider"), catalog, state.status?.provider || "anthropic");
  fillProviders($("settings-provider"), catalog, state.status?.provider || "anthropic");
  bindConnectorForm("setup", catalog);
  bindConnectorForm("settings", catalog);
  const saved = state.status?.config?.providers?.[state.status?.provider] || {};
  $("settings-url").value = saved.base_url || catalog[state.status?.provider]?.default_base_url || "";
  $("settings-model").value = state.status?.model || saved.default_model || "";
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
    if (event.type === "workers_started") {
      addBubble("system", "Planning isolated workers. Chats stay separate; they share memory only.");
      return;
    }
    if (event.type === "worker") {
      addToolCard({
        tool_name: event.title || event.worker_id || "worker",
        summary: event.answer || event.prompt || "",
      });
      return;
    }
    if (event.type === "permission_request") {
      showPermission(event);
      if (native?.notify) native.notify("Jonathan Ai needs permission", event.message || event.tool_name);
      return;
    }
    if (event.type === "done") {
      if (Array.isArray(event.messages)) {
        renderTranscript(event.messages);
        if (event.text) addBubble("system", event.text);
      } else if (event.text && !(assistant && assistant.dataset.raw)) {
        addBubble(event.kind === "command" ? "system" : "assistant", event.text);
      }
      if (event.session) {
        renderUsage(event.session);
        refreshStatus();
        refreshSessions();
      } else if (event.usage) {
        renderUsage({ token_usage: event.usage });
      }
      if (native?.notify && event.kind !== "command") {
        native.notify("Jonathan Ai finished", (event.text || "Done").slice(0, 120));
      }
      return;
    }
    if (event.type === "error") {
      addBubble("system", event.error || "Error");
      if (event.needs_setup) $("setup-modal").classList.remove("hidden");
      if (event.provider_limit && $("settings-modal")) {
        $("settings-modal").classList.remove("hidden");
      }
    }
  };
  source.onerror = () => {
    source.close();
    setBusy(false);
  };
}

async function sendMessage(path = "/api/chat") {
  const text = $("prompt").value;
  if (!text.trim() && !state.attachments.length) return;
  addBubble("user", text || "(attachments)");
  $("prompt").value = "";
  $("slash-palette").classList.add("hidden");
  setBusy(true);
  try {
    const data = await api(path, {
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
  $("send").addEventListener("click", () => sendMessage("/api/chat"));
  $("workers")?.addEventListener("click", () => sendMessage("/api/multi-agent"));
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
    const created = await api("/api/sessions", { method: "POST" });
    renderTranscript(created.messages || []);
    await refreshStatus();
    await refreshSessions();
    $("chat-title").textContent = created.title || "New chat";
    $("prompt").value = "";
    $("prompt").focus();
  });
  $("session-menu-rename").addEventListener("click", () => {
    const session = state.sessions.find((item) => item.session_id === state.menuSessionId);
    hideSessionMenu();
    if (session) startInlineRename(session);
  });
  document.addEventListener("click", (event) => {
    if (!$("session-menu")?.contains(event.target)) hideSessionMenu();
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
    try {
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
    } catch (err) {
      addBubble("system", err.message);
    }
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
    try {
      const provider = $("settings-provider").value;
      const key = $("settings-key").value;
      const info = (state.catalog || {})[provider] || {};
      const configured = Boolean(state.status?.config?.providers?.[provider]?.configured);
      if (key || info.kind === "local" || !configured) {
        await api("/api/login", {
          method: "POST",
          body: JSON.stringify({
            provider,
            api_key: key,
            base_url: $("settings-url").value,
            default_model: $("settings-model").value,
          }),
        });
      } else {
        await api("/api/provider", {
          method: "POST",
          body: JSON.stringify({ provider, model: $("settings-model").value }),
        });
      }
      $("settings-key").value = "";
      $("settings-modal").classList.add("hidden");
      await refreshStatus();
    } catch (err) {
      addBubble("system", err.message);
    }
  });

  const wireHf = (prefix) => {
    const status = $(`${prefix}-hf-status`);
    const token = () => $(`${prefix}-key`).value;
    $(`${prefix}-hf-test`).addEventListener("click", async () => {
      status.textContent = "Testing Hugging Face token…";
      try {
        const data = await api("/api/connectors/hf/test", {
          method: "POST",
          body: JSON.stringify({ api_key: token() }),
        });
        status.textContent = data.message || "Connected.";
      } catch (err) {
        status.textContent = err.message;
      }
    });
    $(`${prefix}-hf-models`).addEventListener("click", async () => {
      status.textContent = "Loading Hub models…";
      try {
        const data = await api("/api/connectors/hf/models", {
          method: "POST",
          body: JSON.stringify({ api_key: token() }),
        });
        const ids = (data.models || []).map((item) => item.id || item);
        fillModelList(`${prefix}-model-list`, ids);
        if (ids[0] && !$(`${prefix}-model`).value) $(`${prefix}-model`).value = ids[0];
        status.textContent = `Loaded ${ids.length} Hub models. Pick one, then Save.`;
      } catch (err) {
        status.textContent = err.message;
      }
    });
    $(`${prefix}-hf-cache`).addEventListener("click", async () => {
      const repo = $(`${prefix}-model`).value;
      status.textContent = `Downloading ${repo} into ~/.clawd/hf-cache…`;
      try {
        const data = await api("/api/connectors/hf/cache", {
          method: "POST",
          body: JSON.stringify({ api_key: token(), repo_id: repo }),
        });
        status.textContent = data.message || data.path;
      } catch (err) {
        status.textContent = err.message;
      }
    });
  };
  const wireLocal = (prefix) => {
    const box = $(`${prefix}-local-results`);
    $(`${prefix}-local-scan`).addEventListener("click", async () => {
      box.textContent = "Scanning loopback ports…";
      try {
        const extra = $(`${prefix}-url`).value;
        const data = await api("/api/connectors/local/scan", {
          method: "POST",
          body: JSON.stringify({ base_url: extra || "" }),
        });
        renderScanResults(box, data.endpoints, (item) => {
          $(`${prefix}-url`).value = item.base_url;
          fillModelList(`${prefix}-model-list`, item.models || []);
          if (item.models?.[0]) $(`${prefix}-model`).value = item.models[0];
        });
      } catch (err) {
        box.textContent = err.message;
      }
    });
    $(`${prefix}-local-models`).addEventListener("click", async () => {
      try {
        const data = await api("/api/connectors/local/models", {
          method: "POST",
          body: JSON.stringify({
            base_url: $(`${prefix}-url`).value,
            api_key: $(`${prefix}-key`).value,
          }),
        });
        fillModelList(`${prefix}-model-list`, data.models || []);
        if (data.models?.[0] && !$(`${prefix}-model`).value) $(`${prefix}-model`).value = data.models[0];
        box.textContent = data.models?.length ? `Found ${data.models.length} models.` : "No models listed.";
      } catch (err) {
        box.textContent = err.message;
      }
    });
  };
  wireHf("setup");
  wireHf("settings");
  wireLocal("setup");
  wireLocal("settings");

  $("open-connectors").addEventListener("click", async () => {
    $("connectors-modal").classList.remove("hidden");
    await refreshStatus();
  });
  $("connectors-close").addEventListener("click", () => $("connectors-modal").classList.add("hidden"));
  $("open-repo").addEventListener("click", async () => {
    try {
      await api("/api/git/open", { method: "POST", body: "{}" });
      addBubble("system", "Opened the git workspace.");
      await refreshStatus();
    } catch (err) {
      addBubble("system", err.message);
    }
  });
  $("pull-repo").addEventListener("click", async () => {
    try {
      const data = await api("/api/git/pull", { method: "POST", body: "{}" });
      addBubble("system", `Pulled ${data.branch || "current branch"}.`);
      await refreshStatus();
    } catch (err) {
      addBubble("system", err.message);
    }
  });
  $("publish-repo").addEventListener("click", async () => {
    const name = window.prompt("Repository name", (state.status?.workspace || "").split(/[\\/]/).pop() || "jonathan-project");
    if (!name) return;
    const forge = window.prompt("Forge: github or gitlab", "github") || "github";
    const branch = window.prompt("Feature branch (leave blank to use jonathan/<name>; default branches are refused unless named)", "") || "";
    try {
      const result = await api("/api/git/publish", {
        method: "POST",
        body: JSON.stringify({ name, forge, branch: branch || null, owner: $("gh-owner")?.value || undefined }),
      });
      const url = result.review?.html_url || result.repo?.html_url || "done";
      addBubble("system", `Published ${result.repo?.full_name || name} on ${result.forge}. ${url}`);
      await refreshStatus();
    } catch (err) {
      addBubble("system", err.message);
    }
  });
  $("gh-save").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/github/login", {
        method: "POST",
        body: JSON.stringify({ token: $("gh-token").value, owner: $("gh-owner").value || "GoDeskio" }),
      });
      $("gh-token").value = "";
      $("gh-status").textContent = `Connected as ${data.login || "GitHub user"}`;
    } catch (err) {
      $("gh-status").textContent = err.message;
    }
  });
  $("gl-save").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/gitlab/login", {
        method: "POST",
        body: JSON.stringify({ token: $("gl-token").value, owner: $("gl-owner").value, host: $("gl-host").value }),
      });
      $("gl-token").value = "";
      $("gl-status").textContent = `Connected as ${data.login || "GitLab user"}`;
    } catch (err) {
      $("gl-status").textContent = err.message;
    }
  });
  $("gh-repos").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/github/repos");
      renderRepoList($("gh-repos-list"), data.repos || [], "github");
    } catch (err) {
      $("gh-status").textContent = err.message;
    }
  });
  $("gl-projects").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/gitlab/projects");
      renderRepoList($("gl-projects-list"), data.projects || [], "gitlab");
    } catch (err) {
      $("gl-status").textContent = err.message;
    }
  });
  $("gh-device").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/github/device/start", {
        method: "POST",
        body: JSON.stringify({ client_id: $("gh-client").value }),
      });
      $("gh-device-status").textContent = data.message || JSON.stringify(data);
    } catch (err) {
      $("gh-device-status").textContent = err.message;
    }
  });
  $("gh-poll").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/github/device/poll", { method: "POST", body: "{}" });
      $("gh-device-status").textContent = data.pending ? "Still waiting…" : `Connected as ${data.login}`;
    } catch (err) {
      $("gh-device-status").textContent = err.message;
    }
  });
  $("gl-device").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/gitlab/device/start", {
        method: "POST",
        body: JSON.stringify({ client_id: $("gl-client").value, host: $("gl-host").value }),
      });
      $("gl-device-status").textContent = data.message || JSON.stringify(data);
    } catch (err) {
      $("gl-device-status").textContent = err.message;
    }
  });
  $("gl-poll").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/gitlab/device/poll", { method: "POST", body: "{}" });
      $("gl-device-status").textContent = data.pending ? "Still waiting…" : `Connected as ${data.login}`;
    } catch (err) {
      $("gl-device-status").textContent = err.message;
    }
  });
  $("mcp-save").addEventListener("click", async () => {
    try {
      const args = ($("mcp-args").value || "").trim().split(/\s+/).filter(Boolean);
      const data = await api("/api/connectors/mcp", {
        method: "POST",
        body: JSON.stringify({
          name: $("mcp-name").value,
          command: $("mcp-command").value,
          args,
          url: $("mcp-url").value,
          token: $("mcp-token").value,
        }),
      });
      $("mcp-status").textContent = "Saved on this machine.";
      renderMcpList(data.mcp || []);
    } catch (err) {
      $("mcp-status").textContent = err.message;
    }
  });
  $("mcp-test").addEventListener("click", async () => {
    try {
      const args = ($("mcp-args").value || "").trim().split(/\s+/).filter(Boolean);
      const data = await api("/api/connectors/mcp/test", {
        method: "POST",
        body: JSON.stringify({
          name: $("mcp-name").value,
          command: $("mcp-command").value,
          args,
          url: $("mcp-url").value,
          token: $("mcp-token").value,
        }),
      });
      $("mcp-status").textContent = `Tools: ${(data.tools || []).join(", ") || "(none listed)"}`;
    } catch (err) {
      $("mcp-status").textContent = err.message;
    }
  });
  $("agent-save").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/agents", {
        method: "POST",
        body: JSON.stringify({
          name: $("agent-name").value,
          base_url: $("agent-url").value,
          api_key: $("agent-key").value,
        }),
      });
      $("agent-status").textContent = "Saved on this machine.";
      renderAgentList(data.agents || []);
    } catch (err) {
      $("agent-status").textContent = err.message;
    }
  });
  $("agent-test").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/agents/test", {
        method: "POST",
        body: JSON.stringify({
          name: $("agent-name").value,
          base_url: $("agent-url").value,
          api_key: $("agent-key").value,
        }),
      });
      const tools = (data.tools || []).map((item) => item.name || item).join(", ");
      $("agent-status").textContent = `Reachable. Tools: ${tools || "(chat completions only)"}`;
    } catch (err) {
      $("agent-status").textContent = err.message;
    }
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
  try {
    const current = await api("/api/sessions/messages");
    renderTranscript(current.messages || []);
  } catch (_err) {
    $("transcript").innerHTML = "";
  }
  addBubble("system", "Jonathan Ai is the agent. Chats persist on this machine. New chat starts empty. Shared memory is local only.");
  try {
    const update = await api("/api/update/check", { method: "POST", body: "{}" });
    renderUpdate(update);
  } catch (_err) {
    renderUpdate({ error: "offline" });
  }
}

boot().catch((err) => addBubble("system", err.message));
