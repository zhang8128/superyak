# Wormhole Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deterministic bridge ship, `wormhole`, relays explicit `@persona` mentions in bridged station rooms to Stanley's aDNA lattice as coordination memos in a shared vault on the Pi, and relays memos addressed to the station back into rooms.

**Architecture:** Three new stdlib-only modules in `agent/superyak_agent/`: `memos.py` (pure memo format, parsing, persona map), `vault.py` (the bare repository and the bridge's working clone, driven with `git`), `wormhole.py` (the relay cycle against the station API), and `vault_git.py` (the forced command that limits Stanley's SSH key to fetching and pushing one repository, plus installing that key). New CLI commands in `agent/superyak_agent/__main__.py`; `make` targets for the operator.

**Tech Stack:** Python 3.11 standard library, git 2.39, OpenSSH 9.2 (`restrict`, `command=`), pytest, the existing station API and agent helpers.

**Spec:** [`docs/superpowers/specs/2026-10-04-wormhole-bridge-design.md`](../specs/2026-10-04-wormhole-bridge-design.md). Read it before Task 1.

## Global Constraints

- Work in the worktree `/home/andy/superyak/.worktrees/wormhole` on branch `wormhole`. Never edit `/home/andy/superyak` (main, live) before Task 6.
- Python 3.11; `agent/` stays standard library only and imports team helpers (`superyak_team.teamlib.redact`) from `../team`.
- Cap test runs: `systemd-run --user --scope -q -p MemoryMax=4G -p MemorySwapMax=0` (written `CAP` below). Agent tests: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider <files>`. Peer tests: `cd peer && CAP uv run --locked python -m pytest -q -p no:cacheprovider <files>`.
- No model call anywhere in the bridge.
- Vault name `Station.aDNA`; bare repository `~/aDNA/Station.aDNA.git`; clone `~/.local/share/superyak/wormhole/Station.aDNA`; folders `who/coordination/outbound/`, `who/coordination/inbox/`, `who/coordination/receipts/`. New files only: the bridge never edits or deletes a memo.
- Outbound memo file name: `coord_<YYYY_MM_DD>_station_to_<persona>_<slug>.md`, slug ≤ 6 words `[a-z0-9_]`, numeric suffix for uniqueness. `expires` = date + 14 days. `status: staged`, `urgency: info`, `reply_required: true`.
- Only `@name` tokens matching the persona map are sent; `@wormhole` lists reachable personas; messages by Wormhole or Odo are never sent.
- Inbound posts: header `**<Persona> (<Vault>) via the wormhole:** <subject>`, body quoted, at most 4,000 characters of body, no `@` anywhere in the post.
- Poll interval 30 s. Default room for new inbound memos: `Gamma Quadrant`.
- Persona map from `https://adna.network/api/registry.v1.json` (`vault`, `persona` per row), overridden by `personas.local.json`; the running bridge never fetches anything.
- The sync key: `restrict,command="<python> <run_agent> vault-git --repo <repo>"`; only `git-upload-pack` / `git-receive-pack` on exactly that repository; anything else is refused and logged with `logger -t station-vault`.
- `client_message_id` ≤ 100 characters.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A memo with hostile front matter or body** (YAML block scalars, nested maps, a header line containing `@serenity`, a 50 KB body, invalid UTF-8): the bridge must post a bounded, `@`-free, one-line-header message and never crash the cycle. Tested in Tasks 1 and 3.
2. **A symlink pushed into the inbox** pointing at a file outside the vault (e.g. `~/.ssh/id_ed25519`): it must never be read or posted. Tested in Tasks 2 and 3.
3. **The station refusing a post (429 rate limit)** midway through a cycle: no memo is written twice and nothing is lost; the next cycle finishes the work. Tested in Task 3.
4. **Both sides committing between syncs** (we add outbound memos while Stanley pushes inbox memos): local commits are replayed on top and pushed without losing either side's files. Tested in Task 2.
5. **SSH command smuggling** through the sync key (`git-upload-pack '/repo'; rm -rf ~`, other repositories, `..` paths, extra arguments): refused. Tested in Task 4.

---

### Task 1: Memo format, parsing and the persona map (`memos.py`)

**Files:**
- Create: `agent/superyak_agent/memos.py`
- Modify: `agent/pyproject.toml` (wheel `only-include`)
- Test: `agent/tests/test_memos.py`

**Interfaces:**
- Produces: `STATION_VAULT = 'Station.aDNA'`; `mentioned(body) -> [lowercase names]`; `slug(text, words=6) -> str`; `memo_name(day, persona, text, taken) -> str` (slug from the first non-empty line); `front_matter(fields) -> str`; `outbound_memo(*, day, persona, vault, author, room_title, room_id, message_id, text, taken) -> (name, markdown)`; `parse_memo(text) -> (fields, body)`; `addressed_to_station(fields) -> bool`; `sender(fields) -> (persona, vault)`; `inbound_post(fields, body, name, limit=4000) -> str`; `personas_from_registry(registry) -> {lower: {'persona', 'vault'}}`; `fetch_registry(url=REGISTRY, opener=urllib.request.urlopen) -> dict`; `load_personas(path) -> dict`.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_memos.py`:

```python
import datetime
import io
import json
from superyak_agent import memos

DAY = datetime.date(2026, 10, 4)


def test_mentions_are_lowercase_unique_and_stripped():
    assert memos.mentioned('Hey @Venus, ask @hestia. and @venus! mail a@b.c') == ['venus', 'hestia']
    assert memos.mentioned('') == []


def test_slug_and_unique_memo_names():
    assert memos.slug('@Venus Can you check the MESH routes tonight, please?') == 'can_you_check_the_mesh_routes'
    assert memos.slug('!!!') == 'message'
    first = memos.memo_name(DAY, 'Venus', 'Check the mesh', set())
    assert first == 'coord_2026_10_04_station_to_venus_check_the_mesh.md'
    assert memos.memo_name(DAY, 'Venus', 'Check the mesh', {first}) == 'coord_2026_10_04_station_to_venus_check_the_mesh_2.md'


def test_outbound_memo_round_trips_through_the_parser():
    name, text = memos.outbound_memo(day=DAY, persona='Venus', vault='Network.aDNA', author='Andy\nAdmin',
                                     room_title='Gamma Quadrant', room_id='r1', message_id='m9',
                                     text='@venus can you check the mesh?\nThanks', taken=set())
    fields, body = memos.parse_memo(text)
    assert name == 'coord_2026_10_04_station_to_venus_can_you_check_the_mesh.md'
    assert fields['type'] == 'coordination' and fields['coordination_class'] == 'outbound_memo'
    assert fields['from'] == 'Station.aDNA (Andy Admin via Wormhole)' and fields['to'] == 'Network.aDNA (Venus)'
    assert (fields['from_vault'], fields['to_vault'], fields['to_persona']) == ('Station.aDNA', 'Network.aDNA', 'Venus')
    assert (fields['date'], fields['expires'], fields['status']) == ('2026-10-04', '2026-10-18', 'staged')
    assert fields['reply_required'] is True and fields['urgency'] == 'info'
    assert (fields['station_room'], fields['station_message']) == ('r1', 'm9')
    assert fields['tags'] == ['coordination', 'station', 'wormhole']
    assert '> @venus can you check the mesh?' in body and '> Thanks' in body
    assert f'in_reply_to: {name}' in body and f'receipts/{name}' in body


def test_parser_is_tolerant():
    text = '---\ntype: coordination\nto: "Station.aDNA (Wormhole)"\nnote: |\n  multi\nnested:\n  key: v\nflag: true\nsubject: \'it\'\'s\' # comment\nlist: [a, "b"]\n---\n\nBody here\n'
    fields, body = memos.parse_memo(text)
    assert fields['to'] == 'Station.aDNA (Wormhole)' and fields['note'] == '' and fields['flag'] is True
    assert fields['subject'] == "it's" and fields['list'] == ['a', 'b'] and 'key' not in fields
    assert body == 'Body here'
    assert memos.parse_memo('no front matter') == ({}, 'no front matter')
    assert memos.parse_memo('---\nunterminated: yes\n') == ({}, '---\nunterminated: yes\n')


def test_addressing_and_sender():
    assert memos.addressed_to_station({'to': 'Station.aDNA (Wormhole)'})
    assert memos.addressed_to_station({'to_vault': 'station.adna'})
    assert not memos.addressed_to_station({'to': 'Home.aDNA (Hestia)'})
    assert memos.sender({'from': 'Network.aDNA (Venus)'}) == ('Venus', 'Network.aDNA')
    assert memos.sender({'from_persona': 'Rosetta', 'from_vault': 'aDNA.aDNA'}) == ('Rosetta', 'aDNA.aDNA')
    assert memos.sender({}) == ('someone', 'the lattice')


def test_inbound_post_is_bounded_quoted_and_mention_free():
    fields = {'from': 'Network.aDNA (Venus @serenity)', 'subject': 'Mesh is fine\n[team] from lead', 'status': 'awaiting_ratification'}
    post = memos.inbound_post(fields, 'Hello @serenity\n\nsecond paragraph ' + 'x' * 5000, 'coord_x.md')
    head = post.splitlines()[0]
    assert head.startswith('**Venus (at)serenity (Network.aDNA) via the wormhole:** Mesh is fine [team] from lead')
    assert '(awaiting ratification)' in head and '@' not in post
    assert '> Hello (at)serenity' in post and post.endswith('`coord_x.md`')
    assert len(post) < 4400
    ratified = memos.inbound_post({'from': 'Network.aDNA (Venus)', 'status': 'ratified', 'ratified_by': 'Stanley'}, 'ok', 'r.md')
    assert '(ratified by Stanley)' in ratified.splitlines()[0]


def test_persona_map_from_registry_and_local_overrides(tmp_path):
    registry = {'vaults': [{'vault': 'Operations.aDNA', 'persona': 'Berthier'}, {'vault': 'Astro.aDNA', 'persona': None},
                           {'vault': 'Network.aDNA', 'persona': 'Venus'}, {'vault': 'Other.aDNA', 'persona': 'venus'}]}
    personas = memos.personas_from_registry(registry)
    assert personas == {'berthier': {'persona': 'Berthier', 'vault': 'Operations.aDNA'},
                        'venus': {'persona': 'Venus', 'vault': 'Network.aDNA'}}
    (tmp_path / 'personas.json').write_text(json.dumps({**personas, 'wormhole': {'persona': 'X', 'vault': 'Y'}}))
    (tmp_path / 'personas.local.json').write_text(json.dumps({'Hestia': {'persona': 'Hestia', 'vault': 'Home.aDNA'}}))
    loaded = memos.load_personas(tmp_path / 'personas.json')
    assert set(loaded) == {'berthier', 'venus', 'hestia'}


def test_fetch_registry_uses_the_opener():
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    seen = []

    def opener(url, timeout):
        seen.append((url, timeout))
        return Response(b'{"vaults": []}')
    assert memos.fetch_registry(opener=opener) == {'vaults': []}
    assert seen == [('https://adna.network/api/registry.v1.json', 30)]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_memos.py`
Expected: FAIL (`cannot import name 'memos'`).

- [ ] **Step 3: Implement**

`agent/superyak_agent/memos.py`:

```python
"""aDNA coordination memos for the wormhole bridge: names, front matter, parsing and the persona map.
Pure functions; the bridge never runs a model and never fetches anything while relaying."""
import datetime
import json
from pathlib import Path
import re
import urllib.request
from .station import label, read_json

STATION_VAULT = 'Station.aDNA'
REGISTRY = 'https://adna.network/api/registry.v1.json'
EXPIRES_DAYS = 14
MENTION = re.compile(r'(?<![\w@])@([a-z0-9][a-z0-9_.-]{1,63})', re.IGNORECASE)
LINE = re.compile(r'^([A-Za-z_][\w-]*):[ \t]*(.*)$')


def mentioned(body):
    """Lowercase @names in a message, in order, without trailing punctuation."""
    return list(dict.fromkeys(m.group(1).rstrip('._-').lower() for m in MENTION.finditer(body or '')))


def slug(text, words=6):
    tokens = re.findall(r'[a-z0-9]+', re.sub(r'@\S+', ' ', (text or '').lower()))
    return '_'.join(tokens[:words]) or 'message'


def memo_name(day, persona, text, taken):
    first = next((line for line in (text or '').splitlines() if line.strip()), '')
    base = f'coord_{day:%Y_%m_%d}_station_to_{slug(persona, 1)}_{slug(first)}'
    name, n = f'{base}.md', 2
    while name in taken:
        name, n = f'{base}_{n}.md', n + 1
    return name


def _yaml_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return '[' + ', '.join(str(v) for v in value) + ']'
    return json.dumps(str(value), ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def front_matter(fields):
    return '---\n' + ''.join(f'{key}: {_yaml_value(value)}\n' for key, value in fields.items()) + '---\n'


def outbound_memo(*, day, persona, vault, author, room_title, room_id, message_id, text, taken):
    """(file name, markdown) for one station message addressed to one lattice persona. `text` is
    already secret-redacted by the caller."""
    name = memo_name(day, persona, text, taken)
    who, subject = label(author), label(text, 80)
    fields = {
        'type': 'coordination', 'coordination_class': 'outbound_memo',
        'from': f'{STATION_VAULT} ({who} via Wormhole)', 'to': f'{vault} ({persona})',
        'from_vault': STATION_VAULT, 'from_persona': who, 'to_vault': vault, 'to_persona': persona,
        'subject': subject, 'date': f'{day:%Y-%m-%d}',
        'expires': f'{day + datetime.timedelta(days=EXPIRES_DAYS):%Y-%m-%d}',
        'status': 'staged', 'urgency': 'info', 'reply_required': True,
        'station_room': room_id, 'station_message': message_id, 'tags': ['coordination', 'station', 'wormhole'],
    }
    quoted = '\n'.join('> ' + line if line.strip() else '>' for line in text.splitlines()) or '>'
    body = (f'# {subject}\n\n'
            f'{who} wrote this in the station room "{label(room_title)}" on Deep Space 9, the Superyak station on '
            f"Andy's Raspberry Pi, and addressed it to {persona} through the wormhole bridge.\n\n"
            f'{quoted}\n\n'
            f'Reply by adding a new memo to `{STATION_VAULT}/who/coordination/inbox/` with '
            f'`to: "{STATION_VAULT} (Wormhole)"` and `in_reply_to: {name}`. To show it was picked up, add an empty '
            f'file `{STATION_VAULT}/who/coordination/receipts/{name}`.\n')
    return name, front_matter(fields) + '\n' + body


def _scalar(raw):
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            return raw.strip('"')
    if raw.startswith("'") and len(raw) >= 2:
        end = raw.rfind("'")
        return raw[1:end].replace("''", "'") if end > 0 else raw.strip("'")
    if raw.startswith('[') and raw.endswith(']'):
        return [item.strip().strip('"\'') for item in raw[1:-1].split(',') if item.strip()]
    if raw.lower() in ('true', 'false'):
        return raw.lower() == 'true'
    if raw in ('|', '>', '|-', '>-', '|+', '>+'):
        return ''
    return raw.split(' #', 1)[0].strip()


def parse_memo(text):
    """(front matter, body). A tolerant subset of YAML: top-level `key: value` lines only; quoted
    strings unquoted; `[a, b]` lists split; block scalars become ''; nested maps are ignored."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}, text
    fields = {}
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            return fields, '\n'.join(lines[index + 1:]).strip()
        match = LINE.match(line)
        if match:
            fields[match.group(1)] = _scalar(match.group(2).strip())
    return {}, text


def addressed_to_station(fields):
    return any(STATION_VAULT.lower() in str(fields.get(key, '')).lower() for key in ('to', 'to_vault'))


def sender(fields):
    """(persona, vault) of an inbound memo, from from_persona/from_vault or `from: "Vault (Persona)"`."""
    persona, vault = str(fields.get('from_persona') or ''), str(fields.get('from_vault') or '')
    match = re.match(r'^\s*([^()]+?)\s*\(([^()]+)\)', str(fields.get('from') or ''))
    if match:
        vault, persona = vault or match.group(1), persona or match.group(2)
    return label(persona or 'someone'), label(vault or 'the lattice')


def inbound_post(fields, body, name, limit=4000):
    """A station post for a memo addressed to the station: labelled header, quoted body, no '@'."""
    persona, vault = sender(fields)
    status = str(fields.get('status') or '').lower()
    notes = []
    if fields.get('ratification_required') is True or status == 'awaiting_ratification':
        notes.append('awaiting ratification')
    if status == 'ratified':
        notes.append(f'ratified by {label(fields.get("ratified_by") or persona)}')
    head = f'**{persona} ({vault}) via the wormhole:** {label(fields.get("subject") or "", 200)}'
    if notes:
        head += f' ({"; ".join(notes)})'
    text = body if len(body) <= limit else body[:limit].rstrip() + ' …'
    quoted = '\n'.join('> ' + line if line.strip() else '>' for line in text.splitlines()) or '>'
    return f'{head}\n\n{quoted}\n\n`{label(name)}`'.replace('@', '(at)')


def personas_from_registry(registry):
    """{persona lowercase: {'persona': display name, 'vault': vault}}; rows without a persona are
    skipped, and the first vault to claim a persona keeps it."""
    out = {}
    for row in registry.get('vaults', []):
        persona, vault = row.get('persona'), row.get('vault')
        if isinstance(persona, str) and persona.strip() and isinstance(vault, str) and vault.strip():
            out.setdefault(persona.strip().lower(), {'persona': persona.strip(), 'vault': vault.strip()})
    return out


def fetch_registry(url=REGISTRY, opener=urllib.request.urlopen):
    with opener(url, timeout=30) as response:
        return json.loads(response.read())


def load_personas(path):
    """The registry map plus personas.local.json beside it (local entries win). Keys are lowercase,
    and 'wormhole' is reserved for the bridge itself."""
    path = Path(path)
    personas = {k.lower(): v for k, v in (read_json(path, {}) or {}).items()}
    personas.update({k.lower(): v for k, v in (read_json(path.with_name('personas.local.json'), {}) or {}).items()})
    personas.pop('wormhole', None)
    return personas
```

Add `"superyak_agent/memos.py",` to the wheel `only-include` list in `agent/pyproject.toml` (alphabetical).

- [ ] **Step 4: Run the tests**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_memos.py`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/memos.py agent/tests/test_memos.py agent/pyproject.toml
git commit -m "agent: aDNA coordination memos for the wormhole bridge

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The shared vault (`vault.py`)

**Files:**
- Create: `agent/superyak_agent/vault.py`
- Modify: `agent/pyproject.toml`
- Test: `agent/tests/test_vault.py`

**Interfaces:**
- Produces: `OUTBOUND, INBOX, RECEIPTS` folder constants; `VaultError`; `Vault(clone, remote='origin', branch='main')` with `create(bare, clone, template=None, branch='main') -> Vault` (classmethod), `sync()`, `publish()`, `add_outbound(name, text) -> bool`, `files(folder) -> [names]`, `read(folder, name, limit=200_000) -> str`.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_vault.py`:

```python
import os
import subprocess
import pytest
from superyak_agent.vault import INBOX, OUTBOUND, RECEIPTS, Vault, VaultError


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def vault(tmp_path):
    template = tmp_path / 'template'
    (template / 'who' / 'coordination').mkdir(parents=True)
    (template / 'CLAUDE.md').write_text('base\n')
    (template / 'node_modules').mkdir()
    (template / 'node_modules' / 'x.js').write_text('x')
    return Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone', template=template), tmp_path


def stanley(tmp_path):
    path = tmp_path / 'stanley'
    if not path.exists():
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'Station.aDNA.git'), str(path)], check=True)
    git(path, 'pull', '-q')
    return path


def test_create_makes_a_bare_repository_with_the_layout_and_drop_box(vault):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    for folder in (OUTBOUND, INBOX, RECEIPTS):
        assert (other / folder / 'README.md').exists()
    assert (other / 'CLAUDE.md').read_text() == 'base\n' and (other / 'README.md').exists()
    assert not (other / 'node_modules').exists()
    with pytest.raises(VaultError):
        Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone2')


def test_outbound_memos_are_committed_once_and_published(vault):
    vault, tmp_path = vault
    assert vault.add_outbound('coord_a.md', 'hello\n') is True
    assert vault.add_outbound('coord_a.md', 'changed\n') is False
    vault.publish()
    other = stanley(tmp_path)
    assert (other / OUTBOUND / 'coord_a.md').read_text() == 'hello\n'
    assert 'Wormhole' in git(other, 'log', '-1', '--format=%an')


def test_both_sides_committing_between_syncs_keeps_every_file(vault):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    (other / INBOX / 'coord_reply.md').write_text('reply\n')
    git(other, 'add', '-A')
    git(other, 'commit', '-q', '-m', 'stanley')
    git(other, 'push', '-q')
    vault.add_outbound('coord_b.md', 'out\n')
    vault.sync()
    vault.publish()
    assert vault.files(INBOX) == ['coord_reply.md']
    other = stanley(tmp_path)
    assert (other / OUTBOUND / 'coord_b.md').exists() and (other / INBOX / 'coord_reply.md').exists()


def test_files_and_read_skip_readmes_hidden_files_and_symlinks(vault, tmp_path):
    vault, _ = vault
    secret = tmp_path / 'secret.txt'
    secret.write_text('id_ed25519 private')
    (vault.clone / INBOX / 'coord_ok.md').write_text('ok')
    (vault.clone / INBOX / '.hidden.md').write_text('x')
    os.symlink(secret, vault.clone / INBOX / 'coord_link.md')
    assert vault.files(INBOX) == ['coord_ok.md']
    assert vault.read(INBOX, 'coord_ok.md') == 'ok'
    assert vault.read(INBOX, 'coord_link.md') == ''
    assert vault.read(INBOX, '../../secret.txt') == ''
    (vault.clone / INBOX / 'coord_big.md').write_bytes(b'a' * 300_000 + b'\xff')
    assert len(vault.read(INBOX, 'coord_big.md')) == 200_000
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_vault.py`
Expected: FAIL (`No module named 'superyak_agent.vault'`).

- [ ] **Step 3: Implement**

`agent/superyak_agent/vault.py`:

```python
"""The shared vault Station.aDNA: a bare repository on the Pi that Stanley's lattice syncs over the
mesh, and the bridge's working clone. Both sides only add files, so syncing replays our commits on
top of theirs."""
from pathlib import Path
import shutil
import subprocess

OUTBOUND = 'who/coordination/outbound'
INBOX = 'who/coordination/inbox'
RECEIPTS = 'who/coordination/receipts'
AUTHOR = ['-c', 'user.name=Wormhole', '-c', 'user.email=wormhole@station.invalid']
SAFE = ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'commit.gpgsign=false',
        '-c', 'protocol.file.allow=always']
VAULT_README = """# Station.aDNA

The shared vault of Deep Space 9, the Superyak station on Andy's Raspberry Pi. Its persona is
**Wormhole**, a bridge that relays messages between station rooms and aDNA personas. It runs no
model: it only copies text.

- `who/coordination/outbound/` — memos from the station to aDNA personas (`to_persona`).
- `who/coordination/inbox/` — memos to the station: `to: "Station.aDNA (Wormhole)"`; set
  `in_reply_to` to an outbound file name to answer it.
- `who/coordination/receipts/` — add an empty file named after an outbound memo to show it was
  picked up.

New files only, following the aDNA coordination drop-box doctrine: never edit or delete a memo.
"""
FOLDER_README = {
    OUTBOUND: '# Outbound\n\nMemos from Deep Space 9 to aDNA personas. Read the ones addressed to you; never edit them.\n',
    INBOX: ('# Inbox\n\nThe Station.aDNA drop-box. New files only; no probe needed. Address memos to '
            '`Station.aDNA (Wormhole)`. The station relays them into its rooms. Follows the aDNA coordination '
            'drop-box doctrine.\n'),
    RECEIPTS: '# Receipts\n\nAdd an empty file named exactly like an outbound memo to show it was picked up.\n',
}


class VaultError(RuntimeError):
    pass


class Vault:
    def __init__(self, clone, remote='origin', branch='main'):
        self.clone, self.remote, self.branch = Path(clone), remote, branch

    def git(self, *args, check=True):
        result = subprocess.run(['git', '-C', str(self.clone), *SAFE, *args], capture_output=True, text=True)
        if check and result.returncode:
            raise VaultError(f'git {args[0]} failed: {result.stderr.strip()[:300]}')
        return result

    @classmethod
    def create(cls, bare, clone, template=None, branch='main'):
        """Create the bare repository and the bridge's clone, with the aDNA layout copied from
        `template` (without .git or node_modules) and the three drop-box folders."""
        bare, clone = Path(bare), Path(clone)
        if bare.exists() or clone.exists():
            raise VaultError(f'{bare} or {clone} already exists')
        bare.parent.mkdir(parents=True, exist_ok=True)
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', branch, str(bare)], check=True, capture_output=True)
        subprocess.run(['git', 'clone', '-q', str(bare), str(clone)], check=True, capture_output=True)
        vault = cls(clone, branch=branch)
        vault.git('symbolic-ref', 'HEAD', f'refs/heads/{branch}')
        if template:
            shutil.copytree(template, clone, dirs_exist_ok=True, symlinks=True,
                            ignore=shutil.ignore_patterns('.git', 'node_modules'))
        (clone / 'README.md').write_text(VAULT_README)
        for folder, text in FOLDER_README.items():
            (clone / folder).mkdir(parents=True, exist_ok=True)
            (clone / folder / 'README.md').write_text(text)
        vault.git('add', '-A')
        vault.git(*AUTHOR, 'commit', '-q', '-m', 'Station.aDNA: the shared vault of the Deep Space 9 wormhole bridge')
        vault.git('push', '-q', vault.remote, f'HEAD:{branch}')
        vault.git('branch', '-q', f'--set-upstream-to={vault.remote}/{branch}')
        return vault

    def sync(self):
        """Fetch, then replay our unpublished commits on top of the remote branch."""
        self.git('fetch', '-q', self.remote)
        upstream = f'{self.remote}/{self.branch}'
        if self.git('rev-parse', '--verify', '-q', upstream, check=False).returncode:
            return
        rebase = self.git(*AUTHOR, 'rebase', '-q', upstream, check=False)
        if rebase.returncode:
            self.git('rebase', '--abort', check=False)
            raise VaultError(f'could not replay local memos on {upstream}: {rebase.stderr.strip()[:300]}')

    def publish(self):
        ahead = self.git('rev-list', '--count', f'{self.remote}/{self.branch}..HEAD', check=False)
        if ahead.returncode or ahead.stdout.strip() != '0':
            self.git('push', '-q', self.remote, f'HEAD:{self.branch}')

    def add_outbound(self, name, text):
        """Write and commit one outbound memo. Never overwrites: returns False if it exists."""
        path = self.clone / OUTBOUND / name
        if path.exists() or path.is_symlink():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.git('add', '--', f'{OUTBOUND}/{name}')
        self.git(*AUTHOR, 'commit', '-q', '-m', f'wormhole: {name}')
        return True

    def files(self, folder):
        """Regular, non-hidden files in a drop-box folder (README.md excluded), sorted by name."""
        root = self.clone / folder
        if not root.is_dir() or root.is_symlink():
            return []
        return sorted(p.name for p in root.iterdir()
                      if not p.is_symlink() and p.is_file() and p.name != 'README.md' and not p.name.startswith('.'))

    def read(self, folder, name, limit=200_000):
        """Text of one file in a drop-box folder; '' for anything that is not a plain file directly in it."""
        root = (self.clone / folder).resolve()
        path = self.clone / folder / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
            return ''
        with open(path, 'rb') as stream:
            return stream.read(limit).decode('utf-8', 'replace')
```

Add `"superyak_agent/vault.py",` to the wheel `only-include` list.

- [ ] **Step 4: Run the tests**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_vault.py`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/vault.py agent/tests/test_vault.py agent/pyproject.toml
git commit -m "agent: the shared Station.aDNA vault for the wormhole bridge

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The relay cycle (`wormhole.py`)

**Files:**
- Create: `agent/superyak_agent/wormhole.py`
- Modify: `agent/pyproject.toml`
- Test: `agent/tests/test_wormhole.py`

**Interfaces:**
- Consumes: `memos.*`, `Vault`, `INBOX`, `OUTBOUND`, `RECEIPTS`, `StationClient`, `StationError`, `read_json`, `write_private`, `superyak_team.teamlib.redact`.
- Produces: `POLL_SECONDS = 30`; `DEFAULT_ROOM = 'Gamma Quadrant'`; `Wormhole(client, vault, personas, state_path, today=datetime.date.today)` with `.cycle() -> int` (posts made). State keys: `rooms` (room id → last seen message id, `''` when empty), `sent` (`<message id>:<persona>` → file name), `memos` (file name → `{room, persona, vault}`), `relayed` (inbox file names), `receipts` (outbound file names).

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_wormhole.py`:

```python
import datetime
import os
import subprocess
import pytest
from superyak_agent import memos
from superyak_agent.station import StationClient, StationError
from superyak_agent.vault import INBOX, OUTBOUND, RECEIPTS, Vault
from superyak_agent.wormhole import Wormhole

PERSONAS = {'venus': {'persona': 'Venus', 'vault': 'Network.aDNA'}, 'hestia': {'persona': 'Hestia', 'vault': 'Home.aDNA'}}


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), '-c', 'user.name=s', '-c', 'user.email=s@s', *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def bridge(station, tmp_path):
    fake, andy, jenn, serenity = station
    wormhole = fake.user('wormhole', 'Wormhole', 'ship', None, key='wormhole-key')
    odo = fake.user('odo', 'Odo', 'ship', None, key='odo-key')
    gamma = fake.room('Gamma Quadrant', andy, odo, wormhole)
    vault = Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone')
    client = StationClient('http://station.test', 'wormhole-key', transport=fake)

    def make():
        return Wormhole(client, vault, PERSONAS, tmp_path / 'state.json', today=lambda: datetime.date(2026, 10, 4))
    return fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path


def lattice(tmp_path, files=None, folder=INBOX):
    """Stand-in for Stanley's side: clone, add files, push."""
    path = tmp_path / 'stanley'
    if not path.exists():
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'Station.aDNA.git'), str(path)], check=True)
    git(path, 'pull', '-q')
    for name, text in (files or {}).items():
        (path / folder / name).write_text(text)
    if files:
        git(path, 'add', '-A')
        git(path, 'commit', '-q', '-m', 'lattice')
        git(path, 'push', '-q')
    return path


def bodies(fake, room):
    return [m['body'] for m in fake.rooms[room]['messages']]


def test_first_sight_skips_history_then_mentions_become_memos_once(bridge):
    fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path = bridge
    fake.say(gamma, andy, '@venus old message before the bridge')
    w = make()
    assert w.cycle() == 0
    fake.say(gamma, andy, '@Venus, can you check the mesh?\ntoken ghp_' + 'a' * 30)
    assert w.cycle() == 1
    name = 'coord_2026_10_04_station_to_venus_can_you_check_the_mesh.md'
    assert bodies(fake, gamma)[-1] == f'Sent to Venus (Network.aDNA) as `{name}`.'
    sent = (lattice(tmp_path) / OUTBOUND / name).read_text()
    fields, body = memos.parse_memo(sent)
    assert fields['to'] == 'Network.aDNA (Venus)' and fields['station_room'] == gamma
    assert '[REDACTED]' in body and 'ghp_' not in body
    assert w.cycle() == 0 and make().cycle() == 0
    assert len(list((lattice(tmp_path) / OUTBOUND).glob('coord_*.md'))) == 1


def test_unknown_names_own_and_odo_messages_are_not_sent_but_other_ships_are(bridge):
    fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path = bridge
    w = make()
    w.cycle()
    fake.rooms[gamma]['member_ids'].append(serenity['id'])
    fake.say(gamma, andy, '@nobody hello')
    fake.say(gamma, odo, '@venus from odo')
    fake.say(gamma, wormhole, '@venus from me')
    fake.say(gamma, serenity, '@hestia from serenity')
    fake.say(gamma, andy, '@wormhole who can you reach?')
    w.cycle()
    outbound = sorted(p.name for p in (lattice(tmp_path) / OUTBOUND).glob('coord_*.md'))
    assert outbound == ['coord_2026_10_04_station_to_hestia_from_serenity.md']
    help_post = bodies(fake, gamma)[-1]
    assert help_post.startswith('Through the wormhole I can reach:') and 'Venus (Network.aDNA)' in help_post and '@' not in help_post


def test_inbound_replies_return_to_their_room_and_new_memos_go_to_gamma_quadrant(bridge):
    fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path = bridge
    ops = fake.room('Ops', andy, wormhole)
    w = make()
    w.cycle()
    fake.say(ops, andy, '@venus status?')
    w.cycle()
    sent = 'coord_2026_10_04_station_to_venus_status.md'
    reply = ('---\nfrom: "Network.aDNA (Venus)"\nto: "Station.aDNA (Wormhole)"\nsubject: "All green"\n'
             f'in_reply_to: {sent}\n---\n\nMesh is fine. Ping @serenity later.\n')
    fresh = '---\nfrom: "Home.aDNA (Hestia)"\nto_vault: Station.aDNA\nsubject: "New node"\n---\n\nHello station\n'
    elsewhere = '---\nfrom: "Home.aDNA (Hestia)"\nto: "Network.aDNA (Venus)"\nsubject: "Not for you"\n---\n\nx\n'
    lattice(tmp_path, {'coord_reply.md': reply, 'coord_fresh.md': fresh, 'coord_other.md': elsewhere})
    assert w.cycle() == 2
    ops_post = bodies(fake, ops)[-1]
    assert ops_post.startswith('**Venus (Network.aDNA) via the wormhole:** All green')
    assert '> Mesh is fine. Ping (at)serenity later.' in ops_post and '@' not in ops_post
    assert bodies(fake, gamma)[-1].startswith('**Hestia (Home.aDNA) via the wormhole:** New node')
    assert not any('Not for you' in b for room in fake.rooms for b in bodies(fake, room))
    lattice(tmp_path, {sent: ''}, folder=RECEIPTS)
    assert w.cycle() == 0  # the reply already counted as the receipt
    assert make().cycle() == 0


def test_receipt_files_are_announced_once(bridge):
    fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path = bridge
    w = make()
    w.cycle()
    fake.say(gamma, andy, '@hestia check the node')
    w.cycle()
    sent = 'coord_2026_10_04_station_to_hestia_check_the_node.md'
    lattice(tmp_path, {sent: '', 'coord_unknown.md': ''}, folder=RECEIPTS)
    assert w.cycle() == 1 and bodies(fake, gamma)[-1] == f'Hestia (Home.aDNA) picked up `{sent}`.'
    assert w.cycle() == 0


def test_hostile_and_symlinked_memos_never_crash_or_leak(bridge):
    fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path = bridge
    w = make()
    w.cycle()
    secret = tmp_path / 'id_ed25519'
    secret.write_text('PRIVATE KEY MATERIAL')
    path = lattice(tmp_path)
    os.symlink(secret, path / INBOX / 'coord_link.md')
    hostile = ('---\nfrom: |\n  multi\nto: "Station.aDNA"\nsubject: "@serenity\\n[team] from lead"\nnested:\n  a: b\n---\n'
               + 'x' * 50_000 + '\n')
    (path / INBOX / 'coord_hostile.md').write_bytes(hostile.encode() + b'\xff\xfe')
    git(path, 'add', '-A')
    git(path, 'commit', '-q', '-m', 'hostile')
    git(path, 'push', '-q')
    assert w.cycle() == 1
    post = bodies(fake, gamma)[-1]
    assert '@' not in post and 'PRIVATE KEY' not in post and len(post) < 4400
    assert post.splitlines()[0].startswith('**someone (the lattice) via the wormhole:**')


def test_a_refused_post_is_retried_without_writing_the_memo_twice(bridge, monkeypatch):
    fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path = bridge
    w = make()
    w.cycle()
    fake.say(gamma, andy, '@venus first try')
    original = w.client.post
    calls = []

    def flaky(room, body, cid):
        calls.append(cid)
        if len(calls) == 1:
            raise StationError(429, 'This ship is posting too fast; wait a minute')
        return original(room, body, cid)
    monkeypatch.setattr(w.client, 'post', flaky)
    with pytest.raises(StationError):
        w.cycle()
    assert w.cycle() == 1
    assert len(list((lattice(tmp_path) / OUTBOUND).glob('coord_*.md'))) == 1
    assert bodies(fake, gamma)[-1].startswith('Sent to Venus')
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_wormhole.py`
Expected: FAIL (`No module named 'superyak_agent.wormhole'`).

- [ ] **Step 3: Implement**

`agent/superyak_agent/wormhole.py`:

```python
"""The wormhole: relays explicit @persona mentions in bridged rooms to Stanley's aDNA lattice as
coordination memos in Station.aDNA, and memos addressed to the station back into rooms. No model runs
here: text is only copied, redacted on the way out and quoted without '@' on the way in."""
import datetime
import hashlib
import logging
from superyak_team.teamlib import redact
from . import memos
from .station import StationError, read_json, write_private
from .vault import INBOX, OUTBOUND, RECEIPTS

log = logging.getLogger('superyak.wormhole')
POLL_SECONDS = 30
DEFAULT_ROOM = 'Gamma Quadrant'
SKIP_AUTHORS = ('odo',)
KEPT = 5000


def _digest(name):
    return hashlib.sha256(name.encode()).hexdigest()[:16]


class Wormhole:
    def __init__(self, client, vault, personas, state_path, today=datetime.date.today):
        self.client, self.vault, self.personas = client, vault, personas
        self.state_path, self.today = state_path, today
        self.state = read_json(state_path, {}) or {}
        for key, default in (('rooms', {}), ('sent', {}), ('memos', {}), ('relayed', []), ('receipts', [])):
            self.state.setdefault(key, default)
        self.me = None

    def save(self):
        write_private(self.state_path, self.state)

    def _mark(self, key, value):
        self.state[key] = (self.state[key] + [value])[-KEPT:]
        self.save()

    def cycle(self):
        if self.me is None:
            self.me = self.client.me()
        self.vault.sync()
        rooms = [r for r in self.client.rooms() if ':' not in r['id']]
        posted = self._outbound(rooms)
        self.vault.publish()
        return posted + self._inbound(rooms) + self._receipts()

    def _post(self, room_id, text, client_message_id):
        try:
            self.client.post(room_id, text.replace('@', '(at)'), client_message_id)
            return 1
        except StationError as error:
            if error.status not in (403, 404, 409):
                raise
            log.warning('could not post %s: %s', client_message_id, error)
            return 0

    def _outbound(self, rooms):
        posted = 0
        for summary in rooms:
            room = self.client.room(summary['id'])
            members = {m['id']: m for m in room.get('members', [])}
            ids = [m['id'] for m in room['messages']]
            if room['id'] not in self.state['rooms']:
                self.state['rooms'][room['id']] = ids[-1] if ids else ''  # first sight: no history replay
                self.save()
                continue
            seen = self.state['rooms'][room['id']]
            start = ids.index(seen) + 1 if seen in ids else 0
            for message in room['messages'][start:]:
                posted += self._relay_out(room, members, message)
                self.state['rooms'][room['id']] = message['id']
                self.save()
        return posted

    def _relay_out(self, room, members, message):
        author = members.get(message['author_id'], {})
        if message['author_id'] == self.me['id'] or author.get('username') in SKIP_AUTHORS:
            return 0
        names, posted = memos.mentioned(message['body']), 0
        if 'wormhole' in names:
            posted += self._post(room['id'], self._help(), f'wormhole-help-{message["id"]}')
        for name in names:
            target = self.personas.get(name)
            if not target:
                continue
            key = f'{message["id"]}:{name}'
            file_name = self.state['sent'].get(key)
            if file_name is None:
                taken = set(self.state['memos']) | set(self.vault.files(OUTBOUND))
                file_name, text = memos.outbound_memo(
                    day=self.today(), persona=target['persona'], vault=target['vault'],
                    author=author.get('name') or 'someone', room_title=room['title'], room_id=room['id'],
                    message_id=message['id'], text=redact(message['body']), taken=taken)
                self.vault.add_outbound(file_name, text)
                self.state['sent'][key] = file_name
                self.state['memos'][file_name] = {'room': room['id'], 'persona': target['persona'], 'vault': target['vault']}
                self.save()
            posted += self._post(room['id'], f'Sent to {target["persona"]} ({target["vault"]}) as `{file_name}`.',
                                 f'wormhole-out-{message["id"]}-{name[:40]}')
        return posted

    def _help(self):
        reachable = sorted(f'{p["persona"]} ({p["vault"]})' for p in self.personas.values())
        if not reachable:
            return 'No aDNA personas are configured for the wormhole yet.'
        more = f', and {len(reachable) - 40} more' if len(reachable) > 40 else ''
        return 'Through the wormhole I can reach: ' + ', '.join(reachable[:40]) + more + '.'

    def _inbound(self, rooms):
        member_rooms = {r['id'] for r in rooms}
        gamma = [r for r in rooms if r.get('title') == DEFAULT_ROOM]
        default = max(gamma, key=lambda r: r.get('last_activity') or 0)['id'] if gamma else None
        posted = 0
        for name in self.vault.files(INBOX):
            if name in self.state['relayed'] or not name.endswith('.md'):
                continue
            fields, body = memos.parse_memo(self.vault.read(INBOX, name))
            if not memos.addressed_to_station(fields):
                self._mark('relayed', name)
                continue
            reply_to = str(fields.get('in_reply_to') or '')
            room = (self.state['memos'].get(reply_to) or {}).get('room')
            if room not in member_rooms:
                station_room = fields.get('station_room')
                room = station_room if station_room in member_rooms else default
            if room is None:
                continue  # no Gamma Quadrant yet: keep the memo for a later cycle
            posted += self._post(room, memos.inbound_post(fields, body, name), f'wormhole-in-{_digest(name)}')
            if reply_to in self.state['memos'] and reply_to not in self.state['receipts']:
                self._mark('receipts', reply_to)  # an answer is also a read receipt
            self._mark('relayed', name)
        return posted

    def _receipts(self):
        posted = 0
        for name in self.vault.files(RECEIPTS):
            info = self.state['memos'].get(name)
            if info is None or name in self.state['receipts']:
                continue
            posted += self._post(info['room'], f'{info["persona"]} ({info["vault"]}) picked up `{name}`.',
                                 f'wormhole-rcpt-{_digest(name)}')
            self._mark('receipts', name)
        return posted
```

Add `"superyak_agent/wormhole.py",` to the wheel `only-include` list.

- [ ] **Step 4: Run the tests**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_wormhole.py tests/test_memos.py tests/test_vault.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/wormhole.py agent/tests/test_wormhole.py agent/pyproject.toml
git commit -m "agent: the wormhole relay between station rooms and aDNA memos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The sync-key lock, CLI commands and make targets

**Files:**
- Create: `agent/superyak_agent/vault_git.py`
- Modify: `agent/superyak_agent/__main__.py`, `agent/pyproject.toml`, root `Makefile`
- Test: `agent/tests/test_vault_git.py`

**Interfaces:**
- Produces: `vault_git.allowed(command, repo, home=None) -> (verb, path) | None`; `vault_git.serve(repo, environ=os.environ, execvp=os.execvp, log=None) -> int`; `vault_git.install_key(key, repo, python, run_agent, authorized_keys) -> bool`. CLI: `wormhole --config C --state S --vault CLONE --personas P [--once]`; `wormhole-init --bare B --clone C [--template T]`; `wormhole-personas --out P [--registry URL]`; `vault-git --repo R`; `wormhole-key --key K --repo R [--authorized-keys PATH]`. Make: `wormhole-personas`, `wormhole-key KEY='…'`.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_vault_git.py`:

```python
import pytest
from superyak_agent import vault_git

REPO_NAME = 'aDNA/Station.aDNA.git'


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / REPO_NAME
    path.mkdir(parents=True)
    return path


@pytest.mark.parametrize('command', [
    "git-upload-pack '{repo}'", "git-receive-pack '{repo}'", "git-upload-pack '~/aDNA/Station.aDNA.git'",
    "git-upload-pack 'aDNA/Station.aDNA.git'", 'git-upload-pack {repo}'])
def test_allowed_git_commands_on_the_vault(repo, tmp_path, monkeypatch, command):
    monkeypatch.setenv('HOME', str(tmp_path))
    verb, path = vault_git.allowed(command.format(repo=repo), repo, home=tmp_path)
    assert verb in vault_git.VERBS and path == str(repo.resolve())


@pytest.mark.parametrize('command', [
    '', 'bash', 'git-upload-pack', "git-upload-pack '/etc'", "git-upload-pack '{repo}/../other.git'",
    "git-upload-pack '{repo}'; rm -rf ~", "git-upload-pack '{repo}' extra", "git-upload-archive '{repo}'",
    "scp -t '{repo}'", "git-upload-pack '{repo}", 'git-upload-pack $(id)'])
def test_everything_else_is_refused(repo, tmp_path, command):
    assert vault_git.allowed(command.format(repo=repo), repo, home=tmp_path) is None


def test_serve_executes_allowed_commands_and_logs_refusals(repo, tmp_path, capsys):
    ran, logged = [], []
    vault_git.serve(repo, environ={'SSH_ORIGINAL_COMMAND': f"git-receive-pack '{repo}'"}, execvp=lambda v, a: ran.append(a))
    assert ran == [['git-receive-pack', str(repo.resolve())]]
    code = vault_git.serve(repo, environ={'SSH_ORIGINAL_COMMAND': 'cat ~/.ssh/id_ed25519'}, execvp=lambda v, a: ran.append(a),
                           log=logged.append)
    assert code == 1 and len(ran) == 1 and 'refused' in logged[0]
    assert 'only fetch and push the station vault' in capsys.readouterr().err


def test_install_key_adds_one_restricted_line_and_keeps_the_rest(repo, tmp_path):
    keys = tmp_path / '.ssh' / 'authorized_keys'
    keys.parent.mkdir()
    keys.write_text('ssh-ed25519 AAAAexisting lattice-master-to-andy\n')
    key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStanleySync stanley-sync'
    assert vault_git.install_key(key, repo, '/usr/bin/python3', '/r/agent/run_agent.py', keys) is True
    lines = keys.read_text().splitlines()
    assert lines[0] == 'ssh-ed25519 AAAAexisting lattice-master-to-andy'
    assert lines[1] == f'restrict,command="/usr/bin/python3 /r/agent/run_agent.py vault-git --repo {repo.resolve()}" {key}'
    assert keys.stat().st_mode & 0o777 == 0o600 and keys.with_name('authorized_keys.bak-wormhole').exists()
    assert vault_git.install_key(key, repo, '/usr/bin/python3', '/r/agent/run_agent.py', keys) is False
    for bad in ('not a key', 'ssh-ed25519 AAAA\nssh-ed25519 BBBB evil', 'ssh-ed25519 AAAA"; rm'):
        with pytest.raises(ValueError):
            vault_git.install_key(bad, repo, '/usr/bin/python3', '/r/agent/run_agent.py', keys)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_vault_git.py`
Expected: FAIL (`cannot import name 'vault_git'`).

- [ ] **Step 3: Implement the lock and key install**

`agent/superyak_agent/vault_git.py`:

```python
"""Stanley's sync key can only fetch and push the station vault: `authorized_keys` forces this
command, which accepts exactly `git-upload-pack` or `git-receive-pack` on one repository."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

VERBS = ('git-upload-pack', 'git-receive-pack')
KEY_LINE = re.compile(r'^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com) '
                      r'[A-Za-z0-9+/]+=*( [^"\\]*)?$')


def allowed(command, repo, home=None):
    """(verb, absolute repo path) when `command` is a fetch or push of exactly `repo`, else None."""
    try:
        parts = shlex.split(command or '')
    except ValueError:
        return None
    if len(parts) != 2 or parts[0] not in VERBS:
        return None
    raw, home = parts[1], Path(home or Path.home())
    path = home / raw[2:] if raw.startswith('~/') else Path(raw) if raw.startswith('/') else home / raw
    try:
        if path.resolve() != Path(repo).resolve():
            return None
    except OSError:
        return None
    return parts[0], str(Path(repo).resolve())


def _syslog(message):
    subprocess.run(['logger', '-t', 'station-vault', message[:500]], check=False)


def serve(repo, environ=os.environ, execvp=os.execvp, log=None):
    command = environ.get('SSH_ORIGINAL_COMMAND', '')
    found = allowed(command, repo)
    if found is None:
        print('This key can only fetch and push the station vault.', file=sys.stderr)
        (log or _syslog)(f'refused {command!r}')
        return 1
    verb, path = found
    execvp(verb, [verb, path])
    return 0


def install_key(key, repo, python, run_agent, authorized_keys):
    """Append one `restrict,command=…` line for `key`. Returns False when the key is already there."""
    if '\n' in key or '\r' in key or not KEY_LINE.match(key.strip()):
        raise ValueError('Give one SSH public key line, e.g. "ssh-ed25519 AAAA… comment"')
    key = key.strip()
    command = f'{python} {run_agent} vault-git --repo {Path(repo).resolve()}'
    if '"' in command or '\\' in command:
        raise ValueError('Paths with quotes or backslashes are not supported')
    path = Path(authorized_keys)
    lines = path.read_text().splitlines() if path.exists() else []
    if any(key.split()[1] in line.split() for line in lines):
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.bak-wormhole'))
    tmp = path.with_name(path.name + '.tmp-wormhole')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('\n'.join(lines + [f'restrict,command="{command}" {key}']) + '\n')
    os.replace(tmp, path)
    return True
```

Add `"superyak_agent/vault_git.py",` to the wheel `only-include` list.

- [ ] **Step 4: Add the CLI commands**

In `agent/superyak_agent/__main__.py`, add to `build_parser()` after the existing commands:

```python
    worm = commands.add_parser('wormhole', help='Relay bridged rooms and the Station.aDNA vault (runs as a service)')
    worm.add_argument('--config', type=Path, required=True)
    worm.add_argument('--state', type=Path, required=True)
    worm.add_argument('--vault', type=Path, required=True, help='The bridge clone of Station.aDNA')
    worm.add_argument('--personas', type=Path, required=True)
    worm.add_argument('--once', action='store_true')
    init = commands.add_parser('wormhole-init', help='Create the Station.aDNA bare repository and the bridge clone')
    init.add_argument('--bare', type=Path, required=True)
    init.add_argument('--clone', type=Path, required=True)
    init.add_argument('--template', type=Path)
    personas = commands.add_parser('wormhole-personas', help='Write the persona map from the public aDNA registry')
    personas.add_argument('--out', type=Path, required=True)
    personas.add_argument('--registry', default=None)
    vg = commands.add_parser('vault-git', help='Forced command for the sync key (fetch/push one repository only)')
    vg.add_argument('--repo', type=Path, required=True)
    key = commands.add_parser('wormhole-key', help="Authorize Stanley's sync key for the station vault only")
    key.add_argument('--key', required=True)
    key.add_argument('--repo', type=Path, required=True)
    key.add_argument('--authorized-keys', type=Path, default=Path.home() / '.ssh' / 'authorized_keys')
```

and handlers in `main()`:

```python
    if args.command == 'wormhole':
        import logging
        import time
        from .memos import load_personas
        from .station import client_for, load_config
        from .vault import Vault
        from .wormhole import POLL_SECONDS, Wormhole
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        bridge = Wormhole(client_for(load_config(args.config)), Vault(args.vault), load_personas(args.personas), args.state)
        while True:
            try:
                posted = bridge.cycle()
                if posted:
                    logging.info('posted %d message(s)', posted)
            except Exception:  # noqa: BLE001 - keep the service alive
                logging.exception('cycle failed')
                bridge.me = None
            if args.once:
                return 0
            time.sleep(POLL_SECONDS)
    if args.command == 'wormhole-init':
        from .vault import Vault
        Vault.create(args.bare, args.clone, template=args.template)
        print(f'Station.aDNA created: {args.bare} (bridge clone {args.clone})')
        return 0
    if args.command == 'wormhole-personas':
        from .memos import REGISTRY, fetch_registry, personas_from_registry
        from .station import write_private
        found = personas_from_registry(fetch_registry(args.registry or REGISTRY))
        write_private(args.out, found)
        print(f'{len(found)} personas written to {args.out}. Add your own in {args.out.with_name("personas.local.json")}.')
        return 0
    if args.command == 'vault-git':
        from .vault_git import serve
        return serve(args.repo)
    if args.command == 'wormhole-key':
        import sys
        from .vault_git import install_key
        run_agent = Path(__file__).resolve().parents[1] / 'run_agent.py'
        added = install_key(args.key, args.repo, sys.executable, run_agent, args.authorized_keys)
        print('Key authorized: it can only fetch and push the station vault.' if added else
              'That key is already in authorized_keys; nothing changed. If it is an unrestricted key, ask for a dedicated one.')
        return 0
```

- [ ] **Step 5: Add the make targets**

In the root `Makefile`, add `wormhole-personas wormhole-key` to `.PHONY`, help lines, and:

```make
WORMHOLE_HOME ?= $(HOME)/.local/share/superyak/wormhole
STATION_VAULT_REPO ?= $(HOME)/aDNA/Station.aDNA.git
KEY ?=

wormhole-personas:
	python3 agent/run_agent.py wormhole-personas --out "$(WORMHOLE_HOME)/personas.json"

wormhole-key:
	@test -n "$(KEY)" || { echo "Usage: make wormhole-key KEY='ssh-ed25519 AAAA… comment'"; exit 2; }
	python3 agent/run_agent.py wormhole-key --key "$(KEY)" --repo "$(STATION_VAULT_REPO)"
```

- [ ] **Step 6: Run the tests**

Run: `cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agent/superyak_agent/vault_git.py agent/superyak_agent/__main__.py agent/tests/test_vault_git.py agent/pyproject.toml Makefile
git commit -m "agent: lock the sync key to the station vault; wormhole commands

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: End-to-end through the real station, and docs

**Files:**
- Test: `peer/tests/test_ship_agent.py` (append)
- Modify: `agent/README.md`, `CLAUDE.md`, `peer/pyproject.toml` (none unless a new test file), `README.md` (one line)

- [ ] **Step 1: Write the end-to-end test**

Append to `peer/tests/test_ship_agent.py`:

```python
def test_the_wormhole_relays_both_ways_through_the_real_station(env, tmp_path):
    import datetime
    import subprocess
    from superyak_agent.station import StationClient
    from superyak_agent.vault import INBOX, OUTBOUND, Vault
    from superyak_agent.wormhole import Wormhole
    app, clients, users, clock = env
    store = app.state.store
    wormhole = store.create_station_ship('wormhole', 'Wormhole')
    key = store.issue_ship_key(wormhole['id'])
    gamma = clients[0].post('/api/chats', json={'title': 'Gamma Quadrant', 'member_ids': [wormhole['id']]}).json()['id']
    vault = Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone')
    personas = {'venus': {'persona': 'Venus', 'vault': 'Network.aDNA'}}
    bridge = Wormhole(StationClient('http://testserver', key, transport=transport_for(app)), vault, personas,
                      tmp_path / 'state.json', today=lambda: datetime.date(2026, 10, 4))
    bridge.cycle()
    clock[0] += 1
    clients[0].post(f'/api/chats/{gamma}/messages', json={'client_message_id': 'a', 'body': '@venus is the mesh up?'})
    assert bridge.cycle() == 1
    name = 'coord_2026_10_04_station_to_venus_is_the_mesh_up.md'
    other = tmp_path / 'stanley'
    subprocess.run(['git', 'clone', '-q', str(tmp_path / 'Station.aDNA.git'), str(other)], check=True)
    assert (other / OUTBOUND / name).exists()
    (other / INBOX / 'coord_reply.md').write_text(
        f'---\nfrom: "Network.aDNA (Venus)"\nto: "Station.aDNA (Wormhole)"\nsubject: "Up"\nin_reply_to: {name}\n---\n\nAll up @patient\n')
    git = ['git', '-C', str(other), '-c', 'user.name=s', '-c', 'user.email=s@s']
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-q', '-m', 'reply'], check=True)
    subprocess.run(git + ['push', '-q'], check=True)
    clock[0] += 1
    assert bridge.cycle() == 1
    last = clients[0].get(f'/api/chats/{gamma}').json()['messages'][-1]['body']
    assert last.startswith('**Venus (Network.aDNA) via the wormhole:** Up') and '@' not in last
    assert store.mentions(users[0]['id']) == []
```

Run: `cd peer && CAP uv run --locked python -m pytest -q -p no:cacheprovider tests/test_ship_agent.py`
Expected: all pass (fix code, not the test, if it fails).

- [ ] **Step 2: Document**

- `agent/README.md`: add a "The wormhole" section: what it relays (explicit `@persona` mentions in rooms Wormhole is in; memos addressed to `Station.aDNA` back), the vault folders, `make wormhole-personas`, `make wormhole-key KEY_FILE=<.pub file>`, the service command, and that no model runs.
- `CLAUDE.md` (root), under "Approving on the station": add "To bridge a room to Stanley's aDNA lattice, add the `wormhole` ship to it as the room owner (Andy) when he asks; to unbridge, remove it."
- `README.md`: one line in the `agent/` description mentioning the wormhole bridge.

- [ ] **Step 3: Run every suite**

```bash
cd agent && CAP uv run --locked --extra dev python -m pytest -q -p no:cacheprovider
cd ../peer && CAP uv run --locked python -m pytest -q -p no:cacheprovider --ignore=tests/test_browser.py
```
Expected: all pass (record counts).

- [ ] **Step 4: Commit**

```bash
git add peer/tests/test_ship_agent.py agent/README.md CLAUDE.md README.md
git commit -m "wormhole: end-to-end test through the station; docs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Deploy on the Pi (controller, after Andy's go-ahead)

This changes the live station; ask Andy before merging.

- [ ] **Step 1: Merge.** `cd /home/andy/superyak && git status --short` (clean) → `git merge --ff-only wormhole` → `git push origin main` (Andy has approved pushing main for this testing loop; mention it).
- [ ] **Step 2: The ship.**
```bash
install -d -m 700 ~/.local/share/superyak/wormhole/workspace
~/superyak/peer/.venv/bin/python -m superyak_peer create-ship --data-dir ~/.local/share/superyak/lighthouse \
  --username wormhole --name Wormhole --station http://127.0.0.1:7435 --origin https://smart.tail7db420.ts.net \
  --workspace ~/.local/share/superyak/wormhole/workspace --config ~/.local/share/superyak/wormhole/station.json
```
- [ ] **Step 3: The vault and personas.**
```bash
python3 ~/superyak/agent/run_agent.py wormhole-init --bare ~/aDNA/Station.aDNA.git \
  --clone ~/.local/share/superyak/wormhole/Station.aDNA --template ~/aDNA/.adna
cd ~/superyak && make wormhole-personas
```
- [ ] **Step 4: Gamma Quadrant** (owner andy; members odo, wormhole) via the trusted Store, as for Ops.
- [ ] **Step 5: The service** `~/.config/systemd/user/superyak-wormhole.service`:
```ini
[Unit]
Description=Wormhole: bridge between station rooms and Stanley's aDNA lattice (no model)
After=superyak-lighthouse.service
Requires=superyak-lighthouse.service

[Service]
Environment=PATH=/usr/local/bin:/usr/bin:/bin
WorkingDirectory=%h/.local/share/superyak/wormhole
ExecStart=/usr/bin/python3 %h/superyak/agent/run_agent.py wormhole --config %h/.local/share/superyak/wormhole/station.json --state %h/.local/share/superyak/wormhole/state.json --vault %h/.local/share/superyak/wormhole/Station.aDNA --personas %h/.local/share/superyak/wormhole/personas.json
Restart=always
RestartSec=10
MemoryMax=256M
MemorySwapMax=0

[Install]
WantedBy=default.target
```
`systemctl --user daemon-reload && systemctl --user enable --now superyak-wormhole`.
- [ ] **Step 6: Live check (no Stanley needed).** Write a stand-in inbound memo addressed to `Station.aDNA` from a temporary clone of `~/aDNA/Station.aDNA.git`, push, and confirm Wormhole posts it in Gamma Quadrant within a minute; then remove nothing (new-files-only — label the stand-in memo `coord_…_station_selftest_….md` so it is obviously a test). Outbound needs a person's or ship's message: ask Andy (web) or Defiant (its Claude Code) to post `@venus hello from the station` in Gamma Quadrant, and confirm the memo appears in the bare repository.
- [ ] **Step 7: Handoff and message.** Add a dated HANDOFF entry; update the message for Stanley with: what Station.aDNA is, how to clone it over the mesh (`git clone andy@10.43.0.16:aDNA/Station.aDNA.git`, after the key is installed), the three folders, and the ask for a dedicated sync public key (saved as a `.pub` file and installed with `make wormhole-key KEY_FILE=…`).
