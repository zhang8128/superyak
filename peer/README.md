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

To provision an ordinary peer instead:

```sh
uv run --locked python -m superyak_peer init --username owner --name 'Peer owner'
uv run --locked python -m superyak_peer serve
```

The owner password is prompted privately. Default ordinary state is
`.engram/home`. The local owner can issue expiring one-use invitations; account
administration grants no access to another person's private content. Back up the
entire state directory securely while the server is stopped, including identity
keys and the database. Tested automated migration, key recovery/rotation, password
reset, and unattended service installation are outside this release.

In the parent repository, equivalent entry points are `make setup-peer`,
`make check-peer`, `make home-demo`, `make home`, and `make peer-bundle`.
`HOME_DATA`, `HOME_DEMO_DATA`, `HOME_PORT`, and `HOME_ARGS` select isolated state,
port, and optional serve arguments. These commands never start research workers.

## Pair two peers

See [API.md](API.md) for provisioning, routes, state, and audience semantics;
[PROTOCOL.md](PROTOCOL.md) specifies the signed envelope/card schema, independent
origins, receipts, bounded retry and revocation behavior. Operators explicitly
review each card's fingerprint and named remote participant. There is no automatic
discovery, implicit account merge, or network-wide owner.

```sh
uv run --locked python -m superyak_peer card --username owner --endpoint https://peer.example:7435 > owner-card.json
uv run --locked python -m superyak_peer serve --peer-tls --host 127.0.0.1 --origin https://peer.example:7435 --federation-endpoint https://peer.example:7435 --sync
```

Use the actual hostname on the first card export so its certificate includes that
name. The example requires an operator-provided route/tunnel to the loopback
listener. Remote binds require TLS. Trust the generated certificate through your
browser/OS explicitly; do not bypass certificate verification. Import and pair
each other's card in Connections using the local setup owner. Pairing addresses
the named remote participant; it grants no content until a room or release
explicitly selects that contact. The UI shows failed or pending deliveries while
local editing continues. The server needs `--sync` for background delivery;
Connections also provides an explicit sync action.

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
