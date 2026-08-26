const native = window.clawdDesktop || null;
const state = {
  status: null,
  commands: [],
  sessions: [],
  attachments: [],
  pendingPermission: null,
  permissionQueue: [],
  sending: false,
  currentJob: null,
  currentSessionId: null,
  activeJobs: new Map(),
  pendingSessions: new Set(),
  changedSessions: new Set(),
  menuSessionId: null,
  renamingId: null,
  projectChanged: false,
  previewOpen: false,
  selectedExternalId: null,
  externalOauth: null,
  agentProfiles: [],
  librarySkills: [],
  selectedSkill: null,
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

function appendConversationImage(target, image) {
  const source = image?.source || {};
  const previewUrl = image?.view_url || image?.preview_url || (source.data
    ? `data:${source.media_type || image.media_type || "image/png"};base64,${source.data}`
    : image?.download_url);
  if (!previewUrl) return;
  const name = image?.name || "conversation-image.png";
  const frame = document.createElement("figure");
  frame.className = "conversation-image";
  const previewLink = document.createElement("a");
  previewLink.href = previewUrl;
  previewLink.target = "_blank";
  previewLink.rel = "noopener";
  previewLink.title = `Open ${name}`;
  const preview = document.createElement("img");
  preview.className = "conversation-image-preview";
  preview.src = previewUrl;
  preview.alt = name;
  preview.loading = "lazy";
  previewLink.appendChild(preview);
  const caption = document.createElement("figcaption");
  const label = document.createElement("span");
  label.textContent = image?.caption || name;
  const download = document.createElement("a");
  download.className = "conversation-image-download";
  download.href = image?.download_url || previewUrl;
  download.download = name;
  download.textContent = "Download";
  caption.append(label, download);
  frame.append(previewLink, caption);
  target.appendChild(frame);
}

function appendConversationArtifact(target, artifact) {
  if (!artifact?.download_url) return;
  if (artifact.is_image || /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(artifact.name || "")) {
    appendConversationImage(target, artifact);
    return;
  }
  const link = document.createElement("a");
  link.className = "tool-download";
  link.href = artifact.download_url;
  link.download = artifact.name || "download";
  link.textContent = `Download ${artifact.name || "file"}`;
  target.appendChild(link);
}

function appendConversationAttachment(target, attachment) {
  if (attachment?.is_image && (attachment.preview_url || attachment.download_url)) {
    appendConversationImage(target, attachment);
    return;
  }
  if (!attachment?.download_url) return;
  appendConversationArtifact(target, {
    ...attachment,
    is_image: false,
    name: attachment.name || "attachment",
  });
}

function addArtifactBubble(artifacts, caption = "Generated file") {
  const items = Array.isArray(artifacts) ? artifacts : [artifacts];
  const valid = items.filter((item) => item?.download_url);
  if (!valid.length) return null;
  const bubble = addBubble("assistant", caption, "media-bubble");
  for (const artifact of valid) appendConversationArtifact(bubble, artifact);
  return bubble;
}

function newSkillSource(name = "new-skill") {
  return `---\nname: "${name}"\ndescription: "Describe the specific reusable workflow and when it applies."\n---\n\n# ${name}\n\nWrite concise, actionable instructions here. Keep credentials and one-off chat details out of skills.\n`;
}

function selectLibrarySkill(skill) {
  state.selectedSkill = skill?.name || null;
  $("skill-name").value = skill?.name || "";
  $("skill-content").value = skill?.content || "";
  $("skill-status").textContent = skill?.valid === false
    ? (skill.errors || []).join(" ")
    : "Changes are UTF-8 and become available to every agent immediately.";
  for (const card of $("skills-list").querySelectorAll(".skill-card")) {
    card.classList.toggle("active", card.dataset.name === state.selectedSkill);
  }
}

function renderSkillLibrary(data) {
  state.librarySkills = data.skills || [];
  $("skills-path").textContent = data.path || "—";
  $("skills-path").title = data.path || "";
  const list = $("skills-list");
  list.innerHTML = "";
  for (const skill of state.librarySkills) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "skill-card";
    card.dataset.name = skill.name;
    const title = document.createElement("strong");
    title.textContent = skill.name;
    const description = document.createElement("small");
    description.textContent = skill.description || "No description";
    const validity = document.createElement("small");
    validity.textContent = skill.valid ? `v${skill.version || "1.0.0"} · ready` : "Needs attention";
    card.append(title, description, validity);
    card.addEventListener("click", () => selectLibrarySkill(skill));
    list.appendChild(card);
  }
  const selected = state.librarySkills.find((item) => item.name === state.selectedSkill);
  if (selected) selectLibrarySkill(selected);
  else if (state.librarySkills.length) selectLibrarySkill(state.librarySkills[0]);
  else selectLibrarySkill(null);
}

async function refreshSkillLibrary() {
  const data = await api("/api/skills/library");
  renderSkillLibrary(data);
  return data;
}

function renderEccCatalog(data) {
  state.eccCatalog = data || {};
  const counts = data?.counts || {};
  const revision = String(data?.revision || "").slice(0, 8);
  $("ecc-summary").textContent = data?.available
    ? `${counts.skills || 0} skills · ${counts.agents || 0} agents · ${counts.enabled || 0} enabled${revision ? ` · ${revision}` : ""}`
    : "Not synchronized";
  const query = ($("ecc-filter")?.value || "").trim().toLowerCase();
  const list = $("ecc-skill-list");
  list.innerHTML = "";
  for (const skill of (data?.skills || []).filter((item) => !query || `${item.name} ${item.description}`.toLowerCase().includes(query)).slice(0, 300)) {
    const card = document.createElement("div");
    card.className = "ecc-skill-card";
    const label = document.createElement("span");
    label.textContent = skill.name;
    label.title = skill.description || skill.name;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = !skill.installed ? "Import" : (skill.enabled ? "Disable" : "Enable");
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const body = !skill.installed
          ? { action: "import", skills: [skill.name], agents: [], enable: [skill.name] }
          : { action: skill.enabled ? "disable" : "enable", skills: [skill.name] };
        const result = await api("/api/integrations/ecc", { method: "POST", body: JSON.stringify(body) });
        renderEccCatalog(result.catalog || result);
      } catch (err) { $("skill-status").textContent = err.message; }
      finally { button.disabled = false; }
    });
    card.append(label, button);
    list.appendChild(card);
  }
}

async function refreshEccCatalog() {
  const data = await api("/api/integrations/ecc");
  renderEccCatalog(data);
  return data;
}

function renderTranscript(messages) {
  $("transcript").innerHTML = "";
  for (const msg of messages || []) {
    const role = msg.role || "assistant";
    const content = msg.content;
    const text = typeof content === "string" ? content : (Array.isArray(content)
      ? content.filter((block) => block?.type === "text").map((block) => block.text || "").join("\n") : "");
    let bubble = text.trim() ? addBubble(role, text) : null;
    if (Array.isArray(content)) {
      for (const block of content) {
        if (block?.type === "image" && block.source?.data) {
          bubble = bubble || addBubble(role, "", "media-bubble");
          appendConversationImage(bubble, block);
        } else if (block?.type === "artifact") {
          bubble = bubble || addBubble(role, block.caption || "Generated file", "media-bubble");
          appendConversationArtifact(bubble, block);
        } else if (block?.type === "attachment") {
          bubble = bubble || addBubble(role, "", "media-bubble");
          appendConversationAttachment(bubble, block);
        }
      }
    }
  }
}

function updateBusyUi() {
  const sessionId = state.currentSessionId;
  const busy = state.pendingSessions.has(sessionId)
    || [...state.activeJobs.values()].some((job) => job.sessionId === sessionId);
  state.sending = busy;
  $("send").disabled = busy;
  $("workers").disabled = busy;
  const robot = $("working-robot");
  if (robot) robot.classList.toggle("hidden", !busy);
  if (!busy && $("working-progress")) $("working-progress").textContent = "Working…";
}

function setProgress(label) {
  if ($("working-progress") && label) $("working-progress").textContent = label;
}

function setBusy(busy, sessionId = state.currentSessionId) {
  if (!sessionId) return;
  if (busy) state.pendingSessions.add(sessionId);
  else state.pendingSessions.delete(sessionId);
  updateBusyUi();
}

function showPermission(event) {
  if (state.pendingPermission) {
    if (state.pendingPermission.request_id !== event.request_id
        && !state.permissionQueue.some((item) => item.request_id === event.request_id)) {
      state.permissionQueue.push(event);
    }
    return;
  }
  state.pendingPermission = event;
  const session = state.sessions.find((item) => item.session_id === event.session_id);
  const agentLabel = session?.title || String(event.session_id || "").slice(-8);
  $("perm-title").textContent = `Allow ${event.tool_name} for ${agentLabel || "this agent"}?`;
  $("perm-message").textContent = event.message || "";
  $("permission-banner").classList.remove("hidden");
}

function hidePermission() {
  state.pendingPermission = null;
  $("permission-banner").classList.add("hidden");
  const next = state.permissionQueue.shift();
  if (next) queueMicrotask(() => showPermission(next));
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
  state.currentSessionId = state.status.session?.session_id || state.currentSessionId;
  $("workspace-path").textContent = state.status.workspace;
  $("workspace-path").title = state.status.workspace;
  $("projects-path").textContent = state.status.projects_dir || "—";
  $("projects-path").title = state.status.projects_dir || "";
  const model = state.status.model || "unconfigured";
  $("model-line").textContent = `${state.status.provider} · ${model}`;
  $("chat-title").textContent = state.status.session?.title || "New chat";
  if ($("app-version")) {
    const ver = state.status.version || "0.4.7";
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
  renderFooocusStatus(state.status.fooocus || state.status.media?.image?.fooocus || {});
  renderTerminals(state.status.terminals || []);
  renderMediaStatus(state.status.media || {});
  renderAdminStatus(state.status.administrator || {});
  renderDeviceAccess(state.status.device_access || {});
  renderAutonomyStatus(state.status.earned_autonomy || {});
  renderFinanceStatus(state.status.business_finance || {});
  renderKronosStatus(state.status.kronos || {});
  renderPersonalFinanceStatus(state.status.personal_finance || {});
  renderCodeMemoryStatus(state.status.code_memory || {});
  renderProcoderStatus(state.status.procoder || {});
  renderDrawAiStatus(state.status.drawai || {});
  renderArtifacts(state.status.artifacts || []);
  if (state.status.needs_setup) {
    $("setup-modal").classList.remove("hidden");
  } else {
    $("setup-modal").classList.add("hidden");
  }
  renderUpdate(state.status.update || {});
  updateBusyUi();
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function renderArtifacts(items) {
  const box = $("artifact-list");
  if (!box) return;
  box.innerHTML = "";
  if (!items.length) {
    box.innerHTML = '<div class="muted">No packaged downloads yet.</div>';
    return;
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "artifact-item";
    const link = document.createElement("a");
    link.href = item.download_url;
    link.download = item.name;
    link.textContent = item.name;
    link.title = "Download packaged project";
    const size = document.createElement("span");
    size.className = "muted";
    size.textContent = formatBytes(item.size);
    row.append(link, size);
    box.appendChild(row);
  }
}

async function refreshArtifacts() {
  const data = await api("/api/artifacts");
  renderArtifacts(data.artifacts || []);
  return data.artifacts || [];
}

async function packageProject(automatic = false, sessionId = state.currentSessionId) {
  if (!automatic && sessionId === state.currentSessionId) addBubble("system", "Packaging the current project…");
  try {
    const data = await api("/api/artifacts/package", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
    renderArtifacts(data.artifacts || []);
    const artifact = data.artifact;
    if (artifact && sessionId === state.currentSessionId) {
      const node = addBubble("system", "");
      node.innerHTML = `Project ready: <a href="${artifact.download_url}" download="${artifact.name}">${artifact.name}</a> (${formatBytes(artifact.size)})`;
    }
  } catch (err) {
    if (!automatic) addBubble("system", err.message);
  }
}

async function refreshPreview() {
  const data = await api("/api/preview");
  $("preview-path").textContent = data.workspace || "Workspace";
  const files = $("preview-files");
  files.innerHTML = "";
  for (const name of data.files || []) {
    const row = document.createElement("div");
    row.className = "preview-file";
    row.textContent = name;
    row.title = name;
    files.appendChild(row);
  }
  const frame = $("preview-frame");
  const empty = $("preview-empty");
  if (data.entry_url) {
    frame.src = `${data.entry_url}?preview=${Date.now()}`;
    frame.classList.remove("hidden");
    empty.classList.add("hidden");
  } else {
    frame.removeAttribute("src");
    frame.classList.add("hidden");
    empty.classList.remove("hidden");
  }
  await refreshArtifacts();
}

async function setPreviewOpen(open) {
  state.previewOpen = open;
  $("app").classList.toggle("preview-open", open);
  $("preview-pane").classList.toggle("hidden", !open);
  $("toggle-preview").textContent = open ? "Hide preview" : "Preview";
  if (open) await refreshPreview();
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
  const approximation = usage.estimated ? "~" : "";
  node.textContent = `${approximation}${inn} in · ${approximation}${out} out · ${approximation}${total} total (informational)`;
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
    btn.className = `session-item${session.session_id === current ? " active" : ""}${session.agent_state === "working" ? " working" : ""}`;
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
      meta.textContent = `${session.agent_state === "working" ? "Agent working · " : ""}${formatActivity(session.updated_at)} · ${tokens} tok`;
      btn.appendChild(heading);
      btn.appendChild(meta);
    }
    btn.addEventListener("click", async () => {
      if (state.renamingId === session.session_id) return;
      await loadAgentSession(session.session_id);
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
  await refreshInstances();
}

async function loadAgentSession(sessionId) {
  const loaded = await api("/api/sessions/load", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
  state.currentSessionId = loaded.session_id;
  renderTranscript(loaded.messages || []);
  await refreshStatus();
  await refreshSessions();
  updateBusyUi();
  $("prompt").focus();
}

async function refreshInstances() {
  const box = $("instance-list");
  if (!box) return;
  const data = await api("/api/instances");
  const instances = data.instances || [];
  box.innerHTML = "";
  for (const instance of instances) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `instance-item ${instance.state || "idle"}`;
    button.title = `${instance.workspace || ""}\n${instance.state === "working" ? "Click to cross-view this running agent" : "Click to view this agent"}`;
    const dot = document.createElement("span");
    dot.className = "agent-dot";
    const copy = document.createElement("span");
    copy.className = "instance-copy";
    copy.textContent = `${instance.title || instance.session_id}${instance.state === "working" ? " · working" : ""}`;
    button.append(dot, copy);
    button.addEventListener("click", () => loadAgentSession(instance.session_id));
    box.appendChild(button);
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
    if ($("card-github-state")) $("card-github-state").textContent = connectors.github.configured ? `Connected · ${connectors.github.login || connectors.github.owner}` : "Not connected";
  }
  if ($("gl-status") && connectors.gitlab) {
    $("gl-status").textContent = connectors.gitlab.configured
      ? `Connected ${connectors.gitlab.login || ""} · ${connectors.gitlab.host}`
      : "Not connected";
    if (connectors.gitlab.host) $("gl-host").value = connectors.gitlab.host;
    if (connectors.gitlab.owner) $("gl-owner").value = connectors.gitlab.owner;
    if ($("card-gitlab-state")) $("card-gitlab-state").textContent = connectors.gitlab.configured ? `Connected · ${connectors.gitlab.login || connectors.gitlab.owner}` : "Not connected";
  }
  renderMcpList(connectors.mcp || []);
  renderAgentList(connectors.agents || []);
  renderExternalList(connectors.services || []);
  if ($("card-mcp-state")) $("card-mcp-state").textContent = connectors.mcp?.length ? `${connectors.mcp.length} saved` : "Add server";
  if ($("card-agents-state")) $("card-agents-state").textContent = connectors.agents?.length ? `${connectors.agents.length} saved` : "Add agent";
  if ($("card-external-state")) $("card-external-state").textContent = connectors.services?.length ? `${connectors.services.length} saved` : "Add service";
}

function openControl(panelId) {
  $("control-modal").classList.remove("hidden");
  for (const id of ["search-panel", "agent-hub-panel", "doctor-panel"]) $(id).classList.toggle("hidden", id !== panelId);
}

async function runHistorySearch() {
  const query = $("history-query").value.trim();
  const data = await api(`/api/search?q=${encodeURIComponent(query)}&limit=50`);
  $("history-meta").textContent = `${data.documents || 0} indexed entries · ${data.fts5 ? "fast full-text search" : "basic search"}`;
  const box = $("history-results");
  box.innerHTML = "";
  for (const hit of data.hits || []) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "scan-item search-hit";
    const title = document.createElement("strong");
    title.textContent = `${hit.title || "Memory"} · ${hit.role || hit.kind}`;
    const snippet = document.createElement("small");
    snippet.textContent = String(hit.snippet || "").replace(/[\[\]]/g, "");
    row.append(title, snippet);
    if (hit.session_id) row.addEventListener("click", async () => {
      try {
        await loadAgentSession(hit.session_id);
        $("control-modal").classList.add("hidden");
      } catch (_err) {
        addBubble("system", "That result is retained in shared memory; its original conversation is no longer available.");
      }
    });
    box.appendChild(row);
  }
  if (!(data.hits || []).length) box.innerHTML = '<div class="muted">No matching conversations or memory facts.</div>';
}

function clearProfileForm() {
  $("profile-id").value = "";
  $("profile-name").value = "";
  $("profile-workspace").value = state.status?.workspace || "";
  $("profile-instructions").value = "";
}

async function refreshAgentProfiles() {
  const data = await api("/api/agent-profiles");
  state.agentProfiles = data.agents || [];
  const floor = $("agent-floor");
  floor.innerHTML = "";
  const command = document.createElement("div"); command.className = "agent-desk command-desk"; command.innerHTML = '<span class="desk-light"></span><strong>Jonathan command</strong><small>Current conversation</small>'; floor.appendChild(command);
  for (const profile of state.agentProfiles) {
    const desk = document.createElement("button"); desk.type = "button"; desk.className = `agent-desk ${profile.state || "idle"}`;
    const tokens = profile.session?.token_usage || {}; desk.innerHTML = '<span class="desk-light"></span><strong></strong><small></small>';
    desk.querySelector("strong").textContent = profile.name || "Agent"; desk.querySelector("small").textContent = `${profile.state || "idle"} · ${(tokens.input_tokens || 0) + (tokens.output_tokens || 0)} tokens · ${profile.unread || 0} unread`;
    desk.addEventListener("click", async () => { const loaded=await api("/api/agent-profiles/open",{method:"POST",body:JSON.stringify({agent_id:profile.id})}); state.currentSessionId=loaded.session_id; renderTranscript(loaded.messages||[]); $("control-modal").classList.add("hidden"); await refreshStatus(); await refreshSessions(); }); floor.appendChild(desk);
  }
  if (!state.agentProfiles.length) { const empty=document.createElement("div"); empty.className="agent-desk empty-desk"; empty.innerHTML="<strong>Open desk</strong><small>Create a named agent below</small>"; floor.appendChild(empty); }
  const box = $("profile-list");
  box.innerHTML = "";
  for (const profile of state.agentProfiles) {
    const card = document.createElement("article");
    card.className = "profile-card";
    const tokens = profile.session?.token_usage || {};
    card.innerHTML = `<strong></strong><small class="muted"></small><div class="profile-actions"></div>`;
    card.querySelector("strong").textContent = `${profile.name}${profile.state === "working" ? " · working" : ""}`;
    const approximation = tokens.estimated ? "~" : "";
    card.querySelector("small").textContent = `${approximation}${tokens.input_tokens || 0} in · ${approximation}${tokens.output_tokens || 0} out · ${profile.unread || 0} unread`;
    const actions = card.querySelector(".profile-actions");
    const addAction = (label, fn, cls = "ghost") => {
      const button = document.createElement("button"); button.type = "button"; button.className = cls; button.textContent = label; button.addEventListener("click", fn); actions.appendChild(button);
    };
    addAction("Open", async () => {
      const loaded = await api("/api/agent-profiles/open", { method: "POST", body: JSON.stringify({ agent_id: profile.id }) });
      state.currentSessionId = loaded.session_id; renderTranscript(loaded.messages || []); $("control-modal").classList.add("hidden"); await refreshStatus(); await refreshSessions();
    });
    addAction("Run", async () => {
      const message = window.prompt(`Send work to ${profile.name}`, "");
      if (!message) return;
      const result = await api("/api/agent-profiles/run", { method: "POST", body: JSON.stringify({ agent_id: profile.id, message, sender_session_id: state.currentSessionId }) });
      watchJob(result.job_id, result.session_id); await refreshAgentProfiles();
    });
    addAction("Edit", () => {
      $("profile-id").value = profile.id; $("profile-name").value = profile.name || ""; $("profile-workspace").value = profile.workspace || ""; $("profile-instructions").value = profile.instructions || "";
    });
    addAction("Remove", async () => {
      if (!window.confirm(`Remove ${profile.name} from the roster? Its conversation will remain searchable.`)) return;
      await api("/api/agent-profiles/remove", { method: "POST", body: JSON.stringify({ agent_id: profile.id }) }); await refreshAgentProfiles();
    }, "danger");
    box.appendChild(card);
  }
  if (!state.agentProfiles.length) box.innerHTML = '<div class="muted">No named agents yet. Create one above.</div>';
}

async function showDoctor(repair = false) {
  const data = await api(repair ? "/api/doctor/repair" : "/api/doctor", repair ? { method: "POST", body: "{}" } : {});
  $("doctor-summary").textContent = `${data.ok ? "Core runtime ready" : "Attention needed"} · ${data.next_action || ""}${data.repaired?.length ? ` · repaired ${data.repaired.join(", ")}` : ""}`;
  const box = $("doctor-results"); box.innerHTML = "";
  for (const check of data.checks || []) {
    const row = document.createElement("div"); row.className = `scan-item ${check.ok ? "ok" : ""}`; row.innerHTML = "<strong></strong><small></small>"; row.querySelector("strong").textContent = `${check.ok ? "✓" : "!"} ${check.name}`; row.querySelector("small").textContent = check.detail || ""; box.appendChild(row);
  }
}

function renderFooocusStatus(status) {
  if (!status) return;
  const stateLabel = status.dependencies_ready ? "Ready" : "Needs dependencies";
  if ($("card-fooocus-state")) $("card-fooocus-state").textContent = stateLabel;
  const box = $("fooocus-status");
  if (!box) return;
  box.innerHTML = "";
  const rows = [
    ["State", stateLabel],
    ["Engine", `${status.backend || "diffusers"} · ${status.model || "local model"}`],
    ["Runtime", status.dependencies_ready ? "Python packages ready" : `Missing: ${(status.missing || []).join(", ")}`],
    ["Outputs", status.outputs || "—"],
  ];
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "scan-item";
    row.innerHTML = `<strong>${label}</strong><small></small>`;
    row.querySelector("small").textContent = value;
    box.appendChild(row);
  }
  if (status.log && (status.starting || !status.dependencies_ready)) {
    const log = document.createElement("pre");
    log.className = "connector-log";
    log.textContent = status.log;
    box.appendChild(log);
  }
}

function renderExternalList(items) {
  const box = $("external-list");
  if (!box) return;
  box.innerHTML = "";
  for (const item of items) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `connector-mini-card${state.selectedExternalId === item.id ? " active" : ""}`;
    card.innerHTML = `<strong>${item.name}</strong><small>${item.auth_type} · ${item.configured ? "configured" : "needs credentials"}</small>`;
    card.addEventListener("click", () => {
      state.selectedExternalId = item.id;
      $("external-name").value = item.name || "";
      $("external-url").value = item.base_url || "";
      $("external-auth").value = item.auth_type || "none";
      $("external-username").value = item.username || "";
      $("external-header").value = item.api_key_header || "X-API-Key";
      $("external-auth-url").value = item.authorization_url || "";
      $("external-token-url").value = item.token_url || "";
      $("external-client-id").value = item.client_id || "";
      $("external-scopes").value = item.scopes || "";
      updateExternalAuthFields();
      renderExternalList(items);
    });
    box.appendChild(card);
  }
}

function openConnectorPanel(name) {
  document.querySelectorAll("[data-connector-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.connectorPanel !== name);
  });
  $("connector-dashboard").classList.add("hidden");
  $("connector-detail").classList.remove("hidden");
}

function closeConnectorPanel() {
  $("connector-detail").classList.add("hidden");
  $("connector-dashboard").classList.remove("hidden");
}

function updateExternalAuthFields() {
  const auth = $("external-auth").value;
  const visible = new Set(
    auth === "password" || auth === "basic" ? ["external-username", "external-password"]
      : auth === "api_key" ? ["external-token", "external-header"]
        : auth === "bearer" ? ["external-token"]
          : auth === "oauth2" ? ["external-auth-url", "external-token-url", "external-client-id", "external-client-secret", "external-scopes", "external-code"]
            : []
  );
  for (const id of ["external-username", "external-password", "external-token", "external-header", "external-auth-url", "external-token-url", "external-client-id", "external-client-secret", "external-scopes", "external-code"]) {
    $(id).closest("label").classList.toggle("hidden", !visible.has(id));
  }
  $("external-oauth-start").classList.toggle("hidden", auth !== "oauth2");
  $("external-oauth-finish").classList.toggle("hidden", auth !== "oauth2");
}

function showDirectImageResult(data) {
  const box = $("image-result");
  box.innerHTML = "";
  const row = document.createElement("div");
  row.className = "scan-item";
  const title = document.createElement("strong");
  title.textContent = `${data.action || "Image"} · ${data.width || "?"}×${data.height || "?"}${data.engine ? ` · ${data.engine}` : ""}`;
  row.appendChild(title);
  const artifact = data.artifact || (data.artifacts || [])[0];
  if (artifact?.download_url) {
    const link = document.createElement("a");
    link.className = "tool-download";
    link.href = artifact.download_url;
    link.download = artifact.name || "image";
    link.textContent = `Download ${artifact.name || "image"}`;
    row.appendChild(link);
    const preview = document.createElement("img");
    preview.className = "direct-image-preview";
    preview.src = artifact.view_url || artifact.download_url;
    preview.alt = artifact.name || "Image result";
    row.appendChild(preview);
  }
  box.appendChild(row);
}

function renderTerminals(items) {
  const box = $("terminal-list");
  if (!box) return;
  box.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "scan-item";
    row.innerHTML = `<strong>${item.name}</strong><div class="muted">${item.path}</div>`;
    box.appendChild(row);
  }
  if (!items.length) box.innerHTML = '<div class="muted">No supported terminal discovered.</div>';
}

function renderMediaStatus(media) {
  const box = $("media-status");
  if (!box) return;
  const image = media.image || {};
  const threeD = media.three_d || {};
  box.innerHTML = "";
  const rows = [
    ["Image Studio", image.pillow && image.opencv, image.pillow && image.opencv ? "Ready · creation, editing, text removal, conversion" : "Dependencies will repair on restart"],
    ["Local 3D", threeD.trimesh, threeD.trimesh ? "Ready · GLB/GLTF/OBJ/STL/PLY" : "Dependencies will repair on restart"],
    ["Blender", threeD.blender, threeD.blender ? `Ready · ${threeD.blender_path || "installed"}` : "Optional · needed for textures, renders, BLEND/FBX/USD"],
  ];
  for (const [label, ready, detail] of rows) {
    const row = document.createElement("div");
    row.className = "scan-item media-engine";
    row.innerHTML = `<strong>${ready ? "●" : "○"} ${label}</strong><span class="muted">${detail}</span>`;
    box.appendChild(row);
  }
  const threeBox = $("media-3d-status");
  if (threeBox) {
    threeBox.innerHTML = rows.slice(1).map(([label, ready, detail]) => `<div class="scan-item media-engine"><strong>${ready ? "●" : "○"} ${label}</strong><span class="muted">${detail}</span></div>`).join("");
  }
  if ($("card-images-state")) $("card-images-state").textContent = image.ai_configured ? "AI + local ready" : "Local ready · add AI key";
  if ($("image-api-url") && image.ai_endpoint) $("image-api-url").value = image.ai_endpoint;
}

function renderAdminStatus(admin) {
  const box = $("admin-status");
  if (!box) return;
  const privilege = admin.administrator ? "Administrator privileges active" : "Standard privileges · elevation requested when required";
  box.innerHTML = `<div class="scan-item media-engine"><strong>${admin.ready ? "●" : "○"} Administrator tools</strong><span class="muted">${privilege}</span></div>`
    + `<div class="scan-item media-engine"><strong>● Action audit</strong><span class="muted">${admin.audit_path || "~/.clawd/audit/actions.jsonl"}</span></div>`
    + `<div class="scan-item media-engine"><strong>${admin.git ? "●" : "○"} Git automation</strong><span class="muted">GitHub and GitLab clone, fetch, pull, review-branch push</span></div>`;
}

function renderDeviceAccess(access) {
  const box = $("device-access-status");
  if (!box) return;
  const enabled = Boolean(access.enabled);
  const scope = access.operating_system_scope || "signed-in user";
  const approval = access.approved_at ? ` · approved ${new Date(access.approved_at).toLocaleString()}` : "";
  box.innerHTML = `<div class="scan-item media-engine ${enabled ? "ok" : ""}"><strong>${enabled ? "● Full access enabled" : "○ Full access disabled"}</strong><span class="muted">OS scope: ${scope}${approval}</span></div>`
    + `<div class="scan-item media-engine"><strong>${access.uac_required_for_elevation ? "○" : "●"} Administrator elevation</strong><span class="muted">${access.uac_required_for_elevation ? "Windows will display UAC when administrator rights are required" : "Administrator rights are active"}</span></div>`;
  const button = $("device-access-toggle");
  button.textContent = enabled ? "Revoke full access" : "Enable full access";
  button.className = enabled ? "danger" : "primary";
  if ($("card-device-state")) $("card-device-state").textContent = enabled ? "Full access enabled" : "Approval gated";
}

function renderAutonomyStatus(data) {
  const box = $("autonomy-status");
  if (!box) return;
  box.innerHTML = "";
  const profiles = data.profiles || [];
  if (!profiles.length) {
    box.innerHTML = '<div class="scan-item"><strong>Execute with approval</strong><span class="muted">No reviewed tool decisions yet. Access stays approval-gated.</span></div>';
    return;
  }
  for (const profile of profiles) {
    const row = document.createElement("div");
    row.className = "scan-item media-engine";
    const confidence = Math.round(Number(profile.clean_approval_lower_bound || 0) * 100);
    row.innerHTML = "<strong></strong><span class=\"muted\"></span>";
    row.querySelector("strong").textContent = `${profile.workflow} · ${profile.recommended_level_label}`;
    row.querySelector("span").textContent = `${profile.clean_approvals} clean / ${profile.total_decisions} decisions · ≥${confidence}% confidence · ${profile.risk} risk ceiling: ${profile.autonomy_ceiling_label}`;
    box.appendChild(row);
  }
  const note = document.createElement("div");
  note.className = "muted";
  note.textContent = data.enforcement || "Explicit user approval remains the enforcement point.";
  box.appendChild(note);
}

function renderDeviceInventory(data) {
  const box = $("device-inventory");
  if (!box) return;
  box.innerHTML = "";
  const counts = data.counts || {};
  const summary = document.createElement("div");
  summary.className = "scan-item media-engine ok";
  const title = document.createElement("strong");
  title.textContent = `● ${counts.applications || 0} applications · ${counts.browsers || 0} browsers · ${counts.command_line_tools || 0} CLI tools`;
  const detail = document.createElement("span");
  detail.className = "muted";
  detail.textContent = "Agents can address any listed executable by name or absolute path.";
  summary.append(title, detail);
  box.appendChild(summary);
  for (const [label, items] of [["Browsers", data.browsers || []], ["Applications", data.applications || []], ["Command-line tools", data.command_line_tools || []]]) {
    if (!items.length) continue;
    const row = document.createElement("div");
    row.className = "scan-item media-engine";
    const heading = document.createElement("strong");
    heading.textContent = label;
    const names = document.createElement("span");
    names.className = "muted";
    names.textContent = items.slice(0, 24).map((item) => item.name).join(", ") + (items.length > 24 ? ` … and ${items.length - 24} more` : "");
    row.append(heading, names);
    box.appendChild(row);
  }
}

function renderFinanceStatus(finance) {
  const box = $("finance-status");
  if (!box) return;
  const broker = finance.broker || {};
  box.innerHTML = `<div class="scan-item media-engine"><strong>${finance.market_data ? "●" : "○"} Market data &amp; portfolio</strong><span class="muted">${finance.market_data ? "Ready" : "Dependencies repair on restart"}</span></div>`
    + `<div class="scan-item media-engine"><strong>● Business manager</strong><span class="muted">${finance.business_database || "Local encrypted profile"}</span></div>`
    + `<div class="scan-item media-engine"><strong>${broker.configured ? "●" : "○"} Alpaca broker</strong><span class="muted">${broker.configured ? `Connected · ${broker.mode}` : "Optional · not connected"}</span></div>`;
  if ($("alpaca-mode")) $("alpaca-mode").value = broker.paper === false ? "live" : "paper";
  if ($("card-finance-state")) $("card-finance-state").textContent = broker.configured ? `Alpaca · ${broker.mode}` : "Markets ready · broker optional";
}

function renderKronosStatus(status) {
  if (!status) return;
  const ready = Boolean(status.source_ready && status.runtime_ready);
  if ($("card-kronos-state")) $("card-kronos-state").textContent = ready ? "Local engine ready" : status.source_ready ? "Runtime pending" : "Not installed";
  const box = $("kronos-status");
  if (!box) return;
  box.innerHTML = `<div class="scan-item media-engine"><strong>${ready ? "●" : "○"} Local engine</strong><span class="muted">${ready ? "Ready" : "Install or repair to continue"}</span></div>`
    + `<div class="scan-item media-engine"><strong>Engine</strong><span class="muted">Jonathan-native probabilistic forecast</span></div>`
    + `<div class="scan-item media-engine"><strong>Safety</strong><span class="muted">Research only · no automatic orders</span></div>`;
}

function renderPersonalFinanceStatus(status) {
  if (!status) return;
  const label = status.running ? "Running locally" : status.runtime_ready ? "Ready to start" : status.source_ready ? "Needs Docker / Podman" : "Not installed";
  if ($("card-personal-finance-state")) $("card-personal-finance-state").textContent = label;
  const box = $("personal-finance-status");
  if (!box) return;
  box.innerHTML = `<div class="scan-item media-engine"><strong>${status.running ? "●" : "○"} Service</strong><span class="muted">${label}</span></div>`
    + `<div class="scan-item media-engine"><strong>Database</strong><span class="muted">${escapeHtml(status.database || status.path || "Local SQLite")}</span></div>`
    + `<div class="scan-item media-engine"><strong>Isolation</strong><span class="muted">Embedded Jonathan vault · no containers or payment</span></div>`;
}

function renderCodeMemoryStatus(status) {
  if (!status) return;
  const ready = Boolean(status.runtime_ready);
  if ($("card-code-memory-state")) $("card-code-memory-state").textContent = ready ? "Local graph ready" : status.source_ready ? "Build pending" : "Not installed";
  const box = $("code-memory-status");
  if (!box) return;
  box.innerHTML = `<div class="scan-item media-engine"><strong>${ready ? "●" : "○"} Local engine</strong><span class="muted">${ready ? "Ready" : "Install or repair to continue"}</span></div>`
    + `<div class="scan-item media-engine"><strong>Database</strong><span class="muted">${escapeHtml(status.database || "Local SQLite")}</span></div>`
    + `<div class="scan-item media-engine"><strong>Privacy</strong><span class="muted">Local only · no hooks · no payment</span></div>`;
}

function renderProcoderStatus(status) {
  if (!status) return;
  const ready = Boolean(status.runtime_ready && status.checksum_verified);
  if ($("card-procoder-state")) $("card-procoder-state").textContent = ready ? `Verified · v${status.version || "?"}` : status.source_ready ? "Verification pending" : "Not installed";
  const box = $("procoder-status");
  if (!box) return;
  box.innerHTML = `<div class="scan-item media-engine"><strong>${ready ? "●" : "○"} Controller</strong><span class="muted">${ready ? `SHA-256 verified · v${escapeHtml(status.version || "")}` : "Install or verify to continue"}</span></div>`
    + `<div class="scan-item media-engine"><strong>Authority</strong><span class="muted">Built in · reports only · no hooks, edits, commits or tags</span></div>`;
}

function renderDrawAiStatus(status) {
  if (!status) return;
  const ready = Boolean(status.runtime_ready);
  const label = ready ? "Models ready" : status.dependencies_ready ? "Models optional" : status.source_ready ? "Dependencies pending" : "Not installed";
  if ($("card-drawai-state")) $("card-drawai-state").textContent = label;
  const box = $("drawai-status"); if (!box) return;
  box.innerHTML = `<div class="scan-item media-engine"><strong>${ready ? "●" : "○"} Editable graphics</strong><span class="muted">${label}</span></div>`
    + `<div class="scan-item media-engine"><strong>Outputs</strong><span class="muted">Editable SVG · native-shape PPTX · rendered PNG</span></div>`;
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
    body: JSON.stringify({ attachments: payload, session_id: state.currentSessionId }),
  });
  state.attachments.push(...(data.attachments || []));
  renderAttachments();
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function fileAttachmentPayload(file) {
  const nativePath = file?.path || (native?.getPathForFile ? native.getPathForFile(file) : "");
  if (nativePath) return { kind: "file", path: nativePath, name: file.name };
  return {
    kind: "file",
    name: file.name || "upload.bin",
    media_type: file.type || "application/octet-stream",
    data_base64: arrayBufferToBase64(await file.arrayBuffer()),
  };
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

function watchJob(jobId, sessionId) {
  state.currentJob = jobId;
  state.activeJobs.set(jobId, { sessionId });
  state.pendingSessions.delete(sessionId);
  updateBusyUi();
  let assistant = null;
  let accumulated = "";
  const source = new EventSource(`/api/events?job_id=${encodeURIComponent(jobId)}`);
  source.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    const visible = state.currentSessionId === sessionId;
    if (event.type === "stream_end") {
      source.close();
      state.activeJobs.delete(jobId);
      state.pendingSessions.delete(sessionId);
      updateBusyUi();
      if (visible) {
        api(`/api/instances/peek?session_id=${encodeURIComponent(sessionId)}`)
          .then((snapshot) => renderTranscript(snapshot.messages || []))
          .catch(() => {});
      }
      refreshSessions();
      refreshStatus();
      return;
    }
    if (event.type === "job_started") {
      if (visible) setProgress("Reading attachments…");
      return;
    }
    if (event.type === "attachment_scan") {
      if (visible) setProgress(event.ocr ? "Reading image text…" : "Recognizing image…");
      return;
    }
    if (event.type === "user") {
      return;
    }
    if (event.type === "token") {
      if (visible) setProgress("Writing response…");
      accumulated += event.text;
      if (visible) {
        if (!assistant || !assistant.isConnected) assistant = addBubble("assistant", "");
        assistant.dataset.raw = accumulated;
        assistant.innerHTML = renderMarkdown(accumulated);
        assistant.scrollIntoView({ block: "end" });
      }
      return;
    }
    if (event.type === "tool_use" || event.type === "tool_result" || event.type === "tool_error") {
      const toolName = String(event.tool_name || "").toLowerCase();
      if (event.type === "tool_use" && ["write", "edit", "multiedit", "notebookedit", "bash", "powershell"].some((name) => toolName.includes(name))) {
        state.changedSessions.add(sessionId);
      }
      if (visible && event.type === "tool_use") {
        const labels = {
          imagestudio: "Editing image…",
          visionanalyze: "Analyzing image…",
          fooocus: "Generating image…",
          read: "Reading file…",
          write: "Creating file…",
          edit: "Editing file…",
          bash: "Running command…",
          powershell: "Running PowerShell…",
          artifact: "Packaging download…",
        };
        setProgress(labels[toolName] || "Working…");
      }
      if (visible && event.type === "tool_result") {
        const output = event.tool_output && typeof event.tool_output === "object" ? event.tool_output : {};
        const artifacts = Array.isArray(output.artifacts) ? output.artifacts : (output.artifact ? [output.artifact] : []);
        if (artifacts.length) addArtifactBubble(artifacts, "Ready to download");
      }
      if (visible && state.previewOpen && event.type === "tool_result") refreshPreview().catch(() => {});
      return;
    }
    if (event.type === "workers_started") {
      if (visible) setProgress("Planning agents…");
      return;
    }
    if (event.type === "worker") {
      if (visible) setProgress("Agents are working…");
      return;
    }
    if (event.type === "permission_request") {
      showPermission(event);
      if (native?.notify) native.notify("Jonathan Ai needs permission", event.message || event.tool_name);
      return;
    }
    if (event.type === "done") {
      if (visible && Array.isArray(event.messages)) {
        renderTranscript(event.messages);
        if (event.text) addBubble("system", event.text);
      } else if (visible && event.text && !(assistant && assistant.dataset.raw)) {
        addBubble(event.kind === "command" ? "system" : "assistant", event.text);
      }
      if (visible && event.session) {
        renderUsage(event.session);
        refreshStatus();
        refreshSessions();
      } else if (visible && event.usage) {
        renderUsage({ token_usage: event.usage });
      }
      if (native?.notify && event.kind !== "command") {
        native.notify("Jonathan Ai finished", (event.text || "Done").slice(0, 120));
      }
      if (event.kind !== "command" && state.changedSessions.has(sessionId)) {
        state.changedSessions.delete(sessionId);
        packageProject(true, sessionId);
      } else {
        refreshArtifacts().catch(() => {});
      }
      return;
    }
    if (event.type === "error") {
      if (visible) addBubble("system", event.error || "Error");
      if (event.needs_setup) $("setup-modal").classList.remove("hidden");
      if (event.provider_limit && $("settings-modal")) {
        $("settings-modal").classList.remove("hidden");
      }
    }
  };
  source.onerror = () => {
    source.close();
    state.activeJobs.delete(jobId);
    state.pendingSessions.delete(sessionId);
    updateBusyUi();
  };
}

async function sendMessage(path = "/api/chat") {
  const text = $("prompt").value;
  if (!text.trim() && !state.attachments.length) return;
  const sessionId = state.currentSessionId;
  if (!sessionId) return;
  const pendingAttachments = [...state.attachments];
  const userBubble = addBubble("user", text || "", pendingAttachments.some((item) => item.is_image) ? "media-bubble" : "");
  for (const item of pendingAttachments) {
    appendConversationAttachment(userBubble, item);
  }
  $("prompt").value = "";
  $("slash-palette").classList.add("hidden");
  state.changedSessions.delete(sessionId);
  setBusy(true, sessionId);
  try {
    const data = await api(path, {
      method: "POST",
      body: JSON.stringify({
        text,
        session_id: sessionId,
        mode: path === "/api/multi-agent" ? ($("worker-mode")?.value || "balanced") : undefined,
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
    watchJob(data.job_id, data.session_id || sessionId);
  } catch (err) {
    setBusy(false, sessionId);
    if (state.currentSessionId === sessionId) addBubble("system", err.message);
  }
}

function bindUi() {
  $("send").addEventListener("click", () => sendMessage("/api/chat"));
  $("workers")?.addEventListener("click", () => sendMessage("/api/multi-agent"));
  $("open-search").addEventListener("click", () => { openControl("search-panel"); $("history-query").focus(); });
  $("open-agent-hub").addEventListener("click", async () => { openControl("agent-hub-panel"); clearProfileForm(); await refreshAgentProfiles(); });
  $("open-skills").addEventListener("click", async () => {
    $("skills-modal").classList.remove("hidden");
    try { await Promise.all([refreshSkillLibrary(), refreshEccCatalog()]); } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("skills-close").addEventListener("click", () => $("skills-modal").classList.add("hidden"));
  $("skills-new").addEventListener("click", () => {
    state.selectedSkill = null;
    $("skill-name").value = "new-skill";
    $("skill-content").value = newSkillSource("new-skill");
    $("skill-status").textContent = "Rename the skill and edit its instructions, then validate and save.";
    $("skill-name").focus();
    $("skill-name").select();
  });
  $("skill-name").addEventListener("input", () => {
    if (state.selectedSkill) return;
    const name = $("skill-name").value.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-");
    const current = $("skill-content").value;
    $("skill-content").value = current
      .replace(/^name: .*$/m, `name: "${name}"`)
      .replace(/^# .*$/m, `# ${name}`);
  });
  $("skill-save").addEventListener("click", async () => {
    $("skill-status").textContent = "Validating and saving…";
    try {
      const data = await api("/api/skills/save", {
        method: "POST",
        body: JSON.stringify({ name: $("skill-name").value, content: $("skill-content").value }),
      });
      state.selectedSkill = data.saved?.name || $("skill-name").value;
      renderSkillLibrary(data);
      $("skill-status").textContent = `Saved and ready for every agent: ${data.saved?.path || "SKILL.md"}`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("skill-archive").addEventListener("click", async () => {
    const name = state.selectedSkill || $("skill-name").value.trim();
    if (!name || !window.confirm(`Archive ${name}? It remains recoverable in the library's .archive folder.`)) return;
    try {
      const data = await api("/api/skills/archive", { method: "POST", body: JSON.stringify({ name }) });
      state.selectedSkill = null;
      renderSkillLibrary(data);
      $("skill-status").textContent = `Archived ${name}; the file remains recoverable.`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("skills-open-folder").addEventListener("click", async () => {
    try {
      const data = await api("/api/skills/open", { method: "POST", body: "{}" });
      $("skill-status").textContent = `Opened ${data.path}`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("skill-learn-project").addEventListener("click", async () => {
    $("skill-status").textContent = "Analyzing sanitized local Git history…";
    try {
      const draft = await api("/api/integrations/ecc", { method: "POST", body: JSON.stringify({ action: "analyze_git", commits: 200 }) });
      state.selectedSkill = null;
      $("skill-name").value = draft.name;
      $("skill-content").value = draft.content;
      $("skill-status").textContent = `Drafted from ${draft.analyzed_commits} commits at confidence ${draft.confidence}. Review it, then Validate & save to activate.`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("ecc-filter").addEventListener("input", () => renderEccCatalog(state.eccCatalog || {}));
  $("ecc-sync").addEventListener("click", async () => {
    $("skill-status").textContent = "Synchronizing the ECC catalog…";
    try {
      const result = await api("/api/integrations/ecc", { method: "POST", body: JSON.stringify({ action: "sync" }) });
      renderEccCatalog(result.catalog || result);
      $("skill-status").textContent = `ECC synchronized at ${String(result.revision || "").slice(0, 12)}.`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("ecc-scan").addEventListener("click", async () => {
    $("skill-status").textContent = "Scanning ECC prompts, scripts, hooks, MCP files, and credentials…";
    try {
      const result = await api("/api/integrations/ecc", { method: "POST", body: JSON.stringify({ action: "scan" }) });
      $("skill-status").textContent = `Scanned ${result.files_scanned} files: ${result.critical} critical and ${result.high} high findings. Import checks only content that can be activated.`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("ecc-import-all").addEventListener("click", async () => {
    if (!window.confirm("Import the complete ECC skills and agent-template catalog? Only the curated skill set will be enabled in agent context.")) return;
    $("skill-status").textContent = "Auditing and importing the complete ECC catalog…";
    try {
      const result = await api("/api/integrations/ecc", { method: "POST", body: JSON.stringify({ action: "import" }) });
      renderEccCatalog(result.catalog || result);
      $("skill-status").textContent = `Imported ${result.imported_skills.length} skills and ${result.imported_agents.length} agent templates; ${result.enabled_skills.length} curated skills are enabled.`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("ecc-memory-export").addEventListener("click", async () => {
    try {
      const result = await api("/api/integrations/ecc", { method: "POST", body: JSON.stringify({ action: "memory_export" }) });
      $("skill-status").textContent = `Exported ${result.count} unreviewed memory-vault documents to ${result.path}.`;
    } catch (err) { $("skill-status").textContent = err.message; }
  });
  $("open-doctor").addEventListener("click", async () => { openControl("doctor-panel"); await showDoctor(false); });
  $("control-close").addEventListener("click", () => $("control-modal").classList.add("hidden"));
  $("history-search").addEventListener("click", runHistorySearch);
  $("history-query").addEventListener("keydown", (event) => { if (event.key === "Enter") runHistorySearch().catch((err) => $("history-meta").textContent = err.message); });
  $("profile-clear").addEventListener("click", clearProfileForm);
  $("profile-save").addEventListener("click", async () => {
    await api("/api/agent-profiles", { method: "POST", body: JSON.stringify({ id: $("profile-id").value, name: $("profile-name").value, workspace: $("profile-workspace").value, instructions: $("profile-instructions").value }) }); clearProfileForm(); await refreshAgentProfiles();
  });
  $("doctor-run").addEventListener("click", () => showDoctor(false).catch((err) => $("doctor-summary").textContent = err.message));
  $("doctor-repair").addEventListener("click", () => showDoctor(true).catch((err) => $("doctor-summary").textContent = err.message));
  $("undo-turn").addEventListener("click", async () => {
    try { const result = await api("/api/sessions/undo", { method: "POST", body: JSON.stringify({ session_id: state.currentSessionId }) }); renderTranscript(result.messages || []); await refreshStatus(); await refreshSessions(); }
    catch (err) { addBubble("system", err.message); }
  });
  $("retry-turn").addEventListener("click", async () => {
    try { const result = await api("/api/sessions/retry", { method: "POST", body: JSON.stringify({ session_id: state.currentSessionId }) }); renderTranscript((await api("/api/sessions/messages")).messages || []); watchJob(result.job_id, result.session_id); }
    catch (err) { addBubble("system", err.message); }
  });
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
  $("session-menu-remove").addEventListener("click", async () => {
    const sessionId = state.menuSessionId;
    const session = state.sessions.find((item) => item.session_id === sessionId);
    hideSessionMenu();
    if (!sessionId) return;
    if (!window.confirm(`Remove “${session?.title || "this conversation"}” from the sidebar? Its full history stays in persistent memory.`)) return;
    const result = await api("/api/sessions/remove", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (Array.isArray(result.messages)) renderTranscript(result.messages);
    await refreshStatus();
    await refreshSessions();
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
    if (state.previewOpen) await refreshPreview();
  });
  $("pick-projects").addEventListener("click", async () => {
    let path = "";
    if (native?.pickFolder) path = await native.pickFolder();
    else path = window.prompt("Project and download folder", state.status?.projects_dir || "") || "";
    if (!path) return;
    await api("/api/projects-dir", { method: "POST", body: JSON.stringify({ path }) });
    await refreshStatus();
    if (state.previewOpen) await refreshArtifacts();
  });
  $("toggle-preview").addEventListener("click", () => setPreviewOpen(!state.previewOpen));
  $("close-preview").addEventListener("click", () => setPreviewOpen(false));
  $("refresh-preview").addEventListener("click", refreshPreview);
  $("package-project").addEventListener("click", () => packageProject(false));
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
    const payload = await Promise.all(files.map(fileAttachmentPayload));
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
      box.textContent = "Scanning installed runtimes, model folders, and loopback ports…";
      try {
        const extra = $(`${prefix}-url`).value;
        const data = await api("/api/connectors/local/scan", {
          method: "POST",
          body: JSON.stringify({ base_url: extra || "", auto_start: true }),
        });
        renderScanResults(box, data.endpoints, (item) => {
          $(`${prefix}-url`).value = item.base_url;
          fillModelList(`${prefix}-model-list`, item.models || []);
          if (item.models?.[0]) $(`${prefix}-model`).value = item.models[0];
        });
        for (const runtime of data.runtimes || []) {
          const row = document.createElement("div");
          row.className = "scan-item";
          const modelCount = (runtime.models || []).filter((item) => item.type !== "embedding").length || (runtime.model_files || []).length;
          const resources = runtime.resources || {};
          const details = [`${modelCount} local model(s)`, runtime.executable || "model cache"];
          if (resources.model_storage_bytes) details.push(`${formatBytes(resources.model_storage_bytes)} stored`);
          if (resources.resident_memory_bytes) details.push(`${formatBytes(resources.resident_memory_bytes)} live RAM`);
          if (resources.system_available_memory_bytes) details.push(`${formatBytes(resources.system_available_memory_bytes)} RAM free`);
          if (resources.fit && resources.fit !== "unknown") details.push(`${resources.fit} estimated fit`);
          row.innerHTML = `<strong></strong><small></small>`;
          row.querySelector("strong").textContent = `${runtime.label} installed`;
          row.querySelector("small").textContent = details.join(" · ");
          box.appendChild(row);
        }
        if (data.connected) box.insertAdjacentHTML("afterbegin", '<div class="scan-item ok"><strong>Connected automatically</strong><small>The reachable installed model is now Jonathan’s active provider.</small></div>');
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
    closeConnectorPanel();
    await refreshStatus();
  });
  $("connectors-close").addEventListener("click", () => $("connectors-modal").classList.add("hidden"));
  $("connector-detail-close").addEventListener("click", closeConnectorPanel);
  document.querySelectorAll(".connector-card[data-panel]").forEach((card) => {
    card.addEventListener("click", () => openConnectorPanel(card.dataset.panel));
  });
  $("device-access-toggle").addEventListener("click", async () => {
    const enabled = Boolean(state.status?.device_access?.enabled);
    if (enabled) {
      if (!window.confirm("Revoke Full Device & Network Access? Agents will return to workspace-only access and per-action approvals.")) return;
      try {
        const access = await api("/api/device-access", { method: "POST", body: JSON.stringify({ enabled: false }) });
        state.status.device_access = access;
        renderDeviceAccess(access);
        $("device-access-message").textContent = "Full access revoked. Workspace boundaries and approval prompts are active.";
      } catch (err) { $("device-access-message").textContent = err.message; }
      return;
    }
    const confirmation = window.prompt("This grants every Jonathan agent persistent access to files, applications, browsers, shells, CLIs, and network tools available to your Windows account. Type ENABLE FULL ACCESS to continue.", "");
    if (confirmation === null) return;
    try {
      const access = await api("/api/device-access", { method: "POST", body: JSON.stringify({ enabled: true, confirmation }) });
      state.status.device_access = access;
      renderDeviceAccess(access);
      $("device-access-message").textContent = "Full access enabled and audit logged. Windows UAC still controls administrator-only actions.";
    } catch (err) { $("device-access-message").textContent = err.message; }
  });
  $("device-inventory-scan").addEventListener("click", async () => {
    $("device-access-message").textContent = "Scanning registered applications, browsers, and PATH tools…";
    try {
      const data = await api("/api/device/inventory?limit=5000");
      renderDeviceInventory(data);
      $("device-access-message").textContent = "Installed-tool inventory is ready.";
    } catch (err) { $("device-access-message").textContent = err.message; }
  });
  const runFooocusAction = async (action, message, extra = {}) => {
    const node = $("fooocus-message");
    node.textContent = message;
    try {
      const data = await api("/api/fooocus/action", {
        method: "POST",
        body: JSON.stringify({ action, session_id: state.currentSessionId, ...extra }),
      });
      renderFooocusStatus(data);
      if ((action === "publish_latest" || action === "generate") && data.artifact) {
        node.innerHTML = "";
        const link = document.createElement("a");
        link.href = data.artifact.download_url;
        link.textContent = `Download ${data.artifact.name}`;
        link.setAttribute("download", data.artifact.name);
        node.appendChild(link);
        addArtifactBubble(data.artifacts || data.artifact, "Generated with Jonathan local diffusion");
        await refreshArtifacts();
      } else {
        node.textContent = data.dependencies_ready ? "Jonathan's local image engine is ready." : "Done.";
      }
      state.status.fooocus = data;
    } catch (err) {
      node.textContent = err.message;
    }
  };
  $("fooocus-install").addEventListener("click", () => runFooocusAction("install", "Installing Jonathan's local image dependencies…"));
  $("fooocus-start").addEventListener("click", () => runFooocusAction("start", "Verifying Jonathan's local image engine…"));
  $("fooocus-generate").addEventListener("click", () => runFooocusAction("generate", "Generating locally; first model download and CPU generation can take several minutes…", {
    prompt: $("fooocus-prompt").value,
    width: Number($("fooocus-width").value || 1024),
    height: Number($("fooocus-height").value || 1024),
    performance: $("fooocus-performance").value,
  }));
  $("fooocus-stop").addEventListener("click", () => runFooocusAction("stop", "Releasing local image state…"));
  $("fooocus-latest").addEventListener("click", () => runFooocusAction("publish_latest", "Publishing the newest local output…"));
  $("fooocus-open").addEventListener("click", () => runFooocusAction("outputs", "Refreshing local outputs…"));
  $("connector-open-settings").addEventListener("click", () => {
    $("connectors-modal").classList.add("hidden");
    $("settings-modal").classList.remove("hidden");
  });
  $("image-provider-save").addEventListener("click", async () => {
    try {
      const data = await api("/api/media/image-provider", {
        method: "POST",
        body: JSON.stringify({ api_key: $("image-api-key").value, base_url: $("image-api-url").value, model: $("image-api-model").value }),
      });
      $("image-api-key").value = "";
      $("image-provider-status").textContent = "Image generation and prompt editing are connected.";
      renderMediaStatus(data);
    } catch (err) {
      $("image-provider-status").textContent = err.message;
    }
  });
  $("image-use-attachment").addEventListener("click", () => {
    const image = [...state.attachments].reverse().find((item) => item.is_image || item.kind === "image" || item.kind === "screenshot");
    $("image-source").value = image?.path || "";
    $("image-provider-status").textContent = image ? `Using ${image.name}` : "Attach an image to the conversation first.";
  });
  $("image-run").addEventListener("click", async () => {
    try {
      let regions;
      if ($("image-regions").value.trim()) regions = JSON.parse($("image-regions").value);
      const data = await api("/api/media/image", {
        method: "POST",
        body: JSON.stringify({
          session_id: state.currentSessionId,
          action: $("image-action").value,
          engine: $("image-engine").value,
          source: $("image-source").value,
          overlay: $("image-overlay").value,
          prompt: $("image-prompt").value,
          endpoint: $("image-api-url").value,
          model: $("image-api-model").value,
          text: $("image-text").value,
          output: $("image-output").value,
          width: Number($("image-width").value || 1024),
          height: Number($("image-height").value || 1024),
          x: Number($("image-x").value || 0),
          y: Number($("image-y").value || 0),
          angle: Number($("image-angle").value || 0),
          direction: $("image-direction").value,
          regions,
        }),
      });
      showDirectImageResult(data);
      addArtifactBubble(data.artifacts || data.artifact, `${data.action || "Image"} complete`);
      refreshArtifacts().catch(() => {});
    } catch (err) {
      $("image-result").innerHTML = `<div class="scan-item">${String(err.message || err)}</div>`;
    }
  });
  $("external-save").addEventListener("click", async () => {
    try {
      const auth = $("external-auth").value;
      const token = $("external-token").value;
      const connectors = await api("/api/connectors/external", {
        method: "POST",
        body: JSON.stringify({
          id: state.selectedExternalId,
          name: $("external-name").value,
          base_url: $("external-url").value,
          auth_type: auth,
          username: $("external-username").value,
          password: $("external-password").value,
          api_key: auth === "api_key" ? token : "",
          api_key_header: $("external-header").value,
          bearer_token: auth === "bearer" ? token : "",
          authorization_url: $("external-auth-url").value,
          token_url: $("external-token-url").value,
          client_id: $("external-client-id").value,
          client_secret: $("external-client-secret").value,
          scopes: $("external-scopes").value,
        }),
      });
      $("external-password").value = ""; $("external-token").value = ""; $("external-client-secret").value = "";
      const saved = (connectors.services || []).find((item) => item.name === $("external-name").value);
      state.selectedExternalId = saved?.id || state.selectedExternalId;
      state.status.connectors = connectors;
      renderConnectorStatus(connectors);
      $("external-status").textContent = "Connection saved locally.";
    } catch (err) { $("external-status").textContent = err.message; }
  });
  $("external-auth").addEventListener("change", updateExternalAuthFields);
  updateExternalAuthFields();
  $("external-test").addEventListener("click", async () => {
    if (!state.selectedExternalId) { $("external-status").textContent = "Save or select a service first."; return; }
    try {
      const data = await api("/api/connectors/external/test", { method: "POST", body: JSON.stringify({ id: state.selectedExternalId }) });
      $("external-status").textContent = data.reachable ? `Connected · HTTP ${data.status}` : `Connection failed · HTTP ${data.status || "error"}`;
    } catch (err) { $("external-status").textContent = err.message; }
  });
  $("external-oauth-start").addEventListener("click", async () => {
    if (!state.selectedExternalId) { $("external-status").textContent = "Save or select the OAuth service first."; return; }
    try {
      const data = await api("/api/connectors/external/oauth/start", { method: "POST", body: JSON.stringify({ id: state.selectedExternalId }) });
      state.externalOauth = { id: state.selectedExternalId, state: data.state };
      window.open(data.authorization_url, "_blank", "noopener");
      $("external-status").textContent = "Authorization opened. Sign in, then paste the returned code below.";
    } catch (err) { $("external-status").textContent = err.message; }
  });
  $("external-oauth-finish").addEventListener("click", async () => {
    try {
      const data = await api("/api/connectors/external/oauth/exchange", { method: "POST", body: JSON.stringify({ id: state.selectedExternalId, code: $("external-code").value, state: state.externalOauth?.state || "" }) });
      $("external-code").value = ""; state.externalOauth = null;
      state.status.connectors = data.connectors; renderConnectorStatus(data.connectors);
      $("external-status").textContent = "OAuth connection complete.";
    } catch (err) { $("external-status").textContent = err.message; }
  });
  $("external-remove").addEventListener("click", async () => {
    if (!state.selectedExternalId || !window.confirm("Remove this external connection?")) return;
    try {
      const connectors = await api("/api/connectors/external/remove", { method: "POST", body: JSON.stringify({ id: state.selectedExternalId }) });
      state.selectedExternalId = null; state.status.connectors = connectors; renderConnectorStatus(connectors);
      $("external-status").textContent = "Connection removed.";
    } catch (err) { $("external-status").textContent = err.message; }
  });
  $("alpaca-save").addEventListener("click", async () => {
    const live = $("alpaca-mode").value === "live";
    if (live && !window.confirm("Connect LIVE trading with real money? Every order will still require a separate approval.")) return;
    try {
      const data = await api("/api/finance/alpaca", {
        method: "POST",
        body: JSON.stringify({ api_key: $("alpaca-key").value, secret_key: $("alpaca-secret").value, paper: !live }),
      });
      $("alpaca-key").value = "";
      $("alpaca-secret").value = "";
      $("alpaca-message").textContent = `Saved locally · ${data.broker?.mode || "paper"} mode`;
      renderFinanceStatus(data);
    } catch (err) {
      $("alpaca-message").textContent = err.message;
    }
  });
  $("kronos-install").addEventListener("click", async () => {
    $("kronos-message").textContent = "Installing Kronos locally; the selected model downloads only when first used…";
    try {
      const data = await api("/api/integrations/kronos", { method: "POST", body: JSON.stringify({ action: "install" }) });
      renderKronosStatus(data);
      $("kronos-message").textContent = "Kronos is ready for local research forecasts.";
    } catch (err) {
      $("kronos-message").textContent = err.message;
    }
  });
  $("kronos-run").addEventListener("click", async () => {
    if (!$("kronos-input").value.trim()) { $("kronos-message").textContent = "Choose a timestamped OHLCV CSV first."; return; }
    $("kronos-message").textContent = "Running the local market forecast; first use downloads the selected model…";
    try {
      const data = await api("/api/integrations/kronos", { method: "POST", body: JSON.stringify({
        action: "forecast", input_csv: $("kronos-input").value.trim(), output_csv: $("kronos-output").value.trim(),
        model: $("kronos-model").value, pred_len: Number($("kronos-pred-len").value || 24),
        lookback: Number($("kronos-lookback").value || 400),
      }) });
      addArtifactBubble(data.artifacts || data.artifact, "Kronos research forecast");
      $("kronos-message").textContent = `Forecast complete · ${data.rows} rows · ${data.device} · research only.`;
      await refreshStatus();
    } catch (err) {
      $("kronos-message").textContent = err.message;
    }
  });
  const runPersonalFinanceAction = async (action, message) => {
    $("personal-finance-message").textContent = message;
    try {
      const data = await api("/api/integrations/personal-finance", { method: "POST", body: JSON.stringify({ action }) });
      state.status.personal_finance = data;
      renderPersonalFinanceStatus(data);
      $("personal-finance-message").textContent = data.restart_required ? "Container runtime installed; restart Windows or Docker Desktop, then press Start." : data.running ? "Personal finance vault is running locally." : "Done.";
      return data;
    } catch (err) {
      $("personal-finance-message").textContent = err.message;
      return null;
    }
  };
  $("personal-finance-install").addEventListener("click", () => runPersonalFinanceAction("install", "Preparing the isolated finance source and container runtime…"));
  $("personal-finance-start").addEventListener("click", () => runPersonalFinanceAction("start", "Building and starting the isolated finance services…"));
  $("personal-finance-stop").addEventListener("click", () => runPersonalFinanceAction("stop", "Stopping the finance services while preserving their volumes…"));
  $("personal-finance-open").addEventListener("click", async () => {
    let status = state.status.personal_finance || {};
    if (!status.running) status = await runPersonalFinanceAction("start", "Starting the isolated finance services…") || status;
    if (!status.running) return;
    if (!status.url) { $("personal-finance-message").textContent = "The native vault is available to Jonathan through the PersonalFinanceVault tool; it has no separate web service."; return; }
    await setPreviewOpen(true);
    $("preview-path").textContent = status.url || "http://127.0.0.1:3132/";
    $("preview-frame").src = status.url || "http://127.0.0.1:3132/";
    $("preview-frame").classList.remove("hidden");
    $("preview-empty").classList.add("hidden");
  });
  const runCodeMemory = async (payload, message) => {
    $("code-memory-message").textContent = message;
    try {
      const data = await api("/api/integrations/code-memory", { method: "POST", body: JSON.stringify(payload) });
      state.status.code_memory = data;
      renderCodeMemoryStatus(data);
      $("code-memory-result").textContent = data.output || "Complete.";
      $("code-memory-message").textContent = "Complete. Data remains in Jonathan’s local code-memory database.";
      return data;
    } catch (err) {
      $("code-memory-message").textContent = err.message;
      return null;
    }
  };
  $("code-memory-install").addEventListener("click", () => runCodeMemory({ action: "install" }, "Installing and building the isolated local engine…"));
  $("code-memory-scan").addEventListener("click", () => runCodeMemory({ action: "scan" }, "Incrementally mapping this workspace…"));
  $("code-memory-run").addEventListener("click", () => {
    const action = $("code-memory-action").value;
    const query = $("code-memory-query").value.trim();
    if (!query) { $("code-memory-message").textContent = "Enter a query, symbol, or note first."; return; }
    runCodeMemory({ action, query, target: $("code-memory-target").value.trim(), limit: Number($("code-memory-limit").value || 100) }, "Running the local code-memory query…");
  });
  const runProcoder = async (payload, message) => {
    $("procoder-message").textContent = message;
    try {
      const data = await api("/api/integrations/procoder", { method: "POST", body: JSON.stringify(payload) });
      state.status.procoder = data; renderProcoderStatus(data);
      $("procoder-result").textContent = data.output || (data.runtime_ready ? "Ready." : "No report output.");
      $("procoder-message").textContent = data.ok === false ? `Report found blocking or unchecked work (exit ${data.exit_code}).` : "Report completed.";
    } catch (err) { $("procoder-message").textContent = err.message; }
  };
  $("procoder-install").addEventListener("click", () => runProcoder({ action: "install" }, "Verifying Jonathan's built-in engineering controller…"));
  $("procoder-run").addEventListener("click", () => runProcoder({ action: $("procoder-action").value, deep: $("procoder-deep").checked }, "Running the selected engineering report…"));
  $("drawai-use-attachment").addEventListener("click", () => { const image = [...state.attachments].reverse().find((item) => item.is_image || item.kind === "image" || item.kind === "screenshot"); $("drawai-input").value = image?.path || ""; $("drawai-message").textContent = image ? `Using ${image.name}` : "Upload an image in the conversation first."; });
  const runDrawAi = async (payload, message) => {
    $("drawai-message").textContent = message;
    try {
      const data = await api("/api/integrations/drawai", { method: "POST", body: JSON.stringify(payload) });
      state.status.drawai = data; renderDrawAiStatus(data);
      if (data.artifacts) addArtifactBubble(data.artifacts, "Editable graphics outputs");
      $("drawai-message").textContent = data.artifacts ? `Complete · ${data.artifacts.length} downloadable files.` : "DrawAI is ready.";
    } catch (err) { $("drawai-message").textContent = err.message; }
  };
  $("drawai-install").addEventListener("click", () => runDrawAi({ action: "install", device: $("drawai-device").value }, "Verifying Jonathan's built-in editable-graphics dependencies…"));
  $("drawai-run").addEventListener("click", () => { const image = $("drawai-input").value.trim(); if (!image) { $("drawai-message").textContent = "Select an uploaded image first."; return; } runDrawAi({ action: "convert", image, output_dir: $("drawai-output").value.trim(), device: $("drawai-device").value }, "Reconstructing editable SVG and PPTX artifacts…"); });
  $("character-generate").addEventListener("click", async () => { $("character-message").textContent="Drawing the deterministic SVG rig…"; try { const data=await api("/api/media/character",{method:"POST",body:JSON.stringify({name:$("character-name").value,seed:$("character-seed").value,species:$("character-species").value,medium:$("character-medium").value})}); addArtifactBubble(data.artifacts,"Procedural character assets"); $("character-message").textContent=`Created ${data.name} · ${data.species}.`; } catch(err){ $("character-message").textContent=err.message; } });
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
    const payload = await Promise.all(files.map(fileAttachmentPayload));
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
  let voiceRecorder = null;
  let voiceStream = null;
  let voiceChunks = [];
  $("voice-record").addEventListener("click", async () => {
    const button = $("voice-record");
    if (voiceRecorder?.state === "recording") {
      voiceRecorder.stop();
      return;
    }
    try {
      voiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      voiceChunks = [];
      const preferred = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
      voiceRecorder = new MediaRecorder(voiceStream, preferred ? { mimeType: preferred } : undefined);
      voiceRecorder.addEventListener("dataavailable", (event) => { if (event.data?.size) voiceChunks.push(event.data); });
      voiceRecorder.addEventListener("stop", async () => {
        button.textContent = "Voice";
        button.classList.remove("primary");
        voiceStream?.getTracks().forEach((track) => track.stop());
        const type = voiceRecorder.mimeType || "audio/webm";
        const file = new File(voiceChunks, `voice-${new Date().toISOString().replace(/[:.]/g, "-")}.webm`, { type });
        if (file.size) {
          await addAttachmentPayload([await fileAttachmentPayload(file)]);
          if (!$("prompt").value.trim()) $("prompt").value = "Transcribe this voice recording and follow the request.";
        }
        voiceChunks = [];
      }, { once: true });
      voiceRecorder.start();
      button.textContent = "Stop voice";
      button.classList.add("primary");
    } catch (err) {
      addBubble("system", `Microphone unavailable: ${err.message}`);
    }
  });
  window.setInterval(() => {
    if (state.renamingId) refreshInstances().catch(() => {});
    else refreshSessions().catch(() => {});
  }, 1800);
}

boot().catch((err) => addBubble("system", err.message));
