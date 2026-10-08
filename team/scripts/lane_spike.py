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


def start_broker(mode, lane, work, playwright, channel, allow_read, env):
    """Start the broker; returns (process, endpoint or None, a note, its folder). mode: plain | profile | profile-chrome-sandbox."""
    # A short folder: Chrome's singleton socket lives under it, and a Unix socket path must fit in 104 bytes on macOS.
    folder = lane / ('b' + hashlib.sha256(f'{mode} {channel}'.encode()).hexdigest()[:4])
    folder.mkdir(mode=0o700)
    secret = secrets.token_urlsafe(24)
    benv = {k: v for k, v in env.items() if not k.startswith('SPIKE_')}
    benv.update(TMPDIR=str(folder), MAC_CHROMIUM_TMPDIR=str(folder), SPIKE_PLAYWRIGHT=str(Path(playwright).resolve()),
                SPIKE_CHANNEL=channel, SPIKE_BROKER_SECRET=secret,
                SPIKE_BROKER_CHROME_SANDBOX='off' if mode == 'profile' else 'on')
    cmd = ['node', str(work / 'lane_broker.js')]
    if mode != 'plain':
        if not shutil.which('sandbox-exec'):
            return None, None, 'sandbox-exec not found (macOS only)', folder
        (folder / 'broker.sb').write_text(broker_profile(lane, playwright, allow_read))
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


def stop_stream(stream):
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
        found = re.search(r'deny\(\d+\) (\S+) (.*)$', line)
        key = f'{found.group(1)} {found.group(2)[:160]}' if found else line[-200:]
        if 'deny' in line and key not in seen:
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
    parser.add_argument('--broker', action='append', choices=['plain', 'profile', 'profile-chrome-sandbox'],
                        help='spike 4: drive a browser started outside the lane (repeatable). plain: no sandbox at all '
                             '(shows what a broker must close); profile: under its own sandbox-exec profile, Chrome sandbox '
                             'off; profile-chrome-sandbox: the same with Chrome\'s own sandbox on')
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
            stream = denial_stream()
            if broker:
                home_probe = Path.home() / WRITE_PROBE
                if home_probe.exists():
                    sys.exit(f'{home_probe} exists before the run; remove it and retry')
                proc, endpoint, note, folder = start_broker(broker, lane, work, args.playwright, channel, args.allow_read, env)
                print(f'\n== {name}: {note.splitlines()[0] if note else ""} ==')
                if endpoint is None:
                    print(note)
                    for line in stop_stream(stream)[:80] or ['(no denials captured)']:
                        print(line)
                    continue
                run_env.update(SPIKE_BROKER_WS=endpoint, SPIKE_BROKER_MODE=broker, SPIKE_WRITE_PROBE=WRITE_PROBE)
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
            denials = stop_stream(stream)
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
            print(f'\n-- sandbox denials streamed during {name} (unique, first 80) --')
            for line in denials[:80] or ['(none captured)']:
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
