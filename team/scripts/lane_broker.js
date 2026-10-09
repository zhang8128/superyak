// Browser-lane spike 4, the broker: started by the driver OUTSIDE the worker's sandbox (optionally under its own
// sandbox-exec profile), it runs a Playwright browser server on loopback and prints its endpoint as one line.
// The endpoint's path is a secret from the driver, so only the lane that was given it can drive the browser.
// It stops when the driver closes its stdin.
const { chromium } = require(process.env.SPIKE_PLAYWRIGHT);
(async () => {
  const server = await chromium.launchServer({
    channel: process.env.SPIKE_CHANNEL || 'chrome', headless: true, host: '127.0.0.1', port: Number(process.env.SPIKE_BROKER_PORT || 0),
    wsPath: '/' + process.env.SPIKE_BROKER_SECRET, chromiumSandbox: process.env.SPIKE_BROKER_CHROME_SANDBOX === 'on',
    args: process.env.SPIKE_CHROME_DEBUG ? ['--enable-logging=stderr', '--v=1'] : [],
  });
  console.log('ENDPOINT ' + server.wsEndpoint());
  process.stdin.on('end', () => server.close().then(() => process.exit(0)));
  process.stdin.resume();
})().catch(e => {  // the whole error (with the browser's own log) to stderr, which the driver keeps; one line to stdout
  console.error(String(e && e.stack || e));
  console.log('ERROR ' + String(e).split('\n')[0].slice(0, 300));
  process.exit(1);
});
