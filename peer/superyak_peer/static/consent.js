"use strict";
// The remote connector's sign-in and consent page (connector plan, Task 5; spec "The consent page"). It is static,
// with no inline script, as the CSP asks. It reads the signed request from the URL fragment, posts it as it is and
// never parses it. Every word a person or a client chose goes in through textContent, never as markup.

const root = document.getElementById("consent");
const request = location.hash.slice(1);
// Read once, then gone from the address and its history: on a shared browser profile a request left there could be
// signed into by someone else within its ten minutes, and a second sign-in takes the consent over (Tardis).
if (request) history.replaceState(null, "", location.pathname);
const DAYS = 30;  // a connection lasts 1 to 30 days, 30 by default, never more (spec, "Tokens")
const ENDED = {
  request_expired: "This request has expired. Go back to Claude and connect again.",
  invalid_request: "This request can't be used. Go back to Claude and connect again.",
  already_decided: "This request was already answered. Go back to Claude.",
};
const RETRY = {
  invalid_login: "That username and password don't match.",
  too_many_attempts: "Too many attempts. Try again later.",
};
const LOST = "The connection to your home was lost. Try again.";

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === true) node.setAttribute(name, "");
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
}

function show(...nodes) {
  root.replaceChildren(...nodes);
  root.querySelector("h1")?.focus();
}

async function post(path, body) {
  try {
    const response = await fetch(path, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    return { ok: response.ok, data };
  } catch {
    return { ok: false, data: {} };
  }
}

function ended(code) {
  show(el("h1", { tabindex: "-1" }, "This connection can't go on"), el("p", { class: "lede" }, ENDED[code]));
}

function field(label, input) {
  return el("div", { class: "field" }, el("label", { for: input.id }, label), input);
}

function signIn(message = "", csrf = null) {
  const username = el("input", { class: "input", id: "username", autocomplete: "username", required: true });
  const password = el("input", {
    class: "input", id: "password", type: "password", autocomplete: "current-password", required: true,
  });
  const status = el("p", { class: "inline-message", role: "status" }, message);
  const form = el("form", {}, field("Username", username), field("Password", password),
    el("button", { class: "button", type: "submit" }, "Sign in"), status);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "Signing in...";
    // Switch person sends the token this page holds: without it a request already signed in can't be taken over
    const answer = await post("/authorize/signin", { request, username: username.value, password: password.value, ...(csrf ? { csrf } : {}) });
    if (answer.ok) return consent(answer.data);
    const code = answer.data.error;
    if (ENDED[code]) return ended(code);
    status.textContent = RETRY[code] || LOST;
  });
  show(el("h1", { tabindex: "-1" }, "Connect an app to your home"),
    el("p", { class: "lede" }, "Sign in to choose what it can read. Your password is checked here, on your home."),
    form);
}

function endsOn(days) {
  return new Date(Date.now() + days * 86400000).toLocaleDateString(undefined, { dateStyle: "long" });
}

function consent(view) {
  const app = view.app.split(" (")[0];  // "Claude (claude.ai)" is Claude: the app named by its redirect host
  const status = el("p", { class: "inline-message", role: "status" });
  const allow = el("button", { class: "button", type: "button", disabled: true }, "Allow");
  const deny = el("button", { class: "button secondary", type: "button" }, "Deny");
  const all = el("input", { type: "checkbox", id: "room-all" });
  const boxes = [];
  const earlier = new Map();
  for (const room of view.rooms.filter((room) => room.earlier_of)) {
    earlier.set(room.earlier_of, [...(earlier.get(room.earlier_of) || []), room]);
  }
  const list = el("div", { class: "choices" });
  view.rooms.filter((room) => !room.earlier_of).forEach((room, index) => {
    const box = el("input", { type: "checkbox", id: `room-${index}`, value: room.room, disabled: room.cloud });
    const row = el("div", { class: "choice" }, box, el("label", { for: box.id }, room.title || "Untitled"));
    if (room.cloud) row.append(" ", el("span", { class: "badge" }, "Kept away from cloud models"));
    for (const part of earlier.get(room.room) || []) {
      row.append(el("p", { class: "meta" }, `${part.title || "Untitled"}: earlier part of ${room.title || "Untitled"}`));
    }
    if (!room.cloud) boxes.push(box);
    list.append(row);
  });
  list.append(el("div", { class: "choice" }, all, el("label", { for: all.id }, "All my rooms, including new ones")));
  const days = el("input", { class: "input", id: "days", type: "number", min: "1", max: String(DAYS), value: String(DAYS) });
  const ends = el("small", {}, `Ends on ${endsOn(DAYS)}, and never later than ${DAYS} days from now.`);
  const chosen = () => (all.checked ? "*" : boxes.filter((box) => box.checked).map((box) => box.value));
  const update = () => {
    const count = Number.parseInt(days.value, 10);
    const good = Number.isInteger(count) && count >= 1 && count <= DAYS;
    if (good) ends.textContent = `Ends on ${endsOn(count)}, and never later than ${DAYS} days from now.`;
    allow.disabled = !good || (chosen() !== "*" && chosen().length === 0);
  };
  for (const box of [...boxes, all]) box.addEventListener("change", update);
  days.addEventListener("input", update);
  const decide = async (yes) => {
    allow.disabled = deny.disabled = true;
    status.textContent = yes ? "Allowing..." : "Denying...";
    const body = { pending: view.pending, csrf: view.csrf, allow: yes };
    const answer = await post("/authorize/decision", yes ? { ...body, rooms: chosen(), days: Number.parseInt(days.value, 10) } : body);
    if (answer.ok && answer.data.redirect) return location.assign(answer.data.redirect);
    const code = answer.data.error;
    if (ENDED[code]) return ended(code);
    status.textContent = LOST;
    deny.disabled = false;
    update();
  };
  allow.addEventListener("click", () => decide(true));
  deny.addEventListener("click", () => decide(false));
  const switchPerson = el("button", { class: "button ghost", type: "button" }, "Switch person");
  switchPerson.addEventListener("click", () => signIn("", view.csrf));
  const lines = [
    `What ${app} reads can't be taken back.`,
    `${app}'s HIPAA agreement doesn't cover connectors.`,
    "Room text can contain instructions written by other people. Don't let a chat that uses this connector send email or post elsewhere without checking.",
    "This home's admins can see that this connection exists and can end it. They can't see which rooms it reads.",
    `Allow only if you just started connecting from your own ${app} account.`,
  ];
  show(
    el("p", { class: "meta" }, `Signed in as ${view.name} `, switchPerson),
    el("h1", { tabindex: "-1" }, view.app),
    ...(view.client_name ? [el("p", { class: "meta" }, `It calls itself "${view.client_name}".`)] : []),
    el("p", { class: "lede" }, `${app} wants to read the rooms you choose on this home. It can't post or change anything.`),
    el("fieldset", { class: "field" }, el("legend", {}, "Rooms it can read"), list),
    field("Connection lasts (days)", days), ends,
    ...lines.map((line) => el("p", {}, line)),
    el("div", { class: "button-row" }, allow, deny), status,
  );
  update();
}

if (!request) ended("invalid_request");
else signIn();
