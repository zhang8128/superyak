"use strict";

const app = document.querySelector("#app");
const announcer = document.querySelector("#announcer");

const state = {
  me: null,
  home: null,
  contacts: [],
  files: [],
  sync: { enabled: false, deliveries: [] },
  accounts: [],
  corrections: [],
  connections: [],
  activeLayers: {},
  activeLayerErrors: {},
  revisions: [],
  room: null,
  selectedLayerId: null,
  selectedSharedId: null,
  selectedChatId: null,
  currentSpaceId: "all",
  preview: false,
  confirmWithdraw: false,
  chatDialog: null,
  profileDialog: false,
  pairPreview: null,
  invitation: null,
  flash: null,
  transitionNote: null,
  reauth: false,
  reauthError: null,
  layerEdits: {},
  editorIdentity: null,
  logoutError: null,
};

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pathPart(value) {
  return encodeURIComponent(String(value));
}

function formatDate(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "Date unavailable";
  const date = new Date(seconds * 1000);
  if (!Number.isFinite(date.getTime())) return "Date unavailable";
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  } catch (_) {
    return "Date unavailable";
  }
}

function announce(message) {
  announcer.textContent = "";
  requestAnimationFrame(() => {
    announcer.textContent = message;
  });
}

function setFlash(message, error = false) {
  state.flash = { message, error };
  announce(message);
}

function identityKey(user) {
  return user ? `${user.peer_id}:${user.id}` : null;
}

function bindEditorIdentity(user) {
  const next = identityKey(user);
  if (state.editorIdentity !== next) state.layerEdits = {};
  state.editorIdentity = next;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.json !== undefined) {
    headers.set("content-type", "application/json");
    options.body = JSON.stringify(options.json);
  }
  if (state.me?.csrf_token && !["GET", "HEAD"].includes(options.method || "GET")) {
    headers.set("x-csrf-token", state.me.csrf_token);
  }
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...options, headers });
  } catch (_) {
    throw new ApiError("Connection lost. Try again when this peer is reachable.", 0);
  }
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new ApiError(data?.error || "Request could not be completed", response.status);
  }
  return data;
}

function routeParts() {
  const raw = location.hash.replace(/^#\/?/, "") || "home";
  const [route, id] = raw.split("/");
  return { route: ["home", "chats", "layers", "shared", "connections"].includes(route) ? route : "home", id: id ? decodeURIComponent(id) : null };
}

function navLink(route, label, icon) {
  const current = routeParts().route === route;
  return `<a href="#${route}" ${current ? 'aria-current="page"' : ""}><span class="nav-icon" aria-hidden="true">${icon}</span><span>${label}</span></a>`;
}

function brand() {
  return `<a class="brand" href="#home" aria-label="Superyak home"><span class="brand-mark" aria-hidden="true">S</span><span><strong>Superyak</strong><span>Your peer, your pace</span></span></a>`;
}

function layout(content) {
  const name = escapeHtml(state.me.name);
  const spaces = state.home.spaces || [];
  const currentSpace = state.currentSpaceId === "all" ? "All my spaces" : spaces.find((space) => space.id === state.currentSpaceId)?.name || "All my spaces";
  return `<div class="shell">
    <aside class="sidebar">
      ${brand()}
      <nav class="nav" aria-label="Main navigation">
        ${navLink("home", "Home", "⌂")}
        ${navLink("chats", "Chats", "◌")}
        ${navLink("layers", "My sharing layers", "▤")}
        ${navLink("shared", "Shared spaces", "◇")}
        ${navLink("connections", "Connections", "↔")}
      </nav>
      <div class="sidebar-foot">Private work stays on this peer until you choose an audience.</div>
    </aside>
    <div class="main-column">
      <header class="topbar">
        <div class="space-picker">
          <label for="space-context">Current space</label>
          <select id="space-context" aria-label="Current space">
            <option value="all" ${state.currentSpaceId === "all" ? "selected" : ""}>All my spaces</option>
            ${spaces.map((space) => `<option value="${escapeHtml(space.id)}" ${space.id === state.currentSpaceId ? "selected" : ""}>${escapeHtml(space.name)}</option>`).join("")}
          </select>
        </div>
        <button class="account-button" data-action="profile" aria-label="Account and sign out">
          <span class="account-meta"><strong>${name}</strong><span>${escapeHtml(currentSpace)}</span></span>
          <span class="avatar" aria-hidden="true">${escapeHtml(state.me.name.trim().charAt(0).toUpperCase() || "S")}</span>
        </button>
      </header>
      <main class="content" id="main-content" tabindex="-1">
        ${state.flash ? `<div class="notice ${state.flash.error ? "error" : ""}" role="status">${escapeHtml(state.flash.message)}</div>` : ""}
        ${content}
      </main>
    </div>
    ${profileDialog()}${reauthDialog()}
  </div>`;
}

function showLogin(message = "") {
  state.me = null;
  app.innerHTML = `<main class="login-page" id="main-content">
    <div class="login-wrap">
      <section class="login-story">
        ${brand()}
        <div><h1>A home for the parts of your life you choose to share.</h1><p>Write privately, talk with people you trust, and turn on only the version you mean to share.</p></div>
        <p class="login-note">Self-hosted on your Superyak peer.</p>
      </section>
      <section class="login-panel" aria-labelledby="login-title">
        <p class="eyebrow">Personal home</p>
        <h2 id="login-title">Sign in to your home</h2>
        <p>Your account belongs to this peer.</p>
        ${message ? `<div class="notice error" role="alert">${escapeHtml(message)}</div>` : ""}
        <form id="login-form">
          <div class="field"><label for="username">Username</label><input class="input" id="username" name="username" autocomplete="username" required></div>
          <div class="field"><label for="password">Password</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required></div>
          <button class="button" type="submit">Sign in</button>
        </form>
        <details class="invitation-redeem"><summary>Use an invitation</summary><p>An account owner gives you a one-use token. You choose your own local username, name, and password.</p><form id="redeem-form"><div class="field"><label for="invitation-token">Invitation token</label><input class="input" id="invitation-token" name="token" autocomplete="off" required></div><div class="field"><label for="new-username">New username</label><input class="input" id="new-username" name="username" autocomplete="username" required></div><div class="field"><label for="new-name">Your display name</label><input class="input" id="new-name" name="name" required></div><div class="field"><label for="new-password">New password</label><input class="input" id="new-password" name="password" type="password" minlength="12" autocomplete="new-password" required></div><button class="button secondary" type="submit">Create my account</button></form></details>
      </section>
    </div>
  </main>`;
  document.title = "Sign in · Superyak";
}

function flashMarkup() {
  return state.flash ? `<div class="notice ${state.flash.error ? "error" : ""}" role="status">${escapeHtml(state.flash.message)}</div>` : "";
}

function empty(title, body) {
  return `<div class="empty"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p></div>`;
}

function kindLabel(kind) {
  return { "care-circle": "Care circle", project: "Project", organization: "Organization" }[kind] || "Space";
}

function homeView() {
  const { counts, layers, chats, shared_layers: shared, spaces } = state.home;
  const recentLayer = layers[0];
  const recentChat = chats[0];
  const grouped = ["care-circle", "project", "organization"];
  return `<header class="page-head"><div><p class="eyebrow">Welcome, ${escapeHtml(state.me.name)}</p><h1>Your home</h1><p class="lede">Pick up a private thought, return to a conversation, or see what others have shared with you.</p></div></header>
    <section class="grid cols-4" aria-label="Your home at a glance">
      <div class="card stat"><strong>${counts.chats}</strong><span>Private chats</span></div>
      <div class="card stat"><strong>${counts.layers}</strong><span>Your sharing layers</span></div>
      <div class="card stat"><strong>${counts.shared_layers}</strong><span>Active items you can read</span></div>
      <div class="card stat"><strong>${counts.spaces}</strong><span>Care circles and spaces</span></div>
    </section>
    <section class="section"><div class="section-head"><h2>Continue where you left off</h2></div>
      <div class="grid cols-2">
        ${recentLayer ? `<a class="card tint" href="#layers/${pathPart(recentLayer.id)}"><p class="eyebrow">Private writing</p><h3>${escapeHtml(recentLayer.title)}</h3><p class="meta">${recentLayer.active_revision ? "A release is active; your draft remains editable." : "Private draft · sharing is off"}</p></a>` : `<div class="card tint"><h3>Start a sharing layer</h3><p class="meta">Draft privately for as long as you need.</p><a class="text-button" href="#layers">Open sharing layers</a></div>`}
        ${recentChat ? `<a class="card amber" href="#chats/${pathPart(recentChat.id)}"><p class="eyebrow">Recent chat</p><h3>${escapeHtml(recentChat.title)}</h3><p class="meta">${escapeHtml(participantSummary(recentChat))} · ${formatDate(recentChat.last_activity)}</p></a>` : `<div class="card amber"><h3>Your first private chat</h3><p class="meta">A personal room is useful even before you invite anyone.</p><a class="text-button" href="#chats">Open chats</a></div>`}
      </div>
    </section>
    <section class="section"><div class="section-head"><h2>Your circles and spaces</h2></div>
      ${spaces.length ? `<div class="grid cols-3">${grouped.map((kind) => {
        const matching = spaces.filter((space) => space.kind === kind);
        return `<div class="card compact"><p class="eyebrow">${kindLabel(kind)}</p>${matching.length ? matching.map((space) => `<h3>${escapeHtml(space.name)}</h3><p class="meta">${space.member_ids.length} ${space.member_ids.length === 1 ? "person" : "people"} · ${escapeHtml(space.audience_note)}</p>`).join("") : `<p class="meta">No ${kind === "care-circle" ? "care circles" : kind + "s"} yet.</p>`}</div>`;
      }).join("")}</div>` : empty("No spaces yet", "Create care circles, projects, or organizations when they become useful.")}
    </section>
    <section class="section"><div class="section-head"><h2>Shared with you</h2><a class="text-button" href="#shared">See all shared spaces</a></div>
      ${shared.length ? `<div class="item-list">${shared.slice(0, 3).map(sharedItem).join("")}</div>` : empty("Nothing shared yet", "Your private writing and chats are ready whenever you are.")}
    </section>`;
}

function layerStatus(layer) {
  const active = state.activeLayers[layer.id];
  if (layer.active_revision && state.activeLayerErrors[layer.id]) return `<span class="badge active">Active · details unavailable</span>`;
  if (!active) return `<span class="badge draft">Private draft</span>`;
  return `<span class="badge active">Active</span>`;
}

function layerItem(layer) {
  return `<button class="item" data-action="open-layer" data-id="${escapeHtml(layer.id)}"><span class="item-main"><strong>${escapeHtml(layer.title)}</strong><span>Draft version ${layer.version}</span></span><span class="status-stack">${layerStatus(layer)}</span></button>`;
}

function selectedLayer() {
  return state.home.layers.find((layer) => layer.id === state.selectedLayerId) || null;
}

function layerForEditor() {
  const layer = selectedLayer();
  const edit = layer && state.layerEdits[layer.id];
  return edit ? { ...layer, ...edit.values } : layer;
}

function currentLayerEdit() {
  const layer = selectedLayer();
  return layer ? state.layerEdits[layer.id] : null;
}

function choiceContact(contact, selected) {
  const remote = contact.remote ? " · paired contact" : "";
  return `<label class="choice"><input type="checkbox" name="audience-user" value="${escapeHtml(contact.id)}" ${selected.includes(contact.id) ? "checked" : ""}><span class="choice-copy"><strong>${escapeHtml(contact.name)}</strong><small>Named person${remote}</small></span></label>`;
}

function choiceSpace(space, selected) {
  const note = space.kind === "organization" ? "Current and future members can see an active release" : "People selected when you activate this version";
  return `<label class="choice"><input type="checkbox" name="audience-space" value="${escapeHtml(space.id)}" ${selected.includes(space.id) ? "checked" : ""}><span class="choice-copy"><strong>${escapeHtml(space.name)}</strong><small>${escapeHtml(note)}</small></span></label>`;
}

function effectiveAudience(active) {
  if (!active) return "Nobody can see this draft.";
  const names = (active.audience_users || []).map(contactName);
  const spaces = (active.audience_spaces || []).map(spaceName);
  const routes = [...names, ...spaces];
  if (active.public) routes.push("Anyone with the public link");
  return routes.length ? routes.join(" · ") : "No active audience routes";
}

function attachmentChoices(layer) {
  if (!state.files.length) return `<p class="meta">No files uploaded yet. Choose a text, PDF, PNG, JPEG, or GIF file to add one.</p>`;
  return `<div class="choices">${state.files.map((file) => `<label class="choice"><input type="checkbox" name="attachment" value="${escapeHtml(file.id)}" ${(layer.attachment_ids || []).includes(file.id) ? "checked" : ""}><span class="choice-copy"><strong>${escapeHtml(file.name)}</strong><small>${formatBytes(file.size)} · ${escapeHtml(file.digest.slice(0, 10))}…</small></span></label>`).join("")}</div>`;
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "Size unavailable";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function editorState(layer, active) {
  const unsaved = currentLayerEdit()?.dirty ? '<span class="badge draft">Unsaved changes</span>' : "";
  if (layer.active_revision && state.activeLayerErrors[layer.id]) {
    return `<span class="badge active">Active release</span>${unsaved}<span class="state-note">Latest sharing details unavailable</span>`;
  }
  if (!active) return `<span class="badge draft">Private draft</span>${unsaved}<span class="state-note">Sharing is off</span>`;
  const unpublished = active.draft_version !== layer.version;
  return `<span class="badge active">Active · version ${active.draft_version}</span>${unsaved}${unpublished ? '<span class="badge draft">Unpublished changes</span>' : '<span class="state-note">Draft and active release match</span>'}`;
}

function revisionHistory() {
  if (!state.revisions.length) return `<p class="meta">No releases yet. Activated versions will appear here without replacing earlier ones.</p>`;
  return state.revisions.slice().reverse().map((revision) => `<details><summary>Release ${revision.revision} · draft version ${revision.draft_version}</summary><p class="meta">Owner account ${escapeHtml(revision.owner_id)}</p><p class="meta">Origin peer ${escapeHtml(state.me.peer_id)} · ${formatDate(revision.created)}</p><h4>${escapeHtml(revision.title)}</h4><div class="shared-body">${escapeHtml(revision.body)}</div></details>`).join("");
}

function activePanel(layer, active) {
  if (layer.active_revision && state.activeLayerErrors[layer.id]) {
    return `<div class="active-panel unavailable"><h3>Active release details are unavailable</h3><p>The peer still reports an active release. Its current audience and controls could not be loaded, so no change is being claimed.</p></div>`;
  }
  if (!active) return `<div class="active-panel"><h3>Sharing is off</h3><p>Your saved draft is private. Preview a concrete saved version before turning it on.</p></div>`;
  const publicLink = `/public/?layer=${pathPart(layer.id)}`;
  const routeControls = [
    ...(active.audience_users || []).map((id) => `<button class="button ghost" data-action="revoke-route" data-route-kind="person" data-id="${escapeHtml(id)}">Stop sharing directly with ${escapeHtml(contactName(id))}</button>`),
    ...(active.audience_spaces || []).map((id) => `<button class="button ghost" data-action="revoke-route" data-route-kind="space" data-id="${escapeHtml(id)}">Turn off ${escapeHtml(spaceName(id))}</button>`),
  ].join("");
  return `<div class="active-panel"><h3>Current release</h3><p><strong>Effective access:</strong> ${escapeHtml(effectiveAudience(active))}</p><p>Overlapping routes stay effective independently. A role or organization membership does not reveal anything you did not share.</p><div class="button-row">
    ${active.public ? `<a class="button secondary" href="${escapeHtml(publicLink)}" target="_blank" rel="noopener">View as a visitor</a><button class="button secondary" data-action="public-off">Turn off public link</button>` : ""}
    <button class="button danger secondary" data-action="withdraw">Stop all sharing</button>
  </div>${routeControls ? `<div class="button-row" aria-label="Turn off individual audience routes">${routeControls}</div>` : ""}</div>`;
}

function previewDialog(layer) {
  if (!state.preview) return "";
  const users = (layer.audience_users || []).map(contactName);
  const spaces = (layer.audience_spaces || []).map((id) => {
    const space = state.home.spaces.find((item) => item.id === id);
    return space ? `${space.name}${space.kind === "organization" ? " (current and future members)" : " (people selected at activation)"}` : "Unknown space";
  });
  return `<dialog open aria-labelledby="preview-title"><div class="dialog-body"><p class="eyebrow">Audience preview</p><h2 id="preview-title">Preview version ${layer.version}</h2><p>This exact saved version will become active. Later draft edits stay private until you activate again.</p><div class="preview-paper"><h3>${escapeHtml(layer.title)}</h3><p>${escapeHtml(layer.body)}</p></div><h3>Who would see it</h3><p>${[...users, ...spaces, ...(layer.public ? ["Anyone with the public link"] : [])].map(escapeHtml).join(" · ") || "Only you — no audience is selected."}</p>${layer.public ? "<p>Public access cannot exclude an individual.</p>" : ""}<div class="button-row"><button class="button" data-action="activate">Turn on version ${layer.version}</button><button class="button secondary" data-action="close-dialog">Keep it private</button></div></div></dialog>`;
}

function withdrawDialog() {
  if (!state.confirmWithdraw) return "";
  return `<dialog open aria-labelledby="withdraw-title"><div class="dialog-body"><h2 id="withdraw-title">Stop every active route?</h2><p>This removes the hosted release from named people, spaces, and the public link. Your private draft and release history remain.</p><div class="button-row"><button class="button danger" data-action="confirm-withdraw">Yes, stop all sharing</button><button class="button secondary" data-action="close-dialog">Keep sharing on</button></div></div></dialog>`;
}

function layerEditor(layer) {
  const active = state.activeLayers[layer.id];
  const edit = currentLayerEdit();
  return `<section class="card editor" aria-labelledby="editor-title"><div class="editor-head"><div><p class="eyebrow">Your private workspace</p><h2 id="editor-title">Edit this layer</h2><div class="status-stack">${editorState(layer, active)}</div></div></div>
    <form id="layer-form">
      <div class="field"><label for="layer-title">Layer title</label><input class="input" id="layer-title" name="title" maxlength="200" value="${escapeHtml(layer.title)}" required></div>
      <div class="field"><label for="layer-body">What do you want to share?</label><textarea class="textarea" id="layer-body" name="body" maxlength="100000">${escapeHtml(layer.body)}</textarea></div>
      <fieldset class="field"><legend>Named people</legend><small>People only see an activated version. Selecting someone here does not reveal the private draft.</small><div class="choices">${state.contacts.map((contact) => choiceContact(contact, layer.audience_users || [])).join("") || `<p class="meta">No contacts are available yet.</p>`}</div></fieldset>
      <fieldset class="field"><legend>Care circles and spaces</legend><div class="choices">${state.home.spaces.map((space) => choiceSpace(space, layer.audience_spaces || [])).join("") || `<p class="meta">No spaces are available yet.</p>`}</div></fieldset>
      <fieldset class="field"><legend>Public access</legend><label class="choice public-choice"><input type="checkbox" name="public" ${layer.public ? "checked" : ""}><span class="choice-copy"><strong>Anyone with the public link</strong><small>Only the activated version and its chosen attachments are public.</small></span></label></fieldset>
      <fieldset class="field"><legend>Attachments</legend>${attachmentChoices(layer)}<label class="button secondary" for="file-upload">Upload a file</label><input class="sr-only" id="file-upload" type="file" accept="text/plain,application/pdf,image/png,image/jpeg,image/gif"><p id="upload-status" class="inline-message" role="status"></p></fieldset>
      <div class="editor-actions"><div class="button-row"><button class="button" type="submit">Save private draft</button><button class="button secondary" type="button" data-action="preview">Preview audience</button></div><span class="state-note">Saved version ${layer.version}</span></div>
      <p id="layer-status" class="inline-message ${edit?.conflict ? "error" : ""}" role="status">${edit?.conflict ? "This draft changed in another tab. Your text is still here." : ""}</p>${edit?.conflict ? '<button class="button secondary" type="button" data-action="resolve-conflict">Save my text onto the latest draft</button>' : ""}
    </form>
    ${activePanel(layer, active)}
    <div class="history"><h3>Release and correction history</h3><p class="meta">Earlier releases keep their words, version, date, and original account attribution. A corrected display name never changes grants.</p>${revisionHistory()}</div>
    ${previewDialog(layer)}${withdrawDialog()}
  </section>`;
}

function layersView() {
  const layer = layerForEditor();
  return `<header class="page-head"><div><p class="eyebrow">Private first</p><h1>My sharing layers</h1><p class="lede">Build your sharing layers at your own pace. Save them privately, see what each audience would see, and turn them on when you're ready.</p></div><button class="button" data-action="new-layer">New layer</button></header>
    <div class="workspace"><aside class="workspace-list"><div class="item-list">${state.home.layers.map(layerItem).join("") || empty("No layers yet", "Start with a private draft. You do not need to choose an audience.")}</div></aside>${layer ? layerEditor(layer) : `<section>${empty("Choose a layer", "Select a draft from the list or start a new one.")}</section>`}</div>`;
}

function sharedItem(layer) {
  return `<button class="item" data-action="open-shared" data-id="${escapeHtml(layer.id)}"><span class="item-main"><strong>${escapeHtml(layer.title)}</strong><span>${escapeHtml(accessLabel(layer.access_routes || []))}</span></span><span class="item-side">Release ${escapeHtml(layer.revision)}</span></button>`;
}

function accessLabel(routes) {
  const labels = routes.map((route) => {
    if (route === "owner") return "Your active release";
    if (route === "person") return "Shared directly with you";
    if (route === "public") return "Public link";
    if (route.startsWith("space:")) return spaceName(route.slice(6));
    return "Shared with you";
  });
  return [...new Set(labels)].join(" · ");
}

function sharedView() {
  const selected = state.home.shared_layers.find((layer) => layer.id === state.selectedSharedId);
  const visibleSpaces = state.home.spaces.filter((space) => state.currentSpaceId === "all" || space.id === state.currentSpaceId);
  return `<header class="page-head"><div><p class="eyebrow">People and places</p><h1>Shared spaces</h1><p class="lede">Read active releases available to you through a named person, a selected space, or a public link.</p></div></header>
    <section class="grid cols-2"><div><div class="section-head"><h2>Active releases</h2></div><div class="item-list">${state.home.shared_layers.map(sharedItem).join("") || empty("Nothing active here", "Private drafts never appear in this view.")}</div></div>
    <div>${selected ? `<article class="card"><p class="eyebrow">Release ${escapeHtml(selected.revision)} · ${escapeHtml(accessLabel(selected.access_routes || []))}</p><h2>${escapeHtml(selected.title)}</h2>${sharedAttribution(selected)}<p class="shared-body">${escapeHtml(selected.body)}</p>${sharedAttachments(selected)}</article>` : `<div class="section-head"><h2>Your visible spaces</h2></div>${visibleSpaces.length ? visibleSpaces.map((space) => `<div class="card compact"><p class="eyebrow">${kindLabel(space.kind)}</p><h3>${escapeHtml(space.name)}</h3><p class="meta">${escapeHtml(space.audience_note)}</p></div>`).join("") : empty("No spaces in this view", "Choose All my spaces or create one when you need it.")}`}</div></section>`;
}

function sharedOwnerName(layer) {
  if (isSelf(layer.owner_id)) return state.me.name;
  const local = state.contacts.find((contact) => contact.id === layer.owner_id);
  if (local) return local.name;
  const remote = state.contacts.find((contact) => contact.remote && `${contact.peer_id}:${contact.user_id}` === layer.owner_id);
  return remote?.name || "Account on this peer";
}

function sharedAttribution(layer) {
  if (!layer.owner_id) return `<p class="meta">This release is available through its public route; account attribution is not included.</p>`;
  const origin = layer.origin || (String(layer.owner_id).includes(":") ? String(layer.owner_id).split(":", 1)[0] : state.me.peer_id);
  return `<div class="attribution"><strong>Shared by ${escapeHtml(sharedOwnerName(layer))}</strong><span>Owner account ${escapeHtml(layer.owner_id)}</span><span>Origin peer ${escapeHtml(origin)}</span></div>`;
}

function sharedAttachments(layer) {
  if (!(layer.attachment_ids || []).length) return "";
  return `<div class="attachments"><h3>Attachments</h3>${layer.attachment_ids.map((id, index) => `<a class="attachment" href="/api/shared/layers/${pathPart(layer.id)}/files/${pathPart(id)}"><span>Download attachment ${index + 1}</span><span aria-hidden="true">↓</span></a>`).join("")}</div>`;
}

function contactName(id) {
  return state.contacts.find((contact) => contact.id === id)?.name || "Unavailable contact";
}

function spaceName(id) {
  return state.home.spaces.find((space) => space.id === id)?.name || "Unavailable space";
}

function participantName(id) {
  if (id === state.me.id || id === `${state.me.peer_id}:${state.me.id}`) return "You";
  const exact = state.contacts.find((contact) => contact.id === id);
  if (exact) return exact.name;
  const remote = state.contacts.find((contact) => contact.remote && `${contact.peer_id}:${contact.user_id}` === id);
  return remote?.name || "Someone in this chat";
}

function participantSummary(room) {
  const ids = room.member_ids || [];
  const others = ids.filter((id) => id !== state.me?.id && id !== `${state.me?.peer_id}:${state.me?.id}`);
  if (!others.length) return "Personal room";
  return others.map(participantName).join(", ");
}

function messageDelivery(message) {
  if (message.state) return message.state;
  const matches = state.sync.deliveries.filter((delivery) => delivery.message_id === message.id || (delivery.client_message_id && delivery.client_message_id === message.client_message_id));
  if (!matches.length) return "saved";
  if (matches.some((item) => item.status === "failed")) return "failed";
  if (matches.some((item) => item.status === "pending")) return "pending";
  if (matches.every((item) => item.status === "withdrawn")) return "withdrawn";
  return "delivered";
}

function deliveryText(status) {
  return { saved: "Saved here", pending: "Pending delivery", delivered: "Delivered", failed: "Failed to send", withdrawn: "Canceled" }[status] || "Saved here";
}

function isSelf(authorId) {
  return authorId === state.me.id || authorId === `${state.me.peer_id}:${state.me.id}`;
}

function draftKey(roomId) {
  return `superyak:chat-draft:${state.me.peer_id}:${state.me.id}:${roomId}`;
}

function readChatDraft(roomId) {
  try {
    const value = JSON.parse(sessionStorage.getItem(draftKey(roomId)) || "null");
    return value && typeof value.body === "string" ? value : { body: "", clientId: null };
  } catch (_) {
    return { body: "", clientId: null };
  }
}

function messageMarkup(message) {
  const mine = isSelf(message.author_id);
  return `<div class="message ${mine ? "mine" : ""}"><div class="message-meta">${escapeHtml(mine ? "You" : participantName(message.author_id))}</div><p>${escapeHtml(message.body)}</p><div class="message-meta">${formatDate(message.created)} · ${escapeHtml(deliveryText(messageDelivery(message)))}</div></div>`;
}

function roomDetail(room) {
  const draft = readChatDraft(room.id);
  const canManage = room.owner_id === state.me.id && !room.origin;
  return `<section><p class="eyebrow">${room.origin ? "Received private room" : "Private room"}</p><h2>${escapeHtml(room.title)}</h2><div class="participants" aria-label="Participants">${(room.member_ids || []).map((id) => `<span class="participant">${escapeHtml(participantName(id))}</span>`).join("")}</div>${state.transitionNote ? `<div class="notice">${escapeHtml(state.transitionNote)}</div>` : ""}<div class="messages" aria-label="Messages">${(room.messages || []).map(messageMarkup).join("") || empty("No messages yet", "This room begins with an empty history.")}</div>
    <form class="composer" id="message-form"><label class="sr-only" for="message-body">Message</label><textarea class="textarea" id="message-body" name="body" aria-label="Message" maxlength="20000" placeholder="Write a private message…">${escapeHtml(draft.body)}</textarea><button class="button" type="submit">Send message</button><p id="chat-status" class="inline-message" role="status"></p></form>
    ${canManage ? `<div class="room-management"><p class="meta">Removing someone ends their access to this hosted room and cancels delivery queued for them.</p><div class="button-row"><button class="button ghost" data-action="change-participants">Change participants</button>${(room.member_ids || []).filter((id) => !isSelf(id)).map((id) => `<button class="button danger secondary" data-action="remove-participant" data-id="${escapeHtml(id)}">Remove ${escapeHtml(participantName(id))} from this room</button>`).join("")}</div></div>` : ""}
  </section>`;
}

function chatDialog() {
  if (!state.chatDialog) return "";
  const room = state.room;
  const existing = new Set(state.chatDialog === "linked" ? room?.member_ids || [] : []);
  const title = state.chatDialog === "new" ? "Start a private chat" : "Start a new linked chat";
  return `<dialog open aria-labelledby="chat-dialog-title"><div class="dialog-body"><h2 id="chat-dialog-title">${title}</h2><p>${state.chatDialog === "new" ? "Choose nobody for a personal room, one person for a direct room, or several people for a group." : "The new room starts empty. Earlier messages stay with their original participants."}</p><form id="chat-form">${state.chatDialog === "new" ? '<div class="field"><label for="chat-title">Chat title</label><input class="input" id="chat-title" name="title" maxlength="200" required></div>' : ""}<fieldset class="field"><legend>Participants</legend><div class="choices">${state.contacts.map((contact) => `<label class="choice"><input type="checkbox" name="chat-member" value="${escapeHtml(contact.id)}" ${existing.has(contact.id) ? "checked disabled" : ""}><span class="choice-copy"><strong>${escapeHtml(contact.name)}</strong><small>${existing.has(contact.id) ? "Already in this room" : contact.remote ? "Paired contact" : "Local contact"}</small></span></label>`).join("")}</div></fieldset><div class="button-row"><button class="button" type="submit">${state.chatDialog === "new" ? "Create chat" : "Start a new linked chat"}</button><button class="button secondary" type="button" data-action="close-dialog">Cancel</button></div></form></div></dialog>`;
}

function chatsView() {
  return `<header class="page-head"><div><p class="eyebrow">Private conversation</p><h1>Chats</h1><p class="lede">Personal, direct, and group rooms work without an assistant or model.</p></div><button class="button" data-action="new-chat">New private chat</button></header>
    <div class="split-view"><aside class="split-list"><div class="item-list">${state.home.chats.map((room) => `<button class="item" data-action="open-chat" data-id="${escapeHtml(room.id)}"><span class="item-main"><strong>${escapeHtml(room.title)}</strong><span>${escapeHtml(participantSummary(room))}</span></span><span class="item-side">${formatDate(room.last_activity)}</span></button>`).join("") || empty("No chats yet", "A personal room can be your first quiet place to write.")}</div></aside><div class="split-detail">${state.room ? roomDetail(state.room) : empty("Choose a chat", "Open a room or create a private conversation.")}</div></div>${chatDialog()}`;
}

function connectionGroup(connection) {
  const peers = state.connections.filter((item) => item.peer_id === connection.peer_id);
  if (peers[0]?.id !== connection.id) return "";
  return `<div class="card"><p class="eyebrow">${connection.paired ? "Paired peer" : "Disconnected peer"}</p><h3>${peers.map((item) => escapeHtml(item.name)).join(", ")}</h3><p class="meta">Endpoint: ${escapeHtml(connection.card?.endpoint || "Unavailable")}</p><p class="fingerprint meta">Fingerprint: ${escapeHtml(connection.card?.fingerprint || "Unavailable")}</p>${connection.paired ? `<button class="button danger secondary" data-action="unpair" data-id="${escapeHtml(connection.id)}">Disconnect peer and ${peers.length} ${peers.length === 1 ? "contact" : "contacts"}</button><p class="meta">This disconnects the entire peer and hides received content for ${peers.map((item) => escapeHtml(item.name)).join(", ")}.</p>` : ""}</div>`;
}

function deliveryCard(delivery) {
  return `<div class="item"><span class="item-main"><strong>${escapeHtml(delivery.action.replaceAll(".", " "))}</strong><span>Revision ${escapeHtml(delivery.revision)} · ${escapeHtml(deliveryText(delivery.status))} · ${escapeHtml(delivery.attempts)} attempts</span></span>${delivery.status === "failed" ? `<button class="button secondary" data-action="retry-delivery" data-id="${escapeHtml(delivery.id)}">Retry</button>` : `<span class="badge ${escapeHtml(delivery.status)}">${escapeHtml(delivery.status)}</span>`}</div>`;
}

function accountSupport() {
  if (!state.me.is_admin) return "";
  return `<section class="section"><div class="section-head"><div><h2>Account support</h2><p class="meta">Account support does not open private chats or drafts.</p></div><button class="button secondary" data-action="invite">Create invitation</button></div>${state.invitation ? `<div class="notice"><strong>One-use invitation</strong><p>Share this token through a channel you trust. It expires ${formatDate(state.invitation.expires)}.</p><div class="code-box">${escapeHtml(state.invitation.token)}</div></div>` : ""}<div class="item-list">${state.accounts.map((account) => `<div class="item"><span class="item-main"><strong>${escapeHtml(account.name)}</strong><span>@${escapeHtml(account.username)} · joined ${formatDate(account.created)}</span></span><span class="badge">${account.is_admin ? "Account owner" : "Participant"}</span></div>`).join("")}</div></section>`;
}

function connectionsView() {
  const statuses = state.sync.deliveries || [];
  return `<header class="page-head"><div><p class="eyebrow">Explicit peer exchange</p><h1>Connections</h1><p class="lede">Review a peer’s address, participant, and certificate fingerprint before pairing. Pairing alone shares nothing.</p></div><div class="button-row"><button class="button secondary" data-action="show-card">Show my peer card</button><button class="button" data-action="sync">Check delivery now</button></div></header>
    <section class="grid cols-2"><div class="card"><h2>Paired peers</h2>${state.me.is_admin ? (state.connections.length ? state.connections.map(connectionGroup).join("") : empty("No peers paired", "Import a card and compare its fingerprint before connecting.")) : `<p class="meta">The local account owner manages peer pairing. You control what you share with known contacts.</p>`}</div>
    <div class="card"><h2>Delivery</h2><p class="meta">Background synchronization is ${state.sync.enabled ? "on" : "off"}. Local writing still works while another peer is unavailable.</p><div class="item-list">${statuses.length ? statuses.map(deliveryCard).join("") : empty("No delivery activity", "Pending, delivered, failed, and canceled work will remain distinct here.")}</div></div></section>
    ${state.me.is_admin ? `<section class="section card"><h2>Pair another peer</h2><p>Paste the complete public card, preview it, and compare the fingerprint outside Superyak before confirming.</p><form id="pair-preview-form"><div class="field"><label for="peer-card">Peer card</label><textarea class="textarea code-box" id="peer-card" name="card" placeholder="Paste peer card JSON"></textarea></div><button class="button secondary" type="submit">Preview peer card</button></form>${state.pairPreview ? `<div class="active-panel"><h3>${escapeHtml(state.pairPreview.participant.name)}</h3><p>${escapeHtml(state.pairPreview.endpoint)}</p><p class="fingerprint"><strong>Fingerprint:</strong> ${escapeHtml(state.pairPreview.fingerprint)}</p><button class="button" data-action="confirm-pair">Fingerprint matches — pair this peer</button></div>` : ""}</section>` : ""}
    ${accountSupport()}`;
}

function profileDialog() {
  if (!state.profileDialog || !state.me) return "";
  const corrections = state.corrections.length
    ? `<div class="history"><h3>Name correction history</h3>${state.corrections.slice().reverse().map((item) => `<div class="correction"><strong>${escapeHtml(item.old_name)} → ${escapeHtml(item.new_name)}</strong><span>Changed by ${item.actor_id === state.me.id ? `you (${escapeHtml(item.actor_id)})` : escapeHtml(item.actor_id)} · ${formatDate(item.created)}</span></div>`).join("")}</div>`
    : `<p class="meta">No name corrections recorded for this account.</p>`;
  return `<dialog open aria-labelledby="account-title"><div class="dialog-body"><p class="eyebrow">Local account</p><h2 id="account-title">Your account</h2><p>A name correction keeps the same private account and sharing permissions. Earlier releases remain attributed to this account.</p>${state.logoutError ? `<div class="notice error" role="alert">Sign-out could not be completed. This account is still signed in on this device.</div>` : ""}<form id="profile-form"><div class="field"><label for="display-name">Display name</label><input class="input" id="display-name" name="name" maxlength="200" value="${escapeHtml(state.me.name)}" required></div><div class="button-row"><button class="button" type="submit">Save name correction</button><button class="button secondary" type="button" data-action="logout">${state.logoutError ? "Retry sign out" : "Sign out"}</button><button class="button ghost" type="button" data-action="close-dialog">Close</button></div></form>${corrections}</div></dialog>`;
}

function reauthDialog() {
  if (!state.reauth || !state.me) return "";
  return `<dialog open aria-labelledby="reauth-title"><div class="dialog-body"><p class="eyebrow">Session ended</p><h2 id="reauth-title">Sign in again to keep working</h2><p>Your unsaved layer text is still in this editor. Sign in to save it to your peer.</p>${state.reauthError ? `<div class="notice error" role="alert">${escapeHtml(state.reauthError)}</div>` : ""}<form id="reauth-form"><div class="field"><label for="reauth-username">Username</label><input class="input" id="reauth-username" name="username" value="${escapeHtml(state.me.username)}" readonly></div><div class="field"><label for="reauth-password">Password</label><input class="input" id="reauth-password" name="password" type="password" autocomplete="current-password" required></div><div class="button-row"><button class="button" type="submit">Sign in again</button><button class="button secondary" type="button" data-action="close-reauth">Keep editing offline</button></div></form></div></dialog>`;
}

async function renderPublic() {
  document.title = "Shared on Superyak";
  const layerId = new URLSearchParams(location.search).get("layer");
  let content;
  if (!layerId) {
    content = `<article class="public-article"><h1>Public view</h1><p>This address needs a complete Superyak sharing link.</p></article>`;
  } else {
    try {
      const layer = await api(`/public/layers/${pathPart(layerId)}`);
      content = `<article class="public-article"><p class="eyebrow">Shared from a personal Superyak peer · release ${escapeHtml(layer.revision)}</p><h1>${escapeHtml(layer.title)}</h1><div class="public-body">${escapeHtml(layer.body)}</div>${(layer.attachment_ids || []).length ? `<div class="attachments"><h2>Attachments</h2>${layer.attachment_ids.map((id, index) => `<a class="attachment" href="/public/layers/${pathPart(layer.id)}/files/${pathPart(id)}"><span>Download attachment ${index + 1}</span><span aria-hidden="true">↓</span></a>`).join("")}</div>` : ""}</article>`;
      document.title = `${layer.title} · Superyak`;
    } catch (error) {
      content = `<article class="public-article"><p class="eyebrow">Superyak public view</p><h1>This page is not shared</h1><p>The owner may have turned off the public link or stopped sharing this release.</p></article>`;
    }
  }
  app.innerHTML = `<main class="public-page" id="main-content"><div class="public-wrap"><header class="public-header">${brand()}<a class="text-button" href="/">Sign in</a></header>${content}</div></main>`;
}

async function loadData() {
  const [home, contacts, files, sync, corrections] = await Promise.all([
    api("/api/home"), api("/api/contacts"), api("/api/files"), api("/api/sync"), api("/api/me/corrections")
  ]);
  state.home = home;
  state.contacts = contacts;
  state.files = files;
  state.sync = sync;
  state.corrections = corrections;
  const activePairs = await Promise.all(home.layers.filter((layer) => layer.active_revision).map(async (layer) => {
    try { return { id: layer.id, active: await api(`/api/shared/layers/${pathPart(layer.id)}`) }; }
    catch (error) {
      if (error.status === 401) throw error;
      return { id: layer.id, error };
    }
  }));
  const previousActive = state.activeLayers;
  state.activeLayers = Object.fromEntries(activePairs.flatMap((result) => {
    const active = result.active || previousActive[result.id];
    return active ? [[result.id, active]] : [];
  }));
  state.activeLayerErrors = Object.fromEntries(activePairs.flatMap((result) => result.error ? [[result.id, result.error.message]] : []));
  if (state.me.is_admin) {
    [state.accounts, state.connections] = await Promise.all([api("/api/accounts"), api("/api/connections")]);
  } else {
    state.accounts = [];
    state.connections = [];
  }
}

async function loadRoute() {
  const { route, id } = routeParts();
  state.preview = false;
  state.confirmWithdraw = false;
  state.chatDialog = null;
  if (route === "layers") {
    state.selectedLayerId = id || state.selectedLayerId || state.home.layers[0]?.id || null;
    if (state.selectedLayerId && state.home.layers.some((item) => item.id === state.selectedLayerId)) {
      state.revisions = await api(`/api/layers/${pathPart(state.selectedLayerId)}/revisions`);
    } else {
      state.selectedLayerId = null;
      state.revisions = [];
    }
  }
  if (route === "chats") {
    state.selectedChatId = id || state.selectedChatId || null;
    if (state.selectedChatId && state.home.chats.some((item) => item.id === state.selectedChatId)) {
      try { state.room = await api(`/api/chats/${pathPart(state.selectedChatId)}`); }
      catch (_) { state.room = null; }
    } else {
      state.room = null;
    }
  }
  if (route === "shared") state.selectedSharedId = id || state.selectedSharedId;
}

function render() {
  if (!state.me || !state.home) return;
  const route = routeParts().route;
  const view = { home: homeView, chats: chatsView, layers: layersView, shared: sharedView, connections: connectionsView }[route]();
  app.innerHTML = layout(view);
  document.title = `${{ home: "Home", chats: "Chats", layers: "My sharing layers", shared: "Shared spaces", connections: "Connections" }[route]} · Superyak`;
}

async function refresh(message = null) {
  try {
    await loadData();
    await loadRoute();
    if (message) setFlash(message);
    render();
  } catch (error) {
    if (error.status === 401) showLogin("Your session ended. Sign in again; text in an open form has not been sent.");
    else {
      setFlash(error.message, true);
      render();
    }
  }
}

function layerFormData(form = document.querySelector("#layer-form")) {
  return {
    title: form.elements.title.value,
    body: form.elements.body.value,
    audience_users: [...form.querySelectorAll('[name="audience-user"]:checked')].map((input) => input.value),
    audience_spaces: [...form.querySelectorAll('[name="audience-space"]:checked')].map((input) => input.value),
    public: form.elements.public.checked,
    attachment_ids: [...form.querySelectorAll('[name="attachment"]:checked')].map((input) => input.value),
  };
}

function rememberLayerForm(form = document.querySelector("#layer-form")) {
  const layer = selectedLayer();
  if (!layer || !form) return null;
  const previous = state.layerEdits[layer.id];
  const edit = {
    values: layerFormData(form),
    dirty: true,
    conflict: previous?.conflict || false,
    generation: (previous?.generation || 0) + 1,
  };
  state.layerEdits[layer.id] = edit;
  return edit;
}

function updateLayer(layer) {
  const index = state.home.layers.findIndex((item) => item.id === layer.id);
  if (index >= 0) state.home.layers[index] = layer;
}

async function saveLayer(form) {
  const layer = selectedLayer();
  const submitted = rememberLayerForm(form);
  const values = submitted.values;
  const status = form.querySelector("#layer-status");
  status.classList.remove("error");
  status.textContent = "Saving…";
  try {
    const saved = await api(`/api/layers/${pathPart(layer.id)}`, { method: "PUT", json: { version: layer.version, ...values } });
    updateLayer(saved);
    const current = state.layerEdits[layer.id];
    const newerEdits = current && current.generation !== submitted.generation;
    if (!newerEdits) delete state.layerEdits[layer.id];
    else current.conflict = false;
    setFlash(newerEdits ? "Submitted draft saved. Newer edits still need saving." : "Private draft saved");
    render();
  } catch (error) {
    if (error.status === 401) {
      const current = state.layerEdits[layer.id] || submitted;
      current.conflict = false;
      state.layerEdits[layer.id] = current;
      state.reauth = true;
      state.reauthError = null;
      render();
      return;
    }
    if (error.status === 409) {
      const current = state.layerEdits[layer.id] || submitted;
      current.conflict = true;
      state.layerEdits[layer.id] = current;
      render();
      announce("This draft changed in another tab. Your text is still here.");
      return;
    }
    status.classList.add("error");
    status.textContent = `${error.message} Your text is still here.`;
    announce(status.textContent);
  }
}

async function uploadFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  const draftEdit = rememberLayerForm();
  const status = document.querySelector("#upload-status");
  if (file.size > 4 * 1024 * 1024) {
    status.className = "inline-message error";
    status.textContent = "Choose a file no larger than 4 MiB.";
    return;
  }
  status.textContent = "Uploading…";
  try {
    const content_base64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = reject;
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.readAsDataURL(file);
    });
    const uploaded = await api("/api/files", { method: "POST", json: { name: file.name, media_type: file.type, content_base64 } });
    state.files.push(uploaded);
    const layer = selectedLayer();
    const current = state.layerEdits[layer.id] || draftEdit;
    current.values.attachment_ids = [...new Set([...(current.values.attachment_ids || []), uploaded.id])];
    current.dirty = true;
    current.generation += 1;
    state.layerEdits[layer.id] = current;
    render();
    document.querySelector("#upload-status").textContent = `${uploaded.name} uploaded. Save the draft to keep it selected.`;
  } catch (error) {
    status.className = "inline-message error";
    status.textContent = `${error.message} Your draft text is still here.`;
  }
}

async function openLayer(id) {
  state.selectedLayerId = id;
  location.hash = `layers/${pathPart(id)}`;
  state.revisions = await api(`/api/layers/${pathPart(id)}/revisions`);
  state.flash = null;
  render();
}

async function resolveConflict() {
  const layer = selectedLayer();
  const initial = rememberLayerForm();
  if (!layer || !initial) return;
  try {
    const latest = await api(`/api/layers/${pathPart(layer.id)}`);
    const submitted = state.layerEdits[layer.id];
    const saved = await api(`/api/layers/${pathPart(layer.id)}`, {
      method: "PUT",
      json: { version: latest.version, ...submitted.values },
    });
    updateLayer(saved);
    const current = state.layerEdits[layer.id];
    if (current?.generation === submitted.generation) delete state.layerEdits[layer.id];
    else if (current) current.conflict = false;
    setFlash("Private draft saved");
    render();
  } catch (error) {
    setFlash(`${error.message} Your text is still here.`, true);
    render();
  }
}

async function activateLayer() {
  const layer = selectedLayer();
  try {
    await api(`/api/layers/${pathPart(layer.id)}/activate`, { method: "POST", json: { version: layer.version } });
    state.preview = false;
    await refresh(`Version ${layer.version} is now active`);
  } catch (error) {
    state.preview = false;
    setFlash(error.status === 409 ? "The draft changed before activation. Review the saved version again." : error.message, true);
    render();
  }
}

async function publicOff() {
  const layer = selectedLayer();
  const active = state.activeLayers[layer.id];
  try {
    const narrowed = await api(`/api/layers/${pathPart(layer.id)}/revoke`, { method: "POST", json: { revision: active.revision, public: true } });
    const namedRoutes = [...(narrowed.audience_users || []), ...(narrowed.audience_spaces || [])];
    await refresh(namedRoutes.length ? "Named sharing is still on" : "No active audience routes remain");
  } catch (error) {
    setFlash(error.status === 409 ? "The active release changed. It has been refreshed; review it before trying again." : error.message, true);
    await refresh();
  }
}

async function revokeRoute(kind, id) {
  const layer = selectedLayer();
  const active = state.activeLayers[layer.id];
  try {
    const narrowed = await api(`/api/layers/${pathPart(layer.id)}/revoke`, {
      method: "POST",
      json: {
        revision: active.revision,
        user_ids: kind === "person" ? [id] : [],
        space_ids: kind === "space" ? [id] : [],
      },
    });
    const remainingNames = [
      ...(narrowed.audience_users || []).map(contactName),
      ...(narrowed.audience_spaces || []).map(spaceName),
    ];
    const message = remainingNames.length
      ? `${remainingNames.join(" and ")} ${remainingNames.length === 1 ? "is" : "are"} still an active route`
      : "No named audience routes remain";
    await refresh(message);
  } catch (error) {
    setFlash(error.status === 409 ? "The active release changed. Review its routes before trying again." : error.message, true);
    await refresh();
  }
}

async function confirmWithdraw() {
  const layer = selectedLayer();
  try {
    await api(`/api/layers/${pathPart(layer.id)}/withdraw`, { method: "POST", json: {} });
    state.confirmWithdraw = false;
    await refresh("Sharing is off");
  } catch (error) {
    setFlash(`${error.message} The current release may still be active.`, true);
    render();
  }
}

async function openChat(id) {
  state.selectedChatId = id;
  state.room = await api(`/api/chats/${pathPart(id)}`);
  location.hash = `chats/${pathPart(id)}`;
  state.flash = null;
  state.transitionNote = null;
  render();
}

async function createChat(form) {
  const members = [...form.querySelectorAll('[name="chat-member"]:checked:not(:disabled)')].map((input) => input.value);
  try {
    let room;
    if (state.chatDialog === "new") {
      room = await api("/api/chats", { method: "POST", json: { title: form.elements.title.value, member_ids: members } });
      state.transitionNote = null;
    } else {
      room = await api(`/api/chats/${pathPart(state.room.id)}/participants`, { method: "POST", json: { member_ids: members } });
      state.transitionNote = "New room · earlier messages stay in the original chat";
    }
    state.chatDialog = null;
    await loadData();
    state.selectedChatId = room.id;
    state.room = await api(`/api/chats/${pathPart(room.id)}`);
    history.replaceState(null, "", `#chats/${pathPart(room.id)}`);
    render();
  } catch (error) {
    setFlash(error.message, true);
    render();
  }
}

async function removeParticipant(id) {
  const room = state.room;
  const name = participantName(id);
  try {
    await api(`/api/chats/${pathPart(room.id)}/participants/${pathPart(id)}`, { method: "DELETE", json: {} });
    await loadData();
    state.room = await api(`/api/chats/${pathPart(room.id)}`);
    state.transitionNote = `${name} no longer has access to this room`;
    render();
  } catch (error) {
    setFlash(`${error.message} Room access was not changed.`, true);
    render();
  }
}

async function sendMessage(form) {
  const room = state.room;
  const textarea = form.elements.body;
  const body = textarea.value;
  if (!body.trim()) return;
  let draft = readChatDraft(room.id);
  if (draft.body !== body) draft = { body, clientId: null };
  if (!draft.clientId) draft.clientId = crypto.randomUUID();
  sessionStorage.setItem(draftKey(room.id), JSON.stringify(draft));
  const status = form.querySelector("#chat-status");
  status.className = "inline-message";
  status.textContent = "Sending…";
  let accepted;
  try {
    accepted = await api(`/api/chats/${pathPart(room.id)}/messages`, { method: "POST", json: { client_message_id: draft.clientId, body } });
  } catch (error) {
    status.className = "inline-message error";
    status.textContent = error.status === 0 ? "Connection lost. Your message is still here." : `${error.message} Your message is still here.`;
    announce(status.textContent);
    return;
  }
  const currentDraft = readChatDraft(room.id);
  if (currentDraft.clientId === draft.clientId && currentDraft.body === body) sessionStorage.removeItem(draftKey(room.id));
  if (state.room?.id === room.id) {
    const duplicate = (state.room.messages || []).some((message) => message.id === accepted.id || (message.author_id === accepted.author_id && message.client_message_id === accepted.client_message_id));
    if (!duplicate) state.room.messages = [...(state.room.messages || []), accepted];
  }
  try {
    const [latestRoom, latestSync] = await Promise.all([
      api(`/api/chats/${pathPart(room.id)}`),
      api("/api/sync"),
    ]);
    if (state.room?.id === room.id) state.room = latestRoom;
    state.sync = latestSync;
    render();
    const refreshedStatus = document.querySelector("#chat-status");
    if (refreshedStatus && state.room?.id === room.id) refreshedStatus.textContent = "Message saved";
  } catch (error) {
    setFlash("Message saved. Latest room status is unavailable.");
    render();
  }
}

function clearChatDrafts() {
  if (!state.me) return;
  const prefix = `superyak:chat-draft:${state.me.peer_id}:${state.me.id}:`;
  for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
    const key = sessionStorage.key(index);
    if (key?.startsWith(prefix)) sessionStorage.removeItem(key);
  }
}

async function logout() {
  const complete = () => {
    state.logoutError = null;
    clearChatDrafts();
    state.layerEdits = {};
    state.editorIdentity = null;
    state.me = null;
    location.hash = "";
    showLogin();
  };
  try {
    await api("/api/logout", { method: "POST", json: {} });
    complete();
  } catch (error) {
    if (error.status === 401) {
      complete();
      return;
    }
    state.logoutError = "Sign-out could not be completed";
    state.profileDialog = true;
    render();
  }
}

async function showCard() {
  try {
    const card = await api("/api/connections/card");
    setFlash(JSON.stringify(card, null, 2));
  } catch (error) {
    setFlash(error.message, true);
  }
  render();
}

async function previewPair(form) {
  try {
    const card = JSON.parse(form.elements.card.value);
    state.pairPreview = await api("/api/connections/preview", { method: "POST", json: { card } });
    state.flash = null;
  } catch (error) {
    setFlash(error instanceof SyntaxError ? "Peer card is not valid JSON" : error.message, true);
  }
  render();
}

async function bootstrap() {
  if (location.pathname === "/public/" || location.pathname.startsWith("/public/view")) {
    await renderPublic();
    return;
  }
  try {
    state.me = await api("/api/me");
    bindEditorIdentity(state.me);
    await refresh();
  } catch (error) {
    showLogin(error.status === 401 ? "" : error.message);
  }
}

document.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.id === "login-form") {
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await api("/api/login", { method: "POST", json: { username: form.elements.username.value, password: form.elements.password.value } });
      const signedIn = await api("/api/me");
      bindEditorIdentity(signedIn);
      state.me = signedIn;
      state.logoutError = null;
      await refresh();
    } catch (error) {
      showLogin(error.message);
    }
    return;
  }
  if (form.id === "redeem-form") {
    try {
      await api("/api/invitations/redeem", { method: "POST", json: { token: form.elements.token.value, username: form.elements.username.value, name: form.elements.name.value, password: form.elements.password.value } });
      showLogin("Account created. Sign in to open your home.");
    } catch (error) {
      showLogin(error.message);
      const details = document.querySelector(".invitation-redeem");
      if (details) details.open = true;
    }
    return;
  }
  if (form.id === "reauth-form") {
    const expectedId = state.me.id;
    try {
      await api("/api/login", { method: "POST", json: { username: state.me.username, password: form.elements.password.value } });
      const signedIn = await api("/api/me");
      if (signedIn.id !== expectedId) throw new ApiError("Sign in with the account that owns this draft", 403);
      bindEditorIdentity(signedIn);
      state.me = signedIn;
      state.reauth = false;
      state.reauthError = null;
      await loadData();
      await loadRoute();
      setFlash("Signed in again. Your unsaved text is ready to save.");
      render();
    } catch (error) {
      state.reauthError = error.message;
      render();
    }
    return;
  }
  if (form.id === "layer-form") await saveLayer(form);
  if (form.id === "chat-form") await createChat(form);
  if (form.id === "message-form") await sendMessage(form);
  if (form.id === "pair-preview-form") await previewPair(form);
  if (form.id === "profile-form") {
    const oldName = state.me.name;
    try {
      await api("/api/me", { method: "PATCH", json: { name: form.elements.name.value } });
      state.me = await api("/api/me");
      bindEditorIdentity(state.me);
      state.profileDialog = false;
      setFlash(`Name corrected from ${oldName} to ${state.me.name}. Your account and sharing permissions did not change.`);
      await loadData();
      render();
    } catch (error) {
      setFlash(error.message, true);
      render();
    }
  }
});

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action === "new-layer") {
    try {
      const layer = await api("/api/layers", { method: "POST", json: {} });
      state.home.layers.push(layer);
      await openLayer(layer.id);
    } catch (error) { setFlash(error.message, true); render(); }
  }
  if (action === "open-layer") await openLayer(target.dataset.id);
  if (action === "preview") {
    if (currentLayerEdit()?.dirty) {
      const status = document.querySelector("#layer-status");
      status.className = "inline-message error";
      status.textContent = "Save this private draft before previewing a version.";
    } else { state.preview = true; render(); }
  }
  if (action === "activate") await activateLayer();
  if (action === "public-off") await publicOff();
  if (action === "revoke-route") await revokeRoute(target.dataset.routeKind, target.dataset.id);
  if (action === "resolve-conflict") await resolveConflict();
  if (action === "withdraw") { state.confirmWithdraw = true; render(); }
  if (action === "confirm-withdraw") await confirmWithdraw();
  if (action === "close-dialog") { state.preview = false; state.confirmWithdraw = false; state.chatDialog = null; state.profileDialog = false; render(); }
  if (action === "close-reauth") { state.reauth = false; render(); }
  if (action === "open-shared") { state.selectedSharedId = target.dataset.id; location.hash = `shared/${pathPart(target.dataset.id)}`; render(); }
  if (action === "new-chat") { state.chatDialog = "new"; render(); }
  if (action === "open-chat") await openChat(target.dataset.id);
  if (action === "change-participants") { state.chatDialog = "linked"; render(); }
  if (action === "remove-participant") await removeParticipant(target.dataset.id);
  if (action === "profile") { state.profileDialog = true; render(); }
  if (action === "logout") await logout();
  if (action === "invite") {
    try { state.invitation = await api("/api/invitations", { method: "POST", json: {} }); state.flash = null; }
    catch (error) { setFlash(error.message, true); }
    render();
  }
  if (action === "show-card") await showCard();
  if (action === "sync") {
    try { state.sync = await api("/api/sync", { method: "POST", json: {} }); setFlash("Delivery status refreshed"); }
    catch (error) { setFlash(error.message, true); }
    render();
  }
  if (action === "retry-delivery") {
    try { await api(`/api/sync/${pathPart(target.dataset.id)}/retry`, { method: "POST", json: {} }); await refresh("Delivery queued again"); }
    catch (error) { setFlash(error.message, true); render(); }
  }
  if (action === "confirm-pair") {
    try {
      await api("/api/connections/pair", { method: "POST", json: { card: state.pairPreview, fingerprint: state.pairPreview.fingerprint } });
      state.pairPreview = null;
      await refresh("Peer paired. Nothing has been shared automatically.");
    } catch (error) { setFlash(error.message, true); render(); }
  }
  if (action === "unpair") {
    try { await api(`/api/connections/${pathPart(target.dataset.id)}`, { method: "DELETE", json: {} }); await refresh("The peer and all of its contacts are disconnected"); }
    catch (error) { setFlash(error.message, true); render(); }
  }
});

document.addEventListener("input", (event) => {
  if (event.target.closest("#layer-form")) rememberLayerForm();
  if (event.target.id === "message-body" && state.room) {
    const previous = readChatDraft(state.room.id);
    const next = { body: event.target.value, clientId: previous.body === event.target.value ? previous.clientId : null };
    sessionStorage.setItem(draftKey(state.room.id), JSON.stringify(next));
  }
});

document.addEventListener("change", async (event) => {
  if (event.target.closest("#layer-form") && event.target.id !== "file-upload") rememberLayerForm();
  if (event.target.id === "space-context") {
    state.currentSpaceId = event.target.value;
    render();
  }
  if (event.target.id === "file-upload") await uploadFile(event.target);
});

window.addEventListener("hashchange", async () => {
  if (!state.me) return;
  state.flash = null;
  state.transitionNote = null;
  try { await loadRoute(); render(); }
  catch (error) { setFlash(error.message, true); render(); }
});

bootstrap();
