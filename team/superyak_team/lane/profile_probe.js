// Browser-lane self-check (lane.self_check): run directly under the broker's profile, as code that took over the
// browser would run: `sandbox-exec -p <profile> <node> -e <this file's text> <probe>`. Exit 0 means the action
// SUCCEEDED. Every probe but the positive controls (lane_port, write_own_folder, exec_node) must fail. Each probe acts
// on the exact target lane.self_check found outside the sandbox (PROBE_* variables), so a refusal can't be a missing
// file. Exit codes: 0 the action succeeded, 1 it was refused (stdout `refused: <code> ...`), 2 the probe could not
// run (unknown probe, missing or invalid input: stdout `broken: ...`), which lane.judge_probe never reads as a
// refusal. It never prints a file's contents and never creates an rc file; lane.self_check removes anything a probe
// managed to create. Adapted from team/scripts/lane_profile_probe.js (spike 5).
const fs = require('fs'), net = require('net'), path = require('path'), { execFileSync } = require('child_process');
const probe = process.argv[1], marker = 'superyak-lane-probe';
class Usage extends Error {}
const need = (name) => { const v = process.env[name]; if (!v) throw new Usage('missing ' + name); return v; };
const needPort = (name) => {
  const v = need(name);
  if (!/^[0-9]+$/.test(v) || +v < 1 || +v > 65535) throw new Usage('invalid ' + name);
  return +v;
};
const run = (file, args) => execFileSync(file, args, { stdio: 'pipe', timeout: 8000 });
const connect = (port, host) => new Promise((ok, fail) => {
  const s = net.connect(port, host).on('connect', () => { s.destroy(); ok(); }).on('error', fail);
  s.setTimeout(5000, () => { s.destroy(); fail(Object.assign(new Error('timeout'), { code: 'ETIMEDOUT' })); });
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
  net_canary: () => connect(needPort('PROBE_CANARY_PORT'), '127.0.0.1'),
  lane_port: () => connect(needPort('PROBE_LANE_PORT'), '127.0.0.1'),
  read_dotfile: () => fs.readFileSync(need('PROBE_DOTFILE')),
  read_claude_tmp: () => fs.readdirSync(need('PROBE_CLAUDE_TMP')),
  read_user_temp: () => fs.readdirSync(need('PROBE_USER_TEMP')),
  write_home: () => fs.writeFileSync(path.join(need('HOME'), marker + '.txt'), 'x'),
  // The classic bypass of path rules: a hard link to the dotfile inside the lane's own folder. Making the link is the
  // success (other same-uid sandboxes can write the lane, so the dotfile would be readable and writable through it),
  // whatever a read through it does; the link is always removed.
  link_dotfile: () => {
    const link = path.join(need('TMPDIR'), marker + '-link');
    try { fs.linkSync(need('PROBE_DOTFILE'), link); } finally { fs.rmSync(link, { force: true }); }
  },
  write_launchagents: () => fs.writeFileSync(path.join(need('PROBE_LAUNCHAGENTS'), marker + '.plist'), 'x'),
  // Opens the EXISTING rc file for writing ('r+' never creates) and closes it without writing a byte.
  open_rc_for_write: () => fs.closeSync(fs.openSync(need('PROBE_RC'), 'r+')),
  write_users_shared: () => fs.writeFileSync(path.join(need('PROBE_USERS_SHARED'), marker), 'x'),
  write_own_folder: () => fs.writeFileSync(path.join(need('TMPDIR'), marker), 'x'),
  // Starting node itself must work (fork, then exec of the one allowed binary): without it, every exec_* probe above
  // would be refused for the wrong reason.
  exec_node: () => run(process.execPath, ['-e', '0']),
};
// The error's code (a failed fetch keeps it in `cause`); `nocode` when it has none, so judge_probe can't take it for EPERM.
const codeOf = (e) => String(e.code || (e.cause && e.cause.code) || 'nocode');
(async () => {
  try {
    if (!Object.prototype.hasOwnProperty.call(probes, probe)) throw new Usage('unknown probe');
    await probes[probe]();
    console.log('succeeded');
    process.exit(0);
  } catch (e) {
    if (e instanceof Usage) { console.log('broken: ' + e.message); process.exit(2); }
    console.log('refused: ' + codeOf(e) + ' (' + String(e.message || e).split('\n')[0].slice(0, 100) + ')');
    process.exit(1);
  }
})();
