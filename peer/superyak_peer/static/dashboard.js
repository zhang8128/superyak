"use strict";

const Dashboard = (() => {
  let query = '', space = null, memberChange = null, memberError = null, spaceNames = {}, help = false, pending = false;
  let epoch = 0;
  const starters = {
    care: { title: 'Questions for my care team', body: 'What matters to me right now\n\nWhat I have noticed (including approximate dates)\n\nQuestions I want to ask\n\nWhat I am unsure about\n\nSupport I would find helpful\n' },
    evidence: { title: 'My evidence review', body: 'Research question\n\nSources and exact supporting passages\n\nStudy design, population, and outcomes\n\nFindings\n\nLimitations and conflicting evidence\n\nWhat is still uncertain\n\nNext steps\n' },
    update: { title: 'An update for people I choose', body: 'What I would like you to know\n\nWhat has changed\n\nWhere I could use support\n\nWhat I am still working out\n' },
  };
  function reset() { epoch++; query = ''; space = null; memberChange = null; memberError = null; spaceNames = {}; help = false; pending = false; }
  function close() { if (!pending) memberChange = null; help = false; }
  function validNow() { const serial = epoch, person = identityKey(state.me); return () => serial === epoch && person === identityKey(state.me); }
  function applyDisplay() {
    try { document.documentElement.classList.toggle('large-text', localStorage.getItem('superyak:large-text') === 'yes'); document.documentElement.classList.toggle('quiet-view', localStorage.getItem('superyak:quiet-view') === 'yes'); } catch (_) { /* Display preferences are optional. */ }
  }
  function searchForm() {
    return `<form class="home-search" id="home-search-form" role="search"><label class="sr-only" for="home-search">Search your home</label><input class="input" id="home-search" type="search" maxlength="200" value="${escapeHtml(query)}" placeholder="Find your notes, spaces, or sources"><button class="button secondary" type="submit">Search</button></form>`;
  }
  function layerLink(layer) {
    const edit = state.layerEdits[layer.id];
    return `<a class="item" href="#layers/${pathPart(layer.id)}"><span class="item-main"><strong>${escapeHtml(edit?.values.title || layer.title)}</strong><span>${edit?.dirty ? 'Unsaved words in this tab' : layer.active_revision ? 'A version is shared · draft stays editable' : 'Saved privately · sharing off'}</span></span><span aria-hidden="true">↗</span></a>`;
  }
  function spaceCard(item) {
    return `<article class="card compact space-card"><p class="eyebrow">${kindLabel(item.kind)}</p><h3><a href="#spaces/${pathPart(item.id)}">${escapeHtml(item.name)}</a></h3><p class="meta">${item.member_ids.length} ${item.member_ids.length === 1 ? 'person' : 'people'} · ${item.owner_id === state.me.id ? 'You manage this space' : 'You are a member'}</p><p class="meta">${item.kind === 'organization' ? 'Organization access applies to explicitly shared releases.' : 'Shared versions keep their selected audience.'}</p></article>`;
  }
  function sharingSummary() {
    const layers = state.home.layers;
    const visible = Object.values(state.activeLayers);
    const publicCount = visible.filter(layer => layer.public && !state.activeLayerErrors[layer.id]).length;
    const unknown = layers.filter(layer => layer.active_revision && state.activeLayerErrors[layer.id]).length;
    return `<section class="section card sharing-summary"><div class="section-head"><div><p class="eyebrow">At your pace</p><h2>Your sharing overview</h2></div><a class="text-button" href="#layers">Review sharing</a></div><div class="sharing-counts"><div><strong>${layers.filter(layer => !layer.active_revision).length}</strong><span>Private drafts</span></div><div><strong>${layers.filter(layer => layer.active_revision).length}</strong><span>Active releases</span></div><div><strong>${publicCount}${unknown ? '+' : ''}</strong><span>Public versions${unknown ? ' · some status unavailable' : ''}</span></div></div><p class="meta">Build each layer over days or weeks. Private edits stay private until you preview and activate a saved version.</p>${layers.filter(layer => layer.active_revision).slice(0, 4).map(layer => `<a class="sharing-row" href="#layers/${pathPart(layer.id)}"><strong>${escapeHtml(layer.title)}</strong><span>${state.activeLayerErrors[layer.id] ? 'Latest audience unavailable' : state.activeLayers[layer.id]?.public ? 'Public is on' : 'Named sharing is on'}</span><span class="text-button">Manage</span></a>`).join('')}</section>`;
  }
  function home() {
    const { layers, chats, spaces, shared_layers: shared } = state.home;
    const resume = [...layers].sort((a, b) => Number(!!state.layerEdits[b.id]?.dirty) - Number(!!state.layerEdits[a.id]?.dirty) || Number(b.id === state.selectedLayerId) - Number(a.id === state.selectedLayerId));
    const deliveries = state.sync.deliveries.filter(row => row.status === 'failed' || row.status === 'pending');
    const unsaved = layers.filter(row => state.layerEdits[row.id]?.dirty);
    return `<header class="page-head home-head"><div><p class="eyebrow">Welcome, ${escapeHtml(state.me.name)}</p><h1>Your home</h1><p class="lede">Your questions, conversations, and research, with room to work things out.</p></div><button class="button secondary" data-action="dashboard-help">Display & help</button></header><section class="home-start card tint"><div><p class="eyebrow">Start with what you need</p><h2>A private place to begin</h2><p>You can be a patient, family member, clinician, researcher, or several of these. Choose a starting point; your audience comes later.</p></div><div class="starter-actions"><button class="button" data-action="dashboard-starter" data-kind="care">Prepare care questions</button><button class="button secondary" data-action="dashboard-starter" data-kind="evidence">Plan an evidence review</button><button class="button secondary" data-action="dashboard-starter" data-kind="update">Write an update</button><button class="button secondary" data-action="new-chat">New private chat</button></div></section><div class="home-columns"><div><section class="section"><div class="section-head"><h2>Continue where you left off</h2><a class="text-button" href="#layers">All my drafts</a></div><div class="item-list">${resume.slice(0, 3).map(layerLink).join('') || empty('No drafts yet', 'A starting point above opens a saved private draft.')}${chats.slice(0, 2).map(room => `<a class="item" href="#chats/${pathPart(room.id)}"><span class="item-main"><strong>${escapeHtml(room.title)}</strong><span>Private chat · ${escapeHtml(participantSummary(room))}</span></span><span class="meta">${formatDate(room.last_activity)}</span></a>`).join('')}</div></section><section class="section"><div class="section-head"><h2>Your circles and spaces</h2><button class="button secondary" data-action="new-space">Create space</button></div><div class="grid cols-2">${spaces.map(spaceCard).join('') || empty('Make room for collaboration', 'Create a care circle, research project, or organization when it is useful.')}</div></section><section class="section"><div class="section-head"><h2>Shared with you</h2><a class="text-button" href="#shared">See all releases</a></div><div class="item-list">${shared.slice(0, 3).map(sharedItem).join('') || empty('Nothing shared yet', 'Your private work is ready whenever you are.')}</div></section></div><aside>${sharingSummary()}<section class="section card"><p class="eyebrow">Research & data</p><h2>Follow the evidence</h2><p>Keep original sources alongside the questions and limits you identify.</p><p class="meta">${state.sources === null ? 'Source count unavailable' : `${state.sources.length} imported source records`} · ${state.files.length} uploaded files</p><a class="button secondary" href="#research">Open source library</a><p class="meta">${state.assistant.enabled ? 'Gemma is available for private draft assistance.' : 'Manual writing is available. Local assistance is currently off.'}</p></section><section class="section card"><h2>Pick up what needs attention</h2><p>${unsaved.length ? `${unsaved.length} draft${unsaved.length === 1 ? '' : 's'} have unsaved words in this tab.` : 'Your loaded drafts have no unsaved edits in this tab.'}</p><p class="meta">${deliveries.length ? `${deliveries.length} peer deliveries are waiting or need a retry.` : 'No peer deliveries are waiting in the latest status.'}</p><a class="text-button" href="#connections">View connections and delivery</a></section></aside></div>${chatDialog()}`;
  }
  async function loadSpace(id) {
    const valid = validNow(); space = null;
    if (!id) return;
    const [selected, releases] = await Promise.all([api(`/api/spaces/${pathPart(id)}`), api("/api/shared/layers")]);
    if (valid() && routeParts().route === 'spaces' && routeParts().id === id) { space = selected; state.home.shared_layers = releases; }
  }
  function spacesView() {
    if (!space) return `<header class="page-head"><div><p class="eyebrow">Care circles, projects, organizations</p><h1>Your spaces</h1><p class="lede">A space brings people together around versions they choose to share.</p></div><button class="button" data-action="new-space">Create space</button></header><div class="grid cols-3">${state.home.spaces.map(spaceCard).join('')}</div>`;
    const owner = space.owner_id === state.me.id;
    const releases = state.home.shared_layers.filter(layer => (layer.access_routes || []).includes(`space:${space.id}`));
    const available = state.contacts.filter(person => !person.remote && !space.member_ids.includes(person.id));
    return `<header class="page-head"><div><p class="eyebrow">${kindLabel(space.kind)}</p><h1>${escapeHtml(space.name)}</h1><p class="lede">${escapeHtml(space.audience_note)}</p></div><a class="button secondary" href="#spaces">All spaces</a></header><div class="home-columns"><section><div class="section-head"><h2>Shared in this space</h2><a class="text-button" href="#layers">Prepare a sharing layer</a></div><p class="meta">Only active releases available to you through this space appear here. Your personal drafts and private chats have their own audiences.</p><div class="item-list">${releases.map(sharedItem).join('') || empty('No releases here yet', 'Prepare a private layer, select this space, and preview the audience when ready.')}</div></section><aside class="card"><h2>People in this space</h2><div class="item-list">${space.member_ids.map(id => `<div class="member-row"><span><strong>${escapeHtml(contactName(id))}</strong>${id === space.owner_id ? '<small class="meta">Space owner</small>' : ''}</span>${owner && id !== state.me.id ? `<button class="button ghost" data-action="dashboard-remove-member" data-id="${escapeHtml(id)}">Remove ${escapeHtml(contactName(id))}</button>` : ''}</div>`).join('')}</div>${owner ? `<form id="space-add-form" class="section"><div class="field"><label for="space-add-person">Person to add</label><select class="select" id="space-add-person" name="person" required><option value="">Choose a person</option>${available.map(person => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}</option>`).join('')}</select></div><button class="button secondary" ${available.length ? '' : 'disabled'}>Review adding person</button></form><details class="section" ${spaceNames[space.id] !== undefined ? "open" : ""}><summary>Correct this space's name</summary><form id="space-rename-form"><div class="field"><label for="space-rename">Space name</label><input class="input" id="space-rename" name="name" required maxlength="200" value="${escapeHtml(spaceNames[space.id] ?? space.name)}"></div><button class="button secondary">Save name correction</button></form><p class="meta">Correcting a name keeps the same space and membership.</p></details>` : '<p class="meta">The space owner manages its name and membership.</p>'}</aside></div>`;
  }
  function searchView() {
    const term = query.trim().toLocaleLowerCase();
    const rows = [
      ...state.home.layers.map(layer => ({ title: state.layerEdits[layer.id]?.values.title || layer.title, text: layer.body, kind: 'Your draft', href: `#layers/${pathPart(layer.id)}` })),
      ...state.home.chats.map(room => ({ title: room.title, kind: 'Your chat · title search', href: `#chats/${pathPart(room.id)}` })),
      ...state.home.spaces.map(item => ({ title: item.name, kind: kindLabel(item.kind), href: `#spaces/${pathPart(item.id)}` })),
      ...state.home.shared_layers.map(layer => ({ title: layer.title, text: layer.body, kind: 'Release available to you', href: `#shared/${pathPart(layer.id)}` })),
      ...(state.sources || []).map(source => ({ title: source.record.content.title, text: source.record.content.body, kind: 'Your source record', href: '#research' })),
      ...state.files.map(file => ({ title: file.name, kind: 'Your file', href: `/api/files/${pathPart(file.id)}` })),
    ].filter(row => term && `${row.title} ${row.text || ''}`.toLocaleLowerCase().includes(term));
    return `<header class="page-head"><div><p class="eyebrow">Search your accessible work</p><h1>Search results</h1><p class="lede">${term ? `${rows.length} matches for “${escapeHtml(query)}”` : 'Enter a word or title in the search box.'}</p></div></header><p class="meta">Search covers the notes, source text, file names, space names, and chat titles already loaded into your personal home.</p><div class="item-list">${rows.slice(0, 100).map(row => `<a class="item" href="${escapeHtml(row.href)}"><span class="item-main"><strong>${escapeHtml(row.title)}</strong><span>${escapeHtml(row.kind)}</span></span></a>`).join('') || empty('No matching items', 'Try another word or open Research & data to browse your source collections.')}</div>${rows.length > 100 ? '<p>Showing the first 100 matches. Use a more specific search to narrow them.</p>' : ''}`;
  }
  function dialogs() {
    if (help) return `<dialog aria-labelledby="help-title"><div class="dialog-body"><h2 id="help-title">Make yourself comfortable</h2><p>You do not need to finish setting up sharing to use your home. Return to a draft whenever you are ready.</p><label class="choice"><input type="checkbox" id="large-text" ${document.documentElement.classList.contains('large-text') ? 'checked' : ''}><span>Larger text</span></label><label class="choice"><input type="checkbox" id="quiet-view" ${document.documentElement.classList.contains('quiet-view') ? 'checked' : ''}><span>Quieter view</span></label><h3>If something is mixed up</h3><p>Names can be corrected in Account or a space's settings. A name correction keeps the same identity and sharing rules. Review the actual people before sharing.</p><h3>Leaving and returning</h3><p>Save private drafts before closing the page or switching accounts. While this tab stays open, you can browse and return to unsaved layer text. Private chat drafts also stay in this tab until you sign out.</p><button class="button secondary" data-action="close-dialog">Back to my home</button></div></dialog>`;
    if (!memberChange) return '';
    return `<dialog aria-labelledby="member-preview-title"><div class="dialog-body"><p class="eyebrow">Review membership</p><h2 id="member-preview-title">${memberChange.remove ? 'Remove' : 'Add'} ${escapeHtml(contactName(memberChange.person))}</h2><p>Space: <strong>${escapeHtml(memberChange.space.name)}</strong></p><p>${memberChange.space.kind === 'organization' ? memberChange.remove ? 'This removes organization membership and its route to active releases. Another direct, space, or public route may still allow access.' : 'This person will be able to read active releases explicitly shared with this organization, including future releases.' : memberChange.remove ? 'Earlier care-circle or project releases keep the people selected at activation. Removing membership does not revoke those saved audiences. Review each release to stop its sharing.' : 'Earlier care-circle or project releases keep their original selected people. This person can be included when an owner previews and activates a new version.'}</p><p class="meta">Private drafts and chat histories keep their own audiences. Copies already received cannot be erased.</p>${memberError ? `<p class="notice error" role="status">${escapeHtml(memberError)} You can retry or cancel.</p>` : ""}<div class="button-row"><button class="button" data-action="dashboard-confirm-member" ${pending ? 'disabled' : ''}>${memberChange.remove ? 'Remove this person' : 'Add this person'}</button><button class="button secondary" data-action="close-dialog" ${pending ? 'disabled' : ''}>Cancel</button></div></div></dialog>`;
  }
  async function perform(operation) {
    if (pending) return;
    const valid = validNow(); pending = true; memberError = null;
    try { await operation(valid); }
    catch (error) { if (valid()) { setFlash(error.message, true); if (memberChange) memberError = error.message; if (error.status === 401) state.reauth = true; } }
    finally { if (valid()) { pending = false; render(); } }
  }
  async function submit(form) {
    if (form.id === 'home-search-form') { query = form.querySelector('input').value; location.hash = 'search'; render(); }
    if (form.id === 'space-add-form' && space) {
      const selected = form.elements.person.value, current = space;
      if (!selected) return;
      await perform(async valid => { const latest = await api(`/api/spaces/${pathPart(current.id)}`); if (valid()) memberChange = { space: latest, person: selected, remove: false }; });
    }
    if (form.id === 'space-rename-form' && space) {
      const current = space, name = form.elements.name.value;
      await perform(async valid => { const updated = await api(`/api/spaces/${pathPart(current.id)}`, { method: 'PATCH', json: { name } }); if (valid()) { if (space?.id === current.id) space = updated; if (spaceNames[current.id] === name) delete spaceNames[current.id]; await loadData(); if (valid()) setFlash('Space name corrected. Membership and sharing stay the same.'); } });
    }
  }
  async function action(target) {
    if (target.dataset.action === 'dashboard-help') { help = true; render(); }
    if (target.dataset.action === 'dashboard-starter') {
      const draft = starters[target.dataset.kind];
      if (draft) await perform(async valid => { const layer = await api('/api/layers', { method: 'POST', json: draft }); if (valid()) { state.home.layers.push(layer); await openLayer(layer.id); } });
    }
    if (target.dataset.action === 'dashboard-remove-member' && space) {
      const current = space, person = target.dataset.id;
      await perform(async valid => { const latest = await api(`/api/spaces/${pathPart(current.id)}`); if (valid()) memberChange = { space: latest, person, remove: true }; });
    }
    if (target.dataset.action === 'dashboard-confirm-member' && memberChange) {
      const change = memberChange;
      await perform(async valid => {
        const endpoint = `/api/spaces/${pathPart(change.space.id)}/members`;
        const updated = await api(change.remove ? `${endpoint}/${pathPart(change.person)}` : endpoint, { method: change.remove ? 'DELETE' : 'POST', json: change.remove ? {} : { user_id: change.person } });
        if (valid()) { if (space?.id === change.space.id) space = updated; memberChange = null; await loadData(); if (valid()) setFlash('Membership updated. Review active sharing routes for the effective audience.'); }
      });
    }
  }
  function input(target) { if (target.id === 'home-search') query = target.value; if (target.id === 'space-rename' && space) spaceNames[space.id] = target.value; }
  function change(target) { if (['large-text', 'quiet-view'].includes(target.id)) { try { localStorage.setItem(`superyak:${target.id}`, target.checked ? 'yes' : 'no'); } catch (_) {} document.documentElement.classList.toggle(target.id, target.checked); } }
  return { reset, close, home, spacesView, searchView, searchForm, dialogs, loadSpace, submit, action, input, change, applyDisplay };
})();
