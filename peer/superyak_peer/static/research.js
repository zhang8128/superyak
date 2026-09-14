"use strict";

// Account-owned research collections. No external feed or model runs on entry.
const Research = (() => {
  const fresh = () => ({ catalog: [], source: null, items: [], imports: [], more: {}, drafts: {}, create: null, batch: null, error: null, conflict: false, busy: false, sequence: 0 });
  let ui = fresh();
  const path = (id) => `/api/data-sources/${pathPart(id)}`;
  const guard = () => { const current = ui, person = identityKey(state.me); return () => current === ui && person === identityKey(state.me); };
  const nameOf = (item) => item.kind === "file" ? item.file.name : item.source.record.content.title;
  function reset() { ui = fresh(); }
  function close() { if (!ui.busy) { ui.create = null; ui.batch = null; } }
  const atSource = (id) => routeParts().route === 'research' && (routeParts().id || null) === (id || null);
  async function load(id) {
    if (!atSource(id)) return;
    if (ui.source?.id !== id) ui.source = null;
    const valid = guard(), sequence = ++ui.sequence;
    const catalog = await api("/api/data-sources?limit=50");
    const detail = id ? await Promise.all([api(path(id)), api(`${path(id)}/items?limit=50`), api(`${path(id)}/imports?limit=50`)]) : null;
    if (!valid() || sequence !== ui.sequence || !atSource(id)) return;
    ui.catalog = catalog.sources; ui.more.catalog = catalog.sources.length === 50;
    ui.source = detail?.[0] || null;
    ui.items = detail?.[1].items || []; ui.imports = detail?.[2].imports || [];
    ui.more.items = ui.items.length === 50; ui.more.imports = ui.imports.length === 50;
  }
  function remember(target) {
    if (target.closest('#source-settings')) {
      const form = target.form;
      const id = form.dataset.sourceId;
      if (!id) return;
      ui.drafts[id] = { name: form.elements.name.value, description: form.elements.description.value, version: ui.drafts[id]?.version ?? Number(form.dataset.version) };
    }
    if (target.closest('#source-create-form') && ui.create) {
      const form = target.form;
      ui.create = { name: form.elements.name.value, kind: form.elements.kind.value, description: form.elements.description.value };
    }
  }
  function fields(value, creating = false) {
    const prefix = creating ? 'new-source' : 'source';
    return `<div class="field"><label for="${prefix}-name">Source name</label><input id="${prefix}-name" class="input" name="name" required maxlength="200" value="${escapeHtml(value.name)}"></div>${creating ? `<div class="field"><label for="${prefix}-kind">Source type</label><select id="${prefix}-kind" class="select" name="kind"><option value="selected-records" ${value.kind === 'selected-records' ? 'selected' : ''}>Papers and selected source records</option><option value="file" ${value.kind === 'file' ? 'selected' : ''}>Uploaded files and datasets</option></select></div>` : ''}<div class="field"><label for="${prefix}-description">Description</label><textarea id="${prefix}-description" class="textarea short" name="description" maxlength="2000">${escapeHtml(value.description || '')}</textarea></div>`;
  }
  function dialogs() {
    if (ui.create) return `<dialog aria-labelledby="new-source-title"><div class="dialog-body"><h2 id="new-source-title">New private source</h2><p>Give a collection a name you recognize. You can correct it later.</p>${errorMarkup()}<form id="source-create-form">${fields(ui.create, true)}<div class="button-row"><button class="button" ${ui.busy ? 'disabled' : ''}>Create source</button><button type="button" class="button secondary" data-action="close-dialog">Cancel</button></div></form></div></dialog>`;
    if (!ui.batch) return '';
    const batch = ui.batch;
    return `<dialog aria-labelledby="import-preview-title"><div class="dialog-body"><p class="eyebrow">Only you</p><h2 id="import-preview-title">Review this import</h2><p>Into <strong>${escapeHtml(batch.name)}</strong>. Imported content stays private. This does not grant training or publication rights.</p><ul>${batch.names.map(name => `<li>${escapeHtml(name)}</li>`).join('')}</ul><p class="meta">${batch.document ? 'Up to 20 selected records. Attribution and recorded permissions remain source claims.' : 'Up to 20 files, 4 MiB each. Original bytes are preserved. Files uploaded before an interrupted import remain in your private files.'}</p>${errorMarkup()}<div class="button-row"><button class="button" data-action="research-import" ${ui.busy ? 'disabled' : ''}>${ui.busy ? 'Importing…' : 'Import privately'}</button><button class="button secondary" data-action="close-dialog" ${ui.busy ? 'disabled' : ''}>Cancel</button></div></div></dialog>`;
  }
  function errorMarkup() { return ui.error ? `<p class="notice error" role="status">${escapeHtml(ui.error)}</p>${ui.conflict ? `<button class="button secondary" data-action="research-reload">Load latest source settings</button>` : ""}` : ''; }
  function moreButton(kind) { return ui.more[kind] ? `<button class="button secondary" data-action="research-more" data-kind="${kind}" ${ui.busy ? 'disabled' : ''}>Load more ${kind === 'catalog' ? 'sources' : kind === 'items' ? 'items' : 'import history'}</button>` : ''; }
  function itemMarkup(item) {
    if (item.kind === 'file') return `<article class="card compact"><h3>${escapeHtml(item.file.name)}</h3><p class="meta">${escapeHtml(item.file.media_type)} · ${formatBytes(item.file.size)} · In your library</p><p class="meta">Active sharing layers may also give others access to this file.</p><a class="text-button" href="/api/files/${pathPart(item.file.id)}">Download original file</a><details><summary>File provenance</summary><p class="fingerprint">SHA-256 ${escapeHtml(item.file.digest)}</p></details></article>`;
    const { id, record } = item.source;
    return `<article class="card compact evidence-card"><p class="eyebrow">Source record · Only you</p><h3>${escapeHtml(record.content.title)}</h3><p class="meta">${escapeHtml(record.author)} · ${escapeHtml(record.source_locator)}</p><details><summary>Read source and provenance</summary><p class="shared-body">${escapeHtml(record.content.body)}</p><p class="meta">Origin: ${escapeHtml(record.origin)}<br>Revision: ${escapeHtml(record.revision)}</p><p class="fingerprint meta">Source hash: ${escapeHtml(record.source_hash)}</p><p class="meta">Recorded audience: ${escapeHtml(JSON.stringify(record.audience))}. These claims do not grant new access.</p></details><div class="button-row"><button class="button secondary" data-action="research-review" data-id="${escapeHtml(id)}">Start evidence review</button><button class="button ghost" data-action="export-source" data-id="${escapeHtml(id)}">Export source</button></div></article>`;
  }
  function view() {
    const source = ui.source;
    const draft = source && (ui.drafts[source.id] || source);
    return `<header class="page-head"><div><p class="eyebrow">Your research workspace</p><h1>Research & data</h1><p class="lede">Keep papers, clinical files, and biotech datasets together. Inspect the source before building an evidence review.</p></div><button class="button" data-action="research-new">New source</button></header><div class="notice">Importing is private. Sharing is a separate choice in My sharing layers. Sources currently import files you select; automatic feeds are not connected.</div>${!ui.create && !ui.batch ? errorMarkup() : ''}<div class="workspace research-workspace"><aside class="workspace-list"><div class="item-list">${ui.catalog.map(row => `<a class="item ${source?.id === row.id ? 'selected' : ''}" href="#research/${pathPart(row.id)}"><span class="item-main"><strong>${escapeHtml(row.name)}</strong><span>${row.item_count} items · ${row.enabled ? 'Imports on' : 'Imports paused'}</span></span></a>`).join('') || empty('Your first source', 'Create a collection for papers, observations, or datasets.')}${moreButton('catalog')}</div></aside><section>${source ? `<div class="section-head"><div><p class="eyebrow">${source.kind === 'file' ? 'Files and datasets' : 'Papers and records'} · Only you</p><h2>${escapeHtml(source.name)}</h2></div><button class="button secondary" data-action="research-toggle" ${ui.busy ? 'disabled' : ''}>${source.enabled ? 'Pause imports' : 'Resume imports'}</button></div><p class="meta">${source.enabled ? 'Imports are on.' : 'Imports are paused.'} Existing items remain available and keep their sharing settings.</p><details class="card compact source-settings" ${ui.drafts[source.id] ? "open" : ""}><summary>Edit source details</summary><form id="source-settings" data-source-id="${escapeHtml(source.id)}" data-version="${source.version}">${fields(draft)}<button class="button secondary" ${ui.busy ? 'disabled' : ''}>Save source details</button></form></details><div class="section"><div class="section-head"><h2>Items in this source</h2><label class="button secondary ${source.enabled ? '' : 'disabled'}" for="research-upload">${source.kind === 'file' ? 'Select files' : 'Select source document'}</label><input id="research-upload" class="sr-only" aria-label="${source.kind === 'file' ? 'Select files' : 'Select source document'}" type="file" ${source.enabled && !ui.busy ? '' : 'disabled'} ${source.kind === 'file' ? 'multiple accept=".csv,.json,.txt,.pdf,.png,.jpg,.jpeg,.gif"' : 'accept="application/json,.json"'}></div><div class="item-list">${ui.items.map(itemMarkup).join('') || empty('No items imported yet', 'Select a file to preview what you are adding.')}${moreButton('items')}</div></div><details class="section card compact"><summary>Import history · ${ui.imports.length}${ui.more.imports ? '+' : ''} receipts</summary>${ui.imports.map(receipt => `<div class="history-entry"><strong>${receipt.status === 'succeeded' ? `Imported · ${receipt.added_count} new items` : 'Import needs attention'}</strong><p class="meta">${formatDate(receipt.created_at)}${receipt.error ? ` · ${escapeHtml(receipt.error)}` : ''}</p><details><summary>Receipt details</summary><p class="fingerprint meta">${escapeHtml(receipt.id)}<br>Request ${escapeHtml(receipt.request_id)}</p></details></div>`).join('') || '<p>No imports yet.</p>'}${moreButton('imports')}</details>` : `<div class="card tint"><h2>A place for the evidence</h2><p>Start a paper collection for a research question, or upload clinical and biotech files you are authorized to use.</p><p>Each source keeps its identity when you correct its name. A review starts as your own private draft, with its source attached as a citation.</p><button class="button secondary" data-action="research-new">Create your first source</button></div>`}</section></div>${dialogs()}`;
  }
  async function run(operation) {
    if (ui.busy) return;
    const valid = guard(); ui.busy = true; ui.error = null; ui.conflict = false;
    try { await operation(valid); }
    catch (error) {
      if (!valid()) return;
      ui.conflict = error.status === 409;
      ui.error = error.status === 409 ? `This source changed or imports are paused. Your correction and selected input are still here. Load the latest source settings below, then review your correction before retrying. ${error.message}` : error.message;
      if (error.status === 401) { state.reauth = true; state.reauthError = null; }
    } finally { if (valid()) { ui.busy = false; render(); } }
  }
  async function submit(form) {
    if (form.id === 'source-create-form') {
      remember(form.elements.name);
      await run(async valid => {
        const result = await api('/api/data-sources', { method: 'POST', json: ui.create });
        if (!valid()) return;
        ui.create = null; location.hash = `research/${pathPart(result.id)}`; await load(result.id);
      });
    }
    if (form.id === 'source-settings') {
      if (!ui.source || form.dataset.sourceId !== ui.source.id || !atSource(ui.source.id)) return;
      remember(form.elements.name);
      const source = ui.source, submitted = ui.drafts[source.id], draft = { ...submitted };
      await run(async valid => {
        const updated = await api(path(source.id), { method: 'PATCH', json: draft });
        if (!valid()) return;
        if (ui.drafts[source.id] === submitted) delete ui.drafts[source.id];
        if (atSource(source.id)) { ui.source = updated; await load(source.id); }
        if (valid()) setFlash('Source details saved. Its contents and sharing did not change.');
      });
    }
  }
  async function choose(input) {
    if (input.id !== 'research-upload' || !input.files.length || ui.busy || !ui.source) return;
    const valid = guard(), source = ui.source, files = [...input.files];
    try {
      const batch = { sourceId: source.id, name: source.name, requestId: crypto.randomUUID(), version: source.version, uploaded: [], files, names: files.map(file => file.name) };
      if (source.kind === 'selected-records') {
        if (files[0].size > 512 * 1024) throw new Error('Choose a source document of 512 KiB or less.');
        batch.document = JSON.parse(await files[0].text());
        if (batch.document.format !== 'superyak.selected-sources.v1' || !Array.isArray(batch.document.records) || !batch.document.records.length || batch.document.records.length > 20) throw new Error('Choose a selected-source document with 1–20 records.');
        batch.names = batch.document.records.map(record => record.content?.title || 'Untitled source record');
      } else if (files.length > 20 || files.some(file => file.size > 4 * 1024 * 1024)) throw new Error('Choose up to 20 files, each 4 MiB or less.');
      if (!valid() || ui.source?.id !== source.id) return;
      ui.batch = batch; ui.error = null;
    } catch (error) { if (valid()) ui.error = error instanceof SyntaxError ? 'This file is not valid JSON. Your source is unchanged.' : error.message; }
    if (valid()) { input.value = ''; render(); }
  }
  async function importBatch(valid) {
    const batch = ui.batch;
    if (!batch) return;
    for (let index = batch.uploaded.length; !batch.document && index < batch.files.length; index++) {
      const file = batch.files[index], bytes = new Uint8Array(await file.arrayBuffer());
      if (!valid()) return;
      let binary = ''; for (let start = 0; start < bytes.length; start += 32768) binary += String.fromCharCode(...bytes.subarray(start, start + 32768));
      const extension = file.name.split('.').pop().toLowerCase();
      const mediaType = ({ csv: 'text/csv', json: 'application/json', txt: 'text/plain', pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif' })[extension] || file.type;
      const uploaded = await api('/api/files', { method: 'POST', json: { name: file.name, media_type: mediaType, content_base64: btoa(binary) } });
      if (!valid()) return;
      batch.uploaded.push(uploaded.id);
    }
    const result = await api(`${path(batch.sourceId)}/imports`, { method: 'POST', json: { request_id: batch.requestId, version: batch.version, ...(batch.document ? { document: batch.document } : { file_ids: batch.uploaded }) } });
    if (!valid()) return;
    ui.batch = null;
    setFlash(`Imported privately · ${result.added_count} new items. No sharing was turned on.`);
    await load(batch.sourceId);
    if (valid()) { await loadData(); }
  }
  async function action(target) {
    const action = target.dataset.action;
    if (action === 'research-new') { ui.create = { name: '', kind: 'selected-records', description: '' }; ui.error = null; render(); }
    if (action === 'research-toggle' && ui.source) {
      const source = ui.source;
      await run(async valid => { const updated = await api(path(source.id), { method: 'PATCH', json: { version: source.version, enabled: !source.enabled } }); if (valid() && atSource(source.id)) { ui.source = updated; await load(source.id); } });
    }
    if (action === 'research-reload') {
      const id = ui.batch?.sourceId || ui.source?.id;
      await run(async valid => { await load(id); if (valid() && ui.source?.id === id) { if (ui.batch) ui.batch.version = ui.source.version; if (ui.drafts[id]) ui.drafts[id].version = ui.source.version; } });
    }
    if (action === 'research-import') await run(importBatch);
    if (action === 'research-review') {
      const item = ui.items.find(item => item.kind === 'record' && item.source.id === target.dataset.id);
      if (item) await run(async valid => {
        const record = item.source.record;
        const excerpt = record.content.body.slice(0, 12000);
        const body = `Research question\nWhat does this source support, and what remains uncertain?\n\nSource: ${record.content.title}\nAuthor: ${record.author}\nLocation: ${record.source_locator}\nRevision: ${record.revision}\nSource hash: ${record.source_hash}\n\nSelected source text${excerpt.length < record.content.body.length ? ' (first 12,000 characters; inspect the full source in Research & data)' : ''}\n${excerpt}\n\nEvidence review\nStudy design and population:\nMain findings and exact supporting passages:\nLimitations and conflicting evidence:\nApplicability and unanswered questions:\n\nDraft review — not independently validated. Source-use and publication permissions need review.`;
        const layer = await api('/api/layers', { method: 'POST', json: { title: `Review: ${record.content.title}`.slice(0, 200), body } });
        if (!valid()) return;
        state.home.layers.push(layer); await openLayer(layer.id);
      });
    }
    if (action === 'research-more') await run(async valid => {
      const kind = target.dataset.kind, rows = kind === 'catalog' ? ui.catalog : ui[kind];
      const endpoint = kind === 'catalog' ? '/api/data-sources' : `${path(ui.source.id)}/${kind}`;
      const result = await api(`${endpoint}?limit=50&offset=${rows.length}`);
      if (!valid()) return;
      const incoming = result[kind === 'catalog' ? 'sources' : kind];
      rows.push(...incoming); ui.more[kind] = incoming.length === 50;
    });
  }
  return { reset, close, load, remember, view, submit, choose, action };
})();
