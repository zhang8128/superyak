"use strict";

const app = document.querySelector("#app");
const announcer = document.querySelector("#announcer");

const state = {
  me: null,
  demoAccounts: [],
  home: null,
  contacts: [],
  files: [],
  sync: { enabled: false, deliveries: [] },
  accounts: [],
  accessRequests: [],
  roleChanges: [],
  accountRolePreview: null,
  activation: null,
  corrections: [],
  connections: [],
  ships: [], dockCode: null, docking: null,
  activeLayers: {},
  activeLayerErrors: {},
  revisions: [],
  room: null,
  selectedLayerId: null,
  selectedSharedId: null,
  selectedChatId: null,
  currentSpaceId: "all",
  preview: false,
  spaceDialog: false,
  spaceError: null,
  confirmWithdraw: false,
  chatDialog: null,
  profileDialog: false,
  pairPreview: null,
  invitation: null,
  flash: null,
  transitionNote: null,
  briefEdit: null, briefHistory: null, chatPicked: null, chatError: null,
  reauth: false,
  reauthError: null,
  layerEdits: {},
  editorIdentity: null,
  logoutError: null,
  assistant: { enabled: false },
  assistance: {},
  sources: [],
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

function clearAccountAdministration() {
  state.accounts = []; state.accessRequests = []; state.roleChanges = []; state.invitation = null;
  state.accountRolePreview = null; state.profileDialog = false; state.pairPreview = null;
  state.ships = []; state.docking = null;
}

function bindEditorIdentity(user) {
  const next = identityKey(user);
  if (state.editorIdentity !== next) { state.briefEdit = null; state.briefHistory = null; state.boardPost = null; state.boardDone = null; state.boardAsk = null; state.board = null; state.boardView = null; state.grants = null; state.grantPeople = null; state.grantForm = null; state.grantAsk = null; state.layerEdits = {}; state.assistance = {}; state.sources = []; clearAccountAdministration(); Research.reset(); Dashboard.reset(); }
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
  return { route: ["home", "chats", "board", "grants", "layers", "shared", "spaces", "research", "search", "connections"].includes(route) ? route : "home", id: id ? decodeURIComponent(id) : null };
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
        ${navLink("board", "Board", "☰")}
        ${navLink("grants", "Grants", "✧")}
        ${navLink("layers", "My sharing layers", "▤")}
        ${navLink("shared", "Shared spaces", "◇")}
        ${navLink("spaces", "Circles & projects", "◎")}
        ${navLink("research", "Research & data", "⌕")}
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
        ${Dashboard.searchForm()}
        <button class="account-button" data-action="profile" aria-label="Account and sign out">
          <span class="account-meta"><strong>${name}</strong><span>${state.demoAccounts.length ? `Local demo · ${escapeHtml(state.me.username)}` : escapeHtml(currentSpace)}</span></span>
          <span class="avatar" aria-hidden="true">${escapeHtml(state.me.name.trim().charAt(0).toUpperCase() || "S")}</span>
        </button>
      </header>
      <main class="content" id="main-content" tabindex="-1">
        ${state.flash ? `<div class="notice ${state.flash.error ? "error" : ""}" role="status">${escapeHtml(state.flash.message)}</div>` : ""}
        ${content}
      </main>
    </div>
    ${spaceDialog()}${profileDialog()}${Dashboard.dialogs()}${reauthDialog()}${accountRoleDialog()}${dockingDialog()}
  </div>`;
}

function demoChoices() {
  if (!state.demoAccounts.length) return "";
  return `<section class="section"><h3>Try another dashboard</h3><p>Local demo. No password needed. Save any work you want to keep before switching accounts.</p><div class="button-row">${state.demoAccounts.map((account) => `<button class="button secondary" type="button" data-action="demo-login" data-username="${escapeHtml(account.username)}" ${account.username === state.me?.username ? "disabled" : ""}>Try ${escapeHtml(account.username)}</button>`).join("")}</div></section>`;
}

function showLogin(message = "") {
  dataLoadSequence++;
  state.me = null;
  state.home = null;
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
        ${demoChoices()}
        ${state.demoAccounts.length ? '<details><summary>Sign in with another account</summary>' : ''}
        <form id="login-form">
          <div class="field"><label for="username">Username</label><input class="input" id="username" name="username" autocomplete="username" required></div>
          <div class="field"><label for="password">Password</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required></div>
          <button class="button" type="submit">Sign in</button>
        </form>
        ${state.demoAccounts.length ? '</details>' : ''}
        <details class="invitation-redeem"><summary>Use an invitation</summary><p>An admin gives you a one-use token. Use the supplied username and name for a reserved account, or choose your own for a new invitation. You choose your password.</p><form id="redeem-form"><div class="field"><label for="invitation-token">Invitation token</label><input class="input" id="invitation-token" name="token" autocomplete="off" required></div><div class="field"><label for="new-username">New username</label><input class="input" id="new-username" name="username" autocomplete="username" required></div><div class="field"><label for="new-name">Your display name</label><input class="input" id="new-name" name="name" required></div><div class="field"><label for="new-password">New password</label><input class="input" id="new-password" name="password" type="password" minlength="12" autocomplete="new-password" required></div><button class="button secondary" type="submit">Create my account</button></form></details>
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

function homeView() { return Dashboard.home(); }

function layerStatus(layer) {
  const active = state.activeLayers[layer.id];
  if (layer.active_revision && state.activeLayerErrors[layer.id]) return `<span class="badge active">Active · details unavailable</span>`;
  if (!active) return `<span class="badge draft">Private draft</span>`;
  return `<span class="badge active">Active</span>`;
}

function shipName(id) {
  return (state.ships || []).find((ship) => ship.id === id)?.name || "a ship";
}

function draftedBy(layer) {
  return layer.drafted_by ? `Drafted by ${shipName(layer.drafted_by)}. Read it before you activate it.` : "";
}

function layerItem(layer) {
  const drafted = layer.drafted_by ? `<span>Drafted by ${escapeHtml(shipName(layer.drafted_by))}</span>` : "";
  return `<button class="item" data-action="open-layer" data-id="${escapeHtml(layer.id)}"><span class="item-main"><strong>${escapeHtml(layer.title)}</strong><span>Draft version ${layer.version}</span>${drafted}</span><span class="status-stack">${layerStatus(layer)}</span></button>`;
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
  return `<label class="choice"><input type="checkbox" name="audience-space" aria-label="${escapeHtml(space.name)}" aria-describedby="space-choice-${escapeHtml(space.id)}" value="${escapeHtml(space.id)}" ${selected.includes(space.id) ? "checked" : ""}><span class="choice-copy"><strong>${escapeHtml(space.name)}</strong><small id="space-choice-${escapeHtml(space.id)}">${escapeHtml((space.member_ids || []).map(contactName).join(", "))} · ${escapeHtml(note)}</small></span></label>`;
}

function effectiveAudience(active) {
  if (!active) return "Nobody can see this draft.";
  const names = (active.audience_users || []).map(contactName);
  const spaces = (active.audience_details || []).map((space) => `${space.name}: ${space.members.map((member) => member.name).join(", ")} (${space.kind === "organization" ? "current and future members" : "selected at activation"})`);
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
  const drafted = layer.drafted_by ? `<span class="state-note">${escapeHtml(draftedBy(layer))}</span>` : "";
  const unsaved = (currentLayerEdit()?.dirty ? '<span class="badge draft">Unsaved changes</span>' : "") + drafted;
  if (layer.active_revision && state.activeLayerErrors[layer.id]) {
    return `<span class="badge active">Active release</span>${unsaved}<span class="state-note">Latest sharing details unavailable</span>`;
  }
  if (!active) return `<span class="badge draft">Private draft</span>${unsaved}<span class="state-note">Sharing is off on this peer</span>`;
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
  if (!active) return `<div class="active-panel"><h3>Sharing is off on this peer</h3><p>Your saved draft is private. Preview a concrete saved version before turning it on.</p></div>`;
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

function previewDialog() {
  const layer = state.preview;
  if (!layer) return "";
  const spaces = layer.audience_details.map((space) => `${space.name}: ${space.members.map((member) => member.name).join(", ")} (${space.kind === "organization" ? "current and future members can see this release" : "these people selected at activation"})`);
  return `<dialog aria-labelledby="preview-title"><div class="dialog-body"><p class="eyebrow">Audience preview</p><h2 id="preview-title">Preview version ${layer.version}</h2><p>This exact saved version will become active. Later draft edits stay private until you activate again.</p><div class="preview-paper"><h3>${escapeHtml(layer.title)}</h3><p>${escapeHtml(layer.body)}</p></div><h3>Selected attachments</h3>${layer.files.length ? layer.files.map((file) => `<p><a href="/api/files/${pathPart(file.id)}" target="_blank" rel="noopener">Inspect ${escapeHtml(file.name)}</a><small class="meta"> · ${formatBytes(file.size)} · ${escapeHtml(file.media_type)}</small></p><details><summary>File details</summary><p class="fingerprint meta">SHA-256: ${escapeHtml(file.digest)}</p></details>`).join("") : "<p>No attachments selected.</p>"}<h3>Who would see it</h3><p>${[...layer.people.map((person) => person.name), ...spaces, ...(layer.public ? ["Anyone with the public link"] : [])].map(escapeHtml).join(" · ") || "Only you — no audience is selected."}</p>${layer.public ? "<p>Public access cannot exclude an individual.</p>" : ""}<div class="button-row"><button class="button" data-action="activate">Turn on version ${layer.version}</button><button class="button secondary" data-action="close-dialog">Keep it private</button></div></div></dialog>`;
}

function spaceDialog() {
  if (!state.spaceDialog) return "";
  return `<dialog aria-labelledby="space-title"><div class="dialog-body"><h2 id="space-title">Create a space</h2><p>You are included. Select local participants explicitly. Creating a space shares no layers or chat history.</p>${state.spaceError ? `<p role="alert">${escapeHtml(state.spaceError)}</p>` : ""}<form id="space-form"><div class="field"><label for="space-name">Space name</label><input class="input" id="space-name" name="name" maxlength="200" required autofocus></div><div class="field"><label for="space-kind">Space kind</label><select id="space-kind" name="kind"><option value="care-circle">Care circle</option><option value="project">Project</option><option value="organization">Organization</option></select></div><p>Organizations include current and future members in any active release shared with them. Care circles and projects keep the people selected at activation.</p><fieldset><legend>Local participants</legend>${state.contacts.filter((contact) => !contact.remote).map((contact) => `<label class="choice"><input type="checkbox" name="space-member" value="${escapeHtml(contact.id)}"><span>${escapeHtml(contact.name)}</span></label>`).join("")}</fieldset><div class="button-row"><button class="button" type="submit">Create space</button><button class="button secondary" type="button" data-action="close-dialog">Cancel</button></div></form></div></dialog>`;
}

async function createSpace(form) {
  try {
    await api("/api/spaces", { method: "POST", json: { name: form.elements.name.value, kind: form.elements.kind.value, member_ids: [...form.querySelectorAll('[name="space-member"]:checked')].map((input) => input.value) } });
    state.spaceDialog = false;
    await refresh("Space created. Choose it in a saved layer and preview before sharing.");
  } catch (error) { state.spaceError = error.message; render(); }
}

function withdrawDialog() {
  if (!state.confirmWithdraw) return "";
  return `<dialog aria-labelledby="withdraw-title"><div class="dialog-body"><h2 id="withdraw-title">Stop every active route?</h2><p>This stops access on this peer for named people, spaces, and the public link. Remote hosts must acknowledge withdrawal before their hosted access stops; offline hosts may still show it. Existing copies cannot be erased. Your private draft and release history remain.</p><div class="button-row"><button class="button danger" data-action="confirm-withdraw">Yes, stop all sharing</button><button class="button secondary" data-action="close-dialog">Keep sharing on</button></div></div></dialog>`;
}

function shipChoices(layer) {
  const mine = (state.ships || []).filter((ship) => ship.owner_id === state.me.id);
  const selected = layer.audience_users || [];
  return mine.map((ship) => `<label class="choice"><input type="checkbox" name="audience-ship" value="${escapeHtml(ship.id)}" ${selected.includes(ship.id) ? "checked" : ""}><span class="choice-copy"><strong>${escapeHtml(ship.name)}</strong><small>Your ship</small></span></label>`).join("") || `<p class="meta">You have no docked ships yet.</p>`;
}

// The Ships status view (what each ship has read, and when) is deferred to step 4.
function layerEditor(layer) {
  const instructions = layer.kind === "instructions";
  const active = state.activeLayers[layer.id];
  const edit = currentLayerEdit();
  return `<section class="card editor" aria-labelledby="editor-title"><div class="editor-head"><div><p class="eyebrow">Your private workspace</p><h2 id="editor-title">Edit this layer</h2><div class="status-stack">${editorState(layer, active)}</div></div></div>
    <form id="layer-form" data-layer-id="${escapeHtml(layer.id)}">
      <div class="field"><label for="layer-title">Layer title</label><input class="input" id="layer-title" name="title" maxlength="200" value="${escapeHtml(layer.title)}" required></div>
      <div class="field"><label for="layer-kind">Kind</label><select class="input" id="layer-kind" name="kind"><option value="note" ${instructions ? "" : "selected"}>Note for people</option><option value="instructions" ${instructions ? "selected" : ""}>Instructions for my ships</option></select></div>
      <div class="field"><label for="layer-body">What do you want to share?</label><textarea class="textarea" id="layer-body" name="body" maxlength="${instructions ? 20000 : 100000}">${escapeHtml(layer.body)}</textarea></div>
      ${instructions ? `<fieldset class="field"><legend>Ships</legend><small>Only your own ships can read instructions, and only once you turn on a version.</small><div class="choices">${shipChoices(layer)}</div></fieldset>` : `<fieldset class="field"><legend>Named people</legend><small>People only see an activated version. Selecting someone here does not reveal the private draft.</small><div class="choices">${state.contacts.map((contact) => choiceContact(contact, layer.audience_users || [])).join("") || `<p class="meta">No contacts are available yet.</p>`}</div></fieldset>
      <fieldset class="field"><legend>Care circles and spaces</legend><div class="choices">${state.home.spaces.map((space) => choiceSpace(space, layer.audience_spaces || [])).join("") || `<p class="meta">No spaces are available yet.</p>`}</div></fieldset>
      <fieldset class="field"><legend>Public access</legend><label class="choice public-choice"><input type="checkbox" name="public" ${layer.public ? "checked" : ""}><span class="choice-copy"><strong>Anyone with the public link</strong><small>Only the activated version and its chosen attachments are public.</small></span></label></fieldset>
      <fieldset class="field"><legend>Attachments</legend>${attachmentChoices(layer)}<label class="button secondary" for="file-upload">Upload a file</label><input class="sr-only" id="file-upload" type="file" accept="text/plain,text/csv,application/json,application/pdf,image/png,image/jpeg,image/gif,.csv,.json"><p id="upload-status" class="inline-message" role="status"></p></fieldset>`}
      <div class="editor-actions"><div class="button-row"><button class="button" type="submit">Save private draft</button><button class="button secondary" type="button" data-action="preview">Preview audience</button></div><span class="state-note">Saved version ${layer.version}</span></div>
      <p id="layer-status" class="inline-message ${edit?.conflict ? "error" : ""}" role="status">${edit?.conflict ? "This draft changed in another tab. Your text is still here." : ""}</p>${edit?.conflict ? '<button class="button secondary" type="button" data-action="resolve-conflict">Save my text onto the latest draft</button>' : ""}
    </form>
    ${assistantPanel(layer)}
    ${exportPanel(layer)}
    ${activePanel(layer, active)}${resourceDelivery(layer.id)}
    <div class="history"><h3>Release and correction history</h3><p class="meta">Earlier releases keep their words, version, date, and original account attribution. A corrected display name never changes grants.</p>${revisionHistory()}</div>
    ${previewDialog(layer)}${withdrawDialog()}
  </section>`;
}

function layersView() {
  const layer = layerForEditor();
  return `<header class="page-head"><div><p class="eyebrow">Private first</p><h1>My sharing layers</h1><p class="lede">Build your sharing layers at your own pace. Save them privately, see what each audience would see, and turn them on when you're ready.</p></div><button class="button" data-action="new-layer">New layer</button></header>
    <div class="workspace"><aside class="workspace-list"><div class="item-list">${state.home.layers.map(layerItem).join("") || empty("No layers yet", "Start with a private draft. You do not need to choose an audience.")}</div></aside>${layer ? layerEditor(layer) : `<section>${empty("Choose a layer", "Select a draft from the list or start a new one.")}</section>`}</div>${sourcePanel()}`;
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
  return `<header class="page-head"><div><p class="eyebrow">People and places</p><h1>Shared spaces</h1><p class="lede">Read active releases available to you through a named person, a selected space, or a public link.</p></div><button class="button" data-action="new-space">Create space</button></header>
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
  if (id === state.me.id) return state.me.name;
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

function messageDelivery(message, room) {
  if (message.state) return message.state;
  if (room?.origin) return null;  // a received room: only the station's own state, never a guess from client ids
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

const BOARD_WORDS = ["Posted ", "Linked ", "Done ", "Dropped "];  // work board 4.5: a board line's fixed first word
const BOARD_KINDS = ["spec", "plan", "build", "review", "ops", "other"];

function sourceLabel(message) {
  const source = message.source;
  if (!source) return "";
  // A grant's builder run names its grantee too (grants step 3, G17). Escaped where it is shown.
  if (source.kind === "run") return source.mode === "build" ? (source.root_name ? `builder run for ${source.root_name}${source.via_name ? `, via ${source.via_name}` : ""}` : "builder run") : "read-only run";
  if (source.kind === "notice") return "station notice";
  // Only the station writes a kind-claim body, so no member's post can pass as a board line (work board 5.2).
  if (source.kind === "claim") return BOARD_WORDS.some((word) => String(message.body || "").startsWith(word)) ? "board" : "claim";
  return source.kind === "post" ? "no run ticket" : "";
}

// The server's mark for words a room's host attributes to someone on this station that this station never sent.
const UNVERIFIED_AUTHOR = "Unverified: the room's host says this is from someone on this station";

function messageMarkup(message, room) {
  const mine = isSelf(message.author_id);
  const system = room?.system_author;  // the station's own author, known by id, never by display name (R31)
  const author = mine ? "You" : system && message.author_id === system.id ? "Station" : message.unverified ? UNVERIFIED_AUTHOR : participantName(message.author_id);
  const delivery = messageDelivery(message, room);
  return `<div class="message${mine ? " mine" : ""}${message.unverified ? " unverified" : ""}"><div class="message-meta">${escapeHtml(author)}${sourceLabel(message) ? ` · <span class="message-source">${escapeHtml(sourceLabel(message))}</span>` : ""}</div><p>${escapeHtml(message.body)}</p><div class="message-meta">${formatDate(message.created)}${delivery ? ` · ${escapeHtml(deliveryText(delivery))}` : ""}</div></div>`;
}

// Ship briefs S4: whose words a revision is, from its own author fields and never from a name. The room's owner when
// the author is the owner and a person (or an older station doesn't say); a ship when the station says ship.
function briefAuthorClass(room, item) {
  if (item.author_kind === "ship") return "ship";
  if (item.author_id && item.author_id === room.owner_id && (item.author_kind === "person" || item.author_kind == null)) return "owner";
  return "other";
}

function briefAuthorLine(room, item) {
  const kind = briefAuthorClass(room, item);
  if (kind === "owner") return room.owner_id === state.me.id ? "Written by you" : `Written by the room's owner, ${item.author_name}`;
  if (kind === "ship") return `Written by ${item.author_name}, a ship, not the room's owner`;
  return `Written by ${item.author_name}, not the room's owner`;
}

// The author line, everywhere a brief's text shows (S4). A ship's revision leads with the "Ship" tag. All escaped.
function briefAuthor(room, item, place = "") {
  const tag = briefAuthorClass(room, item) === "ship" ? '<span class="badge pending brief-ship-tag">Ship</span> ' : "";
  return `<p class="meta brief-author ${place}">${tag}${escapeHtml(briefAuthorLine(room, item))}</p>`;
}

function briefMeta(brief) {
  if (brief.carried_from) return `Carried from the previous room on ${formatDate(brief.updated)}`;
  return `Revision ${brief.revision} · updated ${formatDate(brief.updated)}`;
}

// S4: when the editor opens with a ship's text, saving makes all of it the owner's, so it says so above Save.
function briefWarning(edit) {
  if (!edit.shipAuthor) return "";
  // Hidden while the box is blank (trimmed): Save then removes the brief, so nothing becomes the owner's. The input
  // handler toggles it as he types.
  return `<p class="brief-warning" role="note"${edit.body.trim() ? "" : " hidden"}>${escapeHtml(`This text was written by ${edit.shipAuthor}, a ship. Saving makes all of it yours, so read it all first.`)}</p>`;
}

// S5: the owner's history, newest first. Every body and name is escaped. "Use this text" puts a revision's body in
// the editor as its value, at the room's current revision, and Save is the ordinary save. A removal has no text to use.
// "Use this text" over typing the owner hasn't saved asks first, in place, as the board's Drop does.
function briefUseAsk(revision) {
  const n = escapeHtml(revision);
  return `<div class="board-ask" role="group" aria-label="Replace your unsaved text with revision ${n}?"><p>Replace your unsaved text with revision ${n}?</p><div class="button-row"><button class="button secondary" type="button" data-action="brief-use-cancel">Cancel</button><button class="button danger" type="button" data-action="brief-use-confirm" data-revision="${n}" aria-label="Yes, replace my text with revision ${n}">Yes</button></div></div>`;
}

function briefHistory(room) {
  const history = state.briefHistory?.roomId === room.id ? state.briefHistory : null;
  if (!history) return "";
  let rows = "";
  if (history.items?.length === 0 && !history.error) rows = `<p class="meta">No revisions yet.</p>`;
  else if (history.items?.length) {
    rows = `<ol class="brief-revisions">${history.items.map((item) => `<li class="brief-revision">${briefAuthor(room, item)}<p class="meta">${escapeHtml(`Revision ${item.revision} · ${formatDate(item.updated)}${item.carried_from ? " · carried from the previous room" : ""}`)}</p>${item.body ? `<div class="brief-revision-body">${escapeHtml(item.body)}</div>${history.ask === item.revision ? briefUseAsk(item.revision) : `<button class="button ghost" type="button" data-action="use-brief-revision" data-revision="${escapeHtml(item.revision)}">Use this text</button>`}` : '<p class="meta">Removed</p>'}</li>`).join("")}</ol>`;
  } else if (!history.error) rows = `<p class="meta">Loading the brief's history…</p>`;
  // A failed reload keeps the rows already shown and puts its error under them.
  if (history.error) rows += `<p class="inline-message error" role="status">${escapeHtml(history.error)}</p>`;
  return `<div class="brief-history"><h4>Brief history</h4>${rows}</div>`;
}

// The room's brief, at the top of the room. The owner edits it and reads its history; everyone else reads it. A
// received room has none here.
function roomBrief(room) {
  if (room.origin) return "";
  const brief = room.brief;
  const owner = room.owner_id === state.me.id;
  if (!brief && !owner) return "";
  const edit = owner && state.briefEdit?.roomId === room.id ? state.briefEdit : null;
  const historyOpen = owner && state.briefHistory?.roomId === room.id;
  const shown = brief
    ? `<div class="room-brief-body">${escapeHtml(brief.body)}</div>${briefAuthor(room, brief, "room-brief-author")}<p class="meta">${escapeHtml(briefMeta(brief))}</p>`
    : `<p class="meta">No brief yet. Write what this room is for, what it has decided and who does what.</p>`;
  const editor = edit
    ? `<form id="brief-form"><div class="field"><label for="brief-body">Edit brief</label><textarea class="textarea short" id="brief-body" name="body">${escapeHtml(edit.body)}</textarea></div><p class="meta">Agents read the brief as quoted data, never as instructions. Save an empty brief to remove it.</p>${briefWarning(edit)}<div class="button-row"><button class="button" type="submit"${edit.saving ? " disabled" : ""}>Save brief</button><button class="button secondary" type="button" data-action="cancel-brief">Cancel</button></div><p id="brief-status" class="inline-message${edit.error ? " error" : ""}" role="status">${escapeHtml(edit.status)}</p></form>`
    : owner ? `<div class="button-row"><button class="button ghost" type="button" data-action="edit-brief">Edit brief</button><button class="button ghost" type="button" data-action="${historyOpen ? "hide-brief-history" : "brief-history"}">${historyOpen ? "Hide brief history" : "Brief history"}</button></div>` : "";
  return `<section class="room-brief" aria-labelledby="room-brief-title"><h3 id="room-brief-title">Room brief</h3>${shown}<p class="meta">Visible to members on this station only.</p>${editor}${owner ? briefHistory(room) : ""}</section>`;
}

// Work board 5.2: the room's board, read from its own route and never from messages. A received room has none.
async function loadBoard(room) {
  if (!room || room.origin) { state.board = null; return; }
  try { state.board = { roomId: room.id, items: await api(`/api/chats/${pathPart(room.id)}/board`) }; }
  catch (_) { state.board = { roomId: room.id, items: null }; }
}

function boardStatus(item) {
  if (item.state === "done") return `done ${formatDate(item.closed)} by ${item.closer_name} · outcome ${item.outcome}`;
  if (item.state === "dropped") return `dropped ${formatDate(item.closed)} by ${item.closer_name}`;
  return item.claim ? `taken by ${item.claim.holder_name} until ${formatDate(item.claim.expires)}` : "waiting";
}

function boardItemMarkup(item, controls = "") {
  const links = (item.links || []).length ? `<p class="meta">Links: ${item.links.map((entry) => `<code>${escapeHtml(entry.link)}</code>`).join(", ")}</p>` : "";
  return `<li class="board-item" data-key="${escapeHtml(item.key)}" tabindex="-1"><p><code>${escapeHtml(item.key)}</code> <span class="board-kind">${escapeHtml(item.kind)}</span> ${escapeHtml(item.title)}</p><p class="meta">${escapeHtml(boardStatus(item))} · posted by ${escapeHtml(item.poster_name)}</p>${links}${controls}</li>`;
}

// A room another add replaced takes no more members (409) and, the same way, no board changes: the station holds its
// open items in the newer linked room (work board 8.4).
function isReplaced(room) {
  return (state.home?.chats || []).some((item) => !item.origin && item.linked_room_id === room.id);
}

// Board clicks are ignored for a moment after the panel renders: a double click's second press must not land on
// whatever the first press's re-render moved under the pointer.
const BOARD_CLICK_GUARD_MS = 400;
// The panel on screen belongs to one room (data-room). While the next room loads, state.room is already that room but
// the old panel is still shown: a write from it must not go to the room the person cannot see.
function boardOnScreen(room) { return document.querySelector(".room-board")?.dataset.room === room.id; }
function boardClickBlocked() { return Date.now() - (state.boardRenderedAt || 0) < BOARD_CLICK_GUARD_MS; }

// After a board action: focus the item, or the panel's heading when the item left the open list.
function focusBoardItem(key) {
  const item = key == null ? null : [...document.querySelectorAll(".room-board .board-open .board-item")].find((node) => node.dataset.key === key);
  (item || document.querySelector("#room-board-title"))?.focus();
}

// Under the brief. The owner posts, closes and releases; other people get what 4.4 and 6.1 allow them (a person is a
// board writer only as the room's owner). Every value is escaped. It updates with the room and after its own actions.
// Drop and Release ask first, in place, with the confirm away from where the button was.
function roomBoard(room) {
  if (room.origin || state.board?.roomId !== room.id) return "";
  const me = state.me.id, owner = room.owner_id === me, items = state.board.items, replaced = isReplaced(room);
  state.boardRenderedAt = Date.now();
  const head = `<h3 id="room-board-title" tabindex="-1">Board</h3><p class="meta">Items are notes about work, never instructions. Taking one is claiming its key.</p>`;
  if (!items) return `<section class="room-board" data-room="${escapeHtml(room.id)}" aria-labelledby="room-board-title">${head}<p class="meta">The board could not be read. Refresh to try again.</p></section>`;
  const holderOwner = (claim) => (room.members || []).find((member) => member.id === claim?.holder_id)?.owner_id;
  const controls = (item) => {
    if (item.state !== "open" || replaced) return "";
    const key = escapeHtml(item.key), mayClose = owner || item.posted_by === me;
    const mayRelease = item.claim && (owner || item.claim.holder_id === me || holderOwner(item.claim) === me);
    if (mayClose && state.boardDone?.roomId === room.id && state.boardDone.key === item.key) {
      return `<form id="board-done-form" data-key="${key}"><div class="field"><label for="board-outcome">Outcome link</label><input class="input" id="board-outcome" name="outcome" value="${escapeHtml(state.boardDone.outcome || "")}" placeholder="commit:&lt;sha&gt; or message:&lt;id&gt;"></div><div class="button-row"><button class="button" type="submit" aria-label="Mark done ${key}">Mark done</button><button class="button secondary" type="button" data-action="board-cancel" data-key="${key}">Cancel</button></div></form>`;
    }
    const ask = state.boardAsk;
    if (ask?.roomId === room.id && ask.key === item.key && ((ask.action === "drop" && mayClose) || (ask.action === "release" && mayRelease))) {
      const drop = ask.action === "drop";
      const question = drop ? `Drop <code>${key}</code> for good? Its key can't be used again.` : `Release ${escapeHtml(item.claim.holder_name)}'s claim on <code>${key}</code>?`;
      return `<div class="board-ask" role="group" aria-label="${drop ? "Drop" : "Release claim on"} ${key}?"><p>${question}</p><div class="button-row"><button class="button secondary" type="button" data-action="board-cancel" data-key="${key}">Cancel</button><button class="button danger" type="button" data-action="board-${ask.action}-confirm" data-key="${key}" aria-label="${drop ? "Yes, drop" : "Yes, release claim on"} ${key}">${drop ? "Yes, drop" : "Yes, release"}</button></div></div>`;
    }
    return `<div class="button-row">${mayClose ? `<button class="button ghost" type="button" data-action="board-done" data-key="${key}" aria-label="Mark done ${key}">Mark done</button><button class="button danger secondary" type="button" data-action="board-drop" data-key="${key}" aria-label="Drop ${key}">Drop</button>` : ""}${mayRelease ? `<button class="button secondary" type="button" data-action="board-release" data-key="${key}" aria-label="Release claim on ${key}">Release claim</button>` : ""}</div>`;
  };
  const open = items.filter((item) => item.state === "open"), closed = items.filter((item) => item.state !== "open");
  const draft = state.boardPost?.roomId === room.id ? state.boardPost : { key: "", title: "", kind: "build" };
  // No maxlength on the title: the station counts code points, a browser UTF-16 units (Review Focus 5).
  const post = owner && !replaced ? `<form id="board-post-form" class="board-post"><div class="field"><label for="board-key">Key</label><input class="input" id="board-key" name="key" value="${escapeHtml(draft.key)}" placeholder="spec:d7"></div><div class="field"><label for="board-title">Title</label><input class="input" id="board-title" name="title" value="${escapeHtml(draft.title)}"></div><div class="field"><label for="board-kind">Kind</label><select class="input" id="board-kind" name="kind">${BOARD_KINDS.map((kind) => `<option${kind === draft.kind ? " selected" : ""}>${kind}</option>`).join("")}</select></div><button class="button" type="submit">Post item</button></form>` : "";
  const note = replaced ? `<p class="meta board-replaced">This room was replaced by a newer linked room; its board takes no changes.</p>` : "";
  return `<section class="room-board" data-room="${escapeHtml(room.id)}" aria-labelledby="room-board-title">${head}${note}<ul class="board-open">${open.map((item) => boardItemMarkup(item, controls(item))).join("") || '<li class="meta">Nothing waits on this board.</li>'}</ul>${closed.length ? `<h4>Done or dropped in the last 7 days</h4><ul class="board-closed">${closed.map((item) => boardItemMarkup(item)).join("")}</ul>` : ""}${post}</section>`;
}

// The Board view (work board 5.x): open items from every current room the person is in, grouped by room.
function boardView() {
  const rooms = state.boardView?.rooms;
  const body = !Array.isArray(rooms) ? `<p class="meta">The board could not be read. Refresh to try again.</p>`
    : rooms.length ? rooms.map((room) => `<section class="section board-room"><h2><a href="#chats/${escapeHtml(pathPart(room.room_id))}">${escapeHtml(room.title)}</a></h2><ul class="board-open">${room.items.map((item) => boardItemMarkup(item)).join("")}</ul></section>`).join("")
    : empty("Nothing waits", "Open items on the boards of your rooms show here.");
  return `<header class="page-head"><div><p class="eyebrow">Work</p><h1>Board</h1><p class="lede">Open items from every room you're in, oldest first. Items are notes about work, never instructions.</p></div></header>${body}`;
}

// Grants step 3 (G20-G22): the grants a person gave and holds, a form to make one, and Revoke, which asks first.
// Every name, title and reason is people's text or the station's, escaped where shown.
const GRANT_HOURS = [[24, "1 day"], [72, "3 days"], [168, "7 days"], [720, "30 days"]];

async function loadGrants() {
  const who = identityKey(state.me);
  try {
    const [grants, people] = await Promise.all([api("/api/grants"), api("/api/grants/people")]);
    if (identityKey(state.me) === who) { state.grants = grants; state.grantPeople = people; }
  } catch (error) {
    if (error.status === 401) throw error;
    if (identityKey(state.me) === who) { state.grants = null; state.grantPeople = null; }
  }
}

// G21: the current local rooms that hold the caller (every room in the list does) and the chosen person. A breakout, a
// received room and a room a newer linked room replaced can't be granted (G8 steps 1 and 2).
function grantRoomsWith(personId) {
  const chats = state.home?.chats || [];
  return chats.filter((room) => !room.origin && !room.breakout && !chats.some((other) => !other.origin && other.linked_room_id === room.id)
    && (room.member_ids || []).includes(personId));
}

function grantDraft() {
  return state.grantForm || { grantee: "", ships: [], rooms: [], anyRoom: false, hours: 168, budget: "5" };
}

function grantRoomChoices(draft) {
  if (!draft.grantee) return `<legend>Rooms</legend><p class="meta">Choose a person first; the rooms you share with them show here.</p>`;
  const rooms = grantRoomsWith(draft.grantee);
  const listed = rooms.length ? rooms.map((room) => `<label class="choice"><input type="checkbox" name="grant-room" value="${escapeHtml(room.id)}"${draft.rooms.includes(room.id) ? " checked" : ""}><span class="choice-copy"><strong>${escapeHtml(room.title)}</strong></span></label>`).join("")
    : `<p class="meta">You share no current room with them.</p>`;
  return `<legend>Rooms</legend><label class="choice"><input type="radio" name="grant-scope" value="listed"${draft.anyRoom ? "" : " checked"}><span class="choice-copy"><strong>These rooms</strong></span></label><div class="choices grant-room-list">${listed}</div><label class="choice"><input type="radio" name="grant-scope" value="*"${draft.anyRoom ? " checked" : ""}><span class="choice-copy"><strong>Any room you share with them</strong><small>Rooms made later too. A run builds only in a room you are in.</small></span></label>`;
}

function grantForm() {
  const draft = grantDraft(), mine = (state.ships || []).filter((ship) => ship.owner_id === state.me.id);  // an admin is sent every ship
  const intro = `<p>Their mentions start builder runs of your ships on your machine. A run can read your repository and uses your model time, and its reply is posted in the room.</p>`;
  const body = !mine.length ? `<p class="meta">You have no ships to grant. Dock a machine's agent first.</p>`
    : `<form id="grant-form"><div class="field"><label for="grant-person">Person</label><select class="input" id="grant-person" name="grantee"><option value="">Choose a person</option>${(state.grantPeople || []).map((person) => `<option value="${escapeHtml(person.id)}"${person.id === draft.grantee ? " selected" : ""}>${escapeHtml(person.name)}</option>`).join("")}</select></div><fieldset class="field"><legend>Ships</legend><div class="choices">${mine.map((ship) => `<label class="choice"><input type="checkbox" name="grant-ship" value="${escapeHtml(ship.id)}"${draft.ships.includes(ship.id) ? " checked" : ""}><span class="choice-copy"><strong>${escapeHtml(ship.name)}</strong></span></label>`).join("")}</div></fieldset><fieldset class="field grant-rooms">${grantRoomChoices(draft)}</fieldset><div class="field"><label for="grant-hours">How long</label><select class="input" id="grant-hours" name="hours">${GRANT_HOURS.map(([hours, label]) => `<option value="${hours}"${hours === draft.hours ? " selected" : ""}>${label}</option>`).join("")}</select></div><div class="field"><label for="grant-budget">Builds a day</label><input class="input" id="grant-budget" name="budget" type="number" min="1" max="500" step="1" value="${escapeHtml(draft.budget)}"></div><button class="button" type="submit">Make grant</button></form>`;
  return `<section class="section grant-make" aria-labelledby="grant-make-title"><h2 id="grant-make-title">Let someone build your ships</h2>${intro}${body}</section>`;
}

function readGrantForm(form) {
  const checked = (name) => [...form.querySelectorAll(`[name="${name}"]:checked`)].map((input) => input.value);
  return { grantee: form.elements.grantee.value, ships: checked("grant-ship"), rooms: checked("grant-room"),
           anyRoom: form.querySelector('[name="grant-scope"]:checked')?.value === "*", hours: Number(form.elements.hours.value), budget: form.elements.budget.value };
}

function grantRoomsText(grant) {
  if (grant.rooms === "*") return "Any room you share with them";
  return grant.rooms.map((room) => room.current ? `${room.title} (replaced; now covers ${room.current.title})` : room.title).join(", ");
}

// The ask takes the Revoke button's place with its question first, so a hurried second press lands on text; Cancel
// gets the focus, as the board's Drop does.
function grantItem(grant, given) {
  const short = escapeHtml(grant.short);
  const ships = grant.targets.map((ship) => `${ship.name}, ${ship.ship_builds_left} grant build${ship.ship_builds_left === 1 ? "" : "s"} left for the ship`).join("; ");
  const status = grant.valid ? '<span class="badge active">Valid</span>' : `<span class="badge failed">Not valid</span> ${escapeHtml(grant.reason || "")}`;
  let controls = "";
  if (given && grant.revoked == null) {
    const ask = state.grantAsk?.id === grant.id ? state.grantAsk : null;
    controls = ask
      ? `<div class="board-ask grant-ask" role="group" aria-label="Revoke ${short}?"><p>Revoke ${short}? Their mentions stop starting builder runs at once; a run already going finishes.</p><div class="field"><label for="grant-reason">Reason (optional)</label><input class="input" id="grant-reason" value="${escapeHtml(ask.reason)}"></div><div class="button-row"><button class="button secondary" type="button" data-action="grant-cancel" data-id="${escapeHtml(grant.id)}">Cancel</button><button class="button danger" type="button" data-action="grant-revoke-confirm" data-id="${escapeHtml(grant.id)}" aria-label="Yes, revoke ${short}">Yes, revoke</button></div></div>`
      : `<div class="button-row"><button class="button danger secondary" type="button" data-action="grant-revoke" data-id="${escapeHtml(grant.id)}" aria-label="Revoke ${short}">Revoke</button></div>`;
  }
  return `<li class="grant-item" data-id="${escapeHtml(grant.id)}"><p><code>${short}</code> ${escapeHtml(given ? `To ${grant.grantee?.name}` : `From ${grant.issuer?.name}`)} ${status}</p><p class="meta">Ships: ${escapeHtml(ships)}</p><p class="meta">Rooms: ${escapeHtml(grantRoomsText(grant))}</p><p class="meta">${escapeHtml(`${grant.budget_left} of ${grant.budget} builds left in the last 24 hours · expires ${formatDate(grant.expires)}`)}</p>${controls}</li>`;
}

function grantsView() {
  const head = `<header class="page-head"><div><p class="eyebrow">Your ships</p><h1>Grants</h1><p class="lede">A grant lets another person's mentions start builder runs of your ships, in rooms you share, for a while, with a daily budget of builds.</p></div></header>`;
  if (!Array.isArray(state.grants)) return `${head}<p class="meta">Grants could not be read. Refresh to try again.</p>`;
  const me = state.me.id, held = state.grants.filter((grant) => grant.grantee?.id === me), given = state.grants.filter((grant) => grant.grantee?.id !== me);
  const list = (grants, mine, none) => grants.length ? `<ul class="grant-list">${grants.map((grant) => grantItem(grant, mine)).join("")}</ul>` : `<p class="meta">${none}</p>`;
  return `${head}${grantForm()}<section class="section grants-given" aria-labelledby="grants-given-title"><h2 id="grants-given-title" tabindex="-1">Given by you</h2>${list(given, true, "You haven't let anyone build your ships.")}</section><section class="section grants-held" aria-labelledby="grants-held-title"><h2 id="grants-held-title">Held by you</h2>${list(held, false, "No one has let you build their ships.")}</section>`;
}

// One grant write at a time (G22): a second click while one is on its way would make a second grant or meet the first
// one's revoke. The list is read again after every write, so it shows what the station holds.
async function grantWrite(path, json, message, saved = () => {}) {
  if (state.grantSaving) return;
  state.grantSaving = true;
  const who = identityKey(state.me);
  try {
    const answer = await api(path, { method: "POST", json });
    if (identityKey(state.me) !== who) return;
    saved(answer);
    state.grantAsk = null;
    setFlash(message(answer));
  } catch (error) {
    if (error.status === 401) { showLogin("Your session ended. Sign in again; text in an open form has not been sent."); return; }
    if (identityKey(state.me) === who) setFlash(error.message, true);
  } finally {
    state.grantSaving = false;
    if (state.me && identityKey(state.me) === who) {
      try { await loadGrants(); } catch (_) { /* the list below says it could not be read */ }
      if (routeParts().route === "grants") render();
    }
  }
}

async function makeGrant(form) {
  if (state.grantSaving) return;
  const draft = state.grantForm = readGrantForm(form), rooms = draft.anyRoom ? "*" : draft.rooms;
  const missing = !draft.grantee ? "Choose a person." : !draft.ships.length ? "Choose at least one ship." : rooms !== "*" && !rooms.length ? "Choose at least one room, or any room you share with them." : null;
  if (missing) { setFlash(missing, true); render(); return; }
  // The budget field's own validation (min 1, max 500, step 1) stops an out-of-range or fractional budget before this
  // runs; an empty field is sent as 0, which the station refuses with its own message.
  await grantWrite("/api/grants", { grantee: draft.grantee, targets: draft.ships, rooms, hours: draft.hours, budget: Number(draft.budget) },
                   (grant) => `Grant ${grant.short} made.`, () => { state.grantForm = null; });
}

// One board write at a time: a second click while one is on its way would get 409 for the first one's own work and
// show it as a failure (Review Focus 4). The board and the room are read again after every write, so the panel shows
// what the station holds and the history shows the new line. focusKey: the item to focus afterwards (the panel's
// heading if it left the open list); undefined leaves focus to the caller.
async function boardWrite(path, json, message, { saved = () => {}, focusKey } = {}) {
  const room = state.room;
  if (!room || state.boardSaving || !boardOnScreen(room)) return;
  state.boardSaving = true;
  let ok = false;
  try {
    const answer = await api(`/api/chats/${pathPart(room.id)}${path}`, { method: "POST", json });
    saved();
    state.boardDone = null; state.boardAsk = null;
    // A close that released someone else's claim says whose (the station's name, escaped where shown).
    setFlash(answer?.released ? `${message} ${answer.released}'s claim on it is released.` : message);
    ok = true;
  } catch (error) {
    if (error.status === 401) { showLogin("Your session ended. Sign in again; text in an open form has not been sent."); return; }
    setFlash(error.message, true);
  } finally {
    state.boardSaving = false;
    if (state.me && state.room?.id === room.id) {
      try { const latest = await api(`/api/chats/${pathPart(room.id)}`); if (state.room?.id === room.id) state.room = latest; } catch (_) { /* the board below still reads */ }
      if (state.room?.id === room.id) await loadBoard(state.room);
    }
    render();
    if (!ok && state.boardDone?.roomId === room.id) document.querySelector("#board-outcome")?.focus();
    else if (focusKey !== undefined) focusBoardItem(focusKey);
  }
}

async function postBoardItem(form) {
  if (state.boardSaving || !state.room || !boardOnScreen(state.room)) return;
  const roomId = state.room.id, draft = { key: form.elements.key.value, title: form.elements.title.value, kind: form.elements.kind.value };
  state.boardPost = { roomId, ...draft };
  await boardWrite("/board", draft, "Item posted.", { saved: () => { if (state.boardPost?.roomId === roomId) state.boardPost = null; } });
  if (state.me) document.querySelector("#board-key")?.focus();  // posted or refused, the key field is where the next try starts
}

// In "Start a new linked chat": shown only when there is a brief, unchecked, with the text that would be carried and
// who wrote it (S4), since a carry keeps the author.
function carryBriefChoice(room) {
  const brief = room && !room.origin ? room.brief : null;
  if (!brief) return "";
  return `<fieldset class="field"><legend>Room brief</legend><label class="choice"><input type="checkbox" name="carry-brief" value="${escapeHtml(brief.revision)}"><span class="choice-copy"><strong>Carry the room brief into the new room</strong></span></label>${briefAuthor(room, brief, "carry-brief-author")}<div class="carry-brief-text">${escapeHtml(brief.body)}</div></fieldset>`;
}

const CARRY_HELP = "Only the brief, if ticked, and the board's open items are carried. Earlier messages stay with their original participants.";

// Work board 5.x: adding members carries the room's open board items, so the dialog says what is carried whenever the
// room has a brief or an open item. The items are read when the dialog opens: null when they couldn't be read, and
// then the dialog says it anyway.
async function openBoardItems(room) {
  if (!room || room.origin) return [];
  try { return (await api(`/api/chats/${pathPart(room.id)}/board`)).filter((item) => item.state === "open"); }
  catch (_) { return null; }
}

function carryHelp(room) {
  const items = state.chatBoard;
  if (!room?.brief && items !== null && !items?.length) return "";
  const moving = !items?.length ? "" : items.length === 1
    ? "This open board item, with its links and claim, moves to the new room. Drop it first if it shouldn't."
    : `These ${items.length} open board items, with their links and claims, move to the new room. Drop any that shouldn't first.`;
  const list = moving ? `<div class="carry-board"><p>${escapeHtml(moving)}</p><ul>${items.map((item) => `<li><code>${escapeHtml(item.key)}</code> ${escapeHtml(item.title)}</li>`).join("")}</ul></div>` : "";
  return `<p class="meta carry-help">${CARRY_HELP}</p>${list}`;
}

function roomDetail(room) {
  const draft = readChatDraft(room.id);
  const canManage = room.owner_id === state.me.id && !room.origin;
  const replaced = (state.home?.chats || []).some((item) => !item.origin && item.linked_room_id === room.id);  // takes no more members (409)
  return `<section><p class="eyebrow">${room.origin ? "Received private room" : "Private room"}</p><h2>${escapeHtml(room.title)}</h2><div class="participants" aria-label="Participants">${(room.member_ids || []).map((id) => `<span class="participant">${escapeHtml(participantName(id))}</span>`).join("")}</div>${roomBrief(room)}${roomBoard(room)}${shipBanner(room)}${state.transitionNote ? `<div class="notice">${escapeHtml(state.transitionNote)}</div>` : ""}${resourceDelivery(room.id)}<div class="messages" aria-label="Messages">${(room.messages || []).map((message) => messageMarkup(message, room)).join("") || empty("No messages yet", "This room begins with an empty history.")}</div>
    <form class="composer" id="message-form"><label class="sr-only" for="message-body">Message</label><textarea class="textarea" id="message-body" name="body" aria-label="Message" maxlength="20000" placeholder="Write a private message…">${escapeHtml(draft.body)}</textarea><button class="button" type="submit">Send message</button><p id="chat-status" class="inline-message" role="status"></p></form>
    ${canManage ? `<div class="room-management"><p class="meta">Removing someone stops access on this peer and cancels obsolete queued content. Remote hosts must acknowledge removal; offline hosts may still show earlier content. Existing copies cannot be erased.</p><div class="button-row">${replaced ? "" : '<button class="button ghost" data-action="change-participants">Change participants</button>'}${(room.member_ids || []).filter((id) => !isSelf(id)).map((id) => `<button class="button danger secondary" data-action="remove-participant" data-id="${escapeHtml(id)}">Remove ${escapeHtml(participantName(id))} from this room</button>`).join("")}</div></div>` : ""}
  </section>`;
}

function chatDialog() {
  if (!state.chatDialog) return "";
  const room = state.room;
  const existing = new Set(state.chatDialog === "linked" ? room?.member_ids || [] : []);
  const picked = new Set(state.chatPicked || []);
  const title = state.chatDialog === "new" ? "Start a private chat" : "Start a new linked chat";
  return `<dialog aria-labelledby="chat-dialog-title"><div class="dialog-body"><h2 id="chat-dialog-title">${title}</h2><p>${state.chatDialog === "new" ? "Choose nobody for a personal room, one person for a direct room, or several people for a group." : "The new room starts with no messages."}</p>${state.chatError ? `<p role="alert">${escapeHtml(state.chatError)}</p>` : ""}<form id="chat-form">${state.chatDialog === "new" ? '<div class="field"><label for="chat-title">Chat title</label><input class="input" id="chat-title" name="title" maxlength="200" required></div>' : ""}<fieldset class="field"><legend>Participants</legend><div class="choices">${state.contacts.map((contact) => `<label class="choice"><input type="checkbox" name="chat-member" value="${escapeHtml(contact.id)}" ${existing.has(contact.id) ? "checked disabled" : picked.has(contact.id) ? "checked" : ""}><span class="choice-copy"><strong>${escapeHtml(contact.name)}</strong><small>${existing.has(contact.id) ? "Already in this room" : contact.remote ? "Paired contact" : "Local contact"}</small></span></label>`).join("")}</div></fieldset>${state.chatDialog === "linked" ? `<div class="carry-help-slot">${carryHelp(room)}</div>` + carryBriefChoice(room) : ""}<div class="button-row"><button class="button" type="submit">${state.chatDialog === "new" ? "Create chat" : "Start a new linked chat"}</button><button class="button secondary" type="button" data-action="close-dialog">Cancel</button></div></form></div></dialog>`;
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

function deliveryDescription(delivery) {
  const withdrawal = delivery.action.endsWith("withdraw");
  const person = delivery.contact_name || contactName(delivery.contact_id);
  if (delivery.status === "withdrawn") return "Canceled obsolete queued content; this is not a remote acknowledgement";
  if (withdrawal) {
    if (delivery.status === "delivered") return `Remote withdrawal acknowledged by ${person}'s peer. Existing copies may remain.`;
    return `Access stopped here; waiting for ${person}'s peer to acknowledge withdrawal${delivery.status === "failed" ? " — delivery failed; remote acknowledgement unknown" : ""}.`;
  }
  return `${deliveryText(delivery.status)}${delivery.status === "failed" ? " — remote acknowledgement unknown" : ""}`;
}

function deliveryOperation(action) {
  return { "layer.release": "Share update", "layer.withdraw": "Remove update access", "room.roster": "Share chat", "room.message": "Send message", "room.reply": "Send reply", "room.withdraw": "Remove chat access" }[action] || "Peer delivery";
}

function deliveryCard(delivery) {
  return `<div class="item"><div class="item-main"><strong>${escapeHtml(delivery.resource_title || "Shared item")} → ${escapeHtml(delivery.contact_name || contactName(delivery.contact_id))}</strong><span>${escapeHtml(deliveryOperation(delivery.action))} · ${escapeHtml(deliveryDescription(delivery))}</span><details><summary>Connection details</summary><p class="fingerprint meta">Item ${escapeHtml(delivery.resource_id)}<br>Peer ${escapeHtml(delivery.peer_id)}<br>Revision ${escapeHtml(delivery.revision)} · ${escapeHtml(delivery.attempts)} attempts</p></details></div>${delivery.status === "failed" ? `<button class="button secondary" data-action="retry-delivery" data-id="${escapeHtml(delivery.id)}">Retry</button>` : ""}</div>`;
}

function resourceDelivery(id) {
  const rows = (state.sync.deliveries || []).filter((row) => row.resource_id === id);
  if (!rows.length) return "";
  const latest = new Map();
  for (const row of rows) latest.set(row.contact_id, row);
  return `<section class="section"><div class="section-head"><h3>Remote delivery</h3><button class="button secondary" data-action="sync">Check delivery now</button></div>${[...latest.values()].map(deliveryCard).join("")}</section>`;
}

function accountSupport() {
  if (!state.me.is_admin) return "";
  return `<section class="section"><div class="section-head"><div><h2>Account support</h2><p class="meta">Account support does not open private chats or drafts.</p></div><button class="button secondary" data-action="invite">Create invitation</button></div>${state.invitation ? `<div class="notice"><strong>One-use invitation</strong><p>Share this token through a channel you trust. It expires ${formatDate(state.invitation.expires)}.</p><div class="code-box">${escapeHtml(state.invitation.token)}</div></div>` : ""}<div class="item-list">${state.accounts.map((account) => `<div class="item"><span class="item-main"><strong>${escapeHtml(account.name)}</strong><span>@${escapeHtml(account.username)} · joined ${formatDate(account.created)}</span></span><span class="badge">${roleLabel(roleOf(account))}</span></div>`).join("")}</div></section>`;
}

function accessRequests() {
  if (!state.me.is_admin) return "";
  const pending = state.accessRequests.filter(request => request.status === "pending");
  const body = pending.length ? pending.map(request => `<div class="item"><span class="item-main"><strong>${escapeHtml(request.name)}</strong><span>${escapeHtml(request.contact)} · asked ${formatDate(request.created)}</span>${request.note ? `<span>${escapeHtml(request.note)}</span>` : ""}</span><div class="button-row"><button class="button" data-action="approve-access" data-id="${escapeHtml(request.id)}">Approve</button><button class="button secondary" data-action="deny-access" data-id="${escapeHtml(request.id)}">Deny</button></div></div>`).join("") : `<p class="meta">No one is waiting for access.</p>`;
  return `<section class="section"><div class="section-head"><div><h2>Access requests</h2><p class="meta">Approving creates a one-use invitation that only the requester can collect. They become a participant.</p></div></div><div class="item-list">${body}</div></section>`;
}

function shipsSection() {
  const ships = state.ships || [];
  const rows = ships.length ? ships.map(ship => `<div class="item"><span class="item-main"><strong>${escapeHtml(ship.name)}</strong><span>@${escapeHtml(ship.username)} · ${ship.owner_name ? `${escapeHtml(ship.owner_name)}’s ship` : "Station ship"}${ship.machine ? ` · ${escapeHtml(ship.machine)}` : ""} · ${ship.last_used ? `last seen ${formatDate(ship.last_used)}` : "not used yet"}</span></span>${ship.active_keys ? `<button class="button danger secondary" data-action="revoke-ship" data-id="${escapeHtml(ship.id)}">Revoke key</button>` : `<span class="badge">Key revoked</span>`}</div>`).join("") : `<p class="meta">No ships docked yet. Run <code>make dock</code> on a machine to dock its agent.</p>`;
  return `<section class="section"><div class="section-head"><div><h2>Ships</h2><p class="meta">Each ship is one machine’s agent. A ship reads and posts only in rooms it was added to.</p></div></div><div class="item-list">${rows}</div></section>`;
}

function dockingDialog() {
  const docking = state.docking;
  if (!docking) return "";
  return `<dialog aria-labelledby="docking-title"><div class="dialog-content"><h2 id="docking-title">${docking.redock ? "Re-dock" : "Dock"} ${escapeHtml(docking.ship_name)}</h2><p>From <strong>${escapeHtml(docking.machine)}</strong>. Confirm only if you just ran <code>make dock</code> there.</p><p>${docking.redock ? "This replaces the ship’s old key." : "The ship will be yours. It reads and posts only in rooms a room owner adds it to."}</p><div class="button-row"><button class="button" data-action="confirm-docking">Confirm docking</button><button class="button secondary" data-action="cancel-docking">Cancel</button></div></div></dialog>`;
}

function shipBanner(room) {
  const ships = (room.members || []).filter(member => member.kind === "ship");
  return ships.length ? `<div class="notice ship-banner"><strong>Ships in this room send its text to Claude.</strong><p>Aboard: ${ships.map(ship => escapeHtml(ship.name)).join(", ")}. Keep patient and participant details out of this room.</p></div>` : "";
}

async function loadDocking() {
  if (!state.dockCode || state.docking) return;
  try {
    state.docking = await api(`/api/dockings/code/${pathPart(state.dockCode)}`);
  } catch (error) {
    state.dockCode = null;
    if (error.status === 401) throw error;
    setFlash(error.message, true);
  }
}

function roleLabel(role) {
  return { participant: 'Participant', admin: 'Admin', super_admin: 'Super admin' }[role] || 'Not assigned';
}

function roleOf(account) {
  return account.is_super_admin ? 'super_admin' : account.is_admin ? 'admin' : 'participant';
}

function accountRights() {
  if (!state.me.is_super_admin) return '';
  const names = new Map(state.accounts.map(account => [account.id, account.name]));
  return `<section class="section card"><h2>Account rights</h2><p>Participants manage their own work. Admins invite people and pair peers. Super admins also grant and revoke administrative roles. These roles do not open private chats, drafts, or records.</p>${state.accounts.map(account => `<form class="item account-role-form" data-id="${escapeHtml(account.id)}"><span class="item-main"><strong>${escapeHtml(account.name)}</strong><span>${escapeHtml(account.username)} · ${roleLabel(roleOf(account))}${account.activation_pending ? ' · Awaiting activation' : ''}</span></span><div class="field"><label for="role-${escapeHtml(account.id)}">Role for ${escapeHtml(account.name)}</label><select id="role-${escapeHtml(account.id)}" name="role" ${account.activation_pending ? 'disabled' : ''}>${['participant', 'admin', 'super_admin'].map(role => `<option value="${role}" ${role === roleOf(account) ? 'selected' : ''}>${roleLabel(role)}</option>`).join('')}</select></div><button class="button secondary" type="submit" ${account.activation_pending ? 'disabled' : ''}>Review rights for ${escapeHtml(account.name)}</button></form>`).join('')}<details><summary>Recent rights changes</summary><ul>${state.roleChanges.map(change => `<li>${escapeHtml(names.get(change.actor_id) || 'Account')} changed ${escapeHtml(names.get(change.user_id) || 'Account')} from ${roleLabel(change.old_role)} to ${roleLabel(change.new_role)} · ${formatDate(change.created)}</li>`).join('') || '<li>No rights changes recorded.</li>'}</ul></details></section>`;
}

function accountRoleDialog() {
  const preview = state.accountRolePreview;
  if (!preview) return '';
  return `<dialog aria-labelledby="account-rights-title"><div class="dialog-content"><h2 id="account-rights-title">Review account rights</h2><p><strong>${escapeHtml(preview.name)}</strong> · ${escapeHtml(preview.username)}</p><p>${roleLabel(preview.oldRole)} → <strong>${roleLabel(preview.role)}</strong></p><p>${preview.role === 'super_admin' ? 'This person will be able to grant and revoke admin and super-admin rights, invite people, and pair peers.' : preview.role === 'admin' ? 'This person will be able to invite people and pair peers.' : 'This person will lose administrative rights. Unused invitations they created will be revoked.'}</p><p>Private chats, drafts, and records keep their existing sharing permissions.</p><div class="button-row"><button class="button" data-action="confirm-account-role">Grant these rights</button><button class="button secondary" data-action="close-dialog">Cancel</button></div></div></dialog>`;
}

function connectionsView() {
  const statuses = state.sync.deliveries || [];
  return `<header class="page-head"><div><p class="eyebrow">Explicit peer exchange</p><h1>Connections</h1><p class="lede">Review a peer’s address, participant, and certificate fingerprint before pairing. Pairing alone shares nothing.</p></div><div class="button-row"><button class="button secondary" data-action="show-card">Show my peer card</button><button class="button" data-action="sync">Check delivery now</button></div></header>
    <section class="grid cols-2"><div class="card"><h2>Paired peers</h2>${state.me.is_admin ? (state.connections.length ? state.connections.map(connectionGroup).join("") : empty("No peers paired", "Import a card and compare its fingerprint before connecting.")) : `<p class="meta">The local account owner manages peer pairing. You control what you share with known contacts.</p>`}</div>
    <div class="card"><h2>Delivery</h2><p class="meta">Background synchronization is ${state.sync.enabled ? "on" : "off"}. Local writing still works while another peer is unavailable.</p><div class="item-list">${statuses.length ? statuses.map(deliveryCard).join("") : empty("No delivery activity", "Pending, delivered, failed, and canceled work will remain distinct here.")}</div></div></section>
    ${state.me.is_admin ? `<section class="section card"><h2>Pair another peer</h2><p>Paste the complete public card, preview it, and compare the fingerprint outside Superyak before confirming.</p><form id="pair-preview-form"><div class="field"><label for="peer-card">Peer card</label><textarea class="textarea code-box" id="peer-card" name="card" placeholder="Paste peer card JSON"></textarea></div><button class="button secondary" type="submit">Preview peer card</button></form>${state.pairPreview ? `<div class="active-panel"><h3>${escapeHtml(state.pairPreview.participant.name)}</h3><p>${escapeHtml(state.pairPreview.endpoint)}</p><p class="fingerprint"><strong>Fingerprint:</strong> ${escapeHtml(state.pairPreview.fingerprint)}</p><button class="button" data-action="confirm-pair">Fingerprint matches — pair this peer</button></div>` : ""}</section>` : ""}
    ${shipsSection()}${accessRequests()}${accountSupport()}${accountRights()}`;
}

function profileDialog() {
  if (!state.profileDialog || !state.me) return "";
  const corrections = state.corrections.length
    ? `<div class="history"><h3>Name correction history</h3>${state.corrections.slice().reverse().map((item) => `<div class="correction"><strong>${escapeHtml(item.old_name)} → ${escapeHtml(item.new_name)}</strong><span>Changed by ${item.actor_id === state.me.id ? `you (${escapeHtml(item.actor_id)})` : escapeHtml(item.actor_id)} · ${formatDate(item.created)}</span></div>`).join("")}</div>`
    : `<p class="meta">No name corrections recorded for this account.</p>`;
  return `<dialog aria-labelledby="account-title"><div class="dialog-body"><p class="eyebrow">Local account</p><h2 id="account-title">Your account</h2><p>A name correction keeps the same private account and sharing permissions. Earlier releases remain attributed to this account.</p>${state.logoutError ? `<div class="notice error" role="alert">Sign-out could not be completed. This account is still signed in on this device.</div>` : ""}<form id="profile-form"><div class="field"><label for="display-name">Display name</label><input class="input" id="display-name" name="name" maxlength="200" value="${escapeHtml(state.me.name)}" required></div><div class="button-row"><button class="button" type="submit">Save name correction</button><button class="button secondary" type="button" data-action="logout">${state.logoutError ? "Retry sign out" : "Sign out"}</button><button class="button ghost" type="button" data-action="close-dialog">Close</button></div></form>${demoChoices()}${corrections}</div></dialog>`;
}

function reauthDialog() {
  if (!state.reauth || !state.me) return "";
  return `<dialog aria-labelledby="reauth-title"><div class="dialog-body"><p class="eyebrow">Session ended</p><h2 id="reauth-title">Sign in again to keep working</h2><p>Your unsaved layer text is still in this editor. Sign in to save it to your peer.</p>${state.reauthError ? `<div class="notice error" role="alert">${escapeHtml(state.reauthError)}</div>` : ""}<form id="reauth-form"><div class="field"><label for="reauth-username">Username</label><input class="input" id="reauth-username" name="username" value="${escapeHtml(state.me.username)}" readonly></div>${isDemoAccount(state.me.username) ? `<p>Continue with this local demo account. No password needed.</p>` : `<div class="field"><label for="reauth-password">Password</label><input class="input" id="reauth-password" name="password" type="password" autocomplete="current-password" required></div>`}<div class="button-row"><button class="button" type="submit">Sign in again</button><button class="button secondary" type="button" data-action="close-reauth">Keep editing offline</button></div></form></div></dialog>`;
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
      content = error.status === 404 ? `<article class="public-article"><p class="eyebrow">Superyak public view</p><h1>This page is not shared</h1><p>The owner may have turned off the public link or stopped sharing this release.</p></article>` : `<article class="public-article"><h1>This page is unavailable</h1><p>The peer could not be reached or could not load this page. Try again later; its sharing status is unknown.</p></article>`;
    }
  }
  app.innerHTML = `<main class="public-page" id="main-content"><div class="public-wrap"><header class="public-header">${brand()}<a class="text-button" href="/">Sign in</a></header>${content}</div></main>`;
}

let dataLoadSequence = 0;
async function loadData() {
  const user = state.me, identity = identityKey(user), sequence = ++dataLoadSequence;
  const valid = () => !!user && identityKey(state.me) === identity && sequence === dataLoadSequence;
  if (!user) return false;
  try {
    const [home, contacts, files, sync, corrections] = await Promise.all([
      api("/api/home"), api("/api/contacts"), api("/api/files"), api("/api/sync"), api("/api/me/corrections")
    ]);
    if (!valid()) return false;
    if (home.user.id !== user.id) throw new ApiError("This browser's account changed. Sign in again to continue.", 401);
    const [assistant, sources, activePairs, accounts, connections, roleChanges, accessRequestList, ships] = await Promise.all([
      api("/api/assistant").catch(() => ({ enabled: false, message: "Assistant status unavailable. Manual writing remains available." })),
      api("/api/sources").catch(() => null),
      Promise.all(home.layers.filter(layer => layer.active_revision).map(async layer => {
        try { return { id: layer.id, active: await api(`/api/shared/layers/${pathPart(layer.id)}`) }; }
        catch (error) { if (error.status === 401) throw error; return { id: layer.id, error }; }
      })),
      home.user.is_admin ? api("/api/accounts") : [],
      home.user.is_admin ? api("/api/connections") : [],
      home.user.is_super_admin ? api("/api/account-role-changes") : [],
      home.user.is_admin ? api("/api/access-requests") : [],
      api("/api/ships"),
    ]);
    if (!valid()) return false;
    const previousActive = state.activeLayers;
    const activeLayers = Object.fromEntries(activePairs.flatMap(result => {
      const active = result.active || previousActive[result.id];
      return active ? [[result.id, active]] : [];
    }));
    const activeLayerErrors = Object.fromEntries(activePairs.flatMap(result => result.error ? [[result.id, result.error.message]] : []));
    Object.assign(state, { me: { ...user, ...home.user }, home, contacts, files, sync, corrections, assistant, sources, activeLayers, activeLayerErrors, accounts, accessRequests: accessRequestList, connections, roleChanges, ships });
    return true;
  } catch (error) { if (!valid()) return false; throw error; }
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
  if (route === "chats" && (id || state.selectedChatId) && !state.home.chats.some((item) => item.id === (id || state.selectedChatId))) {
    try { await loadData(); } catch (_) { /* the list below says so if the room is still unknown */ }  // a room made after this page loaded
  }
  if (route === "chats") {
    state.selectedChatId = id || state.selectedChatId || null;
    if (state.selectedChatId && state.home.chats.some((item) => item.id === state.selectedChatId)) {
      try { state.room = await api(`/api/chats/${pathPart(state.selectedChatId)}`); await loadBoard(state.room); }
      catch (_) { state.room = null; }
    } else {
      state.room = null;
    }
  }
  if (route === "grants") { try { await loadData(); } catch (_) { /* the view below reads what it can */ } await loadGrants(); }
  if (route === "board") { try { await loadData(); } catch (_) { /* the view below reads what it can */ } const who = identityKey(state.me); try { const view = await api("/api/board"); if (identityKey(state.me) === who) state.boardView = view; } catch (_) { if (identityKey(state.me) === who) state.boardView = null; } }
  if (route === "shared") {
    const identity = identityKey(state.me), hash = location.hash;
    state.selectedSharedId = id || state.selectedSharedId;
    // A fresh navigation rechecks access rather than displaying a cached release.
    const releases = await api("/api/shared/layers");
    if (identityKey(state.me) !== identity || location.hash !== hash) return;
    state.home.shared_layers = releases;
    if (!releases.some(layer => layer.id === state.selectedSharedId)) state.selectedSharedId = null;
  }
  if (route === "research") await Research.load(id);
  if (route === "spaces") await Dashboard.loadSpace(id);
  if (routeParts().route === route && routeParts().id === id) state.currentSpaceId = route === "spaces" && id ? id : "all";
}

let dialogReturn = null;
function closeDialogs() {
  state.accountRolePreview = null;
  state.docking = null; state.dockCode = null;
  state.preview = false; state.confirmWithdraw = false; state.chatDialog = null; state.chatPicked = null; state.chatError = null; state.profileDialog = false; state.spaceDialog = false; state.reauth = false; Research.close(); Dashboard.close();
  render();
}

function render() {
  if (!state.me || !state.home) return;
  const route = routeParts().route;
  const view = { home: homeView, chats: chatsView, board: boardView, grants: grantsView, layers: layersView, shared: sharedView, spaces: Dashboard.spacesView, research: Research.view, search: Dashboard.searchView, connections: connectionsView }[route]();
  const focused = document.activeElement;
  const hadDialog = !!app.querySelector("dialog[open]");
  if (!hadDialog && focused?.dataset.action) dialogReturn = `[data-action="${CSS.escape(focused.dataset.action)}"]`;
  const focusSelector = focused?.id ? `#${CSS.escape(focused.id)}` : focused?.dataset.action ? `[data-action="${CSS.escape(focused.dataset.action)}"]` : null;
  app.innerHTML = layout(view);
  const dialogs = app.querySelectorAll("dialog");
  for (const dialog of dialogs) {
    dialog.showModal();
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const controls = [...dialog.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')].filter((node) => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); closeDialogs(); });
  }
  if (hadDialog && !dialogs.length && dialogReturn) app.querySelector(dialogReturn)?.focus();
  else if (hadDialog && dialogs.length && focusSelector) app.querySelector(focusSelector)?.focus();
  document.title = `${{ home: "Home", chats: "Chats", board: "Board", grants: "Grants", layers: "My sharing layers", shared: "Shared spaces", spaces: "Circles & projects", research: "Research & data", search: "Search", connections: "Connections" }[route]} · Superyak`;
}

async function refresh(message = null) {
  try {
    if (!await loadData()) return;
    await loadRoute();
    await loadDocking();
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
  const checked = (name) => [...form.querySelectorAll(`[name="${name}"]:checked`)].map((input) => input.value);
  const base = { title: form.elements.title.value, body: form.elements.body.value };
  if (form.elements.kind.value === "instructions") {
    return { ...base, kind: "instructions", audience_users: checked("audience-ship"), audience_spaces: [], public: false, attachment_ids: [] };
  }
  return { ...base, kind: "note", audience_users: checked("audience-user"), audience_spaces: checked("audience-space"), public: Boolean(form.elements.public?.checked), attachment_ids: checked("attachment") };
}

// While a layer is opening, the old editor is still on screen but the selection is already the new layer. A form acts
// only for the layer it shows (its data-layer-id), and only once that is the selected one.
function editorSwitching(form = document.querySelector("#layer-form")) {
  return Boolean(form) && form.dataset.layerId !== state.selectedLayerId;
}

function refuseWhileSwitching(form = document.querySelector("#layer-form")) {
  if (!editorSwitching(form)) return false;
  announce("The editor is switching layers; try again.");  // no render: the old editor keeps its text until the new one opens
  return true;
}

function rememberLayerForm(form = document.querySelector("#layer-form")) {
  if (!form) return null;
  const layer = state.home.layers.find((item) => item.id === form.dataset.layerId);
  if (!layer) return null;
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
  if (refuseWhileSwitching(form)) return;
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
  if (refuseWhileSwitching()) return;
  const initiatingLayer = selectedLayer();
  const layerId = initiatingLayer.id;
  const initiatingIdentity = state.editorIdentity;
  rememberLayerForm();
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
    if (state.editorIdentity !== initiatingIdentity) return;
    state.files.push(uploaded);
    const savedLayer = state.home.layers.find((layer) => layer.id === layerId);
    if (!savedLayer) return;
    const current = state.layerEdits[layerId];
    const latestValues = current?.values || {
      title: savedLayer.title,
      body: savedLayer.body,
      audience_users: savedLayer.audience_users || [],
      audience_spaces: savedLayer.audience_spaces || [],
      public: savedLayer.public,
      attachment_ids: savedLayer.attachment_ids || [],
    };
    state.layerEdits[layerId] = {
      values: {
        ...latestValues,
        attachment_ids: [...new Set([...(latestValues.attachment_ids || []), uploaded.id])],
      },
      dirty: true,
      conflict: current?.conflict || false,
      generation: (current?.generation || 0) + 1,
    };
    if (state.selectedLayerId === layerId) {
      render();
      document.querySelector("#upload-status").textContent = `${uploaded.name} uploaded. Save the draft to keep it selected.`;
    }
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
  if (refuseWhileSwitching()) return;
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
  const layer = state.preview;
  if (!layer) return;
  try {
    await api(`/api/layers/${pathPart(layer.id)}/activate`, { method: "POST", json: { version: layer.version, space_versions: layer.space_versions } });
    state.preview = false;
    await refresh(`Version ${layer.version} is now active`);
  } catch (error) {
    state.preview = false;
    setFlash(error.status === 409 ? "The draft or space membership changed before activation. Review the saved version again." : error.message, true);
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
    await refresh("Sharing is off on this peer. Remote withdrawal requires acknowledgement; check delivery below.");
  } catch (error) {
    setFlash(`${error.message} The current release may still be active.`, true);
    render();
  }
}

async function openChat(id) {
  state.selectedChatId = id;
  state.room = await api(`/api/chats/${pathPart(id)}`);
  await loadBoard(state.room);
  location.hash = `chats/${pathPart(id)}`;
  state.flash = null;
  state.transitionNote = null;
  state.briefHistory = null;
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
      const carry = form.querySelector('[name="carry-brief"]:checked');
      room = await api(`/api/chats/${pathPart(state.room.id)}/participants`, { method: "POST", json: { member_ids: members, carry_brief: carry ? Number(carry.value) : null } });
      state.transitionNote = "New room · earlier messages stay in the original chat";
    }
    state.chatDialog = null; state.chatPicked = null; state.chatError = null;
    await loadData();
    state.selectedChatId = room.id;
    state.room = await api(`/api/chats/${pathPart(room.id)}`);
    await loadBoard(state.room);
    history.replaceState(null, "", `#chats/${pathPart(room.id)}`);
    render();
  } catch (error) {
    if (error.status === 409 && state.chatDialog === "linked" && state.room && !error.message.startsWith("The room brief changed")) {
      state.chatPicked = members;  // a room replaced since this page loaded: the station's own words, in the dialog
      state.chatError = error.message;
      announce(state.chatError);
      render();
      return;
    }
    if (error.status === 409 && state.chatDialog === "linked" && state.room) {
      state.chatPicked = members;
      state.chatError = "The room brief changed since you opened this. The newer brief is shown below; tick the box again to carry it.";
      try {
        state.room = await api(`/api/chats/${pathPart(state.room.id)}`);
      } catch (_) {
        state.chatError = "The room brief changed since you opened this. Close this and open the room again to see the newer brief.";
      }
      announce(state.chatError);
      render();
      document.querySelector('dialog [name="carry-brief"]')?.focus();  // the box to tick again, inside the dialog
      return;
    }
    setFlash(error.message, true);
    render();
  }
}
async function saveBrief(form) {
  const room = state.room, edit = state.briefEdit;
  // One save at a time: a second submit while saving would send a stale revision and read as a false conflict.
  if (!room || !edit || edit.roomId !== room.id || edit.saving) return;
  const body = form.elements.body.value;
  Object.assign(edit, { body, saving: true, status: "Saving…", error: false });
  form.querySelector('button[type="submit"]').disabled = true;
  const status = form.querySelector("#brief-status");
  status.className = "inline-message";
  status.textContent = "Saving…";
  try {
    // The revision is the one this editor opened, never a newer one: a stale tab gets 409 and overwrites nothing.
    await api(`/api/chats/${pathPart(room.id)}/brief`, { method: "PUT", json: { body, revision: edit.revision } });
  } catch (error) {
    // The station's own message: the editor has no maxlength, so "A brief is at most 4,000 characters" arrives here.
    let message = error.status === 0 ? "Connection lost. Your brief is still here." : `${error.message.replace(/\.?$/, ".")} Your brief is still here.`;
    if (error.status === 409) {
      message = "A newer brief was saved while you were editing. It is shown above, and your text is still here. Save again to replace it.";
      try {
        const latest = await api(`/api/chats/${pathPart(room.id)}`);
        if (state.room?.id === room.id) state.room = latest;
        edit.revision = latest.brief_revision;
      } catch (_) {
        message = "A newer brief was saved while you were editing. Your text is still here; reload the room to see the newer brief.";
      }
    }
    Object.assign(edit, { status: message, error: true, saving: false });
    announce(message);
    render();
    document.querySelector("#brief-body")?.focus();  // render() drops focus when no dialog is open; the error is about this box
    return;
  }
  if (state.briefEdit === edit) state.briefEdit = null;  // only this editor closes: one opened since then stays
  try {
    const latest = await api(`/api/chats/${pathPart(room.id)}`);
    if (state.room?.id === room.id) state.room = latest;
  } catch (_) { /* the save stands; the next refresh shows it */ }
  if (state.briefHistory?.roomId === room.id) await openBriefHistory(room);  // the saved revision joins the list
  setFlash(body.trim() ? "Room brief saved." : "Room brief removed.");
  render();
}

async function openBriefHistory(room) {
  // Keeps the rows already shown while it reloads, so a save doesn't flash "Loading".
  const history = { roomId: room.id, items: state.briefHistory?.roomId === room.id ? state.briefHistory.items : null, error: null };
  state.briefHistory = history;
  render();
  try { history.items = await api(`/api/chats/${pathPart(room.id)}/brief/revisions`); }
  catch (error) { history.error = error.message; }
  if (state.briefHistory === history) render();
}

// "Use this text" (S5): the revision's body becomes the editor's value, never HTML, at the room's current revision,
// so Save is the ordinary save and makes a new revision by the owner. The editor warns when the text is a ship's (S4).
function useBriefRevision(room, revision, confirmed = false) {
  const item = state.briefHistory?.roomId === room.id ? state.briefHistory.items?.find((r) => r.revision === revision) : null;
  if (!item) return;
  const open = state.briefEdit?.roomId === room.id ? state.briefEdit : null;
  if (open && open.body !== open.opened && !confirmed) {  // unsaved typing: ask before it goes
    state.briefHistory.ask = revision;
    render();
    document.querySelector('.board-ask [data-action="brief-use-cancel"]')?.focus();  // the safe choice, as the board's Drop
    return;
  }
  state.briefHistory.ask = null;
  state.briefEdit = { roomId: room.id, revision: room.brief_revision ?? 0, body: item.body, opened: item.body, status: "", error: false,
                      shipAuthor: briefAuthorClass(room, item) === "ship" ? item.author_name : null };
  render();
  const box = document.querySelector("#brief-body");
  if (box) { box.value = item.body; box.focus(); }
}

async function removeParticipant(id) {
  const room = state.room;
  const name = participantName(id);
  let updated;
  try {
    updated = await api(`/api/chats/${pathPart(room.id)}/participants/${pathPart(id)}`, { method: "DELETE", json: {} });
  } catch (error) {
    setFlash(`${error.message} Room access was not changed.`, true);
    render();
    return;
  }
  if (state.room?.id === room.id) {
    state.room = { ...state.room, ...updated, messages: state.room.messages || [] };
    state.transitionNote = `${name} no longer has access on this peer; remote removal requires acknowledgement`;
    render();
  }
  try {
    await loadData();
    if (state.room?.id === room.id) state.room = await api(`/api/chats/${pathPart(room.id)}`);
    render();
  } catch (error) {
    if (error.status === 401) {
      showLogin(`${name} no longer has access on this peer; remote removal requires acknowledgement. Sign in again to continue.`);
      return;
    }
    setFlash(`${name} no longer has access on this peer; remote removal requires acknowledgement. Latest room status is unavailable.`);
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
  if (currentDraft.clientId === draft.clientId && currentDraft.body === body) {
    if (textarea.isConnected && textarea.value === body) textarea.value = "";
    sessionStorage.removeItem(draftKey(room.id));
    if (status.isConnected) status.textContent = "Message saved. Refreshing room…";
  }
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
    clearAccountAdministration();
    clearChatDrafts();
    state.layerEdits = {};
    state.assistance = {};
    state.sources = [];
    Research.reset(); Dashboard.reset();
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

function isDemoAccount(username) {
  return state.demoAccounts.some((account) => account.username === username);
}

async function demoLogin(username) {
  await api("/api/local-demo/login", { method: "POST", json: { username } });
  return api("/api/me");
}

async function bootstrap() {
  if (location.hash.startsWith('#dock?')) {
    state.dockCode = new URLSearchParams(location.hash.slice('#dock?'.length)).get('code') || null;
    history.replaceState(null, '', location.pathname + location.search);
  }
  if (location.hash.startsWith('#activate?')) {
    const fields = new URLSearchParams(location.hash.slice('#activate?'.length));
    state.activation = Object.fromEntries(['token', 'username', 'name'].map(key => [key, fields.get(key) || '']));
    history.replaceState(null, '', location.pathname + location.search);
    showLogin();
    const form = document.querySelector('#redeem-form');
    for (const key of ['token', 'username', 'name']) form.elements[key].value = state.activation[key];
    document.querySelector('.invitation-redeem').open = true;
    return;
  }
  if (location.pathname === "/public/" || location.pathname.startsWith("/public/view")) {
    await renderPublic();
    return;
  }
  try {
    try {
      state.demoAccounts = (await api("/api/local-demo")).accounts;
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    try {
      state.me = await api("/api/me");
    } catch (error) {
      if (error.status !== 401 || !isDemoAccount("patient")) throw error;
      state.me = await demoLogin("patient");
    }
    bindEditorIdentity(state.me);
    await refresh();
  } catch (error) {
    showLogin(error.status === 401 ? "" : error.message);
  }
}

document.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.matches('.account-role-form')) {
    const account = state.accounts.find(row => row.id === form.dataset.id);
    if (!state.me?.is_super_admin || !account) return;
    state.accountRolePreview = { id: account.id, name: account.name, username: account.username, oldRole: roleOf(account), role: form.elements.role.value, expected_version: account.role_version };
    render();
    return;
  }
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
      state.activation = null;
      showLogin("Account created. Sign in to open your home.");
    } catch (error) {
      showLogin(error.message);
      const details = document.querySelector(".invitation-redeem");
      if (details) details.open = true;
      if (state.activation) for (const key of ['token', 'username', 'name']) document.querySelector('#redeem-form').elements[key].value = state.activation[key];
    }
    return;
  }
  if (form.id === "reauth-form") {
    const expectedId = state.me.id;
    try {
      let signedIn;
      if (isDemoAccount(state.me.username)) {
        signedIn = await demoLogin(state.me.username);
      } else {
        await api("/api/login", { method: "POST", json: { username: state.me.username, password: form.elements.password.value } });
        signedIn = await api("/api/me");
      }
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
  await Research.submit(form);
  await Dashboard.submit(form);
  if (form.id === "layer-form") await saveLayer(form);
  if (form.id === "space-form") await createSpace(form);
  if (form.id === "chat-form") await createChat(form);
  if (form.id === "brief-form") await saveBrief(form);
  if (form.id === "board-post-form") await postBoardItem(form);
  if (form.id === "grant-form") await makeGrant(form);
  if (form.id === "board-done-form") await boardWrite("/board/done", { key: form.dataset.key, outcome: form.elements.outcome.value }, "Marked done.", { focusKey: form.dataset.key });
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
  if (target.closest("section.editor") && refuseWhileSwitching()) return;
  if (action.startsWith("research-")) { await Research.action(target); return; }
  if (action.startsWith("dashboard-")) { await Dashboard.action(target); return; }
  if (action === "demo-login") {
    target.disabled = true;
    if (state.me) {
      await logout();
      if (state.me) return;
    }
    try {
      await demoLogin(target.dataset.username);
      // A new document clears all previous account views and pending callbacks.
      location.replace("/");
    } catch (error) {
      showLogin(error.message);
    }
    return;
  }
  if (action === "new-layer") {
    try {
      const layer = await api("/api/layers", { method: "POST", json: {} });
      state.home.layers.push(layer);
      await openLayer(layer.id);
    } catch (error) { setFlash(error.message, true); render(); }
  }
  if (action === "open-layer") await openLayer(target.dataset.id);
  if (action === "preview") {
    if (refuseWhileSwitching()) return;
    if (currentLayerEdit()?.dirty) {
      const status = document.querySelector("#layer-status");
      status.className = "inline-message error";
      status.textContent = "Save this private draft before previewing a version.";
    } else {
      try { state.preview = await api(`/api/layers/${pathPart(selectedLayer().id)}/preview`); render(); }
      catch (error) { setFlash(`Preview unavailable. No selection was activated. ${error.message}`, true); render(); }
    }
  }
  if (action === "ask-assistant") await askAssistant();
  if (action === "apply-suggestion") applySuggestion();
  if (action === "export-draft") await exportSelection("draft");
  if (action === "export-active") await exportSelection("active");
  if (action === "export-source") {
    try { downloadJSON(await api("/api/interchange/export", { method: "POST", json: { source_ids: [target.dataset.id] } })); }
    catch (error) { setFlash(error.message, true); render(); }
  }
  if (action === "activate") await activateLayer();
  if (action === "public-off") await publicOff();
  if (action === "revoke-route") await revokeRoute(target.dataset.routeKind, target.dataset.id);
  if (action === "resolve-conflict") await resolveConflict();
  if (action === "withdraw") { state.confirmWithdraw = true; render(); }
  if (action === "confirm-withdraw") await confirmWithdraw();
  if (action === "close-dialog") closeDialogs();
  if (action === "new-space") { state.spaceDialog = true; state.spaceError = null; render(); }
  if (action === "close-reauth") { state.reauth = false; render(); }
  if (action === "open-shared") { state.selectedSharedId = target.dataset.id; location.hash = `shared/${pathPart(target.dataset.id)}`; render(); }
  if (action === "new-chat") { state.chatDialog = "new"; state.chatPicked = null; state.chatError = null; render(); }
  if (action === "open-chat") await openChat(target.dataset.id);
  if (action === "change-participants") {
    state.chatDialog = "linked"; state.chatPicked = null; state.chatError = null; state.chatBoard = undefined;
    render();  // the dialog opens at once, with the help text only if there is a brief
    const room = state.room, items = await openBoardItems(room);
    if (state.chatDialog !== "linked" || state.room !== room) return;
    state.chatBoard = items;  // fill in the slot only, so nothing the owner already ticked is redrawn
    const slot = document.querySelector("dialog .carry-help-slot");
    if (slot) slot.innerHTML = carryHelp(room);
  }
  if (action.startsWith("board-") && event.detail !== 0 && boardClickBlocked()) return;  // a key press (detail 0) is never a double click
  if (action === "board-done" && state.room) { state.boardAsk = null; state.boardDone = { roomId: state.room.id, key: target.dataset.key, outcome: "" }; render(); document.querySelector("#board-outcome")?.focus(); }
  if ((action === "board-drop" || action === "board-release") && state.room) {
    state.boardDone = null; state.boardAsk = { roomId: state.room.id, key: target.dataset.key, action: action.slice(6) };
    render();
    document.querySelector('.board-ask [data-action="board-cancel"]')?.focus();  // the safe choice, not the one under the pointer
  }
  if (action === "board-cancel") { state.boardDone = null; state.boardAsk = null; render(); focusBoardItem(target.dataset.key); }
  if (action === "board-drop-confirm" && state.boardAsk?.action === "drop" && state.boardAsk.key === target.dataset.key) await boardWrite("/board/drop", { key: target.dataset.key }, "Item dropped.", { focusKey: target.dataset.key });
  if (action === "board-release-confirm" && state.boardAsk?.action === "release" && state.boardAsk.key === target.dataset.key) await boardWrite("/claims/release", { key: target.dataset.key }, "Claim released.", { focusKey: target.dataset.key });
  if (action === "grant-revoke") {
    state.grantAsk = { id: target.dataset.id, reason: "" };
    render();
    document.querySelector('.grant-ask [data-action="grant-cancel"]')?.focus();  // the safe choice
  }
  if (action === "grant-cancel") {
    state.grantAsk = null;
    render();
    document.querySelector(`.grant-item[data-id="${CSS.escape(target.dataset.id)}"] [data-action="grant-revoke"]`)?.focus();
  }
  if (action === "grant-revoke-confirm" && state.grantAsk?.id === target.dataset.id) {
    const grant = (state.grants || []).find((item) => item.id === target.dataset.id);
    await grantWrite(`/api/grants/${pathPart(target.dataset.id)}/revoke`, { reason: state.grantAsk.reason }, () => `Grant ${grant?.short || ""} revoked.`);
    document.querySelector("#grants-given-title")?.focus();
  }
  if (action === "remove-participant") await removeParticipant(target.dataset.id);
  if (action === "edit-brief" && state.room) {
    const brief = state.room.brief;
    // S4: the editor warns when the text it opens with is a ship's; saving would make all of it the owner's.
    state.briefEdit = { roomId: state.room.id, revision: state.room.brief_revision ?? 0, body: brief?.body || "", opened: brief?.body || "", status: "", error: false,
                        shipAuthor: brief && briefAuthorClass(state.room, brief) === "ship" ? brief.author_name : null };
    render();
    document.querySelector("#brief-body")?.focus();
  }
  if (action === "cancel-brief") { state.briefEdit = null; if (state.briefHistory) state.briefHistory.ask = null; render(); }
  if (action === "brief-history" && state.room) await openBriefHistory(state.room);
  if (action === "hide-brief-history") { state.briefHistory = null; render(); }
  if (action === "use-brief-revision" && state.room) useBriefRevision(state.room, Number(target.dataset.revision));
  if (action === "brief-use-confirm" && state.room) useBriefRevision(state.room, Number(target.dataset.revision), true);
  if (action === "brief-use-cancel" && state.briefHistory) { state.briefHistory.ask = null; render(); document.querySelector("#brief-body")?.focus(); }
  if (action === "profile") { state.profileDialog = true; render(); }
  if (action === "logout") await logout();
  if (action === "invite") {
    const identity = identityKey(state.me);
    try {
      const invitation = await api("/api/invitations", { method: "POST", json: {} });
      if (identityKey(state.me) !== identity) return;
      state.invitation = invitation; state.flash = null;
    }
    catch (error) { if (identityKey(state.me) !== identity) return; setFlash(error.message, true); }
    render();
  }
  if (action === "cancel-docking") { state.docking = null; state.dockCode = null; render(); return; }
  if (action === "confirm-docking") {
    if (target.disabled || !state.docking) return;
    const identity = identityKey(state.me), docking = state.docking, code = state.dockCode;
    target.disabled = true;
    try {
      const ship = await api(`/api/dockings/${pathPart(docking.id)}/confirm`, { method: "POST", json: { code } });
      if (identityKey(state.me) !== identity) return;
      state.docking = null; state.dockCode = null;
      await refresh(`${ship.name} is docked. Its machine finishes setup on its own.`);
    } catch (error) {
      if (identityKey(state.me) !== identity) return;
      state.docking = null; state.dockCode = null;
      await refresh();
      setFlash(error.message, true);
    }
    return;
  }
  if (action === "revoke-ship") {
    if (target.disabled) return;
    const identity = identityKey(state.me);
    target.disabled = true;
    try {
      await api(`/api/ships/${pathPart(target.dataset.id)}/revoke`, { method: "POST", json: {} });
      if (identityKey(state.me) !== identity) return;
      await refresh("Ship key revoked. That machine must dock again to return.");
    } catch (error) {
      if (identityKey(state.me) !== identity) return;
      await refresh();
      setFlash(error.message, true);
    }
    return;
  }
  if (action === "approve-access" || action === "deny-access") {
    if (target.disabled) return;
    const identity = identityKey(state.me);
    target.disabled = true;
    try {
      await api(`/api/access-requests/${pathPart(target.dataset.id)}/${action === "approve-access" ? "approve" : "deny"}`, { method: "POST", json: {} });
      if (identityKey(state.me) !== identity) return;
      await refresh(action === "approve-access" ? "Access approved. Their invitation is ready for them to collect." : "Access request denied");
    } catch (error) {
      if (identityKey(state.me) !== identity) return;
      await refresh();
      setFlash(error.message, true);
    }
    render();
  }
  if (action === 'confirm-account-role') {
    const preview = state.accountRolePreview;
    if (!preview || target.disabled) return;
    const identity = identityKey(state.me);
    target.disabled = true;
    try {
      await api(`/api/accounts/${pathPart(preview.id)}/role`, { method: 'PATCH', json: { role: preview.role, expected_version: preview.expected_version } });
      if (identityKey(state.me) !== identity) return;
      state.accountRolePreview = null;
      await refresh('Account rights updated');
    } catch (error) {
      if (identityKey(state.me) !== identity) return;
      state.accountRolePreview = null;
      await refresh();
      setFlash(error.message, true);
      render();
    }
  }
  if (action === "show-card") await showCard();
  if (action === "sync") {
    try { await api("/api/sync", { method: "POST", json: {} }); await refresh("Delivery status refreshed"); }
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
  Research.remember(event.target); Dashboard.input(event.target);
  if (event.target.id === "brief-body" && state.briefEdit) {
    state.briefEdit.body = event.target.value;
    const warning = document.querySelector("#brief-form .brief-warning");
    if (warning) warning.hidden = !event.target.value.trim();
  }
  if (event.target.closest("#board-post-form") && state.room) {
    const form = event.target.form;  // kept per room, so a re-render (a message sent, another item closed) keeps it
    state.boardPost = { roomId: state.room.id, key: form.elements.key.value, title: form.elements.title.value, kind: form.elements.kind.value };
  }
  if (event.target.id === "board-outcome" && state.boardDone) state.boardDone.outcome = event.target.value;
  if (event.target.closest("#grant-form")) state.grantForm = readGrantForm(event.target.form);  // kept through a re-render
  if (event.target.id === "grant-reason" && state.grantAsk) state.grantAsk.reason = event.target.value;
  if (event.target.id === "assistant-request" && selectedLayer() && !editorSwitching()) {
    const entry = state.assistance[selectedLayer().id] ||= {};
    entry.text = event.target.value;
  }
  if (event.target.closest("#layer-form")) rememberLayerForm();
  if (event.target.id === "message-body" && state.room) {
    const previous = readChatDraft(state.room.id);
    const next = { body: event.target.value, clientId: previous.body === event.target.value ? previous.clientId : null };
    sessionStorage.setItem(draftKey(state.room.id), JSON.stringify(next));
  }
});

document.addEventListener("change", async (event) => {
  Research.remember(event.target); Dashboard.change(event.target);
  if (event.target.id === "research-upload") { await Research.choose(event.target); return; }
  if (event.target.closest("#layer-form") && event.target.id !== "file-upload") rememberLayerForm();
  if (event.target.id === "layer-kind" && !editorSwitching()) {
    const edit = currentLayerEdit();
    if (edit) { edit.values = { ...edit.values, audience_users: [], audience_spaces: [], public: false, attachment_ids: [] }; render(); }
  }
  if (event.target.id === "space-context") {
    state.currentSpaceId = event.target.value;
    location.hash = state.currentSpaceId === "all" ? "home" : `spaces/${pathPart(state.currentSpaceId)}`;
    render();
  }
  if (event.target.id === "file-upload") await uploadFile(event.target);
  if (event.target.id === "grant-person") {
    // The draft is read from the form, so a room ticked for someone else, gone from the new list, is dropped.
    const form = event.target.form;
    state.grantForm = readGrantForm(form);
    form.querySelector(".grant-rooms").innerHTML = grantRoomChoices(state.grantForm);
  }
});

window.addEventListener("hashchange", async () => {
  if (!state.me) return;
  state.flash = null;
  state.transitionNote = null;
  try { await loadRoute(); render(); }
  catch (error) { setFlash(error.message, true); render(); }
});

Dashboard.applyDisplay();
bootstrap();

// Assistance and source records use the authenticated API and account-bound memory.
function assistantPanel(layer) {
  const entry = state.assistance[layer.id] || {};
  return `<section class="section"><h3>Private drafting assistance</h3><p class="meta">${escapeHtml(state.assistant.message || "Assistant is disabled.")} The selected input is saved version ${layer.version} of this layer. Unsaved edits and attachments are excluded.</p><label for="assistant-request">Assistant request</label><textarea class="textarea" id="assistant-request" maxlength="8000" ${entry.pending ? "disabled" : ""}>${escapeHtml(entry.text || "")}</textarea><button class="button secondary" data-action="ask-assistant" ${!state.assistant.enabled || entry.pending ? "disabled" : ""}>${entry.pending ? "Waiting for Gemma…" : "Ask Gemma privately"}</button>${entry.error ? `<p role="status">${escapeHtml(entry.error)}</p>` : ""}${entry.result ? `<div class="notice"><p>Suggestion from saved version ${entry.result.version}</p><div class="shared-body">${escapeHtml(entry.result.suggestion)}</div><p class="meta">Appending keeps your current words. Review and save privately before choosing any release.</p><button class="button secondary" data-action="apply-suggestion">Append suggestion to my private draft</button></div>` : ""}</section>`;
}

async function askAssistant() {
  if (refuseWhileSwitching()) return;
  const layer = selectedLayer();
  const identity = identityKey(state.me);
  const entry = state.assistance[layer.id] ||= {};
  if (entry.pending) return;
  entry.text = document.querySelector("#assistant-request").value;
  entry.pending = true;
  entry.error = null;
  entry.result = null;
  const text = entry.text;
  render();
  try {
    const result = await api("/api/assistant", { method: "POST", json: { text, layer_id: layer.id, version: layer.version } });
    if (identityKey(state.me) !== identity || state.assistance[layer.id] !== entry) return;
    entry.result = result;
  } catch (error) {
    if (identityKey(state.me) !== identity || state.assistance[layer.id] !== entry) return;
    entry.error = error.message;
    // A generation failure may disable the server adapter; this is a read only check.
    state.assistant = await api("/api/assistant").catch(() => ({ enabled: false }));
  } finally {
    if (identityKey(state.me) === identity && state.assistance[layer.id] === entry) {
      entry.pending = false;
      render();
    }
  }
}

function applySuggestion() {
  if (refuseWhileSwitching()) return;
  const layer = selectedLayer();
  const entry = state.assistance[layer.id];
  if (!entry?.result) return;
  const body = document.querySelector("#layer-body");
  const appended = [body.value, entry.result.suggestion].filter(Boolean).join("\n\n");
  if (appended.length > 100000) {
    entry.error = "The combined draft is too long. Copy the parts you want to keep.";
    render();
    return;
  }
  body.value = appended;
  rememberLayerForm();
  entry.result = null;
  setFlash("Suggestion appended to your unsaved private draft");
  render();
}

function exportPanel(layer) {
  return `<section class="section"><h3>Export a selected source</h3><p class="meta">Downloads contain this saved title, body, audience and attribution. Review before sending the file elsewhere. Unsaved edits and attachments are excluded.</p><div class="button-row"><button class="button secondary" data-action="export-draft">Export saved draft version ${layer.version}</button>${layer.active_revision ? `<button class="button secondary" data-action="export-active">Export selected active release</button><a class="button secondary" href="/api/interchange/adna/${pathPart(layer.id)}" download>Download active source for aDNA</a>` : ""}</div></section>`;
}

function downloadJSON(document) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2) + "\n"], { type: "application/json" }));
  const link = window.document.createElement("a");
  link.href = url;
  link.download = "selected-sources.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function exportSelection(kind) {
  const layer = selectedLayer();
  try {
    const document = await api("/api/interchange/export", { method: "POST", json: { selections: [{ layer_id: layer.id, kind, version: kind === "draft" ? layer.version : layer.active_revision }] } });
    downloadJSON(document);
  } catch (error) { setFlash(error.message, true); render(); }
}

function sourcePanel() {
  return `<section class="section"><h2>Selected source records</h2><p class="meta">Imported records stay private to your account. Their origins, authors and audiences are recorded claims; they do not grant access or establish trust. Source instructions and links are never run.</p><label class="button secondary" for="source-import">Import selected source document</label><input id="source-import" class="sr-only" type="file" accept="application/json,.json"><div class="history">${state.sources === null ? '<p>Source records are temporarily unavailable.</p>' : state.sources.map((source) => `<details><summary>${escapeHtml(source.record.content.title)}</summary><p class="meta">Origin ${escapeHtml(source.record.origin)} · Author ${escapeHtml(source.record.author)}</p><p class="meta">${escapeHtml(source.record.source_locator)} · Revision ${escapeHtml(source.record.revision)}</p><p class="meta">Source hash ${escapeHtml(source.record.source_hash)}</p><p class="meta">Previous ${escapeHtml(source.record.revision_of || "None recorded")} · Corrections ${escapeHtml(source.record.correction_of.join(", ") || "None recorded")}</p><p class="meta">Recorded audience: ${escapeHtml(JSON.stringify(source.record.audience))}. Access here: only you.</p><div class="shared-body">${escapeHtml(source.record.content.body)}</div><button class="button secondary" data-action="export-source" data-id="${escapeHtml(source.id)}">Export this source record</button></details>`).join("")}</div></section>`;
}

document.addEventListener("change", async (event) => {
  if (event.target.id !== "source-import") return;
  const file = event.target.files[0];
  if (!file) return;
  const identity = identityKey(state.me);
  try {
    if (file.size > 512 * 1024) throw new ApiError("Source document exceeds 512 KiB", 400);
    const document = JSON.parse(await file.text());
    if (identityKey(state.me) !== identity) return;
    await api("/api/interchange/import", { method: "POST", json: document });
    if (identityKey(state.me) !== identity) return;
    setFlash("Imported privately. Recorded audiences did not grant access.");
    const sources = await api("/api/sources").catch(() => null);
    if (identityKey(state.me) !== identity) return;
    state.sources = sources;
  } catch (error) {
    if (identityKey(state.me) !== identity) return;
    setFlash(error instanceof SyntaxError ? "Invalid source JSON document" : error.message, true);
  }
  if (identityKey(state.me) === identity) render();
});
