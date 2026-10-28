# A visitor can ask for access: design (draft for Andy)

**Status:** draft, revision 1 (2026-10-28, Tardis). **Nothing is built until Andy says yes (D1).** Then a fresh reviewer
approves it (law section 3), and since it changes the public route, each partner says yes too (public route spec).

**Why.** Goal 4, "people outside us use it", and Tardis's T4. A cold walk of the public address on 2026-10-28 used a
fresh browser with no cookies, through Funnel's ingress. "What is this?" was half answered: the sign-in page explains
Superyak in general, and tardis/front-page-copy adds that it's a prototype, with a link to the README. "How do I join?"
was not answered for anyone without an invitation. The page offers only *Sign in* and *Use an invitation*. The door
takes access requests, but only as an API (`POST /api/access-requests`, used by `make dock --request`), so a person at
Andy's table with a phone has no way to ask.

## 1. What a visitor is told, and what is kept (first, as Rio Grande asked)

Before they send anything, the page says, in plain words:
- **Who reads it:** "Andy, who runs this station, reads your request. Nobody else does." The admins who can decide
  requests on this station are the readers; on Andy's station that is Andy.
- **What happens next:** "Nothing happens until he answers. You get no account, no email and no messages from us
  until then."
- **What is kept, and for how long:** your name, contact and note, for 7 days while the request waits. After a
  request is approved, denied or expired, its contact and note are deleted after 30 days, and its name is kept with
  the decision for the station's record.
- **What not to send:** "Please don't put patient information or anything private in the note."

**This needs one change to the door.** Today nothing ever deletes a decided or expired request's contact or note
(`access_requests` has no purge). The build adds one: a daily sweep, as the imprint sweep does, clears `contact` and
`note` 30 days after a request is decided or expires. The 30 days are D2.

## 2. Where it lives

**On the door's own origin, not the lighthouse's.** The access-request route is public only through `superyak-door`
(port 7436, published by Funnel). The lighthouse's `PUBLIC_ROUTES` doesn't hold it, and its CSP is `default-src
'self'`. So the form is one small static page served by the door, posting to the door's own route. The lighthouse
keeps its boundary as it is, and adds only a link. Rio Grande's point in all hands; Tardis leans the same way.
- The door gains `GET /` (or `/ask`): one HTML page, a stylesheet and one script, all from the door. It has no
  cookies and no third-party requests. It posts JSON to the existing `POST /api/access-requests`.
- After sending, the page shows the request's short id and a private status link, which carries the request's
  secret. It also shows the status as it changes: waiting, approved, denied, expired. That's
  `GET /api/access-requests/{key}?secret=…`, which exists already.
- **Approved:** the page shows the next step that approval gives. Today that's an invitation, whose link the
  visitor opens on the lighthouse (`#activate?token=…`), the path the README's "If Andy invited you" describes.

## 3. The link from the lighthouse, and whose home it is

The sign-in page gains a line under *Use an invitation*: "New here? **Ask for access**". It links to the door's page,
and appears only when the station sets a door address. Every peer serves this page, so the words stay generic by
default. A station's own **welcome line**, set by its owner, may say whose home it is: "Andy's station" (D3). That also
fixes the footnote's "your Superyak peer", which reads wrong for a stranger (Rio Grande's note on front-page-copy).

## 4. Limits

The door keeps its own limits: 16 KiB a request, 20 requests an hour across the station, and 50 waiting at once
(`HOURLY_LIMIT`, `PENDING_LIMIT`). The page adds no route the door didn't already serve. Name and contact are
required and the note is optional, with the door's existing caps.

## 5. Decisions for Andy

- **D1:** may a stranger ask for access from the front page at all? Today the README says "by invitation only; to
  ask, say hello in Discussions". A yes changes that welcome. A no keeps the door CLI-only, and the README's
  Discussions line stays the way in.
- **D2:** how long a decided or expired request's contact and note are kept. The draft says 30 days.
- **D3:** the welcome line's words for his station.

## 6. Acceptance

A fresh cold walk, the same way as 2026-10-28's, answers "what is this?" and "how do I join?" in one click each.
A request sent from the page appears in `make station-pending` with its short id. Andy approves or denies it as today.
The sweep clears contact and note at day 30. And the page makes no request off the door's origin.

## Out of scope

Email or SMS notifications, accounts before approval, CAPTCHAs (the door's limits come first), and translations.
