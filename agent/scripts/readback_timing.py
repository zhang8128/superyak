"""The lessons hook's read-back on a real transcript (own lessons spec, "Finding the boundary"; plan Task 3): how long
`transcript_ids` over the whole file, `last_boundary`, and `transcript_ids` from the boundary take, each as p50 and p95
against the limit of the event that runs it, with the margin left. Read-only: it opens the transcript and nothing else.

A prompt in a compacted session runs `last_boundary` then `transcript_ids(start=offset)` within 150 ms (LIMITS). The
2 s events run the whole-file read for `seen` plus the same two for `window_seen` within 2 s; a compact SessionStart
runs the whole-file read alone. Run with `python3 -I agent/scripts/readback_timing.py --transcript <path>`."""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from superyak_agent import lessons_hook as lh  # noqa: E402 - the checkout's own hook, after the path line above

GENEROUS = 60.0  # seconds: a deadline the measure never meets, so each call does its whole work


def timed(fn, runs, timer=time.perf_counter):
    """Each run's milliseconds, and the last run's result."""
    out, ms = None, []
    for _ in range(runs):
        start = timer()
        out = fn()
        ms.append((timer() - start) * 1000)
    return sorted(ms), out


def pct(values, q):
    return values[min(len(values) - 1, int(q * len(values)))]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='readback_timing')
    parser.add_argument('--transcript', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=20)
    args = parser.parse_args(argv)
    path = str(args.transcript)

    def deadline():
        return time.monotonic() + GENEROUS

    whole, ids = timed(lambda: lh.transcript_ids(path, deadline()), args.runs)
    bound, offset = timed(lambda: lh.last_boundary(path, deadline()), args.runs)
    tail, tail_ids = timed(lambda: lh.transcript_ids(path, deadline(), start=offset or 0), args.runs)
    # Each path's p50 and p95 as the sum of its calls' own: a bound on the path's, since the slowest runs needn't coincide.
    prompt = [pct(bound, q) + pct(tail if offset is not None else whole, q) for q in (0.5, 0.95)]
    two_s = [pct(whole, q) + pct(bound, q) + pct(tail, q) for q in (0.5, 0.95)]
    size = args.transcript.stat().st_size
    lines = [f'transcript {size / 2**20:.1f} MiB; last boundary at {offset} '
             f'({(size - (offset or 0)) / 2**20:.1f} MiB from the end); {args.runs} runs each',
             f'transcript_ids, whole file: p50 {pct(whole, .5):.1f} ms, p95 {pct(whole, .95):.1f} ms, {len(ids)} ids',
             f'last_boundary: p50 {pct(bound, .5):.1f} ms, p95 {pct(bound, .95):.1f} ms',
             f'transcript_ids from the boundary: p50 {pct(tail, .5):.1f} ms, p95 {pct(tail, .95):.1f} ms, '
             f'{len(tail_ids)} ids']
    ok = True
    for name, (p50, p95), limit in (('a prompt (boundary + tail)', prompt, lh.LIMITS[lh.PROMPT]),
                                    ('a 2 s event (whole + boundary + tail)', two_s, lh.LIMITS[lh.FAILURE])):
        margin = limit * 1000 - p95
        ok = ok and margin > 0
        lines.append(f'{name}: p50 {p50:.1f} ms, p95 {p95:.1f} ms of {limit * 1000:.0f} ms; margin {margin:.1f} ms '
                     f'({margin / (limit * 10):.0f}% of the limit)')
    if offset is None:
        lines.append('no boundary: a prompt reads from the start, as the whole-file line shows')
    print('\n'.join(lines + ['PASS' if ok else 'FAIL']))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
