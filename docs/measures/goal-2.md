# Goal 2's measures, before and after each change

Goal 2 (docs/goals.md): a room read takes under 400 ms (`scripts/room_read_timing.py`), and the web app's first paint
takes under 600 ms (`scripts/first_paint_timing.py`), measured before and after each change. Each row says where it was
taken, since the Mac's resolver sends it through Funnel and a machine on the tailnet goes straight to the Pi.

## Baseline, 2026-11-09, main 7d80c067, from Tardis (not the Mac)

**An older script, not comparable to the tables below.** First paint used the script's first version (eba97fcb), 10
cold loads per path and no form time; the room read used `scripts/room_read_timing.py` as it is on main, 20 reads per
path. **Where:** Tardis's machine, an Intel N150 mini PC (4 cores) on Ubuntu 26.04.1 (Linux 7.0.0-38), wired, on a home connection.
Playwright 1.62.0 with headless Chromium 151.0.7922.34, unchanged since 7d80c067.

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

"2 of 10 over 600" beside a p95 and max of 604 means both of those loads fell between 600 and 604 ms. Their raw values
weren't kept. A first run a few minutes earlier, by the same method, gave a tailnet p50 of 84 ms and a Funnel p50 of 402 ms, with a
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

Taken with the script's second version (fc8097a4), 50 loads per path, Funnel pinned to 208.111.34.11. Cold:
`--pin funnel=208.111.34.11`, 20:52:31Z to 20:53:37Z. Warm: `--warm --pin funnel=208.111.34.11`, 20:53:37Z to
20:54:37Z. **Where:** Tardis's machine, an Intel N150 mini PC (4 cores) on Ubuntu 26.04.1 (Linux 7.0.0-38), wired, on a home connection.
Playwright 1.62.0 with headless Chromium 151.0.7922.34, unchanged since 7d80c067.

It adds the first frame after the sign-in form's heading joins the page, since first paint is only the loading shell
("Opening this home…"). Warm loads reuse one browser context after a load that fills it, the way a person comes back.
"Cold" means a cold cache: the browser process, its DNS and the OS's state carry over between loads. No load failed.

| Path | Cache | first paint p50 / p95 / max | sign-in form p50 / p95 / max | first byte p50 | over 600 ms (paint, form) | failed | transferred, each load |
|---|---|---|---|---|---|---|---|
| Tailnet | cold | 96 / 116 / 140 ms | 121 / 141 / 148 ms | 27 ms | 0, 0 of 50 | 0 | 300 KB in 7 requests |
| Funnel | cold | 256 / 528 / 1,336 ms | 344 / 937 / 1,596 ms | 128 ms | 2, 4 of 50 | 0 | 300 KB in 6 requests |
| Tailnet | warm | 64 / 84 / 112 ms | 94 / 130 / 143 ms | 7 ms | 0, 0 of 50 | 0 | 300 KB in 7 requests |
| Funnel | warm | 148 / 368 / 444 ms | 263 / 774 / 1,011 ms | 32 ms | 0, 5 of 50 | 0 | 300 KB in 6 requests |

**Why 7 requests on the tailnet and 6 through Funnel:** the page asks `/api/local-demo` first. On the tailnet that
answers 404, so the page goes on to ask `/api/me` (401) before it shows the form. Through Funnel, `/api/local-demo`
answers 401 itself, and the page shows the form without asking `/api/me`.

**A warm load still moves all 300 KB.** Every file says `no-store`, so the browser keeps nothing. A warm load is
faster probably because the connection is already open (first byte 7 ms rather than 27 on the tailnet). TLS session and
DNS reuse may also count. With
`Accept-Encoding: gzip, br`, nothing is compressed: `/assets/app.js` is 238,279 bytes now (214,132 at 7d80c067),
`app.css` 27,007, `dashboard.js` 19,996, `research.js` 17,948 and the page 2,203.

**What a visitor waits for is the form, not the paint.** Through Funnel, the form lands about 90 ms after first paint
at the median, and it crosses 600 ms in 4 to 5 loads of 50 where paint crosses it in 0 to 2. So the downloads change is
judged on both columns, warm and cold.

## Where the tail goes, 2026-11-09 23:49Z to 23:54Z, main 29be1533, from Tardis

Rio Grande asked: if warm loads miss 600 ms as often as cold ones, is the tail in the first byte or in the page's
scripts? The script's third version (this commit) answers with `--tail 6`, which splits each path's 6 slowest loads into
the moments each part ended. Cold: `--tail 6 --pin funnel=208.111.34.11`, 23:49:52Z to 23:51:47Z. Warm: `--warm --tail 6
--pin funnel=208.111.34.11`, 23:51:58Z to 23:53:37Z. Same machine, network and browser build as above. No load failed.

| Path | Cache | first paint p50 / p95 | sign-in form p50 / p95 / max | first byte p50 | form over 600 ms |
|---|---|---|---|---|---|
| Tailnet | cold | 96 / 116 ms | 125 / 139 / 329 ms | 31 ms | 0 of 50 |
| Funnel | cold | 642 / 1,840 ms | 1,077 / 2,652 / 7,053 ms | 399 ms | 43 of 50 |
| Tailnet | warm | 48 / 192 ms | 80 / 217 / 303 ms | 5 ms | 0 of 50 |
| Funnel | warm | 230 / 1,072 ms | 733 / 3,337 / 7,202 ms | 59 ms | 30 of 50 |

**Funnel was about three times slower than at 20:52Z,** on the same machine, while the tailnet path didn't move. So
Funnel's link varies by the hour. A "before" and an "after" are compared only when taken in the same hour, and better in
turns.

**The tail is the files, not the first byte or the scripts.** In the 6 slowest warm loads through Funnel, the connection
was already open, the first byte came at 171 to 572 ms, and the page's own HTML was done 3 to 4 ms later. Then its files
finished at 2,118 to 6,821 ms. The time from the last file to the form, which covers parsing, running the scripts and the
one API call, was 67 to 381 ms. Cold loads split the same way, with 319 to 874 ms more to connect. On the tailnet, the slowest
loads spent up to about 230 ms on the page's HTML and none of them reached 600 ms.

So when the link is slow, the 300 KB is what a visitor waits for, warm or cold. Warm is no better at the tail because
`no-store` makes it move the same bytes. **The downloads change claims the tail, and these rows test that claim:** with
the assets cached, a warm load's files should end near its first byte. With them compressed, a cold load's files should
come to about a quarter of today's bytes. If the Funnel p95 doesn't fall in a same-hour comparison, the claim is wrong.
