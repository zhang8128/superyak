#!/usr/bin/env python3
"""Goal 2's measure (docs/goals.md): how long a real read of a real room takes from this machine, as its ship, against
the 400 ms line. Standard library and curl only; it reads rooms and writes nothing.

    python3 scripts/room_read_timing.py --room <32 hex> [--runs 20] [--limit 100] [--unpaged] [--pin NAME=ADDRESS ...]

The path `resolved` goes wherever this machine's resolver sends it, which is what a browser here takes. Each --pin adds
a path forced to that address, to compare them: the Mac's resolver gives Funnel's public address, so pinning the Pi's
tailnet address shows what Funnel costs. --limit defaults to the web app's page (ROOM_PAGE in static/app.js). --unpaged
also reads the whole room, which the web app doesn't do.

What this doesn't measure, so say so beside its numbers: curl opens a new connection per read and pays for TLS each
time, which a browser keeping a connection doesn't, so a path through Funnel reads pessimistic; first paint; and a room
while ships post and watchers poll, unless you make that happen during the run.

The key reaches curl on stdin, never in its arguments, where any process on this machine could read it."""
import argparse
import ipaddress
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from collections import namedtuple
from urllib.parse import urlsplit

Read = namedtuple('Read', 'code tls first total size ip')
FORMAT = '%{http_code} %{time_appconnect} %{time_starttransfer} %{time_total} %{size_download} %{remote_ip}'
SLOW_MS = 1000
CURL_GRACE_S = 10  # past curl's own --max-time, so a curl that won't stop can't hold the run
FAILED = Read(0, 0.0, 0.0, 0.0, 0, '')


def nearest_rank(ordered, share):
    """The value at least `share` of a sorted list is at or under; p95 of 20 is the 19th, of 10 the 10th."""
    return ordered[math.ceil(share * len(ordered)) - 1]


def read_once(station, key, room, query, pin, timeout):
    parts = urlsplit(station)
    resolve = []
    if pin:
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        address = f'[{pin}]' if ipaddress.ip_address(pin).version == 6 else pin
        resolve = ['--resolve', f'{parts.hostname}:{port}:{address}']
    url = f'{station.rstrip("/")}/api/chats/{room}{query}'
    command = ['curl', '-sS', '-o', '/dev/null', '--max-time', str(timeout), '-K', '-', '-w', FORMAT, *resolve, url]
    try:
        done = subprocess.run(command, input=f'header = "authorization: Bearer {key}"\n', capture_output=True, text=True,
                              timeout=timeout + CURL_GRACE_S)
        fields = done.stdout.split()
        code, tls, first, total, size = fields[:5]
        return Read(int(code), float(tls) * 1000, float(first) * 1000, float(total) * 1000, int(size),
                    fields[5] if len(fields) > 5 else '')
    except (subprocess.TimeoutExpired, OSError, ValueError):  # no curl, a curl that hung, or output that isn't its format
        return FAILED


def report(label, name, rows):
    good = sorted(row.total for row in rows if row.code == 200)
    failed = [row for row in rows if row.code != 200]
    slow = [row for row in rows if row.total > SLOW_MS]
    times = (f'p50 {statistics.median(good):.0f} p95 {nearest_rank(good, .95):.0f} max {good[-1]:.0f} ms'
             if good else 'no good read')
    codes = sorted({row.code for row in failed})
    lines = [f'{label:10} {name:10} n={len(rows)} ok={len(good)} {times}; failed {len(failed)}'
             f'{f" (codes {codes})" if failed else ""}; over 1 s {len(slow)}; '
             f'{rows[0].size // 1024} KB; ip {rows[0].ip or "none"}']
    lines += [f'    code {row.code} tls {row.tls:.0f} first byte {row.first:.0f} total {row.total:.0f} ms' for row in slow[:6]]
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


def load_station(path):
    """The station's address and this ship's key. An error here never repeats the key."""
    try:
        with open(path) as file:
            settings = json.load(file)
        station, key = settings['station'], settings['key']
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit(f'room_read_timing: {path} is missing or has no station and key') from None
    if not isinstance(station, str) or not isinstance(key, str):
        raise SystemExit(f'room_read_timing: {path} has no station and key as text')
    if urlsplit(station).scheme not in ('http', 'https') or not urlsplit(station).hostname:
        raise SystemExit(f'room_read_timing: the station address in {path} is not a URL')
    if not re.fullmatch(r'[\x21\x23-\x5b\x5d-\x7e]+', key):  # curl's config syntax: no quote, backslash, space or newline
        raise SystemExit(f'room_read_timing: the key in {path} has characters curl\'s config file can\'t carry')
    return station, key


def main(argv=None):
    parser = argparse.ArgumentParser(description='Time real reads of a real room from this machine (goal 2).')
    parser.add_argument('--room', type=room_id, required=True)
    parser.add_argument('--runs', type=bounded(1, 1000), default=20)
    parser.add_argument('--limit', type=bounded(1, 1000), default=100)
    parser.add_argument('--unpaged', action='store_true', help='also read the whole room')
    parser.add_argument('--pin', type=pinned, action='append', default=[], metavar='NAME=ADDRESS')
    parser.add_argument('--gap-ms', type=bounded(0, 60000), default=300)
    parser.add_argument('--timeout', type=bounded(1, 120), default=25)
    parser.add_argument('--station-file', default=os.path.expanduser('~/.superyak/station.json'))
    args = parser.parse_args(argv)
    station, key = load_station(args.station_file)
    reads = [(f'limit={args.limit}', f'?limit={args.limit}')] + ([('unpaged', '')] if args.unpaged else [])
    paths = [('resolved', None), *args.pin]
    every_read_good = True
    for label, query in reads:
        for name, pin in paths:
            rows = []
            for run in range(args.runs):
                if run:
                    time.sleep(args.gap_ms / 1000)
                rows.append(read_once(station, key, args.room, query, pin, args.timeout))
            print(report(label, name, rows), flush=True)
            every_read_good = every_read_good and all(row.code == 200 for row in rows)
    return 0 if every_read_good else 1


if __name__ == '__main__':
    sys.exit(main())
