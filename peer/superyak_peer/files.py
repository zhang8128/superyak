"""Bounded immutable attachments; filenames never select a path."""
import base64
import binascii
import hashlib
import re
from .common import Problem, uid, require, text

MAX_FILE = 4 * 1024 * 1024

class Files:
    def upload_file(self, actor, name, media_type, content_base64):
        validated = validate_file(name, media_type, content_base64)
        content = validated['content']
        key, digest = uid(), hashlib.sha256(content).hexdigest()
        with self.transaction() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?)', (key, actor, name, media_type, digest, len(content), content))
        return {'id': key, 'name': name, 'media_type': media_type, 'digest': digest, 'size': len(content)}

    def list_files(self, actor):
        with self.transaction() as db:
            return [dict(r) for r in db.execute('SELECT id,name,media_type,digest,size FROM files WHERE owner_id=? ORDER BY id', (actor,))]

    def download_file(self, actor, key, *, layer_id=None, public=False):
        text(key, 'file ID', 100)
        if layer_id and ':' in layer_id:
            if public or actor is None:
                raise Problem(404, 'Not found')
            return self.remote_file(actor, layer_id, key)
        with self.transaction() as db:
            if layer_id:
                layer = self._active_layer(db, layer_id, actor, public=public)
                if key not in layer['attachment_ids']:
                    raise Problem(404, 'Not found')
                row = require(db.execute('SELECT * FROM files WHERE id=?', (key,)).fetchone())
            else:
                if public:
                    raise Problem(404, 'Not found')
                row = require(db.execute('SELECT * FROM files WHERE id=? AND owner_id=?', (key, actor)).fetchone())
            return dict(row)


def validate_file(name, media_type, content_base64):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}', name) or '..' in name:
        raise Problem(400, 'Use a plain filename without directories')
    if not isinstance(content_base64, str):
        raise Problem(400, 'Invalid attachment encoding')
    if len(content_base64) > 4 * ((MAX_FILE + 2) // 3):
        raise Problem(413, 'Attachment exceeds 4 MiB')
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise Problem(400, 'Invalid attachment encoding') from None
    if len(content) > MAX_FILE:
        raise Problem(413, 'Attachment exceeds 4 MiB')
    if not isinstance(media_type, str):
        raise Problem(400, 'Invalid file type')
    signatures = {'application/pdf': b'%PDF-', 'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff', 'image/gif': b'GIF8'}
    if media_type == 'text/plain':
        try:
            content.decode('utf-8')
        except UnicodeDecodeError:
            raise Problem(400, 'Text must be UTF-8') from None
    elif media_type not in signatures or not content.startswith(signatures[media_type]):
        raise Problem(400, 'Unsupported file type or invalid signature')
    return {'content':content, 'digest':hashlib.sha256(content).hexdigest(), 'size':len(content)}
