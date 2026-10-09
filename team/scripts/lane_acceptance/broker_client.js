// Browser-lane acceptance, step 3, run INSIDE a browser worker by worker_probes.py: drive the lane's browser through
// the broker and test one thing (argv[2]); argv[3] is params.json's text. Exit codes follow lane/profile_probe.js:
//   0  the action SUCCEEDED          (a pass for `page`, a failure for the negative probes)
//   1  the action was REFUSED        (prints `refused: <name>`; only for a refusal this script recognises by its code)
//   2  the probe could not tell      (prints `broken: ...`: a timeout, a crash, an unexpected error, a missing input)
// A negative probe never counts an arbitrary exception as a refusal. What each tests:
//   page          a page served on a lane port loads (must succeed)
//   wrongsecret   the endpoint with its secret works (control), then with no secret and with a wrong 64-hex secret
//                 each is rejected (refused only if the control connected and both wrong ones were rejected)
//   external      a public page loads (must be blocked by the network wall)
//   file          the dotfile the driver checked (non-empty, exists) opens as file:// (must be ERR_ACCESS_DENIED)
//   canary        a server on a port outside this lane's block answers (must be blocked)
//   write         two downloads through CDP: into the lane's b/ (the control: the broker may write there) and into the
//                 home folder. It reports Browser.downloadWillBegin / downloadProgress for each as JSON and exits 0;
//                 the driver decides, from outside, by comparing $HOME's top-level names and looking for the control.
//   getusermedia  a page granted camera and microphone: only a rejection of the getUserMedia promise counts, and its
//                 name is printed (the driver's sandbox_check rows show the services denied)
//   exposenetwork for information only (spec, build order 0): does exposeNetwork '<loopback>' reach a port outside this
//                 lane through the connection itself?
// It reads the endpoint from PW_TEST_CONNECT_WS_ENDPOINT, as Playwright Test does, and every line it prints goes
// through redact(): Playwright's errors quote the endpoint, secret and all.
const { chromium } = require(require.resolve('playwright-core', { paths: [process.cwd()] }));
const what = process.argv[2], p = JSON.parse(process.argv[3]);
const endpoint = process.env.PW_TEST_CONNECT_WS_ENDPOINT;
const secret = endpoint ? new URL(endpoint).pathname : '/';
const redact = text => String(text).split(secret).join('/<secret>').replace(/\x1b\[[0-9;]*m/g, '')
  .replace(/\/[0-9a-f]{64}/g, '/<secret>');
const say = text => console.log(redact(text).replace(/\s+/g, ' ').slice(0, 280));
const first = e => String(e).split('\n')[0];
const refused = name => { say('refused: ' + name); process.exit(1); };
const broken = why => { say('broken: ' + why); process.exit(2); };
const serve = (port, handler) => new Promise((resolve, reject) => {
  const srv = require('http').createServer(handler).on('error', reject).listen(port, '127.0.0.1', () => resolve(srv));
});
const netCode = text => (/net::(ERR_[A-Z_]+)/.exec(String(text)) || [])[1];
// The Chromium network errors the sandbox's network wall gives (the machine's network is up: the driver checked).
const NET_REFUSED = new Set(['ERR_NAME_NOT_RESOLVED', 'ERR_ACCESS_DENIED', 'ERR_NETWORK_ACCESS_DENIED',
  'ERR_CONNECTION_REFUSED', 'ERR_ADDRESS_UNREACHABLE', 'ERR_CONNECTION_FAILED', 'ERR_NAME_RESOLUTION_FAILED']);
(async () => {
  if (!endpoint) broken('no PW_TEST_CONNECT_WS_ENDPOINT in this environment');
  if (what === 'wrongsecret') {
    let good;
    try { good = await chromium.connect(endpoint, { timeout: 15000 }); await good.close(); }
    catch (e) { broken('the control connection with the real secret failed: ' + first(e)); }
    const wrong = [];
    for (const path of ['/', '/' + '0123456789abcdef'.repeat(4)]) {
      const url = new URL(endpoint);
      url.pathname = path;
      try { const b = await chromium.connect(url.toString(), { timeout: 8000 }); await b.close(); say('connected with ' + (path === '/' ? 'no secret' : 'a wrong secret')); process.exit(0); }
      catch (e) { wrong.push(first(e)); }
    }
    refused('both a missing and a wrong secret were rejected (' + wrong[0].slice(0, 80) + ')');
  }
  if (what === 'exposenetwork') {
    const tunneled = await chromium.connect(endpoint, { timeout: 15000, exposeNetwork: '<loopback>' });
    const page = await tunneled.newPage();
    let reached = 1, said = '';
    try { await page.goto(`http://127.0.0.1:${p.canary_port}/`, { timeout: 5000 }); reached = 0; said = 'reached through the connection'; }
    catch (e) { said = first(e); }
    say(said);
    await tunneled.close();
    process.exit(reached);
  }
  let browser;
  try { browser = await chromium.connect(endpoint, { timeout: 15000 }); }
  catch (e) { broken('connect failed: ' + first(e)); }
  if (what === 'page') {
    const srv = await serve(p.base + 5, (q, r) => r.end('<title>lane ok</title>'));
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${p.base + 5}/`, { timeout: 15000 });
    const title = await page.title();
    srv.close();
    say(title);
    await browser.close();
    process.exit(title === 'lane ok' ? 0 : 1);
  } else if (what === 'external') {
    const page = await browser.newPage();
    try { await page.goto('https://example.com', { timeout: 8000 }); say('REACHED'); process.exit(0); }
    catch (e) { const c = netCode(e); if (NET_REFUSED.has(c)) refused(c); broken(first(e)); }
  } else if (what === 'file') {
    if (!p.dotfile) broken('the driver found no non-empty dotfile');
    const tab = await browser.newPage();
    try {
      await tab.goto('file://' + p.dotfile, { timeout: 5000 });
      const length = await tab.evaluate(() => (document.body ? document.body.innerText.length : 0));
      if (length > 0) { say('readable (' + length + ' characters)'); process.exit(0); }
      broken('the page loaded but showed nothing: not proven');
    } catch (e) {
      if (netCode(e) === 'ERR_ACCESS_DENIED') refused('ERR_ACCESS_DENIED');
      broken(first(e));
    }
  } else if (what === 'canary') {
    const page = await browser.newPage();
    try { await page.goto(`http://127.0.0.1:${p.canary_port}/`, { timeout: 5000 }); say('answered'); process.exit(0); }
    catch (e) {
      const c = netCode(e);
      if (c === 'ERR_INVALID_HTTP_RESPONSE' || c === 'ERR_EMPTY_RESPONSE') { say('answered (' + c + ')'); process.exit(0); }
      if (NET_REFUSED.has(c)) refused(c);
      broken(first(e));
    }
  } else if (what === 'write') {
    const names = { control: p.write_probe_control, home: p.write_probe };
    const srv = await serve(p.base + 6, (q, r) => {
      const m = /^\/f\/([A-Za-z0-9._-]+)$/.exec(q.url);
      if (m) { r.setHeader('Content-Disposition', `attachment; filename="${m[1]}"`); r.end('x\n'); }
      else r.end(`<a id="c" href="/f/${names.control}" download>c</a><a id="h" href="/f/${names.home}" download>h</a>`);
    });
    const cdp = await browser.newBrowserCDPSession();
    const events = [];
    cdp.on('Browser.downloadWillBegin', e => events.push({ k: 'begin' }));
    cdp.on('Browser.downloadProgress', e => events.push({ k: 'progress', s: e.state }));
    const { browserContextIds } = await cdp.send('Target.getBrowserContexts');
    const result = {};
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${p.base + 6}/`, { timeout: 15000 });
    for (const [label, dir, link] of [['control', p.control_dir, '#c'], ['home', p.home, '#h']]) {
      let set = 0;
      for (const id of [undefined, ...browserContextIds]) {
        try { await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: dir, eventsEnabled: true, browserContextId: id }); set++; }
        catch (e) { /* counted by `set` */ }
      }
      const before = events.length;
      await page.click(link).catch(() => {});
      await new Promise(resolve => setTimeout(resolve, 4000));
      const mine = events.slice(before);
      result[label] = { set, began: mine.some(e => e.k === 'begin'), states: [...new Set(mine.filter(e => e.k === 'progress').map(e => e.s))] };
    }
    srv.close();
    say(JSON.stringify(result));
    await browser.close();
    process.exit(0);
  } else if (what === 'getusermedia') {
    const srv = await serve(p.base + 7, (q, r) => r.end('<title>media</title>'));
    const context = await browser.newContext({ permissions: ['camera', 'microphone'] });
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${p.base + 7}/`, { timeout: 15000 });
    const outcome = await page.evaluate(() => {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return { missing: true };
      return navigator.mediaDevices.getUserMedia({ audio: true, video: true })
        .then(stream => { stream.getTracks().forEach(t => t.stop()); return { granted: true }; }, e => ({ rejected: e.name }));
    });
    srv.close();
    if (outcome.granted) { say('granted'); process.exit(0); }
    if (outcome.rejected) refused(outcome.rejected);
    broken('navigator.mediaDevices is missing in this page');
  }
  broken('unknown probe ' + what);
})().catch(e => { say('broken: ' + e); process.exit(2); });
