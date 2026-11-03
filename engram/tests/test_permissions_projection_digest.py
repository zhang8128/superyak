"""The permission ledger's projection digest (docs/superpowers/plans/2026-11-03-projection-digest.md): each test names
its task and the decision it pins."""
import hashlib
import json
import os

import permission_ledger
from lighthouse_protocol import canonical_json
from permission_ledger import Ledger, ledger_path
from permissions import _COLUMNS


# ---------------------------------------------------------------- Task 0b: what this Python gives the key read

def test_0b_the_key_read_has_pread_and_cloexec_and_needs_no_sqlite_dbpage(tmp_path):
    """D4: the change counter and the journal bytes are read with `os.pread` on a descriptor opened `O_RDONLY |
    O_CLOEXEC`, never with `open()`. This runs wherever the suite runs (Tardis, the Pi, the Mac), so each machine's
    Engram Python says it has both. `sqlite_dbpage` is not relied on: it is missing from the Engram venv's SQLite on
    Tardis (3.53.1), though the system Python's 3.46.1 has it."""
    assert hasattr(os, "pread") and hasattr(os, "O_CLOEXEC")
    Ledger._blank(tmp_path, "ledger-0b").close()
    fd = os.open(ledger_path(tmp_path), os.O_RDONLY | os.O_CLOEXEC)
    try:
        header = os.pread(fd, 100, 0)
        assert header[:16] == b"SQLite format 3\x00"
        assert header[18:20] == b"\x01\x01"                # a rollback journal: the file format bytes D4 pins
        assert os.get_inheritable(fd) is False
    finally:
        os.close(fd)


# ---------------------------------------------------------------- Task 1: the row encoding and hash (D2)

# (table, values, the encoding D2 names, BLAKE2b-256 of that encoding computed apart from the code)
_KNOWN = [
    ("persons", ("person:andy", "place:home/andy", 1, -5, None),
     b"t7:persons" b"s11:person:andy" b"s15:place:home/andy" b"i1:1" b"i2:-5" b"n",
     "fe21add4b031afc4b8922942bc4ce2615471abee04d597cecdf3592a9dc2ad30"),
    ("places", ("place:x", 1, 2, None, b"\x00\xff"),
     b"t6:places" b"s7:place:x" b"i1:1" b"i1:2" b"n" b"b2:\x00\xff",
     "57f85e570d04881b3992e363915034d7395e50351b283e0cd9eb5e2f57a3cf70"),
    ("lane_notes", ("mem:S/episode/m1", "café", 1.5, 3),        # a REAL, and a length in UTF-8 bytes
     b"t10:lane_notes" b"s16:mem:S/episode/m1" b"s5:caf\xc3\xa9" b"r3:1.5" b"i1:3",
     "ec654e4944683f557abcc0ab58f280ec121e6f0248629a280b79be65175c4760"),
]


def test_1_known_rows_hash_to_fixed_values_with_every_tag_and_a_real():
    """D2: `t<len>:<table>`, then per value `n`, or `i`, `s`, `b` or `r` with a length in bytes and the bytes."""
    for table, values, encoded, digest in _KNOWN:
        assert permission_ledger._row_bytes(table, values) == encoded
        assert permission_ledger._row_hash(table, values) == int(digest, 16)
    # framing: a value can't run into the next one, nor the table name into the first value
    assert permission_ledger._row_hash("groups", ("ab", "c", 1)) != permission_ledger._row_hash("groups", ("a", "bc", 1))
    assert permission_ledger._row_hash("copies", ("1", "x", 1)) != permission_ledger._row_hash("copies", (1, "x", 1))


_MEMBERS = [("collection:andy/medical", f"mem:S/episode/m{i}", "person", i + 1, "person:andy", None, None)
            for i in range(6)]


def test_1_a_part_ignores_insert_order_and_a_row_taken_out_and_put_back():
    forward, backward = permission_ledger._new_parts(), permission_ledger._new_parts()
    for row in _MEMBERS:
        permission_ledger._fold(forward, "collection_members", row)
    for row in reversed(_MEMBERS):
        permission_ledger._fold(backward, "collection_members", row)
    assert forward == backward and forward["collection_members"][0] == len(_MEMBERS)
    assert permission_ledger._parts_digest(forward) == permission_ledger._parts_digest(backward)
    permission_ledger._fold(backward, "collection_members", _MEMBERS[2], -1)          # an update's subtraction
    assert backward != forward and backward["collection_members"][0] == len(_MEMBERS) - 1
    permission_ledger._fold(backward, "collection_members", _MEMBERS[2])
    assert backward == forward


def test_1_the_whole_is_blake2b_of_the_parts_canonical_json_in_a_fixed_order():
    parts = permission_ledger._new_parts()
    assert tuple(parts) == permission_ledger._PARTS == ("meta", *_COLUMNS) and len(parts) == 18
    for row in _MEMBERS:
        permission_ledger._fold(parts, "collection_members", row)
    text = permission_ledger._parts_text(parts)
    assert text == canonical_json({p: [n, f"{s:064x}"] for p, (n, s) in parts.items()})
    assert list(json.loads(text)) == sorted(permission_ledger._PARTS)
    assert permission_ledger._parts_digest(parts) == hashlib.blake2b(text.encode(), digest_size=32).hexdigest()
    assert permission_ledger._read_parts(text) == parts


def test_1_the_meta_part_excludes_head_and_the_projection_keys_and_covers_gate_admins_and_owner():
    kept = [("ledger_id", "l-1"), ("schema_version", "2"), ("owner", "person:andy"), ("admins", "person:andy"),
            ("gate", "shadow")]
    plain, with_followers = permission_ledger._new_parts(), permission_ledger._new_parts()
    for kv in kept:
        permission_ledger._fold(plain, "meta", kv)
    for kv in kept + [("head", "3:ab"), ("projection", "3:cd"), ("projection_parts", "{}")]:
        permission_ledger._fold(with_followers, "meta", kv)
    assert plain == with_followers and plain["meta"][0] == len(kept)
    for gone in ("gate", "admins", "owner"):
        other = permission_ledger._new_parts()
        for kv in kept:
            if kv[0] != gone:
                permission_ledger._fold(other, "meta", kv)
        assert other["meta"] != plain["meta"], gone

