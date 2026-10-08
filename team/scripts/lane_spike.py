#!/usr/bin/env python3
"""Browser-lane spike: what can a team-mode worker do inside the candidate lane sandbox?

It runs ONE real `claude -p` with a worker's sandbox settings plus the lane's network block, and has it run
lane_probe.sh once. The probes, not the model, produce the results. On macOS it then lists the sandbox's denials
(which Mach services Chrome wanted, for example). Run it from the repository root on the machine that runs team mode:

    python3 team/scripts/lane_spike.py --playwright ~/path/to/bricks/node_modules/playwright --socket "$SSH_AUTH_SOCK"

Nothing it creates outlives it (the lane folder is removed unless --keep). It never reads or prints any key.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
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
    parser.add_argument('--variant', action='append', choices=['base', 'mach-star'], help='sandbox variants to run (default: base)')
    parser.add_argument('--channels', default='chrome', help="browser channels to probe, e.g. 'chrome chromium'")
    parser.add_argument('--allow-read', action='append', default=[], help='an extra folder the lane may read (e.g. ~/Library/Caches/ms-playwright)')
    args = parser.parse_args()

    version, text = claude_version()
    print(f'claude: {text}', '(older than 2.1.285: repo settings may loosen the sandbox)' if version and version < MIN_CLAUDE else '')
    for warning in user_allowlists():
        print('WARNING user-level allowlist merges into the lane:', warning)

    lane = fresh_lane(private_parent(), f'spike-{os.getpid()}')
    work = lane / 'work'
    for name in ('lane_probe.sh', 'lane_chrome_probe.js'):
        shutil.copy(HERE / name, work / name)
    srv = canary()
    sockets = [s for s in args.socket + [os.environ.get('SSH_AUTH_SOCK', '')] if s]
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    # MAC_CHROMIUM_TMPDIR: Chromium on macOS makes its singleton socket under the user temp folder (spike 2), not TMPDIR.
    env.update(CLAUDE_CODE_TMPDIR=str(lane / 'tmp'), MAC_CHROMIUM_TMPDIR=str(lane / 'tmp'), npm_config_cache=str(lane / 'npm-cache'),
               SUPERYAK_BROWSER_LANE='1', SPIKE_CANARY_PORT=str(srv.getsockname()[1]), SPIKE_SOCKETS=' '.join(dict.fromkeys(sockets)),
               SPIKE_CHANNELS=args.channels, SPIKE_CHROME_SCRIPT=str(work / 'lane_chrome_probe.js'), SPIKE_LOG=str(work / 'chrome-debug.log'))
    if args.playwright:
        env['SPIKE_PLAYWRIGHT'] = str(Path(args.playwright).resolve())
    print(f'lane: {lane}')

    if args.baseline:
        print('\n== baseline, outside the sandbox ==')
        print(subprocess.run(['bash', str(work / 'lane_probe.sh')], cwd=work, env=env, capture_output=True, text=True, timeout=600).stdout)

    try:
        for variant in args.variant or ['base']:
            settings = lane_settings(work, lane, args.playwright, variant, args.allow_read)
            (lane / f'settings-{variant}.json').write_text(json.dumps(settings, indent=1))
            stream = denial_stream()
            prompt = (f'Run exactly this one Bash command, once: bash {work / "lane_probe.sh"}\n'
                      'Then reply with only its output, unchanged. Do not run anything else.')
            cmd = ['claude', '-p', prompt, '--output-format', 'text', '--model', args.model, '--permission-mode', 'dontAsk',
                   '--settings', str(lane / f'settings-{variant}.json')]
            try:
                output = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=900).stdout
            except subprocess.TimeoutExpired:
                output = '(claude -p timed out)'
            denials = stop_stream(stream)
            print(f'\n== inside the lane, variant {variant} ==')
            rows = [line.split('\t', 3) for line in output.splitlines() if line.count('\t') >= 3]
            for name, expect, code, detail in rows:
                print(f'{judge(expect, code):5} {name:32} exit={code:3} {detail[:160]}')
            if not rows:
                print('(no probe lines: claude did not run the script)\n' + output[-2000:])
            for channel in args.channels.split():
                log = Path(f'{work / "chrome-debug.log"}.{channel}')
                if log.exists():
                    lines = log.read_text(errors='replace').splitlines()
                    keep = [l for l in lines if re.search(r'(?i)singleton|denied|not permitted|EPERM|EACCES|sandbox|failed|error|fatal|mach|socket|lock|check', l)]
                    print(f'\n-- Chrome debug log [{channel}], variant {variant}: {len(lines)} lines, {len(keep)} relevant (first 60) --')
                    for line in keep[:60]:
                        print(line[:300])
                    log.unlink()
            print(f'\n-- sandbox denials streamed during variant {variant} (unique, first 80) --')
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
