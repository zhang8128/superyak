// Superyak browser-lane broker (spike 4's script, docs/superpowers/specs/2026-10-08-browser-lane-design.md). teamd
// runs it OUTSIDE the worker's sandbox, from its own package, never from a file in the lane:
//   sandbox-exec -p <profile> <lane_node> -e <this file's text> <port>
// teamd writes the secret on its stdin's first line, not in its environment, which Chrome inherits. It serves
// Playwright's headless shell (launchServer with no channel) on 127.0.0.1:<port>, the lane's last port, behind the
// secret path, prints "ENDPOINT <ws url>" once, and stops when teamd closes its stdin. If the browser dies, so does
// the broker, and teamd starts a new one at the next turn. Its environment is built from nothing by teamd: the pinned
// Playwright's folder, PLAYWRIGHT_BROWSERS_PATH, PATH, HOME and TMPDIR.
const { chromium } = require(process.env.SUPERYAK_BROKER_PLAYWRIGHT);
let server = null, closing = false, secret = null, buffered = '';
const start = async () => {
  server = await chromium.launchServer({
    headless: true, host: '127.0.0.1', port: Number(process.argv[1]), wsPath: '/' + secret,
    chromiumSandbox: false,  // macOS forbids a second sandbox inside the profile (forbidden-sandbox-reinit)
  });
  server.process().on('exit', () => process.exit(closing ? 0 : 1));
  if (closing) return server.close().then(() => process.exit(0));
  console.log('ENDPOINT ' + server.wsEndpoint());
};
const fail = e => {  // the whole error to stderr (teamd's own folder, never posted); one line to stdout for teamd
  console.error(String(e && e.stack || e));
  console.log('ERROR ' + String(e).split('\n')[0].split(secret || '\0').join('[lane secret]').slice(0, 300));
  process.exit(1);
};
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  if (secret !== null) return;
  buffered += chunk;
  const end = buffered.indexOf('\n');
  if (end < 0) return;
  secret = buffered.slice(0, end).trim();
  start().catch(fail);
});
process.stdin.on('end', () => {
  closing = true;
  if (server) server.close().then(() => process.exit(0));
  else if (secret === null) process.exit(0);
});
process.stdin.resume();
