"""`make join-machine-plan PEER=<full peer id>`: every step of bringing another machine's peer into this station's
lessons room, each checked against this station's own records and marked done or left, with who does it and where.
The person's steps print together, so they are one sitting (Tardis's lesson, 2026-11-02: "Andy had about six sittings
today where one would have done"). It reads the store read-only and changes nothing; steps on the other machine can't
be seen from here and say so."""
import sqlite3
import subprocess
from pathlib import Path

PERSON, SHIP, HERE, THERE = 'Andy', 'a ship', 'this station', 'that machine'


def _read(data_dir):
    return sqlite3.connect(f'file:{Path(data_dir).resolve() / "peer.sqlite3"}?mode=ro', uri=True)


def _current_room(db):
    """The lessons room's current room: the recorded one, followed forward along linked_room_id."""
    row = db.execute('SELECT room_key FROM lessons_room WHERE id=1').fetchone()
    room = row[0] if row else None
    while room:
        newer = db.execute('SELECT id FROM rooms WHERE linked_room_id=?', (room,)).fetchone()
        if not newer:
            return room
        room = newer[0]
    return None


def _quiet(run, argv):
    try:
        return run(argv, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def plan(data_dir, peer, run=subprocess.run):
    """[(state, who, where, step, how)] in order; state is 'done', 'left' or 'check there'."""
    db = _read(data_dir)
    try:
        paired = db.execute('SELECT paired FROM peers WHERE peer_id=?', (peer,)).fetchone()
        contacts = db.execute(
            'SELECT c.id, c.name, (h.contact_id IS NOT NULL), (p.code IS NOT NULL) FROM remote_contacts c '
            'LEFT JOIN contact_holds h ON h.contact_id=c.id LEFT JOIN pairing_confirmations p ON p.contact_id=c.id '
            'WHERE c.peer_id=? ORDER BY c.name', (peer,)).fetchall()
        listed = db.execute('SELECT 1 FROM lessons_peers WHERE peer_id=?', (peer,)).fetchone() is not None
        room = _current_room(db)
        members = {r[0] for r in db.execute('SELECT contact_id FROM remote_room_members WHERE room_id=?', (room,))} if room else set()
    finally:
        db.close()
    listening = _quiet(run, ['systemctl', '--user', 'is-active', 'superyak-federation-listen.service']).strip() == 'active'
    served = ':7437' in _quiet(run, ['tailscale', 'serve', 'status'])
    live = [c for c in contacts if not c[2] and c[3]]
    steps = [
        ('done' if paired and paired[0] else 'left', PERSON, f'{THERE}, then {HERE}', "the peer's card paired here",
         '`card --pull` on that machine shows its code; `pair --card <its card> --as andy` here, in an ordinary terminal'),
        ('check there', PERSON, f'{HERE}, then {THERE}', "this station's card paired there",
         "`card --endpoint …:7437` here shows its code; `pair` there; `connections --as andy` there says it's done"),
        ('done' if listening and served else 'left', PERSON, HERE, 'this station listens for peers',
         'make federation-units; enable superyak-federation-listen and superyak-federate; tailscale serve --tcp 7437 '
         '(the harness refuses these to a ship)'),
        ('done' if live else 'left', PERSON, f'{THERE}, then {HERE}', "each account there paired here, with its own code",
         'contacts here: ' + (', '.join(f'{c[1]} ({"held" if c[2] else "confirmed" if c[3] else "unconfirmed"})'
                                     for c in contacts) or 'none')),
        ('done' if listed else 'left', SHIP, HERE, 'the lessons room lists that peer',
         'Rio Grande: make station-lessons-room ID=<short id> PEERS="<every listed peer>", then CONFIRM='),
        ('done' if live and all(c[0] in members for c in live) else 'left', PERSON, HERE,
         "that peer's accounts are members of the lessons room",
         f'in the browser, add {", ".join(c[1] for c in live if c[0] not in members) or "them"} to the room '
         f'{(room or "?")[:6]}; that makes the chain\'s next room'),
        ('check there', SHIP, THERE, 'the room recorded there, the hook docked, the lessons laid',
         "that machine's ship: make lessons-room ID=<full id>, CONFIRM=; make dock … --lessons; lay its lessons"),
    ]
    return steps


def describe(steps, peer):
    lines = [f'Joining peer {peer[:12]} to the lessons room. From this station\'s records; nothing was changed.']
    for heading, keep in (("Left for Andy, in one sitting", lambda s: s[0] == 'left' and s[1] == PERSON),
                          ('Left for ships', lambda s: s[0] == 'left' and s[1] == SHIP),
                          ('To check on that machine', lambda s: s[0] == 'check there'),
                          ('Done', lambda s: s[0] == 'done')):
        chosen = [s for s in steps if keep(s)]
        if chosen:
            lines.append(f'{heading}:')
            lines += [f'  - {step} ({where}): {how}' for _, _, where, step, how in chosen]
    return '\n'.join(lines)
