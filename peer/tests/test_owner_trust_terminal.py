"""Owner trust at the terminal (docs/superpowers/specs/2026-11-02-machine-trust-design.md, revision 6, item 2a): the
admin's yes at the Pi's terminal grants an owner trust with no password. `station-trust-grant` runs twice: the first run
shows the contact, its peer, the browser's exact grant line, the days, the count and a confirm code, and grants
nothing; the second, with the code and a file of the admin's words naming the contact and the count, grants, and the
grant row keeps the line and the words for its Ops notice."""
from contextlib import closing
import getpass
import os
import re
import shlex
import sqlite3
import subprocess
from pathlib import Path

import pytest
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import pairing_code, show_code
from superyak_peer.owner_trust import OwnerTrust, TERMINAL_CHANGED, WORDS_FIRST
from test_owner_trust import NOW, grant, machine, paired, rows, run  # noqa: F401 - machine, paired: fixtures

REPO = Path(__file__).resolve().parents[2]


def short_of(contact):
    return contact['id'].removeprefix('remote_')[:8]


def yes_for(owner, expect=1):
    """A yes as the rule asks for it: naming the contact's short id and the count."""
    return f'yes, grant it: contact {short_of(owner)}, count {expect}'


def first(paired, days=90, expect=1, contact=None, username='andy'):
    station, _, owner, _ = paired
    return station.station_trust_grant(username, contact or short_of(owner), days=days, expect=expect)


GOOD = object()  # confirm's default: a yes naming the contact and the count


def confirm(paired, code, words=GOOD, days=90, expect=1, contact=None, username='andy'):
    station, _, owner, _ = paired
    return station.station_trust_grant(username, contact or short_of(owner), days=days, expect=expect, confirm=code,
                                       words=yes_for(owner, expect) if words is GOOD else words)


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


def terminal_notices(station):
    return [n for n in station.station_notices() if n['id'].startswith('trust-terminal-')]


def test_a_first_run_grants_nothing_and_shows_the_browsers_exact_line(paired, monkeypatch, capsys):
    """The first run shows the very line the browser's preview shows (owner_trust_line, the same grant_line), the
    contact's label and full peer id, the days and the count plainly, a code and the rule: DAYS and EXPECT are Andy's,
    the whole output is shown, and the yes names the contact and the count. It writes no row. Mutation: the terminal
    building its own line."""
    station, admin, owner, card = paired
    browser = station.owner_trust_line(admin['id'], owner['id'], 90)
    view = first(paired)
    assert view['line'] == browser and not view['granted'] and re.fullmatch(r'[0-9a-f]{8}', view['confirm'])
    status, out, err = cli(monkeypatch, capsys, station, '--contact', short_of(owner), '--days', 90, '--expect', 1,
                           '--as', 'andy')
    assert status == 0 and err == '', err
    lines = out.splitlines()
    assert lines[1] == f"Contact {short_of(owner)} (participant {owner['user_id'][:8]}): Andy B on peer {owner['peer_id']}"
    assert lines[2] == f"Grant line: {browser['text']}"
    assert lines[3] == 'Days: 90. Expected count: 1 (the trust pauses after 1 pairing).'
    assert code_in(out) == view['confirm'] and lines[4].startswith('Nothing is granted yet.')
    assert "DAYS and EXPECT are andy's own numbers" in lines[4]
    assert 'the contact, its peer, the grant line, the days and the count' in lines[4]
    assert f'naming contact {short_of(owner)} and the count ("1 ship"; any number of days must be 90)' in lines[4]
    assert 'WORDS_FILE=<that file>' in lines[4]
    assert pairing_code(card) not in out and show_code(pairing_code(card)) not in out
    assert rows(station) == []


def test_the_confirm_run_grants_and_station_trust_list_names_it(paired, tmp_path):
    """End to end through the real command, on the real clock: the first run's code, then the confirm run with the
    words file grants once; station-trust-list names the trust and says it was granted at the terminal."""
    station, admin, owner, card = paired
    base = ('station-trust-grant', '--data-dir', station.data_dir, '--contact', short_of(owner), '--days', 30,
            '--expect', 2, '--as', 'andy')
    shown = run(*base)
    assert shown.returncode == 0, shown.stderr
    words = tmp_path / 'words.txt'
    words.write_text(yes_for(owner, 2) + '\n')
    done = run(*base, '--confirm', code_in(shown.stdout), '--words-file', words)
    assert done.returncode == 0 and done.stderr == '', done.stderr
    [row] = rows(station)
    assert row['event'] == 'grant' and row['by_id'] == admin['id'] and row['expect'] == 2
    assert row['words'] == yes_for(owner, 2) and f"Grant line: {row['line']}" in shown.stdout
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
    ({'words': 'yes {short} 1 ' + '1a2b-3c4d ' * 4}, 400, 'give the yes without it'),
    ({'words': 'yes {short} 1\nand more'}, 400, 'control, format or invisible'),
    ({'words': 'yes {short}\t1'}, 400, 'control, format or invisible'),
    ({'words': 'yes {short}\u31641'}, 400, 'control, format or invisible'),
])
def test_a_changed_view_or_bad_words_refuse_and_grant_nothing(paired, change, status, word):
    """Each refusal of the confirm run writes nothing: a wrong code, other days or another count than the code was
    shown for, missing, empty or over-long words, words that hold a run shaped like a pairing code (the notice would
    post it in Ops), and words with a newline, a tab or a Hangul filler, which Ops would not show as typed.
    Mutations: the code not bound to the count (the days are bound twice over: the line names the day the trust ends);
    words unchecked."""
    owner = paired[2]
    code = first(paired)['confirm']
    words = change.get('words', GOOD)
    words = words.format(short=short_of(owner)) if isinstance(words, str) else words
    refused(status, word, confirm, paired, change.get('code', code), words=words, days=change.get('days', 90),
            expect=change.get('expect', 1))
    assert rows(paired[0]) == []
    assert len(confirm(paired, code, yes_for(owner) + ' ' + 'y' * 450)['grant_id']) == 32  # good words grant


NO_CONTACT, NO_COUNT = 'short id ({short}', "don't name the expected count"
SHAPE, DAYS_DIFFER, COUNT_DIFFER = 'a range or a fraction', "isn't DAYS", "isn't the expected count"


@pytest.mark.parametrize('words, word, days, expect', [
    ('yes, grant it', NO_CONTACT, 90, 1),
    ('yes {partial}, count 1', NO_CONTACT, 90, 1),
    ('yes x{short}, count 1', NO_CONTACT, 90, 1),
    ('yes deadbeef, 1 ship', NO_CONTACT, 90, 1),                  # R1: another contact's short id
    ('yes {peer12}, 1 ship', NO_CONTACT, 90, 1),                  # R1: the peer id is neither the contact's nor its participant's
    ('yes {short}', NO_COUNT, 90, 1),
    ('yes {short}', NO_COUNT, 90, 4),                             # R1: a count digit only inside the short id
    ('yes {short}, 0.1', NO_COUNT, 90, 1),                        # R1
    ('yes {short}, count 1st', NO_COUNT, 90, 1),
    ('yes {short}, count x1', NO_COUNT, 90, 1),
    ('yes {short} 90, 1', NO_COUNT, 90, 1),                       # two bare numbers, and no noun to tell them apart
    ('yes {short}, 10 ships', COUNT_DIFFER, 90, 1),               # R1: 1 inside 10
    ('yes {short}, 21 ships', COUNT_DIFFER, 90, 1),               # R1
    ('yes {short}, 1,000 ships', COUNT_DIFFER, 90, 1),            # R1
    ('yes {short}, 90 days, 5 ships', COUNT_DIFFER, 90, 90),      # R1: the count equals the days; his words say 5 ships
    ('yes {short}, 1 ship, 2 machines', COUNT_DIFFER, 90, 1),
    ('yes {short} for 90 days, 1 ship', DAYS_DIFFER, 1, 90),      # R1: DAYS and EXPECT swapped
    ('yes {short}, 1 ship for 30 days', DAYS_DIFFER, 90, 1),
    ('yes {short}, a 30-day trust, 1 ship', DAYS_DIFFER, 90, 1),
    ('yes {short}, 1-2 ships', SHAPE, 90, 2),                     # R1: a range
    ('yes {short}, 1 - 2 ships', SHAPE, 90, 2),
    ('yes {short}, 1–2 ships', SHAPE, 90, 2),                # an en dash
    ('yes {short}, 1 to 2 ships', SHAPE, 90, 2),
    ('yes {short}, 1 or 2 ships', SHAPE, 90, 2),
    ('yes {short}, 1/2 ships', SHAPE, 90, 2),                     # R1: a fraction
    ('yes {short}, ½ ships', SHAPE, 90, 2),                  # NFKC reads it as 1, a fraction slash and 2
    ('yes {short}, 1.5 ships', SHAPE, 90, 1),
    ('yes {short}, 1.0 ships', SHAPE, 90, 1),
    ('yes {short}, -1 ships', SHAPE, 90, 1),                      # R1: a sign
    ('yes {short}, +1 ships', SHAPE, 90, 1),
    ('yes {short}, 1 ship, -90 days', SHAPE, 90, 1),
])
def test_the_words_must_name_the_contact_and_the_count_and_their_numbers_mean_the_grants(paired, words, word, days,
                                                                                          expect):
    """The second run refuses words that don't name the contact by a short id of 8 or more characters, or the count
    (spec 2a, the review's N6), and words whose numbers say another grant (the re-check's S5, each of its R1 cases):
    a number next to day or days must be DAYS, one next to ship(s), pairing(s) or machine(s) must be EXPECT, each one
    whole number, never a range, a fraction or a sign; with no such noun the count must be the only bare number. Each
    refusal names what is missing or wrong, never the words. Mutations: the days unchecked; ranges taken."""
    station, _, owner, _ = paired
    code = first(paired, days=days, expect=expect)['confirm']
    filled = words.format(short=short_of(owner), partial=short_of(owner)[:6], peer12=owner['peer_id'][:12])
    error = refused(400, word.format(short=short_of(owner)), confirm, paired, code, words=filled, days=days,
                    expect=expect)
    assert filled not in error.message and rows(station) == []


@pytest.mark.parametrize('words, days, expect', [
    ('Yes, {SHORT}. Count: 1.', 90, 1),
    ('ok {participant} (1)', 90, 1),
    ('yes {short_long} for 1 ship', 90, 1),
    ('{short}: 1', 90, 1),
    ('yes {short}, a 90-day trust for 1 ship', 90, 1),
    ('yes {short} 1 ship 90 days', 90, 1),
    ('yes {short}, 1 ship, until 2027-04-15', 90, 1),             # a date beside a counted noun
    ('yes {short}, 30 days, 2 machines', 30, 2),
    ('yes {short}, up to 1,000 ships', 90, 1000),
    ('yes {short} for 90 days, 90 ships', 90, 90),
    ('yes — {short}, 1 ship', 90, 1),                        # an em dash as punctuation is not a sign
    ('yes {short}, 1 pairing', 90, 1),
    ('yes, {short}, {participant}, {peer12}, 90 days, 1 ship', 90, 1),   # R5: the ids with commas between them
    ('yes {short}, 1 ship \U0001f44d', 90, 1),                    # an emoji with no variation selector
])
def test_the_contact_and_the_count_are_named_in_any_plain_way(paired, words, days, expect):
    """The contact by its short id or its participant's, upper or lower case, or more of either id; the count as a
    numbered noun or the only bare number, next to punctuation; the days with a noun as DAYS, a hyphen between."""
    owner = paired[2]
    filled = words.format(SHORT=short_of(owner).upper(), short=short_of(owner), participant=owner['user_id'][:8],
                          short_long=owner['id'].removeprefix('remote_')[:12], peer12=owner['peer_id'][:12])
    assert confirm(paired, first(paired, days=days, expect=expect)['confirm'], words=filled, days=days,
                   expect=expect)['granted']


def test_every_unicode_space_counts_as_a_plain_one(paired):
    """A no-break space (macOS's Option-Space), an ideographic space and the other Unicode spaces are taken as plain
    ones (the re-check's N10): the words keep them as typed, and the notice posts plain spaces."""
    station, _, owner, _ = paired
    words = f'yes, {short_of(owner)},　1 ship please'
    confirm(paired, first(paired)['confirm'], words=words)
    assert [r['words'] for r in rows(station)] == [words]
    [notice] = terminal_notices(station)
    assert notice['text'].endswith(f'words: "yes, {short_of(owner)}, 1 ship please"')


def digit_ended(owner):
    """An 8 or more character start of the contact's id, or of its participant id, that ends in a digit."""
    for ident in (owner['id'].removeprefix('remote_'), owner['user_id']):
        for n in range(8, len(ident) + 1):
            if ident[n - 1].isdigit():
                return ident[:n]


@pytest.mark.parametrize('dash', [' — ', ' – ', ' - ', ', ', '-'])
def test_a_dash_after_an_id_ending_in_a_digit_is_punctuation(paired, dash):
    """A dash or a slash makes a range only after a whole number that stands alone, never after the digit that ends an
    id (the re-check 2's S6): "yes <id> — 1 ship" grants with an em dash, an en dash and a hyphen, whatever the id
    ends in, while "1-2 ships" still refuses. Mutation: the range read from the one character before the dash."""
    owner = paired[2]
    ident = digit_ended(owner)
    assert ident and ident[-1].isdigit()
    assert confirm(paired, first(paired)['confirm'], words=f'yes {ident}{dash}1 ship')['granted']


def test_a_range_after_a_whole_number_still_refuses_beside_an_id(paired):
    owner = paired[2]
    for words in (f'yes {digit_ended(owner)}, 1-2 ships', f'yes {digit_ended(owner)} 1 - 2 ships'):
        refused(400, SHAPE, confirm, paired, first(paired, expect=2)['confirm'], words=words, expect=2)


@pytest.mark.parametrize('words, expect', [
    ('yes {short}, one ship', 1),                                 # N11: one to ten in words before a counted noun
    ('yes, grant {short} for One ship', 1),
    ('Yes. {short}. Two machines (Serenity and Tardis).', 2),
    ('yes {short}, a one-ship trust', 1),
    ('yes {short}, TEN ships', 10),
    ('yes {short}, count 1. ship it', 1),                         # N11: a period before a space is punctuation
    ('yes {short}, 1. That is all.', 1),
    ('yes {short}, 1 ship ❤️', 1),                       # N11: an emoji's selector is taken
    ('yes {short}, 1 ship ✔️', 1),
    ('️yes {short}, 1 ship', 1),
])
def test_natural_yeses_of_re_check_2_grant(paired, words, expect):
    """The re-check 2's N11: a count of one to ten written in words, a period that ends a sentence after the count, and
    an emoji carrying its variation selector."""
    owner = paired[2]
    filled = words.format(short=short_of(owner))
    assert confirm(paired, first(paired, expect=expect)['confirm'], words=filled, expect=expect)['granted']


@pytest.mark.parametrize('words, expect, word', [
    ('yes {short}, three ships', 1, COUNT_DIFFER),
    ('yes {short}, one ship', 2, COUNT_DIFFER),
    ('yes {short}, eleven ships', 11, 'write it in digits (11 ships)'),
    ('yes {short}, twenty-one ships', 21, 'write it in digits (21 ships)'),
    ('yes {short}, one hundred ships', 100, 'write it in digits (100 ships)'),
    ('yes {short}, 1 ship, ninety days', 1, 'write the number of days in digits (90 days)'),
    ('yes {short}, one ship, ten days', 1, 'write the number of days in digits (90 days)'),
    ('yes {short}, 1 ship for a thirty-day trust', 1, 'write the number of days in digits (90 days)'),
    ('yes {short}, 0.1', 1, NO_COUNT),
    ('yes {short}, 1.5 ships', 1, SHAPE),
    ('yes {short}, 1.0 ships', 1, SHAPE),
])
def test_number_words_and_decimals_that_still_refuse(paired, words, expect, word):
    """Number words past ten before a counted noun, and any before day or days, are refused with a request for digits,
    so a count or a number of days in words is never left unchecked; a decimal point still makes a fraction."""
    station, _, owner, _ = paired
    filled = words.format(short=short_of(owner))
    error = refused(400, word, confirm, paired, first(paired, expect=expect)['confirm'], words=filled, expect=expect)
    assert filled not in error.message and rows(station) == []


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


def test_a_code_grants_once_and_is_stale_after_any_change_to_that_owners_trusts(paired):
    """The code binds the owner's latest owner_trust row (the review's N3): after a grant made with it and a revocation
    the same day, replaying the code and the words grants nothing; a new first run's code does. Mutation: the latest
    row left out of the code."""
    station, admin, owner, _ = paired
    code = first(paired)['confirm']
    done = confirm(paired, code)
    station.revoke_owner_trust(admin['id'], done['grant_id'])
    refused(409, TERMINAL_CHANGED, confirm, paired, code)
    assert [r['event'] for r in rows(station)] == ['grant', 'revoke']
    again = first(paired)['confirm']
    assert again != code and confirm(paired, again)['granted']
    assert [r['event'] for r in rows(station)] == ['grant', 'revoke', 'grant']


def renamed(machine, paired, name):
    """B's person renamed, and Andy's typed code for the new card: the contact keeps its id and gets the new label."""
    b_store, person, _, b_fed = machine
    with b_store.transaction() as db:
        db.execute('UPDATE users SET name=? WHERE id=?', (name, person['id']))
    card = b_fed.card(person['id'])
    station, admin, _, _ = paired
    Federation(station, endpoint='https://localhost:7436').pair(admin['id'], card, code=pairing_code(card))


@pytest.mark.parametrize('before, after', [('Andy B', 'Andy C'),
                                           ('Andy B ' + 'x' * 80 + ' one', 'Andy B ' + 'x' * 80 + ' two')])
def test_a_rename_between_the_runs_refuses(machine, paired, before, after):
    """A rename between the runs, its code typed again, refuses the code shown for the old name. Past the 80th
    character the line reads the same (grant_line shows 80), and only the code's label catches it. Mutation: the
    label left out of the code."""
    station = paired[0]
    renamed(machine, paired, before)
    shown = first(paired)
    renamed(machine, paired, after)
    assert (first(paired)['line'] == shown['line']) == (len(before) > 80)
    refused(409, TERMINAL_CHANGED, confirm, paired, shown['confirm'])
    assert rows(station) == []


def test_the_store_method_needs_the_shown_line_and_checks_it_in_its_transaction(paired):
    """grant_owner_trust_at_terminal takes `shown` as required, not optional, and refuses a line other than the one it
    would store now. Mutation: _as_shown skipped when the terminal calls."""
    station, admin, owner, _ = paired
    line = station.owner_trust_line(admin['id'], owner['id'], 90)['text']
    at = station.grant_owner_trust_at_terminal
    words = yes_for(owner)
    refused(400, 'shown', at, admin['id'], owner['id'], days=90, expect=1, shown=None, words=words, latest=None)
    refused(409, 'reads differently', at, admin['id'], owner['id'], days=90, expect=1, shown=line + '.', words=words,
            latest=None)
    refused(409, 'reads differently', at, admin['id'], owner['id'], days=60, expect=1, shown=line, words=words,
            latest=None)
    refused(400, 'latest', at, admin['id'], owner['id'], days=90, expect=1, shown=line, words=words, latest='1')
    refused(409, "owner's trusts changed", at, admin['id'], owner['id'], days=90, expect=1, shown=line,
            words=words, latest=7)
    assert rows(station) == []
    assert at(admin['id'], owner['id'], days=90, expect=1, shown=line, words=words, latest=None)['text'] == line


def test_the_store_method_refuses_a_non_admin_and_an_ineligible_owner(paired):
    """The store method itself, not only the first run: an actor who isn't an admin (403), a held owner and an owner
    whose typed code isn't current (409), each writing nothing. _grant_in's admin check is the terminal path's only
    one. Mutations: _admin dropped from _grant_in; owner_eligible dropped from _grant_in."""
    station, admin, owner, _ = paired
    sam = station.create_user('sam', 'Sam', 'long-password-sam')
    line = station.owner_trust_line(admin['id'], owner['id'], 90)['text']
    at = station.grant_owner_trust_at_terminal
    words = yes_for(owner)
    refused(403, 'Admin required', at, sam['id'], owner['id'], days=90, expect=1, shown=line, words=words, latest=None)
    with station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?,?)', (owner['id'], NOW))
    refused(409, 'held', at, admin['id'], owner['id'], days=90, expect=1, shown=line, words=words, latest=None)
    with station.transaction() as db:
        db.execute('DELETE FROM contact_holds')
        db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (owner['id'],))
    refused(409, 'A code typed', at, admin['id'], owner['id'], days=90, expect=1, shown=line, words=words, latest=None)
    assert rows(station) == []


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
            expect=1, shown='any', words=yes_for(owner), latest=None)
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
    refused(400, WORDS_FIRST, station.station_trust_grant, 'andy', short_of(owner), days=90, expect=1,
            words=yes_for(owner))
    assert rows(station) == []


def test_no_password_is_read(paired, monkeypatch, capsys, tmp_path):
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
    words = tmp_path / 'words'
    words.write_text(yes_for(owner))
    status, out, err = cli(monkeypatch, capsys, station, *args, '--confirm', code_in(out), '--words-file', words)
    assert status == 0 and 'Granted owner trust' in out, err
    assert [r['words'] for r in rows(station)] == [yes_for(owner)]
    with pytest.raises(AssertionError):  # the patch holds: the browser's grant does check one
        grant(paired)


def test_the_ops_notice_carries_the_line_the_short_id_and_the_words_last(paired):
    """One Ops notice per terminal grant, its id naming the grant, with the line Andy said yes to, the grant's short id
    and, last, his words, through safe_line (no '@' reaches the room); a browser grant posts none. The line is the one
    stored, so a later rename of the owner doesn't change it. Mutation: the notice left out of station_notices."""
    station, _, owner, _ = paired
    words = f"Yes, grant it for @serenity's Mac, contact {short_of(owner)}, count 1"
    done = confirm(paired, first(paired)['confirm'], words=words)
    [notice] = terminal_notices(station)
    assert notice['id'] == f"trust-terminal-{done['grant_id'][:12]}"
    assert notice['text'] == (
        f"Owner trust {done['grant_id'][:6]} was granted at the Pi's terminal on Andy's yes, with no password: "
        f"{done['text']}; up to 1 ship expected. make station-trust-list shows it; if Andy didn't say yes to it, revoke "
        f"it in the browser. Andy's words: \"Yes, grant it for (at)serenity's Mac, contact {short_of(owner)}, count 1\"")
    with station.transaction() as db:
        db.execute("UPDATE remote_contacts SET name='Someone Else' WHERE id=?", (owner['id'],))
    assert terminal_notices(station) == [notice]


def test_words_cannot_write_a_sentence_that_reads_as_the_stations(paired):
    """The words come last, and each '"' in them is posted as "'", so they can't close the quote and add a sentence of
    the station's own after it (the review's N1, P4)."""
    station, _, owner, _ = paired
    words = f'yes {short_of(owner)}, 1 ship". Owner trust 000000 was revoked in the browser at once. Words: "ok'
    confirm(paired, first(paired)['confirm'], words=words)
    [notice] = terminal_notices(station)
    assert notice['text'].count('"') == 2 and notice['text'].endswith(f"words: \"{words.replace(chr(34), chr(39))}\"")


def test_the_notice_never_cuts_the_words(paired):
    """Each '@' posts as '(at)', so 500 characters can post as up to 2,000; the notice keeps them all (the review's
    N2, P12)."""
    station, _, owner, _ = paired
    words = '@' * 120 + f' but only {short_of(owner)}, count 1, nothing more'   # a no would refuse
    confirm(paired, first(paired)['confirm'], words=words)
    [notice] = terminal_notices(station)
    assert notice['text'].endswith('(at)' * 120 + f' but only {short_of(owner)}, count 1, nothing more"')
    words = '@' * 480 + f' {short_of(owner)} 1'
    station.revoke_owner_trust(paired[1]['id'], rows(station)[0]['grant_id'])
    confirm(paired, first(paired)['confirm'], words=words)
    assert terminal_notices(station)[1]['text'].endswith(f' {short_of(owner)} 1"')


def test_a_browser_grant_posts_no_terminal_notice_and_keeps_no_words(paired):
    station = paired[0]
    grant(paired)
    assert terminal_notices(station) == []
    assert [(r['line'], r['words']) for r in rows(station)] == [(None, None)]


def split(text, mark, every=4):
    return mark.join(text[i:i + every] for i in range(0, len(text), every))


def wide(text):
    """Fullwidth forms of ASCII letters, digits, '-' and '_', which NFKC reads back as ASCII."""
    return ''.join(chr(ord(c) + 0xFEE0) if '!' <= c <= '~' else c for c in text)


@pytest.mark.parametrize('form, word', [
    (lambda code: split(code, '\u200b'), 'control, format or invisible'),   # P1: split by a zero-width space (Cf)
    (lambda code: split(code, '\x01'), 'control, format or invisible'),     # P2: split by a control character (Cc)
    (lambda code: split(code, '\u2060'), 'control, format or invisible'),   # a word joiner (Cf)
    (lambda code: split(code, '\ufe0f'), 'control, format or invisible'),   # N7: a variation selector (Mn)
    (lambda code: split(code, '\U000e0100'), 'control, format or invisible'),  # N7: a supplementary one
    (lambda code: split(code, '\u034f'), 'control, format or invisible'),   # N7: the combining grapheme joiner
    (lambda code: split(code, '\u180b'), 'control, format or invisible'),   # N7: a Mongolian selector
    (lambda code: split(code, '\u3164'), 'control, format or invisible'),   # N7: a Hangul filler, drawn blank
    (lambda code: split(code, '\u115f'), 'control, format or invisible'),
    (lambda code: split(code, '\uffa0'), 'control, format or invisible'),
    (lambda code: split(code, '\u2800'), 'control, format or invisible'),   # N12: the braille blank
    (lambda code: split(code, ' \ufe0f'), 'give the yes without it'),       # N11: taken after a space, read past
    (lambda code: split(code, '\u00a0'), 'give the yes without it'),        # N10: a no-break space is a space
    (lambda code: split(code, ' ', 8), 'give the yes without it'),           # not show_code's grouping, but a code typed here
    (lambda code: wide(code), 'give the yes without it'),        # P14: fullwidth, NFKC reads it as the code
    (lambda code: split(wide(code), ' '), 'give the yes without it'),
])
def test_a_pairing_code_in_any_form_of_the_words_is_refused(paired, form, word):
    """The words are checked in every form a reader of Ops could take a code from: as typed, as posted (plain_name and
    safe_line drop format characters and space out control ones, which would join or display a split code) and in
    NFKC. The refusal never shows the code (the review's S2)."""
    station, _, owner, card = paired
    code = pairing_code(card)
    error = refused(400, word, confirm, paired, first(paired)['confirm'], words=f'{yes_for(owner)} {form(code)}')
    assert code not in error.message and show_code(code) not in error.message
    assert rows(station) == [] and terminal_notices(station) == []


@pytest.mark.parametrize('form, word', [
    (lambda key: key, 'live ship key'),
    (lambda key: key[:20] + '\u200b' + key[20:], 'control, format or invisible'),  # P3: the notice would join it
    (lambda key: key[:20] + '\ufe0f' + key[20:], 'control, format or invisible'),  # N7: a reader would see it whole
    (lambda key: wide(key), 'live ship key'),                       # NFKC reads it as the key
])
def test_a_live_ship_key_in_any_form_of_the_words_is_refused(paired, form, word):
    """The notice would post the words in Ops, so a live ship key in any of their forms is refused, never echoed: a
    notice holding one would be refused (422) at every Odo cycle and never post, so the grant would go unseen."""
    from test_presence import docked
    station, admin, owner, _ = paired
    _, key = docked(station, admin['id'], 'rio-grande')
    error = refused(400, word, confirm, paired, first(paired)['confirm'], words=f'{yes_for(owner)} {form(key)}')
    assert key not in error.message and rows(station) == []


@pytest.mark.parametrize('words', [
    'yes {short} {participant} {peer12} 90 days 1 ship',          # R5: 8 + 8 + 12 hex, then the 90 and the da of days
    'yes {short}, 1 ship, peer {peer64}',                         # R5: the whole peer id from the Contact line
    'yes {short} {participant} {peer12} beef, 1 ship',              # 8 + 8 + 12 + 4
])
def test_ids_run_together_are_refused_with_what_to_do(paired, words):
    """32 hex in a row that isn't a code the station knows, or one written as a code is shown, is still refused, since
    the notice would post it, but the refusal says the ids ran together and to put commas between them (the re-check's
    N10). With the commas, the same words grant."""
    station, _, owner, _ = paired
    filled = words.format(short=short_of(owner), participant=owner['user_id'][:8], peer12=owner['peer_id'][:12],
                          peer64=owner['peer_id'])
    error = refused(400, 'put commas between the ids', confirm, paired, first(paired)['confirm'], words=filled)
    assert "give the yes without it" not in error.message and rows(station) == []
    commas = f"yes {short_of(owner)}, {owner['user_id'][:8]}, {owner['peer_id'][:12]}, 90 days, 1 ship"
    assert confirm(paired, first(paired)['confirm'], words=commas)['granted']


def test_an_act_on_that_owner_between_the_two_transactions_refuses_the_grant(paired):
    """The grant's own transaction compares the owner's latest owner_trust row with the one the first run's code was
    bound to (the re-check's N9, R4): an ended browser grant revoked after the confirm run's view and before its grant
    refuses it, and nothing is granted. Mutation: the seq compared only in the view."""
    station, admin, owner, _ = paired
    clock = [NOW]
    station.clock = lambda: clock[0]
    ended = grant(paired, days=1, expect=1)
    clock[0] += 2 * 86400
    code = first(paired)['confirm']
    inner = station.grant_owner_trust_at_terminal

    def revoke_first(*args, **kwargs):
        station.revoke_owner_trust(admin['id'], ended['grant_id'])
        return inner(*args, **kwargs)
    station.grant_owner_trust_at_terminal = revoke_first
    refused(409, "owner's trusts changed", confirm, paired, code)
    assert [r['event'] for r in rows(station)] == ['grant', 'revoke']


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


# The words file (the review's S3): Andy's words never pass through a shell or make.

def test_the_words_file_is_read_as_written(tmp_path):
    """--words-file reads a regular file as UTF-8, takes off one trailing newline and changes nothing else; a file over
    2,000 bytes, one that isn't UTF-8, a missing one, a directory, a link and a FIFO (never waited on) are refused,
    and no refusal shows the content."""
    from superyak_peer.__main__ import WORDS_FILE_MAX, read_words_file
    words = tmp_path / 'words'
    for content, expected in ((b'yes\n', 'yes'), (b'yes\r\n', 'yes'), (b'yes\n\n', 'yes\n'), (b'yes', 'yes'),
                              (b' yes  $5 `x` $(y)', ' yes  $5 `x` $(y)'), ('ja, ölçü'.encode(), 'ja, ölçü')):
        words.write_bytes(content)
        assert read_words_file(words) == expected
    words.write_bytes('é'.encode() * (WORDS_FILE_MAX // 2))
    assert len(read_words_file(words)) == WORDS_FILE_MAX // 2
    words.write_bytes(b'y' * (WORDS_FILE_MAX + 1))
    refused(400, 'over 2000 bytes', read_words_file, words)
    words.write_bytes(b'secret-ish \xff')
    assert 'secret-ish' not in refused(400, 'not UTF-8', read_words_file, words).message
    refused(400, 'missing', read_words_file, tmp_path / 'none')
    refused(400, 'not a regular file', read_words_file, tmp_path)
    link = tmp_path / 'link'
    link.symlink_to(words)
    refused(400, 'not a regular file', read_words_file, link)
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    refused(400, 'not a regular file', read_words_file, fifo)


def test_a_second_trailing_newline_is_kept_and_refused(paired, monkeypatch, capsys, tmp_path):
    """Only one trailing newline is taken off: a second is part of the words, which the grant then refuses."""
    station, _, owner, _ = paired
    args = ('--contact', short_of(owner), '--days', 90, '--expect', 1, '--as', 'andy')
    _, out, _ = cli(monkeypatch, capsys, station, *args)
    words = tmp_path / 'words'
    words.write_text(yes_for(owner) + '\n\n')
    status, out, err = cli(monkeypatch, capsys, station, *args, '--confirm', code_in(out), '--words-file', words)
    assert status == 1 and 'control, format or invisible' in err and yes_for(owner) not in err and rows(station) == []


def make(data_dir, *values):
    return subprocess.run(['make', '-s', '-C', str(REPO), 'station-trust-grant', f'STATION_DATA={data_dir}', *values],
                          capture_output=True, text=True, timeout=120)


USAGE = ("Usage: make station-trust-grant CONTACT=<contact short id> DAYS=90 EXPECT=1 [CONFIRM=<code> "
         "WORDS_FILE=<file holding Andy's words as typed>] [APPROVER=andy]")


def test_the_make_target_refuses_a_missing_value_with_a_usage_line(tmp_path):
    for values in ([], ['DAYS=90', 'EXPECT=1'], ['CONTACT=abcd', 'EXPECT=1'], ['CONTACT=abcd', 'DAYS=90']):
        done = make(tmp_path, *values)
        assert done.returncode != 0 and USAGE in done.stdout + done.stderr


def test_the_make_target_refuses_a_contact_shaped_like_a_code_unshown(tmp_path, paired):
    code = pairing_code(paired[3])
    done = make(tmp_path, f'CONTACT={show_code(code)}', 'DAYS=90', 'EXPECT=1')
    assert done.returncode != 0 and "pairing code's shape" in done.stdout + done.stderr
    assert code not in done.stdout + done.stderr and show_code(code) not in done.stdout + done.stderr


def test_make_never_expands_or_hands_its_values_to_the_shell(tmp_path):
    """None of CONTACT, DAYS, EXPECT, CONFIRM or WORDS_FILE is expanded by make (a `$(shell ...)` in a command-line
    variable runs inside make unless it is unexported) or reaches the shell as text (a `$(...)` or a backtick).
    Mutations: the unexport line dropped; $(value ...) dropped."""
    for name in ('CONTACT', 'DAYS', 'EXPECT', 'CONFIRM', 'WORDS_FILE'):
        markers = [tmp_path / f'{kind}-{name}' for kind in ('make', 'shell', 'tick')]
        values = {'CONTACT': 'abcd', 'DAYS': '90', 'EXPECT': '1', 'CONFIRM': 'abcd1234', 'WORDS_FILE': 'none'}
        values[name] = f'$(shell touch {markers[0]})$$(touch {markers[1]})`touch {markers[2]}`'
        make(tmp_path / 'station', *[f'{k}={v}' for k, v in values.items()])
        assert not any(marker.exists() for marker in markers), name


def test_the_old_words_value_is_refused_and_never_expanded(tmp_path):
    """WORDS= (round 0's form) is unexported, so make never expands it, and the target refuses it with a pointer to
    WORDS_FILE before anything else runs (the re-check's N8). Mutations: WORDS left off the unexport line; the refusal
    dropped."""
    marker = tmp_path / 'ran-words-value'
    line = (f'make -s -C {shlex.quote(str(REPO))} station-trust-grant STATION_DATA={shlex.quote(str(tmp_path / "st"))} '
            f"CONTACT=abcd DAYS=90 EXPECT=1 CONFIRM=abcd1234 'WORDS=x$(shell touch {marker})'")
    done = subprocess.run(['bash', '-c', line], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert done.returncode != 0 and 'WORDS_FILE=<that file>' in done.stdout + done.stderr
    assert not marker.exists() and not (tmp_path / 'st').exists()


MARKS = ('ran-words-dollar', 'ran-words-tick', 'ran-words-make')  # relative: no temp path's hex reaches the words


def test_the_documented_make_line_through_bash_keeps_the_words_file_as_written(paired, tmp_path):
    """The two runs as CLAUDE.md and spec 2a write them, each through bash: the words file holds `$5`, a backtick
    command, a `$(...)` and a `$(shell ...)`, and the stored words equal its content; nothing in it runs, in the
    shell's directory or in make's."""
    station, _, owner, _ = paired
    words = (f'yes, contact {short_of(owner)}, 1 ship: it costs $5 `touch {MARKS[1]}` $(touch {MARKS[0]}) '
             f'$(shell touch {MARKS[2]})')
    words_file = tmp_path / 'words.txt'
    words_file.write_text(words + '\n')
    base = (f'make -s -C {shlex.quote(str(REPO))} station-trust-grant STATION_DATA={shlex.quote(str(station.data_dir))} '
            f'CONTACT={short_of(owner)} DAYS=30 EXPECT=1')
    shown = subprocess.run(['bash', '-c', base], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert shown.returncode == 0, shown.stdout + shown.stderr
    line = f'{base} CONFIRM={code_in(shown.stdout)} WORDS_FILE={shlex.quote(str(words_file))}'
    done = subprocess.run(['bash', '-c', line], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and 'Granted owner trust' in done.stdout, done.stdout + done.stderr
    assert [r['words'] for r in rows(station)] == [words]
    assert not any((where / mark).exists() for where in (tmp_path, REPO) for mark in MARKS)


def test_every_phony_name_has_a_rule_and_none_is_glued_to_another():
    """The review's S1: a missing space in .PHONY joined station-pair-trusted and station-bridge into a name no rule
    has, so neither was phony any more. Every .PHONY name has a rule, once, and no name, phony or a rule's, is two
    rule names run together."""
    lines = (REPO / 'Makefile').read_text().splitlines()
    phony = [name for line in lines if line.startswith('.PHONY:') for name in line.split(':', 1)[1].split()]
    rules = set()
    for line in lines:
        target = re.match(r'([A-Za-z0-9_%/.-][A-Za-z0-9_%/. -]*?)\s*:(?![=:])', line)
        if target and not line.startswith(('\t', '#', '.')):
            rules.update(target.group(1).split())
    assert 'station-trust-grant' in phony and 'station-bridge' in phony and 'station-pair-trusted' in phony
    assert [name for name in phony if name not in rules] == []
    assert len(phony) == len(set(phony))
    glued = [name for name in set(phony) | rules if any(name == a + b for a in rules for b in rules)]
    assert glued == []


@pytest.mark.parametrize('words', [
    'no, not {short}, 1 ship', "don't grant {short}, 1 ship", 'dont grant {short}, 1 ship', 'do not grant {short}, 1 ship',
    'deny {short}, 1 ship', 'never {short} for 1 ship', 'wait. {short} 1 ship? not yet', 'stop, {short} 1 ship',
    'cancel {short}, 1 ship', 'I refuse {short}, 1 ship', 'reject {short}, 1 ship', 'decline {short} 1 ship',
    'nope {short} 1 ship', 'Don\u2019t: {short}, 1 ship', 'NO {short} 1 ship', 'yes {short}, no more than 1 ship',
])
def test_words_that_say_no_never_grant(paired, words):
    """Tardis's read of 26e4545f: words that name the contact and the count but say no granted. A whole-word no now
    refuses, before the naming check, and nothing is granted. Mutation: the NOT_A_YES check removed."""
    owner = paired[2]
    refused(400, 'hold a no', confirm, paired, first(paired)['confirm'], words=words.format(short=short_of(owner)))


@pytest.mark.parametrize('words', ['yes {short}, 1 ship', 'Yes, notably {short} for 1 ship', 'yes {short} 1 ship, nothing more',
                                   'yes {short}, 1 ship, knot and all'])
def test_a_yes_whose_words_only_contain_no_inside_another_word_grants(paired, words):
    """The no is a whole word: "notably", "nothing" and "knot" aren't one."""
    owner = paired[2]
    assert confirm(paired, first(paired)['confirm'], words=words.format(short=short_of(owner)))['granted']
