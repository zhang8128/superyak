"""Owner trust (docs/superpowers/specs/2026-11-02-machine-trust-design.md, "The change" item 2): the admin's password lets
one remote person, a contact whose code was typed, vouch for their ships on their own peer. This module holds the
append-only `owner_trust` table and its companions, granting and renewing, and the two rules the pairing and
`connections()` share: `code_current` and `live_trust`. Revision 6: the admin's yes at the Pi's terminal grants too,
with no password (`station-trust-grant`), and the grant row keeps the line they said yes to and their words."""
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata

from .common import Problem, encode, uid
from .identity import pairing_code, typed_code
from .ships import safe_line, ship_label_line, short_id

TRUST_DAYS = 90
EXPECT_MAX = 10_000
WORDS_MAX = 500  # spec revision 6: the admin's yes at the terminal, as typed, kept with the grant
TRUST_CAP = 200  # spec "The change" item 4: contacts per owner trust per UTC day, from trust_confirmations
DIGEST_DAYS = 7  # the ended UTC days the digest lists, so Odo catches up after a week away (spec item 5)
# A day's digest waits this long after midnight (UTC): pair_trusted dates a pairing when its transaction starts, so one
# begun just before midnight can commit just after it, and a digest posted at once would be a pairing short for good.
DIGEST_SETTLE = 300
# Spec revision 6: a grant made at the terminal keeps the grant line the admin said yes to and the words they typed;
# a browser grant, whose proof is the password, and every renewal and revocation keep neither. The table checks the
# pair, as it checks `expect`. db.py adds them to an older store in this order, which places each just as the CREATE
# below does, so an old store and a new one hold the same schema text.
TERMINAL_COLUMNS = (('line', 'TEXT'),
                    ('words', "TEXT CHECK(CASE WHEN words IS NULL THEN line IS NULL ELSE event='grant' AND line IS NOT NULL "
                              f'AND length(words) BETWEEN 1 AND {WORDS_MAX} END)'))
OWNER_TRUST_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS owner_trust(seq INTEGER PRIMARY KEY AUTOINCREMENT, grant_id TEXT NOT NULL,
  event TEXT NOT NULL CHECK(event IN ('grant','renew','revoke')), peer_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  until REAL, by_id TEXT, at REAL NOT NULL, reason TEXT, expect INTEGER, '''
    + ', '.join(f'{name} {ddl}' for name, ddl in TERMINAL_COLUMNS) + ''',
  CHECK(event='revoke' OR (expect IS NOT NULL AND expect BETWEEN 1 AND 10000)))''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_update BEFORE UPDATE ON owner_trust
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_delete BEFORE DELETE ON owner_trust
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TRIGGER IF NOT EXISTS owner_trust_no_replace BEFORE INSERT ON owner_trust
WHEN EXISTS (SELECT 1 FROM owner_trust WHERE seq=NEW.seq)
BEGIN SELECT RAISE(ABORT, 'owner_trust is append-only'); END''',
    '''CREATE TABLE IF NOT EXISTS trust_confirmations(id TEXT PRIMARY KEY, contact_id TEXT NOT NULL,
  grant_id TEXT NOT NULL, assertion TEXT NOT NULL, acting_ship_id TEXT NOT NULL, confirmed REAL NOT NULL,
  day TEXT NOT NULL, window_seq INTEGER NOT NULL)''',
    # The cap's count and contact_labels' latest confirmation per contact, by index rather than by scan (ruling, Task 3).
    '''CREATE TRIGGER IF NOT EXISTS trust_confirmations_no_update BEFORE UPDATE ON trust_confirmations
BEGIN SELECT RAISE(ABORT, 'trust_confirmations is append-only'); END''',
    '''CREATE TRIGGER IF NOT EXISTS trust_confirmations_no_delete BEFORE DELETE ON trust_confirmations
BEGIN SELECT RAISE(ABORT, 'trust_confirmations is append-only'); END''',
    'CREATE INDEX IF NOT EXISTS trust_confirmations_contact ON trust_confirmations(contact_id, confirmed)',
    'CREATE INDEX IF NOT EXISTS trust_confirmations_grant_day ON trust_confirmations(grant_id, day)',
    # trust_window's count of one window, by index.
    'CREATE INDEX IF NOT EXISTS trust_confirmations_window ON trust_confirmations(window_seq)',
    '''CREATE TABLE IF NOT EXISTS trust_cap_refusals(grant_id TEXT NOT NULL, day TEXT NOT NULL,
  refused INTEGER NOT NULL, PRIMARY KEY(grant_id, day))''',
    '''CREATE TABLE IF NOT EXISTS retired_peers(peer_id TEXT PRIMARY KEY, retired REAL NOT NULL, by_id TEXT)''',
    # Ruling (after Tardis's plan review): remote_contacts.name stays the card's participant name, so a typed-code pair
    # that rewrites it can't make a ship read as a person. A contact with any trust confirmation, revoked or held too,
    # reads "ship of <owner>: <name>", its owner taken from its latest confirmation's grant as (peer, participant id),
    # never an id alone, and that owner's name read live. Every other contact reads as its own name.
    '''CREATE VIEW IF NOT EXISTS contact_labels(id, label) AS SELECT c.id, CASE WHEN t.grant_id IS NULL THEN c.name
  ELSE 'ship of ' || COALESCE((SELECT o.name FROM owner_trust g JOIN remote_contacts o ON o.peer_id=g.peer_id
    AND o.user_id=g.owner_user_id WHERE g.grant_id=t.grant_id ORDER BY g.seq LIMIT 1), 'an unknown owner') || ': ' || c.name
  END FROM remote_contacts c LEFT JOIN trust_confirmations t ON t.rowid=(SELECT rowid FROM trust_confirmations
    WHERE contact_id=c.id ORDER BY confirmed DESC, rowid DESC LIMIT 1)''',
)
OWNER_TRUST_SCHEMA = ';\n'.join(OWNER_TRUST_STATEMENTS) + ';'

DAYS_SHAPE = f'days is a whole number from 1 to {TRUST_DAYS}'
EXPECT_SHAPE = f'expect is a whole number from 1 to {EXPECT_MAX}'
GRANT_TEXT = "ships owned by {name} on {peer} may be paired by this station's ships, until {date}"
DIGEST_TEXT = ('Owner trust, {day}: {n} ship(s) of {owner} on {peer} paired by {ships}{refused}. '
               'Full ids: make station-trust-list on the Pi.')
PAUSE_TEXT = ("Owner trust for {owner} on {peer} paused after {n} pairings. make station-trust-list shows them; if you "
              "didn't expect them, unpair that peer as retired; otherwise renew or revoke it in the browser.")
PAUSE_WAITING = ' {k} of its ships wait for the lessons room until you renew.'
PAUSE_WAITING_ONE = ' 1 of its ships waits for the lessons room until you renew.'
# Spec revision 6: the Ops notice of a grant made at the terminal, and the terminal's refusals (none echoes the words).
# The words come last, each '"' in them posted as "'", so they can't write a sentence that reads as the station's own.
TERMINAL_TEXT = ("Owner trust {short} was granted at the Pi's terminal on {who}'s yes, with no password: {line}; up to {n} "
                 "ship{s} expected. make station-trust-list shows it; if {who} didn't say yes to it, revoke it in the "
                 "browser. {who}'s words: \"{words}\"")
WORDS_SHAPE = f"words are the admin's yes as typed at the terminal: not empty, at most {WORDS_MAX} characters"
WORDS_UNPRINTABLE = ("The words hold a control, format or invisible character (a Hangul filler, a braille blank, and a "
                     "variation selector after a letter, a digit, '-' or '_', count), or another that Ops would not "
                     'show as written, so they are not taken: only printable characters and spaces are')
WORDS_CODE_SHAPED = ("The words hold a run with a pairing code's shape (32 hex), so they aren't taken or shown; give the "
                     'yes without it')
WORDS_IDS_RUN_TOGETHER = ("The words hold 32 or more hex characters in a row once spaces and hyphens are taken out, a "
                          "pairing code's shape, though not a code the station knows: ids that run together, or a whole "
                          "peer id. So they aren't taken; put commas between the ids, and name the contact by its short id")
WORDS_KEY = "The words hold a live ship key, so they aren't taken or shown"
WORDS_NO_CONTACT = ("The words don't name the contact by its short id ({short}, as the first run shows it), so they aren't "
                    'taken: the yes names it')
WORDS_NO_COUNT = ("The words don't name the expected count ({n}), as \"{n} ship{s}\" or as their only number apart from the "
                  'days, so they aren\'t taken: the yes names it')
WORDS_NUMBER_SHAPE = ('The words give a signed number, a range or a fraction next to days, ships, pairings or machines, so '
                      "they aren't taken: the yes gives each as one whole number")
WORDS_DAYS_IN_DIGITS = ("The words give the days in words, so they aren't taken: write the number of days in digits "
                        '({days} days)')
WORDS_COUNT_IN_DIGITS = ("The words give the count in words past ten, so they aren't taken: write it in digits "
                         '({n} ship{s})')
WORDS_DAYS_DIFFER = ("A number of days in the words isn't DAYS ({days}), so they aren't taken: the yes names the grant it "
                     'approves')
WORDS_COUNT_DIFFER = ("A number of ships, pairings or machines in the words isn't the expected count ({n}), so they aren't "
                      'taken: the yes names the grant it approves')
WORDS_TRUSTS_CHANGED = ("That owner's trusts changed since the first run (a grant, a renewal or a revocation), so nothing "
                        'is granted; run it again without CONFIRM')
WORDS_FIRST = ("Words come with the second run, with CONFIRM: they are the admin's yes to the line the first run shows, "
               'so run it first without them')
TERMINAL_CHANGED = ("The contact, its grant line, the days, the expected count or that owner's trusts changed since they "
                    'were shown, or that is not the code shown; run it again without CONFIRM')
# A contact as every display names it (the ruling after Tardis's plan review): by its label, never its raw name.
LABELLED_CONTACT = 'SELECT c.id, c.peer_id, c.user_id, l.label FROM remote_contacts c JOIN contact_labels l ON l.id=c.id'


SPELLING_JOINERS = frozenset('‌‍')  # ZWNJ, ZWJ: format characters that names are spelled with


def plain_name(text):
    """A label or name bound for the browser's JSON with its format characters (category Cf, such as a right-to-left
    override or an isolate) and other non-printables removed or made spaces, so a paired person's name can't reorder the
    ship part of a label, even inside <bdi>. The CLI reads the same text. The zero-width non-joiner and joiner stay:
    Persian, Hindi and other scripts spell names with them, and neither reorders text."""
    if text is None:
        return None
    kept = ''.join(c for c in str(text) if c in SPELLING_JOINERS or unicodedata.category(c) != 'Cf')
    return ''.join(c if c.isprintable() or c in SPELLING_JOINERS else ' ' for c in kept)


def code_current(db, contact_id):
    """The rule `connections()` uses: a typed code confirms the contact only while it is still the code of the
    stored card with this contact's participant, and the peer is paired. A card that no longer validates has no code."""
    row = db.execute('SELECT remote_contacts.user_id,remote_contacts.name,peers.card,peers.paired,'
                     'pairing_confirmations.code FROM remote_contacts JOIN peers USING(peer_id) '
                     'JOIN pairing_confirmations ON pairing_confirmations.contact_id=remote_contacts.id '
                     'WHERE remote_contacts.id=?', (contact_id,)).fetchone()
    if row is None or not row['paired']:
        return False
    try:
        code = pairing_code({**json.loads(row['card']), 'participant': {'id': row['user_id'], 'name': row['name']}})
    except Problem:
        return False
    return row['code'] == code


def live_trust(db, peer_id, owner_user_id, now):
    """The unrevoked trust for this owner (a peer and a participant id, never an id alone) with its latest `until`
    still ahead of `now`, as a row with `grant_id` and `until`; None when there is none."""
    return db.execute(
        'SELECT grant_id, MAX(until) AS until FROM owner_trust WHERE peer_id=? AND owner_user_id=? '
        "AND grant_id NOT IN (SELECT grant_id FROM owner_trust WHERE event='revoke') "
        'GROUP BY grant_id HAVING MAX(until)>? ORDER BY MAX(until) DESC LIMIT 1', (peer_id, owner_user_id, now)).fetchone()


# Latest by the wall-clock `confirmed`: a clock stepped back fails closed, the ship held again at the next settle.
LATEST = 'ORDER BY confirmed DESC, rowid DESC LIMIT 1'  # a contact's latest trust confirmation, as contact_labels picks it
# The ships not held, each with the grant of its latest confirmation.
UNHELD_SHIPS = ('SELECT c.id, c.peer_id, c.user_id, t.grant_id FROM remote_contacts c JOIN trust_confirmations t ON '
                f't.rowid=(SELECT rowid FROM trust_confirmations WHERE contact_id=c.id {LATEST}) '
                'WHERE c.id NOT IN (SELECT contact_id FROM contact_holds)')
REVOKED = "SELECT grant_id FROM owner_trust WHERE event='revoke'"


def latest_grant(db, contact_id):
    """The grant of this contact's latest trust confirmation, or None for a contact no trust made."""
    row = db.execute(f'SELECT grant_id FROM trust_confirmations WHERE contact_id=? {LATEST}', (contact_id,)).fetchone()
    return row[0] if row else None


def ships_to_hold(db, grant_ids=None):
    """The ships a revocation holds: those not held whose latest confirmation's grant is revoked (`grant_ids` None) or
    one of `grant_ids`, less any whose own typed code is current. A code typed for that one account is a person's act
    and the stronger proof, so it stands when a trust ends (coordinator's ruling on Task 4, after the spec's "What a
    code proves")."""
    if grant_ids is None:
        rows = db.execute(f'{UNHELD_SHIPS} AND t.grant_id IN ({REVOKED})')
    else:
        grant_ids = list(grant_ids)
        if not grant_ids:
            return []
        rows = db.execute(f"{UNHELD_SHIPS} AND t.grant_id IN ({','.join('?' * len(grant_ids))})", grant_ids)
    return [ship for ship in rows.fetchall() if not code_current(db, ship['id'])]


def hold_contact(db, contact, now):
    """Holds one contact as Federation.unpair holds each of a peer's (backups._hold_like_replaced, for one): its
    confirmation gone, its pending and failed outbox rows withdrawn, and the received payloads it authored cleared.
    A contact already held keeps the date of its first hold. A trust-made member of the lessons room leaves its chain
    (drop_held_from_lessons), read before its confirmation goes; a Store caller of settle_owner_trust emits for the
    rooms that changed (_emit_held)."""
    from .lessons import drop_held_from_lessons
    db.execute('INSERT OR IGNORE INTO contact_holds VALUES(?, ?)', (contact['id'], now))
    drop_held_from_lessons(db, [contact['id']], now)
    db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (contact['id'],))
    db.execute("UPDATE outbox SET status='withdrawn' WHERE contact_id=? AND status IN ('pending','failed')", (contact['id'],))
    db.execute('UPDATE inbox SET payload=NULL WHERE origin=? AND actor=? AND payload IS NOT NULL',
               (contact['peer_id'], contact['user_id']))


def _owner_failed(db, peer_id, owner_user_id):
    """Whether a trust's owner can no longer vouch: its peer retired, its contact gone or held, or its typed code no
    longer current (which `code_current` also finds for a peer that is unpaired or missing)."""
    if db.execute('SELECT 1 FROM retired_peers WHERE peer_id=?', (peer_id,)).fetchone():
        return True
    owner = db.execute('SELECT id FROM remote_contacts WHERE peer_id=? AND user_id=?', (peer_id, owner_user_id)).fetchone()
    if owner is None or db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (owner['id'],)).fetchone():
        return True
    return not code_current(db, owner['id'])


def settle_owner_trust(db, now):
    """The one invariant (spec "The change" items 3 and 6, S10, N13), run inside the caller's transaction by unpair,
    pair, a revoke and a restore. Every unrevoked trust, expired ones too, whose owner has failed gets a revocation
    dated `now` with reason 'owner held', so every hold of an owner has a date; then every ship whose latest
    confirmation names a revoked trust, and whose own typed code isn't current, is held. Returns the grant ids it
    revoked, in grant order."""
    revoked = []
    while True:  # until a pass ends nothing; a held ship is never an owner (an owner has no trust confirmation)
        grants = db.execute(f"SELECT grant_id, peer_id, owner_user_id FROM owner_trust WHERE event='grant' "
                            f'AND grant_id NOT IN ({REVOKED}) ORDER BY seq').fetchall()
        ended = [g for g in grants if _owner_failed(db, g['peer_id'], g['owner_user_id'])]
        for g in ended:
            db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,reason) "
                       "VALUES (?,'revoke',?,?,NULL,NULL,?,'owner held')", (g['grant_id'], g['peer_id'], g['owner_user_id'], now))
        revoked += [g['grant_id'] for g in ended]
        for ship in ships_to_hold(db):
            hold_contact(db, ship, now)
        if not ended:
            return revoked


def _days(days):
    if type(days) is not int or not 1 <= days <= TRUST_DAYS:
        raise Problem(400, DAYS_SHAPE)
    return days


def _expect(expect):
    if type(expect) is not int or not 1 <= expect <= EXPECT_MAX:
        raise Problem(400, EXPECT_SHAPE)
    return expect


def posted_words(words):
    """The words as the Ops notice posts them (trust_terminal_notices): through plain_name and safe_line, cut only at the
    length safe_line's '@' to '(at)' can reach, so no part of WORDS_MAX characters is lost, with each '"' made "'"."""
    return safe_line(plain_name(words), 4 * WORDS_MAX).replace('"', "'")


def word_forms(words):
    """Every form of the words a check reads (spec revision 6, the review's S2): as typed, as posted, and the NFKC form
    of each, in which fullwidth or other compatibility letters read as the ASCII a person would type; each with its
    variation selectors taken out (SELECTORS), so a selector the words may hold can't hide a run of hex or a key."""
    posted = posted_words(words)
    forms = (words, posted, *(unicodedata.normalize('NFKC', form) for form in (words, posted)))
    return tuple(SELECTOR.sub('', form) for form in forms)


# Unicode's Default_Ignorable_Code_Point (DerivedCoreProperties), the Hangul fillers among them, less the variation
# selectors (SELECTORS, below), and U+2800 BRAILLE PATTERN BLANK, which is drawn blank but isn't default-ignorable (the
# re-check 2's N12): each is drawn as nothing, so a code or a key split by one reads whole in Ops. Most are format
# characters, which the printable rule refuses anyway; the combining grapheme joiner, the Mongolian selectors, the
# fillers and the braille blank are printable to Python, so they are named here (the re-check's N7). Look-alike letters
# (a Cyrillic a, U+0430, for a Latin a) are taken, as a room post takes them: parity with every message, since room
# posts refuse no pairing code at all.
INVISIBLE = ((0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
             (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x2800, 0x2800), (0x3164, 0x3164), (0xFEFF, 0xFEFF),
             (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE00FF),
             (0xE01F0, 0xE0FFF))
# The variation selectors. One splits a code or a key only where it follows an ASCII letter, a digit, '-' or '_', so it
# is refused only there; elsewhere it is an emoji's (a heart, a check mark) and taken (the re-check 2's N11). The checks
# read every form with them taken out (word_forms).
SELECTORS = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))
SELECTOR = re.compile('[\ufe00-\ufe0f\U000e0100-\U000e01ef]')


def _within(ranges, c):
    return any(low <= ord(c) <= high for low, high in ranges)


def _shown_as_written(c, before=''):
    """A character the notice shows as typed, after `before` (the character before it, or ''): a space of any kind
    (Unicode Zs, the no-break space that macOS's Option-Space types included), which safe_line posts as a plain space;
    a variation selector that follows no ASCII letter, digit, '-' or '_'; or any other printable character that isn't
    invisible (INVISIBLE)."""
    if unicodedata.category(c) == 'Zs':
        return True
    if _within(SELECTORS, c):
        return not re.fullmatch(r'[A-Za-z0-9_-]', before)
    return c.isprintable() and not _within(INVISIBLE, c)


def _words(words):
    """The admin's yes at the terminal (spec revision 6), kept as typed: text that isn't empty once stripped, of at most
    WORDS_MAX characters, every character one the notice shows as written (_shown_as_written: no control, format or
    invisible character for plain_name or safe_line to drop, space out or hide a split behind). The code and key checks
    run in the grant's transaction (_refuse_codes)."""
    if not isinstance(words, str) or not words.strip() or len(words) > WORDS_MAX:
        raise Problem(400, WORDS_SHAPE)
    if not all(_shown_as_written(c, words[i - 1] if i else '') for i, c in enumerate(words)):
        raise Problem(400, WORDS_UNPRINTABLE)
    return words


# A pairing code as a person would copy it: 32 hex alone, or show_code's eight groups of four between spaces or hyphens
CODE_FORM = re.compile(r'(?<![0-9a-f])(?:[0-9a-f]{32}|[0-9a-f]{4}(?:[\s-]+[0-9a-f]{4}){7})(?![0-9a-f])', re.ASCII)


def _refuse_codes(db, words):
    """The Ops notice posts the words, and a ship never puts a pairing code in a room, so 32 hex in a row in any of their
    forms (word_forms), once spaces and hyphens are taken out as typed_code reads a code, is refused unread. The refusal
    says which: a code (one the station holds as typed for a contact, or written as a code is shown), or ids run
    together (the re-check's N10), with what to do. Either way nothing is taken."""
    forms = [form.lower() for form in word_forms(words)]
    joined = [re.sub(r'[\s-]', '', form) for form in forms]
    if not any(re.search(r'[0-9a-f]{32}', form, re.ASCII) for form in joined):
        return
    known = [row[0] for row in db.execute('SELECT code FROM pairing_confirmations') if row[0]]
    if any(CODE_FORM.search(form) for form in forms) or any(code in form for code in known for form in joined):
        raise Problem(400, WORDS_CODE_SHAPED)
    raise Problem(400, WORDS_IDS_RUN_TOGETHER)


COUNT_NOUNS = {'ship', 'ships', 'pairing', 'pairings', 'machine', 'machines'}
NOUN = r'(days?|ships?|pairings?|machines?)(?![a-z])'
# A number next to a noun the grant has a number for: "90 days", "a 90-day trust", "1 ship", "1,000 machines". The number
# takes in any '.', ',' or '/' with a digit after it, so "1.5 ships" or "1/2 ships" is read whole and refused, while a
# period or comma before a space or the end is punctuation ("count 1. ship it") (the re-check 2's N11).
NUMBERED = re.compile(r'(?<![0-9a-z])([0-9](?:[0-9]|[.,/](?=[0-9]))*)(?:\s*-\s*|\s*)' + NOUN)
WHOLE = re.compile(r'[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+')
BARE = re.compile(r'(?<![0-9a-z.,/+-])([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?![0-9a-z])(?![.,/][0-9])')
# What comes just before a number that makes it a range or a fraction: a whole number that stands alone (never the end
# of an id or another word, the re-check 2's S6), then a dash, a slash, "to" or "or"; and what makes it signed: a minus
# or a plus that follows no letter or digit ("-1 ships", where "x-1" is a hyphenated word).
RANGE_BEFORE = re.compile(r'(?<![0-9a-z])([0-9][0-9,]*)(?:\s*[-\u2013\u2014/\u2044\u2215]\s*|\s+(?:to|or)\s+)$')
SIGN_BEFORE = re.compile(r'(?:^|[^0-9a-z])[-+\u2212]$')
# Number words: one to ten before a counted noun are read as the number (the re-check 2's N11); any other, and any
# before day or days, are refused with a request for digits, so a count or days written in words is never unchecked.
ONE_TO_TEN = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
              'ten': 10}
NUMBER_WORDS = sorted([*ONE_TO_TEN, 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen',
                       'eighteen', 'nineteen', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty',
                       'ninety', 'hundred', 'thousand'], key=len, reverse=True)
WORD_NUMBER = '(?:' + '|'.join(NUMBER_WORDS) + ')'
WORDED = re.compile(r'(?<![0-9a-z-])(' + WORD_NUMBER + r'(?:(?:\s*-\s*|\s+)(?:and\s+)?' + WORD_NUMBER + r')*)'
                    r'(?:\s*-\s*|\s+)' + NOUN)


def _names_the_grant(words, contact, days, expect):
    """Spec revision 6, item 2a: the yes names the contact and the count, and its numbers mean what the grant does, so the
    stored words can be checked against the grant they approved. Read in the NFKC form, case folded.
    - The contact: a run of 8 or more ASCII letters and digits that starts its id (without remote_) or its participant
      id, as the first run shows them.
    - Every number next to day or days is DAYS, and every one next to ship(s), pairing(s) or machine(s) is the count;
      each a whole number, thousands commas allowed, never signed ("-1 ships"), a range ("1-2 ships", "1 to 2 ships")
      or a fraction ("1/2 ships", "1.5 ships") (the re-check's S5). A dash after an id is punctuation ("yes 64cd8098 -
      1 ship"), and so is a period before a space ("count 1. ship it"). The words one to ten before a counted noun are
      that number ("one ship"); days, and a count past ten, are refused unless written in digits.
    - The count appears so, or, when no such noun has a number, as the words' only bare number (the days' numbers, and
      an id naming the contact, apart).
    The refusals name what is missing or wrong, never the words."""
    folded = unicodedata.normalize('NFKC', words).lower()
    ids = (contact['id'].removeprefix('remote_').lower(), contact['user_id'].lower())
    naming = {token for token in re.findall(r'[0-9a-z]+', folded)
              if len(token) >= 8 and any(i.startswith(token) for i in ids)}
    if not naming:
        raise Problem(400, WORDS_NO_CONTACT.format(short=contact['id'].removeprefix('remote_')[:8]))
    counted, taken = [], []
    for match in NUMBERED.finditer(folded):
        number, noun, before = match.group(1), match.group(2), folded[:match.start()]
        ranged = RANGE_BEFORE.search(before)
        if (not WHOLE.fullmatch(number) or SIGN_BEFORE.search(before)
                or (ranged and ranged.group(1) not in naming)):
            raise Problem(400, WORDS_NUMBER_SHAPE)
        value = int(number.replace(',', ''))
        if noun in COUNT_NOUNS:
            if value != expect:
                raise Problem(400, WORDS_COUNT_DIFFER.format(n=expect))
            counted.append(value)
        elif value != days:
            raise Problem(400, WORDS_DAYS_DIFFER.format(days=days))
        taken.append(match.span(1))
    for match in WORDED.finditer(folded):
        phrase, noun = match.group(1), match.group(2)
        if noun not in COUNT_NOUNS:
            raise Problem(400, WORDS_DAYS_IN_DIGITS.format(days=days))
        if phrase not in ONE_TO_TEN:
            raise Problem(400, WORDS_COUNT_IN_DIGITS.format(n=expect, s='' if expect == 1 else 's'))
        if ONE_TO_TEN[phrase] != expect:
            raise Problem(400, WORDS_COUNT_DIFFER.format(n=expect))
        counted.append(ONE_TO_TEN[phrase])
    if counted:
        return
    bare = [int(m.group(1).replace(',', '')) for m in BARE.finditer(folded)
            if m.span(1) not in taken and m.group(1) not in naming]
    if bare != [expect]:
        raise Problem(400, WORDS_NO_COUNT.format(n=expect, s='' if expect == 1 else 's'))


def latest_trust_row(db, peer_id, owner_user_id):
    """The seq of the latest owner_trust row (a grant, a renewal or a revocation) of this owner (peer, participant id),
    or None: what the terminal's confirm code binds, and its grant checks again (spec revision 6)."""
    return db.execute('SELECT MAX(seq) FROM owner_trust WHERE peer_id=? AND owner_user_id=?',
                      (peer_id, owner_user_id)).fetchone()[0]


def contact_prefix(value):
    """A remote contact's short id as an operator typed it, for station-lessons-add and station-trust-grant alike:
    short_id's form (at least 4 characters, lower-cased). A value shaped like a pairing code is refused unread."""
    from .lessons import ADD_CODE_SHAPED
    prefix = short_id(value)
    if typed_code(prefix) is not None:
        raise Problem(400, ADD_CODE_SHAPED)
    return prefix


def named_contact(db, prefix):
    """The one remote contact a short id (contact_prefix) names: the start of its id, with or without remote_, or of
    its participant id, which the listings show in parentheses. No refusal echoes what was typed."""
    from .lessons import ADD_AMBIGUOUS, ADD_NOT_REMOTE
    matches = [r['id'] for r in db.execute('SELECT id, user_id FROM remote_contacts ORDER BY id')
               if r['id'].startswith(prefix) or r['id'].removeprefix('remote_').startswith(prefix)
               or r['user_id'].lower().startswith(prefix)]
    if len(matches) > 1:
        raise Problem(400, ADD_AMBIGUOUS)
    if not matches:
        raise Problem(404, ADD_NOT_REMOTE)
    return matches[0]


def trust_window(db, grant_id):
    """`(window_seq, expect, paired)` of the grant's latest grant-or-renewal row: that row's seq, the count its person
    expected, and the trust_confirmations rows that paired under it (spec item 4a). The trust is paused when
    paired >= expect."""
    row = db.execute("SELECT seq, expect FROM owner_trust WHERE grant_id=? AND event IN ('grant','renew') "
                     'ORDER BY seq DESC LIMIT 1', (grant_id,)).fetchone()
    if row is None:
        raise Problem(404, 'No such owner trust')
    paired = db.execute('SELECT COUNT(*) FROM trust_confirmations WHERE window_seq=?', (row['seq'],)).fetchone()[0]
    return row['seq'], row['expect'], paired


def _unchanged_since(db, grant_id, seen):
    """Refuses (409) when the grant's window or its paired count is not what the renewal page showed. Run before the
    password and again in the writing transaction, so a ship paired in between can't close its window unseen."""
    if db.execute('SELECT 1 FROM owner_trust WHERE grant_id=?', (grant_id,)).fetchone() and \
            trust_window(db, grant_id)[::2] != seen:
        raise Problem(409, 'the trust paired more ships since you looked; read the page again')


def grant_line(name, peer_id, until):
    """The grant's words (spec item 2, GRANT_TEXT) for an owner's name, its peer and an `until` (UTC date), as the
    station stores them and the page shows them: `before`, `name` (through safe_line, so no control or bidi character
    and no '@' survives), `after`, the whole `text` and `until`. The page puts `name` in <bdi> between the other two, so
    what the admin reads before the password is exactly `text` (Task 7's review)."""
    before, _, rest = GRANT_TEXT.partition('{name}')
    name, after = safe_line(name), rest.format(peer=peer_id[:12], date=utc_day(until))
    return {'before': before, 'name': name, 'after': after, 'text': before + name + after, 'until': until}


def _text(name, peer_id, until):
    return grant_line(name, peer_id, until)['text']


def _as_shown(text, shown):
    """Refuses (409) when the line the page showed the admin (`shown`) is not the text this grant or renewal would
    store: a new UTC day since the page read it, or the owner renamed (Task 7's review). Run before the password and
    again in the writing transaction, as _unchanged_since is. None, a caller with no page, checks nothing."""
    if shown is not None and shown != text:
        raise Problem(409, 'the grant reads differently now; read it again')


def _owner_contact(db, grant_id):
    """The labelled contact of a trust's owner, by (peer, participant id), or None."""
    grant = db.execute("SELECT peer_id, owner_user_id FROM owner_trust WHERE grant_id=? AND event='grant'",
                       (grant_id,)).fetchone()
    return grant and db.execute(f'{LABELLED_CONTACT} WHERE c.peer_id=? AND c.user_id=?',
                                (grant['peer_id'], grant['owner_user_id'])).fetchone()


def owner_eligible(db, contact):
    """The refusals grant and renew share: the owner is a remote person contact, not held, not made by a trust, whose
    typed code is still current."""
    if contact is None:
        raise Problem(404, 'No such contact')
    if db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (contact['id'],)).fetchone():
        raise Problem(409, 'That contact is held')
    if db.execute('SELECT 1 FROM trust_confirmations WHERE contact_id=?', (contact['id'],)).fetchone():
        raise Problem(409, 'That contact was paired by an owner trust, not by a typed code')
    if not code_current(db, contact['id']):
        raise Problem(409, 'A code typed for that contact is needed first')


def utc_day(at):
    """A time's UTC date, as trust_confirmations.day and the cap count it."""
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d')


def owner_label(db, peer_id, owner_user_id):
    """A trust's owner as every display names it: the label of its contact, found by the pair (peer, participant id),
    never an id alone."""
    row = db.execute(f'{LABELLED_CONTACT} WHERE c.peer_id=? AND c.user_id=?', (peer_id, owner_user_id)).fetchone()
    return row['label'] if row else 'an unknown owner'


def contact_line(db, contact_id, limit):
    """A remote contact's label as one safe line of about `limit` characters, or None for no such contact. A ship an
    owner trust paired keeps its whole name after its shortened owner (ship_label_line), its name taken after the
    label's last ': ', since a ship's name (SHIP_NAME) holds no colon; any other contact is safe_line(label, limit)."""
    row = db.execute('SELECT label, EXISTS(SELECT 1 FROM trust_confirmations WHERE contact_id=contact_labels.id) AS ship '
                     'FROM contact_labels WHERE id=?', (contact_id,)).fetchone()
    if row is None:
        return None
    if not row['ship']:
        return safe_line(row['label'], limit)
    return ship_label_line(row['label'], row['label'].rpartition(': ')[2], limit)


def trust_state(db, grant_id, now):
    """One grant as trust_list, connections() and the renewal page say it: its latest `until`, its first revocation
    (time, reason, person) or None, its current window (trust_window) and its state: 'revoked', else 'expired' once
    `until` is past, else 'paused' when the window is full, else 'live'. Only a damaged file holds a NULL `until` or a
    window with no count; each fails closed, as expired and as paused."""
    until = db.execute("SELECT MAX(until) FROM owner_trust WHERE grant_id=? AND event IN ('grant','renew')",
                       (grant_id,)).fetchone()[0]
    revoke = db.execute("SELECT owner_trust.at, owner_trust.reason, users.username FROM owner_trust LEFT JOIN users ON "
                        "users.id=owner_trust.by_id WHERE grant_id=? AND event='revoke' ORDER BY seq LIMIT 1",
                        (grant_id,)).fetchone()
    window_seq, expect, paired = trust_window(db, grant_id)
    state = ('revoked' if revoke else 'expired' if until is None or until <= now
             else 'paused' if expect is None or paired >= expect else 'live')
    return {'until': until, 'revoke': revoke, 'window_seq': window_seq, 'expect': expect, 'paired': paired, 'state': state}


def contact_trust(db, peer_id, user_id, now):
    """connections()' `owner_trust` for a contact whose code was typed: its unrevoked, unexpired trust, else its latest
    grant, as {'grant_id', 'until', 'live', 'state', 'window_seq', 'expect', 'paired', 'line'} (trust_state); None when no
    trust was ever granted for it. `live` is whether it pairs now, so a paused trust is not live (Task 6's review).
    `line` is the trust's grant line (grant_line) for its `until`, which the page shows; None when `until` is."""
    live = live_trust(db, peer_id, user_id, now)
    row = live or db.execute("SELECT grant_id FROM owner_trust WHERE peer_id=? AND owner_user_id=? AND event='grant' "
                             'ORDER BY seq DESC LIMIT 1', (peer_id, user_id)).fetchone()
    if row is None:
        return None
    known = trust_state(db, row['grant_id'], now)
    line = None if known['until'] is None else grant_line(owner_label(db, peer_id, user_id), peer_id, known['until'])
    return {'grant_id': row['grant_id'], 'until': known['until'], 'live': known['state'] == 'live',
            'state': known['state'], 'window_seq': known['window_seq'], 'expect': known['expect'], 'paired': known['paired'],
            'line': line}


def trust_renewal(db, grant_id, now):
    """The renewal page (spec item 4a): the grant with its owner by label, its state and its current window, and the
    ships paired in that window, each by label with the acting ship, when, and whether it's held, before the page asks
    for the password. The page sends back (window_seq, paired) as `seen`, so it renews only what it showed. Labels are
    plain here (plain_name: no bidi control can reorder them), and the page escapes them."""
    grant = db.execute("SELECT peer_id, owner_user_id FROM owner_trust WHERE grant_id=? AND event='grant'",
                       (grant_id,)).fetchone()
    if grant is None:
        raise Problem(404, 'No such owner trust')
    known = trust_state(db, grant_id, now)
    ships = [{'contact_id': r['contact_id'], 'label': plain_name(r['label']), 'acting_ship': r['acting'], 'confirmed': r['confirmed'],
              'held': bool(r['held'])} for r in db.execute(
        'SELECT t.contact_id, t.confirmed, COALESCE(l.label, ?) AS label, '
        'COALESCE(users.username, substr(t.acting_ship_id, 1, 6)) AS acting, '
        'EXISTS(SELECT 1 FROM contact_holds WHERE contact_id=t.contact_id) AS held FROM trust_confirmations t '
        'LEFT JOIN contact_labels l ON l.id=t.contact_id LEFT JOIN users ON users.id=t.acting_ship_id '
        'WHERE t.window_seq=? ORDER BY t.confirmed, t.rowid', ('a contact no longer here', known['window_seq']))]
    return {'grant_id': grant_id, 'owner': plain_name(owner_label(db, grant['peer_id'], grant['owner_user_id'])),
            'peer_id': grant['peer_id'], 'until': known['until'], 'state': known['state'],
            'window_seq': known['window_seq'], 'expect': known['expect'], 'paired': known['paired'], 'ships': ships}


def trust_digests(db, now):
    """Spec item 5, the record (the pause notice is the alarm): one Ops line per owner trust per UTC day, for each of
    the DIGEST_DAYS days before today that had a pairing or a refusal at the cap, in day order. Ruling on N12: a day is
    listed only once it ended DIGEST_SETTLE seconds ago, so its count never changes under its id, which Odo announces
    once (agent watch.py, `_announce`). Every name goes through safe_line. A pure read: station_notices runs off the
    gate."""
    settled = now - DIGEST_SETTLE  # "today" is the day this time falls in, so a day lists DIGEST_SETTLE after it ends
    days = [utc_day(settled - back * 86400) for back in range(DIGEST_DAYS, 0, -1)]
    marks = ','.join('?' * len(days))
    listed = []
    for grant in db.execute("SELECT grant_id, peer_id, owner_user_id FROM owner_trust WHERE event='grant' ORDER BY seq").fetchall():
        grant_id = grant['grant_id']
        paired = dict(db.execute(f'SELECT day, COUNT(*) FROM trust_confirmations WHERE grant_id=? AND day IN ({marks}) '
                                 'GROUP BY day', (grant_id, *days)).fetchall())
        refused = dict(db.execute(f'SELECT day, refused FROM trust_cap_refusals WHERE grant_id=? AND day IN ({marks})',
                                  (grant_id, *days)).fetchall())
        for day in sorted(set(paired) | set(refused)):
            ships = [safe_line(row[0]) for row in db.execute(
                'SELECT DISTINCT COALESCE(users.username, substr(t.acting_ship_id, 1, 6)) AS ship FROM trust_confirmations t '
                'LEFT JOIN users ON users.id=t.acting_ship_id WHERE t.grant_id=? AND t.day=? ORDER BY ship', (grant_id, day))]
            text = DIGEST_TEXT.format(
                day=day, n=paired.get(day, 0), owner=safe_line(owner_label(db, grant['peer_id'], grant['owner_user_id'])),
                peer=grant['peer_id'][:12], ships=', '.join(ships) or 'no ship',
                refused=f'; {refused[day]} refused at the cap of {TRUST_CAP}' if refused.get(day) else '')
            listed.append((day, {'id': f'trust-digest-{grant_id[:12]}-{day}', 'text': text}))
    return [notice for _, notice in sorted(listed, key=lambda item: item[0])]  # stable: grant order within a day


def trust_pauses(db, waiting=None):
    """Spec item 4a, the alarm: one Ops notice for each unrevoked trust whose current window is full, so it posts at
    Odo's next cycle after the nth pairing. Its id names the grant and its window's row, so each window posts once and
    a renewal's window, paused in turn, posts again; Task 5's restore raises the sequence, so no id comes back. An
    expired trust still alarms (its pairings happened while it was live); a revoked one is the admin's answer already.
    A window with no count, which only a damaged file holds, reads as paused (fail closed, as Task 5's restore reads
    it). Names go through safe_line. A pure read. `waiting(grant_id)`, when given, counts the grant's ships that wait for
    the lessons room only for this pause (lessons.waiting_for_lessons); a count above 0 adds PAUSE_WAITING to the text."""
    notices = []
    for grant in db.execute("SELECT grant_id, peer_id, owner_user_id FROM owner_trust WHERE event='grant' "
                            f'AND grant_id NOT IN ({REVOKED}) ORDER BY seq').fetchall():
        window_seq, expect, paired = trust_window(db, grant['grant_id'])
        if expect is None or paired >= expect:
            text = PAUSE_TEXT.format(owner=safe_line(owner_label(db, grant['peer_id'], grant['owner_user_id'])),
                                     peer=grant['peer_id'][:12], n=paired if expect is None else expect)
            waits = waiting(grant['grant_id']) if waiting else 0
            notices.append({'id': f'trust-paused-{grant["grant_id"][:12]}-{window_seq}',
                            'text': text + (PAUSE_WAITING_ONE if waits == 1 else PAUSE_WAITING.format(k=waits) if waits else '')})
    return notices


def trust_terminal_notices(db):
    """Spec revision 6, what makes a grant with no password seen: one Ops notice for each owner trust granted at the
    Pi's terminal, with its short id, the grant line the admin said yes to and their words, as the grant row keeps
    them, so a later rename of the owner never changes it. Its id names the grant, so Odo posts it once, at its next
    cycle; it lists for as long as the row stands, as lessons_notices' do. Every value through plain_name, then
    safe_line, so no '@' or control character reaches the room; the words come last, whole, as posted_words gives them
    (the grant checked that form and its NFKC form for a code and a live key). A pure read."""
    notices = []
    for row in db.execute('SELECT g.grant_id, g.expect, g.line, g.words, u.name FROM owner_trust g LEFT JOIN users u '
                          "ON u.id=g.by_id WHERE g.event='grant' AND g.words IS NOT NULL ORDER BY g.seq").fetchall():
        who = safe_line(plain_name(row['name'] or 'the admin'), 40)
        notices.append({'id': f'trust-terminal-{row["grant_id"][:12]}', 'text': TERMINAL_TEXT.format(
            short=row['grant_id'][:6], who=who, line=safe_line(plain_name(row['line']), 400), n=row['expect'],
            s='' if row['expect'] == 1 else 's', words=posted_words(row['words']))})
    return notices


def _signed_name(assertion):
    """The ship's name in a stored assertion (canonical JSON), or None when the row holds none."""
    try:
        name = json.loads(assertion)['record']['ship_name']
    except (ValueError, KeyError, TypeError):
        return None
    return name if isinstance(name, str) else None


def trust_list(db, now):
    """`station-trust-list` (spec item 5: the digest's full ids): every owner trust in grant order, with its owner by
    label, its `until`, its state ('live', 'paused', 'expired' or 'revoked', with the revocation's time, reason and
    person), its current window, and each ship it paired: the label, the signed name, the full participant id, the
    acting ship, when, whether it's held and its window. `at_terminal` is the granting admin's username for a grant made
    on their yes at the Pi's terminal (spec revision 6), else None. Names are raw here; the CLI makes each line safe."""
    trusts = []
    for grant in db.execute("SELECT g.grant_id, g.peer_id, g.owner_user_id, CASE WHEN g.words IS NULL THEN NULL ELSE "
                            "COALESCE(u.username, 'an admin no longer here') END AS at_terminal FROM owner_trust g "
                            "LEFT JOIN users u ON u.id=g.by_id WHERE g.event='grant' ORDER BY g.seq").fetchall():
        grant_id = grant['grant_id']
        known = trust_state(db, grant_id, now)
        until, revoke, state = known['until'], known['revoke'], known['state']
        window_seq, expect, paired = known['window_seq'], known['expect'], known['paired']
        ships = [{'contact_id': r['contact_id'], 'label': plain_name(r['label']), 'ship_name': _signed_name(r['assertion']),
                  'participant_id': r['user_id'], 'acting_ship': r['acting'], 'confirmed': r['confirmed'],
                  'held': bool(r['held']), 'window_seq': r['window_seq']}
                 for r in db.execute(
                     'SELECT t.contact_id, t.assertion, t.confirmed, t.window_seq, c.user_id, '
                     '(SELECT label FROM contact_labels WHERE id=t.contact_id) AS label, '
                     'COALESCE(users.username, substr(t.acting_ship_id, 1, 6)) AS acting, '
                     'EXISTS(SELECT 1 FROM contact_holds WHERE contact_id=t.contact_id) AS held '
                     'FROM trust_confirmations t LEFT JOIN remote_contacts c ON c.id=t.contact_id '
                     'LEFT JOIN users ON users.id=t.acting_ship_id WHERE t.grant_id=? ORDER BY t.confirmed, t.rowid',
                     (grant_id,))]
        trusts.append({'grant_id': grant_id, 'peer_id': grant['peer_id'], 'owner_user_id': grant['owner_user_id'],
                       'owner': plain_name(owner_label(db, grant['peer_id'], grant['owner_user_id'])), 'until': until, 'state': state,
                       'revoked_at': revoke['at'] if revoke else None, 'reason': revoke['reason'] if revoke else None,
                       'revoked_by': revoke['username'] if revoke else None, 'window_seq': window_seq, 'expect': expect,
                       'paired': paired, 'ships': ships, 'at_terminal': grant['at_terminal']})
    return trusts


class OwnerTrust:
    def _trust_password(self, actor, password, source, public, device):
        with self.transaction() as db:
            self._admin(db, actor)
            username = db.execute('SELECT username FROM users WHERE id=?', (actor,)).fetchone()['username']
        if not self.check_password_attempt(username, password, source, public=public, device=device):
            raise Problem(401, 'Invalid password')

    def owner_trust_line(self, actor, contact_id, days):
        """The grant line the page shows before the password (grant_line): what a grant, or a renewal, for this owner
        contact would store if made now for `days` days, by this station's clock, never the browser's."""
        _days(days)
        with self.transaction() as db:
            self._admin(db, actor)
            contact = db.execute(f'{LABELLED_CONTACT} WHERE c.id=?', (contact_id,)).fetchone()
            if contact is None:
                raise Problem(404, 'No such contact')
            return grant_line(contact['label'], contact['peer_id'], self.clock() + days * 86400)

    def grant_owner_trust(self, actor, contact_id, *, days, expect, password, source, public=True, device=None,
                          shown=None):
        """The admin's act, with their password: a remote person contact, whose code was typed and is still current,
        may have their ships paired by this station's ships for `days` whole days, up to `expect` of them before the
        trust pauses (spec item 4a). `shown` is the grant line the page showed (_as_shown)."""
        _days(days)
        _expect(expect)
        if shown is not None:
            with self.transaction() as db:  # before the password, so a stale line spends no attempt
                self._admin(db, actor)
                contact = db.execute(f'{LABELLED_CONTACT} WHERE c.id=?', (contact_id,)).fetchone()
                if contact is not None:  # an unknown one is refused below, as before
                    _as_shown(_text(contact['label'], contact['peer_id'], self.clock() + days * 86400), shown)
        self._trust_password(actor, password, source, public, device)
        with self.transaction() as db:  # _as_shown again: the day may have turned while the password was checked
            return self._grant_in(db, actor, contact_id, days, expect, shown)

    def _grant_in(self, db, actor, contact_id, days, expect, shown, words=None, latest=None):
        """A grant's own checks and its 'grant' row, in the caller's writing transaction, for the browser and the terminal
        alike: the admin; an owner contact owner_eligible takes; no live trust for that owner (peer, participant id); and
        the line this grant stores, by this station's clock, as `shown` (_as_shown). At the terminal (`words` given) the
        owner's latest owner_trust row is still `latest`, the one the first run's code was bound to (the re-check's
        N9), and `words`, the admin's yes, names this contact and the count, its numbers as the grant's
        (_names_the_grant); they are kept with the line (TERMINAL_COLUMNS). A browser grant keeps neither. This is the
        terminal path's only admin check: keep it here."""
        self._admin(db, actor)
        now = self.clock()
        contact = db.execute(f'{LABELLED_CONTACT} WHERE c.id=?', (contact_id,)).fetchone()
        owner_eligible(db, contact)
        if live_trust(db, contact['peer_id'], contact['user_id'], now):
            raise Problem(409, 'That owner is already trusted; renew it')
        if words is not None and latest_trust_row(db, contact['peer_id'], contact['user_id']) != latest:
            raise Problem(409, WORDS_TRUSTS_CHANGED)
        grant_id, until = uid(), now + days * 86400
        text = _text(contact['label'], contact['peer_id'], until)
        _as_shown(text, shown)
        if words is not None:
            _names_the_grant(words, contact, days, expect)
        db.execute('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect,line,words) '
                   "VALUES (?,'grant',?,?,?,?,?,?,?,?)", (grant_id, contact['peer_id'], contact['user_id'], until, actor,
                                                         now, expect, None if words is None else text, words))
        return {'grant_id': grant_id, 'until': until, 'text': text}

    def grant_owner_trust_at_terminal(self, actor, contact_id, *, days, expect, shown, words, latest):
        """Spec revision 6: the admin's act on their yes at the Pi's terminal, with no password. The browser's grant
        (_grant_in: the same checks, the same 'grant' row and the same line), except that `shown`, the grant line the
        terminal showed before the yes, is required, and `words`, the yes as typed (_words), which names the contact and
        the count (_names_the_grant), is kept with that line for the Ops notice (trust_terminal_notices). `latest` is the
        owner's latest owner_trust seq the first run read (None for none), compared again in this transaction. Words
        holding a pairing code's shape (_refuse_codes) or a live ship key in any of their forms (word_forms) are
        refused, since the notice would post them. No password is asked for, read or taken. station_trust_grant is its
        one caller outside the tests."""
        _days(days)
        _expect(expect)
        if not isinstance(shown, str) or not shown:
            raise Problem(400, 'shown is the grant line the terminal showed before the yes')
        if latest is not None and type(latest) is not int:
            raise Problem(400, "latest is the owner's latest owner_trust seq the first run read, or None")
        _words(words)
        with self.transaction() as db:
            _refuse_codes(db, words)
            if any(self._live_ship_key_in(db, form) for form in word_forms(words)):
                raise Problem(400, WORDS_KEY)
            return self._grant_in(db, actor, contact_id, days, expect, shown, words, latest)

    def owner_trust_at_terminal(self, username, contact, *, days, expect):
        """`station-trust-grant`'s first run (spec revision 6): the owner contact named by its short id (contact_prefix,
        named_contact), the grant line a grant for `days` days would store if made now (grant_line, as the browser's
        preview reads it), and a confirm code: 8 hex of a SHA-256 over the admin, the contact, its label, peer and
        participant, the line, the days, the count and the latest owner_trust row of that owner (peer, participant id),
        as station-lessons-room builds its own. Any change to one of them, a new UTC day in the line included, changes
        the code, so a code shown before any grant, renewal or revocation of that owner is stale, and one code grants at
        most once. It refuses what the grant would (an admin by username, an owner owner_eligible takes, no live
        trust) and grants nothing."""
        _days(days)
        _expect(expect)
        prefix = contact_prefix(contact)
        with self.transaction() as db:
            actor = self._operator(db, username)
            self._admin(db, actor)
            found = db.execute(f'{LABELLED_CONTACT} WHERE c.id=?', (named_contact(db, prefix),)).fetchone()
            owner_eligible(db, found)
            now = self.clock()
            if live_trust(db, found['peer_id'], found['user_id'], now):
                raise Problem(409, 'That owner is already trusted; renew it in the browser')
            line = grant_line(found['label'], found['peer_id'], now + days * 86400)
            latest = latest_trust_row(db, found['peer_id'], found['user_id'])
        code = hashlib.sha256(encode({'act': 'owner-trust-grant', 'actor': actor, 'contact': found['id'],
                                      'label': found['label'], 'peer': found['peer_id'], 'owner': found['user_id'],
                                      'line': line['text'], 'days': days, 'expect': expect,
                                      'latest': latest}).encode()).hexdigest()[:8]
        return {'actor': actor, 'admin': username, 'contact_id': found['id'],
                'contact_short': found['id'].removeprefix('remote_')[:8], 'user_short': found['user_id'][:8],
                'label': found['label'], 'peer_id': found['peer_id'], 'line': line, 'days': days, 'expect': expect,
                'latest': latest, 'confirm': code, 'granted': False}

    def station_trust_grant(self, username, contact, *, days, expect, confirm=None, words=None):
        """`make station-trust-grant` (spec revision 6). Without `confirm`, the first run: owner_trust_at_terminal's
        view, and nothing granted; words then are refused, since they are the yes to the line this run shows. With
        `confirm` equal to the code the view has now, so the contact, its line, the days, the count and that owner's
        trusts read as the first run showed them, the grant: grant_owner_trust_at_terminal with that line as `shown`,
        re-checked in the grant's own transaction, and the words. Returns the view, with the grant's id, until and text
        once granted."""
        view = self.owner_trust_at_terminal(username, contact, days=days, expect=expect)
        if confirm is None:
            if words is not None:
                raise Problem(400, WORDS_FIRST)
            return view
        if not isinstance(confirm, str) or confirm.strip().lower() != view['confirm']:
            raise Problem(409, TERMINAL_CHANGED)
        done = self.grant_owner_trust_at_terminal(view['actor'], view['contact_id'], days=days, expect=expect,
                                                  shown=view['line']['text'], words=words, latest=view['latest'])
        return {**view, **done, 'granted': True}

    def renew_owner_trust(self, actor, grant_id, *, days, expect, seen, password, source, public=True, device=None,
                          shown=None):
        """Extends an unrevoked trust to `days` whole days from now; it never shortens one. `seen` is the window the
        renewal page showed (_unchanged_since) and `shown` its grant line (_as_shown)."""
        _days(days)
        _expect(expect)
        if not (type(seen) is tuple and len(seen) == 2 and all(type(n) is int for n in seen)):
            raise Problem(400, 'seen is the (window_seq, paired) the renewal page showed')
        with self.transaction() as db:  # before the password, so a stale page spends no attempt
            self._admin(db, actor)
            _unchanged_since(db, grant_id, seen)
            known = _owner_contact(db, grant_id)
            if known is not None:  # an unknown trust or owner is refused below, as before
                _as_shown(_text(known['label'], known['peer_id'], self.clock() + days * 86400), shown)
        self._trust_password(actor, password, source, public, device)
        with self.transaction() as db:
            self._admin(db, actor)
            _unchanged_since(db, grant_id, seen)  # again: a ship may have paired while the password was checked
            now = self.clock()
            rows = db.execute('SELECT event,peer_id,owner_user_id,until FROM owner_trust WHERE grant_id=?', (grant_id,)).fetchall()
            if not rows:
                raise Problem(404, 'No such owner trust')
            if any(r['event'] == 'revoke' for r in rows):
                raise Problem(409, 'That owner trust was revoked')
            peer_id, owner = rows[0]['peer_id'], rows[0]['owner_user_id']
            contact = db.execute(f'{LABELLED_CONTACT} WHERE c.peer_id=? AND c.user_id=?', (peer_id, owner)).fetchone()
            owner_eligible(db, contact)
            latest = db.execute("SELECT grant_id FROM owner_trust WHERE peer_id=? AND owner_user_id=? AND event='grant' "
                                'ORDER BY seq DESC LIMIT 1', (peer_id, owner)).fetchone()
            if latest['grant_id'] != grant_id:
                raise Problem(409, "That is not this owner's latest trust; grant a new one")
            live = live_trust(db, peer_id, owner, now)
            if live and live['grant_id'] != grant_id:
                raise Problem(409, 'That owner is already trusted under another grant')
            current = max(r['until'] for r in rows)
            until = now + days * 86400
            if until <= current:
                raise Problem(409, 'That owner trust already runs longer')
            text = _text(contact['label'], peer_id, until)
            _as_shown(text, shown)
            db.execute('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect) '
                       "VALUES (?,'renew',?,?,?,?,?,?)", (grant_id, peer_id, owner, until, actor, now, expect))
        return {'grant_id': grant_id, 'until': until, 'text': text}

    def owner_trust_renewal(self, actor, grant_id):
        """The admin's renewal page for one trust (trust_renewal): what a renewal would renew, read before the
        password is asked for."""
        with self.transaction() as db:
            self._admin(db, actor)
            return trust_renewal(db, grant_id, self.clock())

    def revoke_owner_trust(self, actor, grant_id):
        """The admin's act (spec "The change" item 6): ends the trust at once, so this grant, expired or not, and every
        other unrevoked grant of the same owner (peer, participant id), whose ships would otherwise stay paired (review
        ruling). It holds every ship whose latest confirmation one of them made and that has no current typed code of
        its own (ships_to_hold), as settle_owner_trust holds them; `held` counts them. It only takes power away, so it
        needs no password. A grant revoked already is refused, so it never gains a second revocation."""
        with self.transaction() as db:
            self._admin(db, actor)
            now = self.clock()
            rows = db.execute('SELECT event, peer_id, owner_user_id FROM owner_trust WHERE grant_id=? ORDER BY seq',
                              (grant_id,)).fetchall()
            if not rows:
                raise Problem(404, 'No such owner trust')
            if any(r['event'] == 'revoke' for r in rows):
                raise Problem(409, 'That owner trust was revoked already')
            peer_id, owner = rows[0]['peer_id'], rows[0]['owner_user_id']
            grants = [r[0] for r in db.execute("SELECT grant_id FROM owner_trust WHERE peer_id=? AND owner_user_id=? "
                                               f"AND event='grant' AND grant_id NOT IN ({REVOKED}) ORDER BY seq",
                                               (peer_id, owner))]
            ships = ships_to_hold(db, grants)
            epochs = self._chain_epochs(db)
            db.executemany("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,reason) "
                           "VALUES (?,'revoke',?,?,NULL,?,?,'revoked')", [(g, peer_id, owner, actor, now) for g in grants])
            settle_owner_trust(db, now)
            self._emit_held(db, epochs)  # the ships it held left the lessons room: their peers get the roster
        return {'grant_id': grant_id, 'held': len(ships)}
