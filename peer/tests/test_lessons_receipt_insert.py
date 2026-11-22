"""The receipt's insert names its columns, so a store a newer peer has given a seventh column (the receipt-place spec's
`place`, 2026-11-18-lesson-receipt-place.md, section 3) still takes this peer's receipts. Its fresh code reader's 5:
the named insert lands on main first, since it works with both schemas. Fails on main before it, with "table
lesson_receipts has 7 columns but 6 values were supplied"."""
import json

from superyak_peer import lessons
from conftest import lesson_body

HASHES = lesson_body(claim='Copy a hash from the output; never type one.', command=('git show',))


def test_a_receipt_is_written_to_a_store_with_a_column_this_peer_does_not_know(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c0', HASHES)
    store.lessons_index(None)
    with store.transaction() as db:   # once receipt-place lands the fresh schema has it; before, the newer peer adds it
        if 'place' not in {r['name'] for r in db.execute('PRAGMA table_info(lesson_receipts)')}:
            db.execute("ALTER TABLE lesson_receipts ADD COLUMN place TEXT CHECK(place IN ('superyak','other'))")
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'git show 1a2b', 'words_only': True}))
    answer = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0)[0]
    assert answer['lessons']
    with store.transaction() as db:
        assert [tuple(r) for r in db.execute('SELECT lesson_id IS NOT NULL, place FROM lesson_receipts')] == [(1, None)]
