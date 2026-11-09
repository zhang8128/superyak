# Goal 2's measures, before and after each change

Goal 2 (docs/goals.md): a room read takes under 400 ms (`scripts/room_read_timing.py`), and the web app's first paint
takes under 600 ms (`scripts/first_paint_timing.py`), measured before and after each change. Each row says where it was
taken, since the Mac's resolver sends it through Funnel and a machine on the tailnet goes straight to the Pi.

## Baseline, 2026-11-09, main 7d80c067, from Tardis (not the Mac)

Taken by Tardis while Serenity, which took the Mac's readings, is out. Funnel's path is pinned to its public address
(208.111.34.11), which is what a visitor from outside reaches.

**Room read,** all hands, 100 messages (the web app's page), 20 reads per path, as the ship `tardis`:

| Path | p50 | p95 | max | TLS p50 | first byte p50 | over 1 s |
|---|---|---|---|---|---|---|
| Tailnet (this machine's resolver) | 60 ms | 73 ms | 73 ms | 25 ms | 56 ms | 0 |
| Funnel | 316 ms | 525 ms | 682 ms | 137 ms | 218 ms | 0 |

curl opens a new connection for every read and pays for TLS each time, which a browser keeping its connection doesn't.
So the Funnel row reads pessimistic, by up to its TLS p50.

**First paint,** the sign-in page a signed-out visitor gets, cold cache, headless Chromium, 10 loads per path:

| Path | p50 | p95 | max | first byte p50 | load p50 | over 600 ms | transferred |
|---|---|---|---|---|---|---|---|
| Tailnet | 100 ms | 136 ms | 136 ms | 29 ms | 95 ms | 0 of 10 | 276 KB in 7 requests |
| Funnel | 404 ms | 604 ms | 604 ms | 212 ms | 628 ms | 2 of 10 | 276 KB in 6 requests |

A first run a few minutes earlier, by the same method, gave a tailnet p50 of 84 ms and a Funnel p50 of 402 ms, with a
Funnel max of 700 ms.

**Not measured here:**
- A signed-in person's first paint. That needs the person's own browser session, which a ship doesn't have, so it's
  taken on the person's machine.
- The Mac's own path and browser.
- Either measure while ships post and watchers poll.

**What it points at:** every cold load transfers 276 KB, and through Funnel that comes to about 400 ms before first
paint. Read from the live home's headers on the same day, with `Accept-Encoding: gzip, br` sent:
- **Nothing is compressed.** No asset carries a `Content-Encoding`.
- **Nothing may be cached.** The page and every asset say `cache-control: no-store`, so a browser fetches them all
  again on every load, not only the first.
- **One file is most of it.** `/assets/app.js` is 214,132 bytes; `app.css` 26,540, `dashboard.js` 19,996,
  `research.js` 17,948, and the page 2,203.

That's `spec:what-a-person-downloads`. Its "after" goes in a row below.

## Before the downloads change, 2026-11-09 20:52Z, main e7b8fef2, from Tardis

The same method with the script's second version, 50 loads per path, Funnel pinned to 208.111.34.11. It adds the first
frame after the sign-in form's heading joins the page, since first paint is only the loading shell ("Opening this
home…"). Warm loads reuse one browser context after a load that fills it, the way a person comes back.

| Path | Cache | first paint p50 / p95 / max | sign-in form p50 / p95 / max | first byte p50 | over 600 ms (paint, form) | transferred, each load |
|---|---|---|---|---|---|---|
| Tailnet | cold | 96 / 116 / 140 ms | 121 / 141 / 148 ms | 27 ms | 0, 0 of 50 | 300 KB in 7 requests |
| Funnel | cold | 256 / 528 / 1,336 ms | 344 / 937 / 1,596 ms | 128 ms | 2, 4 of 50 | 300 KB in 6 requests |
| Tailnet | warm | 64 / 84 / 112 ms | 94 / 130 / 143 ms | 7 ms | 0, 0 of 50 | 300 KB in 7 requests |
| Funnel | warm | 148 / 368 / 444 ms | 263 / 774 / 1,011 ms | 32 ms | 0, 5 of 50 | 300 KB in 6 requests |

**A warm load still moves all 300 KB.** Every file says `no-store`, so the browser keeps nothing. A warm load is
faster only because the connection is already open (first byte 7 ms rather than 27 on the tailnet). With
`Accept-Encoding: gzip, br`, nothing is compressed: `/assets/app.js` is 238,279 bytes now (214,132 at 7d80c067),
`app.css` 27,007, `dashboard.js` 19,996, `research.js` 17,948 and the page 2,203.

**What a visitor waits for is the form, not the paint.** Through Funnel, the form lands about 90 ms after first paint
at the median, and it crosses 600 ms in 4 to 5 loads of 50 where paint crosses it in 0 to 2. So the downloads change is
judged on both columns, warm and cold.
