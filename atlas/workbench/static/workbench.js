'use strict';
(() => {
  const bundle = JSON.parse(document.getElementById('bundle-data').textContent);
  const records = new Map(bundle.items.map(record => [record.id, record]));
  const rows = new Map(Array.from(document.querySelectorAll('[data-list-id]'), row => [row.dataset.listId, row]));
  const details = new Map(Array.from(document.querySelectorAll('[data-record-id]'), panel => [panel.dataset.recordId, panel]));
  const form = document.getElementById('filters');
  const search = document.getElementById('search');
  const kind = document.getElementById('kind');
  const status = document.getElementById('status');
  const facets = Array.from(document.querySelectorAll('[data-facet]'));
  let selected = Array.from(details.keys())[0];

  function showRecord(id, focus = false) {
    if (!records.has(id)) return;
    selected = id;
    for (const [recordId, panel] of details) panel.hidden = recordId !== id;
    for (const link of document.querySelectorAll('.record-link')) {
      if (link.dataset.open === id) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
    document.getElementById('detail-empty').textContent = '';
    document.getElementById('selection-note').hidden = !rows.get(id).hidden;
    if (focus) details.get(id).querySelector('h2').focus({preventScroll: true});
    if (focus) document.getElementById('detail-pane').scrollIntoView({block: 'start'});
  }

  function filter() {
    const query = search.value.trim().toLocaleLowerCase();
    let count = 0;
    for (const [id, record] of records) {
      const matches = (!query || `${record.title} ${record.summary}`.toLocaleLowerCase().includes(query))
        && (!kind.value || kind.value === record.kind)
        && (!status.value || status.value === record.status)
        && facets.every(control => !control.value || (record.facets[control.dataset.facet] || []).includes(control.value));
      rows.get(id).hidden = !matches;
      if (matches) count++;
    }
    document.getElementById('result-count').textContent = `${count} of ${records.size} ${records.size === 1 ? 'record' : 'records'}`;
    document.getElementById('no-results').hidden = count !== 0;
    // Keep evidence in view when filtering; state explicitly when it lies outside the result set.
    if (selected) document.getElementById('selection-note').hidden = !rows.get(selected).hidden;
  }

  function openHash(focus = false) {
    if (!location.hash.startsWith('#record=')) return;
    try { showRecord(decodeURIComponent(location.hash.slice(8)), focus); }
    catch (error) { if (!(error instanceof URIError)) throw error; }
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-open]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    history.replaceState(null, '', link.getAttribute('href'));
    showRecord(link.dataset.open, true);
  });
  form.addEventListener('submit', event => event.preventDefault());
  form.addEventListener('input', filter);
  form.addEventListener('change', filter);
  form.addEventListener('reset', () => setTimeout(filter, 0));
  window.addEventListener('hashchange', () => openHash(true));
  filter();
  openHash();
})();
