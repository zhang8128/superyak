#!/usr/bin/env python3
"""Goal 2's other measure (docs/goals.md): the web app's first paint from this machine, against the 600 ms line.

    uv run --project peer python scripts/first_paint_timing.py [--url URL] [--runs 50] [--warm] [--pin NAME=ADDRESS ...]

Each run opens a fresh browser context, so the cache is cold, loads the page, and reads the browser's own paint and
navigation timings. First paint is the loading shell ("Opening this home…"); what a visitor can use is the sign-in form,
so each run also reports the first frame after the form's heading joins the page (a MutationObserver set before any
script runs). With --warm, each path loads the page once in one context to fill its cache, then measures every run in
that same context, the way a person comes back; each run's bytes are its own, so a cached file counts 0 and a
revalidated one only its headers. No request is routed through Playwright, because routing turns the cache off. The path `resolved` goes wherever this machine's resolver sends it. Each --pin adds a path forced to
that address (Chromium's host resolver rules), to compare them. The Mac's resolver gives Funnel's public address, and a
machine on the tailnet gets the tailnet address, so pin Funnel's address to see what a visitor from outside gets.

What this doesn't measure, so say so beside its numbers:
- A signed-out visitor's page: the sign-in shell. A signed-in person's first paint needs that person's browser session,
  and a ship has none. Take that one on the person's own machine.
- Headless Chromium, not the person's browser, and a cold cache every run unless --warm.
- A page while ships post and watchers poll, unless you make that happen during the run.

It writes nothing anywhere and sends no credential. A run with a failed load exits 1."""
import argparse
import json
import math
import statistics
import sys
from urllib.parse import urlsplit

DEFAULT_URL = 'https://smart.tail7db420.ts.net/'
TIMINGS = """() => {
  const nav = performance.getEntriesByType('navigation')[0];
  const paint = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, p.startTime]));
  const res = performance.getEntriesByType('resource');
  return {fcp: paint['first-contentful-paint'] ?? null, ttfb: nav.responseStart, load: nav.loadEventEnd,
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


def measure(playwright, url, rule, runs, timeout_ms, warm):
    browser = playwright.chromium.launch(args=[f'--host-resolver-rules={rule}'] if rule else [])
    rows, failed = [], 0
    try:
        shared = fresh(browser) if warm else None
        if warm:
            load(shared, url, timeout_ms)  # fills the cache; not counted
        for _ in range(runs):
            context = shared or fresh(browser)
            try:
                rows.append(load(context, url, timeout_ms))
            except Exception:  # noqa: BLE001 - a failed load is counted and reported, not raised
                failed += 1
            finally:
                if not warm:
                    context.close()
    finally:
        browser.close()
    return rows, failed


def line(name, rows, failed):
    fcp = sorted(r['fcp'] for r in rows if r['fcp'] is not None)
    if not fcp:
        return f'{name:10} n=0 failed {failed}'
    ttfb = statistics.median(r['ttfb'] for r in rows)
    form = sorted(r['form'] for r in rows if r['form'] is not None)
    over = sum(1 for v in fcp if v > 600)
    form_over = sum(1 for v in form if v > 600)
    kb = statistics.median(r['bytes'] for r in rows) / 1024
    shown = (f'sign-in form p50 {statistics.median(form):.0f} p95 {p95(form):.0f} max {form[-1]:.0f} ms; ' if form
             else 'sign-in form not seen; ')
    return (f'{name:10} n={len(rows)} first paint p50 {statistics.median(fcp):.0f} p95 {p95(fcp):.0f} max {fcp[-1]:.0f} ms; '
            f'{shown}first byte p50 {ttfb:.0f}; load p50 {statistics.median(r["load"] for r in rows):.0f}; '
            f'over 600 ms: paint {over}, form {form_over}; failed {failed}; '
            f'{kb:.1f} KB (median) in {rows[0]["resources"] + 1} requests; page "{rows[0]["title"]}"')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--runs', type=int, default=50)
    parser.add_argument('--warm', action='store_true', help='measure loads that reuse one cache, after one that fills it')
    parser.add_argument('--pin', type=pinned, action='append', default=[], metavar='NAME=ADDRESS')
    parser.add_argument('--timeout', type=int, default=30, help='seconds for one load')
    args = parser.parse_args(argv)
    if not 1 <= args.runs <= 200:
        parser.error('--runs must be 1 to 200')
    host = urlsplit(args.url).hostname
    if urlsplit(args.url).scheme != 'https' or not host:
        parser.error('--url must be an https address')
    from playwright.sync_api import sync_playwright
    paths = [('resolved', None)] + [(name, f'MAP {host} {address}') for name, address in args.pin]
    results, any_failed = {}, False
    with sync_playwright() as playwright:
        for name, rule in paths:
            rows, failed = measure(playwright, args.url, rule, args.runs, args.timeout * 1000, args.warm)
            results[name] = line(name, rows, failed)
            any_failed = any_failed or failed > 0 or not rows
    print(f'{args.url}, {args.runs} {"warm" if args.warm else "cold"} loads per path')
    for text in results.values():
        print(text)
    return 1 if any_failed else 0


if __name__ == '__main__':
    sys.exit(main())
