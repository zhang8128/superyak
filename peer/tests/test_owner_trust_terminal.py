"""Owner trust at the terminal (docs/superpowers/specs/2026-11-02-machine-trust-design.md, revision 6, item 2a): the
admin's yes at the Pi's terminal grants an owner trust with no password. `station-trust-grant` runs twice: the first run
shows the browser's exact grant line and a confirm code and grants nothing; the second, with the code and the words,
grants, and the grant row keeps the line and the words for its Ops notice."""
from contextlib import closing
import getpass
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.identity import pairing_code, show_code
from superyak_peer.owner_trust import OwnerTrust, TERMINAL_CHANGED, WORDS_FIRST
from test_owner_trust import NOW, grant, machine, paired, rows, run  # noqa: F401 - machine, paired: fixtures

REPO = Path(__file__).resolve().parents[2]


def short_of(contact):
    return contact['id'].removeprefix('remote_')[:8]


def first(paired, days=90, expect=1, contact=None, username='andy'):
    station, _, owner, _ = paired
    return station.station_trust_grant(username, contact or short_of(owner), days=days, expect=expect)


def confirm(paired, code, words='yes, grant it', days=90, expect=1, contact=None, username='andy'):
    station, _, owner, _ = paired
    return station.station_trust_grant(username, contact or short_of(owner), days=days, expect=expect, confirm=code,
                                       words=words)


def refused(status, word, call, *args, **kwargs):
    with pytest.raises(Problem) as caught:
        call(*args, **kwargs)
    assert caught.value.status == status and word in caught.value.message, (caught.value.status, caught.value.message)
    return caught.value


def cli(monkeypatch, capsys, station, *args):
    """`station-trust-grant` in this process, its Store on the station's clock, as (exit status, stdout, stderr)."""
    import superyak_peer.__main__ as entry
    monkeypatch.setattr(entry, 'Store', lambda data_dir, **options: Store(data_dir, clock=station.clock, **options))
    try:
        entry.main(['station-trust-grant', '--data-dir', str(station.data_dir), *map(str, args)])
        status = 0
    except SystemExit as stopped:
        status = stopped.code
    said = capsys.readouterr()
    return status, said.out, said.err


def code_in(text):
    return re.search(r'Confirm code: ([0-9a-f]{8})\.', text).group(1)


def test_a_first_run_grants_nothing_and_shows_the_browsers_exact_line(paired, monkeypatch, capsys):
    """The first run shows the very line the browser's preview shows (owner_trust_line, the same grant_line), the
    contact's label and full peer id, the days, the count and a code, and writes no row. Mutation: the terminal building
    its own line."""
    station, admin, owner, card = paired
    browser = station.owner_trust_line(admin['id'], owner['id'], 90)
    view = first(paired)
    assert view['line'] == browser and not view['granted'] and re.fullmatch(r'[0-9a-f]{8}', view['confirm'])
    status, out, err = cli(monkeypatch, capsys, station, '--contact', short_of(owner), '--days', 90, '--expect', 1,
                           '--as', 'andy')
    assert status == 0 and err == '', err
    lines = out.splitlines()
    assert lines[1] == f"Contact {short_of(owner)} (participant {owner['user_id'][:8]}): Andy B on peer {owner['peer_id']}"
    assert lines[2] == f"Grant line: {browser['text']}" and lines[3] == 'For 90 days, expecting up to 1 ship.'
    assert code_in(out) == view['confirm'] and 'Nothing is granted yet' in lines[4]
    assert pairing_code(card) not in out and show_code(pairing_code(card)) not in out
    assert rows(station) == []


def test_the_confirm_run_grants_and_station_trust_list_names_it(paired):
    """End to end through the real command, on the real clock: the first run's code, then the confirm run with the
    words grants once; station-trust-list names the trust and says it was granted at the terminal."""
    station, admin, owner, card = paired
    base = ('station-trust-grant', '--data-dir', station.data_dir, '--contact', short_of(owner), '--days', 30,
            '--expect', 2, '--as', 'andy')
    shown = run(*base)
    assert shown.returncode == 0, shown.stderr
    done = run(*base, '--confirm', code_in(shown.stdout), '--words', 'yes, grant it')
    assert done.returncode == 0 and done.stderr == '', done.stderr
    [row] = rows(station)
    assert row['event'] == 'grant' and row['by_id'] == admin['id'] and row['expect'] == 2
    assert row['words'] == 'yes, grant it' and f"Grant line: {row['line']}" in shown.stdout
    assert f"Granted owner trust {row['grant_id'][:6]}, until " in done.stdout
    listed = run('station-trust-list', '--data-dir', station.data_dir)
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.splitlines()[1].startswith(f"{row['grant_id'][:6]}  Andy B on {owner['peer_id'][:12]}, until ")
    assert listed.stdout.splitlines()[1].endswith(": live, 0 of 2 paired in this window; granted at the Pi's terminal "
                                                  "on andy's yes")
    for out in (shown.stdout, done.stdout, listed.stdout):
        assert pairing_code(card) not in out and show_code(pairing_code(card)) not in out


@pytest.mark.parametrize('change, status, word', [
    ({'code': '00000000'}, 409, TERMINAL_CHANGED),
    ({'days': 89}, 409, TERMINAL_CHANGED),
    ({'expect': 2}, 409, TERMINAL_CHANGED),
    ({'words': None}, 400, 'words are'),
    ({'words': '   '}, 400, 'words are'),
    ({'words': 'y' * 501}, 400, 'at most 500'),
    ({'words': 'yes ' + '1a2b-3c4d ' * 4}, 400, "pairing code's shape"),
])
def test_a_changed_view_or_bad_words_refuse_and_grant_nothing(paired, change, status, word):
    """Each refusal of the confirm run writes nothing: a wrong code, other days or another count than the code was
    shown for, missing, empty or over-long words, and words that hold a run shaped like a pairing code (the notice would
    post it in Ops). Mutations: the code not bound to the count (the days are bound twice over: the line names the day
    the trust ends); words unchecked."""
    code = first(paired)['confirm']
    refused(status, word, confirm, paired, change.get('code', code), words=change.get('words', 'yes, grant it'),
            days=change.get('days', 90), expect=change.get('expect', 1))
    assert rows(paired[0]) == []
    assert len(confirm(paired, code, 'y' * 500)['grant_id']) == 32  # the same run with good words grants


def test_a_code_shown_before_midnight_is_stale_after_it(paired):
    """The code binds the line, and the line names the day the trust ends, so a code shown before a UTC midnight
    refuses after it, as the browser's `shown` does. Mutation: the code not bound to the line."""
    station = paired[0]
    clock = [NOW]
    station.clock = lambda: clock[0]
    code = first(paired)['confirm']
    clock[0] += 86400
    refused(409, TERMINAL_CHANGED, confirm, paired, code)
    assert rows(station) == []
    assert confirm(paired, first(paired)['confirm'])['granted']


def test_the_store_method_needs_the_shown_line_and_checks_it_in_its_transaction(paired):
    """grant_owner_trust_at_terminal takes `shown` as required, not optional, and refuses a line other than the one it
    would store now. Mutation: _as_shown skipped when the terminal calls."""
    station, admin, owner, _ = paired
    line = station.owner_trust_line(admin['id'], owner['id'], 90)['text']
    at = station.grant_owner_trust_at_terminal
    refused(400, 'shown', at, admin['id'], owner['id'], days=90, expect=1, shown=None, words='yes')
    refused(409, 'reads differently', at, admin['id'], owner['id'], days=90, expect=1, shown=line + '.', words='yes')
    refused(409, 'reads differently', at, admin['id'], owner['id'], days=60, expect=1, shown=line, words='yes')
    assert rows(station) == []
    assert at(admin['id'], owner['id'], days=90, expect=1, shown=line, words='yes')['text'] == line


def test_a_live_trust_is_a_409_and_only_an_admin_grants(paired):
    """A live trust, granted in the browser, refuses both runs with a 409; an account that isn't an admin, a ship, an
    unknown account, an unknown contact and a contact named by a pairing code's shape refuse, and none writes."""
    station, admin, owner, card = paired
    station.create_user('sam', 'Sam', 'long-password-sam')
    with station.transaction() as db:
        station._new_ship(db, 'rio-grande', 'Rio Grande', admin['id'])
    code = first(paired)['confirm']
    refused(403, 'Admin required', first, paired, username='sam')
    refused(403, 'Only people', first, paired, username='rio-grande')
    refused(404, 'No account named', first, paired, username='nobody')
    refused(404, "isn't a remote contact", first, paired, contact='ffffffff')
    taken = refused(400, "pairing code's shape", first, paired, contact=pairing_code(card))
    assert pairing_code(card) not in taken.message
    assert rows(station) == []
    grant(paired)
    refused(409, 'already trusted', first, paired)
    refused(409, 'already trusted', confirm, paired, code)
    refused(409, 'already trusted', station.grant_owner_trust_at_terminal, admin['id'], owner['id'], days=90,
            expect=1, shown='any', words='yes')
    assert [r['words'] for r in rows(station)] == [None]


def test_a_contact_is_named_by_the_short_ids_station_lessons_add_takes(paired):
    """The contact's id with or without remote_, or its participant id, as station-lessons-add takes them."""
    owner = paired[2]
    for short in (owner['id'][:12], short_of(owner), owner['user_id'][:8], owner['user_id'][:8].upper()):
        assert first(paired, contact=short)['contact_id'] == owner['id']
    refused(400, 'at least 4', first, paired, contact='abc')


def test_words_before_the_line_is_shown_are_refused(paired):
    """Words are the yes to the line the first run shows, so a first run given words refuses."""
    station, _, owner, _ = paired
    refused(400, WORDS_FIRST, station.station_trust_grant, 'andy', short_of(owner), days=90, expect=1, words='yes')
    assert rows(station) == []


def test_no_password_is_read(paired, monkeypatch, capsys):
    """Neither run asks for, reads or checks a password: each way one could fails the test. Mutation: the terminal
    calling _trust_password."""
    def no(*args, **kwargs):
        raise AssertionError('a password was asked for or checked')
    monkeypatch.setattr(Store, 'check_password_attempt', no)
    monkeypatch.setattr(OwnerTrust, '_trust_password', no)
    monkeypatch.setattr(getpass, 'getpass', no)
    station, _, owner, _ = paired
    args = ('--contact', short_of(owner), '--days', 90, '--expect', 1, '--as', 'andy')
    status, out, err = cli(monkeypatch, capsys, station, *args)
    assert status == 0, err
    status, out, err = cli(monkeypatch, capsys, station, *args, '--confirm', code_in(out), '--words', 'yes')
    assert status == 0 and 'Granted owner trust' in out, err
    assert [r['words'] for r in rows(station)] == ['yes']
    with pytest.raises(AssertionError):  # the patch holds: the browser's grant does check one
        grant(paired)


def test_the_ops_notice_carries_the_line_the_short_id_and_the_words(paired):
    """One Ops notice per terminal grant, its id naming the grant, with the line Andy said yes to, the grant's short id
    and his words, through safe_line (no '@' reaches the room); a browser grant posts none. The line is the one stored,
    so a later rename of the owner doesn't change it. Mutation: the notice left out of station_notices."""
    station, _, owner, _ = paired
    done = confirm(paired, first(paired)['confirm'], words='Yes, grant it for @serenity\'s Mac, contact ' + short_of(owner))
    [notice] = [n for n in station.station_notices() if n['id'].startswith('trust-terminal-')]
    assert notice['id'] == f"trust-terminal-{done['grant_id'][:12]}"
    assert notice['text'] == (
        f"Owner trust {done['grant_id'][:6]} was granted at the Pi's terminal on Andy's yes, with no password: "
        f"{done['text']}; up to 1 ship expected. Andy's words: \"Yes, grant it for (at)serenity's Mac, contact "
        f"{short_of(owner)}\". make station-trust-list shows it; if Andy didn't say yes to it, revoke it in the browser.")
    with station.transaction() as db:
        db.execute("UPDATE remote_contacts SET name='Someone Else' WHERE id=?", (owner['id'],))
    assert [n for n in station.station_notices() if n['id'] == notice['id']] == [notice]


def test_a_browser_grant_posts_no_terminal_notice_and_keeps_no_words(paired):
    station = paired[0]
    grant(paired)
    assert not [n for n in station.station_notices() if n['id'].startswith('trust-terminal-')]
    assert [(r['line'], r['words']) for r in rows(station)] == [(None, None)]


def test_words_holding_a_live_ship_key_are_refused(paired):
    """The notice would post the words in Ops, so words holding a live ship key are refused, and never echoed."""
    from test_presence import docked
    station, admin, owner, _ = paired
    _, key = docked(station, admin['id'], 'rio-grande')
    error = refused(400, 'ship key', confirm, paired, first(paired)['confirm'], words=f'yes {key}')
    assert key not in error.message and rows(station) == []


def test_the_table_checks_the_line_and_the_words(paired):
    """owner_trust itself refuses words on a row that isn't a grant, words without the line, a line without words and
    words past 500 characters, as it checks `expect`, and stays append-only for the new columns."""
    station, admin, owner, _ = paired
    done = confirm(paired, first(paired)['confirm'])
    insert = ('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect,line,words) '
              'VALUES (?,?,?,?,?,?,?,?,?,?)')
    base = [done['grant_id'], 'renew', owner['peer_id'], owner['user_id'], NOW + 86400, admin['id'], NOW, 1]
    for event, line, words in (('renew', 'l', 'yes'), ('grant', None, 'yes'), ('grant', 'l', None), ('grant', 'l', 'y' * 501)):
        values = list(base)
        values[1] = event
        with station.transaction() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, (*values, line, words))
    with station.transaction() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE owner_trust SET words='no'")
    assert len(rows(station)) == 1


OLD_OWNER_TRUST = '''CREATE TABLE owner_trust(seq INTEGER PRIMARY KEY AUTOINCREMENT, grant_id TEXT NOT NULL,
  event TEXT NOT NULL CHECK(event IN ('grant','renew','revoke')), peer_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  until REAL, by_id TEXT, at REAL NOT NULL, reason TEXT, expect INTEGER,
  CHECK(event='revoke' OR (expect IS NOT NULL AND expect BETWEEN 1 AND 10000)))'''


def schema_of(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT sql FROM sqlite_master WHERE name='owner_trust'").fetchone()[0]


def test_an_older_store_gains_the_columns_and_the_same_schema_text(tmp_path):
    """A store made before revision 6 keeps its grants, gains `line` and `words` at the next start, and then holds the
    very schema text a new store has, so a restore's comparison of the two finds no difference. Mutation: the columns
    added in another order or with another check."""
    old = tmp_path / 'old'
    old.mkdir(mode=0o700)
    with closing(sqlite3.connect(old / 'peer.sqlite3')) as db:
        db.execute(OLD_OWNER_TRUST)
        db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect) "
                   "VALUES ('g','grant','p','o',1,'b',0,5)")
        db.commit()
    Store(old)
    Store(tmp_path / 'new')
    assert schema_of(old / 'peer.sqlite3') == schema_of(tmp_path / 'new' / 'peer.sqlite3')
    with closing(sqlite3.connect(old / 'peer.sqlite3')) as db:
        assert db.execute('SELECT grant_id, line, words FROM owner_trust').fetchall() == [('g', None, None)]


def make(tmp_path, *values):
    return subprocess.run(['make', '-s', '-C', str(REPO), 'station-trust-grant', f'STATION_DATA={tmp_path}', *values],
                          capture_output=True, text=True, timeout=120)


def test_the_make_target_refuses_a_missing_value_with_a_usage_line(tmp_path):
    for values in ([], ['DAYS=90', 'EXPECT=1'], ['CONTACT=abcd', 'EXPECT=1'], ['CONTACT=abcd', 'DAYS=90']):
        done = make(tmp_path, *values)
        assert done.returncode != 0 and 'Usage: make station-trust-grant CONTACT=<contact short id> DAYS=90 EXPECT=1 ' \
            '[CONFIRM=<code> WORDS="<Andy\'s words>"] [APPROVER=andy]' in done.stdout + done.stderr


def test_the_make_target_refuses_a_contact_shaped_like_a_code_unshown(tmp_path, paired):
    code = pairing_code(paired[3])
    done = make(tmp_path, f'CONTACT={show_code(code)}', 'DAYS=90', 'EXPECT=1')
    assert done.returncode != 0 and "pairing code's shape" in done.stdout + done.stderr
    assert code not in done.stdout + done.stderr and show_code(code) not in done.stdout + done.stderr


def test_the_make_target_never_hands_its_values_to_the_shell(tmp_path):
    """Andy's words may hold a `$(...)` or a backtick; neither, in any value, reaches the shell as text."""
    for name in ('CONTACT', 'DAYS', 'EXPECT', 'CONFIRM', 'WORDS'):
        ran, ticked = tmp_path / f'ran-{name}', tmp_path / f'tick-{name}'
        values = {'CONTACT': 'abcd', 'DAYS': '90', 'EXPECT': '1', 'CONFIRM': 'abcd1234', 'WORDS': 'yes'}
        values[name] = f'$$(touch {ran}) `touch {ticked}`'
        make(tmp_path / 'station', *[f'{k}={v}' for k, v in values.items()])
        assert not ran.exists() and not ticked.exists(), name


def test_the_make_target_grants_with_the_words_as_typed(paired):
    """The two runs through make on a real station, with words holding a `$`, quotes and a backtick, kept as typed."""
    station, _, owner, _ = paired
    values = [f'CONTACT={short_of(owner)}', 'DAYS=30', 'EXPECT=1']
    shown = make(station.data_dir, *values)
    assert shown.returncode == 0, shown.stdout + shown.stderr
    words = 'yes, "grant" it: it costs $5 `and` nothing else'
    done = make(station.data_dir, *values, f'CONFIRM={code_in(shown.stdout)}', f'WORDS={words}')
    assert done.returncode == 0 and 'Granted owner trust' in done.stdout, done.stdout + done.stderr
    assert [r['words'] for r in rows(station)] == [words]
