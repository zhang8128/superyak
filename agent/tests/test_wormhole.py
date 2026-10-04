import datetime
import os
import subprocess
import pytest
from superyak_agent import memos
from superyak_agent.station import StationClient, StationError
from superyak_agent.vault import INBOX, OUTBOUND, RECEIPTS, Vault
from superyak_agent.wormhole import Wormhole

PERSONAS = {'venus': {'persona': 'Venus', 'vault': 'Network.aDNA'}, 'hestia': {'persona': 'Hestia', 'vault': 'Home.aDNA'}}
# What the forced command of Stanley's sync key sets, so the bare repository's gate applies to these pushes.
LATTICE_ENV = {**os.environ, 'STATION_VAULT_PUSHER': 'lattice'}


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), '-c', 'user.name=s', '-c', 'user.email=s@s', *args],
                          capture_output=True, text=True, check=True).stdout


def push(path):
    subprocess.run(['git', '-C', str(path), 'push', '-q'], capture_output=True, text=True, check=True, env=LATTICE_ENV)


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
        push(path)
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
    # The vault's gate refuses a symlink pushed by the lattice, so plant it directly in the bridge's clone.
    os.symlink(secret, vault.clone / INBOX / 'coord_link.md')
    path = lattice(tmp_path)
    hostile = ('---\nfrom: |\n  multi\nto: "Station.aDNA"\nsubject: "@serenity\\n[team] from lead"\nnested:\n  a: b\n---\n'
               + 'x' * 50_000 + '\n')
    (path / INBOX / 'coord_hostile.md').write_bytes(hostile.encode() + b'\xff\xfe')
    git(path, 'add', '-A')
    git(path, 'commit', '-q', '-m', 'hostile')
    push(path)
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


def test_a_memo_with_a_list_valued_station_room_still_reaches_gamma_quadrant(bridge):
    fake, andy, serenity, odo, wormhole, gamma, vault, make, tmp_path = bridge
    w = make()
    w.cycle()
    odd = '---\nfrom: "Home.aDNA (Hestia)"\nto_vault: Station.aDNA\nsubject: "Odd"\nstation_room: [a, b]\n---\n\nhi\n'
    later = '---\nfrom: "Home.aDNA (Hestia)"\nto_vault: Station.aDNA\nsubject: "Later"\n---\n\nhi\n'
    lattice(tmp_path, {'coord_a_odd.md': odd, 'coord_b_later.md': later})
    assert w.cycle() == 2
    assert bodies(fake, gamma)[-1].startswith('**Hestia (Home.aDNA) via the wormhole:** Later')
