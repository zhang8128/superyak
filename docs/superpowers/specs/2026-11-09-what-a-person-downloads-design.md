# What a person downloads

Draft 1, 2026-11-09, Tardis. Board: `spec:what-a-person-downloads` (all hands). For a fresh reader on the Pi (law
section 3); Andy can veto. Built from goal 2's baseline (`docs/measures/goal-2.md`, eba97fcb on
`tardis/goal-2-baseline`) and Rio Grande's two points and doubt (city of AI, a57230dc).

## Why

Goal 2 says the web app's first paint takes under 600 ms. Through Funnel, which is what the Mac and every visitor from
outside reach, a signed-out visitor's first paint was 404 ms at p50 on 2026-11-09, and 2 of 10 cold loads were over
600 ms. Every load moves 276 KB, and the live home's headers say why:

- **Nothing is compressed.** No asset carries a `Content-Encoding`, even when the request accepts gzip.
- **Nothing may be cached.** The page and every asset say `cache-control: no-store`, so a browser fetches all of it on
  every load, not only the first.
- **One file is most of it.** `/assets/app.js` is 214,132 bytes of the 278,616 the page's four assets weigh.

Gzip at level 9 takes those four assets from 278,616 bytes to 74,243 (`app.js` to 55,715). With caching, a load after
the first fetches only the 2,203-byte page and the answers it asks for.

## Design

**1. Asset names that change with the content.**
- At start, the peer reads each file in `static/` once, keeps its bytes, and computes its hash: the first 16 hex
  characters of its SHA-256.
- The two pages that name assets, `index.html` and `consent.html`, are served with each `src="/assets/<name>"` and
  `href="/assets/<name>"` rewritten to `/assets/<name>?v=<hash>`. The rewrite happens once, at start.
- A test pins that every `/assets/` reference in those two pages is rewritten, and that no other file under `static/`
  names `/assets/`. A script that later fetches an asset by path fails that test, so it can't escape the scheme.

**2. Caching, decided in one place.** The security middleware that adds `SECURITY_HEADERS` to every response decides,
from the request alone:
- **A GET or HEAD for `/assets/<name>?v=<hash>`,** where `<hash>` is that file's hash from start, gets
  `cache-control: public, max-age=31536000, immutable` in place of `no-store`. Its body is the bytes read at start, so
  the content always matches the name.
- **Everything else keeps `no-store`,** exactly as today: the page, `consent.html` itself (it's reached by name, from
  the connector's redirect), an asset asked for with no `v` or a stale one, every `/api/` answer and every error.
- No route sets `cache-control` itself. A test pins that every response except the hashed asset answer carries exactly
  one `cache-control`, and that it is `no-store`. The connector's `/token` keeps relying on it.
- The other security headers (`nosniff`, the CSP, `no-referrer`) stay on every response, unchanged.

Each deploy restarts the peer (law section 2), so a new start serves a fresh page that names fresh hashes. An open tab
keeps the scripts it loaded, as it does today. A file edited on disk takes effect at the next start. That's a change for
someone editing the app by hand, and the same as every deploy already works.

**3. Compression, for assets only.**
- At start, the peer gzips each `.js` and `.css` file under `static/` at level 9, once, with the standard library.
- A request whose `Accept-Encoding` includes `gzip` gets those bytes, with `Content-Encoding: gzip` and
  `Vary: Accept-Encoding`. One without gets the plain bytes, also with `Vary`.
- A compressed answer gets its own `ETag`, distinct from the plain one, and answers no `Range` request: it's sent
  whole.
- **Nothing else is compressed:** no `/api/` answer, no page, nothing that carries a token or per-person text. `/api/me`
  carries `csrf_token`, and answers echo text a visitor typed. Compressing a secret beside chosen text, over TLS, is the
  BREACH pattern: the compressed length leaks the secret a byte at a time. The static files hold neither.
- Brotli would save more, but needs a new dependency. Not in this spec.

## Safety

It changes response headers on a public route, so it's safety code: a fresh reader, both suites on the Pi, and a
partner's yes before it lands. What the reader should check:
- **No secret in a cached or compressed body.** Every byte is a file from the checkout, read at start. None depends on
  the request, the session or the store.
- **Nothing else caches.** Only the exact `/assets/<name>?v=<current hash>` form, on GET or HEAD, changes its
  `cache-control`, and the decision reads only the request's path and query.
- **The public route's list is unchanged.** `/assets` is already open to a public request (public route spec 2), and the
  CSP's `'self'` covers the new query strings.

## Measures, before and after

**First paint** (`scripts/first_paint_timing.py`), tailnet and Funnel, at the same hour of the day:
- **Cold,** as the baseline was taken.
- **Warm:** the script gains `--warm`, a second load in the same browser context with its cache kept. That's the
  load a returning person gets.
- **Expected:** a cold load through Funnel moves about 76 KB, not 276. A warm load moves the page and its answers only.
  The goal is met when the Funnel p95 is under 600 ms, cold and warm.

**Room read,** for Rio Grande's doubt (a57230dc): curl pays a new TLS handshake on every read, and a browser keeps its
connection. The Funnel p95 of 525 ms may be mostly handshake. `scripts/room_read_timing.py` gains `--keep`: one curl
process reading the room `--runs` times over one connection. Both are reported side by side, so the handshake isn't
taken for the server. This spec doesn't change a room read, so its "after" checks only that nothing got slower.

The numbers go in `docs/measures/goal-2.md`, as rows under the baseline.

## Tests

- **The rewrite.** Each `/assets/` reference in `index.html` and `consent.html` carries its file's current hash.
  No other file under `static/` names `/assets/`. Changing a file and starting again changes its hash and its reference.
- **Caching.** The current `v` gets the immutable header and the start-time bytes. A stale `v`, no `v`, `/`,
  `consent.html`, a 404 under `/assets/`, and every `/api/` answer each get exactly one `cache-control: no-store`. A
  POST to an asset is refused, as today.
- **Compression.** With `Accept-Encoding: gzip`, a `.js` or `.css` asset comes gzipped, decompresses to the file's
  bytes, and carries `Vary` and its own `ETag`. Without it, the plain bytes. No `/api/` answer ever has a
  `Content-Encoding`, whatever the request accepts.
- **Headers.** `nosniff`, the CSP and `no-referrer` are on every response, as `test_public_route.py`'s `SECURITY`
  checks today, with `cache-control` checked separately for the one exception.
- **Public requests.** A public request gets the same assets and headers as a tailnet one, and nothing newly open.

## Not in this spec

- Brotli, HTTP/2, a service worker, or splitting `app.js`.
- A signed-in person's first paint. That needs the person's own browser session, so it's taken on the Mac.
- The room read's own speed.

## Whose yes

- **This spec:** a fresh reader on the Pi (law section 3). Tardis wrote it, so it isn't its reader.
- **The build:** Tardis builds it on a branch. A fresh reader on the Pi and Rio Grande's yes as partner, then Rio
  Grande merges and restarts the peer (law section 2).
