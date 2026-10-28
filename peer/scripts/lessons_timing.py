"""First rail section 5's measure on this peer, against a fixture at the bound: 4 ships x 32 lessons at the byte limits,
in a new temporary data directory, through this machine's own embedder (runtime.json). It writes nothing anywhere else.

Three paths, each p95 of 50 runs after one warm-up, the first recorded beside it:
- query: the hook's `python -I -B -m superyak_peer.lessons query` at a failure, every field at its cap (under 1 s);
- hook: the prompt path as the hook runs it (C42): a fresh interpreter, with no site-packages, imports
  superyak_peer.lessons from the checkout and calls answer_prompt with budget_ms set to what is left of 100 ms since
  the process was spawned, timed from the spawn (under 150 ms: Task 18's gate);
- prompt: the same request through the query command in a second interpreter, reported beside it (not gated).
It also reports the embedder's own p95 on a 2,000-character prompt: above 100 ms, Near can't finish at a prompt and
only queues the next request behind it, so make lessons-prompt-near NEAR=off (C44).

Two more measures at the bound are reported beside them and gate nothing (reviews B and C):
- could_hold, in process: p95 of 50 calls on the query's command, which matches nothing, so each call reads the whole
  index file and scans every command value;
- one door: p95 of 50 posts into the lessons room through send_message, whose door rebuilds the room's history in its
  transaction. Each re-lays one of a ship's own lessons, so it passes every check and the live lessons stay at the
  bound while the room's posts grow by one a post; the door's checks alone (check_lesson, which posts nothing) are
  timed first, on the room at exactly the bound.

    peer/.venv/bin/python -I scripts/lessons_timing.py [--runtime-config PATH] [--runs 50] [--restart-unit superyak-embedder]

With --restart-unit, the embedder is restarted after the fixture is built (which embeds), so each path's first run is
the first after the embedder starts (section 5)."""
import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SHIPS = ('rio-grande', 'tardis', 'serenity', 'defiant')
ASKING = 'rio-grande'
LIMIT_MS = {'query': 1000, 'hook': 150}
RSS_LIMIT_MIB = 64
PROMPT_BUDGET_MS = 100
SPAWNED = '<spawned>'  # replaced in each run's command by the wall time just before the spawn
CHECKOUT = Path(__file__).resolve().parents[1]


def value(kind, ship, n, i, size):
    """A distinct applies-to value of exactly `size` bytes: letters only, so no pattern of section 6 can match it."""
    stem = f'{kind}{"abcdefgh"[i]}{"abcdefghijklmnopqrstuvwxyzABCDEF"[n]}{ship.replace("-", "")}'
    return (stem + 'q' * size)[:size]


def bound_lesson(ship, n):
    lines = ['lesson', f'ship: {ship}', 'claim: ' + value('claim', ship, n, 0, 160), 'why: ' + value('why', ship, n, 0, 300)]
    for kind in ('error', 'command', 'file'):
        lines += [f'{kind}: ' + value(kind, ship, n, i, 120) for i in range(8)]
    return '\n'.join(lines + ['learned from: own'])


def build_fixture(data_dir, socket_path, clock):
    """The bound: andy, four ships, one recorded lessons room, 32 lessons each, then one index run. Returns the run."""
    from superyak_peer.db import Store
    from superyak_peer.identity import PeerIdentity
    store = Store(data_dir, clock=clock)
    PeerIdentity.load_or_create(store.data_dir)
    andy = store.create_user('andy', 'Andy', 'a-long-password-for-timing', is_admin=True)['id']
    ships = {name: store.lessons_ship(name, 'andy')['id'] for name in SHIPS}
    room = store.create_room(andy, 'Lessons', list(ships.values()))['id']
    with store.transaction() as db:  # four local ships: a fixture, not a room section 3 would record
        db.execute('INSERT INTO lessons_room VALUES(1,?,?,?)', (room, ships[ASKING], clock()))
    for n in range(32):
        for name, ship_id in ships.items():
            store.send_message(ship_id, room, f'timing-{name}-{n}', bound_lesson(name, n))
        clock.advance(10)  # under each ship's 30 posts a minute
    return store.lessons_index(socket_path)


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def requests():
    """Every field at its cap; nothing in them matches a fixture value, so each query runs Near."""
    context = {'ship': ASKING, 'cwd': '/w/' + 'd' * 197, 'branch': 'b' * 200, 'command': 'run ' + 'c' * 296,
               'error': 'Error: ' + 'e' * 293, 'words_only': False, 'seen': []}
    prompt = {'ship': ASKING, 'prompt': ('Why does this suite keep failing on the second run here ' * 40)[:2000], 'seen': []}
    return {'query': context, 'prompt': prompt}


def restart(unit, socket_path, run=subprocess.run, clock=time.monotonic, sleep=time.sleep, wait=120.0):
    """Restart the embedder's unit and wait until it answers again, so the next query is the first after it starts."""
    from superyak_peer.lessons import EmbedderUnavailable, embedder_model
    run(['systemctl', '--user', 'restart', unit], check=True)
    until = clock() + wait
    while True:
        try:
            return embedder_model(socket_path, clock() + 5, clock)
        except EmbedderUnavailable:
            if clock() >= until:
                raise SystemExit(f'{unit} did not answer within {wait:.0f} s of its restart')
            sleep(0.5)


# Each process reports its own peak: Linux carries a parent's peak RSS across exec into ru_maxrss, so RUSAGE_CHILDREN
# would report this script's. /proc/self/status VmHWM is the process's own; macOS has no /proc, so ru_maxrss (bytes).
PEAK = ("import atexit, resource, sys\n"
        "def _peak():\n"
        "    try:\n"
        "        kib = int(next(l for l in open('/proc/self/status') if l.startswith('VmHWM')).split()[1])\n"
        "    except OSError:\n"
        "        kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024\n"
        "    print(f'peak-kib {kib}', file=sys.stderr)\n"
        "atexit.register(_peak)\n")
QUERY = PEAK + "from superyak_peer.lessons import main\nmain(sys.argv[1:])\n"
# The hook's in-process path (C42): argv is spawned, checkout, data dir, runtime config ('' for the default), and a
# wall time to pin (a test's; '' in a real run), set before the module binds time.time.
HOOK = PEAK + ("import json, time\n"
               "spawned, checkout, data_dir, config, pin = float(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] or None, sys.argv[5]\n"
               "if pin:\n"
               "    time.time = lambda: float(pin)\n"
               "sys.dont_write_bytecode = True\n"
               "sys.path.insert(0, checkout)\n"
               "from superyak_peer import lessons\n"
               "request = json.loads(sys.stdin.buffer.read())\n"
               f"request['budget_ms'] = max(0, int({PROMPT_BUDGET_MS} - (time.time() - spawned) * 1000))\n"
               "answer = lessons.answer_prompt(lessons.read_request(json.dumps(request)), data_dir, lessons.embedder_socket(config))\n"
               "sys.stdout.write(lessons.dumps(answer))\n")


def peak_kib(stderr):
    return int(stderr.decode().strip().splitlines()[-1].split()[1])


def p95(values):
    """Nearest rank: of 50 values, the 48th smallest."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def measure(command, payload, runs, run=subprocess.run, timer=time.perf_counter, wall=time.time):
    """(first, the next `runs`) in milliseconds, each a whole process from its spawn, and the largest peak in MiB. A
    SPAWNED word in the command becomes the wall time just before each spawn. A run that fails raises."""
    data = json.dumps(payload).encode()
    times, peaks = [], []
    for _ in range(runs + 1):
        argv = [repr(wall()) if part == SPAWNED else part for part in command]
        start = timer()
        done = run(argv, input=data, capture_output=True)
        times.append((timer() - start) * 1000)
        if done.returncode != 0 or 'lessons' not in json.loads(done.stdout):
            raise RuntimeError(f'run failed: {done.returncode} {done.stderr[-300:]!r}')
        peaks.append(peak_kib(done.stderr))
    return times[0], times[1:], max(peaks) / 1024


def measure_embed(socket_path, text, runs, embed=None, timer=time.perf_counter):
    """The embedder's own time for one prompt-sized request, in milliseconds: (first, the next `runs`)."""
    if embed is None:
        from superyak_peer.lessons import embed
    times = []
    for _ in range(runs + 1):
        start = timer()
        embed(socket_path, [text], 'search_query', time.monotonic() + 60)
        times.append((timer() - start) * 1000)
    return times[0], times[1:]


def measure_could_hold(data_dir, command, runs, ship=ASKING, timer=time.perf_counter):
    """could_hold's own time, in process, in milliseconds (review C): (first, the next `runs`, what it said). Each call
    reads the index file afresh, as the hook's does before a Bash command."""
    from superyak_peer.lessons import could_hold
    times, held = [], None
    for _ in range(runs + 1):
        start = timer()
        held = could_hold(command, ship, data_dir)
        times.append((timer() - start) * 1000)
    return times[0], times[1:], held


def measure_door(data_dir, clock, runs, timer=time.perf_counter):
    """One door's cost with the room at the bound, in milliseconds (review B): {'checks': (first, rest), 'post': (first,
    rest)}. The checks (check_lesson, every check the door runs, posting nothing) are timed first, on the room at
    exactly the bound; then each post goes through send_message and re-lays one of a ship's own lessons under a new
    client id, so it passes every check, the live lessons stay at the bound, and the room's posts grow by one a post.
    The fixture's clock moves 3 s a post, under each ship's 30 posts a minute."""
    from superyak_peer.db import Store
    store = Store(data_dir, clock=clock)
    with store.transaction() as db:
        room = store._lessons_chain(db)[-1]
        ships = {row['username']: row['id'] for row in db.execute("SELECT id, username FROM users WHERE kind='ship'")}
    picks = [(SHIPS[n % len(SHIPS)], bound_lesson(SHIPS[n % len(SHIPS)], n % 32)) for n in range(runs + 1)]
    got = {}
    for name, act in (('checks', lambda n, ship, body: store.check_lesson(ships[ship], body)),
                      ('post', lambda n, ship, body: store.send_message(ships[ship], room, f'timing-door-{n}', body))):
        times = []
        for n, (ship, body) in enumerate(picks):
            start = timer()
            act(n, ship, body)
            times.append((timer() - start) * 1000)
            clock.advance(3)
        got[name] = (times[0], times[1:])
    return got


def spread(rest, unit):
    return (f'{len(rest)} {unit} p50 {sorted(rest)[len(rest) // 2]:.0f} ms, p95 {p95(rest):.0f} ms, '
            f'max {max(rest):.0f} ms')


def report(results, embedded=None, could=None, door=None):
    """One line per path; the hook path and the query gate the PASS, the subprocess prompt path is reported only, and
    could_hold's and the door's lines, after the embedder's, gate nothing."""
    lines, ok = [], True
    rss = max(peak for _, _, peak in results.values())
    for path, (first, rest, _) in results.items():
        line = f'{path}: first {first:.0f} ms; {spread(rest, "runs")}'
        if path in LIMIT_MS:
            good = p95(rest) < LIMIT_MS[path]
            ok &= good
            line += f'; p95 under {LIMIT_MS[path]} ms: {"yes" if good else "NO"}'
        else:
            line += '; reported beside the hook path, not gated'
        lines.append(line)
    ok &= rss < RSS_LIMIT_MIB
    lines.append(f'peak process: {rss:.1f} MiB; under {RSS_LIMIT_MIB} MiB: {"yes" if rss < RSS_LIMIT_MIB else "NO"}')
    if embedded is not None:
        slow = p95(embedded[1]) > PROMPT_BUDGET_MS
        lines.append(f'embedder, one 2,000-character prompt: first {embedded[0]:.0f} ms, p95 {p95(embedded[1]):.0f} ms; '
                     + ('over 100 ms: run make lessons-prompt-near NEAR=off' if slow else 'Near can finish at a prompt'))
    if could is not None:
        lines.append(f'could_hold, in process at the bound: first {could[0]:.0f} ms; {spread(could[1], "calls")}; '
                     f'held: {"yes" if could[2] else "no"}; reported, gates nothing')
    if door is not None:
        lines.append(f'door at the bound, one post into the lessons room: first {door["post"][0]:.0f} ms; '
                     f'{spread(door["post"][1], "posts")}; its checks alone (check_lesson) p95 {p95(door["checks"][1]):.0f} ms; '
                     'reported, gates nothing')
    return '\n'.join(lines + ['PASS' if ok else 'FAIL'])


def main(argv=None):
    from superyak_peer.lessons import INDEX_FILE, embedder_socket
    parser = argparse.ArgumentParser(prog='lessons_timing')
    parser.add_argument('--runtime-config', type=Path)
    parser.add_argument('--runs', type=int, default=50)
    parser.add_argument('--restart-unit', help='Restart this user unit after the fixture is built (superyak-embedder)')
    args = parser.parse_args(argv)
    socket_path = embedder_socket(args.runtime_config)
    if socket_path is None:
        parser.exit(2, 'No embedder_socket in runtime.json: the measure needs this machine\'s embedder\n')
    with tempfile.TemporaryDirectory(prefix='lessons-timing-') as folder:
        data_dir = Path(folder) / 'peer'
        clock = Clock(time.time() - 3600)
        built = build_fixture(data_dir, socket_path, clock)
        if built.get('vectors') != 128:
            parser.exit(1, f'The fixture index has {built.get("vectors")} vectors of 128: is the embedder answering?\n')
        if args.restart_unit:
            restart(args.restart_unit, socket_path)
        config = [] if args.runtime_config is None else ['--runtime-config', str(args.runtime_config)]
        query = [sys.executable, '-I', '-B', '-c', QUERY, 'query', '--data-dir', str(data_dir), *config]
        hook = [sys.executable, '-I', '-S', '-B', '-c', HOOK, SPAWNED, str(CHECKOUT), str(data_dir), str(args.runtime_config or ''), '']
        payloads, results = requests(), {}
        for path, command, payload in (('query', query, payloads['query']), ('hook', hook, payloads['prompt']),
                                       ('prompt', query, payloads['prompt'])):
            (data_dir / INDEX_FILE).touch()  # fresh for the prompt path, whatever the fixture's clock said
            results[path] = measure(command, payload, args.runs)
        embedded = measure_embed(socket_path, payloads['prompt']['prompt'], args.runs)
        could = measure_could_hold(data_dir, payloads['query']['command'], args.runs)
        door = measure_door(data_dir, clock, args.runs)  # last: it adds posts to the room
        print(report(results, embedded, could, door))


if __name__ == '__main__':
    main()
