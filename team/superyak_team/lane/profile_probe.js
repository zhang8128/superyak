// Browser-lane self-check (lane.self_check): run directly under the broker's profile, as code that took over the
// browser would run: `sandbox-exec -p <profile> <node> -e <this file's text> <probe>`. Exit 0 means the action
// SUCCEEDED. Every probe but the positive controls (lane_port, write_own_folder, exec_node) must fail. Each probe acts
// on the exact target lane.self_check found outside the sandbox (PROBE_* variables), so a refusal can't be a missing
// file. It never prints a file's contents and never creates an rc file; lane.self_check removes anything a probe
// managed to create. Adapted from team/scripts/lane_profile_probe.js (spike 5).
const fs = require('fs'), net = require('net'), path = require('path'), { execFileSync } = require('child_process');
const home = process.env.HOME, probe = process.argv[1], marker = 'superyak-lane-probe';
const run = (file, args) => execFileSync(file, args, { stdio: 'pipe', timeout: 8000 });
const connect = (port, host) => new Promise((ok, fail) => {
  const s = net.connect(port, host).on('connect', () => { s.destroy(); ok(); }).on('error', fail);
  s.setTimeout(5000, () => { s.destroy(); fail(new Error('timeout')); });
});
const probes = {
  exec_osascript: () => run('/usr/bin/osascript', ['-e', 'return 1']),
  exec_launchctl: () => run('/bin/launchctl', ['list']),
  exec_security: () => run('/usr/bin/security', ['list-keychains']),
  exec_pbpaste: () => run('/usr/bin/pbpaste', []),
  exec_open_calculator: () => run('/usr/bin/open', ['-a', 'Calculator']),
  exec_curl: () => run('/usr/bin/curl', ['-sSf', '--max-time', '5', '-o', '/dev/null', 'https://example.com']),
  net_domain: () => fetch('https://example.com', { signal: AbortSignal.timeout(8000) }),
  net_ip: () => connect(80, '1.1.1.1'),
  net_canary: () => connect(+process.env.PROBE_CANARY_PORT, '127.0.0.1'),
  lane_port: () => connect(+process.env.PROBE_LANE_PORT, '127.0.0.1'),
  read_dotfile: () => fs.readFileSync(process.env.PROBE_DOTFILE),
  read_claude_tmp: () => fs.readdirSync(process.env.PROBE_CLAUDE_TMP),
  read_user_temp: () => fs.readdirSync(process.env.PROBE_USER_TEMP),
  write_home: () => fs.writeFileSync(path.join(home, marker + '.txt'), 'x'),
  write_launchagents: () => fs.writeFileSync(path.join(process.env.PROBE_LAUNCHAGENTS, marker + '.plist'), 'x'),
  // Opens the EXISTING rc file for writing ('r+' never creates) and closes it without writing a byte.
  open_rc_for_write: () => fs.closeSync(fs.openSync(process.env.PROBE_RC, 'r+')),
  write_users_shared: () => fs.writeFileSync(path.join(process.env.PROBE_USERS_SHARED, marker), 'x'),
  write_own_folder: () => fs.writeFileSync(path.join(process.env.TMPDIR, marker), 'x'),
  // Starting node itself must work (fork, then exec of the one allowed binary): without it, every exec_* probe above
  // would be refused for the wrong reason.
  exec_node: () => run(process.execPath, ['-e', '0']),
};
(async () => {
  try { await probes[probe](); console.log('succeeded'); process.exit(0); }
  catch (e) { console.log('refused: ' + String(e.code || e.message || e).split('\n')[0].slice(0, 120)); process.exit(1); }
})();
