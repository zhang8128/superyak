# What a person downloads

Draft 3, final, 2026-11-09, Tardis. Board: `spec:what-a-person-downloads` (all hands). Approved by the fresh Pi
reader's scoped re-check of draft 2 (707c60d5), with its four shoulds and seven notes written in here and no further
read needed (law section 3); Andy can veto. Built from goal 2's baseline (`docs/measures/goal-2.md`, on
`tardis/goal-2-baseline`), Rio Grande's two points and doubt (city of AI, a57230dc), the reader's APPROVE WITH
CHANGES of draft 1 (0a4546eb), and its re-check of draft 2 (707c60d5). Tables at the end map every finding.

**Depends on** `tardis/goal-2-baseline` merging first: it holds `scripts/first_paint_timing.py` and
`docs/measures/goal-2.md`, which this spec measures with.

## Why

Goal 2 says the web app's first paint takes under 600 ms. Through Funnel, which is what the Mac and every visitor from
outside reach, a signed-out visitor's first paint was 404 ms at p50 on 2026-11-09, over 10 cold loads per path. Every
load moves 276 KB, and the live home's headers say why:

- **Nothing is compressed.** No asset carries a `Content-Encoding`, even when the request accepts gzip.
- **Nothing may be cached.** The page and every asset say `cache-control: no-store`, so a browser fetches all of it on
  every load, not only the first.
- **One file is most of it.** `/assets/app.js` is 214,132 bytes of the 278,616 the page's four assets weigh.

**What a person waits for.** The three scripts are `defer`, so first paint waits only for the page and `app.css`. But the
sign-in form (`#login-form`) is drawn by `app.js`. So the visible form, not first paint, is what the 214 KB holds back.
The measures below report both.

The standard library's gzip at level 9 takes the four assets to 74,237 bytes, and `app.js` to 55,749. With caching, a
load after the first fetches only the 2,203-byte page and the answers it asks for.

## Design

**1. One table, built at start, and nothing read from disk after.**
- At start, the peer reads every file in `static/` once and builds a table keyed by exact path. Each entry holds its
  bytes, its hash (the first 16 lowercase hex characters of its SHA-256), its gzip bytes for a `.js` or `.css` file
  (level 9, `mtime=0`, so the bytes are the same at every start), and its content type.
- **Content types** are today's: `text/javascript; charset=utf-8` and `text/css; charset=utf-8`, pinned by a test. With
  `nosniff`, a wrong one blocks the file.
- **The pages are rewritten once.** `index.html` and `consent.html` have each `src="/assets/<name>"` and
  `href="/assets/<name>"` rewritten to `/assets/<name>?v=<hash>`. Start refuses to finish if a page names a file the
  table doesn't hold.
- **Served from the table:** `/assets` becomes `app.mount('/assets', <an in-memory app>)`, which keeps the `/assets` key
  in `PUBLIC_ROUTES`. `/`, `/public/` and `/assets/index.html` serve the rewritten `index.html`. `/assets/consent.html`
  serves the rewritten `consent.html`. Names are looked up by exact key, with no normalization: `x/../app.js`,
  `//app.js` and `%61pp.js` are 404s, where StaticFiles served `app.js` for each.
- **The key is `raw_path`.** Starlette gives a mounted app the percent-decoded `path`, so `/assets/%61pp.js` arrives as
  `/assets/app.js`, and only `raw_path` keeps what was sent. The key is `raw_path` with `/assets/` removed, for the
  in-memory app and for the middleware's cache check alike. A request with no `raw_path` gets a 404.
- **The directory is an argument.** `create_app` takes the static directory, `STATIC_DIR` by default. Tests pass a
  temporary copy, and no test writes under the package. The live peer on the Pi serves `static/` from the checkout the
  suites run in, so a test writing there would serve its bytes to visitors during a run.
- **Built once per directory per process.** A table build takes 14.5 ms on the Pi. Across about 2,270 tests that each
  call `create_app`, that would add half a minute or more to a run, so the table is cached per directory.
- **One change for whoever edits the app by hand:** under `make home-demo` or `serve`, an edit to `app.js` shows only
  after a restart. No test, script or make target writes under `static/`.
- **Why not from disk.** The live peer runs from the checkout a merge updates. Between a merge and its restart, and again
  after a law-2 revert, the disk holds other bytes than the ones read at start. Served from disk, new bytes would go out
  as immutable under an old hash, and a revert would pin a visitor to the wrong script for a year. A test overwrites a
  file after `create_app`, and every response stays the same.

**2. Caching: which answers, decided from the request and the status.** The security middleware gives an answer
`cache-control: public, max-age=31536000, immutable`, in place of `no-store`, only when all of these hold:
- the path is an exact key for a `.js` or `.css` file in the table, never an `.html` file;
- the query string is `v=` and exactly 16 lowercase hex characters, byte for byte, with no other parameter and no
  second `v`, and those characters are that file's hash;
- the method is GET or HEAD;
- the status is 200 or 304. A 404 or a 5xx at a current-hash URL stays `no-store`, since a year's freshness would make
  even an error storable (RFC 9111).

Everything else keeps exactly one `cache-control: no-store`, as today: the pages, `consent.html`, an asset asked for with
no `v` or a stale one, every `/api/` answer and every error. No route sets `cache-control` itself. An immutable answer
never carries `Set-Cookie`. `door.py` and `listener.py`, which set their own `no-store`, are untouched.

**3. Every response carries the security headers, refusals included.** On main, BrowserBoundary's own 403s (an unknown
Host, a write with no Origin) and its 413 go out on the raw `send`, and the 500 handler runs outside it. None of them
carries `nosniff`, the CSP, `no-referrer` or `no-store`. This build sends them through the same headers, so "every
response carries them" becomes true, and a test checks each of the four. "Every response" means every answer the app
gives: uvicorn's own 400s for malformed HTTP never reach the app.

**4. Compression, for `.js` and `.css` assets only.**
- **Choosing.** The request's `Accept-Encoding` is parsed as a list of tokens, case-insensitively, allowing spaces around
  `;` and `=` and a capital `Q`. `gzip` is chosen when it appears with no `q`, or with a `q` above 0. `gzip;q=0` means
  no. A `q` that isn't an RFC 9110 qvalue counts as 0 and never raises, so `gzip;q=abc` from a stranger is a plain
  answer, not a 500.
- **The answer.** Gzip bytes with `Content-Encoding: gzip`, or the plain bytes. Either way it carries `Vary:
  Accept-Encoding`.
- **ETags.** `"<hash>"` for the plain bytes and `"<hash>-gz"` for the gzip ones. `If-None-Match` is compared with the
  ETag of the variant this request's `Accept-Encoding` selects, as a whole header. A 304 carries that ETag, `Vary`, and
  the same `cache-control` the 200 would. A weak `W/"..."`, a list or `*` doesn't match, and gets a 200. That's
  intended, and safe.
- **Ranges.** `Range` is ignored on every asset: a whole 200, with no `Accept-Ranges`.
- **HEAD** gives each variant's headers and its `Content-Length`, with no body.
- **The real path.** tailscaled's proxy might add gzip to a request that carries none and decode the answer itself,
  which would leave plain bytes under the gzip ETag. Those are the right bytes for that client, and its revalidation
  goes back through the same proxy, so the ETag still matches. The build checks this through Funnel and the tailnet with
  no `Accept-Encoding` sent, and reports what it found.
- **Nothing else is compressed.** That covers every response except a `.js` or `.css` asset: the pages, `consent.html`,
  `/api/`, `/authorize`, `/token`, `/mcp`, `.well-known`, `/public/layers/.../files/...`, and errors. `/api/me` carries
  `csrf_token`, and answers echo text a visitor typed. Compressing a secret beside chosen text over TLS is the BREACH
  pattern. The `.js` and `.css` files hold neither.
- Brotli would save more, but needs a new dependency. Not in this spec.

## Safety

It changes response headers on a public route, so it's safety code: a fresh reader, both suites on the Pi, and a
partner's yes before it lands. What the reader should check:
- **No secret in a cached or compressed body.** Every byte is a file from the checkout, read at start, and none depends
  on the request, the session or the store.
- **Nothing else caches,** by the four conditions above.
- **Nothing newly reachable.** The public route's list is unchanged, and exact-key lookup makes `/assets` stricter than
  StaticFiles.

## Measures, before and after

**`scripts/first_paint_timing.py`** gains:
- `--warm`: a second load in the same browser context, with its cache and connection kept, reporting its own bytes;
- a form-visible time: an init script's MutationObserver takes `performance.now()` when `#login-form` is attached, so
  it's noted in the page, not by polling after `load`;
- a default of 50 loads per path, since at 10 the p95 is the slowest single load.

It uses no Playwright route: routing turns the browser's HTTP cache off, and a warm load then fetches every asset again.

Before this build, the baseline is taken again that way, cold and warm, tailnet and Funnel, with the hour recorded.
After the build, the same runs are taken at a similar hour.

**What judges the build** is what it's built to change:
- **cold bytes,** about 76,000, down from 276 KB;
- **warm bytes,** the page and its API answers only;
- **the form-visible time, cold,** through Funnel and the tailnet.

Goal 2's first-paint line, a Funnel p95 under 600 ms cold and warm, is reported beside them as status. First paint waits
only for the page and `app.css`, so its p95 may already be under 600 ms before the build, and it can't judge the build.

**Room read,** for Rio Grande's doubt (a57230dc): `scripts/room_read_timing.py` gains `--keep`, one curl process reading
`--runs` times over one connection, reported beside today's fresh connection per read. Clients already get HTTP/2 on
both paths. This spec doesn't change a room read, so its "after" checks only that nothing got slower.

The numbers go in `docs/measures/goal-2.md`.

## Tests

- **The table.** On a temporary copy passed to `create_app`, a file overwritten after `create_app` changes no response.
  Start refuses a page that names a missing file. `x/../app.js`, `//app.js` and `%61pp.js` are 404s, through the real
  `raw_path`. No test writes under the package's `static/`.
- **References.** Each `/assets/` reference in the two pages carries its file's current hash. No file under `static/`
  except those two pages names another static file's basename, which catches `import './x.js'`, `url(x.woff2)` and
  `new Worker(...)`.
- **Caching.** The current `v` on a `.js` or `.css` file gets the immutable header and the start-time bytes. Each of these
  gets exactly one `cache-control: no-store`: a stale `v`, no `v`, `v` in capitals, a second parameter, `?v=` on an
  `.html` file, `/`, `/public/`, `consent.html`, a 404 under `/assets/`, and every `/api/` answer. No immutable answer
  carries `Set-Cookie`.
- **Security headers everywhere.** `nosniff`, the CSP and `no-referrer` are on every response, as
  `test_public_route.py`'s `SECURITY` checks, including the unknown-Host 403, the no-Origin 403, the 413 and a 500.
- **Compression.** With `Accept-Encoding: gzip`, a `.js` or `.css` asset comes gzipped, decompresses to the file's bytes,
  and carries `Vary` and `"<hash>-gz"`. The test reads the raw stream to check the bytes and `Content-Length`, since
  httpx's TestClient decodes bodies. With none, or with `gzip;q=0`, `gzip;q=abc` or `GZIP ; Q=0`, the plain bytes and
  `"<hash>"`. "With none" removes the header, since TestClient sends `gzip, deflate` by default. No other response ever
  has a `Content-Encoding`, whatever the request accepts: the routes listed above.
- **Conditional requests, ranges, HEAD.** `If-None-Match` with the selected variant's ETag gives a 304 with that ETag,
  `Vary` and the same `cache-control`. The other variant's ETag gives a 200. `Range` gives a whole 200 with no
  `Accept-Ranges`. HEAD gives each variant's headers and `Content-Length` with no body.
- **Content types,** pinned to today's.
- **Public requests.** A public request gets the same assets and headers as a tailnet one, and nothing newly open.

## Not in this spec

- Brotli, a service worker, or splitting `app.js`.
- A signed-in person's first paint. That needs the person's own browser session, so it's taken on the Mac.
- The room read's own speed.

## Whose yes

- **This spec:** the fresh reader on the Pi (law section 3). Tardis wrote it, so it isn't its reader.
- **The build:** Tardis builds it on a branch. A fresh reader on the Pi and Rio Grande's yes as partner, then Rio Grande
  merges and restarts the peer (law section 2).

## The reader's findings on draft 1

| Finding | Draft 2 |
|---|---|
| Must 1, where the bytes come from | One start-time table; an in-memory app at `/assets`; pages from it too; exact keys; nothing read after start. |
| Must 2, no page is immutable | Immutable only for `.js` and `.css`; `/assets/index.html` serves the rewritten page, `no-store`. |
| Must 3, the match and the status | Exact query `v=<16 lowercase hex>`, exact key, GET or HEAD, status 200 or 304. |
| Must 4, refusals lack the headers | The boundary's 403s and 413 and the 500 carry them; each is tested. |
| Should 1, conditional requests and ranges | ETags named; `If-None-Match` per variant; 304's headers; `Range` ignored; HEAD tested. |
| Should 2, `Accept-Encoding` parsing | Tokens, case-insensitive, `q=0` honored; the proxy checked on the real path. |
| Should 3, compression tests | Widened to every response but `.js` and `.css` assets. |
| Should 4, the reference test | No static file but the two pages names another's basename. |
| Should 5, measures | 50 loads per path, the hour, form visible, warm before and after. |
| Should 6, dependency | `tardis/goal-2-baseline` merges first. |
| Notes 1 to 7 | Standard-library sizes and `mtime=0`; HTTP/2 noted; content types pinned; `door.py` and `listener.py` untouched; no `Set-Cookie` on immutable; start refuses a missing file; consent settled. |

## The re-check's findings on draft 2

| Finding | Draft 3 |
|---|---|
| Should 1, the exact key | `raw_path` with `/assets/` removed, for the app and the middleware; none gives a 404. |
| Should 2, the overwrite test | `create_app` takes the directory; tests use a temporary copy; none writes under the package. |
| Should 3, warm and form-visible | No Playwright route; an init script's observer; warm loads report their own bytes. |
| Should 4, what judges the build | Cold bytes, warm bytes and cold form-visible time; first paint's line reported as status. |
| Note 1, `Accept-Encoding` | A bad `q` counts as 0 and never raises; spaces and capital `Q`; both cases tested. |
| Note 2, `If-None-Match` | Whole-header compare; weak, list and `*` fall to a 200, as intended. |
| Note 3, TestClient | "With none" removes the header; the gzip test reads the raw stream. |
| Note 4, every response | Every answer the app gives; uvicorn's own 400s are outside it. |
| Note 5, the proxy | Settled: report only. |
| Note 6, the cost | Cached per directory per process. |
| Note 7, start-only reads | Settled; the restart-to-see-an-edit change is said. |
