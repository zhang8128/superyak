"""Which instruction layers bind a ship, the prompt blocks that carry them, and the caps that keep them in one
command-line argument (spec A, sections 1 and 4). Build step 2: only the ship's owner's own active instruction layers
bind it. Grants (step 3) and the charter (step 4) add to this rule; they never replace it."""
import json
from .common import Problem, require
from .ships import safe_line

PREAMBLE = ('These instructions were signed by people and bind this ship. If two of them conflict, do not choose: '
            'ask in the room.')
MAX_LAYERS, MAX_BYTES = 10, 48000


def defuse_body(text):
    return '\n'.join(' ' + line if line.startswith(('===', "Instructions '")) else line for line in str(text).splitlines())


def render_one(layer, station):
    return (f'=== Instructions: {safe_line(layer["title"], 200)} · revision {layer["revision"]} · signed by '
            f'{safe_line(layer["signer_name"])} on station {str(station)[:12]} ===\n{defuse_body(layer["body"])}')


def render_blocks(layers, station):
    return PREAMBLE + '\n\n' + '\n\n'.join(render_one(l, station) for l in layers) if layers else ''


class Instructions:
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
