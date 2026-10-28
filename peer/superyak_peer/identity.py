"""Persistent Ed25519 identity, explicit contact cards and canonical envelopes."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, ec
from cryptography.x509.oid import NameOID
from .common import Problem, text, valid_utf8, uid

MAX_ENVELOPE = 6 * 1024 * 1024

def canonical(value):
    try:
        valid_utf8(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise Problem(400, 'Invalid canonical JSON') from None

def parse(raw):
    if isinstance(raw, dict):
        raw = canonical(raw)
    if isinstance(raw, str):
        raw = raw.encode()
    if not isinstance(raw, bytes) or len(raw) > MAX_ENVELOPE:
        raise Problem(413, 'Envelope too large')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('Duplicate key')
            result[k] = v
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        canonical(value)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, RecursionError, UnicodeError):
        raise Problem(400, 'Invalid envelope JSON') from None

def validate_card(card):
    try:
        if set(card) != {'version', 'peer_id', 'signing_key', 'certificate', 'fingerprint', 'endpoint', 'participant'} or type(card['version']) is not int or card['version'] != 1:
            raise ValueError()
        endpoint = text(card['endpoint'], 'endpoint', 2048)
        url = urlsplit(endpoint)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or url.query or url.path or url.port == 0 or any(c.isspace() for c in endpoint):
            raise ValueError()
        key = base64.b64decode(card['signing_key'], validate=True)
        ed25519.Ed25519PublicKey.from_public_bytes(key)
        if hashlib.sha256(key).hexdigest() != card['peer_id']:
            raise ValueError()
        cert = x509.load_pem_x509_certificate(text(card['certificate'], 'certificate', 16384).encode())
        if cert.fingerprint(hashes.SHA256()).hex() != card['fingerprint']:
            raise ValueError()
        participant = card['participant']
        if set(participant) != {'id', 'name'} or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', participant['id']):
            raise ValueError()
        text(participant['name'], 'participant name')
        canonical(card)
        return card
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Problem(400, 'Invalid peer card') from None

def pairing_code(card):
    """fix:pairing-code (federation-pull spec §2): the first 32 hex of the whole card's canonical SHA-256. A person
    types it, read off the exporting machine's own screen, so the card in hand is compared with that screen."""
    return hashlib.sha256(canonical(validate_card(card))).hexdigest()[:32]

def show_code(code):
    return ' '.join(code[i:i + 4] for i in range(0, len(code), 4))

def typed_code(typed):
    """A typed code without its spaces and hyphens, lowercased: 32 ASCII hex, or None."""
    if not isinstance(typed, str):
        return None
    code = re.sub(r'[\s-]', '', typed).lower()
    return code if re.fullmatch(r'[0-9a-f]{32}', code, re.ASCII) else None

# Spec A step 3 (G3, G12): a signed record has exactly its kind's keys and names its station, so no record passes
# as another kind, as a federation envelope (which has no record kind), or as another station's.
RECORD_KEYS = {
    'instructions-revision': frozenset({'kind', 'station', 'layer_id', 'revision', 'owner_id', 'title', 'body',
                                        'audience_users', 'policy', 'created'}),
    'grant': frozenset({'kind', 'station', 'id', 'issuer_id', 'grantee_id', 'actions', 'targets', 'rooms', 'expires',
                        'budget', 'depth', 'confirm', 'parent_id', 'charter_layer_id', 'charter_revision', 'follow',
                        'created'}),
    'grant-revocation': frozenset({'kind', 'station', 'grant', 'revoked', 'revoked_by', 'reason'}),
}

def _record_shape_ok(record):
    return (isinstance(record, dict) and isinstance(record.get('kind'), str)
            and RECORD_KEYS.get(record['kind']) == set(record))

class PeerIdentity:
    def __init__(self, path, record):
        self.data_dir = path
        self.key = serialization.load_pem_private_key(record['signing_private'].encode(), password=None)
        self.public_key = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.peer_id = hashlib.sha256(self.public_key).hexdigest()
        self.certificate = record['certificate']
        self.cert_path, self.key_path = path / 'peer-cert.pem', path / 'peer-key.pem'
        for target, value in [(self.cert_path, self.certificate), (self.key_path, record['tls_private'])]:
            if target.is_symlink():
                raise ValueError('Symlinked identity is not allowed')
            if not target.exists():
                self._write(target, value)
            elif target.read_text() != value:
                raise ValueError('Identity TLS files differ from saved identity')

    @staticmethod
    def _write(path, value):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())

    @classmethod
    def load_or_create(cls, data_dir, *, hosts=('localhost', '127.0.0.1')):
        path = Path(data_dir)
        if path.is_symlink():
            raise ValueError('Symlinked identity is not allowed')
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = path / 'identity.json'
        if target.is_symlink():
            raise ValueError('Symlinked identity is not allowed')
        if not target.exists():
            key, tls = ed25519.Ed25519PrivateKey.generate(), ec.generate_private_key(ec.SECP256R1())
            sans = []
            for host in hosts:
                try:
                    sans.append(x509.IPAddress(ipaddress.ip_address(host)))
                except ValueError:
                    sans.append(x509.DNSName(host))
            now = datetime.now(timezone.utc)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Superyak peer')])
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(tls.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                    .not_valid_after(now + timedelta(days=365)).add_extension(x509.SubjectAlternativeName(sans), critical=False)
                    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(tls, hashes.SHA256()))
            pem = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
            record = {'signing_private': pem(key), 'tls_private': pem(tls), 'certificate': cert.public_bytes(serialization.Encoding.PEM).decode()}
            cls._write(target, json.dumps(record))
        return cls(path, json.loads(target.read_text()))

    def card(self, endpoint, participant):
        cert = x509.load_pem_x509_certificate(self.certificate.encode())
        return validate_card({'version': 1, 'peer_id': self.peer_id, 'signing_key': base64.b64encode(self.public_key).decode(),
                              'certificate': self.certificate, 'fingerprint': cert.fingerprint(hashes.SHA256()).hex(),
                              'endpoint': endpoint, 'participant': {k: participant[k] for k in ('id', 'name')}})

    def sign_record(self, record):
        """G3: this station's signature over one of its own records (RECORD_KEYS), base64."""
        if not _record_shape_ok(record) or record['station'] != self.peer_id:
            raise ValueError('Not a record this station signs')
        return base64.b64encode(self.key.sign(canonical(record))).decode()

    def envelope(self, *, destination, actor, resource_id, revision, action, recipients, payload, event_id=None):
        value = {'version': 1, 'event_id': event_id or uid(), 'origin': self.peer_id, 'destination': destination,
                 'actor': {'peer': self.peer_id, 'id': actor}, 'resource_id': resource_id, 'revision': revision,
                 'action': action, 'recipients': recipients, 'payload': payload,
                 'payload_digest': hashlib.sha256(canonical(payload)).hexdigest()}
        value['signature'] = base64.b64encode(self.key.sign(canonical(value))).decode()
        return value

def verify_envelope(raw, card, destination):
    value = parse(raw)
    try:
        if set(value) != {'version','event_id','origin','destination','actor','resource_id','revision','action','recipients','payload','payload_digest','signature'}:
            raise ValueError()
        if type(value['version']) is not int or value['version'] != 1 or value['origin'] != card['peer_id'] or value['destination'] != destination:
            raise ValueError()
        if set(value['actor']) != {'peer', 'id'} or value['actor']['peer'] != value['origin']:
            raise ValueError()
        for field in ('event_id', 'resource_id'):
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value[field]):
                raise ValueError()
        text(value['actor']['id'], 'actor', 64)
        if type(value['revision']) is not int or not 1 <= value['revision'] <= 2**53:
            raise ValueError()
        recipients = value['recipients']
        if not isinstance(recipients, list) or not 1 <= len(recipients) <= 100 or len(set(recipients)) != len(recipients):
            raise ValueError()
        for recipient in recipients:
            text(recipient, 'recipient', 64)
        if not isinstance(value['payload'], dict) or hashlib.sha256(canonical(value['payload'])).hexdigest() != value['payload_digest']:
            raise ValueError()
        unsigned = {k:v for k,v in value.items() if k != 'signature'}
        ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(card['signing_key'], validate=True)).verify(base64.b64decode(value['signature'], validate=True), canonical(unsigned))
        return value
    except (ValueError, TypeError, KeyError, InvalidSignature):
        raise Problem(403, 'Peer authentication failed') from None

def verify_record(card, record, signature):
    """G3: True only for a valid card, a record with exactly its kind's keys that names the card's station, and a
    signature over its canonical JSON by the card's key. Anything else is False."""
    try:
        validate_card(card)
        if not _record_shape_ok(record) or record['station'] != card['peer_id']:
            return False
        key = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(card['signing_key'], validate=True))
        key.verify(base64.b64decode(signature, validate=True), canonical(record))
        return True
    except Exception:  # noqa: BLE001 - a verifier answers False and never raises (G3)
        return False
