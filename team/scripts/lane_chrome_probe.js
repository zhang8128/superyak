// Browser-lane spike: launch Chrome through Playwright inside the lane, load a page from a loopback server,
// and try a public page, which must fail. Argument: "off" or "on" for Chrome's own sandbox.
const { chromium } = require(process.env.SPIKE_PLAYWRIGHT);
(async () => {
  const sandbox = process.argv[2] === 'on';
  const srv = require('http').createServer((q, r) => r.end('<title>lane ok</title>')).listen(0, '127.0.0.1');
  await new Promise(resolve => srv.on('listening', resolve));
  const browser = await chromium.launch({ channel: process.env.SPIKE_CHANNEL || 'chrome', chromiumSandbox: sandbox, headless: true, timeout: 30000 });
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${srv.address().port}/`);
  const title = await page.title();
  let external = 'blocked';
  try { await page.goto('https://example.com', { timeout: 8000 }); external = 'REACHED'; } catch (e) { external = 'blocked'; }
  console.log(JSON.stringify({ title, external }));
  await browser.close();
  srv.close();
  process.exit(title === 'lane ok' && external === 'blocked' ? 0 : 3);
})().catch(e => { console.log(String(e).slice(0, 240)); process.exit(1); });
