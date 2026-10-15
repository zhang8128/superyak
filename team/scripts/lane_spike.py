#!/usr/bin/env python3
"""Browser-lane spike: what can a team-mode worker do inside the candidate lane sandbox?

It runs ONE real `claude -p` with a worker's sandbox settings plus the lane's network block, and has it run
lane_probe.sh once. The probes, not the model, produce the results. On macOS it then lists the sandbox's denials
(which Mach services Chrome wanted, for example). Run it from the repository root on the machine that runs team mode:

    python3 team/scripts/lane_spike.py --playwright ~/path/to/bricks/node_modules/playwright --socket "$SSH_AUTH_SOCK"

Spike 4 adds a browser broker: with --broker, the driver starts `playwright launchServer` OUTSIDE the worker's sandbox
(plain, or under its own sandbox-exec profile), and the lane drives that browser over loopback instead of launching one:

    python3 team/scripts/lane_spike.py --playwright <bricks>/node_modules/playwright --broker plain --broker profile

Nothing it creates outlives it (the lane folder is removed unless --keep). It never reads or prints any key.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from superyak_team import workers  # noqa: E402  (the real worker settings, so the spike tests what workers get)

MIN_CLAUDE = (2, 1, 285)
DROP_ENV = ('SSH_AUTH_SOCK', 'GPG_AGENT_INFO', 'DOCKER_HOST')


def private_parent():
    """/tmp/sy-lane-<uid>: created 0700 by this user, refused if it is a symlink or anyone else's."""
    parent = Path(f'/tmp/sy-lane-{os.getuid()}')
    try:
        parent.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = os.lstat(parent)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        sys.exit(f'refusing {parent}: not a private directory owned by you (mode 0700, no symlink)')
    return parent


def fresh_lane(parent, name):
    lane = parent / hashlib.sha256(name.encode()).hexdigest()[:10]
    if os.path.lexists(lane):
        if not shutil.rmtree.avoids_symlink_attacks:
            sys.exit('this platform cannot remove a folder safely; remove ' + str(lane) + ' by hand')
        shutil.rmtree(lane)
    for sub in ('tmp', 'npm-cache', 'work'):
        (lane / sub).mkdir(parents=True, mode=0o700)
    os.chmod(lane, 0o700)
    return lane


def canary():
    """A loopback service started OUTSIDE the sandbox: can a lane worker reach other people's localhost services?"""
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(5)

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
                conn.sendall(b'canary-reachable\n')
                conn.close()
            except OSError:
                return
    threading.Thread(target=serve, daemon=True).start()
    return srv


def claude_version():
    try:
        out = subprocess.run(['claude', '--version'], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, 'claude not found'
    found = re.search(r'(\d+)\.(\d+)\.(\d+)', out)
    return (tuple(int(x) for x in found.groups()) if found else None), out.strip()


def user_allowlists():
    """Domains a user-level settings file would merge into the lane's allowlist (the reviewer's finding 3)."""
    found = []
    for path in (Path.home() / '.claude' / 'settings.json', Path.home() / '.claude' / 'settings.local.json'):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        domains = ((data.get('sandbox') or {}).get('network') or {}).get('allowedDomains') or []
        fetches = [r for r in ((data.get('permissions') or {}).get('allow') or []) if str(r).startswith('WebFetch(domain:')]
        if domains or fetches:
            found.append(f'{path}: allowedDomains={domains} WebFetch rules={fetches}')
    return found


def lane_settings(work, lane, playwright, variant='base', allow_read=()):
    settings = workers.claude_sandbox_settings(work, 'build', repo=work)
    sandbox, fs = settings['sandbox'], settings['sandbox']['filesystem']
    # Claude Code points a sandboxed command's TMPDIR at <CLAUDE_CODE_TMPDIR>/claude-<uid> (seen in the Linux dry run);
    # allowUnixSockets is a subpath rule, so the lane's tmp covers it.
    sandbox['network'] = {'allowedDomains': [], 'strictAllowlist': True, 'allowLocalBinding': True,
                          'allowUnixSockets': [str(lane / 'tmp')]}
    fs['allowWrite'] = sorted(set(fs['allowWrite']) | {str(lane)})
    fs['allowRead'] = sorted(set(fs['allowRead']) | {str(lane)} | ({str(Path(playwright).resolve().parent)} if playwright else set())
                             | {str(Path(p).expanduser().resolve()) for p in allow_read})
    if variant == 'mach-star':  # diagnosis only: if Chrome starts with every Mach service allowed, the wall is a Mach lookup
        sandbox['network']['allowMachLookup'] = ['*']
    return settings


WRITE_PROBE = 'superyak-lane-spike-probe.txt'  # what the broker's write probe tries to leave in the home folder


def sb_path(path):
    path = os.path.realpath(os.path.expanduser(str(path)))
    if '"' in path or '\\' in path:
        sys.exit(f'refusing a path a sandbox profile cannot quote: {path!r}')
    return path


def broker_profile(lane, playwright, allow_read=()):
    """The broker's own Seatbelt profile, which teamd (not Claude Code) would own. Everything Chrome needs from macOS
    stays allowed (Mach, sysctl, preferences: the walls of spikes 2 and 3); what is closed is what a lane must not
    reach: the network beyond loopback (DNS included) and the home folder's contents, apart from the few folders a
    browser and Playwright read. Writes go to the lane only."""
    home, lane = sb_path(Path.home()), sb_path(lane)
    node = Path(shutil.which('node') or '/usr/local/bin/node').resolve().parents[1]
    reads = [Path(playwright).resolve().parent, node, '~/Library/Caches/ms-playwright', '~/Library/Fonts', *allow_read]
    rules = ' '.join(f'(subpath "{sb_path(r)}")' for r in reads)
    return '\n'.join([
        '(version 1)',
        '(allow default)',
        '(deny network-outbound)',
        '(allow network-outbound (remote ip "localhost:*"))',  # no Unix-socket connects either: mDNSResponder (DNS) stays shut
        f'(deny file-read-data file-write* (subpath "{home}"))',
        f'(allow file-read-data {rules} (literal "{home}/Library/Preferences/.GlobalPreferences.plist"))',
        f'(allow file-read-data file-write* (subpath "{lane}"))',
        ''])


LANE_PORTS = 8  # the spike's block: 0 page, 1 write probe, 2 the driver's positive-control listener, last the broker
PROFILE_PROBES = ['exec_osascript', 'exec_launchctl', 'exec_security', 'exec_pbpaste', 'exec_curl', 'net_domain', 'net_ip',
                  'net_canary', 'read_dotfile', 'write_home', 'write_launchagents', 'open_rc_for_write', 'read_claude_tmp',
                  'write_users_shared', 'read_user_temp']
POSITIVE_PROBES = ['lane_port', 'write_own_folder']
PROBE_LEFTOVERS = [Path.home() / 'superyak-lane-spike-probe.txt', Path.home() / 'Library/LaunchAgents/superyak-lane-spike-probe.plist',
                   Path('/Users/Shared/superyak-lane-spike-probe')]


def port_block():
    """A free block of LANE_PORTS loopback ports below macOS's ephemeral range (49152+), as teamd's pool would give."""
    for base in range(41000 + 8 * (os.getpid() % 900), 49000, 8):
        socks = []
        try:
            for k in range(LANE_PORTS):
                s = socket.socket()
                s.bind(('127.0.0.1', base + k))
                socks.append(s)
            return base
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    sys.exit('no free block of loopback ports in 41000-48999')


def chrome_bundle(channel):
    return (Path('/Applications/Google Chrome.app') if channel == 'chrome'
            else Path.home() / 'Library/Caches/ms-playwright')


def deny_profile(folder, playwright, channel, base):
    """Spike 5: the broker's profile denies by default. The driver adds only what this broker is (its node, its
    Playwright, Chrome's bundle, its own folder, the lane's ports, its listening port); everything else Chrome needs
    comes from lane_broker_allow.sb, one reviewed rule at a time."""
    node_bin = Path(shutil.which('node') or '/usr/local/bin/node').resolve()
    node = node_bin.parents[1]  # read only: node's libraries. Exec names the binary itself, never a prefix like /usr.
    pw, app, b = sb_path(Path(playwright).resolve().parent), sb_path(chrome_bundle(channel)), sb_path(folder)
    lane_ports = ' '.join(f'(remote ip "localhost:{base + k}")' for k in range(LANE_PORTS - 1))
    # node resolves every path it is given (realpath lstats each ancestor: /tmp, /private, /Users, ...), so the broker
    # may read the METADATA of exactly the ancestor directories of what it is already allowed: literals only, no
    # listing (readdir needs file-read-data), no other file.
    ancestors = sorted({str(parent) for p in (node_bin, Path(playwright).resolve(), chrome_bundle(channel), folder)
                        for q in (Path(p), Path(os.path.realpath(p))) for parent in q.parents})
    ancestry = ' '.join(f'(literal "{sb_path(Path(a))}")' for a in ancestors) + ' (literal "/tmp")'
    return '\n'.join([
        '(version 1)',
        '(deny default)',
        '(import "system.sb")',
        '; generated by the driver: what this broker is',
        f'(allow file-read-metadata {ancestry})',
        '(allow process-fork)',
        f'(allow process-exec (literal "{sb_path(node_bin)}") (subpath "{app}"))',
        f'(allow file-read* (subpath "{sb_path(node)}") (subpath "{pw}") (subpath "{app}") (subpath "{b}"))',
        f'(allow file-write* (subpath "{b}"))',
        f'(allow network-bind network-inbound (local ip "localhost:{base + LANE_PORTS - 1}"))',
        f'(allow network-outbound {lane_ports})',
        '; lane_broker_allow.sb',
        (HERE / 'lane_broker_allow.sb').read_text(),
        ''])


def profile_probes(folder, env, canary_port, base):
    """Run every spike-5 probe directly under the broker's profile, as code that took over the browser would. A probe
    that succeeds is a FAIL (except the positive controls); anything a probe managed to create is removed."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', base + 2))
    listener.listen(5)
    try:
        user_temp = subprocess.run(['getconf', 'DARWIN_USER_TEMP_DIR'], capture_output=True, text=True).stdout.strip()
    except OSError:
        user_temp = ''
    penv = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'TMPDIR': str(folder), 'SPIKE_HOME': str(Path.home()),
            'SPIKE_CANARY_PORT': str(canary_port), 'SPIKE_LANE_LISTENER': str(base + 2),
            'SPIKE_CLAUDE_TMP': f'/private/tmp/claude-{os.getuid()}', 'SPIKE_USER_TEMP': user_temp or '/nonexistent'}
    node = str(Path(shutil.which('node') or '/usr/local/bin/node').resolve())
    shutil.copy(HERE / 'lane_profile_probe.js', folder / 'lane_profile_probe.js')  # the profile can't read the repo
    rows = []
    try:
        for name in PROFILE_PROBES + POSITIVE_PROBES:
            r = subprocess.run(['sandbox-exec', '-f', str(folder / 'broker.sb'), node, str(folder / 'lane_profile_probe.js'), name],
                               env=penv, capture_output=True, text=True, timeout=60)
            ok = r.returncode == 0
            verdict = ('PASS' if ok else 'FAIL') if name in POSITIVE_PROBES else ('FAIL' if ok else 'PASS')
            rows.append(f'{verdict:5} {"profile:" + name:32} exit={r.returncode:<3} {(r.stdout or r.stderr).strip()[:140]}')
    finally:
        listener.close()
        for leftover in PROBE_LEFTOVERS:
            if leftover.exists():
                leftover.unlink()
                rows.append(f'NOTE  removed {leftover}')
    return rows


def start_broker(mode, lane, work, playwright, channel, allow_read, env, base=None):
    """Start the broker; returns (process, endpoint or None, a note, its folder).
    mode: plain | profile | profile-chrome-sandbox | deny (spike 5: deny-default, Chrome's sandbox off)."""
    # A short folder: Chrome's singleton socket lives under it, and a Unix socket path must fit in 104 bytes on macOS.
    folder = lane / ('b' + hashlib.sha256(f'{mode} {channel}'.encode()).hexdigest()[:4])
    folder.mkdir(mode=0o700)
    secret = secrets.token_urlsafe(24)
    benv = {k: v for k, v in env.items() if not k.startswith('SPIKE_')}
    if mode == 'deny':
        benv['SPIKE_CHROME_DEBUG'] = '1'  # spike 5 grows its allow list from what Chrome itself logs, too
    benv.update(TMPDIR=str(folder), MAC_CHROMIUM_TMPDIR=str(folder), SPIKE_PLAYWRIGHT=str(Path(playwright).resolve()),
                SPIKE_CHANNEL=channel, SPIKE_BROKER_SECRET=secret,
                SPIKE_BROKER_CHROME_SANDBOX='off' if mode in ('profile', 'deny') else 'on')
    if base is not None:
        benv['SPIKE_BROKER_PORT'] = str(base + LANE_PORTS - 1)
    # The script runs from the broker's own folder: a deny-default profile reads nothing else of the lane or the repo.
    shutil.copy(work / 'lane_broker.js', folder / 'lane_broker.js')
    # The resolved binary, as the profile probes use: a bare 'node' makes sandbox-exec search PATH, which a
    # deny-default profile refuses (spike 5 on the Mac: execvp() of 'node' failed).
    cmd = [str(Path(shutil.which('node') or '/usr/local/bin/node').resolve()), str(folder / 'lane_broker.js')]
    if mode != 'plain':
        if not shutil.which('sandbox-exec'):
            return None, None, 'sandbox-exec not found (macOS only)', folder
        (folder / 'broker.sb').write_text(deny_profile(folder, playwright, channel, base) if mode == 'deny'
                                          else broker_profile(lane, playwright, allow_read))
        cmd = ['sandbox-exec', '-f', str(folder / 'broker.sb')] + cmd
    proc = subprocess.Popen(cmd, cwd=folder, env=benv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=open(folder / 'stderr.log', 'w'), text=True)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout], daemon=True).start()
    try:
        first = lines.get(timeout=90).strip()
    except queue.Empty:
        first = 'ERROR no endpoint within 90 s'
    if first.startswith('ENDPOINT '):
        return proc, first.split(' ', 1)[1], 'started', folder
    stop_broker(proc)
    tail = [l for l in (folder / 'stderr.log').read_text(errors='replace').splitlines() if not l.lstrip().startswith('at ')][-30:]
    return None, None, first[:600] + ('\n' + '\n'.join(l[:300] for l in tail) if tail else ''), folder


def stop_broker(proc):
    if proc is None:
        return
    try:
        proc.stdin.close()
        proc.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        proc.wait()


def denial_stream():
    """Sandbox denials as they happen (macOS): `log show` after the fact caught nothing in spikes 1 and 2."""
    if platform.system() != 'Darwin':
        return None
    try:
        return subprocess.Popen(['log', 'stream', '--style', 'compact', '--predicate',
                                 'eventMessage CONTAINS "Sandbox:" OR subsystem == "com.apple.sandbox.reporting"'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None


BROKER_PROCESSES = ('node', 'Google Chrome', 'Google Chrome Helper', 'Google Chrome for Testing', 'chrome-headless-shell', 'chrome_crashpad_handler')


def stop_stream(stream, processes=None):
    """Unique denials as 'process: operation argument'. With `processes`, only those processes' denials: the stream
    sees every sandbox on the Mac, and an allow list must never be grown from another program's denials."""
    if stream is None:
        return ['(denials are streamed on macOS only)']
    stream.terminate()
    try:
        out, _ = stream.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        stream.kill()
        out, _ = stream.communicate()
    seen = []
    for line in out.splitlines():
        found = re.search(r'Sandbox: (.+?)\(\d+\) deny\(\d+\) (\S+) ?(.*)$', line)
        if not found:
            continue
        process, operation, argument = found.group(1).strip(), found.group(2), found.group(3)
        if processes and not process.startswith(processes):
            continue
        key = f'{process}: {operation} {argument[:160]}'
        if key not in seen:
            seen.append(key)
    return seen


def listeners():
    """Every TCP listener on this machine, seen from outside the sandbox: on macOS a lane worker can reach each one
    on localhost (allowLocalBinding), so each needs a decision (the reviewer's finding 2)."""
    try:
        out = subprocess.run(['lsof', '-nP', '-iTCP', '-sTCP:LISTEN'], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired) as error:
        return [f'(lsof failed: {error})']
    rows = sorted({' '.join(line.split()[:1] + line.split()[8:9]) for line in out.splitlines()[1:]})
    return rows or ['(no TCP listeners)']


def judge(expect, code):
    if expect == 'info':
        return 'info'
    return 'PASS' if (code == '0') == (expect == 'ok') else 'FAIL'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--playwright', help='path to a playwright (or playwright-core) package folder, e.g. <repo>/node_modules/playwright')
    parser.add_argument('--socket', action='append', default=[], help='a Unix socket the lane must NOT reach (repeatable)')
    parser.add_argument('--model', default='haiku')
    parser.add_argument('--keep', action='store_true', help='keep the lane folder for inspection')
    parser.add_argument('--baseline', action='store_true', help='also run the probes outside the sandbox, for comparison')
    parser.add_argument('--variant', action='append', choices=['base', 'mach-star'],
                        help='sandbox variants that launch Chrome inside the lane (default: base, or none with --broker)')
    parser.add_argument('--broker', action='append', choices=['plain', 'profile', 'profile-chrome-sandbox', 'deny'],
                        help='spike 4: drive a browser started outside the lane (repeatable). plain: no sandbox at all '
                             '(shows what a broker must close); profile: under its own sandbox-exec profile, Chrome sandbox '
                             'off; profile-chrome-sandbox: the same with Chrome\'s own sandbox on; deny: spike 5, a '
                             'deny-default profile (lane_broker_allow.sb) plus probes run directly under it')
    parser.add_argument('--channels', default='chrome', help="browser channels to probe, e.g. 'chrome chromium'")
    parser.add_argument('--allow-read', action='append', default=[], help='an extra folder the lane (and the broker profile) may read, e.g. ~/Library/Caches/ms-playwright')
    args = parser.parse_args()
    if args.broker and not args.playwright:
        sys.exit('--broker needs --playwright')

    version, text = claude_version()
    print(f'claude: {text}', '(older than 2.1.285: repo settings may loosen the sandbox)' if version and version < MIN_CLAUDE else '')
    for warning in user_allowlists():
        print('WARNING user-level allowlist merges into the lane:', warning)

    lane = fresh_lane(private_parent(), f'spike-{os.getpid()}')
    work = lane / 'work'
    for name in ('lane_probe.sh', 'lane_chrome_probe.js', 'lane_broker.js', 'lane_broker_client.js'):
        shutil.copy(HERE / name, work / name)
    srv = canary()
    sockets = [s for s in args.socket + [os.environ.get('SSH_AUTH_SOCK', '')] if s]
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    # MAC_CHROMIUM_TMPDIR: Chromium on macOS makes its singleton socket under the user temp folder (spike 2), not TMPDIR.
    env.update(CLAUDE_CODE_TMPDIR=str(lane / 'tmp'), MAC_CHROMIUM_TMPDIR=str(lane / 'tmp'), npm_config_cache=str(lane / 'npm-cache'),
               SUPERYAK_BROWSER_LANE='1', SPIKE_CANARY_PORT=str(srv.getsockname()[1]), SPIKE_SOCKETS=' '.join(dict.fromkeys(sockets)),
               SPIKE_CHANNELS=args.channels, SPIKE_CHROME_SCRIPT=str(work / 'lane_chrome_probe.js'), SPIKE_LOG=str(work / 'chrome-debug.log'),
               SPIKE_BROKER_SCRIPT=str(work / 'lane_broker_client.js'), SPIKE_HOME=str(Path.home()))
    if args.playwright:
        env['SPIKE_PLAYWRIGHT'] = str(Path(args.playwright).resolve())
    print(f'lane: {lane}')

    if args.baseline:
        print('\n== baseline, outside the sandbox ==')
        print(subprocess.run(['bash', str(work / 'lane_probe.sh')], cwd=work, env=env, capture_output=True, text=True, timeout=600).stdout)

    runs = [(variant, None, None) for variant in (args.variant or ([] if args.broker else ['base']))]
    runs += [('base', broker, channel) for broker in args.broker or [] for channel in args.channels.split()]
    try:
        for variant, broker, channel in runs:
            name = f'broker {broker} [{channel}]' if broker else f'variant {variant}'
            settings = lane_settings(work, lane, args.playwright, variant, args.allow_read)
            (lane / f'settings-{variant}.json').write_text(json.dumps(settings, indent=1))
            run_env, proc = dict(env), None
            run_env['BASH_DEFAULT_TIMEOUT_MS'] = '600000'  # the broker probes outlast Claude Code's 120 s Bash default
            stream = denial_stream()
            if broker:
                home_probe = Path.home() / WRITE_PROBE
                if home_probe.exists():
                    sys.exit(f'{home_probe} exists before the run; remove it and retry')
                base = port_block()
                proc, endpoint, note, folder = start_broker(broker, lane, work, args.playwright, channel, args.allow_read, env, base)
                print(f'\n== {name}: {note.splitlines()[0] if note else ""} ==')
                if endpoint is None:
                    print(note)
                    for line in stop_stream(stream, BROKER_PROCESSES if broker == 'deny' else None)[:80] or ['(no denials captured)']:
                        print(line)
                    continue
                run_env.update(SPIKE_BROKER_WS=endpoint, SPIKE_BROKER_MODE=broker, SPIKE_WRITE_PROBE=WRITE_PROBE,
                               SPIKE_LANE_PORT_BASE=str(base))
            prompt = (f'Run exactly this one Bash command, once: bash {work / "lane_probe.sh"}\n'
                      'Then reply with only its output, unchanged. Do not run anything else.')
            cmd = ['claude', '-p', prompt, '--output-format', 'text', '--model', args.model, '--permission-mode', 'dontAsk',
                   '--settings', str(lane / f'settings-{variant}.json')]
            try:
                output = subprocess.run(cmd, cwd=work, env=run_env, capture_output=True, text=True, timeout=900).stdout
            except subprocess.TimeoutExpired:
                output = '(claude -p timed out)'
            finally:
                stop_broker(proc)
            denials = stop_stream(stream, BROKER_PROCESSES if broker == 'deny' else None)
            print(f'\n== inside the lane, {name} ==')
            rows = [line.split('\t', 3) for line in output.splitlines() if line.count('\t') >= 3]
            for probe_name, expect, code, detail in rows:
                print(f'{judge(expect, code):5} {probe_name:32} exit={code:3} {detail[:160]}')
            if not rows:
                print('(no probe lines: claude did not run the script)\n' + output[-2000:])
            if broker:
                written = home_probe.exists()
                if written:
                    home_probe.unlink()
                print(f'{judge("fail" if broker != "plain" else "info", "0" if written else "1"):5} {"broker_write_home":32} '
                      f'{"the browser wrote into the home folder (removed)" if written else "nothing written into the home folder"}')
                if broker == 'deny':
                    print(f'-- spike 5: probes run directly under the deny-default profile ({folder / "broker.sb"}) --')
                    for row in profile_probes(folder, env, srv.getsockname()[1], base):
                        print(row)
                log = folder / 'stderr.log'
                keep = [l for l in log.read_text(errors='replace').splitlines()
                        if re.search(r'(?i)denied|not permitted|EPERM|EACCES|sandbox|failed|error|fatal', l)]
                print(f'-- broker stderr, relevant lines (first 40 of {len(keep)}) --')
                for line in keep[:40]:
                    print(line[:300])
            for log_channel in args.channels.split():
                log = Path(f'{work / "chrome-debug.log"}.{log_channel}')
                if log.exists():
                    lines = log.read_text(errors='replace').splitlines()
                    keep = [l for l in lines if re.search(r'(?i)singleton|denied|not permitted|EPERM|EACCES|sandbox|failed|error|fatal|mach|socket|lock|check', l)]
                    print(f'\n-- Chrome debug log [{log_channel}], {name}: {len(lines)} lines, {len(keep)} relevant (first 60) --')
                    for line in keep[:60]:
                        print(line[:300])
                    log.unlink()
            limit = 300 if broker == 'deny' else 80  # spike 5 builds its allow list from these
            print(f'\n-- sandbox denials streamed during {name} (unique, first {limit}) --')
            for line in denials[:limit] or ['(none captured)']:
                print(line)
    finally:
        srv.close()
    print('\n== localhost listeners a lane worker could reach on macOS (decide on each) ==')
    for line in listeners():
        print(line)
    if args.keep:
        print(f'\nkept {lane}')
    else:
        shutil.rmtree(lane)


if __name__ == '__main__':
    main()
