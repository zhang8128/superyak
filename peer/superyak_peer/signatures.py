"""Station signatures (spec A step 3, merge 3a; 2026-10-15-grants-step3-design.md G1-G6): the station's Ed25519
key signs each instructions revision, so a revision can be checked against the station's card. Merge 3b adds grants
and revocations here."""
import json
from .common import Problem, require
from .identity import PeerIdentity

SIGNATURE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(layer_id, revision));
'''


class Signatures:
    def _load_station_identity(self):
        """G4: at startup, the identity file federation uses is loaded if it exists (a symlink too, which
        load_or_create refuses), and a store that can't load it doesn't start. A missing one waits for the first
        signature, so a new station's first `card --endpoint` still names its host (plan review M1)."""
        path = self.data_dir / 'identity.json'
        if path.exists() or path.is_symlink():
            try:
                self._identity = PeerIdentity.load_or_create(self.data_dir)
            except Exception as error:
                raise ValueError(f'The station identity {path} could not be loaded ({type(error).__name__}); '
                                 'the station will not start until it is restored') from error

    def _station_identity(self):
        """The identity, created if missing. Only a signing transaction creates it: that holds the dispatch gate, so
        two processes can't both create it, and a failed create rolls the signed write back (G4)."""
        if getattr(self, '_identity', None) is None:
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
        return {'kind': 'instructions-revision', 'station': self._station_identity().peer_id, 'layer_id': layer_id,
                'revision': revision, 'owner_id': row['owner_id'], 'title': snapshot['title'], 'body': snapshot['body'],
                'audience_users': snapshot['audience_users'], 'policy': None, 'created': row['created']}

    def _sign_revision(self, db, layer_id, revision):
        """G2: in the transaction that writes the revision. A note's revision is not signed."""
        record = self._revision_record(db, layer_id, revision)
        if record is not None:
            db.execute('INSERT INTO revision_signatures VALUES(?,?,?)',
                       (layer_id, revision, self._station_identity().sign_record(record)))

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
            return {'station': self._station_identity().peer_id, 'record': self._revision_record(db, layer_id, revision),
                    'signature': row['signature']}
