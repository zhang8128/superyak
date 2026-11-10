#!/usr/bin/env python3
"""Goal 2's other measure (docs/goals.md): the web app's first paint from this machine, against the 600 ms line.

    uv run --project peer python scripts/first_paint_timing.py [--url URL] [--runs 50] [--warm] [--tail N]
        [--pin NAME=ADDRESS ...]

Each run opens a fresh browser context, so the cache is cold (the browser process, its DNS and the OS's state are not),
loads the page, and reads the browser's own paint and navigation timings. First paint is the loading shell ("Opening
this home…"); what a visitor can use is the sign-in form, so each run also reports the first frame after the form's
heading joins the page (a MutationObserver set before any script runs; a frame's start, so a little before its paint).

With --warm, each path loads the page once in one context to fill its cache, then measures every run in that same
context, the way a person comes back. Each run's bytes are its own, so a cached file counts 0 and a revalidated one
only its headers. No request is routed through Playwright, because routing turns the cache off.

The path `resolved` goes wherever this machine's resolver sends it. Each --pin adds a path forced to that address
(Chromium's host resolver rules). The Mac's resolver gives Funnel's public address and a machine on the tailnet gets
the tailnet address, so pin Funnel's address to see what a visitor from outside gets. --tail N prints each path's N
slowest loads by the form's time, split into connection, first byte, the page, its files, its API calls and the form.

The header names this machine's OS, the browser build, the flags and the time window, so a later run can be compared.

What this doesn't measure, so say so beside its numbers:
- A signed-out visitor's page: the sign-in shell. A signed-in person's first paint needs that person's browser session,
  and a ship has none. Take that one on the person's own machine.
- Headless Chromium, not the person's browser.
- A page while ships post and watchers poll, unless you make that happen during the run.

It writes nothing anywhere and sends no credential. A path stops after 5 failed loads in a row. A run with a failed load
exits 1."""
import argparse
import datetime
import math
import platform
import statistics
import sys
from importlib.metadata import version
from urllib.parse import urlsplit

DEFAULT_URL = 'https://smart.tail7db420.ts.net/'
FAILS_IN_A_ROW = 5
TIMINGS = """() => {
  const nav = performance.getEntriesByType('navigation')[0];
  const paint = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, p.startTime]));
  const res = performance.getEntriesByType('resource');
  const end = kinds => Math.max(0, ...res.filter(r => kinds.includes(r.initiatorType)).map(r => r.responseEnd));
  return {fcp: paint['first-contentful-paint'] ?? null, ttfb: nav.responseStart, load: nav.loadEventEnd,
          connect: nav.connectEnd - nav.domainLookupStart, html: nav.responseEnd, files: end(['link', 'script']),
          api: end(['fetch', 'xmlhttprequest']),
          bytes: nav.transferSize + res.reduce((a, r) => a + (r.transferSize || 0), 0), resources: res.length,
          title: document.title, form: window.__formAt ?? null};
}"""
FORM = '#login-title'  # the sign-in form's heading (peer/superyak_peer/static/app.js), shown whether or not demos are
WATCH_FORM = """(() => {
  const seen = () => {
    if (window.__formAt !== undefined || !document.querySelector('%s')) return false;
    window.__formAt = null;
    requestAnimationFrame(t => { window.__formAt = t; });
    return true;
  };
  new MutationObserver((_, observer) => { if (seen()) observer.disconnect(); })
    .observe(document, {childList: true, subtree: true});
})();""" % FORM


def pinned(value):
    name, sep, address = value.partition('=')
    if not sep or not name.isidentifier() or not address:
        raise argparse.ArgumentTypeError('expected NAME=ADDRESS')
    return name, address


def p95(values):
    return values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)]


def load(context, url, timeout_ms):
    page = context.new_page()
    try:
        page.goto(url, wait_until='load', timeout=timeout_ms)
        page.wait_for_function('() => window.__formAt', timeout=timeout_ms)  # a function: the page's CSP refuses eval
        page.wait_for_timeout(300)  # paint entries can land just after load
        return page.evaluate(TIMINGS)
    finally:
        page.close()


def fresh(browser):
    context = browser.new_context()
    context.add_init_script(WATCH_FORM)
    return context


def measure(browser, url, runs, timeout_ms, warm):
    """Rows, failed loads, whether the warm-up failed, and whether the path stopped early."""
    rows, failed, in_a_row, warmup_failed = [], 0, 0, False
    shared = fresh(browser) if warm else None
    try:
        if warm:
            try:
                load(shared, url, timeout_ms)  # fills the cache; not counted
            except Exception:  # noqa: BLE001 - the runs still go ahead; the first one fills the cache instead
                warmup_failed = True
        for _ in range(runs):
            context = shared or fresh(browser)
            try:
                rows.append(load(context, url, timeout_ms))
                in_a_row = 0
            except Exception:  # noqa: BLE001 - a failed load is counted and reported, not raised
                failed += 1
                in_a_row += 1
                if in_a_row == FAILS_IN_A_ROW:
                    return rows, failed, warmup_failed, True
            finally:
                if not warm:
                    context.close()
    finally:
        if shared:
            shared.close()
    return rows, failed, warmup_failed, False


def line(name, rows, failed, warmup_failed, stopped):
    notes = ((' (warm-up failed)' if warmup_failed else '')
             + (f' (stopped after {FAILS_IN_A_ROW} in a row)' if stopped else ''))
    fcp = sorted(r['fcp'] for r in rows if r['fcp'] is not None)
    if not fcp:
        return f'{name:10} n=0 failed {failed}{notes}'
    form = sorted(r['form'] for r in rows if r['form'] is not None)
    shown = (f'sign-in form p50 {statistics.median(form):.0f} p95 {p95(form):.0f} max {form[-1]:.0f} ms; ' if form
             else 'sign-in form not seen; ')
    over = sum(1 for v in fcp if v > 600)
    form_over = sum(1 for v in form if v > 600)
    return (f'{name:10} n={len(rows)} first paint p50 {statistics.median(fcp):.0f} p95 {p95(fcp):.0f} '
            f'max {fcp[-1]:.0f} ms; '
            f'{shown}first byte p50 {statistics.median(r["ttfb"] for r in rows):.0f}; '
            f'load p50 {statistics.median(r["load"] for r in rows):.0f}; '
            f'over 600 ms: paint {over} of {len(fcp)}, form {form_over} of {len(form)}; failed {failed}{notes}; '
            f'{statistics.median(r["bytes"] for r in rows) / 1024:.1f} KB (median) '
            f'in {rows[0]["resources"] + 1} requests; '
            f'page "{rows[0]["title"]}"')


def slowest(name, rows, n):
    """Each of the n slowest loads by the form's time, as the moments each part ended, in ms from the navigation's
    start."""
    ranked = sorted((r for r in rows if r['form'] is not None), key=lambda r: r['form'], reverse=True)[:n]
    return [f'  {name} slow: form {r["form"]:.0f} = connected {r["connect"]:.0f}, first byte {r["ttfb"]:.0f}, '
            f'page {r["html"]:.0f}, files {r["files"]:.0f}, paint {r["fcp"] or 0:.0f}, api {r["api"]:.0f}'
            for r in ranked]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--runs', type=int, default=50)
    parser.add_argument('--warm', action='store_true',
                        help='measure loads that reuse one cache, after one that fills it')
    parser.add_argument('--tail', type=int, default=0, metavar='N', help="print each path's N slowest loads, split up")
    parser.add_argument('--pin', type=pinned, action='append', default=[], metavar='NAME=ADDRESS')
    parser.add_argument('--timeout', type=int, default=30, help='seconds for one load')
    args = parser.parse_args(argv)
    if not 1 <= args.runs <= 200:
        parser.error('--runs must be 1 to 200')
    if not 0 <= args.tail <= args.runs:
        parser.error('--tail must be 0 to --runs')
    host = urlsplit(args.url).hostname
    if urlsplit(args.url).scheme != 'https' or not host:
        parser.error('--url must be an https address')
    from playwright.sync_api import sync_playwright
    paths = [('resolved', None)] + [(name, f'MAP {host} {address}') for name, address in args.pin]
    results, any_failed, build = {}, False, None
    started = datetime.datetime.now(datetime.timezone.utc)
    with sync_playwright() as playwright:
        for name, rule in paths:
            browser = playwright.chromium.launch(args=[f'--host-resolver-rules={rule}'] if rule else [])
            try:
                build = browser.version
                rows, failed, warmup_failed, stopped = measure(browser, args.url, args.runs, args.timeout * 1000,
                                                               args.warm)
            finally:
                browser.close()
            results[name] = [line(name, rows, failed, warmup_failed, stopped)] + slowest(name, rows, args.tail)
            any_failed = any_failed or failed > 0 or not rows
    ended = datetime.datetime.now(datetime.timezone.utc)
    stamp = '%Y-%m-%dT%H:%M:%SZ'
    print(f'{args.url}, {args.runs} {"warm" if args.warm else "cold"} loads per path, '
          f'{started.strftime(stamp)} to {ended.strftime(stamp)}')
    print(f'{platform.platform()} on {platform.machine()}; Playwright {version("playwright")}, '
          f'headless Chromium {build}; '
          f'flags: {" ".join(argv if argv is not None else sys.argv[1:]) or "(none)"}')
    for text in results.values():
        print('\n'.join(text))
    return 1 if any_failed else 0


if __name__ == '__main__':
    sys.exit(main())
