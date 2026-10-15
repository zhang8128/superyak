"""Station signatures (spec A step 3, merge 3a; 2026-10-15-grants-step3-design.md G1-G6): the station's Ed25519
key signs each instructions revision, so a revision can be checked against the station's card. Merge 3b adds grants
and revocations here (G12)."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from .common import Problem, require
from .identity import PeerIdentity

SIGNATURE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(layer_id, revision));
'''
# G4b: the records a new identity would void, as (table, query). A table the database lacks (one from before merge 3a
# or 3b) holds none.
SIGNED_RECORDS = (('revision_signatures', 'SELECT 1 FROM revision_signatures LIMIT 1'),
                  # a grant's row holds an empty signature only inside the transaction that inserts and signs it, which
                  # mustn't count itself: the first grant on a new station creates the identity (G4)
                  ('grants', "SELECT 1 FROM grants WHERE signature!='' LIMIT 1"))
LOST_IDENTITY = ('The station identity {path} is missing, and this station holds signed records that a new identity would '
                 'void. Restore the file; if it is truly gone, run station-new-identity. Nothing was signed.')


def holds_signed_records(db):
    """G4b: whether the station holds any record SIGNED_RECORDS names."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return any(table in tables and db.execute(query).fetchone() is not None for table, query in SIGNED_RECORDS)


def refuse_a_lost_identity(data_dir, db):
    """G4b, the lost-identity check: identity.json missing (not a file, not a symlink) while the station holds signed
    records raises a ValueError naming the file."""
    path = Path(data_dir).absolute() / 'identity.json'
    if not path.exists() and not path.is_symlink() and holds_signed_records(db):
        raise ValueError(LOST_IDENTITY.format(path=path))


def refuse_a_lost_identity_before_the_store(data_dir):
    """G4b for `serve --peer-tls`, which checks before any Store opens: the database read-only, so nothing is created or
    migrated; a missing database holds no signed records. One that can't be read (say, a hot journal a read-only
    connection can't roll back) refuses with its name, since it can't rule signed records out."""
    database = Path(data_dir).absolute() / 'peer.sqlite3'
    if database.is_file():
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
                refuse_a_lost_identity(data_dir, db)
        except sqlite3.Error as error:
            raise ValueError(f'{database} could not be read read-only ({type(error).__name__}), so the station cannot tell '
                             'whether it holds signed records; it will not start until the database can be read') from error


class Signatures:
    def _load_station_identity(self):
        """G4: at a signing start, the identity file federation uses is loaded if it exists (a symlink too, which
        load_or_create refuses), and a store that can't load it doesn't start. A missing one waits for the first
        signature, so a new station's first `card --endpoint` still names its host (plan review M1), unless the station
        holds signed records: then it doesn't start either (G4b)."""
        path = self.data_dir / 'identity.json'
        if path.exists() or path.is_symlink():
            try:
                self._identity = PeerIdentity.load_or_create(self.data_dir)
            except Exception as error:
                raise ValueError(f'The station identity {path} could not be loaded ({type(error).__name__}); '
                                 'the station will not start until it is restored; if no copy exists, move the file aside and run '
                                 'station-new-identity') from error
        else:
            with self.transaction() as db:
                refuse_a_lost_identity(self.data_dir, db)  # G4b: a lost identity is not replaced silently

    def _station_identity(self, db=None):
        """The station's one identity loader (G4, G4a): loaded once, or created if missing, always inside a transaction
        that holds the dispatch gate, so two processes can't both create it and a failed create rolls the caller's
        signed write back. A caller inside a transaction passes its db: a second BEGIN IMMEDIATE on a new connection
        would wait out SQLite's timeout (the gate is reentrant; SQLite's write lock is not). With none, it opens one."""
        if getattr(self, '_identity', None) is None:
            if db is None:
                with self.transaction() as own:
                    return self._station_identity(own)
            refuse_a_lost_identity(self.data_dir, db)  # G4b: never a new key over signed records, whoever opened the store
            self._identity = PeerIdentity.load_or_create(self.data_dir)
        return self._identity

    def _revision_record(self, db, layer_id, revision):
        """G2: an instructions revision's record, from its stored snapshot; None for a note's revision or none."""
        row = db.execute('SELECT layers.owner_id, layer_revisions.snapshot, layer_revisions.created FROM layer_revisions '
                         'JOIN layers ON layers.id=layer_revisions.layer_id '
                         'WHERE layer_revisions.layer_id=? AND layer_revisions.revision=?', (layer_id, revision)).fetchone()
        snapshot = json.loads(row['snapshot']) if row else {}
        if snapshot.get('kind') != 'instructions':  # the revision's own kind, never the layer's current draft (S3)
            return None
        return {'kind': 'instructions-revision', 'station': self._station_identity(db).peer_id, 'layer_id': layer_id,
                'revision': revision, 'owner_id': row['owner_id'], 'title': snapshot['title'], 'body': snapshot['body'],
                'audience_users': snapshot['audience_users'], 'policy': None, 'created': row['created']}

    def _sign_revision(self, db, layer_id, revision):
        """G2: in the transaction that writes the revision. A note's revision is not signed."""
        record = self._revision_record(db, layer_id, revision)
        if record is not None:
            db.execute('INSERT INTO revision_signatures(layer_id, revision, signature) VALUES(?,?,?)',
                       (layer_id, revision, self._station_identity(db).sign_record(record)))

    def _backfill_revision_signatures(self):
        """G5: at every start, each instructions revision without a signature (written before this release) is
        signed once. One transaction, so two starts at once can't both sign the same revision."""
        with self.transaction() as db:
            unsigned = db.execute("SELECT layer_id, revision FROM layer_revisions "
                                  "WHERE json_extract(snapshot, '$.kind')='instructions' AND NOT EXISTS (SELECT 1 FROM "
                                  "revision_signatures WHERE revision_signatures.layer_id=layer_revisions.layer_id "
                                  "AND revision_signatures.revision=layer_revisions.revision)").fetchall()
            for row in unsigned:
                self._sign_revision(db, row['layer_id'], row['revision'])

    def revision_signed(self, actor, layer_id, revision):
        """G6: {station, record, signature} for the layer's owner. Anyone else, and any revision without a signature
        (a note's, or one that doesn't exist), gets 404, so the route never says whether a layer exists."""
        with self.transaction() as db:
            self._owned_layer(db, actor, layer_id)
            if not 1 <= revision <= 2 ** 63 - 1:  # past SQLite's integers sqlite3 raises OverflowError; no such revision
                raise Problem(404, 'Not found')
            row = require(db.execute('SELECT signature FROM revision_signatures WHERE layer_id=? AND revision=?',
                                     (layer_id, revision)).fetchone())
            return {'station': self._station_identity(db).peer_id, 'record': self._revision_record(db, layer_id, revision),
                    'signature': row['signature']}

    def _grant_record(self, db, grant_id):
        """G12: a grant's record, with exactly RECORD_KEYS['grant'], from its stored row: actions, targets and rooms as
        parsed JSON values, not their stored text. Columns a later step adds stay out, so old signatures keep verifying.
        None for no such grant."""
        row = db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone()
        if row is None:
            return None
        return {'kind': 'grant', 'station': self._station_identity(db).peer_id, 'id': row['id'],
                'issuer_id': row['issuer_id'], 'grantee_id': row['grantee_id'], 'actions': json.loads(row['actions']),
                'targets': json.loads(row['targets']), 'rooms': json.loads(row['rooms']), 'expires': row['expires'],
                'budget': row['budget'], 'depth': row['depth'], 'confirm': row['confirm'], 'parent_id': row['parent_id'],
                'charter_layer_id': row['charter_layer_id'], 'charter_revision': row['charter_revision'],
                'follow': row['follow'], 'created': row['created']}

    def _sign_grant(self, db, grant_id):
        """G12: in the transaction that inserts the grant. The record is built from the stored row, the one grant_signed
        serves, so what was signed and what is served can't drift apart."""
        db.execute('UPDATE grants SET signature=? WHERE id=?',
                   (self._station_identity(db).sign_record(self._grant_record(db, grant_id)), grant_id))

    def _revocation_record(self, db, grant_id):
        """G12: a revocation's record, with exactly RECORD_KEYS['grant-revocation']; None while the grant is in force."""
        row = db.execute('SELECT id, revoked, revoked_by, revoke_reason FROM grants WHERE id=?', (grant_id,)).fetchone()
        if row is None or row['revoked'] is None:
            return None
        return {'kind': 'grant-revocation', 'station': self._station_identity(db).peer_id, 'grant': row['id'],
                'revoked': row['revoked'], 'revoked_by': row['revoked_by'], 'reason': row['revoke_reason']}

    def _sign_revocation(self, db, grant_id):
        """G12: in the transaction that revokes, or at the next start for a revocation the restore reconcile wrote."""
        db.execute('UPDATE grants SET revocation_signature=? WHERE id=?',
                   (self._station_identity(db).sign_record(self._revocation_record(db, grant_id)), grant_id))

    def _backfill_revocation_signatures(self):
        """G12: at every signing start, each revocation without a signature is signed once. Only the restore reconcile
        writes one (G13): it works on a staged file and holds no key. With none to sign, the identity is never touched,
        so a new station's first card still names its host (G4)."""
        with self.transaction() as db:
            for row in db.execute('SELECT id FROM grants WHERE revoked IS NOT NULL AND revocation_signature IS NULL '
                                  'ORDER BY id').fetchall():
                self._sign_revocation(db, row['id'])

    def grant_signed(self, actor, grant_id):
        """G12: GET /api/grants/{id}/signed, {station, record, signature}, plus revocation: {record, signature} once it
        is revoked, for anyone G11 shows the grant to; anyone else, and an unknown id, gets 404."""
        with self.transaction() as db:
            grant = self._visible_grant(db, actor, grant_id)
            signed = {'station': self._station_identity(db).peer_id, 'record': self._grant_record(db, grant['id']),
                      'signature': grant['signature']}
            if grant['revoked'] is not None:
                signed['revocation'] = {'record': self._revocation_record(db, grant['id']),
                                        'signature': grant['revocation_signature']}
            return signed
