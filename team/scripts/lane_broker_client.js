// Browser-lane spike 4, run INSIDE the lane: connect to the broker's browser and test one thing (argv[2]).
//   page      a page served by the worker on loopback loads (exit 0 = it did)
//   external  a public page loads (exit 0 = it did; the broker must stop this)
//   file      a dotfile in the home folder opens as file:// (exit 0 = one did; never prints its contents)
//   canary    another program's loopback service answers (exit 0 = it did)
//   write     ask the browser, through CDP, to save a download into the home folder (the driver checks for the file)
//   wrongsecret  connect without the endpoint's secret path (exit 0 = it connected; the broker must refuse)
// It reads the endpoint from SPIKE_BROKER_WS and never prints it.
const { chromium } = require(process.env.SPIKE_PLAYWRIGHT);
const what = process.argv[2];
// Playwright's errors quote the endpoint, secret path and all: every line printed goes through redact().
const secret = new URL(process.env.SPIKE_BROKER_WS).pathname;
const redact = text => String(text).split(secret).join('/<secret>').replace(/\x1b\[[0-9;]*m/g, '');
const say = text => console.log(redact(text));
// Servers the browser loads take the lane's own ports when the driver gave a block (spike 5's profile allows only those).
const lanePort = k => (process.env.SPIKE_LANE_PORT_BASE ? +process.env.SPIKE_LANE_PORT_BASE + k : 0);
(async () => {
  if (what === 'wrongsecret') {
    const url = new URL(process.env.SPIKE_BROKER_WS);
    url.pathname = '/';
    try { const b = await chromium.connect(url.toString(), { timeout: 8000 }); await b.close(); say('connected'); process.exit(0); }
    catch (e) { say('refused: ' + redact(e).split('\n')[0].slice(0, 100)); process.exit(1); }
  }
  const browser = await chromium.connect(process.env.SPIKE_BROKER_WS, { timeout: 15000 });
  const page = await browser.newPage();
  let code = 1, note = '';
  if (what === 'page') {
    const srv = require('http').createServer((q, r) => r.end('<title>lane ok</title>')).listen(lanePort(0), '127.0.0.1');
    await new Promise(resolve => srv.on('listening', resolve));
    await page.goto(`http://127.0.0.1:${srv.address().port}/`, { timeout: 15000 });
    note = await page.title();
    code = note === 'lane ok' ? 0 : 1;
    srv.close();
  } else if (what === 'external') {
    try { await page.goto('https://example.com', { timeout: 8000 }); code = 0; note = 'REACHED'; } catch (e) { note = String(e).split('\n')[0].slice(0, 120); }
  } else if (what === 'file') {
    // Plain dotfiles only: enough to show the leak, and no key or history is ever loaded into a browser the lane drives.
    note = 'none readable';
    for (const f of ['.zshrc', '.bashrc', '.profile', '.gitconfig']) {
      const tab = await browser.newPage();  // a fresh tab each time: a failed file:// load can leave a tab mid-navigation
      try {
        await tab.goto('file://' + require('path').join(process.env.SPIKE_HOME, f), { timeout: 5000 });
        const size = await tab.evaluate(() => (document.body ? document.body.innerText.length : 0));
        if (size > 0) { code = 0; note = 'readable: ' + f; break; }
      } catch (e) { note = 'none readable (last: ' + String(e).split('\n')[0].slice(0, 100) + ')'; }
      finally { await tab.close(); }
    }
  } else if (what === 'canary') {
    try { await page.goto(`http://127.0.0.1:${process.env.SPIKE_CANARY_PORT}/`, { timeout: 5000 }); code = 0; note = 'answered'; }
    catch (e) { note = String(e).split('\n')[0].slice(0, 120); code = /ERR_INVALID_HTTP_RESPONSE|ERR_EMPTY_RESPONSE/.test(note) ? 0 : 1; }
  } else if (what === 'write') {
    const name = process.env.SPIKE_WRITE_PROBE;
    const srv = require('http').createServer((q, r) => {
      if (q.url === '/f') { r.setHeader('Content-Disposition', `attachment; filename="${name}"`); r.end('lane spike write probe\n'); }
      else r.end('<a id="f" href="/f">f</a>');
    }).listen(lanePort(1), '127.0.0.1');
    await new Promise(resolve => srv.on('listening', resolve));
    const cdp = await browser.newBrowserCDPSession();
    const { browserContextIds } = await cdp.send('Target.getBrowserContexts');
    for (const id of [undefined, ...browserContextIds]) {
      try { await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: process.env.SPIKE_HOME, browserContextId: id }); note += 'set '; }
      catch (e) { note += 'refused(' + String(e).split('\n')[0].slice(0, 60) + ') '; }
    }
    await page.goto(`http://127.0.0.1:${srv.address().port}/`, { timeout: 15000 });
    await page.click('#f').catch(() => {});
    await new Promise(resolve => setTimeout(resolve, 4000));
    srv.close();
    code = 0;
  }
  say(note);
  await browser.close();
  process.exit(code);
})().catch(e => { say(redact(e).replace(/\s+/g, ' ').slice(0, 240)); process.exit(1); });
