// Browser-lane acceptance, step 3, run INSIDE a browser worker by worker_probes.py: drive the lane's browser through
// the broker and test one thing (argv[2]); argv[3] is params.json's text. Exit 0 means the action SUCCEEDED:
//   page          a page served on a lane port loads (must succeed)
//   wrongsecret   connect without the endpoint's secret path (must be refused)
//   external      a public page loads (must be blocked)
//   file          a dotfile in the home folder opens as file:// (must be blocked; never prints its contents)
//   canary        a server on a port outside this lane's block answers (must be blocked)
//   write         CDP asks the browser to save a download into the home folder (the driver checks for the file)
//   getusermedia  a page granted camera and microphone gets a stream (must fail; the row records the error's name,
//                 and the driver's sandbox_check rows show the camera and microphone services denied)
//   exposenetwork for information only (spec, build order 0): with Playwright's exposeNetwork '<loopback>', does the
//                 browser reach a port outside this lane through the connection itself? If it does, a later revision
//                 could close the broker's localhost access completely.
// It reads the endpoint from PW_TEST_CONNECT_WS_ENDPOINT, as Playwright Test does, and every line it prints goes
// through redact(): Playwright's errors quote the endpoint, secret and all.
const { chromium } = require(require.resolve('playwright-core', { paths: [process.cwd()] }));
const what = process.argv[2], p = JSON.parse(process.argv[3]);
const endpoint = process.env.PW_TEST_CONNECT_WS_ENDPOINT;
const secret = new URL(endpoint).pathname;
const redact = text => String(text).split(secret).join('/<secret>').replace(/\x1b\[[0-9;]*m/g, '');
const say = text => console.log(redact(text).replace(/\s+/g, ' ').slice(0, 240));
const serve = (port, handler) => new Promise(resolve => {
  const srv = require('http').createServer(handler).listen(port, '127.0.0.1', () => resolve(srv));
});
(async () => {
  if (what === 'wrongsecret') {
    const url = new URL(endpoint);
    url.pathname = '/';
    try { const b = await chromium.connect(url.toString(), { timeout: 8000 }); await b.close(); say('connected'); process.exit(0); }
    catch (e) { say('refused: ' + String(e).split('\n')[0]); process.exit(1); }
  }
  if (what === 'exposenetwork') {
    const tunneled = await chromium.connect(endpoint, { timeout: 15000, exposeNetwork: '<loopback>' });
    const page = await tunneled.newPage();
    let reached = 1, said = '';
    try { await page.goto(`http://127.0.0.1:${p.canary_port}/`, { timeout: 5000 }); reached = 0; said = 'reached through the connection'; }
    catch (e) { said = String(e).split('\n')[0]; }
    say(said);
    await tunneled.close();
    process.exit(reached);
  }
  const browser = await chromium.connect(endpoint, { timeout: 15000 });
  let code = 1, note = '';
  if (what === 'page') {
    const srv = await serve(p.base + 5, (q, r) => r.end('<title>lane ok</title>'));
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${p.base + 5}/`, { timeout: 15000 });
    note = await page.title();
    code = note === 'lane ok' ? 0 : 1;
    srv.close();
  } else if (what === 'external') {
    const page = await browser.newPage();
    try { await page.goto('https://example.com', { timeout: 8000 }); code = 0; note = 'REACHED'; } catch (e) { note = String(e).split('\n')[0]; }
  } else if (what === 'file') {
    note = 'none readable';
    for (const f of ['.zshrc', '.bashrc', '.profile', '.gitconfig']) {
      const tab = await browser.newPage();
      try {
        await tab.goto('file://' + require('path').join(require('os').homedir(), f), { timeout: 5000 });
        if ((await tab.evaluate(() => (document.body ? document.body.innerText.length : 0))) > 0) { code = 0; note = 'readable: ' + f; break; }
      } catch (e) { note = 'none readable (last: ' + String(e).split('\n')[0] + ')'; }
      finally { await tab.close(); }
    }
  } else if (what === 'canary') {
    const page = await browser.newPage();
    try { await page.goto(`http://127.0.0.1:${p.canary_port}/`, { timeout: 5000 }); code = 0; note = 'answered'; }
    catch (e) { note = String(e).split('\n')[0]; code = /ERR_INVALID_HTTP_RESPONSE|ERR_EMPTY_RESPONSE/.test(note) ? 0 : 1; }
  } else if (what === 'write') {
    const srv = await serve(p.base + 6, (q, r) => {
      if (q.url === '/f') { r.setHeader('Content-Disposition', `attachment; filename="${p.write_probe}"`); r.end('x\n'); }
      else r.end('<a id="f" href="/f">f</a>');
    });
    const cdp = await browser.newBrowserCDPSession();
    const { browserContextIds } = await cdp.send('Target.getBrowserContexts');
    for (const id of [undefined, ...browserContextIds]) {
      try { await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: require('os').homedir(), browserContextId: id }); note += 'set '; }
      catch (e) { note += 'refused '; }
    }
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${p.base + 6}/`, { timeout: 15000 });
    await page.click('#f').catch(() => {});
    await new Promise(resolve => setTimeout(resolve, 4000));
    srv.close();
    code = 1;                                    // the driver decides, by looking for the file
  } else if (what === 'getusermedia') {
    const srv = await serve(p.base + 7, (q, r) => r.end('<title>media</title>'));
    const context = await browser.newContext({ permissions: ['camera', 'microphone'] });
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${p.base + 7}/`, { timeout: 15000 });
    note = await page.evaluate(() => navigator.mediaDevices.getUserMedia({ audio: true, video: true })
      .then(stream => { stream.getTracks().forEach(t => t.stop()); return 'granted'; }, e => 'refused: ' + e.name));
    code = note === 'granted' ? 0 : 1;
    srv.close();
  }
  say(note);
  await browser.close();
  process.exit(code);
})().catch(e => { say(e); process.exit(1); });
