#!/usr/bin/env python3
"""Goal 2's before and after, taken in one hour (the goal-2 baseline re-check's Should 1): first_paint_timing.py's
loads in rounds, each round cold then warm on every path, every load kept, so a "before" taken just ahead of a sitting's
restart and an "after" just behind it share Funnel's link of that hour and can be read side by side.

    uv run --project peer python scripts/first_paint_rounds.py run --label before --rounds 4 --runs 10 \
        --pin funnel=208.111.34.11 --out goal2.jsonl
    uv run --project peer python scripts/first_paint_rounds.py summary goal2.jsonl

`run` appends one JSON line per load (label, round, path, cache, the UTC time, and the load's timings and bytes) to
--out. `summary` reads the lines back and prints, for each label, cache and path, the loads, failures, first paint and
sign-in form p50 and p95, how many forms went over 600 ms, and the median bytes. It writes nothing but --out, sends no
credential, and fills no form."""
import argparse
import datetime
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from first_paint_timing import DEFAULT_URL, measure, p95, pinned  # noqa: E402


def run(args):
    from playwright.sync_api import sync_playwright
    host = urlsplit(args.url).hostname
    paths = [('resolved', None)] + [(name, f'MAP {host} {address}') for name, address in args.pin]
    with open(args.out, 'a', encoding='utf-8') as out, sync_playwright() as playwright:
        for number in range(1, args.rounds + 1):
            for cache in ('cold', 'warm'):
                for name, rule in paths:
                    browser = playwright.chromium.launch(args=[f'--host-resolver-rules={rule}'] if rule else [])
                    try:
                        at = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                        rows, failed, _, _ = measure(browser, args.url, args.runs, args.timeout * 1000, cache == 'warm')
                    finally:
                        browser.close()
                    for row in rows:
                        out.write(json.dumps({'label': args.label, 'round': number, 'path': name, 'cache': cache,
                                              'at': at, **row}) + '\n')
                    for _ in range(failed):
                        out.write(json.dumps({'label': args.label, 'round': number, 'path': name, 'cache': cache,
                                              'at': at, 'failed': True}) + '\n')
                    out.flush()
                    print(f'{args.label} round {number} {cache} {name}: {len(rows)} loads, {failed} failed', flush=True)
    return 0


def summary(args):
    groups = defaultdict(list)
    for text in Path(args.file).read_text(encoding='utf-8').splitlines():
        row = json.loads(text)
        groups[(row['label'], row['cache'], row['path'])].append(row)
    for (label, cache, path), rows in sorted(groups.items()):
        good = [r for r in rows if not r.get('failed')]
        form = sorted(r['form'] for r in good if r.get('form') is not None)
        fcp = sorted(r['fcp'] for r in good if r.get('fcp') is not None)
        if not form or not fcp:
            print(f'{label:8} {cache:4} {path:9} no loads; {len(rows) - len(good)} failed')
            continue
        print(f'{label:8} {cache:4} {path:9} n={len(good)} failed {len(rows) - len(good)}; '
              f'paint p50 {statistics.median(fcp):.0f} p95 {p95(fcp):.0f}; '
              f'form p50 {statistics.median(form):.0f} p95 {p95(form):.0f}, over 600 ms {sum(v > 600 for v in form)}; '
              f'{statistics.median(r["bytes"] for r in good) / 1024:.1f} KB (median); '
              f'{min(r["at"] for r in rows)} to {max(r["at"] for r in rows)}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    take = commands.add_parser('run', help='take rounds of loads and append them to --out')
    take.add_argument('--label', required=True, help='before or after, or any word for this set')
    take.add_argument('--rounds', type=int, default=4)
    take.add_argument('--runs', type=int, default=10, help='loads per path, cache and round')
    take.add_argument('--url', default=DEFAULT_URL)
    take.add_argument('--pin', type=pinned, action='append', default=[], metavar='NAME=ADDRESS')
    take.add_argument('--timeout', type=int, default=30, help='seconds for one load')
    take.add_argument('--out', required=True)
    read = commands.add_parser('summary', help='summarize a file of rounds')
    read.add_argument('file')
    args = parser.parse_args(argv)
    if args.command == 'run':
        if not 1 <= args.rounds <= 20 or not 1 <= args.runs <= 100:
            parser.error('--rounds must be 1 to 20 and --runs 1 to 100')
        if urlsplit(args.url).scheme != 'https' or not urlsplit(args.url).hostname:
            parser.error('--url must be an https address')
        return run(args)
    return summary(args)


if __name__ == '__main__':
    sys.exit(main())
