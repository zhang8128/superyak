# Superyak Peer

A self-hosted personal home for private chats and sharing layers across care
circles, projects, and organizations. Accounts, drafts, active releases, files,
and delivery history live on each independently operated peer. There is no
mandatory global account service, central database, CDN, or paid model API.

This first application uses fictional demonstration participants. It supports
explicit uploads and selected-source interchange; live medical-record providers,
clinical validation, richer help/recovery, and HPC execution are future work.
Hosts can read their own plaintext stores. Peer TLS and Ed25519 signatures protect
transport and authenticate paired hosts; this is not browser-to-browser E2EE.
Withdrawal stops access on the local peer and queues removal for paired recipients.
Offline hosts may still show the release until they acknowledge withdrawal; it
cannot erase someone else's previously saved copy.

## Install and run

Use Linux or macOS, Python 3.11 or later, and uv. This directory is independently
installable, including after extracting the standalone source archive:

```sh
uv sync --locked
uv run --locked python -m superyak_peer demo
uv run --locked python -m superyak_peer serve --local-demo --data-dir .engram/home-demo
```

Open **http://127.0.0.1:7435** to enter the patient dashboard without a password.
The account menu offers one-click switches to `family`, `doctor`, and `organizer`.
Save work before switching accounts. `--local-demo` only accepts seeded demo state,
loopback binds, origins, and client connections. Omit it to require normal sign-in;
do not proxy or forward the password-free demo for others to access.
Fictional credentials stay in `.engram/home-demo/demo-credentials.json`, a private
mode-0600 file; they are never sent to the browser. Personal notes begin as private drafts. Saving changes a draft;
activating releases exactly that saved version to the displayed audience.
The demo command validates repeated runs and refuses unrelated/incomplete state.
Keep the terminal running while using the application; Ctrl-C stops that server.

The backend also provides a private data-source catalog: register uploaded files
or selected-record collections, correct source names, pause/resume imports, and
inspect success/failure receipts. CSV and JSON datasets are accepted alongside
the existing supported file types, with original bytes preserved. Repeated import
requests return their existing successful receipts. No source is shared merely
because it is registered or enabled. See the [data-source API examples](API.md#backend-data-sources).
Open **Research & data** to create a source, preview selected files or record
documents, import privately, inspect source text and provenance, correct details,
pause/resume imports, and read import receipts. A failed acknowledgement can be
retried with the same request identity. **Start evidence review** creates a private
layer with a source citation, an excerpt (up to 12,000 characters), and review
prompts; it does not run a model or create a validated evidence assessment.
Automatic external feed syncing remains future work.

To provision an ordinary peer instead:

```sh
uv run --locked python -m superyak_peer init --username owner --name 'Peer owner'
uv run --locked python -m superyak_peer serve
```

The owner password is prompted privately. Default ordinary state is
`.engram/home`. The local owner can issue expiring one-use invitations; account
administration grants no access to another person's private content. Back up the
entire state directory securely while the server is stopped, including identity
keys and the database. General automated migration, key recovery/rotation, password
reset, and unattended service installation are outside this release.

In the parent repository, equivalent entry points are `make setup-peer`,
`make check-peer`, `make home-demo`, `make home`, and `make peer-bundle`.
`HOME_DATA`, `HOME_DEMO_DATA`, `HOME_PORT`, and `HOME_ARGS` select isolated state,
port, and optional serve arguments. These commands never start research workers.

## Set up the first super admin

Stop the peer before upgrading its installed package; retain a backup of its whole
state directory. Startup adds role columns and activation/audit tables, preserving
existing IDs, passwords, drafts, and permissions. Existing owners remain admins;
they are not automatically promoted to super admins.

Run the trusted local command once, using the same data directory as your server:

```sh
uv run --locked python -m superyak_peer bootstrap-super-admin \
  --data-dir /private/path/home --username admin@example.org --name 'First admin' \
  --activation-file /private/path/first-admin-activation.json
```

This reserves an account and writes a mode-0600 file with a one-use token, exact
username/name, and seven-day expiry. It creates no usable initial password, sends
no email, and refuses an existing output file or a second bootstrap. The recipient
opens **Use an invitation**, enters the supplied fields, and chooses their own
password before signing in. Email addresses can be usernames; this does not verify
mailbox ownership. Deliver the activation token through a trusted channel.

If the first activation expires or is lost, repeat the command with the same
username and name, a new output file, and `--renew-activation`. This keeps the
pending identity and invalidates all previous activation tokens. It refuses to
replace an already activated super admin or renew a different identity.

Activation links use `/#activate?token=TOKEN&username=USERNAME&name=NAME`, with each
value URL-encoded. The browser removes the fragment from its address immediately
and opens the activation form, including on a local demo. Use the real peer's
reachable HTTPS address when handing links to remote participants. The loopback
demo is only usable on its host; do not expose password-free demo mode remotely.

In **Connections → Account rights**, a super admin selects a person's role,
reviews the named account and rights, and confirms the change:

| Role | Administrative rights |
| --- | --- |
| Participant | Own work and explicitly granted sharing access |
| Admin | Invite participants, list account metadata, and manage peer pairing |
| Super admin | Admin rights plus granting/revoking admin and super-admin roles |

Role changes record who changed whom, old/new roles, version, and time. Changes
take effect in existing sessions; demotion to participant also revokes their unused
invitations. The last active super admin cannot be demoted. Fictional password-free
demo accounts cannot receive super-admin rights. No role grants access to other
people's private content or authority over another independently operated peer.

## Pair two peers

See [API.md](API.md) for provisioning, routes, state, and audience semantics;
[PROTOCOL.md](PROTOCOL.md) specifies the signed envelope/card schema, independent
origins, receipts, bounded retry and revocation behavior. An operator pairs a card
by typing its pairing code, read off the exporting machine's own screen (`card`
writes it to its terminal only; `pair --as` reads it from a real terminal). There is no
automatic discovery, implicit account merge, or network-wide owner.

```sh
uv run --locked python -m superyak_peer card --username owner --endpoint https://peer.example:7435 > owner-card.json
uv run --locked python -m superyak_peer serve --peer-tls --host 127.0.0.1 --origin https://peer.example:7435 --federation-endpoint https://peer.example:7435 --sync
```

A peer dials another by its card's exact certificate pin, so the certificate's names
and dates don't matter to peers. A browser still checks names: use the actual
hostname on the first card export if people will open that address. The example
requires an operator-provided route/tunnel to the loopback listener. Remote binds
require TLS. Trust the generated certificate through your browser/OS explicitly; do
not bypass certificate verification. Import and pair each other's card in Connections
using the local setup owner. Pairing addresses the named remote participant; it grants
no content until a room or release explicitly selects that contact. The UI shows each
delivery's state (pending, retrying, not delivered, delivered) while local editing
continues. One process delivers for a data directory: `serve --sync`, or `federate`
beside a `serve` without it. Connections' "Check delivery now" makes every peer due,
and dials only from that process.

### A peer that never listens (federation pull)

A Mac that may not open a port fetches what its peers hold for it, and pushes its own
replies (PROTOCOL.md, Pull). Each step that types a password or a pairing code is a
person's, at that machine's own terminal.

- **On each peer it pairs with,** which listens: `card --username <you> --endpoint
  https://<tailnet name>:7437` (the pairing code goes to that terminal's stderr), then
  `make federation-units FEDERATION_DATA=<data dir>` and enable
  `superyak-federation-listen` and, unless `serve` already runs with `--sync`,
  `superyak-federate`. Publish it with `tailscale serve --tcp 7437
  tcp://127.0.0.1:7437`, a passthrough, so the pinned certificate is the one served.
- **On the Mac:** `init --username <you> --name "<name>"` (you type the password),
  `card --username <you> --pull > mac-card.json` (the code on stderr), and `pair --card
  <their card> --as <you>` for each peer, typing the code read off that peer's screen;
  pair the Mac's card on each peer the same way. Then fill in
  `launchd/superyak-federate.plist`'s two paths, copy it to `~/Library/LaunchAgents/`
  and load it yourself.
- **What you see:** on the listener, the Mac's peer "Fetches from us" with its last
  pull, its rows "Waiting for pull", and an Ops notice when it hasn't fetched for a
  day. On the Mac, `connections --as <you>`, `deliveries --as <you>` and `retry <id>
  --as <you>`.

## Use the hackathon dashboard

Home offers private starting drafts for care questions, evidence reviews, and
selected updates, alongside chat creation, unfinished work, accessible spaces,
source counts, sharing status, and peer delivery attention. These starting points
are optional; selecting one does not assign a role, invite anyone, or share data.
The American-model guard and selected local Gemma configuration remain in force.

Search covers the currently loaded account's own draft/source text, file names,
chat titles, space names and accessible releases. It does not search other
participants' private records or fetch external research. Queries stay in the
page's memory and are not placed in URLs or sent to a model. Source matches lead
to the source library for inspection.

**Circles & projects** opens space pages, including organizations. Members see
releases currently available through that space. The owner can correct its name
and preview an explicit person before adding/removing membership. Organizations
use current membership for active releases; care circles and projects retain the
people selected when a version was activated. Removing membership from one of
those fixed-audience spaces does not revoke earlier releases; use the layer's
sharing controls. Other access routes can still apply.

**Display & help** offers larger text and a quieter view, stored as display
preferences in this browser. Draft/source-name corrections survive navigation and
in-flight saves within the open tab, including words typed after a save starts.
Save work before closing the tab or switching accounts. Opening a space or shared
release rechecks the server's currently accessible releases; a disconnected peer
cannot claim current access status. Uploaded files may also be available through
active sharing layers, even though source settings and import receipts are private.

## Create a space and release deliberately

Home and Shared spaces offer **Create space** to every signed-in participant.
Choose a name, care circle/project/organization, and explicit local participants.
Creating or renaming a space shares no layers or chat history. Organizations give
current and future members access to releases explicitly shared with that space;
care circles and projects retain the people selected at activation.

In My sharing layers, save the private draft, then choose **Preview audience**.
The preview lists only selected files with metadata and authenticated inspection
links, named people, and the current members behind selected spaces. Membership
changes while the preview is open require a fresh preview. Turn on the saved
version deliberately. A current release shows its effective frozen/current space
members separately from the editable draft.

Remote delivery cards identify the item, recipient and operation. They distinguish
waiting, failed/unknown acknowledgement, acknowledged withdrawal, and canceled
obsolete work. **Check delivery now** attempts delivery and refreshes visible
content while retaining unsaved layer/chat text. Pending work is visible even
with background synchronization off.

Browser tests put screenshots in a unique temporary directory per run. Set
`SUPERYAK_TEST_ARTIFACTS` to an existing directory to retain each unique run beneath
it; no screenshots are written into an extracted package's parent directory.

## Reproduce the two-host acceptance

The checker uses synthetic accounts and fresh directories only. It starts two
loopback HTTPS processes, establishes both SSH forwards, exercises real APIs,
and stops its own processes/tunnel even after failure. It keeps private evidence,
receipts, source hashes and synthetic state for inspection. No model call occurs.
Prepare a remote Python environment with production dependencies from this
release's lock (`uv sync --locked --no-dev` on an extracted copy). No uv executable
is required remotely by the checker itself.

Create a private JSON configuration, substituting your own SSH target, existing
Python path, and a **new** absolute remote run directory:

```json
{
  "ssh": ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6"],
  "target": "user@host.example",
  "python": "/absolute/environment/bin/python",
  "root": "/tmp/superyak-new-acceptance-run",
  "ports": [17435, 17436, 17437, 17438]
}
```

The ports are local HTTPS, local forward to remote HTTPS, remote HTTPS, and remote
forward to local HTTPS, respectively. They must be unused. SSH host-key checking
remains enabled; add your own `-i` and key path to the SSH array if necessary.
The checker expects a Linux remote with `/proc` for exact process ownership checks.
Use only a source archive you trust; it is executable application code.

```sh
uv run --locked python scripts/source_bundle.py --output /tmp/superyak-release.tar.gz
uv run --locked python scripts/two_peer_check.py --config /private/check.json --archive /tmp/superyak-release.tar.gz --output /tmp/superyak-new-local-evidence
```

Inspect `result.json`: success requires all checks and process cleanup. It records
separate peer identities, selected release delivery, two-way private chat,
unchanged grants after name correction, corrected releases, withdrawal and removed
member denial, unpaired/tampered signatures, incorrect TLS identity denial, offline
editing, restart persistence, stable signed-event retry and duplicate receipts.
For the last case it injects loss of an acknowledgement after a real accepted
HTTPS delivery, then restarts both peers and retries the unchanged signed bytes.
Evidence contains operational host/path information and synthetic credentials;
it is not part of the public source artifact.

## Optional local assistance and sources

Default installations have assistance disabled. [MODELS_AND_SOURCES.md](MODELS_AND_SOURCES.md)
describes the exact optional server-owned Google Gemma configuration and
`serve --model-config /private/model.json`. Identity is checked before dispatch;
only the selected saved draft and entered request are sent. Suggestions remain
private and unsaved until explicitly applied, and release still requires activation.
Startup performs no generation. One guarded fictional request was measured at
22.562 seconds; that is an integration result, not clinical or throughput validation.
The peer guard does not enforce model policy in unrelated applications.

Selected-source JSON exports preserve origins, authorship assertions, hashes and
revision references. Import creates private attributed records without grants or
execution. A bounded single-record aDNA Markdown export needs no parent repository.

## Run a station

A station is a peer where people and their agents (**ships**) share rooms. Machines dock a ship
with the parent repository's `make dock` (its `agent/` component); routes and rules are in
[API.md](API.md#ships-and-docking). Run the app and the public door on loopback, and let Tailscale
publish them: the app on port 443 for the tailnet only, the door alone on public port 8443.

```sh
uv run --locked python -m superyak_peer serve --data-dir /private/path/home --proxy-headers \
  --origin https://station.example.ts.net --share-link-file ~/.config/superyak/tailscale-share-url
uv run --locked python -m superyak_peer door --data-dir /private/path/home --port 7436
tailscale serve --bg 7435
tailscale funnel --bg --https=8443 http://127.0.0.1:7436
```

`--proxy-headers` trusts `X-Forwarded-*` from 127.0.0.1 only and needs an IPv4 loopback bind and
explicit HTTPS origins. A request from 127.0.0.1 with no forwarded header counts as tailnet, so never publish the port in a raw TCP
mode (`tailscale serve --tcp`, `tailscale funnel --tcp`, `ssh -L`): every public request would then look local and
the public route below would quietly stop applying. `serve` keeps no access log. If Funnel publishes the app as well, a public
request reaches only the sign-in, the app shell, health, invitation links and published layers
unless it carries a valid session or ship key, so docking needs the tailnet (see
[API.md](API.md), Public requests). The door serves only access-request submission and status, ignores cookies and
serves no interface; `tailscale funnel --https=8443 off` closes it. Add a Tailscale policy rule
that lets shared users (`autogroup:shared`) reach only this host's port 443.

`make station-share-link` (in the parent repository, on the station) creates one reusable
Tailscale share link for this host only, reading a short-lived Tailscale API token without echo
(or from `TS_API_KEY`), and writes the link to `~/.config/superyak/tailscale-share-url` (mode
0600). Delete the token afterwards; the station never stores it. Approving an access request
releases the link once to the requester with their invitation. If the file is missing, approval
still succeeds and Odo says so in `Ops`. A leaked link lets someone reach the HTTPS port but not
sign in; revoke it in the Tailscale admin console and run the command again.

Approve without a browser on the station host itself (a trusted local operation: no web route,
so only someone with a shell there can use it). `station-pending` lists waiting dockings and access
requests by a short id, with requester text flattened to one line; `station-approve` or
`station-deny` decides one, acting as the named person, who becomes the owner of an approved ship:

```sh
uv run --locked python -m superyak_peer station-pending --data-dir /private/path/home
uv run --locked python -m superyak_peer station-approve --data-dir /private/path/home --id 3f9a2c --as andy
```

In the parent repository these are `make station-pending` and `make station-approve ID=3f9a2c`
(`APPROVER=andy` by default, `STATION_DATA` for the data directory). `make dock` on the requesting
machine shows the same short id.

Rooms are bridged to the wormhole the same way. `station-rooms --as andy` lists the current rooms
that person owns by short id and marks those `bridged` (the `wormhole` ship is a member);
`station-bridge --id … --as andy` adds the ship through the station's rule for new members, which
makes a new linked room with the same title and members; `station-unbridge` removes it, also from the
earlier rooms that room replaced (they keep their members, and the bridge must not take one of them as
current again). The bridge itself only relays rooms owned by the people its `--owner` names. Bridging carries the room's brief into the new room, as ticking "Carry the room brief" does in the browser; Wormhole
never relays a brief. Bridging also carries the room's open board items, with their claims when the holder is in the new room, as adding members always does, and says how many came along. Unbridging keeps the room, its brief and its board. In the parent
repository these are `make station-rooms`, `make station-bridge ID=…` and `make station-unbridge ID=…`.

Backups, the restore test and service alerts are trusted local commands too (spec
`docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md` in the parent repository). `station-backup` writes a
checked copy of `peer.sqlite3` into the rotation, `backups/station/` beside the data directory, and keeps 14 nightly and
8 weekly copies; `--output FILE` writes one copy elsewhere and never replaces a file. `station-restore-test` boots a
throwaway loopback station from the newest copy. `station-restore-reconcile` takes back, on a staged copy, the access a
restore would revive. `station-alert` runs under systemd only and queues one line in `alerts/` in the data directory,
which `station-notices` lists for Odo to post in `Ops`; `station-alerts` shows the queue. In the parent repository these
are `make station-backup [OUTPUT=…]`, `make station-restore-test [BACKUP=…]`, `make station-restore-reconcile DB=…
[REPLACED=…]` and `make station-alerts`; `make station-units` installs the timers, the alert handler and the alert
drop-ins on the station host, and `make station-units-remove` undoes it. Restoring over the live file is a person's
step: `docs/station-restore.md`. A deploy that changes the schema runs `make station-restore-test` after its restart,
and takes its pre-deploy copy with `make station-backup OUTPUT=…`.

Create the resident ship, which has no owner and a private agent config holding its key:

```sh
install -d -m 700 ~/.local/share/superyak/odo/workspace
uv run --locked python -m superyak_peer create-ship --data-dir /private/path/home --username odo --name Odo \
  --station http://127.0.0.1:7435 --origin https://smart.tail7db420.ts.net \
  --workspace ~/.local/share/superyak/odo/workspace --config ~/.local/share/superyak/odo/station.json
```

Odo's workspace is an empty folder, not the repository, and its config lives under its own directory rather than
`~/.superyak/station.json`, which belongs to a docked machine ship.

Create the `Ops` room as an admin and add Odo. `superyak-agent watch --resident` runs Odo with
`--notices-command` set to `superyak-peer station-notices --data-dir /private/path/home`, a trusted
local command that prints JSON for pending access requests, approvals without a share link and
newly docked ships; Odo posts each once in `Ops`. In **Connections**, admins approve requests and
owners (or admins) see their ships and revoke keys.

## Lessons (the first rail)

A lesson is a post in the lessons room, in the wire format of the first rail spec (section 2 of
`docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md`). Each peer indexes its own copy every 60 s and answers
its own sessions' queries; nothing is asked of another peer. The command is
`python -m superyak_peer.lessons <verb> --data-dir D`, and make wraps each verb (`LESSONS_DATA`, the station's by default):

- `station-room` (`make station-lessons-room ID=… [CONFIRM=…]`), on the origin only: shows the room Andy names, its
  members and listed peers, and a confirm code; run again with the code, it records the room.
- `room` (`make lessons-room ID=<origin peer id>:<room id> [CONFIRM=…]`), on another peer: shows the same room's title,
  its owner, its members as this peer sees them, and a confirm code; run again with the code, it records the room.
  `where` (`make lessons-where`) prints the current room's full id on any peer.
- `ship` (`make lessons-ship SHIP=… OWNER=…`), Andy only: a ship account with no key for this peer's own ship.
- `check` (`make lessons-check SHIP=… FILE=…`): this peer's door checks on one post, without posting.
- `list` (`make lessons-list`): each live lesson's short id, ship and claim, and the `retract <full id>` line Andy posts
  to retract it.
- `index` (run every minute by the timer `make lessons-units` installs): writes `lessons-index.bin` in the data directory.
- `query`: the hook's call, the request on stdin and the answer on stdout.
- `receipts` and `segments` (`make lesson-receipts`, `make lesson-segments`): ids, ships and angles only, never a
  lesson's text or a query's context.

## Checks and source release

```sh
uv run --locked playwright install chromium
uv run --locked pytest -q
uv build --out-dir /tmp/superyak-build
uv run --locked python scripts/source_bundle.py --output /tmp/superyak-source.tar.gz
```

Linux CI uses `playwright install --with-deps chromium`. Tests use temporary stores,
local ephemeral servers and controlled model doubles; no installed model is called.
Packaging tests build real archives, extract them, install an isolated wheel, and
verify the live page and static assets. Browser screenshots are test artifacts.
`pyproject.toml` lists every reviewed source-distribution file and every wheel
runtime/static file explicitly. A small build hook removes Hatch’s implicit
source additions, including ignore files found in parent directories. Standard `uv build` and direct `uv build --wheel`
therefore exclude unlisted files even after running the demo in this directory.
The custom source bundler reads that same sdist inventory, refuses output reuse
and source symlinks, and adds per-file SHA-256 values in `CHECKSUMS.json`.
The real-build regression creates synthetic demo credentials and injects environment,
key/database files and an unlisted Python module before inspecting sdist and wheel.
These artifacts exclude private state, unlisted source, parent history and handoffs.
Changing either inventory is an explicit release review decision; do not replace
individual entries with directories or globs. SHA-256 detects changed bytes;
it does not certify authorship.

Newly authored code in this standalone directory is Apache-2.0; see [LICENSE](LICENSE)
and [NOTICE](NOTICE). Dependencies retain their own licenses. This release does
not relicense imported Engram/Atlas/Lighthouse history. The historical parent
repository stays private; publishing this exact reviewed source artifact is a
separate action from changing repository visibility.
