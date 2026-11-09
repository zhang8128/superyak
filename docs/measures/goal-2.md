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
