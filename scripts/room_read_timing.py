#!/usr/bin/env python3
"""Goal 2's measure (docs/goals.md): how long a real read of a real room takes from this machine, as its ship, against
the 400 ms line. Standard library and curl only.

    python3 scripts/room_read_timing.py --room <32 hex> [--runs 20] [--limit 100] [--unpaged] [--pin NAME=ADDRESS ...]

The path `resolved` goes wherever this machine's resolver sends it, which is what a browser here takes. Each --pin adds
a path forced to that address, to compare them: the Mac's resolver gives Funnel's public address, so pinning the Pi's
tailnet address shows what Funnel costs. Every round reads each path once, in an order that rotates, so a load that comes
and goes lands on all of them, and the numbers print at the end. --limit defaults to the web app's page (ROOM_PAGE in
static/app.js). --unpaged also reads the whole room, which the web app doesn't do and which holds the store's write gate
for longer.

What a run changes at the station: a ship's read marks `ship_keys.last_used`, so the directory shows this ship as seen
just now. No event, cursor or presence row changes, so nothing reads as read.

What this doesn't measure, so say so beside its numbers:
- curl opens a new connection per read and pays for TLS each time, which a browser keeping a connection doesn't, so a
  path through Funnel reads pessimistic. The line's tls and first byte p50s are there to judge that.
- A ship's read isn't a person's. A ship's key is checked inside a write transaction, and a person's session in a snapshot.
- A read is timed from when it's sent, and the next isn't due until it ends, so a stall counts once however long it
  lasts. Read `max`, `over 1 s` and the wall time beside the p95.
- First paint, and a room while ships post and watchers poll, unless you make that happen during the run.

It stops a path on 401, 403 or 404, which no retry changes, and after 5 failures in a row. A loopback station with a public
origin answers 403, since no origin is sent. It stops the run at --deadline, and on SIGINT, SIGTERM or SIGHUP, and prints what
it has. A run that stopped early, or with any failed read, exits 1.

The key reaches curl on stdin, never in its arguments or environment. `-q` keeps ~/.curlrc out and `--noproxy` keeps a
proxy out, since either could store the key, send it on, or change what's timed. Plain http carries it only to this
machine."""
import argparse
import ipaddress
import json
import math
import os
import re
import signal
import statistics
import subprocess
import sys
import time
from collections import namedtuple
from datetime import datetime, timezone
from urllib.parse import urlsplit

# exit is curl's own status, or DID_NOT_FINISH when there was no curl or it had to be killed
Read = namedtuple('Read', 'code exit tls first total size ip')
FORMAT = '%{http_code} %{time_appconnect} %{time_starttransfer} %{time_total} %{size_download} %{remote_ip}'
DID_NOT_FINISH = -1
SLOW_MS = 1000
SLOW_SHOWN = 6
CURL_GRACE_S = 10  # past curl's own --max-time, so a curl that won't stop can't hold the run
REFUSED = {401, 403, 404}  # no retry changes these
FAILURES_IN_A_ROW = 5
MAX_PINS = 4
MAX_READS = 2000
MAX_LIMIT = 500  # the route refuses more (app.py)
CAUGHT = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
TIMED_OUT = 28  # curl's own exit when --max-time ends a read


class Stopped(BaseException):
    """A signal arrived. Not an Exception, so nothing on the way out takes it for a failed read."""


def nearest_rank(ordered, share):
    """The value at least `share` of a sorted list is at or under; p95 of 20 is the 19th, of 10 the 10th."""
    return ordered[math.ceil(share * len(ordered)) - 1]


def good(row):
    """A read counts only when the station said 200 and curl finished it: a cut-off 200 is curl's exit 18 or 28."""
    return row.code == 200 and row.exit == 0


def read_once(station, key, room, query, pin, timeout):
    parts = urlsplit(station)
    resolve = []
    if pin:
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        address = f'[{pin}]' if ipaddress.ip_address(pin).version == 6 else pin
        resolve = ['--resolve', f'{parts.hostname}:{port}:{address}']
    url = f'{station.rstrip("/")}/api/chats/{room}{query}'
    command = ['curl', '-q', '--noproxy', '*', '-sS', '-o', '/dev/null', '--max-time', str(timeout), '-K', '-', '-w', FORMAT, *resolve, url]
    started = time.monotonic()
    try:
        done = subprocess.run(command, input=f'header = "authorization: Bearer {key}"\n', capture_output=True, text=True,
                              timeout=timeout + CURL_GRACE_S)
    except (subprocess.TimeoutExpired, OSError, ValueError):  # no curl, a curl that hung, or bytes that aren't text
        return Read(0, DID_NOT_FINISH, 0.0, 0.0, (time.monotonic() - started) * 1000, 0, '')
    try:
        fields = done.stdout.split()
        code, tls, first, total, size = fields[:5]
        return Read(int(code), done.returncode, float(tls) * 1000, float(first) * 1000, float(total) * 1000, int(size),
                    fields[5] if len(fields) > 5 else '')
    except ValueError:  # output that isn't its format
        return Read(0, done.returncode, 0.0, 0.0, (time.monotonic() - started) * 1000, 0, '')


def report(label, name, rows, stopped):
    kept = [row for row in rows if good(row)]
    failed = [row for row in rows if not good(row)]
    slow = [row for row in rows if row.total > SLOW_MS]
    biggest = f'max {max(row.total for row in rows):.0f} ms' if rows else 'max none'
    if kept:
        times = sorted(row.total for row in kept)
        numbers = (f'p50 {statistics.median(times):.0f} p95 {nearest_rank(times, .95):.0f} {biggest}; '
                   f'tls p50 {statistics.median(row.tls for row in kept):.0f} first byte p50 {statistics.median(row.first for row in kept):.0f}')
    else:
        numbers = f'no good read, {biggest}'
    reasons = f' (codes {sorted({row.code for row in failed})}, curl exits {sorted({row.exit for row in failed})})' if failed else ''
    sizes = sorted({row.size // 1024 for row in kept})
    size = '0' if not sizes else str(sizes[0]) if len(sizes) == 1 else f'{sizes[0]}-{sizes[-1]}'
    ips = ', '.join(sorted({row.ip for row in rows if row.ip})) or 'none'
    lines = [f'{label:10} {name:10} n={len(rows)} ok={len(kept)} {numbers}; failed {len(failed)}{reasons}; over 1 s {len(slow)}; '
             f'{size} KB; ip {ips}{f"; stopped: {stopped}" if stopped else ""}']
    lines += [f'    code {row.code} tls {row.tls:.0f} first byte {row.first:.0f} total {row.total:.0f} ms' for row in slow[:SLOW_SHOWN]]
    return '\n'.join(lines)


def room_id(text):
    if not re.fullmatch(r'[0-9a-f]{32}', text):
        raise argparse.ArgumentTypeError('a room id is 32 lowercase hex characters')
    return text


def bounded(low, high):
    def parse(text):
        value = int(text)  # argparse turns its ValueError into a usage error
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f'{value} is outside {low} to {high}')
        return value
    return parse


def pinned(text):
    name, _, address = text.partition('=')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,20}', name):
        raise argparse.ArgumentTypeError('a pin is NAME=ADDRESS, with a short plain name')
    ipaddress.ip_address(address)  # argparse turns its ValueError into a usage error
    return name, address


def on_this_machine(host):
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_station(path, pins):
    """The station's address and this ship's key. An error here never repeats the key."""
    try:
        with open(path) as file:
            settings = json.load(file)
        station, key = settings['station'], settings['key']
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit(f'room_read_timing: {path} is missing or has no station and key') from None
    if not isinstance(station, str) or not isinstance(key, str):
        raise SystemExit(f'room_read_timing: {path} has no station and key as text')
    try:
        parts = urlsplit(station)
        parts.port  # noqa: B018  (reading it is what checks it)
    except ValueError:
        raise SystemExit(f'room_read_timing: the station address in {path} is not a URL') from None
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise SystemExit(f'room_read_timing: the station address in {path} is not a URL')
    if parts.scheme == 'http' and not (on_this_machine(parts.hostname) and all(on_this_machine(address) for _, address in pins)):
        raise SystemExit('room_read_timing: plain http would carry the key off this machine; use https, or loopback')
    if not re.fullmatch(r'[\x21\x23-\x5b\x5d-\x7e]+', key):  # curl's config syntax: no quote, backslash, space or newline
        raise SystemExit(f'room_read_timing: the key in {path} has characters curl\'s config file can\'t carry')
    return station, key


def ignore_signals():
    for caught in CAUGHT:
        signal.signal(caught, signal.SIG_IGN)


def stop_on_signal(*_):
    ignore_signals()  # a second one, close behind, mustn't arrive outside the try
    raise Stopped


def main(argv=None):
    parser = argparse.ArgumentParser(description='Time real reads of a real room from this machine (goal 2).')
    parser.add_argument('--room', type=room_id, required=True)
    parser.add_argument('--runs', type=bounded(1, 1000), default=20)
    parser.add_argument('--limit', type=bounded(1, MAX_LIMIT), default=100)
    parser.add_argument('--unpaged', action='store_true', help='also read the whole room')
    parser.add_argument('--pin', type=pinned, action='append', default=[], metavar='NAME=ADDRESS')
    parser.add_argument('--gap-ms', type=bounded(0, 60000), default=300)
    parser.add_argument('--timeout', type=bounded(1, 120), default=25)
    parser.add_argument('--deadline', type=bounded(1, 86400), default=100, help='seconds for the whole run; the default fits a 2-minute shell limit')
    parser.add_argument('--station-file', default=os.path.expanduser('~/.superyak/station.json'))
    args = parser.parse_args(argv)
    if len(args.pin) > MAX_PINS:
        parser.error(f'at most {MAX_PINS} --pin')
    names = ['resolved', *(name for name, _ in args.pin)]
    if len(set(names)) != len(names):
        parser.error('each --pin needs a name of its own, and not `resolved`')
    reads = [(f'limit={args.limit}', f'?limit={args.limit}')] + ([('unpaged', '')] if args.unpaged else [])
    pairs = [(label, query, name, pin) for label, query in reads for name, pin in [('resolved', None), *args.pin]]
    if args.runs * len(pairs) > MAX_READS:
        parser.error(f'{args.runs} runs of {len(pairs)} paths is over {MAX_READS} reads')
    station, key = load_station(args.station_file, args.pin)

    rows = {pair: [] for pair in pairs}
    stopped, in_a_row = {}, dict.fromkeys(pairs, 0)
    began, ended = time.monotonic(), None
    deadline = began + args.deadline
    when = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    for caught in CAUGHT:
        signal.signal(caught, stop_on_signal)
    try:
        try:
            first = True
            for run in range(args.runs):
                turn = run % len(pairs)
                for pair in pairs[turn:] + pairs[:turn]:
                    if pair in stopped:
                        continue
                    if not first:
                        time.sleep(min(args.gap_ms / 1000, max(0, deadline - time.monotonic())))
                    first = False
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError
                    limit = min(args.timeout, math.ceil(left))
                    row = read_once(station, key, args.room, pair[1], pair[3], limit)
                    if row.exit == TIMED_OUT and limit < args.timeout:  # the deadline cut it short, not the station
                        raise TimeoutError
                    rows[pair].append(row)
                    in_a_row[pair] = 0 if good(row) else in_a_row[pair] + 1
                    if row.code in REFUSED:
                        stopped[pair] = f'refused {row.code}'
                    elif in_a_row[pair] >= FAILURES_IN_A_ROW:
                        stopped[pair] = f'{FAILURES_IN_A_ROW} failures in a row'
                if len(stopped) == len(pairs):
                    break
        except TimeoutError:
            ended = f'stopped at the {args.deadline} s deadline'
        ignore_signals()  # what's measured gets printed
    except Stopped:
        ended = 'stopped by a signal'

    total = sum(len(done) for done in rows.values())
    print(f'room {args.room[:8]} {when}, wall {time.monotonic() - began:.1f} s, {total} reads{f", {ended}" if ended else ""}')
    for pair in pairs:
        print(report(pair[0], pair[2], rows[pair], stopped.get(pair)))
    sys.stdout.flush()
    complete = all(good(row) for done in rows.values() for row in done)
    return 0 if complete and not ended else 1


if __name__ == '__main__':
    sys.exit(main())
