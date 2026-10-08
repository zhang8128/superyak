"""Which instruction layers bind a ship, the prompt blocks that carry them, and the caps that keep them in one
command-line argument (spec A, sections 1 and 4). Build step 2: only the ship's owner's own active instruction layers
bind it. Grants (step 3) and the charter (step 4) add to this rule; they never replace it."""
import json
from .common import Problem, require, uid, encode
from .ships import safe_line

PREAMBLE = ('These instructions were signed by people and bind this ship. If two of them conflict, do not choose: '
            'ask in the room.')
MAX_LAYERS, MAX_BYTES = 10, 48000
DRAFTS_PER_HOUR = 10
WAITING_DRAFTS, WAITING_DAYS = 20, 7  # a rolling window: layers cannot be deleted, so a lifetime cap could lock a ship out


def defuse_body(text):
    return '\n'.join(' ' + line if line.startswith(('===', "Instructions '")) else line for line in str(text).splitlines())


def render_one(layer, station):
    return (f'=== Instructions: {safe_line(layer["title"], 200)} · revision {layer["revision"]} · signed by '
            f'{safe_line(layer["signer_name"])} on station {str(station)[:12]} ===\n{defuse_body(layer["body"])}')


def render_blocks(layers, station):
    return PREAMBLE + '\n\n' + '\n\n'.join(render_one(l, station) for l in layers) if layers else ''


class Instructions:
    def _layers_for(self, db, pairs):
        """The layers at exactly these (layer_id, revision) pairs, as _binding_layers returns them."""
        found = []
        for layer_id, revision in pairs:
            row = db.execute('SELECT layer_revisions.snapshot, layer_revisions.created, layers.owner_id, users.name AS signer '
                             'FROM layer_revisions JOIN layers ON layers.id=layer_revisions.layer_id '
                             'JOIN users ON users.id=layers.owner_id WHERE layer_revisions.layer_id=? AND layer_revisions.revision=?',
                             (layer_id, revision)).fetchone()
            if row:
                snap = json.loads(row['snapshot'])
                found.append({'layer_id': layer_id, 'revision': revision, 'title': snap['title'], 'body': snap['body'],
                              'signer_id': row['owner_id'], 'signer_name': row['signer'], 'created': row['created']})
        return sorted(found, key=lambda l: (l['created'], l['layer_id']))

    def ship_instructions(self, actor, station):
        with self.transaction() as db:
            layers = self._binding_layers(db, actor)
        return {'instructions': [[l['layer_id'], l['revision']] for l in layers],
                'layers': [{'layer_id': l['layer_id'], 'revision': l['revision'], 'title': safe_line(l['title'], 200),
                            'signer_name': safe_line(l['signer_name']), 'block': render_one(l, station)} for l in layers],
                'blocks': render_blocks(layers, station)}

    def ship_draft(self, actor, data):
        """A ship drafts an instructions layer in its owner's name, addressed to itself. Only the owner can activate it."""
        if set(data) - {'title', 'body'}:
            raise Problem(400, 'A ship draft takes only a title and a body')
        with self.transaction() as db:
            ship = require(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone())
            if ship['kind'] != 'ship' or not ship['owner_id']:
                raise Problem(403, 'Only a docked ship with an owner can draft instructions')
            owner, now = ship['owner_id'], self.clock()
            recent = waiting = 0
            for row in db.execute('SELECT draft, NOT EXISTS (SELECT 1 FROM layer_revisions WHERE layer_id=layers.id) AS never '
                                  'FROM layers WHERE owner_id=?', (owner,)):
                d = json.loads(row['draft'])
                if d.get('drafted_by') == actor:
                    recent += d.get('drafted_at', 0) > now - 3600
                    waiting += bool(row['never']) and d.get('drafted_at', 0) > now - WAITING_DAYS * 86400
            if waiting >= WAITING_DRAFTS:
                raise Problem(429, 'A ship may have at most 20 drafts from the last 7 days that were never activated')
            if recent >= DRAFTS_PER_HOUR:
                raise Problem(429, 'A ship may draft 10 instruction layers an hour')
            draft = self._draft(db, owner, {'kind': 'instructions', 'title': data.get('title', 'Untitled'),
                                            'body': data.get('body', ''), 'audience_users': [actor]})
            draft['drafted_by'], draft['drafted_at'] = actor, now
            key = uid()
            db.execute('INSERT INTO layers(id,owner_id,version,draft) VALUES(?,?,1,?)', (key, owner, encode(draft)))
            return {'id': key, 'title': draft['title'], 'version': 1, 'state': 'draft', 'drafted_by': actor}

    def _binding_layers(self, db, ship_id, replace=None):
        ship = require(db.execute('SELECT * FROM users WHERE id=?', (ship_id,)).fetchone())
        if ship['kind'] != 'ship' or not ship['owner_id']:
            return []
        signer = db.execute('SELECT name FROM users WHERE id=?', (ship['owner_id'],)).fetchone()['name']
        rows = [(r['layer_id'], r['revision'], json.loads(r['snapshot']), r['created']) for r in db.execute(
            'SELECT layers.id AS layer_id, layer_revisions.revision, layer_revisions.snapshot, layer_revisions.created '
            'FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision=layer_revisions.revision '
            'WHERE layers.owner_id=?', (ship['owner_id'],))]
        if replace is not None:
            rows = [r for r in rows if r[0] != replace['layer_id']] + [(replace['layer_id'], replace.get('revision', 0), replace['snapshot'], replace['created'])]
        found = [{'layer_id': lid, 'revision': rev, 'title': snap['title'], 'body': snap['body'], 'signer_id': ship['owner_id'],
                  'signer_name': signer, 'created': created}
                 for lid, rev, snap, created in rows if snap.get('kind') == 'instructions' and ship_id in snap.get('audience_users', [])]
        return sorted(found, key=lambda l: (l['created'], l['layer_id']))

    def _check_instruction_caps(self, db, actor, key, snapshot):
        if not snapshot['audience_users']:
            raise Problem(400, 'Choose at least one ship for these instructions')
        for ship_id in snapshot['audience_users']:
            row = db.execute('SELECT owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
            if not row or row['owner_id'] != actor:
                continue  # it does not bind a ship the activator does not own, so it cannot crowd that ship out
            layers = self._binding_layers(db, ship_id, replace={'layer_id': key, 'snapshot': snapshot, 'created': self.clock(), 'revision': 0})
            if len(layers) > MAX_LAYERS or len(render_blocks(layers, 'x' * 12).encode()) > MAX_BYTES:
                raise Problem(409, 'That ship would have more than 10 instruction layers or 48,000 bytes of them')
