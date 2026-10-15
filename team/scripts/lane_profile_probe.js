// Browser-lane spike 5: run by the driver directly under the broker's deny-default profile (`sandbox-exec -f
// broker.sb node lane_profile_probe.js <probe>`), as code that took over the browser would run. Exit 0 means the
// action SUCCEEDED. Every probe except the positive controls (lane_port, write_own_folder) must fail. It never
// prints a file's contents; the driver removes anything a probe managed to create.
const fs = require('fs'), net = require('net'), path = require('path'), { execFileSync } = require('child_process');
const home = process.env.SPIKE_HOME, probe = process.argv[2], marker = 'superyak-lane-spike-probe';
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
  exec_curl: () => run('/usr/bin/curl', ['-sSf', '--max-time', '5', '-o', '/dev/null', 'https://example.com']),
  net_domain: () => fetch('https://example.com', { signal: AbortSignal.timeout(8000) }),
  net_ip: () => connect(80, '1.1.1.1'),
  net_canary: () => connect(+process.env.SPIKE_CANARY_PORT, '127.0.0.1'),
  lane_port: () => connect(+process.env.SPIKE_LANE_LISTENER, '127.0.0.1'),
  read_dotfile: () => { for (const f of ['.zshrc', '.bashrc', '.profile', '.gitconfig']) { try { fs.readFileSync(path.join(home, f)); return; } catch (e) {} } throw new Error('none'); },
  write_home: () => fs.writeFileSync(path.join(home, marker + '.txt'), 'x'),
  write_launchagents: () => fs.writeFileSync(path.join(home, 'Library/LaunchAgents', marker + '.plist'), 'x'),
  // Open an EXISTING rc file for writing and close it without writing: never creates a file, never changes one.
  open_rc_for_write: () => { for (const f of ['.zshrc', '.bashrc', '.profile']) { const p = path.join(home, f); if (fs.existsSync(p)) { fs.closeSync(fs.openSync(p, 'r+')); return; } } throw new Error('no rc file to try'); },
  read_claude_tmp: () => fs.readdirSync(process.env.SPIKE_CLAUDE_TMP),
  write_users_shared: () => fs.writeFileSync('/Users/Shared/' + marker, 'x'),
  read_user_temp: () => fs.readdirSync(process.env.SPIKE_USER_TEMP),
  write_own_folder: () => fs.writeFileSync(path.join(process.env.TMPDIR, marker), 'x'),
};
(async () => {
  try { await probes[probe](); console.log('succeeded'); process.exit(0); }
  catch (e) { console.log('refused: ' + String(e.code || e.message || e).split('\n')[0].slice(0, 120)); process.exit(1); }
})();
